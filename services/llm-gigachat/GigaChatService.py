import io
import json
from typing import Any, Dict, List
from pathlib import Path

import pandas as pd
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from fastapi import UploadFile

from config import settings
from logger import logger
from classifier import (
    build_alias_index,
    analyze_row,
    overall_status,
    format_norm,
    STATUS_COLORS,
    STATUS_LABELS,
)
from storage import init_db, save_protocol
from mapper import SemanticMapper


REPORT_PROMPT = """
Ты — эксперт по контролю качества кофейного сырья.
Тебе дают СВОДКУ результатов автоматической проверки партии протоколов (не все данные, а агрегат).

Твоя задача — написать краткий, деловой текстовый отчёт для оператора на русском языке.

Правила:
- Не выдумывай параметры и номера строк, которых нет в данных.
- Не меняй статусы (ok/warning/fail) — они уже определены.
- Если есть забракованные партии (defect) — упомяни, сколько их и какие основные причины (по параметрам).
- Если есть warning — упомяни как «требует внимания».
- Опирайся на конкретные номера строк (row_index) из sample_problem_rows.
- Пиши 4–8 предложений. Без markdown. Без списков. Сплошной текст.
- Не принимай решений о переработке/списании — это за комиссией.
"""


EXPLAIN_PROMPT = """
Ты — эксперт по технологии производства кофе и стандартизации.
Пользователь — оператор производства. Он видит отклонение параметра от ГОСТа и хочет понять,
ПОЧЕМУ этот параметр важен и КАК отклонение влияет на качество/безопасность продукции.

Правила:
- Отвечай 3–5 предложениями.
- Объясняй простым языком, без излишней академичности.
- Опирайся ТОЛЬКО на предоставленный текст пункта ГОСТа и фактическое значение.
- Не выдумывай номера пунктов и цифры.
- Не предлагай решений о переработке/списании — это за комиссией.
- Без markdown, без списков. Сплошной текст.
"""


