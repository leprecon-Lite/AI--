"""
Одноразовый конвертер: JSON → XLSX.
Читает gost_32775_2014_chunks_verified.json и создаёт
gost_32775_2014_rules.xlsx в машиночитаемом формате.

Запуск: cd services/llm-gigachat && python make_rules_xlsx.py
"""
import json
from pathlib import Path

import pandas as pd

SRC = Path(__file__).parent / "gost_32775_2014_chunks_verified.json"
DST = Path(__file__).parent / "gost_32775_2014_rules.xlsx"

COLUMNS = [
    "id",
    "standard",
    "clause",
    "category",
    "parameter",
    "aliases",
    "operator",
    "value_min",
    "value_max",
    "value_text",
    "unit",
    "method_ref",
    "text",
]


def rule_to_row(rule: dict) -> dict:
    operator = rule.get("operator", "")
    value = rule.get("value")

    value_min = None
    value_max = None
    value_text = None

    if operator == "не более":
        value_max = value
    elif operator == "не менее":
        value_min = value
    elif operator in ("от ... до", "от ... до, включительно"):
        if isinstance(value, dict):
            value_min = value.get("min")
            value_max = value.get("max")
        else:
            value_text = str(value)
    else:
        # Строковые операторы: требование, согласно, не допускается,
        # предел повторяемости, параметры точности метода и т.п.
        value_text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    aliases = rule.get("aliases", [])
    aliases_str = "; ".join(aliases) if aliases else ""

    return {
        "id": rule.get("id"),
        "standard": rule.get("standard"),
        "clause": rule.get("clause"),
        "category": rule.get("category"),
        "parameter": rule.get("parameter"),
        "aliases": aliases_str,
        "operator": operator,
        "value_min": value_min,
        "value_max": value_max,
        "value_text": value_text,
        "unit": rule.get("unit"),
        "method_ref": rule.get("method_ref"),
        "text": rule.get("text"),
    }


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        rules = json.load(f)

    rows = [rule_to_row(r) for r in rules]
    df = pd.DataFrame(rows, columns=COLUMNS)

    # Пишем через openpyxl — нативный формат Excel
    df.to_excel(DST, index=False, engine="openpyxl")

    # Автоширина колонок — чтобы файл сразу читался в Excel
    from openpyxl import load_workbook
    wb = load_workbook(DST)
    ws = wb.active
    for column_cells in ws.columns:
        max_len = max(len(str(c.value)) if c.value is not None else 0 for c in column_cells)
        letter = column_cells[0].column_letter
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 80)
    wb.save(DST)

    print(f"Создан файл: {DST}")
    print(f"Правил: {len(rows)}")
    print(f"Колонок: {len(COLUMNS)}")


if __name__ == "__main__":
    main()