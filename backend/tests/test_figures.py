import json
from typing import Any

import pytest
from app.schemas.chat import SketchFigure, SourceFigure
from app.services.figures import (
    MAX_FIGURES,
    MAX_SOURCES,
    SAMPLES,
    FigureError,
    extract_figures,
    parse_diagram,
    parse_plot,
)

SHEAR = {
    "title": "Shear force, simply supported beam",
    "x": {"label": "x (m)", "min": 0, "max": 6},
    "y": {"label": "V (kN)"},
    "series": [
        {
            "label": "V(x)",
            "pieces": [
                {"expr": "8", "from": 0, "to": 2},
                {"expr": "8 - 4*(x - 2)", "from": 2, "to": 6},
            ],
            "fill": True,
        }
    ],
    "markers": [{"x": 2, "label": "P = 10 kN"}, {"x": 99, "label": "off the chart"}],
}


def _plot(spec: dict[str, Any]) -> Any:
    return parse_plot(json.dumps(spec))


def test_piecewise_shear_diagram_is_sampled_with_the_jump_kept() -> None:
    figure = _plot(SHEAR)

    assert (figure.x_min, figure.x_max, figure.x_label, figure.y_label) == (0, 6, "x (m)", "V (kN)")
    (series,) = figure.series
    assert series.fill and series.style == "line"
    assert series.points[0] == (0.0, 8.0)
    assert series.points[-1] == (6.0, -8.0)
    # Both pieces are evaluated at x = 2, so the plot reaches the boundary from each side.
    assert [y for x, y in series.points if x == 2.0] == [8.0, 8.0]
    assert [marker.label for marker in figure.markers] == ["P = 10 kN"]


def test_formula_series_spans_the_x_axis() -> None:
    figure = _plot(
        {"x": {"min": -3, "max": 3}, "series": [{"label": "pdf", "expr": "exp(-x^2/2)"}]}
    )

    points = figure.series[0].points
    assert len(points) == SAMPLES
    assert points[0][0] == -3.0 and points[-1][0] == 3.0
    assert max(y for _, y in points if y is not None) == pytest.approx(1.0, abs=1e-3)


def test_shade_adds_a_filled_region_without_a_legend_entry() -> None:
    spec = {
        "x": {"min": -3, "max": 3},
        "series": [{"label": "Normal", "expr": "exp(-x^2/2)", "shade": {"from": 1, "to": 5}}],
    }
    curve, shaded = _plot(spec).series

    assert curve.legend and not curve.fill
    assert shaded.fill and not shaded.legend
    assert shaded.points[0][0] == 1.0 and shaded.points[-1][0] == 3.0


def test_points_are_dots_and_set_the_range_when_no_axis_is_given() -> None:
    figure = _plot({"series": [{"label": "data", "points": [[3, 1], [1, 2], [2, 4]]}]})

    assert (figure.x_min, figure.x_max) == (1, 3)
    assert figure.series[0].style == "points"
    assert figure.series[0].points == [(1.0, 2.0), (2.0, 4.0), (3.0, 1.0)]


def test_asymptotes_and_gaps_between_pieces_break_the_line() -> None:
    figure = _plot(
        {
            "x": {"min": -1, "max": 1},
            "series": [
                {"expr": "1/x"},
                {
                    "pieces": [
                        {"expr": "1", "from": -1, "to": -0.5},
                        {"expr": "2", "from": 0.5, "to": 1},
                    ]
                },
            ],
        }
    )
    reciprocal, gapped = figure.series

    assert len(reciprocal.points) == SAMPLES  # x = 0 is not sampled with 200 points
    assert (-0.5, None) in gapped.points


def test_unknown_keys_are_ignored() -> None:
    spec = {**SHEAR, "theme": "dark"}
    assert _plot(spec).title == SHEAR["title"]


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ("not json", "invalid plot spec"),
        ({"series": []}, "series"),
        ({"x": {"min": 0, "max": 1}, "series": [{"expr": "x", "points": [[0, 1]]}]}, "exactly one"),
        ({"series": [{"expr": "x"}]}, "x.min and x.max"),
        ({"x": {"min": 2, "max": 1}, "series": [{"expr": "x"}]}, "below"),
        (
            {"x": {"min": 0, "max": 1}, "y": {"min": 1, "max": 0}, "series": [{"expr": "x"}]},
            "y.min",
        ),
        ({"x": {"min": 0, "max": 1}, "series": [{"expr": "__import__('os')"}]}, "unknown function"),
        ({"x": {"min": -2, "max": -1}, "series": [{"expr": "sqrt(x)"}]}, "nothing to draw"),
        ({"x": {"min": 0, "max": 1}, "series": [{"expr": "x"}] * 7}, "series"),
    ],
)
def test_bad_specs_are_rejected(spec: Any, reason: str) -> None:
    text = spec if isinstance(spec, str) else json.dumps(spec)
    with pytest.raises(FigureError, match=reason):
        parse_plot(text)


CONCEPT_MAP = """
flowchart LR
  w[Distributed load w] -->|dV/dx = -w| V[Shear force V]
  V -->|dM/dx = V| M[Bending moment M]
"""


