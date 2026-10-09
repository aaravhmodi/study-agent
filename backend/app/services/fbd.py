"""Draw free-body diagrams from a small JSON description written by the tutor.

The tutor names a body (beam, block, particle or disk), the forces and moments on
it, supports, distributed loads and dimensions; the geometry is computed here so
arrows point the right way and nothing overlaps the body. Angles are degrees
counter-clockwise from +x in the global frame (gravity points at 270).
"""

import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

INK = "#1d1b18"
INK_2 = "#55504a"
PENCIL = "#b4381f"
FONT = "IBM Plex Sans, system-ui, sans-serif"
ARROW = 70.0  # pixels for a force of relative length 1

ToPixels = Callable[[float, float], tuple[float, float]]


class FbdError(ValueError):
    """The free-body description is invalid."""


class _Spec(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class BodySpec(_Spec):
    shape: Literal["beam", "block", "particle", "disk"] = "block"
    # Beam length, or block width, in the problem's own units.
    length: float = Field(default=4.0, gt=0, le=1000)
    height: float = Field(default=1.0, gt=0, le=1000)
    label: str = Field(default="", max_length=40)


class ForceSpec(_Spec):
    label: str = Field(default="", max_length=40)
    # Point of application in body units: beams use x from the left end; blocks
    # and disks use (x, y) from the centre, in the body's own (tilted) frame.
    at: tuple[float, float] = (0.0, 0.0)
    angle: float = Field(ge=-360, le=360)
    length: float = Field(default=1.0, gt=0, le=3)
    # Pushes are drawn with the arrow tip on the point; pulls start there.
    tip: bool = False
    kind: Literal["applied", "reaction"] = "applied"


class MomentSpec(_Spec):
    label: str = Field(default="", max_length=40)
    at: tuple[float, float] = (0.0, 0.0)
    direction: Literal["ccw", "cw"] = "ccw"
    kind: Literal["applied", "reaction"] = "applied"


class SupportSpec(_Spec):
    x: float
    type: Literal["pin", "roller", "fixed"]


class LoadSpec(_Spec):
    """A distributed load pressing down on a beam between two points."""

    label: str = Field(default="", max_length=40)
    start: float = Field(alias="from")
    end: float = Field(alias="to")
    # Relative intensity at each end: 1 and 1 for uniform, 0 and 1 for a triangle.
    w_start: float = Field(default=1.0, ge=0, le=3)
    w_end: float = Field(default=1.0, ge=0, le=3)


class DimensionSpec(_Spec):
    label: str = Field(max_length=40)
    start: float = Field(alias="from")
    end: float = Field(alias="to")


class FbdSpec(_Spec):
    title: str = Field(default="", max_length=120)
    body: BodySpec = Field(default_factory=BodySpec)
    # Surface tilt under a block, degrees; the block sits on the slope.
    incline: float = Field(default=0.0, ge=-80, le=80)
    # Draw the surface a block rests on; defaults to on when there is an incline.
    surface: bool | None = None
    forces: list[ForceSpec] = Field(default_factory=list, max_length=12)
    moments: list[MomentSpec] = Field(default_factory=list, max_length=6)
    supports: list[SupportSpec] = Field(default_factory=list, max_length=4)
    loads: list[LoadSpec] = Field(default_factory=list, max_length=4)
    dimensions: list[DimensionSpec] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _has_something_to_draw(self) -> "FbdSpec":
        if not (self.forces or self.moments or self.loads):
            raise ValueError("a free-body diagram needs at least one force, moment or load")
        if self.body.shape != "beam" and (self.supports or self.loads or self.dimensions):
            raise ValueError("supports, distributed loads and dimensions need a beam")
        return self


class _Canvas:
    """Collects SVG elements in pixel space and tracks the drawing's extent."""

    def __init__(self) -> None:
        self.items: list[ET.Element] = []
        self.xs: list[float] = []
        self.ys: list[float] = []

    def _track(self, *points: tuple[float, float]) -> None:
        for x, y in points:
            self.xs.append(x)
            self.ys.append(y)

    def add(self, tag: str, extent: list[tuple[float, float]], **attrs: str) -> None:
        self._track(*extent)
        self.items.append(
            ET.Element(tag, {key.replace("_", "-"): value for key, value in attrs.items()})
        )

    def line(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        colour: str = INK,
        width: float = 2,
        dash: str = "",
    ) -> None:
        attrs = {
            "x1": _f(a[0]),
            "y1": _f(a[1]),
            "x2": _f(b[0]),
            "y2": _f(b[1]),
            "stroke": colour,
            "stroke_width": _f(width),
            "stroke_linecap": "round",
        }
        if dash:
            attrs["stroke_dasharray"] = dash
        self.add("line", [a, b], **attrs)

    def polygon(self, points: list[tuple[float, float]], fill: str, stroke: str = "none") -> None:
        self.add(
            "polygon",
            points,
            points=" ".join(f"{_f(x)},{_f(y)}" for x, y in points),
            fill=fill,
            stroke=stroke,
            stroke_width="1.5",
        )

    def circle(
        self, centre: tuple[float, float], radius: float, fill: str = "none", stroke: str = INK
    ) -> None:
        x, y = centre
        self.add(
            "circle",
            [(x - radius, y - radius), (x + radius, y + radius)],
            cx=_f(x),
            cy=_f(y),
            r=_f(radius),
            fill=fill,
            stroke=stroke,
            stroke_width="2",
        )

    def path(
        self, d: str, extent: list[tuple[float, float]], colour: str, width: float = 2
    ) -> None:
        self.add(
            "path",
            extent,
            d=d,
            fill="none",
            stroke=colour,
            stroke_width=_f(width),
            stroke_linecap="round",
        )

    def text(
        self,
        at: tuple[float, float],
        label: str,
        colour: str = INK,
        anchor: str = "middle",
        size: int = 13,
    ) -> None:
        if not label:
            return
        x, y = at
        half = len(label) * size * 0.3
        left = {"start": x, "middle": x - half, "end": x - 2 * half}[anchor]
        self._track((left, y - size), (left + 2 * half, y + 4))
        element = ET.Element(
            "text",
            {
                "x": _f(x),
                "y": _f(y),
                "fill": colour,
                "font-size": str(size),
                "font-family": FONT,
                "text-anchor": anchor,
            },
        )
        element.text = label
        self.items.append(element)

    def arrow(self, tail: tuple[float, float], head: tuple[float, float], colour: str) -> None:
        angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
        back = (head[0] - 11 * math.cos(angle), head[1] - 11 * math.sin(angle))
        self.line(tail, back, colour, 2.2)
        wing = math.pi / 7
        self.polygon(
            [
                head,
                (head[0] - 13 * math.cos(angle - wing), head[1] - 13 * math.sin(angle - wing)),
                (head[0] - 13 * math.cos(angle + wing), head[1] - 13 * math.sin(angle + wing)),
            ],
            fill=colour,
        )

    def svg(self, title: str) -> str:
        pad = 16
        left, top = min(self.xs) - pad, min(self.ys) - pad
        width, height = max(self.xs) - left + pad, max(self.ys) - top + pad
        root = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "viewBox": f"{_f(left)} {_f(top)} {_f(width)} {_f(height)}",
                "width": _f(width),
                "height": _f(height),
            },
        )
        if title:
            ET.SubElement(root, "title").text = title
        root.extend(self.items)
        return ET.tostring(root, encoding="unicode")


