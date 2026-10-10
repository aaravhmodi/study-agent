"""Validate the figures a tutor answer asks for: graphs, concept diagrams and sketches."""

import json
import logging
import math
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.chat import (
    ChatFigure,
    DiagramFigure,
    PlotFigure,
    PlotMarker,
    PlotSeries,
    SketchFigure,
)
from app.services.circuit import CircuitError, render_circuit
from app.services.fbd import FbdError, render_fbd
from app.services.plot_math import Formula, FormulaError, compile_formula
from app.services.svg_safe import SvgError, sanitize_svg

logger = logging.getLogger(__name__)

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
    # Discrete values (x[n], a probability mass function, cash flows) as stems from zero.
    stems: bool = False
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
        if item.stems and item.points is None:
            points = _integer_points(item, x_min, x_max)
        else:
            points = _series_points(item, x_min, x_max)
        if all(y is None for _, y in points):
            raise FigureError(f"nothing to draw for series {item.label or '(unnamed)'}")
        if item.stems:
            series += _stems(item.label, points)
            continue
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
    pad = (x_max - x_min) * 0.04 if any(item.stems for item in spec.series) else 0.0
    return PlotFigure(
        title=spec.title,
        x_label=spec.x.label,
        y_label=spec.y.label,
        # Stems at the very edge would be cut in half by the frame.
        x_min=x_min - pad,
        x_max=x_max + pad,
        y_min=spec.y.min,
        y_max=spec.y.max,
        series=series,
        markers=[
            PlotMarker(x=marker.x, y=marker.y, label=marker.label)
            for marker in spec.markers
            if x_min <= marker.x <= x_max
        ],
    )


_DIAGRAM_TYPES = ("flowchart", "graph", "mindmap", "stateDiagram", "stateDiagram-v2", "timeline")
# Init directives can change Mermaid's config, and click lines attach links or callbacks.
_UNSAFE_DIAGRAM = re.compile(r"%%\{|^\s*click\b|javascript:|<script", re.IGNORECASE | re.MULTILINE)
MAX_DIAGRAM_LENGTH = 2000
MAX_DIAGRAM_LINES = 60


def parse_diagram(text: str) -> DiagramFigure:
    """Check a ```mermaid block is a small concept diagram, or raise FigureError."""

    source = text.strip()
    lines = [line for line in source.splitlines() if line.strip()]
    if not lines:
        raise FigureError("empty diagram")
    if len(source) > MAX_DIAGRAM_LENGTH or len(lines) > MAX_DIAGRAM_LINES:
        raise FigureError("diagram too large")
    kind = lines[0].split()[0]
    if kind not in _DIAGRAM_TYPES:
        raise FigureError(f"unsupported diagram type {kind!r}")
    if _UNSAFE_DIAGRAM.search(source):
        raise FigureError("diagram uses directives, links or scripts")
    return DiagramFigure(source=source)


def _integer_points(item: SeriesSpec, start: float, end: float) -> list[tuple[float, float | None]]:
    """Evaluate a formula at whole numbers only: a discrete signal x[n] or a PMF."""

    first, last = math.ceil(start), math.floor(end)
    if last - first > SAMPLES:
        raise FigureError("too many stems; use a smaller x range")
    pieces = (
        [(item.expr, start, end)]
        if item.expr is not None
        else [(piece.expr, piece.start, piece.end) for piece in item.pieces or []]
    )
    formulas = [(compile_formula(expr), lo, hi) for expr, lo, hi in pieces]
    points: list[tuple[float, float | None]] = []
    for n in range(first, last + 1):
        formula = next((f for f, lo, hi in formulas if lo <= n <= hi), None)
        if formula is not None:
            points.append((float(n), _y(formula(float(n)))))
    return points


def _stems(label: str, points: list[tuple[float, float | None]]) -> list[PlotSeries]:
    """A vertical line from zero to each value, broken between stems, with a dot on top."""

    lines: list[tuple[float, float | None]] = []
    for x, y in points:
        if y is not None:
            lines += [(x, 0.0), (x, y), (x, None)]
    tops: list[tuple[float, float | None]] = [(x, y) for x, y in points if y is not None]
    return [
        PlotSeries(label=label, points=lines),
        PlotSeries(label=f"{label} (values)".strip(), points=tops, style="points", legend=False),
    ]


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


def parse_sketch(text: str) -> SketchFigure:
    """Keep a model-drawn ```svg sketch after stripping anything but drawing markup."""

    try:
        svg = sanitize_svg(text)
    except SvgError as exc:
        raise FigureError(str(exc)) from exc
    title = re.search(r"<title>([^<]{1,120})</title>", svg)
    return SketchFigure(title=title.group(1).strip() if title else "", svg=svg)


def parse_fbd(text: str) -> SketchFigure:
    """Draw a ```fbd free-body description as a sketch."""

    try:
        title, svg = render_fbd(text)
        return SketchFigure(title=title, svg=sanitize_svg(svg))
    except (FbdError, SvgError) as exc:
        raise FigureError(str(exc)) from exc


def parse_circuit(text: str) -> SketchFigure:
    """Draw a ```circuit parts list as a schematic sketch."""

    try:
        title, svg = render_circuit(text)
        return SketchFigure(title=title, svg=sanitize_svg(svg))
    except (CircuitError, SvgError) as exc:
        raise FigureError(str(exc)) from exc


_PARSERS: dict[str, Callable[[str], ChatFigure]] = {
    "plot": parse_plot,
    "mermaid": parse_diagram,
    "svg": parse_sketch,
    "fbd": parse_fbd,
    "circuit": parse_circuit,
}

MAX_FIGURES = 4
# Course questions shown from the student's files; a practice set cites several.
MAX_SOURCES = 6
_FIGURE_BLOCK = re.compile(
    rf"^[ \t]*```[ \t]*({'|'.join(_PARSERS)}|source)[ \t]*\r?\n(.*?)\r?\n[ \t]*```[ \t]*$",
    flags=re.MULTILINE | re.DOTALL,
)


def extract_figures(
    answer: str, source: Callable[[str], ChatFigure] | None = None
) -> tuple[str, list[ChatFigure]]:
    """Swap each valid figure block (```plot, ```mermaid, ```svg) for a ```figure placeholder.

    The placeholder holds the figure's index in the returned list. Blocks that
    cannot be drawn are removed so the student never sees raw JSON. A ```source
    block is resolved by ``source``, which knows the course files the answer may cite.
    """

    figures: list[ChatFigure] = []
    counts = {"source": 0, "drawn": 0}

    def replace(match: re.Match[str]) -> str:
        kind, body = match.group(1), match.group(2)
        group, limit = ("source", MAX_SOURCES) if kind == "source" else ("drawn", MAX_FIGURES)
        parser = source if kind == "source" else _PARSERS[kind]
        if parser is None or counts[group] >= limit:
            return ""
        try:
            figure = parser(body)
        except FigureError as exc:
            logger.warning("Left a %s out of the answer: %s", kind, exc)
            return ""
        counts[group] += 1
        figures.append(figure)
        return f"```figure\n{len(figures) - 1}\n```"

    text = _FIGURE_BLOCK.sub(replace, answer)
    return re.sub(r"\n{3,}", "\n\n", text).strip(), figures
