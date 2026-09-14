"""
Детерминированный классификатор: сравнение чисел с нормативами.
LLM здесь НЕ участвует. Вердикт воспроизводим.
"""
import re
from typing import Any, Dict, List, Optional

from config import settings
from logger import logger


WARNING_TOLERANCE_PERCENT = settings.warning_tolerance_percent

# Эпсилон для компенсации ошибок округления floating point.
# Без него 5.775 при норме 5.5 даёт 5.000000000000001% вместо ровно 5.0%
# и граничное значение уходит в fail вместо warning.
FLOAT_EPSILON = 1e-9

NON_CHECKABLE_IDS = {
    "gost32775-req-003",
    "gost32775-req-004",
    "gost32775-req-005",
    "gost32775-ctrl-001",
    "gost32775-ctrl-002",
    "gost32775-ctrl-003",
    "gost32775-ctrl-004",
}


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = str(name).lower().strip()
    name = re.sub(r"[^\w\s,]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def build_alias_index(rules: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for rule in rules:
        if "value" not in rule or "operator" not in rule:
            continue
        names = [rule.get("parameter", "")] + rule.get("aliases", [])
        for name in names:
            key = normalize_name(name)
            if key:
                index[key] = rule
    return index


def find_rule_fuzzy(param_name: str, alias_index: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    key = normalize_name(param_name)
    if not key:
        return None
    if key in alias_index:
        return alias_index[key]
    for alias, rule in alias_index.items():
        if alias and (alias in key or key in alias):
            return rule
    return None


def parse_number(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            f = float(raw)
            return None if f != f else f  # NaN
        except (ValueError, TypeError):
            return None
    s = str(raw).strip().replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in (".", "-", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def classify_numeric(actual: float, rule: Dict[str, Any]) -> str:
    operator = rule.get("operator", "")
    value = rule.get("value")

    if operator == "не более":
        limit = float(value)
        if actual <= limit:
            return "ok"
        pct = (actual - limit) / limit * 100 if limit > 0 else float("inf")
        if pct <= WARNING_TOLERANCE_PERCENT + FLOAT_EPSILON:
            return "warning"
        return "fail"

    if operator == "не менее":
        limit = float(value)
        if actual >= limit:
            return "ok"
        pct = (limit - actual) / limit * 100 if limit > 0 else float("inf")
        if pct <= WARNING_TOLERANCE_PERCENT + FLOAT_EPSILON:
            return "warning"
        return "fail"

    if operator in ("от ... до", "от ... до, включительно"):
        v = value if isinstance(value, dict) else {}
        vmin = float(v.get("min", float("-inf")))
        vmax = float(v.get("max", float("inf")))
        if vmin <= actual <= vmax:
            return "ok"
        span = vmax - vmin if vmax > vmin else 1.0
        tolerance = span * WARNING_TOLERANCE_PERCENT / 100.0
        if (vmin - tolerance - FLOAT_EPSILON) <= actual <= (vmax + tolerance + FLOAT_EPSILON):
            return "warning"
        return "fail"

    return "unknown"


def classify_text(actual: Any, rule: Dict[str, Any]) -> str:
    operator = rule.get("operator", "")
    if operator == "не допускается":
        text = normalize_name(str(actual))
        if any(w in text for w in ["нет", "отсутствует", "не обнаружено", "0"]):
            return "ok"
        return "fail"
    return "unknown"


def format_norm(rule: Dict[str, Any]) -> str:
    operator = rule.get("operator", "")
    value = rule.get("value")
    unit = rule.get("unit") or ""
    if operator == "не более":
        return f"≤ {value} {unit}".strip()
    if operator == "не менее":
        return f"≥ {value} {unit}".strip()
    if operator in ("от ... до", "от ... до, включительно") and isinstance(value, dict):
        return f"{value.get('min')}–{value.get('max')} {unit}".strip()
    return f"{value}"


def analyze_row(
    row: Dict[str, Any],
    mapping: Dict[str, str],
    rules_by_id: Dict[str, Dict[str, Any]],
    alias_index: Dict[str, Dict[str, Any]],
    row_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Анализирует одну строку.
    mapping: {колонка CSV: rule_id} — результат семантического маппинга.
    Если для колонки маппинга нет — fallback на fuzzy-поиск по alias_index.
    """
    results: List[Dict[str, Any]] = []

    for param_name, raw_value in row.items():
        if raw_value is None:
            continue
        if isinstance(raw_value, float) and raw_value != raw_value:  # NaN
            continue

        rule: Optional[Dict[str, Any]] = None

        # 1) Основной путь: маппинг от GigaChat
        rule_id = mapping.get(param_name)
        if rule_id and rule_id in rules_by_id:
            rule = rules_by_id[rule_id]

        # 2) Fallback: fuzzy-поиск по алиасам
        if rule is None:
            rule = find_rule_fuzzy(param_name, alias_index)

        if rule is None:
            results.append({
                "row_index": row_index,
                "parameter": param_name,
                "source_column": param_name,
                "actual": str(raw_value),
                "norm": None,
                "unit": None,
                "status": "unknown",
                "rule_id": None,
                "clause": None,
                "reason": "Норматив для параметра не найден",
            })
            continue

        # Пропускаем непроверяемые пункты (транспортирование, погрешности методов)
        if rule.get("id") in NON_CHECKABLE_IDS:
            continue

        number = parse_number(raw_value)
        if number is not None:
            status = classify_numeric(number, rule)
            actual_display: Any = number
        else:
            status = classify_text(raw_value, rule)
            actual_display = str(raw_value)

        results.append({
            "row_index": row_index,
            "parameter": rule.get("parameter"),
            "source_column": param_name,
            "actual": actual_display,
            "norm": format_norm(rule),
            "unit": rule.get("unit"),
            "status": status,
            "rule_id": rule.get("id"),
            "clause": rule.get("clause"),
        })

    return results


def overall_status(param_results: List[Dict[str, Any]]) -> str:
    statuses = [r["status"] for r in param_results]
    if any(s == "fail" for s in statuses):
        return "defect"
    if any(s == "warning" for s in statuses):
        return "warning"
    if any(s == "unknown" for s in statuses):
        return "warning"
    return "good"


STATUS_COLORS = {
    "good": "#00FF00",
    "warning": "#FFA500",
    "defect": "#FF0000",
}

STATUS_LABELS = {
    "good": "Зелёный — продукция годна",
    "warning": "Жёлтый — требуется внимание оператора",
    "defect": "Красный — продукция бракуется",
}