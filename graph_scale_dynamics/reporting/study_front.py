from __future__ import annotations

import math
from html import escape
from pathlib import Path

CONTRACT = "gsd-study-front-1"
STYLE = """
:root{--bg:#fbfbfa;--fg:#1d1d1f;--muted:#5d5d63;--line:#d9d9de;--panel:#ffffff;--accent:#2a62c9;--chip:#eef2fa}
@media (prefers-color-scheme: dark){:root{--bg:#141417;--fg:#e8e8ea;--muted:#a0a0a8;--line:#33333a;--panel:#1c1c21;
--accent:#7aa5f0;--chip:#232a38}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 Inter,system-ui,-apple-system,
'Segoe UI',sans-serif}main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}h1{font-size:24px;margin:0 0 4px}
h2{font-size:17px;margin:2px 0 8px}h3{font-size:14px;margin:16px 0 6px}p{margin:6px 0}.muted{color:var(--muted)}
a{color:var(--accent)}section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;
margin:14px 0}nav{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}nav a,nav span{background:var(--chip);border:1px
solid var(--line);border-radius:6px;padding:4px 10px;text-decoration:none}nav span{color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border-bottom:1px solid var(--line);padding:5px 8px;
text-align:left;vertical-align:top}th{font-weight:600;color:var(--muted);font-size:12px}td.num,th.num{text-align:right;
font-variant-numeric:tabular-nums}.wrap{overflow-x:auto}ul{margin:6px 0;padding-left:20px}li{margin:2px 0}
.reason{display:block}.tag{display:inline-block;font-size:11px;border-radius:4px;padding:0 5px;margin-right:4px;
background:var(--chip);border:1px solid var(--line)}code{font-size:12px}
@media (max-width:700px){table.laws,table.laws tbody,table.laws tr,table.laws td{display:block;width:auto}
table.laws thead{display:none}table.laws tr{border-bottom:1px solid var(--line);padding:8px 0}table.laws td{border:0;
padding:1px 0;text-align:left}table.laws td[data-l]::before{content:attr(data-l) " ";color:var(--muted)}}
"""


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value) -> str:
    number = _num(value)
    return "-" if number is None else f"{int(round(number)):,}"


def report_in(part: Path, code: str) -> Path | None:
    part = Path(part)
    direct = part / "reports" / f"{code}.json"
    if direct.is_file():
        return direct
    found = sorted(part.glob(f"{code}-*.json"))
    return found[0] if found else None


def cost_models(ready: list[dict]) -> list[dict]:
    import ijson

    out = []
    for part in ready:
        report = report_in(Path(part["root"]), "16")
        model, why = None, "no report 16 in its part"
        if report is not None:
            try:
                with open(report, "rb") as handle:
                    model = next(ijson.items(handle, "body.cost_model", use_float=True), None)
                why = None if model else "report 16 carries no cost model"
            except Exception as exc:  # noqa: BLE001
                model, why = None, f"{type(exc).__name__}: {str(exc)[:120]}"
        out.append({"campaign_id": str(part["campaign_id"]), "label": part.get("label"), "model": model,
                    **({"why": why} if why else {})})
    return out


def classify_summary(parts: list[dict]) -> list[dict]:
    from graph_scale_dynamics.research.family_classification import family_separations
    from graph_scale_dynamics.reporting.study_explorer import label_of
    out = []
    for entry in parts:
        laws = [law for law in entry["part"].get("laws") or [] if law.get("classify_n")]
        if not laws:
            continue
        nearest = {}
        for law in laws:
            if law.get("nearest"):
                nearest[law["nearest"]] = nearest.get(law["nearest"], 0) + 1
        top = max(int(law.get("classify_n") or 0) for law in laws) or None
        separation = family_separations(top) if top else {}
        out.append({"campaign_id": str(entry["campaign"].get("campaign_id")), "label": label_of(entry["campaign"]),
                    "placed": len(laws), "basis": entry["part"].get("basis"),
                    "nearest": dict(sorted(nearest.items(), key=lambda kv: (-kv[1], kv[0]))),
                    "top_n": top, "separable": separation.get("pairs_the_instrument_can_separate"),
                    "pairs": separation.get("pairs_compared")})
    return out


