"""
Юнит-тесты для classifier.py.
Запуск: cd services/llm-gigachat && python -m pytest tests/ -v
"""
import pytest
from classifier import (
    normalize_name,
    parse_number,
    classify_numeric,
    classify_text,
    find_rule_fuzzy,
    build_alias_index,
    overall_status,
    format_norm,
    NON_CHECKABLE_IDS,
)


# ============================================================
# parse_number
# ============================================================

class TestParseNumber:
    def test_plain_float(self):
        assert parse_number(5.5) == 5.5

    def test_plain_int(self):
        assert parse_number(5) == 5.0

    def test_string_with_dot(self):
        assert parse_number("5.5") == 5.5

    def test_string_with_comma(self):
        assert parse_number("5,5") == 5.5

    def test_string_with_unit(self):
        assert parse_number("5.5 %") == 5.5

    def test_string_with_spaces(self):
        assert parse_number("  5.5  ") == 5.5

    def test_negative(self):
        assert parse_number("-3.2") == -3.2

    def test_none(self):
        assert parse_number(None) is None

    def test_nan_returns_none(self):
        assert parse_number(float("nan")) is None

    def test_empty_string(self):
        assert parse_number("") is None

    def test_garbage(self):
        assert parse_number("нет данных") is None

    def test_dot_only(self):
        assert parse_number(".") is None


# ============================================================
# normalize_name
# ============================================================

class TestNormalizeName:
    def test_lowercase(self):
        assert normalize_name("ВЛАГА") == "влага"

    def test_strip_spaces(self):
        assert normalize_name("  влага  ") == "влага"

    def test_removes_percent_sign(self):
        assert normalize_name("Влага, %") == "влага,"

    def test_collapses_spaces(self):
        assert normalize_name("массовая    доля") == "массовая доля"

    def test_none(self):
        assert normalize_name(None) == ""

    def test_empty(self):
        assert normalize_name("") == ""


# ============================================================
# classify_numeric — оператор "не более"
# ============================================================

class TestClassifyNumericMax:
    RULE = {"operator": "не более", "value": 5.5, "unit": "%"}

    def test_well_below_limit(self):
        assert classify_numeric(3.0, self.RULE) == "ok"

    def test_at_limit(self):
        assert classify_numeric(5.5, self.RULE) == "ok"

    def test_slightly_above_within_tolerance(self):
        assert classify_numeric(5.7, self.RULE) == "warning"

    def test_at_tolerance_boundary(self):
        """5.775 при норме 5.5 = ровно +5% → warning (граница, epsilon спасает)"""
        assert classify_numeric(5.775, self.RULE) == "warning"

    def test_above_tolerance(self):
        assert classify_numeric(6.2, self.RULE) == "fail"

    def test_way_above(self):
        assert classify_numeric(100.0, self.RULE) == "fail"


# ============================================================
# classify_numeric — оператор "не менее"
# ============================================================

class TestClassifyNumericMin:
    RULE = {"operator": "не менее", "value": 0.7, "unit": "%"}

    def test_well_above(self):
        assert classify_numeric(1.0, self.RULE) == "ok"

    def test_at_limit(self):
        assert classify_numeric(0.7, self.RULE) == "ok"

    def test_slightly_below_within_tolerance(self):
        assert classify_numeric(0.68, self.RULE) == "warning"

    def test_at_tolerance_boundary(self):
        assert classify_numeric(0.665, self.RULE) == "warning"

    def test_above_tolerance(self):
        assert classify_numeric(0.60, self.RULE) == "fail"

    def test_zero(self):
        assert classify_numeric(0, self.RULE) == "fail"


# ============================================================
# classify_numeric — оператор "от ... до"
# ============================================================

class TestClassifyNumericRange:
    RULE = {"operator": "от ... до", "value": {"min": 20.0, "max": 35.0}, "unit": "%"}

    def test_inside_range(self):
        assert classify_numeric(25.0, self.RULE) == "ok"

    def test_at_min(self):
        assert classify_numeric(20.0, self.RULE) == "ok"

    def test_at_max(self):
        assert classify_numeric(35.0, self.RULE) == "ok"

    def test_slightly_above_max_within_tolerance(self):
        assert classify_numeric(35.4, self.RULE) == "warning"

    def test_slightly_below_min_within_tolerance(self):
        assert classify_numeric(19.5, self.RULE) == "warning"

    def test_way_below(self):
        assert classify_numeric(18.5, self.RULE) == "fail"

    def test_way_above(self):
        assert classify_numeric(50.0, self.RULE) == "fail"