def test_concept_diagram_is_kept_trimmed() -> None:
    figure = parse_diagram(CONCEPT_MAP)

    assert figure.kind == "diagram"
    assert figure.source.startswith("flowchart LR")


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("", "empty"),
        ('pie title Pets\n  "Dogs" : 3', "unsupported diagram type"),
        ("%%{init: {'securityLevel': 'loose'}}%%\nflowchart LR\n  a --> b", "unsupported"),
        ("flowchart LR\n  %%{init: {'securityLevel': 'loose'}}%%\n  a --> b", "directives"),
        ("flowchart LR\n  a --> b\n  click a callback", "directives"),
        ("flowchart LR\n  a[javascript:alert(1)] --> b", "directives"),
        ("flowchart LR\n" + "  a --> b\n" * 70, "too large"),
    ],
)
def test_unsafe_or_unsupported_diagrams_are_rejected(source: str, reason: str) -> None:
    with pytest.raises(FigureError, match=reason):
        parse_diagram(source)


def _block(kind: str, body: str) -> str:
    return f"```{kind}\n{body}\n```"


def test_figure_blocks_become_numbered_placeholders() -> None:
    answer = "\n\n".join(
        [
            "## Shear force",
            _block("plot", json.dumps(SHEAR)),
            "How the quantities connect:",
            _block("mermaid", CONCEPT_MAP.strip()),
            "```python\nprint('code stays')\n```",
        ]
    )

    text, figures = extract_figures(answer)

    assert [figure.kind for figure in figures] == ["plot", "diagram"]
    assert "```figure\n0\n```" in text and "```figure\n1\n```" in text
    assert "print('code stays')" in text
    assert '"series"' not in text


def test_broken_figures_are_dropped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    answer = "Before\n\n" + _block("plot", "{not json") + "\n\nAfter"

    text, figures = extract_figures(answer)

    assert figures == []
    assert text == "Before\n\nAfter"
    assert "Left a plot out of the answer" in caplog.text


def test_only_the_first_figures_are_kept() -> None:
    answer = "\n\n".join(_block("mermaid", "flowchart LR\n  a --> b") for _ in range(6))

    text, figures = extract_figures(answer)

    assert len(figures) == MAX_FIGURES
    assert text.count("```figure") == MAX_FIGURES


def test_source_blocks_are_resolved_by_the_caller_and_counted_apart() -> None:
    def resolve(block: str) -> SourceFigure:
        spec = json.loads(block)
        if spec["file"] == "unknown.pdf":
            raise FigureError("not a file among the passages")
        return SourceFigure(title="Problem Set 2", filename=spec["file"], question=spec["question"])

    sources = [
        _block("source", json.dumps({"file": "set.pdf", "question": f"Problem {n}"}))
        for n in range(MAX_SOURCES + 2)
    ]
    unknown = _block("source", json.dumps({"file": "unknown.pdf", "question": "Problem 1"}))
    drawing = _block("mermaid", "flowchart LR\n  a --> b")

    text, figures = extract_figures("\n\n".join([unknown, *sources, drawing]), resolve)

    # Sources have their own limit, so a practice set still gets its drawings.
    assert [figure.kind for figure in figures] == ["source"] * MAX_SOURCES + ["diagram"]
    assert isinstance(figures[0], SourceFigure) and figures[0].question == "Problem 0"
    assert text.count("```figure") == MAX_SOURCES + 1 and "```source" not in text

    # Without files to check against, a source block is dropped like any broken figure.
    text, figures = extract_figures(sources[0] + "\n\nAfter")
    assert (text, figures) == ("After", [])


def test_svg_sketches_are_sanitized_and_titled() -> None:
    sketch = (
        '<svg viewBox="0 0 100 60"><title>Block on a table</title>'
        '<rect x="30" y="20" width="40" height="20" onclick="alert(1)"/>'
        "<script>alert(1)</script></svg>"
    )

    text, figures = extract_figures("Free body:\n\n" + _block("svg", sketch))

    (figure,) = figures
    assert isinstance(figure, SketchFigure)
    assert figure.title == "Block on a table"
    assert "<rect" in figure.svg and "onclick" not in figure.svg and "script" not in figure.svg
    assert text == "Free body:\n\n```figure\n0\n```"


def test_unreadable_svg_is_dropped() -> None:
    text, figures = extract_figures(_block("svg", "<svg><rect></svg>"))

    assert figures == [] and text == ""


def test_stems_draw_each_value_from_zero_with_a_dot() -> None:
    spec = {
        "title": "Cash flows",
        "x": {"label": "year", "min": 0, "max": 3},
        "series": [
            {
                "label": "cash flow",
                "points": [[0, -1000], [1, 400], [2, 400], [3, 400]],
                "stems": True,
            }
        ],
    }

    figure = _plot(spec)
    lines, tops = figure.series

    assert figure.x_min < 0 and figure.x_max > 3  # padded so edge stems show in full

    assert lines.style == "line" and lines.legend
    assert lines.points[:3] == [(0.0, 0.0), (0.0, -1000.0), (0.0, None)]
    assert tops.style == "points" and not tops.legend
    assert tops.points == [(0.0, -1000.0), (1.0, 400.0), (2.0, 400.0), (3.0, 400.0)]


def test_stem_formulas_are_evaluated_at_whole_numbers() -> None:
    spec = {
        "x": {"min": 0, "max": 4},
        "series": [
            {"label": "x[n]", "pieces": [{"expr": "0.5^x", "from": 0, "to": 4}], "stems": True}
        ],
    }

    _, tops = _plot(spec).series

    # A discrete signal x[n] = 0.5^n is evaluated at whole numbers only.
    assert tops.points == [(0.0, 1.0), (1.0, 0.5), (2.0, 0.25), (3.0, 0.125), (4.0, 0.0625)]