class GigaChatService:
    def __init__(self):
        rules_path = Path(__file__).parent / settings.rules_path

        self.client = GigaChat(
            base_url=settings.giga_base_url,
            credentials=settings.giga_password,
            scope=settings.giga_scope,
            ca_bundle_file=settings.ca_bundle_file,
            model=settings.giga_model,
        )

        self.rules = self._load_rules(rules_path)
        self.rules_by_id = {r["id"]: r for r in self.rules}
        self.alias_index = build_alias_index(self.rules)
        self.mapper = SemanticMapper(self.client, self.rules)

        init_db()
        logger.info(
            "GigaChatService инициализирован: правил=%d, алиасов=%d",
            len(self.rules), len(self.alias_index),
        )

    @staticmethod
    @staticmethod
    def _load_rules(path: Path) -> List[Dict[str, Any]]:
        """
        Загружает нормативы из XLSX или JSON — по расширению файла.
        На выходе всегда единый список dict с полями:
        id, standard, clause, category, parameter, aliases,
        value, operator, unit, method_ref, text.
        """
        if not path.exists():
            logger.error("Файл нормативов не найден: %s", path)
            return []

        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return GigaChatService._load_rules_from_excel(path)
        return GigaChatService._load_rules_from_json(path)

    @staticmethod
    def _load_rules_from_json(path: Path) -> List[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                rules = json.load(f)
            logger.info("Загружено нормативов (JSON): %d", len(rules))
            return rules
        except Exception as e:
            logger.exception("Не удалось загрузить JSON-правила: %s", e)
            return []

    @staticmethod
    def _load_rules_from_excel(path: Path) -> List[Dict[str, Any]]:
        """
        Читает XLSX с колонками:
        id, standard, clause, category, parameter, aliases, operator,
        value_min, value_max, value_text, unit, method_ref, text

        Восстанавливает исходную структуру value в зависимости от operator.
        """
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except Exception as e:
            logger.exception("Не удалось прочитать XLSX: %s", e)
            return []

        def _is_empty(v) -> bool:
            return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""

        def _to_float(v):
            if _is_empty(v):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        rules: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            operator = str(row.get("operator", "")).strip()

            # Восстанавливаем value в зависимости от оператора
            if operator == "не более":
                value = _to_float(row.get("value_max"))
            elif operator == "не менее":
                value = _to_float(row.get("value_min"))
            elif operator in ("от ... до", "от ... до, включительно"):
                vmin = _to_float(row.get("value_min"))
                vmax = _to_float(row.get("value_max"))
                value = {"min": vmin, "max": vmax}
            else:
                value = None if _is_empty(row.get("value_text")) else str(row.get("value_text"))

            aliases_raw = row.get("aliases")
            if _is_empty(aliases_raw):
                aliases = []
            else:
                aliases = [a.strip() for a in str(aliases_raw).split(";") if a.strip()]

            rule = {
                "id": row.get("id"),
                "standard": row.get("standard"),
                "clause": row.get("clause"),
                "category": row.get("category"),
                "parameter": row.get("parameter"),
                "aliases": aliases,
                "value": value,
                "operator": operator,
                "unit": None if _is_empty(row.get("unit")) else row.get("unit"),
                "method_ref": None if _is_empty(row.get("method_ref")) else row.get("method_ref"),
                "text": row.get("text"),
            }
            rules.append(rule)

        logger.info("Загружено нормативов (XLSX): %d", len(rules))
        return rules

    # ---------- LLM: сводный отчёт ----------

    def _build_summary(
        self,
        filename: str,
        file_overall: str,
        rows_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        total = len(rows_results)
        defect_rows = [r for r in rows_results if r["overall_status"] == "defect"]
        warning_rows = [r for r in rows_results if r["overall_status"] == "warning"]
        good_rows = [r for r in rows_results if r["overall_status"] == "good"]

        problem_rows = defect_rows + warning_rows
        sample = []
        for r in problem_rows[:10]:
            problems = [
                {
                    "param": p["parameter"],
                    "actual": p["actual"],
                    "norm": p["norm"],
                    "status": p["status"],
                    "clause": p.get("clause"),
                }
                for p in r["parameters"]
                if p["status"] in ("fail", "warning")
            ]
            sample.append({
                "row_index": r["row_index"],
                "status": r["overall_status"],
                "problems": problems,
            })

        return {
            "filename": filename,
            "file_overall": file_overall,
            "total_rows": total,
            "defect_count": len(defect_rows),
            "warning_count": len(warning_rows),
            "good_count": len(good_rows),
            "sample_problem_rows": sample,
            "truncated": len(problem_rows) > 10,
        }

    def _generate_report_text(
        self,
        filename: str,
        file_overall: str,
        rows_results: List[Dict[str, Any]],
    ) -> str:
        summary = self._build_summary(filename, file_overall, rows_results)
        user_content = json.dumps(summary, ensure_ascii=False, indent=2)

        try:
            response = self.client.chat(Chat(messages=[
                Messages(role=MessagesRole.SYSTEM, content=REPORT_PROMPT.strip()),
                Messages(role=MessagesRole.USER, content=user_content),
            ]))
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.exception("GigaChat недоступен для отчёта: %s", e)
            return self._fallback_report(filename, file_overall, rows_results)

    @staticmethod
    def _fallback_report(
        filename: str,
        file_overall: str,
        rows_results: List[Dict[str, Any]],
    ) -> str:
        total = len(rows_results)
        defect = sum(1 for r in rows_results if r["overall_status"] == "defect")
        warning = sum(1 for r in rows_results if r["overall_status"] == "warning")
        good = total - defect - warning

        lines = [
            f"Протокол: {filename}.",
            f"Всего партий: {total}. Годных: {good}. Требуют внимания: {warning}. Забраковано: {defect}.",
        ]

        for r in rows_results:
            if r["overall_status"] == "good":
                continue
            bad = [p for p in r["parameters"] if p["status"] in ("fail", "warning")]
            if not bad:
                continue
            parts = ", ".join(
                f"{p['parameter']} — факт {p['actual']} {p.get('unit') or ''}, "
                f"норма {p['norm']} ({p['status']})"
                for p in bad
            )
            lines.append(f"Партия №{r['row_index']}: {parts}.")

        return " ".join(lines)

    # ---------- RAG: объяснение причин брака ----------

    def explain_deviation(self, rule_id: str, actual: Any) -> Dict[str, Any]:
        """
        RAG-объяснение: почему отклонение этого параметра критично.
        Возвращает текст объяснения + ссылку на пункт ГОСТа.
        """
        rule = self.rules_by_id.get(rule_id)
        if not rule:
            return {"error": f"Норматив {rule_id} не найден"}

        context = {
            "parameter": rule.get("parameter"),
            "clause": rule.get("clause"),
            "standard": rule.get("standard"),
            "category": rule.get("category"),
            "norm": format_norm(rule),
            "gost_text": rule.get("text"),
            "actual_value": actual,
            "unit": rule.get("unit"),
            "method_ref": rule.get("method_ref"),
        }

        user_content = json.dumps(context, ensure_ascii=False, indent=2)

        try:
            response = self.client.chat(Chat(messages=[
                Messages(role=MessagesRole.SYSTEM, content=EXPLAIN_PROMPT.strip()),
                Messages(role=MessagesRole.USER, content=user_content),
            ]))
            explanation = response.choices[0].message.content.strip()
        except Exception as e:
            logger.exception("GigaChat недоступен для объяснения: %s", e)
            explanation = (
                f"Параметр «{rule.get('parameter')}» вышел за пределы нормы. "
                f"Согласно {rule.get('standard')} ({rule.get('clause')}): {rule.get('text')}"
            )

        return {
            "rule_id": rule_id,
            "parameter": rule.get("parameter"),
            "clause": rule.get("clause"),
            "standard": rule.get("standard"),
            "gost_text": rule.get("text"),
            "actual_value": actual,
            "explanation": explanation,
        }

    # ---------- Пайплайн ----------

    def _read_dataframe(self, filename: str, content: bytes) -> pd.DataFrame:
        fname = (filename or "").lower()
        if fname.endswith(".csv"):
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp1251", errors="replace")
            try:
                df = pd.read_csv(io.StringIO(text), sep=None, engine="python")
            except Exception:
                df = pd.read_csv(io.StringIO(text))
        elif fname.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise ValueError("Поддерживаются только .csv и .xlsx")

        # Убираем BOM и пробелы из имён колонок
        df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
        return df

    def _analyze_dataframe(
        self,
        df: pd.DataFrame,
        mapping: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        rows_results: List[Dict[str, Any]] = []

        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            param_results = analyze_row(
                row_dict,
                mapping,
                self.rules_by_id,
                self.alias_index,
                row_index=idx + 1,
            )

            if not param_results:
                continue

            row_status = overall_status(param_results)
            rows_results.append({
                "row_index": idx + 1,
                "overall_status": row_status,
                "color": STATUS_COLORS[row_status],
                "label": STATUS_LABELS[row_status],
                "parameters": param_results,
            })

        return rows_results

    def process_file_content(self, filename: str, content: bytes) -> Dict[str, Any]:
        try:
            df = self._read_dataframe(filename, content)
        except Exception as e:
            logger.exception("Ошибка чтения файла: %s", e)
            return {"error": str(e)}

        columns = df.columns.tolist()
        logger.info("Файл %s: строк=%d, колонок=%d", filename, len(df), len(columns))

        # GigaChat #1: семантический маппинг колонок (кэшируется)
        mapping = self.mapper.map_columns(columns)

        # Python: детерминированная проверка
        rows_results = self._analyze_dataframe(df, mapping)

        if not rows_results:
            return {
                "error": "Не удалось сопоставить ни один параметр с нормативами ГОСТ",
                "columns": columns,
                "mapping": mapping,
            }

        all_params = [p for r in rows_results for p in r["parameters"]]
        file_overall = overall_status(all_params)

        # GigaChat #2: сводный отчёт
        report_text = self._generate_report_text(filename, file_overall, rows_results)

        protocol_id = save_protocol(filename, file_overall, rows_results, report_text)

        return {
            "protocol_id": protocol_id,
            "filename": filename,
            "overall_status": file_overall,
            "color": STATUS_COLORS[file_overall],
            "label": STATUS_LABELS[file_overall],
            "total_rows": len(rows_results),
            "rows": rows_results,
            "mapping": mapping,
            "report_text": report_text,
        }

    async def upload_document(self, file: UploadFile) -> Dict[str, Any]:
        import asyncio
        content = await file.read()
        filename = file.filename or ""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.process_file_content, filename, content)

    def upload_document_sync(self, file_path: str) -> Dict[str, Any]:
        with open(file_path, "rb") as f:
            content = f.read()
        return self.process_file_content(Path(file_path).name, content)