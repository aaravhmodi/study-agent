import json
from typing import Any

import pytest
from app.services.figures import SAMPLES, FigureError, parse_plot

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
