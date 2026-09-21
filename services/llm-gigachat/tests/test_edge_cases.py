"""
Тесты на граничные случаи: битые файлы, опечатки, единицы измерения, полнота протокола.
Запуск: cd services/llm-gigachat && python -m pytest tests/ -v
"""
import io
import pytest
import pandas as pd

from classifier import (
    extract_unit_from_column,
    check_unit_match,
    find_unchecked_params,
    analyze_row,
    build_alias_index,
    find_rule_fuzzy,
    parse_number,
)


# ============================================================
# extract_unit_from_column — извлечение единицы из названия колонки
# ============================================================

class TestExtractUnit:
    def test_percent_comma(self):
        assert extract_unit_from_column("Влага, %") == "%"

    def test_percent_parens(self):
        assert extract_unit_from_column("Влага (%)") == "%"

    def test_percent_no_separator(self):
        assert extract_unit_from_column("Влага %") == "%"

    def test_gram(self):
        assert extract_unit_from_column("Масса, г") == "г"

    def test_mg(self):
        assert extract_unit_from_column("Примеси, мг") == "мг"

    def test_kg(self):
        assert extract_unit_from_column("Вес, кг") == "кг"

    def test_mpa(self):
        assert extract_unit_from_column("Прочность, МПа") == "мпа"

    def test_mm(self):
        assert extract_unit_from_column("Диаметр, мм") == "мм"

    def test_no_unit(self):
        assert extract_unit_from_column("Влага") is None

    def test_english_percent(self):
        assert extract_unit_from_column("Moisture, %") == "%"

    def test_empty_string(self):
        assert extract_unit_from_column("") is None

    def test_none(self):
        assert extract_unit_from_column(None) is None


# ============================================================
# check_unit_match — сравнение единицы колонки с единицей норматива
# ============================================================

class TestCheckUnitMatch:
    def test_match_percent(self):
        rule = {"unit": "%", "value": 5.5, "operator": "не более"}
        assert check_unit_match("Влага, %", rule) == "match"

    def test_match_gram(self):
        rule = {"unit": "г", "value": 100, "operator": "не более"}
        assert check_unit_match("Масса, г", rule) == "match"

    def test_match_mpa(self):
        rule = {"unit": "МПа", "value": 100, "operator": "не менее"}
        assert check_unit_match("Прочность, МПа", rule) == "match"

    def test_mismatch_percent_vs_gram(self):
        rule = {"unit": "%", "value": 5.5, "operator": "не более"}
        assert check_unit_match("Влага, г", rule) == "mismatch"

    def test_mismatch_gram_vs_percent(self):
        rule = {"unit": "г", "value": 100, "operator": "не более"}
        assert check_unit_match("Масса, %", rule) == "mismatch"

    def test_unknown_no_unit_in_column(self):
        rule = {"unit": "%", "value": 5.5, "operator": "не более"}
        assert check_unit_match("Влага", rule) == "unknown"

    def test_unknown_no_unit_in_rule(self):
        rule = {"unit": None, "value": 5.5, "operator": "не более"}
        assert check_unit_match("Влага, %", rule) == "unknown"

    def test_unknown_empty_rule_unit(self):
        rule = {"unit": "", "value": 5.5, "operator": "не более"}
        assert check_unit_match("Влага, %", rule) == "unknown"


# ============================================================
# find_unchecked_params — поиск непроверенных нормативов
# ============================================================