def _link(href: str | None, text: str) -> str:
    return f'<a href="{escape(href)}">{escape(text)}</a>' if href else f'<span title="inside the archive">{escape(text)}</span>'


def _graphs(campaign: dict):
    return campaign.get("graphs_finished") if campaign.get("graphs_finished") is not None else campaign.get("graphs")


def _campaigns_table(campaigns: list[dict]) -> str:
    rows = []
    for c in campaigns:
        tree = c.get("gate_tree") or {}
        finished = {int(n): v for n, v in (tree.get("finished_by_rung") or {}).items() if v}
        rungs = ", ".join(f"{n:,}: {v:,}" for n, v in sorted(finished.items())) or "-"
        rows.append(f"<tr><td>{escape(str(c.get('campaign_id')))}</td><td>{escape(str(c.get('label') or ''))}</td>"
                    f"<td class=num>{_int(c.get('laws'))}</td><td class=num>{_int(_graphs(c))}</td>"
                    f"<td>{escape(str(c.get('state') or ''))}</td><td class=muted>{escape(rungs)}</td></tr>")
    return ("<div class=wrap><table><thead><tr><th>campaign</th><th></th><th class=num>laws</th><th class=num>graphs"
            "</th><th>state</th><th>laws finished, by rung</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _found(campaigns: list[dict], classify: list[dict], advice: dict | None, missing: list[dict] | None = None,
           read_utc: dict | None = None) -> str:
    lines = []
    for c in classify:
        near = ", ".join(f"{escape(k)} {_int(v)}" for k, v in list(c["nearest"].items())[:4]) or "none"
        lines.append(f"<li>Classify, {escape(c['label'])}: {_int(c['placed'])} laws placed against the calibration "
                     f"families ({escape(c.get('basis') or 'theory')}); nearest {near}. At "
                     f"{_int(c['top_n'])} the instrument separates {_int(c['separable'])} of {_int(c['pairs'])} pairs "
                     "of known families, and no placement is finer than that.</li>")
    if advice and not advice.get("unavailable"):
        lines.append(f"<li>{_int(advice.get('laws_with_a_reason'))} laws have a reason to be looked at again, and "
                     f"{_int(len(advice.get('leads') or []))} pairs of fields hold beyond the mean degree from one N to "
                     "the next (below).</li>")
    total_laws = sum(int(c.get("laws") or 0) for c in campaigns)
    total_graphs = sum(int(_graphs(c) or 0) for c in campaigns)
    head = (f"<p>{len(campaigns)} campaign(s) in this bundle, {total_laws:,} laws and {total_graphs:,} graphs.</p>")
    absent = "".join(f"<li>campaign {escape(str(m.get('campaign_id')))} is not in these sums: "
                     f"{escape(str(m.get('why') or 'not bundled'))}</li>" for m in missing or [])
    when = ""
    if read_utc and read_utc.get("fleet_resumed_utc"):
        when = (f"<p class=muted>These counts were read at {escape(str(read_utc.get('counts')))}, after the fleet was "
                f"resumed at {escape(str(read_utc['fleet_resumed_utc']))}: they may run ahead of the reports.</p>")
    return (head + when + (f"<ul class=muted>{absent}</ul>" if absent else "") + _campaigns_table(campaigns)
            + (f"<ul>{''.join(lines)}</ul>" if lines else ""))


