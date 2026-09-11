"""
tests/test_number_parser.py

Covers case study section 37 items 6 and 7 (number parsing, negative /
bracket parsing). Pure-Python, no mocking required.
"""
import pytest

from app.utils.number_parser import parse_amount, approximately_equal, effective_tolerance


@pytest.mark.parametrize(
    "raw,expected_value",
    [
        ("(1,234.50)", -1234.50),
        ("₹ 6,862.00", 6862.00),
        ("1,000,000", 1000000.0),
        ("RM 8.49", 8.49),
        ("3,099,638.29", 3099638.29),
        ("(102,572.73)", -102572.73),
        ("41.00", 41.0),
        ("-", None),
        ("", None),
        ("N/A", None),
    ],
)
def test_parse_amount_values(raw, expected_value):
    result = parse_amount(raw)
    assert result.value == expected_value


def test_parse_amount_percentage():
    result = parse_amount("9%")
    assert result.is_percentage is True
    assert result.value == pytest.approx(0.09)


def test_parse_amount_currency_detection():
    assert parse_amount("₹ 100.00").currency == "INR"
    assert parse_amount("RM 8.49").currency == "MYR"
    assert parse_amount("$50.00").currency == "USD"


def test_parse_amount_negative_bracket():
    result = parse_amount("(29,678.54)")
    assert result.is_negative is True
    assert result.value == -29678.54


def test_approximately_equal_within_absolute_tolerance():
    ok, variance = approximately_equal(6862.00, 6861.99, abs_tolerance=0.01)
    assert ok is True
    assert variance == pytest.approx(0.01)


def test_approximately_equal_within_relative_tolerance_for_large_numbers():
    # 0.04 absolute difference on a ~4.9M figure is well within 0.1% relative.
    ok, variance = approximately_equal(4908040.84, 4908040.80, abs_tolerance=0.01, rel_tolerance=0.001)
    assert ok is True


def test_approximately_equal_fails_outside_tolerance():
    ok, variance = approximately_equal(100.0, 150.0)
    assert ok is False


def test_effective_tolerance_scales_with_magnitude():
    small = effective_tolerance(100.0)
    large = effective_tolerance(10_000_000.0)
    assert large > small
