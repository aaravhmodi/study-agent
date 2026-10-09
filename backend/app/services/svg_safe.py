"""Reduce an SVG to drawing elements only, so model-written sketches cannot run code.

Every element and attribute is checked against an allow-list and rebuilt into a
fresh tree; scripts, links, foreign HTML, event handlers, external references and
DTDs are dropped or rejected. The browser sanitizes again before inserting it.
"""

import re
import xml.etree.ElementTree as ET

MAX_SVG_LENGTH = 30_000
MAX_ELEMENTS = 600

_SVG_NS = "http://www.w3.org/2000/svg"
_TAGS = {
    "svg", "g", "defs", "marker", "title", "desc",
    "path", "line", "polyline", "polygon", "rect", "circle", "ellipse",
    "text", "tspan",
}  # fmt: skip
_ATTRIBUTES = {
    "viewBox", "width", "height", "preserveAspectRatio", "transform", "id",
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "dx", "dy", "d", "points",
    "refX", "refY", "markerWidth", "markerHeight", "markerUnits", "orient",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity",
    "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "marker-start", "marker-mid", "marker-end", "style",
}  # fmt: skip
_STYLE_PROPERTIES = {
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity", "font-family",
    "font-size", "font-weight", "font-style", "text-anchor", "dominant-baseline",
}  # fmt: skip
# The only url() allowed points at a marker or gradient inside the same SVG.
_LOCAL_URL = re.compile(r"^url\(#[\w-]+\)$")
_UNSAFE_VALUE = re.compile(r"url\(|expression|javascript:|@import|[<>\\]", re.IGNORECASE)


class SvgError(ValueError):
    """The SVG cannot be read or is too large to show."""


def sanitize_svg(source: str) -> str:
    """Return a clean copy of ``source`` holding only allowed drawing markup."""

    text = source.strip()
    if len(text) > MAX_SVG_LENGTH:
        raise SvgError("sketch too large")
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise SvgError("sketch declares a DTD or entities")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SvgError(f"cannot read sketch: {exc}") from exc
    if _local(root.tag) != "svg":
        raise SvgError("sketch must be an <svg> element")
    if sum(1 for _ in root.iter()) > MAX_ELEMENTS:
        raise SvgError("sketch has too many elements")
    clean = _copy(root)
    if clean is None:
        raise SvgError("sketch has no drawable content")
    if "viewBox" not in clean.attrib:
        width, height = _number(clean.get("width")), _number(clean.get("height"))
        if not (width and height):
            raise SvgError("sketch needs a viewBox")
        clean.set("viewBox", f"0 0 {width:g} {height:g}")
    clean.set("xmlns", _SVG_NS)
    return ET.tostring(clean, encoding="unicode")


def _copy(element: ET.Element) -> ET.Element | None:
    tag = _local(element.tag)
    if tag not in _TAGS:
        return None
    clean = ET.Element(tag)
    for name, value in element.attrib.items():
        name = _local(name)
        if name not in _ATTRIBUTES:
            continue
        value = _clean_style(value) if name == "style" else value.strip()
        if value and _value_allowed(name, value):
            clean.set(name, value)
    clean.text = element.text
    for child in element:
        copied = _copy(child)
        if copied is not None:
            copied.tail = child.tail
            clean.append(copied)
        elif child.tail:
            # Keep text that followed a dropped element.
            clean.text = (clean.text or "") + child.tail
    return clean


def _value_allowed(name: str, value: str) -> bool:
    if name in {"fill", "stroke"} or name.startswith("marker-"):
        if value.startswith("url("):
            return bool(_LOCAL_URL.match(value))
    return not _UNSAFE_VALUE.search(value)


def _clean_style(style: str) -> str:
    kept: list[str] = []
    for declaration in style.split(";"):
        prop, _, value = declaration.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if prop in _STYLE_PROPERTIES and value and _value_allowed(prop, value):
            kept.append(f"{prop}:{value}")
    return ";".join(kept)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _number(value: str | None) -> float | None:
    match = re.match(r"^\s*([\d.]+)", value or "")
    try:
        return float(match.group(1)) if match else None
    except ValueError:
        return None