def render_fbd(text: str) -> tuple[str, str]:
    """Return (title, svg) for a ```fbd block, or raise FbdError."""

    try:
        spec = FbdSpec.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise FbdError(f"invalid free-body diagram: {_reason(exc)}") from exc
    canvas = _Canvas()
    to_px = _draw_body(canvas, spec)
    for load in spec.loads:
        _draw_load(canvas, spec, load)
    for force in spec.forces:
        point = to_px(*force.at)
        if spec.body.shape == "beam":
            point = _beam_contact(spec, force, point)
        _draw_force(canvas, force, point)
    for moment in spec.moments:
        _draw_moment(canvas, moment, to_px(*moment.at))
    _draw_dimensions(canvas, spec, to_px)
    return spec.title, canvas.svg(spec.title)


def _draw_body(canvas: _Canvas, spec: FbdSpec) -> ToPixels:
    body = spec.body
    if body.shape == "beam":
        scale = 440 / body.length
        thick = 2 * BEAM_HALF

        def to_px(x: float, y: float) -> tuple[float, float]:
            return (x * scale, -y * scale)

        canvas.polygon(
            [(0, -thick / 2), (440, -thick / 2), (440, thick / 2), (0, thick / 2)],
            fill="#efe9de",
            stroke=INK,
        )
        for support in spec.supports:
            _draw_support(
                canvas,
                support.type,
                to_px(support.x, 0)[0],
                thick / 2,
                at_end=support.x >= body.length / 2,
            )
        canvas.text((220, thick / 2 + 18 if not spec.supports else -thick / 2 - 8), body.label)
        return to_px
    if body.shape == "particle":
        canvas.circle((0, 0), 5, fill=INK)
        canvas.text((10, -10), body.label, anchor="start")
        return lambda x, y: (0.0, 0.0)
    if body.shape == "disk":
        radius = 60.0
        scale = radius / (body.length / 2)
        canvas.circle((0, 0), radius, fill="#efe9de")
        canvas.circle((0, 0), 2.5, fill=INK)
        canvas.text((0, -8), body.label)
        return lambda x, y: (x * scale, -y * scale)
    # Block, possibly resting on an incline.
    scale = 110 / max(body.length, body.height)
    half_w, half_h = body.length * scale / 2, body.height * scale / 2
    tilt = math.radians(spec.incline)

    def to_px_block(x: float, y: float) -> tuple[float, float]:
        local_x, local_y = x * scale, y * scale
        return (
            local_x * math.cos(tilt) - local_y * math.sin(tilt),
            -(local_x * math.sin(tilt) + local_y * math.cos(tilt)),
        )

    corners = [
        to_px_block(sx * half_w / scale, sy * half_h / scale)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]
    canvas.polygon(corners, fill="#efe9de", stroke=INK)
    if spec.surface if spec.surface is not None else bool(spec.incline):
        # The surface under the block, with hatching on the solid side.
        base = to_px_block(0, -half_h / scale)
        along = (math.cos(tilt), -math.sin(tilt))
        reach = half_w * 2.2
        left_end = (base[0] - along[0] * reach, base[1] - along[1] * reach)
        right_end = (base[0] + along[0] * reach, base[1] + along[1] * reach)
        canvas.line(left_end, right_end, INK_2, 1.5)
        below = (math.sin(tilt), math.cos(tilt))
        for step in range(9):
            t = step / 8
            p = (
                left_end[0] + (right_end[0] - left_end[0]) * t,
                left_end[1] + (right_end[1] - left_end[1]) * t,
            )
            hatch = (p[0] + below[0] * 8 - along[0] * 6, p[1] + below[1] * 8 - along[1] * 6)
            canvas.line(p, hatch, INK_2, 1)
        if spec.incline:
            canvas.text(
                (left_end[0] + 34 * (1 if spec.incline > 0 else -1), left_end[1] - 4),
                f"{abs(spec.incline):g}°",
                INK_2,
                size=12,
            )
    # Off-centre so forces drawn from the centre do not cover it.
    canvas.text(to_px_block(-body.length / 4, body.height / 5), body.label)
    return to_px_block


