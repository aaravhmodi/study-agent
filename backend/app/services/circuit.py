"""Draw circuit schematics from a list of parts the tutor writes, using schemdraw.

Parts are placed one after another like a pen: each starts where the previous one
ended, heading up, down, left or right, unless "at" names an earlier part's start
or end. Lines can close a loop with "to". Nothing the tutor writes is executed;
the JSON only picks from the parts below.
"""

import json
import re
import threading
from typing import Any, Literal

import schemdraw
import schemdraw.elements as elm
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

INK = "#1d1b18"
FONT = "IBM Plex Sans"

_PARTS: dict[str, Any] = {
    "resistor": elm.Resistor,
    "capacitor": elm.Capacitor,
    "inductor": elm.Inductor2,
    "voltage_source": elm.SourceV,
    "current_source": elm.SourceI,
    "ac_source": elm.SourceSin,
    "battery": elm.Battery,
    "switch": elm.Switch,
    "diode": elm.Diode,
    "led": elm.LED,
    "lamp": elm.Lamp,
    "ammeter": elm.MeterA,
    "voltmeter": elm.MeterV,
    "ohmmeter": elm.MeterOhm,
    "line": elm.Line,
    "gap": elm.Gap,
    "dot": elm.Dot,
    "ground": elm.Ground,
}
_ANCHOR = re.compile(r"^([A-Za-z_][\w-]{0,30})(?:\.(start|end))?$")
# schemdraw reads $...$ as math; labels are plain text.
_MATH_MARKS = re.compile(r"[$\\]")
_LOCK = threading.Lock()


class CircuitError(ValueError):
    """The circuit description is invalid or cannot be laid out."""


class PartSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "resistor", "capacitor", "inductor", "voltage_source", "current_source", "ac_source",
        "battery", "switch", "diode", "led", "lamp", "ammeter", "voltmeter", "ohmmeter",
        "line", "gap", "dot", "ground",
    ]  # fmt: skip
    dir: Literal["up", "down", "left", "right"] = "right"
    label: str = Field(default="", max_length=40)
    # A second label on the other side, e.g. a current or voltage drop.
    note: str = Field(default="", max_length=40)
    id: str | None = Field(default=None, pattern=r"^[A-Za-z_][\w-]{0,30}$")
    at: str | None = Field(default=None, max_length=40)
    to: str | None = Field(default=None, max_length=40)
    length: float | None = Field(default=None, gt=0, le=12)
    # Dots only: an open terminal instead of a solid junction.
    open: bool = False

    @model_validator(mode="after")
    def _check(self) -> "PartSpec":
        for name in ("at", "to"):
            value = getattr(self, name)
            if value is not None and not _ANCHOR.match(value):
                raise ValueError(f'{name} must look like "R1", "R1.start" or "R1.end"')
        if self.to is not None and self.type != "line":
            raise ValueError("only lines can use 'to'")
        return self


class CircuitSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", max_length=120)
    parts: list[PartSpec] = Field(min_length=1, max_length=40)


def render_circuit(text: str) -> tuple[str, str]:
    """Return (title, svg) for a ```circuit block, or raise CircuitError."""

    try:
        spec = CircuitSpec.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise CircuitError(f"invalid circuit: {_reason(exc)}") from exc
    # schemdraw keeps its backend choice globally; draw one circuit at a time.
    with _LOCK:
        schemdraw.use("svg")
        drawing = schemdraw.Drawing(show=False)
        drawing.config(color=INK, font=FONT, fontsize=13, lw=1.6)
        placed: dict[str, Any] = {}
        for index, part in enumerate(spec.parts):
            element = _PARTS[part.type]()
            if part.type == "dot" and part.open:
                element = elm.Dot(open=True)
            if part.type not in {"dot", "ground"}:
                element = getattr(element, part.dir)()
                if part.length:
                    element = element.length(part.length)
            if part.at:
                element = element.at(_anchor(placed, part.at, index))
            if part.to:
                element = element.to(_anchor(placed, part.to, index))
            if part.label:
                element = element.label(_plain(part.label))
            if part.note:
                element = element.label(_plain(part.note), loc="bottom")
            drawing.add(element)
            if part.id:
                placed[part.id] = element
        try:
            svg = drawing.get_imagedata("svg").decode("utf-8")
        except Exception as exc:  # layout errors surface here, not when parts are added
            raise CircuitError(f"cannot lay out circuit: {exc}") from exc
    return spec.title, svg


def _anchor(placed: dict[str, Any], reference: str, index: int) -> Any:
    match = _ANCHOR.match(reference)
    assert match is not None  # checked by PartSpec
    name, end = match.group(1), match.group(2) or "end"
    if name == "start" and name not in placed:
        return (0, 0)
    if name not in placed:
        raise CircuitError(f"part {index + 1} refers to unknown part {name!r}")
    return getattr(placed[name], end)


def _plain(label: str) -> str:
    return _MATH_MARKS.sub("", label)


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        return f"{where}: {error['msg']}" if where else str(error["msg"])
    return str(exc)