class TestFindUnchecked:
    def test_finds_missing(self):
        rules = [
            {"id": "r1", "parameter": "Влага", "operator": "не более", "value": 5.5, "unit": "%"},
            {"id": "r2", "parameter": "Кофеин", "operator": "не менее", "value": 0.7, "unit": "%"},
            {"id": "r3", "parameter": "Зола", "operator": "не более", "value": 6.0, "unit": "%"},
        ]
        checked = {"r1", "r3"}
        unchecked = find_unchecked_params(checked, rules)
        assert len(unchecked) == 1
        assert unchecked[0]["rule_id"] == "r2"

    def test_skips_non_checkable(self):
        rules = [
            {"id": "r1", "parameter": "Влага", "operator": "не более", "value": 5.5, "unit": "%"},
            {"id": "gost32775-ctrl-001", "parameter": "Погрешность", "operator": "предел повторяемости", "value": 2.5},
        ]
        unchecked = find_unchecked_params({"r1"}, rules)
        assert len(unchecked) == 0

    def test_empty_checked(self):
        rules = [
            {"id": "r1", "parameter": "Влага", "operator": "не более", "value": 5.5, "unit": "%"},
        ]
        unchecked = find_unchecked_params(set(), rules)
        assert len(unchecked) == 1

    def test_empty_rules(self):
        assert find_unchecked_params(set(), []) == []

    def test_all_checked(self):
        rules = [
            {"id": "r1", "parameter": "Влага", "operator": "не более", "value": 5.5, "unit": "%"},
            {"id": "r2", "parameter": "Кофеин", "operator": "не менее", "value": 0.7, "unit": "%"},
        ]
        unchecked = find_unchecked_params({"r1", "r2"}, rules)
        assert len(unchecked) == 0


# ============================================================
# Анализ строк с проверкой единиц
# ============================================================

class TestAnalyzeRowUnits:
    RULES = [
        {
            "id": "r1",
            "parameter": "Массовая доля влаги",
            "aliases": ["влага"],
            "operator": "не более",
            "value": 5.5,
            "unit": "%",
        },
    ]

    def test_unit_match_flag(self):
        alias_idx = build_alias_index(self.RULES)
        rules_by_id = {r["id"]: r for r in self.RULES}
        result = analyze_row(
            {"Влага, %": 5.0},
            {"Влага, %": "r1"},
            rules_by_id,
            alias_idx,
            row_index=1,
        )
        assert len(result) == 1
        assert result[0]["unit_status"] == "match"

    def test_unit_mismatch_flag(self):
        alias_idx = build_alias_index(self.RULES)
        rules_by_id = {r["id"]: r for r in self.RULES}
        result = analyze_row(
            {"Влага, г": 5.0},
            {"Влага, г": "r1"},
            rules_by_id,
            alias_idx,
            row_index=1,
        )
        assert len(result) == 1
        assert result[0]["unit_status"] == "mismatch"

    def test_unit_unknown_flag(self):
        alias_idx = build_alias_index(self.RULES)
        rules_by_id = {r["id"]: r for r in self.RULES}
        result = analyze_row(
            {"Влага": 5.0},
            {"Влага": "r1"},
            rules_by_id,
            alias_idx,
            row_index=1,
        )
        assert len(result) == 1
        assert result[0]["unit_status"] == "unknown"

    def test_status_ru_present(self):
        alias_idx = build_alias_index(self.RULES)
        rules_by_id = {r["id"]: r for r in self.RULES}
        result = analyze_row(
            {"Влага, %": 6.2},
            {"Влага, %": "r1"},
            rules_by_id,
            alias_idx,
            row_index=1,
        )
        assert result[0]["status"] == "fail"
        assert result[0]["status_ru"] == "Не соответствует"

    def test_unknown_param_gets_status_ru(self):
        alias_idx = build_alias_index(self.RULES)
        rules_by_id = {r["id"]: r for r in self.RULES}
        result = analyze_row(
            {"Неизвестный параметр": 5.0},
            {},
            rules_by_id,
            alias_idx,
            row_index=1,
        )
        assert len(result) == 1
        assert result[0]["status"] == "unknown"
        assert result[0]["status_ru"] == "Нет норматива"


# ============================================================
# Битые файлы — проверяем pandas-парсинг
# ============================================================

