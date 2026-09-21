"""
Детерминированный классификатор: сравнение чисел с нормативами.
LLM здесь НЕ участвует. Вердикт воспроизводим.
"""
import re
from typing import Any, Dict, List, Optional

from config import settings
from logger import logger


WARNING_TOLERANCE_PERCENT = settings.warning_tolerance_percent

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


STATUS_LABELS_RU = {
    "ok": "Соответствует",
    "warning": "Требует внимания",
    "fail": "Не соответствует",
    "unknown": "Нет норматива",
}

OVERALL_LABELS_RU = {
    "good": "Продукция годна",
    "warning": "Требует внимания оператора",
    "defect": "Продукция бракуется",
}

# Соответствия единиц измерения
UNIT_ALIASES = {
    "%": {"%", "процент", "проц", "percent", "pct"},
    "г": {"г", "g", "грамм", "gr"},
    "кг": {"кг", "kg", "килограмм"},
    "мг": {"мг", "mg", "миллиграмм"},
    "мм": {"мм", "mm", "миллиметр"},
    "см": {"см", "cm", "сантиметр"},
    "м": {"м", "m", "метр"},
    "мпа": {"мпа", "mpa"},
    "°c": {"°c", "c", "цельсий", "celsius"},
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
            return None if f != f else f
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


def extract_unit_from_column(column_name: str) -> Optional[str]:
    """
    Пытается извлечь единицу измерения из названия колонки.

    Примеры:
    - "Влага, %"      → "%"
    - "Влага (%)"     → "%"
    - "Влага %"       → "%"
    - "Масса, г"      → "г"
    - "Moisture, %"   → "%"
    - "Влага"         → None
    """
    if not column_name:
        return None
    name = str(column_name).lower()

    # Кандидаты: ищем в скобках и после запятой/точки с запятой
    candidates = re.findall(r"[\(,;]\s*([а-яa-z%°]+)\s*[\)]?", name)

    # Единица в конце строки после пробела: "Влага %"
    tail_match = re.search(r"\s+([а-яa-z%°]+)\s*$", name)
    if tail_match:
        candidates.append(tail_match.group(1))

    # Если кандидатов нет — берём последнее слово
    if not candidates:
        tail = re.split(r"[\(,;]", name)[-1].strip(" )")
        candidates.append(tail)

    for c in candidates:
        c_clean = c.strip().lower()
        for canonical, aliases in UNIT_ALIASES.items():
            if c_clean in aliases:
                return canonical

    return None


def check_unit_match(column_name: str, rule: Dict[str, Any]) -> str:
    """
    Возвращает:
    - "match"    — единицы совпадают
    - "mismatch" — не совпадают
    - "unknown"  — единицу колонки определить не удалось
    """
    rule_unit = (rule.get("unit") or "").strip().lower()
    if not rule_unit:
        return "unknown"

    col_unit = extract_unit_from_column(column_name)
    if not col_unit:
        return "unknown"

    if col_unit == rule_unit:
        return "match"

    for canonical, aliases in UNIT_ALIASES.items():
        if col_unit in aliases and rule_unit in aliases:
            return "match"

    return "mismatch"


def analyze_row(
    row: Dict[str, Any],
    mapping: Dict[str, str],
    rules_by_id: Dict[str, Dict[str, Any]],
    alias_index: Dict[str, Dict[str, Any]],
    row_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for param_name, raw_value in row.items():
        if raw_value is None:
            continue
        if isinstance(raw_value, float) and raw_value != raw_value:
            continue

        rule: Optional[Dict[str, Any]] = None

        rule_id = mapping.get(param_name)
        if rule_id and rule_id in rules_by_id:
            rule = rules_by_id[rule_id]

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
                "status_ru": STATUS_LABELS_RU["unknown"],
                "rule_id": None,
                "clause": None,
                "unit_status": "unknown",
                "reason": "Норматив для параметра не найден",
            })
            continue

        if rule.get("id") in NON_CHECKABLE_IDS:
            continue

        number = parse_number(raw_value)
        if number is not None:
            status = classify_numeric(number, rule)
            actual_display: Any = number
        else:
            status = classify_text(raw_value, rule)
            actual_display = str(raw_value)

        unit_status = check_unit_match(param_name, rule)

        results.append({
            "row_index": row_index,
            "parameter": rule.get("parameter"),
            "source_column": param_name,
            "actual": actual_display,
            "norm": format_norm(rule),
            "unit": rule.get("unit"),
            "status": status,
            "status_ru": STATUS_LABELS_RU.get(status, status),
            "rule_id": rule.get("id"),
            "clause": rule.get("clause"),
            "unit_status": unit_status,
        })

    return results


def find_unchecked_params(
    checked_rule_ids: set,
    rules: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Возвращает список нормативов, которые НЕ проверялись."""
    unchecked = []
    for r in rules:
        rid = r.get("id")
        if not rid or rid in NON_CHECKABLE_IDS:
            continue
        if rid not in checked_rule_ids:
            unchecked.append({
                "rule_id": rid,
                "parameter": r.get("parameter"),
                "clause": r.get("clause"),
                "norm": format_norm(r),
            })
    return unchecked


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