"""Validate the graphs a tutor answer asks for and compute the points to draw."""

import json
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.chat import PlotFigure, PlotMarker, PlotSeries
from app.services.plot_math import Formula, FormulaError, compile_formula

SAMPLES = 200
# Values beyond this are treated as off the chart (asymptotes such as tan(x)).
_LIMIT = 1e9


class FigureError(ValueError):
    """A figure in a tutor answer cannot be drawn and is left out."""


# Model-written specs ignore unknown keys so one stray field does not cost the graph.
class _Spec(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AxisSpec(_Spec):
    label: str = Field(default="", max_length=60)
    min: float | None = None
    max: float | None = None


class RangeSpec(_Spec):
    start: float = Field(alias="from")
    end: float = Field(alias="to")


class PieceSpec(RangeSpec):
    expr: str


class SeriesSpec(_Spec):
    label: str = Field(default="", max_length=60)
    expr: str | None = None
    pieces: list[PieceSpec] | None = Field(default=None, min_length=1, max_length=12)
    points: list[tuple[float, float]] | None = Field(default=None, min_length=1, max_length=200)
    # Points are drawn as dots unless "line" is true; formulas are always lines.
    line: bool | None = None
    fill: bool = False
    shade: RangeSpec | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "SeriesSpec":
        sources = [self.expr is not None, self.pieces is not None, self.points is not None]
        if sum(sources) != 1:
            raise ValueError("a series needs exactly one of expr, pieces or points")
        return self


class MarkerSpec(_Spec):
    x: float
    y: float | None = None
    label: str = Field(default="", max_length=60)


class PlotSpec(_Spec):
    title: str = Field(default="", max_length=120)
    x: AxisSpec = Field(default_factory=AxisSpec)
    y: AxisSpec = Field(default_factory=AxisSpec)
    series: list[SeriesSpec] = Field(min_length=1, max_length=6)
    markers: list[MarkerSpec] = Field(default_factory=list, max_length=8)


def parse_plot(text: str) -> PlotFigure:
    """Read a ```plot block's JSON and return the figure to draw, or raise FigureError."""

    try:
        spec = PlotSpec.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise FigureError(f"invalid plot spec: {_first_error(exc)}") from exc
    try:
        return build_plot(spec)
    except FormulaError as exc:
        raise FigureError(str(exc)) from exc


def build_plot(spec: PlotSpec) -> PlotFigure:
    x_min, x_max = _x_range(spec)
    series: list[PlotSeries] = []
    for item in spec.series:
        points = _series_points(item, x_min, x_max)
        if all(y is None for _, y in points):
            raise FigureError(f"nothing to draw for series {item.label or '(unnamed)'}")
        is_dots = item.points is not None and not item.line
        series.append(
            PlotSeries(
                label=item.label,
                points=points,
                style="points" if is_dots else "line",
                fill=item.fill,
            )
        )
        if item.shade:
            start = max(min(item.shade.start, item.shade.end), x_min)
            end = min(max(item.shade.start, item.shade.end), x_max)
            if start < end:
                series.append(
                    PlotSeries(
                        label=f"{item.label} (shaded)".strip(),
                        points=_series_points(item, start, end),
                        fill=True,
                        legend=False,
                    )
                )
    if spec.y.min is not None and spec.y.max is not None and spec.y.min >= spec.y.max:
        raise FigureError("y.min must be below y.max")
    return PlotFigure(
        title=spec.title,
        x_label=spec.x.label,
        y_label=spec.y.label,
        x_min=x_min,
        x_max=x_max,
        y_min=spec.y.min,
        y_max=spec.y.max,
        series=series,
        markers=[
            PlotMarker(x=marker.x, y=marker.y, label=marker.label)
            for marker in spec.markers
            if x_min <= marker.x <= x_max
        ],
    )


def _x_range(spec: PlotSpec) -> tuple[float, float]:
    starts: list[float] = []
    ends: list[float] = []
    for item in spec.series:
        if item.pieces:
            starts += [piece.start for piece in item.pieces]
            ends += [piece.end for piece in item.pieces]
        if item.points:
            starts += [x for x, _ in item.points]
            ends += [x for x, _ in item.points]
    x_min = spec.x.min if spec.x.min is not None else min(starts, default=None)
    x_max = spec.x.max if spec.x.max is not None else max(ends, default=None)
    if x_min is None or x_max is None:
        raise FigureError("x.min and x.max are needed to plot a formula")
    if not x_min < x_max:
        raise FigureError("x.min must be below x.max")
    return x_min, x_max


def _series_points(item: SeriesSpec, start: float, end: float) -> list[tuple[float, float | None]]:
    if item.points is not None:
        inside = sorted((x, y) for x, y in item.points if start <= x <= end)
        return [(_round(x), _y(y)) for x, y in inside]
    if item.expr is not None:
        return _sample(compile_formula(item.expr), start, end, SAMPLES)
    points: list[tuple[float, float | None]] = []
    width = end - start
    previous_end: float | None = None
    for piece in sorted(item.pieces or [], key=lambda piece: piece.start):
        lo, hi = max(piece.start, start), min(piece.end, end)
        if lo >= hi:
            continue
        if previous_end is not None and lo > previous_end:
            points.append((_round(previous_end), None))
        count = max(20, round(SAMPLES * (hi - lo) / width))
        # At a shared boundary the two pieces' values draw the jump as a vertical line.
        points += _sample(compile_formula(piece.expr), lo, hi, count)
        previous_end = hi
    return points


def _sample(
    formula: Formula, start: float, end: float, count: int
) -> list[tuple[float, float | None]]:
    step = (end - start) / (count - 1)
    return [(_round(start + i * step), _y(formula(start + i * step))) for i in range(count)]


def _y(value: float) -> float | None:
    if math.isnan(value) or abs(value) > _LIMIT:
        return None
    return _round(value)


def _round(value: float) -> float:
    return float(f"{value:.6g}")


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error: Any = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        return f"{where}: {error['msg']}" if where else str(error["msg"])
    return str(exc)
