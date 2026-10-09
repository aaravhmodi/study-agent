"""How the tutor asks for figures. Every example here is checked by the tests to render."""

FIGURE_GUIDE = """\
Figures: whenever the topic has a shape or a picture, include one to three, each right after \
the text it explains, as a fenced block (JSON blocks take no comments). Pick the type that \
teaches best:

Graphs (functions, distributions, shear or moment diagrams, signals, economic curves):
```plot
{"title": "Shear force", "x": {"label": "x (m)", "min": 0, "max": 6}, "y": {"label": "V (kN)"}, \
"series": [{"label": "V(x)", "pieces": [{"expr": "4", "from": 0, "to": 2}, \
{"expr": "-2", "from": 2, "to": 6}], "fill": true}], \
"markers": [{"x": 2, "label": "P = 6 kN"}]}
```
A series has one of "expr" (a formula in x), "pieces" (piecewise formulas) or "points" \
([[x, y], ...]); "shade": {"from": a, "to": b} shades under it. Formulas use + - * / ^, pi, \
e, sin, cos, tan, exp, ln, log10, sqrt, abs, min, max, step(x) and ramp(x) = max(x, 0).

Free-body diagrams (any forces on a body):
```fbd
{"title": "Block resting on a 30° incline", "body": {"shape": "block", "length": 2, \
"height": 1, "label": "m"}, "incline": 30, "forces": [{"label": "W = mg", "angle": 270}, \
{"label": "N", "at": [0, -0.5], "angle": 120, "kind": "reaction"}, \
{"label": "f", "at": [0, -0.5], "angle": 30, "kind": "reaction"}]}
```
Shapes: beam, block, particle, disk. Angles are degrees counter-clockwise from +x (gravity \
is 270). "at" is in body units: [x, 0] from a beam's left end, or [x, y] from a block's \
centre. "tip": true draws a push ending at the point. Beams also take "supports" \
([{"x": 0, "type": "pin"}], or roller, fixed), "loads" ([{"label", "from", "to", "w_start", \
"w_end"}]), "dimensions" ([{"label", "from", "to"}]); any body takes "moments" \
([{"label", "at", "direction": "ccw"}]).

Circuits:
```circuit
{"title": "RC low-pass filter", "parts": [{"type": "voltage_source", "dir": "up", \
"label": "Vs = 5 V", "id": "src"}, {"type": "resistor", "dir": "right", "label": "R = 1 kΩ"}, \
{"type": "capacitor", "dir": "down", "label": "C = 1 µF"}, \
{"type": "line", "dir": "left", "to": "src.start"}]}
```
Parts are drawn pen-style from the previous part's end; "at": "id" or "id.start" starts \
elsewhere and lines can end at "to". Types: resistor, capacitor, inductor, voltage_source, \
current_source, ac_source, battery, switch, diode, led, lamp, ammeter, voltmeter, line, \
dot, ground. Space parallel branches with "length": 3.

How ideas connect (a process, cause and effect, a proof outline): a short mermaid \
flowchart. Anything else worth drawing (a molecule, a geometric construction, a cell, a \
timeline): a small svg block with a viewBox, a <title>, and plain shapes and text.

Labels are plain text, not LaTeX. Draw only values the materials or your example support.\
"""