BEAM_HALF = 7.0
# How far below the beam's underside a support reaches, by type.
_SUPPORT_DEPTH = {"pin": 24.0, "roller": 34.0}


def _beam_contact(
    spec: FbdSpec, force: ForceSpec, point: tuple[float, float]
) -> tuple[float, float]:
    """Move a beam force to the surface it acts on, or under the support that supplies it."""

    pointing_down = -math.sin(math.radians(force.angle)) > 0.3
    pointing_up = -math.sin(math.radians(force.angle)) < -0.3
    if not (pointing_down or pointing_up):
        return point
    # Pushes land on the face the arrow comes from; pulls leave from the opposite face.
    from_below = pointing_up if force.tip else pointing_down
    if not from_below:
        return (point[0], -BEAM_HALF)
    depth = max(
        (
            _SUPPORT_DEPTH.get(support.type, 0.0)
            for support in spec.supports
            if abs(support.x - force.at[0]) <= spec.body.length * 1e-3
        ),
        default=0.0,
    )
    return (point[0], BEAM_HALF + depth)


def _draw_dimensions(canvas: _Canvas, spec: FbdSpec, to_px: ToPixels) -> None:
    """Dimension lines go under everything else so they never cross arrows or labels."""

    top = max(canvas.ys) + 18
    for index, dimension in enumerate(spec.dimensions):
        y = top + 24 * index
        a, b = to_px(dimension.start, 0)[0], to_px(dimension.end, 0)[0]
        canvas.line((a, y), (b, y), INK_2, 1)
        for x in (a, b):
            canvas.line((x, y - 5), (x, y + 5), INK_2, 1)
        canvas.text(((a + b) / 2, y - 5), dimension.label, INK_2, size=12)


