#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from xml.dom import minidom
from xml.parsers.expat import ExpatError

SVG_NS = "http://www.w3.org/2000/svg"
ALLOWED = {"svg", "g", "title", "desc", "defs", "path", "rect", "circle", "ellipse", "line", "polyline",
           "polygon", "text", "tspan", "linearGradient", "radialGradient", "stop"}
WHY_NOT = {
    "foreignObject": "HTML inside SVG draws only in browsers: the boxes come out empty elsewhere "
                     "(Mermaid: flowchart htmlLabels false)",
    "script": "no scripts in a portable SVG",
    "style": "CSS support outside browsers is partial; put fill, stroke and font on each element",
    "marker": "markers are not in SVG Tiny 1.2 (Qt draws no arrowheads); draw the arrowhead as a path",
    "filter": "filters are skipped by Qt and cairo in places",
    "mask": "masks are skipped by Qt",
    "image": "an embedded or linked image is not a drawing",
    "switch": "switch picks a branch by features the renderer claims",
}
NUMBER = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")
TEXT_ATTRIBUTES_REFUSED = ("dy", "dx", "rotate", "dominant-baseline", "alignment-baseline", "textLength")


def _local(tag: str) -> str:
    return tag.split(":", 1)[-1]


def check(text: str) -> list[str]:
    try:
        document = minidom.parseString(text.encode("utf-8") if isinstance(text, str) else text)
    except ExpatError as exc:
        return [f"not well-formed XML at line {exc.lineno}, column {exc.offset}: {exc} "
                "(a standalone .svg is XML: close every tag, <br/> not <br>)"]
    root = document.documentElement
    problems: list[str] = []
    if _local(root.tagName) != "svg":
        return [f"the root element is <{root.tagName}>, not <svg>"]
    if root.getAttribute("xmlns") != SVG_NS:
        problems.append(f'the root <svg> needs xmlns="{SVG_NS}"')
    if not root.getAttribute("viewBox") and not (root.getAttribute("width") and root.getAttribute("height")):
        problems.append("the root <svg> needs a viewBox or a width and height")

    counts: dict[str, int] = {}

    def where(node) -> str:
        name = _local(node.tagName)
        counts[name] = counts.get(name, 0) + 1
        ident = node.getAttribute("id")
        return f"<{name}>" + (f' id="{ident}"' if ident else f" #{counts[name]}")

    def visit(node, inside_text: bool) -> None:
        for child in node.childNodes:
            if child.nodeType != child.ELEMENT_NODE:
                continue
            name = _local(child.tagName)
            at = where(child)
            if name in WHY_NOT:
                problems.append(f"{at}: {WHY_NOT[name]}")
                continue
            if name not in ALLOWED:
                problems.append(f"{at}: not drawn by an SVG Tiny 1.2 renderer")
                continue
            if child.getAttribute("style"):
                problems.append(f"{at}: a style attribute; put each property on the element as an attribute")
            if name == "text":
                for key in ("x", "y"):
                    value = child.getAttribute(key).strip()
                    if not NUMBER.match(value):
                        problems.append(f"{at}: {key}={value!r}; a line of text needs one plain number "
                                        "(no list, no unit, no em)")
            if name in ("text", "tspan"):
                for key in TEXT_ATTRIBUTES_REFUSED:
                    if child.getAttribute(key):
                        problems.append(f"{at}: {key} is ignored by Qt; one <text> per line with numeric x and y")
            if name == "tspan":
                if not inside_text:
                    problems.append(f"{at}: a tspan outside a text element")
                for key in ("x", "y"):
                    if child.getAttribute(key):
                        problems.append(f"{at}: a positioned tspan; Qt ignores tspan x and y, so each line "
                                        "is its own <text>")
            visit(child, inside_text or name == "text")

    visit(root, False)
    return problems


def render(path: Path, out: Path, scale: float = 2.0) -> str:
    try:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return "PySide6 is not installed (pip install PySide6-Essentials); not rendered"
    app = QGuiApplication.instance() or QGuiApplication(["check_svg", "-platform", "offscreen"])
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return "Qt could not read the file"
    box = renderer.viewBoxF()
    image = QImage(int(box.width() * scale), int(box.height() * scale), QImage.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, image.width(), image.height()))
    painter.end()
    image.save(str(out))
    del app
    return f"rendered by Qt to {out} ({image.width()} x {image.height()})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/check_svg.py: see docs/TOOLS.md")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--render", type=Path, default=None,
                        help="draw the (single) file with Qt's SVG renderer to this PNG")
    args = parser.parse_args(argv)
    failed = False
    for path in args.paths:
        problems = check(path.read_text(encoding="utf-8"))
        print(f"{path}: {'portable' if not problems else f'{len(problems)} problem(s)'}")
        for line in problems[:50]:
            print(f"  {line}")
        failed = failed or bool(problems)
        if args.render is not None and len(args.paths) == 1:
            print(f"  {render(path, args.render)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
