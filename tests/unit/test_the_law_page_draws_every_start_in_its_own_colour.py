from __future__ import annotations

import re
from pathlib import Path

from graph_scale_dynamics.measurements import starts

PAGE = Path(__file__).resolve().parents[2] / "graph_scale_dynamics" / "resources" / "ui" / "candidate.html"
SHOWN = ["empty", "given", "triangular", "square", "honeycomb", "cubic", "bcc", "fcc", "tesseract"]
ALIKE = ("cubic", "bcc", "fcc")


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _key(name: str) -> str:
    return "given" if name == "random" else name


def _styles(page: str) -> dict:
    block = page[page.index("const START_STYLE={"):page.index("const START_OTHER=")]
    return {name: (variable, mark, dash) for name, variable, mark, dash in re.findall(
        r"(\w+):\{color:'var\((--start-[a-z]+),#[0-9A-Fa-f]{6}\)',mark:'(\w+)',dash:'([\d ]*)'\}", block)}


def _colours(page: str, theme: str) -> dict:
    opening = ':root[data-theme="light"]{--start-empty' if theme == "light" else ":root{--start-empty"
    block = page[page.index(opening):]
    block = block[:block.index("}")]
    return dict(re.findall(r"(--start-[a-z-]+):(#[0-9A-Fa-f]{6})", block))


def test_every_start_a_law_runs_has_a_colour_a_mark_and_a_place_on_the_page():
    page = _page()
    styles = _styles(page)
    order = re.search(r"const START_ORDER=\[([^\]]*)\];", page).group(1).replace("'", "").split(",")
    assert order == SHOWN, "empty, random, triangular, square, then the three cubic lattices together, then 4D"
    for start in starts.run():
        key = _key(start.name)
        assert key in styles, f"{start.name} runs and the law page gives it no colour of its own"
        assert key in order, f"{start.name} runs and the law page gives it no place"
    assert "empty" in styles and "TC_MORE" not in page, "no start takes its colour from a list by its position"


def test_no_two_starts_share_a_colour_or_a_line():
    page = _page()
    styles = _styles(page)
    running = [_key(start.name) for start in starts.run()]
    assert len({styles[name][0] for name in running}) == len(running)
    assert len({styles[name][2] for name in running}) == len(running), "each start has a dash of its own"
    assert len({(styles[name][1], styles[name][2]) for name in styles}) == len(styles)
    for theme in ("dark", "light"):
        colours = _colours(page, theme)
        used = [colours[styles[name][0]] for name in running]
        assert len(set(used)) == len(used), f"two starts are one colour on the {theme} page"


def _hue(colour: str) -> float:
    import colorsys
    red, green, blue = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(red, green, blue)[0] * 360


def test_the_three_cubic_lattices_are_shades_of_blue_to_purple_and_the_rest_are_as_asked():
    page = _page()
    styles = _styles(page)
    for theme in ("dark", "light"):
        colours = _colours(page, theme)
        hue = {name: _hue(colours[styles[name][0]]) for name in styles}
        assert all(200 <= hue[name] <= 300 for name in ALIKE), hue
        assert hue["given"] < 15 or hue["given"] > 345, "the random start is red"
        assert 90 <= hue["triangular"] <= 140 and 40 <= hue["square"] <= 65 and 170 <= hue["tesseract"] <= 195, hue
        red, green, blue = (int(colours["--start-empty"][i:i + 2], 16) for i in (1, 3, 5))
        assert max(red, green, blue) - min(red, green, blue) < 20, "the chain from empty is grey"