class TestBrokenFiles:
    def test_empty_file_raises_or_empty(self):
        content = ""
        try:
            df = pd.read_csv(io.StringIO(content))
            assert df.empty
        except pd.errors.EmptyDataError:
            pass

    def test_headers_only(self):
        content = "Влага,Кофеин,Зола\n"
        df = pd.read_csv(io.StringIO(content))
        assert len(df) == 0
        assert list(df.columns) == ["Влага", "Кофеин", "Зола"]

    def test_ragged_rows_handled(self):
        """
        pandas 2.x/3.x не падает на ragged rows по умолчанию —
        просто пропускает некорректные строки или заполняет NaN.
        Проверяем, что парсинг не ломается.
        """
        content = "a,b,c\n1,2,3\n4,5\n"
        try:
            df = pd.read_csv(io.StringIO(content), on_bad_lines="error")
            # Если не упало — проверяем, что данные распарсились корректно
            assert list(df.columns) == ["a", "b", "c"]
            # Строка "4,5" может быть отброшена или заполнена NaN
            assert len(df) >= 1
        except pd.errors.ParserError:
            # Альтернативно — pandas может выбросить ошибку
            pass

    def test_bom_stripped(self):
        content = "\ufeffВлага,Кофеин\n5.0,0.8\n"
        df = pd.read_csv(io.StringIO(content))
        df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
        assert df.columns[0] == "Влага"
        assert len(df) == 1

    def test_semicolon_separator(self):
        content = "Влага;Кофеин;Зола\n5.0;0.8;5.5\n"
        df = pd.read_csv(io.StringIO(content), sep=";")
        assert len(df.columns) == 3
        assert len(df) == 1

    def test_extra_whitespace_in_headers(self):
        content = " Влага , Кофеин \n5.0,0.8\n"
        df = pd.read_csv(io.StringIO(content))
        df.columns = [str(c).strip() for c in df.columns]
        assert df.columns[0] == "Влага"
        assert df.columns[1] == "Кофеин"


# ============================================================
# Опечатки в названиях колонок — fuzzy-поиск
# ============================================================

class TestTyposInColumnNames:
    RULES = [
        {
            "id": "r1",
            "parameter": "Массовая доля влаги",
            "aliases": ["влага", "влажность"],
            "operator": "не более",
            "value": 5.5,
            "unit": "%",
        },
    ]

    def test_typo_vlaga(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("Влга", idx)
        assert rule is None or rule["id"] == "r1"

    def test_synonym_vlazhnost(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("Влажность", idx)
        assert rule is not None
        assert rule["id"] == "r1"

    def test_partial_match_with_unit(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("Влага, %", idx)
        assert rule is not None

    def test_case_insensitive(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("ВЛАГА", idx)
        assert rule is not None

    def test_extra_spaces(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("  Влага  ", idx)
        assert rule is not None


# ============================================================
# parse_number — граничные случаи
# ============================================================

class TestUnitConversions:
    def test_percent_value(self):
        assert parse_number("5.5%") == 5.5

    def test_fraction_value(self):
        assert parse_number("0.055") == 0.055

    def test_negative_number(self):
        assert parse_number("-3.2") == -3.2

    def test_comma_decimal(self):
        assert parse_number("5,5") == 5.5

    def test_with_spaces(self):
        assert parse_number("  5.5  ") == 5.5

    def test_with_unit_suffix(self):
        assert parse_number("5.5 г") == 5.5

    def test_with_unit_prefix(self):
        assert parse_number("г 5.5") == 5.5

    def test_zero(self):
        assert parse_number("0") == 0.0

    def test_zero_float(self):
        assert parse_number(0.0) == 0.0

    def test_nan_returns_none(self):
        assert parse_number(float("nan")) is None

    def test_none_returns_none(self):
        assert parse_number(None) is None

    def test_empty_string(self):
        assert parse_number("") is None

    def test_garbage(self):
        assert parse_number("нет данных") is None

    def test_only_letters(self):
        assert parse_number("abc") is None