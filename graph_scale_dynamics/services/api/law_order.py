from __future__ import annotations

import re

from graph_scale_dynamics.observability import law_score as _law_score

LAST = float("inf")
LATTICE_WHO = tuple(kind for kind, _weight in _law_score.WEIGHTS if kind not in _law_score.TWINS)
_DIGITS = re.compile(r"(\d+)\s*$")


def campaign_number(row: dict) -> float:
    found = str(row.get("campaign_id") if row.get("campaign_id") is not None else "")
    return float(found) if found.isdigit() else LAST


def graph_number(row: dict) -> float:
    found = _DIGITS.search(str(row.get("ensemble_code") or ""))
    return float(found.group(1)) if found else LAST


def law_rank(row: dict) -> tuple:
    found = row.get("law_score") or {}
    return (-int(found.get("score") or 0), campaign_number(row), graph_number(row), str(row.get("candidate_id") or ""))
