"""Which graphs teach each course's topics, sent with questions about that course.

The general figure guide is in every prompt, so it stays short; these add the graphs a
statistics, signals or economics course is taught with, and the plot functions that
compute them. Every example here is checked by the tests to render.
"""

import re

STATISTICS = """\
Graphs for this statistics course: draw one whenever a probability, test or data set is \
discussed. Compute curves with normpdf(x, mu, sigma), normcdf(x, mu, sigma), tpdf(x, df), \
chi2pdf(x, k), exppdf(x, rate), unifpdf(x, a, b), binompmf(x, n, p), poissonpmf(x, lam), \
comb(n, k) and gamma, never by writing the density out.
- P(a < X < b) or a percentile: the density with "shade" over exactly that range; mark a and b.
- A hypothesis test: the null distribution, every rejection region shaded ("shade" takes a \
list for both tails), and the test statistic as a marker. A confidence interval: the \
sampling distribution with the interval shaded and its ends marked.
- A discrete distribution: "bars": true with a formula in x, evaluated at whole numbers. A \
CDF: normcdf, or a step function in "pieces".
- Data: a histogram as "bars" from [[bin centre, count], ...]; a scatter plot as \
"points" with the fitted line as a second series; residuals as points about zero.
- Bayes' theorem or total probability: a mermaid tree, branch probabilities on the edges.
```plot
{"title": "Two-sided z test at α = 0.05", "x": {"label": "z", "min": -4, "max": 4}, \
"y": {"label": "density"}, "series": [{"label": "N(0, 1) under H0", \
"expr": "normpdf(x, 0, 1)", "shade": [{"from": -4, "to": -1.96}, {"from": 1.96, "to": 4}]}], \
"markers": [{"x": -1.96, "label": "−1.96"}, {"x": 1.96, "label": "1.96"}, \
{"x": 2.3, "y": 0, "label": "z = 2.3: reject H0"}]}
```
```plot
{"title": "Binomial(n = 10, p = 0.3)", "x": {"label": "k", "min": 0, "max": 10}, \
"y": {"label": "P(X = k)"}, "series": [{"label": "PMF", "expr": "binompmf(x, 10, 0.3)", \
"bars": true}]}
```\
"""

SIGNALS = """\
Graphs for this signals and systems course: sketch every signal, system response or \
spectrum discussed. Functions: u(x) (unit step), ramp(x), rect(x) and tri(x) (one unit wide \
and centred on zero, so rect(t/τ) is τ wide), sinc(x) = sin(x)/x, plus exp, cos and sin.
- Signal operations (shift, scale, reversal, even and odd parts): the original and the \
result as series on one plot.
- Continuous convolution: x(τ) and the flipped, shifted h(t − τ) for one t, then y(t) in a \
second plot. Discrete signals x[n], h[n], y[n]: "stems". An impulse: a stem of its area.
- Fourier series or transform: the magnitude spectrum, with phase as a second plot when it \
matters; line spectra as stems at the harmonic frequencies.
- Frequency response: a Bode plot, x "scale": "log" over whole decades, magnitude in dB as \
20*log10(|H|), the corner frequency marked; phase in degrees as its own plot.
- Poles and zeros: "points" in the s-plane (x Re, y Im), poles and zeros as two series.
- System block diagrams and feedback loops: a mermaid flowchart.
```plot
{"title": "Bode magnitude of H(jω) = 1/(1 + jω/100)", "x": {"label": "ω (rad/s)", \
"min": 1, "max": 10000, "scale": "log"}, "y": {"label": "|H| (dB)"}, \
"series": [{"label": "|H(jω)|", "expr": "-10*log10(1 + (x/100)^2)"}], \
"markers": [{"x": 100, "y": -3.01, "label": "corner: −3 dB at 100 rad/s"}]}
```
```plot
{"title": "rect(t) * rect(t) = tri(t/2)", "x": {"label": "t (s)", "min": -2, "max": 2}, \
"y": {"label": "amplitude"}, "series": [{"label": "x(t) = rect(t)", "expr": "rect(x)"}, \
{"label": "y(t) = x(t) * x(t)", "expr": "tri(x/2)"}]}
```\
"""

ECONOMICS = """\
Graphs for this engineering economics course: draw one for every cash-flow problem and \
every comparison. Interest factors are functions of (i, n), i as a fraction: pf, fp, pa, ap, \
fa, af, so pa(0.1, 5) is (P/A, 10%, 5); use them instead of writing the factors out.
- Every cash-flow problem: a cash-flow diagram, "stems" at the end of each period, \
receipts positive and payments negative.
- Present worth against interest rate: x is i, the IRR marked where the curve crosses zero \
and the MARR as a vertical marker. Compare alternatives on one plot to show where the \
preferred one changes.
- Break-even: cost and revenue against quantity, the break-even point marked. \
Sensitivity: present worth against the percent change in each estimate, one line each.
- Depreciation: book value by year, one series per method. Growth of money: simple and \
compound interest on one plot.
- Supply and demand: price on y against quantity on x, the equilibrium marked.
```plot
{"title": "Cash flows: $1000 now, $300 a year for 5 years", "x": {"label": "end of year", \
"min": 0, "max": 5}, "y": {"label": "$"}, "series": [{"label": "cash flow", \
"points": [[0, -1000], [1, 300], [2, 300], [3, 300], [4, 300], [5, 300]], "stems": true}]}
```
```plot
{"title": "Present worth against interest rate", "x": {"label": "i", "min": 0, "max": 0.3}, \
"y": {"label": "PW ($)"}, "series": [{"label": "PW = −1000 + 300(P/A, i, 5)", \
"expr": "-1000 + 300*pa(x, 5)"}], "markers": [{"x": 0.1, "label": "MARR = 10%"}, \
{"x": 0.1524, "y": 0, "label": "IRR ≈ 15.2%"}]}
```\
"""

# This term's courses, and subject prefixes so a later STAT or ECON course gets its graphs.
_COURSES = {"SYDE 212": STATISTICS, "SYDE 252": SIGNALS, "SYDE 262": ECONOMICS}
_SUBJECTS = {"STAT": STATISTICS, "ECON": ECONOMICS}


def course_figure_guide(course_code: str | None) -> str | None:
    """The graphing guidance for a course, or None when it has none of its own."""

    if not course_code:
        return None
    code = " ".join(course_code.upper().split())
    subject = re.match(r"[A-Z]+", code)
    return _COURSES.get(code) or (_SUBJECTS.get(subject.group()) if subject else None)
