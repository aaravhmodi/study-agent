import pytest
from app.services.svg_safe import SvgError, sanitize_svg

BLOCK = """<svg viewBox="0 0 200 120" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
    <path d="M0,0 L8,4 L0,8 z" fill="#1d1b18"/></marker></defs>
  <rect x="70" y="40" width="60" height="40" fill="none" stroke="#1d1b18"/>
  <line x1="100" y1="80" x2="100" y2="115" stroke="#b4381f" marker-end="url(#arrow)"/>
  <text x="106" y="110" font-size="12">W = mg</text>
</svg>"""


def test_drawing_markup_is_kept() -> None:
    clean = sanitize_svg(BLOCK)

    assert clean.startswith("<svg") and 'xmlns="http://www.w3.org/2000/svg"' in clean
    for kept in ('marker-end="url(#arrow)"', "<rect", "<marker", "W = mg", 'viewBox="0 0 200 120"'):
        assert kept in clean


@pytest.mark.parametrize(
    ("dirty", "gone"),
    [
        (
            '<svg viewBox="0 0 1 1"><script>alert(1)</script><rect width="1" height="1"/></svg>',
            "script",
        ),
        ('<svg viewBox="0 0 1 1"><rect width="1" height="1" onclick="alert(1)"/></svg>', "onclick"),
        ('<svg viewBox="0 0 1 1"><a href="javascript:alert(1)"><text>hi</text></a></svg>', "href"),
        (
            '<svg viewBox="0 0 1 1"><foreignObject><div>x</div></foreignObject><rect/></svg>',
            "foreignObject",
        ),
        ('<svg viewBox="0 0 1 1"><image href="https://evil.example/x.png"/><rect/></svg>', "image"),
        ('<svg viewBox="0 0 1 1"><rect fill="url(https://evil.example/x)"/></svg>', "evil"),
        (
            '<svg viewBox="0 0 1 1"><rect style="fill:red;background:url(https://x)"/></svg>',
            "background",
        ),
        ('<svg viewBox="0 0 1 1"><style>rect{fill:red}</style><rect/></svg>', "<style"),
        (
            '<svg viewBox="0 0 1 1" xmlns:xlink="http://www.w3.org/1999/xlink">'
            '<use xlink:href="#a"/><rect/></svg>',
            "use",
        ),
    ],
)
def test_active_or_external_content_is_removed(dirty: str, gone: str) -> None:
    assert gone not in sanitize_svg(dirty)


def test_style_keeps_only_drawing_properties() -> None:
    clean = sanitize_svg('<svg viewBox="0 0 1 1"><rect style="fill:red; position:fixed"/></svg>')

    assert 'style="fill:red"' in clean


def test_size_from_width_and_height_when_viewbox_is_missing() -> None:
    clean = sanitize_svg('<svg width="176pt" height="80pt"><rect/></svg>')

    assert 'viewBox="0 0 176 80"' in clean


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ('<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg viewBox="0 0 1 1">&a;</svg>', "DTD"),
        ("<svg viewBox='0 0 1 1'><rect></svg>", "cannot read"),
        ("<div>not svg</div>", "must be an <svg>"),
        ("<svg><rect/></svg>", "viewBox"),
        pytest.param('<svg viewBox="0 0 1 1">' + "<rect/>" * 700 + "</svg>", "too many", id="many"),
        pytest.param(
            '<svg viewBox="0 0 1 1">' + "<!-- pad -->" * 3000 + "</svg>", "too large", id="large"
        ),
    ],
)
def test_unreadable_or_oversized_svgs_are_rejected(source: str, reason: str) -> None:
    with pytest.raises(SvgError, match=reason):
        sanitize_svg(source)