def _advice(advice: dict | None, explorer: str | None) -> str:
    if not advice:
        return "<p class=muted>No advice was made for this bundle.</p>"
    if advice.get("unavailable"):
        return f"<p class=muted>The advice could not be made: {escape(str(advice['unavailable']))}</p>"
    reasons = advice.get("reasons") or {}
    legend = "".join(f"<li><b>{escape(r['label'])}</b> (weight {r['weight']}, {_int((advice.get('by_reason') or {}).get(k))} "
                     f"laws): {escape(r['what'])}</li>" for k, r in reasons.items())
    rows = []
    for law in advice.get("laws") or []:
        name = law.get("label") or law.get("id")
        target = f"{explorer}{law['explorer']}" if explorer and law.get("in_the_explorer") else None
        texts = "".join(f"<span class=reason><span class=tag>{escape(reasons.get(r['key'], {}).get('label', r['key']))}"
                        f"</span>{escape(r['text'])}</span>" for r in law.get("reasons") or [])
        rows.append(f"<tr><td class=num data-l=rank>{law['rank']}</td><td data-l=campaign>"
                    f"{escape(str(law.get('campaign_id')))}</td>"
                    f"<td>{_link(target, str(name))}<div class=muted><code>{escape(law['id'])}</code></div></td>"
                    f"<td class=num data-l=score>{law['score']}</td><td class=num data-l='largest N'>"
                    f"{_int(law.get('top_n'))}</td><td>{texts}</td></tr>")
    laws = ("<div class=wrap><table class=laws><thead><tr><th class=num>rank</th><th>campaign</th><th>law</th><th class=num>score"
            "</th><th class=num>largest N</th><th>why</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            if rows else "<p class=muted>No law has a reason to be looked at again.</p>")
    lead_rows = []
    for lead in advice.get("leads") or []:
        target = f"{explorer}{lead['explorer']}" if explorer else None
        within = "temperature not set" if lead["group"] == "not set" else lead["group"]
        lead_rows.append(f"<tr><td>{escape(lead['y'])} against {escape(lead['x'])}</td><td>{escape(within)}</td>"
                         f"<td class=num>{lead['n']:,} then {lead['next_n']:,}</td>"
                         f"<td class=num>{lead['partial']:+.2f} then {lead['next_partial']:+.2f}</td>"
                         f"<td class=num>{lead['readings']:,} and {lead['next_readings']:,}</td>"
                         f"<td>{_link(target, 'show both')}</td></tr>")
    rule = advice.get("lead_rule") or {}
    leads = (f"<h3>Leads: what holds beyond the degree from one N to the next</h3><p class=muted>Every pair of the "
             f"explorer's fields within each temperature and at each N, measured as the explorer's Scan measures it "
             f"(the rank correlation with the mean degree held); a lead is {rule.get('partial_at_least')} or more at "
             f"one N and at the next, with the same sign, on {rule.get('readings_at_least')} readings or more each. "
             f"{_int(advice.get('pairs_tried'))} pairs and rungs were tried, so some look strong by chance: a lead "
             "is where to look, not a finding.</p>"
             + ("<div class=wrap><table><thead><tr><th>pair</th><th>within</th><th class=num>N</th><th class=num>given k"
                "</th><th class=num>readings</th><th></th></tr></thead><tbody>" + "".join(lead_rows) + "</tbody></table></div>"
                if lead_rows else "<p class=muted>No pair holds beyond the degree from one N to the next.</p>"))
    listed = len(advice.get("laws") or [])
    return (f"<p>{escape(advice.get('reading') or '')}</p><ul>{legend}</ul>"
            f"<h3>The laws, ranked</h3><p class=muted>The first {listed:,} of {_int(advice.get('laws_with_a_reason'))} "
            "laws with a reason. A law opens in the explorer, selected; its every rung is on the Laws page.</p>"
            + laws + leads)


def _cost(cost: list[dict]) -> str:
    models = [c for c in cost if c.get("model") and c["model"].get("available")]
    if not models:
        why = "; ".join(f"campaign {c['campaign_id']}: {c.get('why') or (c.get('model') or {}).get('reason') or 'none'}"
                        for c in cost)
        return f"<p class=muted>No campaign of this bundle carries a cost model ({escape(why)}).</p>"
    operators = sorted({op for c in models for op in (c["model"].get("operator_multipliers") or {})})
    head = "".join(f"<th class=num>campaign {escape(c['campaign_id'])}</th>" for c in models)
    rows = []
    for op in operators:
        cells = "".join(f"<td class=num>{_fmt_mult((c['model'].get('operator_multipliers') or {}).get(op))}</td>"
                        for c in models)
        rows.append(f"<tr><td><code>{escape(op)}</code></td>{cells}</tr>")
    base = "".join(f"<td class=num>{_fmt_sci(c['model'].get('base_rate_per_attempted_move'))}</td>" for c in models)
    held = "".join(f"<td class=num>{_fmt_mult((c['model'].get('held_out_accuracy') or {}).get('median_factor_error'))} on "
                   f"{_int((c['model'].get('held_out_accuracy') or {}).get('n'))}</td>" for c in models)
    spread = "".join(f"<td class=num>{_fmt_mult((c['model'].get('observed_rate_spread') or {}).get('max_over_min'), 0)}</td>"
                     for c in models)
    missing = [c for c in cost if c not in models]
    note = ("" if not missing else "<p class=muted>Without one: " + escape("; ".join(
        f"campaign {c['campaign_id']} ({c.get('why') or (c.get('model') or {}).get('reason') or 'not available'})"
        for c in missing)) + ".</p>")
    return ("<p>A law's price before it runs is the base rate times the product of its terms' multipliers: what each "
            "operator does to the cost of one attempted move, the rest held fixed, fitted on each campaign's own "
            "attempts. Read the held-out error first: a typical prediction on signatures the fit never saw is off by "
            "that factor. A reduction, not a precision instrument, and nothing here is about the science.</p>"
            f"<div class=wrap><table><thead><tr><th>operator</th>{head}</tr></thead><tbody>{''.join(rows)}"
            f"<tr><td>base rate, s a move</td>{base}</tr><tr><td>held out: median factor error</td>{held}</tr>"
            f"<tr><td>observed spread, max over min</td>{spread}</tr></tbody></table></div>" + note)


def _fmt_mult(value, digits: int = 2) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.{digits}f}x"


