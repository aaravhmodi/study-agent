import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.config import Settings
from app.schemas.chat import PlotFigure
from app.services.course_figures import (
    ECONOMICS,
    SIGNALS,
    STATISTICS,
    course_figure_guide,
)
from app.services.figures import extract_figures
from app.services.rag import RagService

from tests.fake_openai import FakeVectorStores
from tests.test_shear_force_tutor import FakeResponses


def _plots(guide: str) -> list[PlotFigure]:
    text, figures = extract_figures(guide)
    # Every example renders: none is dropped, and no raw JSON is left in the text.
    assert "```plot" not in text
    assert all(isinstance(figure, PlotFigure) for figure in figures)
    return [figure for figure in figures if isinstance(figure, PlotFigure)]


def test_statistics_examples_shade_both_tails_and_draw_a_pmf() -> None:
    test, pmf = _plots(STATISTICS)

    curve, left, right = test.series
    assert (left.points[-1][0], right.points[0][0]) == (-1.96, 1.96)
    assert max(y for _, y in curve.points if y is not None) == pytest.approx(0.3989, abs=1e-3)
    (bars,) = pmf.series
    assert bars.fill and max(y for _, y in bars.points if y is not None) == pytest.approx(
        0.26683, abs=1e-5
    )


def test_signals_examples_draw_a_bode_plot_and_a_convolution() -> None:
    bode, convolution = _plots(SIGNALS)

    assert bode.x_scale == "log"
    magnitude = dict(bode.series[0].points)
    assert magnitude[1.0] == pytest.approx(0, abs=1e-3)
    assert magnitude[10000.0] == pytest.approx(-40, abs=0.01)
    assert [marker.y for marker in bode.markers] == [-3.01]
    pulse, triangle = (dict(series.points) for series in convolution.series)
    assert {y for x, y in pulse.items() if abs(x) < 0.45} == {1.0}
    assert {y for x, y in pulse.items() if abs(x) > 0.55} == {0.0}
    # rect(t) * rect(t) peaks at 1 when the pulses overlap fully and ends at t = ±1.
    assert max(y for y in triangle.values() if y is not None) == pytest.approx(1.0, abs=0.02)
    assert {y for x, y in triangle.items() if abs(x) >= 1} == {0.0}


def test_economics_examples_draw_cash_flows_and_mark_the_irr_on_the_curve() -> None:
    flows, worth = _plots(ECONOMICS)

    assert [y for _, y in flows.series[1].points] == [-1000, 300, 300, 300, 300, 300]
    curve = dict(worth.series[0].points)
    assert curve[0.0] == pytest.approx(500)
    irr = next(marker for marker in worth.markers if marker.y == 0)
    # Present worth changes sign at the marked IRR.
    below = [y for x, y in curve.items() if y is not None and x < irr.x - 0.005]
    above = [y for x, y in curve.items() if y is not None and x > irr.x + 0.005]
    assert min(below) > 0 and max(above) < 0


@pytest.mark.parametrize(
    ("course", "guide"),
    [
        ("SYDE 212", STATISTICS),
        (" syde  252 ", SIGNALS),
        ("SYDE 262", ECONOMICS),
        ("STAT 230", STATISTICS),
        ("ECON101", ECONOMICS),
        ("SYDE 286", None),
        (None, None),
    ],
)
def test_each_course_gets_its_own_graphs(course: str | None, guide: str | None) -> None:
    assert course_figure_guide(course) == guide


def _service(tmp_path: Path, responses: FakeResponses) -> RagService:
    service = RagService(
        Settings(openai_api_key="test-key"),
        client=SimpleNamespace(responses=responses, vector_stores=FakeVectorStores()),  # type: ignore[arg-type]
    )
    service.manifest_path = tmp_path / "manifest.json"
    files = {"r1": {"course_code": "SYDE 262"}, "r2": {"course_code": "SYDE 286"}}
    service.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": files}), encoding="utf-8"
    )
    return service


def test_course_graphs_are_sent_only_with_that_courses_questions(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)

    service.ask("Explain present worth.", "SYDE 262")
    service.ask("What does the SYDE 262 midterm cover for present worth?")
    service.ask("Explain shear force.", "SYDE 286")

    economics, named, shear = (call["input"] for call in responses.calls)
    assert economics.startswith(f"Course: SYDE 262\n{ECONOMICS}\nQuestion: Explain present worth.")
    assert ECONOMICS in named
    assert "Graphs for this" not in shear
