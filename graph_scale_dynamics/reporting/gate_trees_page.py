from __future__ import annotations

import json
from html import escape
from pathlib import Path

from graph_scale_dynamics.decisions import gates as G
from graph_scale_dynamics.research import gate_tree as GT

CONTRACT = "gsd-gate-trees-page-1"
RESOURCES = Path(__file__).resolve().parents[1] / "resources"

STRETCH_FROM = 65536
CATEGORIES = (
    ("on", "went on", "#008300", "#008300"),
    ("done", "ladder done", "#e87ba4", "#d55181"),
    ("held", "held", "#eda100", "#c98500"),
    ("settling", "stopped: settling", "#4a3aa7", "#9085e9"),
    ("deep rungs", "stopped: deep rungs", "#eb6834", "#d95926"),
    ("structure", "stopped: structure gate", "#2a78d6", "#3987e5"),
    ("final verdict", "stopped: final verdict", "#e34948", "#e66767"),
    ("operational", "stopped: operational", "#898781", "#898781"),
    ("other", "stopped: another rule", "#c3c2b7", "#52514e"),
    ("stopped", "stopped, by any gate", "#e34948", "#e66767"),
    ("running", "still running at this rung", "#c3c2b7", "#52514e"),
)
STOP_STAGES = ("settling", "deep rungs", "structure", "final verdict", "operational")
SERIES = (("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
          ("#e87ba4", "#d55181"), ("#008300", "#008300"), ("#4a3aa7", "#9085e9"), ("#e34948", "#e66767"))


def slug(key: str) -> str:
    return key.replace(" ", "-")


def rules() -> dict:
    out = {}
    for gate in G.GATES:
        out[gate.name] = {"kind": "gate", "stage": gate.stage, "reads": gate.reads, "salted": gate.salted,
                          "why_not": gate.why_not or None, "action": gate.action}
    for stream in G.STREAMS:
        out.setdefault(stream.rule, {"kind": "stream", "action": stream.action, "means": stream.means,
                                     "audit": stream.audit})
    return out


def fates(part: dict | None) -> dict:
    out: dict[str, int] = {}
    for law in (part or {}).get("laws") or []:
        rule, n = law.get("fate"), law.get("fate_n")
        if rule is None or n is None:
            continue
        key = f"{rule}|{int(n)}"
        out[key] = out.get(key, 0) + 1
    return out


def document(columns: list[dict], *, title: str, study: dict, explorer_index: dict | None = None,
             fate_counts: dict | None = None) -> dict:
    explorer_index, fate_counts = explorer_index or {}, fate_counts or {}
    campaigns, reading = [], None
    for column in columns:
        tree = column.get("tree") if isinstance(column.get("tree"), dict) else None
        cid = str(column.get("campaign_id"))
        campaigns.append({"id": cid, "label": column.get("label"), "subtitle": column.get("subtitle"), "tree": tree,
                          "explorer": explorer_index.get(cid), "fates": fate_counts.get(cid) or {}})
        reading = reading or (tree or {}).get("reading")
    return {"contract": CONTRACT, "title": title, "study": study, "campaigns": campaigns, "rules": rules(),
            "gate_order": [gate.name for gate in G.GATES], "stop_stages": list(STOP_STAGES),
            "categories": [{"key": k, "label": label, "slug": slug(k)} for k, label, _l, _d in CATEGORIES],
            "costs": [GT.CHEAP, GT.DEEP], "stretch_from": STRETCH_FROM, "reading": reading}


def _colours() -> str:
    def block(index: int) -> str:
        cats = "".join(f"--cat-{slug(k)}:{pair[index]};" for k, _label, *pair in CATEGORIES)
        series = "".join(f"--series-{i + 1}:{pair[index]};" for i, pair in enumerate(SERIES))
        return cats + series
    return (f":root{{{block(0)}}}\n@media (prefers-color-scheme: dark){{:root:not([data-theme=\"light\"]){{{block(1)}}}}}"
            f"\n:root[data-theme=\"dark\"]{{{block(1)}}}\n")


def render(data: dict, *, links: dict) -> str:
    data = dict(data, links=links)
    css = ((RESOURCES / "explorer" / "explorer.css").read_text(encoding="utf-8") + "\n"
           + (RESOURCES / "gate_trees" / "gate_trees.css").read_text(encoding="utf-8") + "\n" + _colours())
    script = (RESOURCES / "gate_trees" / "gate_trees.js").read_text(encoding="utf-8")
    title = escape(str(data.get("title") or "Gate trees"))
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False, default=str).replace("<", "\\u003c")
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
            f'<style>\n{css}\n</style>\n</head>\n<body>\n'
            f'<div id="app" data-contract="{CONTRACT}"><p class="loading">Opening {title}...</p></div>\n'
            f'<script type="application/json" id="gate-trees-data">{payload}</script>\n'
            f'<script>\n{script}\n</script>\n</body>\n</html>\n')


def unavailable(title: str, why: str) -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>{escape(title)}</title>\n'
            f'</head>\n<body>\n<h1>{escape(title)}</h1>\n<p>The gate trees could not be drawn: {escape(why)}</p>\n'
            f'</body>\n</html>\n')
