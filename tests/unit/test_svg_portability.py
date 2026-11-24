from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import check_svg  # noqa: E402

GOOD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40">'
        '<rect x="1" y="1" width="98" height="38" fill="#eeeeee" stroke="#999999"/>'
        '<text x="50" y="18" text-anchor="middle" font-family="DejaVu Sans" font-size="12" fill="#000000">one</text>'
        '<text x="50" y="32" text-anchor="middle" font-family="DejaVu Sans" font-size="12" fill="#000000">two</text>'
        '</svg>')


def test_every_shipped_svg_is_portable():
    shipped = sorted(p for p in ROOT.joinpath("docs").rglob("*.svg"))
    assert shipped, "docs/diagrams/rung_flow.svg is expected"
    for path in shipped:
        assert check_svg.check(path.read_text(encoding="utf-8")) == [], path


def test_a_portable_drawing_passes():
    assert check_svg.check(GOOD) == []


def test_each_way_a_drawing_goes_blank_outside_a_browser_is_named():
    cases = {
        "not well-formed": GOOD.replace("</text><text", "<br></text><text", 1),
        "foreignObject": GOOD.replace("</svg>", '<foreignObject width="9" height="9"><div>x</div></foreignObject></svg>'),
        "CSS support": GOOD.replace("</svg>", "<style>rect{fill:red}</style></svg>"),
        "style attribute": GOOD.replace('<rect ', '<rect style="fill:red" '),
        "markers": GOOD.replace("</svg>", '<marker id="m"><path d="M0 0 L1 1"/></marker></svg>'),
        "ignored by Qt": GOOD.replace('<text x="50" y="32"', '<text x="50" y="32" dy="1.2em"'),
        "plain number": GOOD.replace('<text x="50" y="32"', '<text x="50" y="2em"'),
        "positioned tspan": GOOD.replace(">two<", '><tspan x="50" y="32">two</tspan><'),
        "xmlns": GOOD.replace(' xmlns="http://www.w3.org/2000/svg"', ""),
    }
    for needle, text in cases.items():
        problems = check_svg.check(text)
        assert any(needle in p for p in problems), (needle, problems)
