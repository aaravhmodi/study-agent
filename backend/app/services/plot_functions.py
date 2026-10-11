"""Named functions for plot formulas: distributions, signal shapes and interest factors.

Writing a t density or a P/A factor out by hand is where tutor formulas go wrong, so the
common ones are computed here. Bad parameters raise ValueError, which the formula
evaluator turns into a gap in the plot.
"""

import math
from collections.abc import Callable


def _positive(value: float, name: str) -> None:
    if not value > 0:
        raise ValueError(f"{name} must be positive")


def _whole(value: float) -> int | None:
    """The integer ``value`` equals, or None if it is not a whole number."""

    return int(round(value)) if abs(value - round(value)) < 1e-9 else None


# Probability and statistics (SYDE 212).


def normpdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    _positive(sigma, "sigma")
    z = (x - mu) / sigma
    return math.exp(-z * z / 2) / (sigma * math.sqrt(2 * math.pi))


def normcdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    _positive(sigma, "sigma")
    return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))


def tpdf(x: float, df: float) -> float:
    _positive(df, "df")
    log_scale = math.lgamma((df + 1) / 2) - math.lgamma(df / 2) - 0.5 * math.log(df * math.pi)
    return math.exp(log_scale - (df + 1) / 2 * math.log1p(x * x / df))


def chi2pdf(x: float, k: float) -> float:
    _positive(k, "k")
    if x < 0:
        return 0.0
    # Below two degrees of freedom the density is infinite at zero: a gap, not a spike.
    return math.exp((k / 2 - 1) * math.log(x) - x / 2 - k / 2 * math.log(2) - math.lgamma(k / 2))


def exppdf(x: float, rate: float) -> float:
    _positive(rate, "rate")
    return rate * math.exp(-rate * x) if x >= 0 else 0.0


def unifpdf(x: float, a: float, b: float) -> float:
    if not a < b:
        raise ValueError("a must be below b")
    return 1 / (b - a) if a <= x <= b else 0.0


def binompmf(k: float, n: float, p: float) -> float:
    trials, count = _whole(n), _whole(k)
    if trials is None or trials < 0 or not 0 <= p <= 1:
        raise ValueError("binompmf needs a whole n >= 0 and 0 <= p <= 1")
    if count is None or not 0 <= count <= trials:
        return 0.0
    return math.comb(trials, count) * p**count * (1 - p) ** (trials - count)


def poissonpmf(k: float, lam: float) -> float:
    _positive(lam, "lambda")
    count = _whole(k)
    if count is None or count < 0:
        return 0.0
    return math.exp(count * math.log(lam) - lam - math.lgamma(count + 1))


def comb(n: float, k: float) -> float:
    whole_n, whole_k = _whole(n), _whole(k)
    if whole_n is None or whole_k is None or whole_n < 0 or whole_k < 0:
        raise ValueError("comb needs whole numbers")
    return float(math.comb(whole_n, whole_k))


# Signals (SYDE 252), as in Lathi: rect and tri are one unit wide and centred on zero,
# so rect(t/tau) and tri(t/tau) are tau wide, and sinc(x) = sin(x)/x.


def rect(x: float) -> float:
    size = abs(x)
    return 1.0 if size < 0.5 else 0.5 if size == 0.5 else 0.0


def tri(x: float) -> float:
    return max(1 - 2 * abs(x), 0.0)


def sinc(x: float) -> float:
    return 1.0 if x == 0 else math.sin(x) / x


# Interest factors (SYDE 262), named as in (P/F, i, n) with i as a fraction.


def pf(i: float, n: float) -> float:
    """(P/F, i, n): today's worth of 1 received n periods from now."""

    return float((1 + i) ** -n)


def fp(i: float, n: float) -> float:
    """(F/P, i, n): what 1 today grows to after n periods."""

    return float((1 + i) ** n)


def pa(i: float, n: float) -> float:
    """(P/A, i, n): today's worth of 1 at the end of each of n periods."""

    return float(n) if i == 0 else (1 - (1 + i) ** -n) / i


def ap(i: float, n: float) -> float:
    """(A/P, i, n): the payment each period that repays 1 borrowed today."""

    return 1 / pa(i, n)


def fa(i: float, n: float) -> float:
    """(F/A, i, n): what 1 deposited each period is worth after n periods."""

    return float(n) if i == 0 else ((1 + i) ** n - 1) / i


def af(i: float, n: float) -> float:
    """(A/F, i, n): the deposit each period that reaches 1 after n periods."""

    return 1 / fa(i, n)


FUNCTIONS: dict[str, Callable[..., float]] = {
    "normpdf": normpdf,
    "normcdf": normcdf,
    "tpdf": tpdf,
    "chi2pdf": chi2pdf,
    "exppdf": exppdf,
    "unifpdf": unifpdf,
    "binompmf": binompmf,
    "poissonpmf": poissonpmf,
    "comb": comb,
    "gamma": math.gamma,
    "erf": math.erf,
    "rect": rect,
    "tri": tri,
    "sinc": sinc,
    "pf": pf,
    "fp": fp,
    "pa": pa,
    "ap": ap,
    "fa": fa,
    "af": af,
}
