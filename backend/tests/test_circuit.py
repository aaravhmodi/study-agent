import json
import re
from typing import Any

import pytest
from app.services.circuit import CircuitError, render_circuit
from app.services.figures import extract_figures

RC: dict[str, Any] = {
    "title": "RC low-pass filter",
    "parts": [
        {"type": "voltage_source", "dir": "up", "label": "Vs = 5 V", "id": "src"},
        {"type": "resistor", "dir": "right", "label": "R = 1 kΩ"},
        {"type": "dot", "id": "out"},
        {"type": "capacitor", "dir": "down", "label": "C = 1 µF"},
        {"type": "line", "dir": "left", "to": "src.start"},
        {"type": "line", "dir": "right", "at": "out", "length": 1.5},
        {"type": "dot", "open": True, "label": "Vout"},
    ],
}


def _labels(svg: str) -> list[str]:
    return re.findall(r"<tspan[^>]*>([^<]*)</tspan>", svg)


def test_rc_filter_renders_every_part_with_its_label() -> None:
    title, svg = render_circuit(json.dumps(RC))

    assert title == "RC low-pass filter"
    assert svg.lstrip().startswith("<svg")
    assert {"Vs = 5 V", "R = 1 kΩ", "C = 1 µF", "Vout"} <= set(_labels(svg))


def test_loop_closes_on_the_source_start() -> None:
    # The return line ends where the source began (the origin), closing the loop.
    _, svg = render_circuit(json.dumps(RC))

    assert re.search(r"L 0(?:\.0)?,-?0(?:\.0)?\b", svg) or "L 0,0" in svg


def test_math_marks_are_stripped_from_labels() -> None:
    spec = {"parts": [{"type": "resistor", "label": "$R_1$ = 2\\Omega"}]}

    _, svg = render_circuit(json.dumps(spec))

    assert "R_1 = 2Omega" in _labels(svg)


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ({"parts": []}, "parts"),
        ({"parts": [{"type": "transistor"}]}, "type"),
        ({"parts": [{"type": "resistor", "dir": "diagonal"}]}, "dir"),
        ({"parts": [{"type": "resistor", "to": "start"}]}, "only lines"),
        ({"parts": [{"type": "line", "at": "R9.end"}]}, "unknown part 'R9'"),
        ({"parts": [{"type": "line", "at": "a; import os"}]}, "must look like"),
        ({"parts": [{"type": "resistor"}] * 41}, "parts"),
        ("not json", "invalid circuit"),
    ],
)
def test_invalid_circuits_are_rejected(spec: Any, reason: str) -> None:
    text = spec if isinstance(spec, str) else json.dumps(spec)
    with pytest.raises(CircuitError, match=reason):
        render_circuit(text)


def test_circuit_blocks_become_sanitized_sketches() -> None:
    text, figures = extract_figures("```circuit\n" + json.dumps(RC) + "\n```")

    (figure,) = figures
    assert figure.kind == "sketch" and figure.title == "RC low-pass filter"
    assert "<svg" in figure.svg and "<script" not in figure.svg
    assert text == "```figure\n0\n```"