def _fmt_sci(value) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.3g}"


def render(*, study: dict, campaigns: list[dict], links: dict, advice: dict | None = None, cost: list | None = None,
           classify: list | None = None, missing: list | None = None) -> str:
    sid, built = str(study.get("study_id") or "?"), str(study.get("built_utc") or "")
    title = f"Study {sid}: the study bundle of {built}"
    views = [("explorer", "the explorer"), ("gate_trees", "the gate trees")]
    documents = [("study", "study.json"), ("advice", "advice.json"), ("anchors", "anchors.json"),
                 ("gates_ledger", "gates_ledger.json")]
    nav = "".join(_link(links.get(key), text) for key, text in views)
    docs = "".join(_link(links.get(key), text) for key, text in documents)
    parts = "".join(_link(href, f"campaign {cid}") for cid, href in (links.get("parts") or {}).items())
    archive = (f'<p class=muted>The documents and the campaigns\' parts are inside the archive: '
               f'<a href="{escape(links["archive"])}">download it</a>.</p>' if links.get("archive") else "")
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Study {escape(sid)}</title>\n'
            f'<style>{STYLE}</style>\n</head>\n<body>\n<main data-contract="{CONTRACT}">\n'
            f'<h1>{escape(title)}</h1>\n<p class=muted>Made on build {escape(str(study.get("build_number") or "?"))}'
            + (f', this page written on build {escape(str(study["page_build"]))} from its reports'
               if study.get("page_build") and str(study.get("page_build")) != str(study.get("build_number")) else "")
            + '. '
            "Everything on this page is computed from the reports in this bundle; it is a reading, not a verdict, and "
            "nothing in the fleet decides on it.</p>\n"
            f"<nav>{nav}</nav><nav>{docs}{parts}</nav>{archive}\n"
            f"<section><h2>What the study found</h2>{_found(campaigns, classify or [], advice, missing, study.get("read_utc"))}</section>\n"
            f"<section><h2>What deserves a closer look</h2>{_advice(advice, links.get('explorer'))}</section>\n"
            f"<section><h2>What a law costs before it runs</h2>{_cost(cost or [])}</section>\n"
            "</main>\n</body>\n</html>\n")


def links_inside(parts: dict[str, str]) -> dict:
    return {"explorer": "explorer.html", "gate_trees": "gate_trees.html", "study": "study.json", "advice": "advice.json",
            "anchors": "anchors.json", "gates_ledger": "gates_ledger.json",
            "parts": {cid: f"{part}/" for cid, part in parts.items()}}


def links_beside(stem: str) -> dict:
    return {"explorer": f"{stem}.explorer.html", "gate_trees": f"{stem}.gate_trees.html",
            "advice": f"{stem}.advice.json", "archive": f"{stem}.tar.zst"}
