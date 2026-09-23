"""
Создаёт XLSX-файл с ГОСТ на растворимый кофе.
Файл можно загрузить через админ-панель проекта.

Формат: совпадает с gost_32775_2014_rules.xlsx
"""
from pathlib import Path

import pandas as pd


OUT_PATH = Path(__file__).parent / "gost_6805_2018_instant_coffee.xlsx"

COLUMNS = [
    "id", "standard", "clause", "category", "parameter",
    "aliases", "operator", "value_min", "value_max", "value_text",
    "unit", "method_ref", "text",
]

RULES = [
    # --- Органолептические ---
    {
        "id": "gost6805-t1-001",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.2, Таблица 1",
        "category": "органолептические показатели",
        "parameter": "Внешний вид — растворимый кофе",
        "aliases": "внешний вид; внешний вид растворимого; appearance",
        "operator": "требование",
        "value_min": None,
        "value_max": None,
        "value_text": "Однородкий сыпучий порошок или гранулы без комков",
        "unit": None,
        "method_ref": None,
        "text": "По ГОСТ 6805—2018 растворимый кофе должен быть однородным сыпучим порошком или гранулами без комков.",
    },
    {
        "id": "gost6805-t1-002",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.2, Таблица 1",
        "category": "органолептические показатели",
        "parameter": "Цвет",
        "aliases": "цвет; color",
        "operator": "требование",
        "value_min": None,
        "value_max": None,
        "value_text": "От светло-коричневого до тёмно-коричневого",
        "unit": None,
        "method_ref": None,
        "text": "Цвет растворимого кофе — от светло-коричневого до тёмно-коричневого.",
    },
    {
        "id": "gost6805-t1-003",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.2, Таблица 1",
        "category": "органолептические показатели",
        "parameter": "Вкус и аромат",
        "aliases": "вкус; аромат; вкус и аромат",
        "operator": "требование",
        "value_min": None,
        "value_max": None,
        "value_text": "Приятные, свойственные растворимому кофе",
        "unit": None,
        "method_ref": None,
        "text": "Вкус и аромат — приятные, свойственные растворимому кофе, без посторонних привкусов и запахов.",
    },

    # --- Физико-химические ---
    {
        "id": "gost6805-t2-001",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.3, Таблица 2",
        "category": "физико-химические показатели",
        "parameter": "Массовая доля влаги (растворимый кофе)",
        "aliases": "влага растворимого; влага растворимый; moisture instant",
        "operator": "не более",
        "value_min": None,
        "value_max": 4.0,
        "value_text": None,
        "unit": "%",
        "method_ref": "ГОСТ ISO 11817",
        "text": "По ГОСТ 6805—2018 массовая доля влаги в растворимом кофе — не более 4,0 %.",
    },
    {
        "id": "gost6805-t2-002",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.3, Таблица 2",
        "category": "физико-химические показатели",
        "parameter": "Массовая доля кофеина (растворимый, сухое вещество)",
        "aliases": "кофеин растворимого; кофеин растворимый; caffeine instant",
        "operator": "не менее",
        "value_min": 2.8,
        "value_max": None,
        "value_text": None,
        "unit": "%",
        "method_ref": "ГОСТ ISO 20481",
        "text": "По ГОСТ 6805—2018 массовая доля кофеина в растворимом кофе — не менее 2,8 % на сухое вещество.",
    },
    {
        "id": "gost6805-t2-003",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.3, Таблица 2",
        "category": "физико-химические показатели",
        "parameter": "Массовая доля золы (растворимый, сухое вещество)",
        "aliases": "зола растворимого; зола растворимый; ash instant",
        "operator": "не более",
        "value_min": None,
        "value_max": 8.0,
        "value_text": None,
        "unit": "%",
        "method_ref": "ГОСТ 15113.8",
        "text": "По ГОСТ 6805—2018 массовая доля золы в растворимом кофе — не более 8,0 %.",
    },
    {
        "id": "gost6805-t2-004",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.3, Таблица 2",
        "category": "физико-химические показатели",
        "parameter": "pH раствора (растворимый кофе)",
        "aliases": "ph; ph раствора; pH растворимого",
        "operator": "от ... до",
        "value_min": 4.8,
        "value_max": 5.3,
        "value_text": None,
        "unit": None,
        "method_ref": "ГОСТ 26188",
        "text": "По ГОСТ 6805—2018 pH водного раствора растворимого кофе — от 4,8 до 5,3.",
    },
    {
        "id": "gost6805-t2-005",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.3, Таблица 2",
        "category": "физико-химические показатели",
        "parameter": "Массовая доля экстрактивных веществ (растворимый)",
        "aliases": "экстрактивные растворимого; экстрактивность растворимого; extract instant",
        "operator": "не менее",
        "value_min": 95.0,
        "value_max": None,
        "value_text": None,
        "unit": "%",
        "method_ref": "Приложение В",
        "text": "По ГОСТ 6805—2018 массовая доля экстрактивных веществ в растворимом кофе — не менее 95,0 %.",
    },
    {
        "id": "gost6805-t2-006",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.3, Таблица 2",
        "category": "физико-химические показатели",
        "parameter": "Металлические примеси (растворимый, частицы ≤ 0,3 мм)",
        "aliases": "металлические примеси растворимого; metal instant",
        "operator": "не более",
        "value_min": None,
        "value_max": 0.0003,
        "value_text": None,
        "unit": "%",
        "method_ref": "ГОСТ 15113.2",
        "text": "По ГОСТ 6805—2018 содержание металлических примесей в растворимом кофе — не более 3×10⁻⁴ %.",
    },

    # --- Прочие ---
    {
        "id": "gost6805-req-001",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.1.4",
        "category": "прочие требования",
        "parameter": "Посторонние примеси и вредители (растворимый)",
        "aliases": "примеси растворимого; посторонние примеси растворимого",
        "operator": "не допускается",
        "value_min": None,
        "value_max": None,
        "value_text": "Не допускается",
        "unit": None,
        "method_ref": None,
        "text": "По ГОСТ 6805—2018 присутствие посторонних примесей и вредителей в растворимом кофе не допускается.",
    },
    {
        "id": "gost6805-req-002",
        "standard": "ГОСТ 6805—2018",
        "clause": "5.3.1",
        "category": "прочие требования",
        "parameter": "Масса нетто упаковки (растворимый)",
        "aliases": "масса нетто растворимого; масса упаковки растворимого",
        "operator": "от ... до",
        "value_min": 10.0,
        "value_max": 5000.0,
        "value_text": None,
        "unit": "г",
        "method_ref": None,
        "text": "Масса нетто упаковки растворимого кофе — от 10 до 5000 г.",
    },
]


def main():
    df = pd.DataFrame(RULES, columns=COLUMNS)
    df.to_excel(OUT_PATH, index=False, engine="openpyxl")

    # Автоширина колонок
    from openpyxl import load_workbook
    wb = load_workbook(OUT_PATH)
    ws = wb.active
    for column_cells in ws.columns:
        max_len = max(len(str(c.value)) if c.value is not None else 0 for c in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 10), 60)
    wb.save(OUT_PATH)

    print(f"Создан файл: {OUT_PATH}")
    print(f"Правил: {len(RULES)}")


if __name__ == "__main__":
    main()