import math

import pytest
from app.services.plot_functions import (
    ap,
    binompmf,
    chi2pdf,
    normpdf,
    pa,
    pf,
    poissonpmf,
    rect,
    sinc,
    tpdf,
    tri,
)
from app.services.plot_math import compile_formula


@pytest.mark.parametrize(
    ("formula", "x", "expected"),
    [
        ("normpdf(x, 0, 1)", 0.0, 1 / math.sqrt(2 * math.pi)),
        ("normpdf(x, 10, 2)", 10.0, 1 / (2 * math.sqrt(2 * math.pi))),
        ("normcdf(x, 0, 1)", 1.96, 0.9750021),
        ("normcdf(x, 100, 15)", 100.0, 0.5),
        # The t density with one degree of freedom is the Cauchy density.
        ("tpdf(x, 1)", 1.0, 1 / (2 * math.pi)),
        ("chi2pdf(x, 2)", 2.0, math.exp(-1) / 2),
        ("exppdf(x, 0.5)", 2.0, 0.5 * math.exp(-1)),
        ("exppdf(x, 0.5)", -1.0, 0.0),
        ("unifpdf(x, 2, 6)", 3.0, 0.25),
        ("binompmf(x, 10, 0.3)", 3.0, 0.2668279),
        ("poissonpmf(x, 4)", 2.0, 8 * math.exp(-4)),
        ("comb(5, 2) + gamma(5)", 0.0, 34.0),
        ("10*u(x - 2)", 2.5, 10.0),
        ("rect(x/4)", 1.9, 1.0),
        ("tri(x)", 0.25, 0.5),
        ("sinc(x)", math.pi, 0.0),
        ("1000*fp(0.05, x)", 2.0, 1102.5),
        ("af(0.1, 2)", 0.0, 1 / 2.1),
    ],
)
def test_named_functions_evaluate_in_formulas(formula: str, x: float, expected: float) -> None:
    assert compile_formula(formula)(x) == pytest.approx(expected, abs=1e-6)


def test_probability_masses_add_up_to_one() -> None:
    assert sum(binompmf(k, 12, 0.4) for k in range(13)) == pytest.approx(1.0)
    assert sum(poissonpmf(k, 3.5) for k in range(60)) == pytest.approx(1.0)


def test_discrete_masses_are_zero_off_the_whole_numbers_in_range() -> None:
    assert binompmf(2.5, 10, 0.3) == binompmf(-1, 10, 0.3) == binompmf(11, 10, 0.3) == 0.0
    assert poissonpmf(1.5, 2) == poissonpmf(-1, 2) == 0.0


def test_t_density_approaches_the_normal_as_df_grows() -> None:
    assert tpdf(0.7, 1e6) == pytest.approx(normpdf(0.7), rel=1e-5)
    assert tpdf(2.0, 5) > normpdf(2.0)


def test_chi_square_below_two_df_has_no_value_at_zero() -> None:
    assert math.isnan(compile_formula("chi2pdf(x, 1)")(0.0))
    assert chi2pdf(-1, 3) == 0.0


@pytest.mark.parametrize(
    "formula", ["normpdf(x, 0, 0)", "binompmf(x, 10, 1.5)", "binompmf(x, 2.5, 0.3)", "tpdf(x)"]
)
def test_bad_parameters_become_gaps(formula: str) -> None:
    assert math.isnan(compile_formula(formula)(1.0))


def test_signal_shapes_follow_lathis_conventions() -> None:
    assert (rect(0.49), rect(0.5), rect(0.51)) == (1.0, 0.5, 0.0)
    # tri is one unit wide, like rect: rect(t) * rect(t) = tri(t / 2).
    assert (tri(0), tri(0.5), tri(0.6)) == (1.0, 0.0, 0.0)
    assert sinc(0) == 1.0 and sinc(math.pi / 2) == pytest.approx(2 / math.pi)


def test_interest_factors_match_the_tables() -> None:
    # (P/A, 10%, 5) = 3.7908 and (P/F, 10%, 5) = 0.6209 in the factor tables.
    assert pa(0.1, 5) == pytest.approx(3.7908, abs=1e-4)
    assert pf(0.1, 5) == pytest.approx(0.6209, abs=1e-4)
    assert ap(0.1, 5) * pa(0.1, 5) == pytest.approx(1.0)
    # At zero interest the series is just n payments.
    assert pa(0, 5) == 5.0