def _draw_support(
    canvas: _Canvas, kind: str, x: float, beam_bottom: float, *, at_end: bool
) -> None:
    if kind == "fixed":
        wall_x = x + (8 if at_end else -8)
        canvas.line((wall_x, -34), (wall_x, 34), INK, 3)
        for y in range(-30, 34, 10):
            side = 8 if at_end else -8
            canvas.line((wall_x, y), (wall_x + side, y + 8), INK_2, 1)
        return
    top, base = beam_bottom, beam_bottom + 22
    canvas.polygon([(x, top), (x - 13, base), (x + 13, base)], fill="none", stroke=INK)
    ground = base
    if kind == "roller":
        for offset in (-7, 7):
            canvas.circle((x + offset, base + 5), 4.5)
        ground = base + 10
    canvas.line((x - 20, ground), (x + 20, ground), INK_2, 1.5)
    for step in range(5):
        start = x - 18 + step * 9
        canvas.line((start, ground), (start - 6, ground + 7), INK_2, 1)


def _draw_load(canvas: _Canvas, spec: FbdSpec, load: LoadSpec) -> None:
    scale = 440 / spec.body.length
    a, b = sorted((load.start * scale, load.end * scale))
    top = -7.0
    left_y = top - (18 + 26 * load.w_start)
    right_y = top - (18 + 26 * load.w_end)
    canvas.line((a, left_y), (b, right_y), PENCIL, 1.5)
    count = max(2, round((b - a) / 36) + 1)
    for index in range(count):
        t = index / (count - 1)
        x = a + (b - a) * t
        y = left_y + (right_y - left_y) * t
        if y < top - 4:
            canvas.arrow((x, y), (x, top), PENCIL)
    canvas.text(((a + b) / 2, min(left_y, right_y) - 8), load.label, PENCIL)


def _draw_force(canvas: _Canvas, force: ForceSpec, point: tuple[float, float]) -> None:
    angle = math.radians(force.angle)
    direction = (math.cos(angle), -math.sin(angle))
    length = ARROW * force.length
    colour = PENCIL if force.kind == "applied" else INK
    if force.tip:
        tail = (point[0] - direction[0] * length, point[1] - direction[1] * length)
        canvas.arrow(tail, point, colour)
        label_at = (tail[0] - direction[0] * 12, tail[1] - direction[1] * 12)
    else:
        head = (point[0] + direction[0] * length, point[1] + direction[1] * length)
        canvas.arrow(point, head, colour)
        label_at = (head[0] + direction[0] * 12, head[1] + direction[1] * 12)
    anchor = "start" if direction[0] > 0.3 else "end" if direction[0] < -0.3 else "middle"
    canvas.text((label_at[0], label_at[1] + 4), force.label, colour, anchor)


def _draw_moment(canvas: _Canvas, moment: MomentSpec, centre: tuple[float, float]) -> None:
    radius = 22.0
    colour = PENCIL if moment.kind == "applied" else INK
    # A 270-degree arc, sampled so the direction never depends on SVG arc flags.
    first, last = (-70.0, 200.0) if moment.direction == "ccw" else (200.0, -70.0)
    angles = [math.radians(first + (last - first) * i / 24) for i in range(25)]
    points = [(centre[0] + radius * math.cos(a), centre[1] - radius * math.sin(a)) for a in angles]
    d = "M " + " L ".join(f"{_f(x)} {_f(y)}" for x, y in points[:-1])
    canvas.path(d, points, colour)
    theta = angles[-1]
    heading = (
        (-math.sin(theta), -math.cos(theta))
        if moment.direction == "ccw"
        else (math.sin(theta), math.cos(theta))
    )
    end = points[-1]
    canvas.arrow(
        (end[0] - heading[0] * 12, end[1] - heading[1] * 12),
        (end[0] + heading[0] * 3, end[1] + heading[1] * 3),
        colour,
    )
    canvas.text((centre[0] + radius + 6, centre[1] - radius - 2), moment.label, colour, "start")


def _f(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        return f"{where}: {error['msg']}" if where else str(error["msg"])
    return str(exc)
