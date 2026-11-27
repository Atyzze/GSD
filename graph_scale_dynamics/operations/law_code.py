from __future__ import annotations

import re

CONTRACT = "gsd-law-code-1"
_PARSE = re.compile(r"^(?:s(?P<study>[a-z0-9._]+?)-?)?c(?P<campaign>\d+)-?"
                    r"(?:g-?(?P<graph>\d+)|(?P<law>[0-9a-f]{6,64}))$")
_LABEL = re.compile(r"^C(?P<campaign>\d+)-(?:G(?P<graph>\d+)|(?P<law>[0-9a-f]{6,64}))$")
_WHOLE = re.compile(r"^S(?P<study>[A-Za-z0-9._]+?)-?C(?P<campaign>\d+)-?(?:G(?P<graph>\d+)|(?P<law>[0-9a-f]{6,64}))$")


def code(study, campaign, graph=None, law=None) -> str:
    head = f"S{study}-" if study not in (None, "") else ""
    if graph is not None:
        return f"{head}C{campaign}-G{int(graph)}"
    return f"{head}C{campaign}-{str(law or '')[:8]}"


def parse(text) -> dict | None:
    found = _PARSE.match(re.sub(r"\s+", "", str(text or "")).lower())
    if found is None:
        return None
    return {"study": found["study"], "campaign": found["campaign"],
            "graph": None if found["graph"] is None else int(found["graph"]), "law": found["law"]}


def same(text, other) -> bool:
    a, b = parse(text), parse(other)
    if a is None or b is None or a["campaign"] != b["campaign"]:
        return False
    if a["study"] is not None and b["study"] is not None and a["study"] != b["study"]:
        return False
    if a["graph"] is not None or b["graph"] is not None:
        return a["graph"] == b["graph"]
    return bool(a["law"]) and bool(b["law"]) and (a["law"].startswith(b["law"]) or b["law"].startswith(a["law"]))


def upgraded(label, study) -> str | None:
    if label is None:
        return label
    found = _LABEL.match(str(label))
    if found is not None:
        return label if study in (None, "") else code(study, found["campaign"], found["graph"], found["law"])
    whole = _WHOLE.match(str(label))
    if whole is None:
        return label
    return code(whole["study"], whole["campaign"], whole["graph"], whole["law"])


def study_of(repo, campaign_id, known: dict | None = None):
    key = str(campaign_id)
    if known is not None and key in known:
        return known[key]
    campaign = repo.campaign(key) if callable(getattr(repo, "campaign", None)) else None
    study = (((campaign or {}).get("spec") or {}).get("study_design") or {}).get("study")
    study = None if study in (None, "") else str(study)
    if known is not None:
        known[key] = study
    return study


def graphs(repo, campaign_id) -> dict[str, int]:
    return {str(row["candidate_id"]): int(row["g"]) for row in repo.conn.execute(
        "SELECT candidate_id, MIN(graph_ordinal) AS g FROM jobs WHERE campaign_id=? AND kind='simulate' "
        "AND graph_ordinal IS NOT NULL GROUP BY candidate_id", (str(campaign_id),)).fetchall()}


def of(repo, campaign_id, law, *, graph=None, known: dict | None = None) -> str:
    if graph is None:
        row = repo.conn.execute(
            "SELECT MIN(graph_ordinal) AS g FROM jobs WHERE campaign_id=? AND candidate_id=? AND kind='simulate' "
            "AND graph_ordinal IS NOT NULL", (str(campaign_id), str(law))).fetchone()
        graph = None if row is None or row["g"] is None else int(row["g"])
    return code(study_of(repo, campaign_id, known), campaign_id, graph, law)


__all__ = ["CONTRACT", "code", "graphs", "of", "parse", "same", "study_of", "upgraded"]
