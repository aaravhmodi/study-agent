import json
import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest
from app.services.fbd import BEAM_HALF, FbdError, render_fbd
from app.services.figures import FigureError, extract_figures, parse_fbd
from app.services.svg_safe import sanitize_svg

BEAM: dict[str, Any] = {
    "title": "Simply supported beam",
    "body": {"shape": "beam", "length": 6},
    "supports": [{"x": 0, "type": "pin"}, {"x": 6, "type": "roller"}],
    "forces": [
        {"label": "P = 12 kN", "at": [2, 0], "angle": 270, "tip": True},
        {"label": "A_y = 8 kN", "at": [0, 0], "angle": 90, "tip": True, "kind": "reaction"},
    ],
    "loads": [{"label": "w = 2 kN/m", "from": 3, "to": 6}],
    "dimensions": [{"label": "6 m", "from": 0, "to": 6}],
}


def _svg(spec: dict[str, Any]) -> ET.Element:
    _, svg = render_fbd(json.dumps(spec))
    return ET.fromstring(svg)


def _texts(root: ET.Element) -> list[str]:
    return [element.text or "" for element in root.iter() if element.tag.endswith("text")]


def _arrowheads(root: ET.Element, colour: str) -> list[tuple[float, float]]:
    """The tip (first point) of each filled arrowhead triangle of a colour."""

    tips = []
    for polygon in root.iter("{http://www.w3.org/2000/svg}polygon"):
        if polygon.get("fill") == colour:
            x, y = polygon.get("points", "").split()[0].split(",")
            tips.append((float(x), float(y)))
    return tips


def test_beam_draws_labels_supports_loads_and_dimensions() -> None:
    root = _svg(BEAM)

    assert {"P = 12 kN", "A_y = 8 kN", "w = 2 kN/m", "6 m"} <= set(_texts(root))
    assert root.find("{http://www.w3.org/2000/svg}title").text == "Simply supported beam"  # type: ignore[union-attr]
    # Sanitizing the generated SVG keeps everything: the renderer uses only allowed markup.
    assert (
        ET.tostring(root, encoding="unicode").count("<")
        <= sanitize_svg(ET.tostring(root, encoding="unicode")).count("<") + 1
    )


def test_beam_load_lands_on_top_and_reaction_comes_from_under_the_support() -> None:
    root = _svg(BEAM)
    scale = 440 / 6

    # P pushes down onto the top face at x = 2 m.
    assert (round(2 * scale, 1), -BEAM_HALF) in _arrowheads(root, "#b4381f")
    # The pin reaction pushes up from below the pin (24 px under the beam).
    assert (0.0, BEAM_HALF + 24) in _arrowheads(root, "#1d1b18")


def test_weight_on_an_incline_points_straight_down() -> None:
    spec = {
        "body": {"shape": "block", "length": 2, "height": 1, "label": "m"},
        "incline": 30,
        "forces": [{"label": "W", "angle": 270}],
    }
    root = _svg(spec)

    (tip,) = _arrowheads(root, "#b4381f")
    assert tip[0] == pytest.approx(0, abs=0.1) and tip[1] > 60
    assert "30°" in _texts(root)


def test_moments_and_particles_render() -> None:
    root = _svg(
        {
            "body": {"shape": "particle", "label": "A"},
            "forces": [{"label": "T1", "angle": 135}, {"label": "T2", "angle": 30}],
            "moments": [{"label": "M", "direction": "cw"}],
        }
    )

    assert {"T1", "T2", "M", "A"} <= set(_texts(root))
    assert root.find("{http://www.w3.org/2000/svg}path") is not None


def test_view_box_contains_every_drawn_point() -> None:
    root = _svg(BEAM)
    left, top, width, height = map(float, root.get("viewBox", "").split())
    numbers = re.findall(r'(?:x1|x2|cx)="(-?[\d.]+)"', ET.tostring(root, encoding="unicode"))

    assert all(left <= float(value) <= left + width for value in numbers)
    assert height > 0


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ({"body": {"shape": "block"}}, "at least one force"),
        (
            {
                "body": {"shape": "block"},
                "forces": [{"angle": 0}],
                "supports": [{"x": 0, "type": "pin"}],
            },
            "need a beam",
        ),
        ({"forces": [{"angle": 0}], "body": {"shape": "blob"}}, "body.shape"),
        ({"forces": [{"label": "x" * 80, "angle": 0}]}, "label"),
    ],
)
def test_invalid_descriptions_are_rejected(spec: dict[str, Any], reason: str) -> None:
    with pytest.raises(FbdError, match=reason):
        render_fbd(json.dumps(spec))


def test_fbd_blocks_become_sketch_figures() -> None:
    text, figures = extract_figures("```fbd\n" + json.dumps(BEAM) + "\n```")

    (figure,) = figures
    assert figure.kind == "sketch" and figure.title == "Simply supported beam"
    assert text == "```figure\n0\n```"
    with pytest.raises(FigureError):
        parse_fbd("{}")