# ============================================================
# classify_numeric — нечисловые операторы
# ============================================================

class TestClassifyNumericUnknown:
    def test_requirement_returns_unknown(self):
        rule = {"operator": "требование", "value": "обжаренные зёрна"}
        assert classify_numeric(5.5, rule) == "unknown"

    def test_soglasno_returns_unknown(self):
        rule = {"operator": "согласно", "value": "по ГОСТ 8.579"}
        assert classify_numeric(5.5, rule) == "unknown"


# ============================================================
# classify_text
# ============================================================

class TestClassifyText:
    RULE = {"operator": "не допускается", "value": "Не допускается присутствие"}

    def test_absence_ok(self):
        assert classify_text("отсутствует", self.RULE) == "ok"

    def test_no_found_ok(self):
        assert classify_text("не обнаружено", self.RULE) == "ok"

    def test_no_ok(self):
        assert classify_text("нет", self.RULE) == "ok"

    def test_zero_ok(self):
        assert classify_text("0", self.RULE) == "ok"

    def test_present_fail(self):
        assert classify_text("обнаружено", self.RULE) == "fail"

    def test_unknown_operator(self):
        rule = {"operator": "требование", "value": "вкус приятный"}
        assert classify_text("что-то", rule) == "unknown"


# ============================================================
# format_norm
# ============================================================

class TestFormatNorm:
    def test_max(self):
        assert format_norm({"operator": "не более", "value": 5.5, "unit": "%"}) == "≤ 5.5 %"

    def test_min(self):
        assert format_norm({"operator": "не менее", "value": 0.7, "unit": "%"}) == "≥ 0.7 %"

    def test_range(self):
        rule = {"operator": "от ... до", "value": {"min": 20, "max": 35}, "unit": "%"}
        assert format_norm(rule) == "20–35 %"


# ============================================================
# build_alias_index + find_rule_fuzzy
# ============================================================

class TestAliasIndex:
    RULES = [
        {
            "id": "test-001",
            "parameter": "Массовая доля влаги",
            "aliases": ["влага", "влажность", "moisture"],
            "value": 5.5,
            "operator": "не более",
        },
        {
            "id": "test-002",
            "parameter": "Кофеин",
            "aliases": ["caffeine"],
            "value": 0.7,
            "operator": "не менее",
        },
    ]

    def test_index_built(self):
        idx = build_alias_index(self.RULES)
        assert "влага" in idx
        assert "влажность" in idx
        assert "кофеин" in idx
        assert "caffeine" in idx

    def test_exact_match(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("Влага", idx)
        assert rule is not None
        assert rule["id"] == "test-001"

    def test_case_insensitive(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("ВЛАЖНОСТЬ", idx)
        assert rule is not None

    def test_partial_match(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("Влага, %", idx)
        assert rule is not None
        assert rule["id"] == "test-001"

    def test_no_match(self):
        idx = build_alias_index(self.RULES)
        rule = find_rule_fuzzy("Неизвестный параметр", idx)
        assert rule is None


# ============================================================
# overall_status
# ============================================================

class TestOverallStatus:
    def test_all_ok(self):
        params = [{"status": "ok"}, {"status": "ok"}]
        assert overall_status(params) == "good"

    def test_one_warning(self):
        params = [{"status": "ok"}, {"status": "warning"}]
        assert overall_status(params) == "warning"

    def test_one_fail(self):
        params = [{"status": "ok"}, {"status": "warning"}, {"status": "fail"}]
        assert overall_status(params) == "defect"

    def test_fail_overrides_warning(self):
        params = [{"status": "warning"}, {"status": "fail"}]
        assert overall_status(params) == "defect"

    def test_unknown_becomes_warning(self):
        params = [{"status": "ok"}, {"status": "unknown"}]
        assert overall_status(params) == "warning"

    def test_empty_list(self):
        assert overall_status([]) == "good"


# ============================================================
# NON_CHECKABLE_IDS
# ============================================================

class TestNonCheckableIds:
    def test_transportation_is_non_checkable(self):
        assert "gost32775-req-005" in NON_CHECKABLE_IDS

    def test_control_methods_are_non_checkable(self):
        for rule_id in ["gost32775-ctrl-001", "gost32775-ctrl-002",
                        "gost32775-ctrl-003", "gost32775-ctrl-004"]:
            assert rule_id in NON_CHECKABLE_IDS

    def test_physchem_is_checkable(self):
        assert "gost32775-t2-001" not in NON_CHECKABLE_IDS