"""
Семантический маппинг колонок CSV → ID нормативов ГОСТа через GigaChat.
Результат кэшируется в SQLite: если та же лаборатория пришлёт файл завтра —
GigaChat не вызывается, маппинг берётся из кэша.
"""
import json
import re
from typing import Any, Dict, List

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

from logger import logger
from storage import get_cached_mapping, save_mapping_cache


MAPPING_PROMPT = """
Ты — эксперт по стандартизации кофейной продукции.
Тебе дают список колонок из протокола лабораторных испытаний и список нормативов ГОСТ 32775—2014.

Задача: сопоставить каждую колонку протокола с ID норматива, к которому она относится по СМЫСЛУ.

Правила:
- Названия колонок могут быть на русском или английском, в сокращённой форме, с единицами измерения.
- Ориентируйся на смысл, а не на точное совпадение строк.
- Если для колонки нет подходящего норматива — верни null.
- НЕ выдумывай ID, используй только те, что даны в списке нормативов.

Ответ верни СТРОГО в формате JSON без markdown-обёрток:
{"колонка_1": "id_норматива_или_null", "колонка_2": "...", ...}
"""


def _clean_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    for start_c, end_c in [("{", "}"), ("[", "]")]:
        s, e = text.find(start_c), text.rfind(end_c)
        if s != -1 and e > s:
            return text[s:e + 1]
    return text


class SemanticMapper:
    def __init__(self, client: GigaChat, rules: List[Dict[str, Any]]):
        self.client = client
        # Компактный справочник: ID + имя + алиасы
        self.rules_digest = [
            {
                "id": r["id"],
                "name": r.get("parameter"),
                "aliases": r.get("aliases", []),
                "unit": r.get("unit"),
            }
            for r in rules
            if "value" in r and "operator" in r
        ]
        self.valid_ids = {r["id"] for r in self.rules_digest}

    def map_columns(self, columns: List[str]) -> Dict[str, str]:
        """
        Возвращает {колонка: rule_id}. Значение None → не включаем в результат.
        """
        # 1) Проверяем кэш
        cached = get_cached_mapping(columns)
        if cached is not None:
            logger.info("Маппинг взят из кэша для колонок: %s", columns)
            return cached

        # 2) Спрашиваем GigaChat
        logger.info("Запрос семантического маппинга к GigaChat для колонок: %s", columns)
        user_content = json.dumps(
            {"columns": columns, "rules": self.rules_digest},
            ensure_ascii=False,
            indent=2,
        )

        mapping: Dict[str, str] = {}
        try:
            response = self.client.chat(Chat(messages=[
                Messages(role=MessagesRole.SYSTEM, content=MAPPING_PROMPT.strip()),
                Messages(role=MessagesRole.USER, content=user_content),
            ]))
            raw = response.choices[0].message.content
            cleaned = _clean_json(raw)
            parsed = json.loads(cleaned)

            for col, rid in parsed.items():
                if rid and rid in self.valid_ids:
                    mapping[col] = rid
            logger.info("GigaChat вернул маппинг: %s", mapping)

        except Exception as e:
            logger.exception("Ошибка семантического маппинга: %s", e)
            # Fallback: пустой маппинг, сработает fuzzy-поиск в classifier

        # 3) Сохраняем в кэш
        if mapping:
            save_mapping_cache(columns, mapping)

        return mapping