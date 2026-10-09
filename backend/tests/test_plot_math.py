import math

import pytest
from app.services.plot_math import FormulaError, compile_formula


@pytest.mark.parametrize(
    ("formula", "x", "expected"),
    [
        ("8 - 4*(x - 2)", 3.0, 4.0),
        ("x^2", 3.0, 9.0),
        ("2x + 1", 2.0, 5.0),
        ("3(x+1)", 1.0, 6.0),
        ("(x+1)(x-1)", 3.0, 8.0),
        ("-x", 2.0, -2.0),
        ("sin(pi/2)", 0.0, 1.0),
        ("exp(-x^2/2)/sqrt(2*pi)", 0.0, 1 / math.sqrt(2 * math.pi)),
        ("log10(x)", 100.0, 2.0),
        ("1e-3*x", 1000.0, 1.0),
        ("max(x, 0) + min(x, 1, 2)", -1.0, -1.0),
        ("10*step(x-2)", 2.0, 10.0),
        ("10*step(x-2)", 1.9, 0.0),
        ("5*ramp(x-1)^2", 3.0, 20.0),
        ("abs(x)·2", -2.0, 4.0),
    ],
)
def test_formulas_evaluate(formula: str, x: float, expected: float) -> None:
    assert compile_formula(formula)(x) == pytest.approx(expected)


@pytest.mark.parametrize("formula", ["1/x", "sqrt(x)", "log(x)", "10^x"])
def test_math_errors_become_gaps(formula: str) -> None:
    x = 0.0 if formula == "1/x" else -1.0 if formula != "10^x" else 1e6
    assert math.isnan(compile_formula(formula)(x))


@pytest.mark.parametrize(
    "formula",
    [
        "",
        "__import__('os').system('echo hi')",
        "x.__class__",
        "open('f')",
        "y + 1",
        "[x]",
        "'x'",
        "lambda: 1",
        "x if x else 1",
        "sin(x=1)",
        "x" * 300,
        "True + x",
        "2 *",
    ],
)
def test_anything_but_math_is_rejected(formula: str) -> None:
    with pytest.raises(FormulaError):
        compile_formula(formula)


def test_huge_powers_do_not_hang() -> None:
    assert math.isnan(compile_formula("9^9^9")(0.0))
