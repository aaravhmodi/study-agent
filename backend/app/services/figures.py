"""Validate the figures a tutor answer asks for: graphs, concept diagrams and sketches."""

import json
import logging
import math
import re
from collections.abc import Callable
from typing import Any, Literal

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
from app.services.practice import QuizError, parse_quiz, quiz_blocks
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
    # "log" for frequency responses (Bode plots) and anything spanning decades.
    scale: Literal["linear", "log"] = "linear"


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
    # Bars centred on each value: a histogram, a bar chart or a PMF; "width" defaults to
    # the closest spacing between values.
    bars: bool = False
    width: float | None = Field(default=None, gt=0)
    fill: bool = False
    # One range, or several for both tails of a two-sided test.
    shade: RangeSpec | list[RangeSpec] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "SeriesSpec":
        sources = [self.expr is not None, self.pieces is not None, self.points is not None]
        if sum(sources) != 1:
            raise ValueError("a series needs exactly one of expr, pieces or points")
        if self.stems and self.bars:
            raise ValueError("a series is drawn as stems or bars, not both")
        if isinstance(self.shade, list) and len(self.shade) > 4:
            raise ValueError("at most 4 shaded ranges")
        return self

    @property
    def discrete(self) -> bool:
        return self.stems or self.bars

    @property
    def shades(self) -> list[RangeSpec]:
        if self.shade is None:
            return []
        return self.shade if isinstance(self.shade, list) else [self.shade]


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
    log_x, log_y = spec.x.scale == "log", spec.y.scale == "log"
    if log_x and x_min <= 0:
        raise FigureError("a log x axis needs x.min above zero")
    if log_y and any(value is not None and value <= 0 for value in (spec.y.min, spec.y.max)):
        raise FigureError("a log y axis needs y.min and y.max above zero")
    series: list[PlotSeries] = []
    # Where bars reach past the values they are centred on.
    edges: list[float] = []
    for item in spec.series:
        if item.discrete and item.points is None:
            points = _integer_points(item, x_min, x_max)
        else:
            points = _series_points(item, x_min, x_max, log_x)
        if log_y:
            # Zero and negative values have no place on a log axis.
            points = [(x, y if y is not None and y > 0 else None) for x, y in points]
        if all(y is None for _, y in points):
            raise FigureError(f"nothing to draw for series {item.label or '(unnamed)'}")
        if item.stems:
            series += _stems(item.label, points)
            continue
        if item.bars:
            series.append(_bars(item.label, points, item.width))
            # A log axis cannot reach below zero, so there bars may be cut at the frame.
            if not log_x:
                edges += [x for x, _ in series[-1].points]
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
        for shade in item.shades:
            start = max(min(shade.start, shade.end), x_min)
            end = min(max(shade.start, shade.end), x_max)
            if start < end:
                series.append(
                    PlotSeries(
                        label=f"{item.label} (shaded)".strip(),
                        points=_series_points(item, start, end, log_x),
                        fill=True,
                        legend=False,
                    )
                )
    if spec.y.min is not None and spec.y.max is not None and spec.y.min >= spec.y.max:
        raise FigureError("y.min must be below y.max")
    discrete = any(item.discrete for item in spec.series) and not log_x
    pad = (x_max - x_min) * 0.04 if discrete else 0.0
    return PlotFigure(
        title=spec.title,
        x_label=spec.x.label,
        y_label=spec.y.label,
        x_scale=spec.x.scale,
        y_scale=spec.y.scale,
        # Stems or bars at the very edge would be cut in half by the frame.
        x_min=min([x_min, *edges]) - pad,
        x_max=max([x_max, *edges]) + pad,
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


def _bars(label: str, points: list[tuple[float, float | None]], width: float | None) -> PlotSeries:
    """One filled outline tracing a bar centred on each value, from zero to its height."""

    values = sorted((x, y) for x, y in points if y is not None)
    gaps = [b[0] - a[0] for a, b in zip(values, values[1:], strict=False) if b[0] > a[0]]
    half = (width if width is not None else min(gaps, default=1.0)) / 2
    outline: list[tuple[float, float | None]] = []
    for x, y in values:
        outline += [
            (_round(x - half), 0.0),
            (_round(x - half), y),
            (_round(x + half), y),
            (_round(x + half), 0.0),
        ]
    return PlotSeries(label=label, points=outline, fill=True)


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


def _series_points(
    item: SeriesSpec, start: float, end: float, log: bool = False
) -> list[tuple[float, float | None]]:
    if item.points is not None:
        inside = sorted((x, y) for x, y in item.points if start <= x <= end)
        return [(_round(x), _y(y)) for x, y in inside]
    if item.expr is not None:
        return _sample(compile_formula(item.expr), start, end, SAMPLES, log)
    points: list[tuple[float, float | None]] = []
    # On a log axis a piece's share of the samples follows its share of the decades.
    scale: Callable[[float], float] = math.log if log else float
    width = scale(end) - scale(start)
    previous_end: float | None = None
    for piece in sorted(item.pieces or [], key=lambda piece: piece.start):
        lo, hi = max(piece.start, start), min(piece.end, end)
        if lo >= hi:
            continue
        if previous_end is not None and lo > previous_end:
            points.append((_round(previous_end), None))
        count = max(20, round(SAMPLES * (scale(hi) - scale(lo)) / width))
        # At a shared boundary the two pieces' values draw the jump as a vertical line.
        points += _sample(compile_formula(piece.expr), lo, hi, count, log)
        previous_end = hi
    return points


def _sample(
    formula: Formula, start: float, end: float, count: int, log: bool = False
) -> list[tuple[float, float | None]]:
    if log:
        # Evenly spaced in decades, so each decade of a Bode plot gets the same detail.
        ratio = (end / start) ** (1 / (count - 1))
        xs = [start * ratio**i for i in range(count)]
    else:
        step = (end - start) / (count - 1)
        xs = [start + i * step for i in range(count)]
    return [(_round(x), _y(formula(x))) for x in xs]


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
# Practice questions answered on the page; a practice set is mostly these.
MAX_QUIZZES = 24
_FIGURE_BLOCK = re.compile(
    rf"^[ \t]*```[ \t]*({'|'.join(_PARSERS)}|source)[ \t]*\r?\n(.*?)\r?\n[ \t]*```[ \t]*$",
    flags=re.MULTILINE | re.DOTALL,
)


def _with_quizzes(answer: str, figures: list[ChatFigure]) -> str:
    """Swap each ```quiz block for a placeholder, adding its question to ``figures``."""

    pieces: list[str] = []
    end = 0
    for start, stop, body in quiz_blocks(answer):
        pieces.append(answer[end:start])
        end = stop
        try:
            if sum(figure.kind == "quiz" for figure in figures) >= MAX_QUIZZES:
                raise QuizError("too many questions in one answer")
            figures.append(parse_quiz(body))
        except (QuizError, ValidationError) as exc:
            # Kept as the text it was, so the question is not lost; the block's start
            # is logged to show what the tutor wrote instead of the format.
            logger.warning(
                "Showed a practice question as plain text: %s (it began %r)", exc, body[:160]
            )
            pieces.append(body if body.endswith("\n") else body + "\n")
            continue
        pieces.append(f"```figure\n{len(figures) - 1}\n```\n")
    pieces.append(answer[end:])
    return "".join(pieces)


def extract_figures(
    answer: str, source: Callable[[str], ChatFigure] | None = None
) -> tuple[str, list[ChatFigure]]:
    """Swap each valid figure block (```plot, ```mermaid, ```svg) for a ```figure placeholder.

    The placeholder holds the figure's index in the returned list. Blocks that
    cannot be drawn are removed so the student never sees raw JSON. A ```source
    block is resolved by ``source``, which knows the course files the answer may cite.
    A ```quiz block that cannot be read stays in the answer as the text it was, so
    the question is not lost.
    """

    figures: list[ChatFigure] = []
    counts = {"source": 0, "drawn": 0}
    # Practice questions first: one about code holds a fenced block of its own, which
    # the pattern for the other kinds would take for the end of the question.
    answer = _with_quizzes(answer, figures)

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
