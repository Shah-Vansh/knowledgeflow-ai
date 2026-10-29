import pytest

from app.agent.tools import CalculatorError, format_number, safe_eval


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("-5 + 2", -3),
        ("+7", 7),
        ("10 / 4", 2.5),
        ("7 // 2", 3),
        ("7 % 4", 3),
        ("2 ** 10", 1024),
        ("2^3", 8),
        ("1,000 + 5", 1005),
        ("12 * (3 + 4)", 84),
        ("1e3 + 1", 1001.0),
        ("10 ** -2", 0.01),
        ("6 × 7", 42),
        ("9 ÷ 3", 3),
    ],
)
def test_safe_eval_computes(expression, expected):
    assert safe_eval(expression) == pytest.approx(expected)


def test_percentage_written_as_decimal():
    assert safe_eval("0.15 * 240") == pytest.approx(36.0)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "abs(-1)",
        "x + 1",
        "'a' * 3",
        "[1, 2]",
        "1 if True else 2",
        "(1).real",
        "lambda: 1",
        "True + 1",
        "",
        "   ",
        "2 +",
        "9 ** 9 ** 9",          # exponent too large
        "10 ** 101",            # exponent too large
        "10 ** 100",            # result too large
        "1 / 0",
        "5 % 0",
        "5 // 0",
        "(-8) ** 0.5",          # complex result
        "9" * 300,              # too long
        "1 + " * 40 + "1",     # too many nodes
    ],
)
def test_safe_eval_rejects(expression):
    with pytest.raises(CalculatorError):
        safe_eval(expression)


def test_safe_eval_rejects_non_text():
    with pytest.raises(CalculatorError):
        safe_eval(None)
    with pytest.raises(CalculatorError):
        safe_eval(42)


@pytest.mark.parametrize(
    "value, expected",
    [(36.0, "36"), (2.5, "2.5"), (14, "14"), (1 / 3, "0.3333333333"), (-4.0, "-4"), (1e20, "1e+20")],
)
def test_format_number(value, expected):
    assert format_number(value) == expected