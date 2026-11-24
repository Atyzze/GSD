from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[2] / "graph_scale_dynamics" / "resources" / "ui" / "system.css").read_text()


def _media_blocks(css: str) -> list[tuple[str, str]]:
    blocks, at = [], 0
    while (start := css.find("@media", at)) >= 0:
        brace = css.index("{", start)
        depth, end = 1, brace + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        blocks.append((css[start + 6:brace].strip(), css[brace + 1:end - 1]))
        at = end
    return blocks


def test_on_a_phone_the_top_bar_scrolls_away_and_now_researching_scrolls_sideways():
    phone = [body for query, body in _media_blocks(CSS) if "max-width:760px" in query.replace(" ", "")]
    rules = "".join(phone).replace(" ", "")
    last = re.findall(r"\.gsd-system-header\{[^}]*position:(\w+)", rules)
    assert last and last[-1] == "relative", f"the last phone rule for the top bar leaves it {last} (789 left it sticky)"
    assert "#live{overflow-x:auto" in rules and re.search(r"#live\.live-grid\{min-width:\d+px", rules), \
        "Now researching is a grid wider than a phone, so on a phone it scrolls inside its box"


def test_on_the_desktop_the_top_bar_stays_and_now_researching_is_unbounded():
    outside = CSS
    for query, body in _media_blocks(CSS):
        outside = outside.replace(body, "")
    assert re.search(r"\.gsd-system-header\{position:sticky", outside.replace(" ", ""))
    assert ".live-unbounded{overflow:visible;max-height:none}" in outside.replace(" ", "")
