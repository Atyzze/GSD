from __future__ import annotations

import math
from collections import Counter

from graph_scale_dynamics.domain import chain_list as CL

STORY_CONTRACT = "what-happened-1"
SIGNS = ("neg", "zero", "pos")
MOTION_SHARE = 0.5


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def motion(accounting: dict | None) -> dict | None:
    counts = ((accounting or {}).get("late") or {}).get("counts") or {}
    if not counts:
        return None
    accepted = {s: sum(v for k, v in counts.items() if k.endswith(f".{s}.accepted")) for s in SIGNS}
    proposed = sum(counts.values())
    total = sum(accepted.values())
    if total == 0:
        return {"accepted": 0, "proposed": proposed, "label": "frozen",
                "text": f"no move was accepted in the late window ({proposed:,} proposed)"}
    share = {s: accepted[s] / total for s in SIGNS}
    if share["neg"] >= MOTION_SHARE:
        label = "descending"
    elif share["zero"] >= MOTION_SHARE:
        label = "wandering on a plateau"
    elif share["pos"] >= 0.2 and share["neg"] >= 0.2:
        label = "thermal motion"
    else:
        label = "mixed"
    return {"accepted": total, "proposed": proposed, "acceptance": total / max(1, proposed),
            "share": {s: round(v, 4) for s, v in share.items()}, "label": label,
            "text": (f"{label}: of {total:,} accepted late moves, {share['neg']:.0%} lowered the energy, "
                     f"{share['zero']:.0%} changed nothing, {share['pos']:.0%} raised it "
                     f"(acceptance {total / max(1, proposed):.1%})")}


def _certificate(metrics: dict) -> dict:
    health = metrics.get("health") or {}
    checkpoints = health.get("sampling_checkpoints") or []
    last = checkpoints[-1] if checkpoints else {}
    cert = last.get("certificate") or {}
    eq = health.get("equilibration") or {}
    split = cert.get("split") or eq.get("split") or {}
    return {"failures": sorted({str(f.get("code")) for f in (last.get("failures") or []) if isinstance(f, dict)}),
            "effective_samples": _num(cert.get("effective_samples", eq.get("effective_samples"))),
            "split_z": max((_num(v) or 0.0 for v in split.values()), default=None) if split else None,
            "structural": {k: _num(v) for k, v in (cert.get("structural_split") or eq.get("structural_split") or {}).items()},
            "limits": cert.get("structural_limits") or {},
            "drift": _num(cert.get("stationarity_drift", (health.get("stationarity") or {}).get("normalized_drift"))),
            "multiplier": last.get("multiplier"), "asked": cert.get("asked") or {}}


def first_given_name(metrics: dict) -> str:
    recorded = (((metrics.get("health") or {}).get("rung_terminal") or {}).get("given_chains")) or []
    first = recorded[0].get("name") if recorded and isinstance(recorded[0], dict) else None
    return str(first or CL.GIVEN)


def every_chain(metrics: dict) -> list[tuple[str, str]]:
    keys = list(dict.fromkeys([*CL.chains_in(metrics.get("census")), *CL.chains_in(metrics.get("move_accounting"))]))
    keys = [CL.FROM_EMPTY, CL.GIVEN] + [key for key in keys if key not in (CL.FROM_EMPTY, CL.GIVEN)]
    return [(first_given_name(metrics) if key == CL.GIVEN else key, key) for key in keys]


def given_chains(metrics: dict) -> list[tuple[str, dict | None, dict | None]]:
    census, accounting = metrics.get("census") or {}, metrics.get("move_accounting") or {}
    return [(shown, CL.of_chain(census, key), CL.of_chain(accounting, key))
            for shown, key in every_chain(metrics) if key != CL.FROM_EMPTY]


def _census_pair(metrics: dict, n: int) -> dict | None:
    census = metrics.get("census") or {}
    out = {}
    chains = [(shown, CL.of_chain(census, key)) for shown, key in every_chain(metrics)]
    for chain, c in chains:
        if not c:
            continue
        giant = c.get("largest_component") or {}
        out[chain] = {"giant_fraction": (giant.get("size") or 0) / max(1, n),
                      "gap": _num((giant.get("spectral_gap") or {}).get("value")),
                      "diameter": (giant.get("diameter") or {}).get("lower_bound"),
                      "cycles_per_node": (giant.get("cycle_rank") or 0) / max(1, n),
                      "components": (c.get("components") or {}).get("count")}
    return out or None


def law_story(measurements: list[dict], decision: dict | None = None) -> dict:
    rows = [m for m in measurements or [] if m.get("metrics")]
    if not rows:
        return {"contract": STORY_CONTRACT, "rung": None, "clauses": [],
                "why": "no measured seed to read"}
    top = max(int(m["n"]) for m in rows)
    seeds = [m for m in rows if int(m["n"]) == top]
    clauses = []
    if decision:
        clauses.append({"topic": "decision", "text": f"{decision.get('action')} ({decision.get('rule')}) at "
                        f"N={decision.get('at_n')}: {decision.get('reason')}"})
    ends = Counter()
    for m in seeds:
        terminal = ((m["metrics"].get("health") or {}).get("rung_terminal")) or {}
        ends[(terminal.get("reason") or "not recorded", terminal.get("classification") or "")] += 1
    clauses.append({"topic": "how the seeds ended", "numbers": {f"{r}:{c}": k for (r, c), k in ends.items()},
                    "text": "; ".join(f"{k} of {len(seeds)} seeds ended {r}" + (f" ({c})" if c else "")
                                      for (r, c), k in ends.most_common())})
    certs = [_certificate(m["metrics"]) for m in seeds]
    failing = Counter(code for c in certs for code in c["failures"])
    parts = []
    asked: dict = {}
    for c in certs:
        asked.update(c["asked"])
    ess = [c["effective_samples"] for c in certs if c["effective_samples"] is not None]
    if ess:
        parts.append(f"effective samples {min(ess):.1f} to {max(ess):.1f} ({_asked(asked, 'effective_samples', 'needed')})")
    zs = [c["split_z"] for c in certs if c["split_z"] is not None]
    if zs:
        parts.append(f"split z between the twin starts' chains up to {max(zs):.2f} ({_asked(asked, 'split_z', 'allowed')})")
    struct: dict[str, list] = {}
    limits = {}
    for c in certs:
        limits.update(c["limits"] or {})
        for key, value in c["structural"].items():
            if value is not None:
                struct.setdefault(key, []).append(value)
    for key, values in sorted(struct.items()):
        limit = limits.get(key)
        spread = (max(values) - min(values)) if len(values) > 1 else None
        parts.append(f"the chains' {key.replace('_', ' ')} gap up to {max(values):.3f}"
                     + (f" against {limit}" if limit is not None else "")
                     + (f", seed spread {spread:.3f}" if spread is not None else ""))
    drifts = [abs(c["drift"]) for c in certs if c["drift"] is not None]
    if drifts:
        parts.append(f"late drift up to {max(drifts):.2f} ({_asked(asked, 'drift', 'allowed')})")
    clauses.append({"topic": "the certificate on the last chunk",
                    "numbers": {"failures": dict(failing)},
                    "text": ("passed on every seed" if not failing else
                             "failed: " + ", ".join(f"{code} on {k} of {len(seeds)}" for code, k in failing.most_common()))
                            + ("; " + "; ".join(parts) if parts else "")})
    names = list(dict.fromkeys(name for m in seeds for name, _, _ in given_chains(m["metrics"])))
    shown_keys = {shown: key for m in seeds for shown, key in every_chain(m["metrics"])}
    for chain in ["empty", *names]:
        moves = [motion(CL.of_chain(m["metrics"].get("move_accounting"), shown_keys.get(chain, chain))) for m in seeds]
        moves = [x for x in moves if x]
        if not moves:
            clauses.append({"topic": f"how the chains from the {chain} start moved",
                            "text": "no move accounting on these seeds"})
            continue
        labels = Counter(x["label"] for x in moves)
        clauses.append({"topic": f"how the chains from the {chain} start moved", "numbers": dict(labels),
                        "text": "; ".join(f"seed {i}: {x['text']}" for i, x in enumerate(moves))})
    for shown in ["empty", *names]:
        clauses.append({"topic": f"how the chains from the {shown} start came to rest",
                        "text": "; ".join(_came_to_rest(seeds, shown_keys.get(shown, shown)))})
    pairs = [_census_pair(m["metrics"], top) for m in seeds]
    finals = []
    for i, pair in enumerate(pairs):
        if not pair:
            finals.append(f"seed {i}: no census of a chain")
            continue
        finals.append(f"seed {i}: " + "; ".join(
            f"{name} giant {c['giant_fraction']:.3f}, diameter {c['diameter']}"
            + (f", gap {c['gap']:.2e}" if c["gap"] else "") + f", cycles per node {c['cycles_per_node']:.3f}"
            for name, c in pair.items()))
    clauses.append({"topic": "every chain's final graph", "text": "; ".join(finals)})
    refusals = Counter()
    for m in seeds:
        for probe in ("d_s", "d_V", "d_B", "d_w"):
            p = m["metrics"].get(probe) or {}
            if isinstance(p, dict) and p.get("valid") is False:
                refusals[f"{probe}: {p.get('refusal') or 'refused'}"] += 1
    if refusals:
        clauses.append({"topic": "the probes", "numbers": dict(refusals),
                        "text": "; ".join(f"{k} on {v} of {len(seeds)} seeds" for k, v in sorted(refusals.items()))})
    return {"contract": STORY_CONTRACT, "rung": top, "seeds": len(seeds), "clauses": clauses}


def _asked(asked: dict, key: str, how: str) -> str:
    value = asked.get(key)
    return f"{float(value):g} {how}" if isinstance(value, (int, float)) else "the target not recorded"


def _came_to_rest(seeds: list[dict], key: str) -> list[str]:
    rest = []
    for i, m in enumerate(seeds):
        descent = m["metrics"].get("descent") or {}
        acc = CL.of_chain(m["metrics"].get("move_accounting"), key) or {}
        chains = descent.get("chains") or {}
        chain = chains.get(key) or chains.get(f"{CL.GIVEN}:{key}") or {}
        last, late_from = chain.get("last_decrease_move"), ((acc.get("late") or {}).get("from_move"))
        if last is None:
            rest.append(f"seed {i}: no descent record")
            continue
        label = (motion(acc) or {}).get("label")
        in_late = late_from is not None and last >= late_from
        text = f"seed {i}: " + {
            "descending": f"still descending, the energy last fell at move {last:,}, in the late window",
            "wandering on a plateau": (f"at rest on a plateau, the energy last fell at move {last:,}"
                                       + (", in the late window" if in_late else ", before the late window")),
            "thermal motion": f"in thermal motion, the energy rising and falling (last fall at move {last:,})",
            "frozen": f"frozen, no move accepted late (last fall at move {last:,})",
        }.get(label, f"the energy last fell at move {last:,}"
              + ("" if late_from is None else (", in the late window" if in_late else ", before the late window")))
        if chain.get("late_neutral_share") is not None:
            text += f"; {chain['late_neutral_share']:.0%} of late accepted moves changed nothing"
        if chain.get("distance_from_reference") is not None:
            ref = descent.get("reference") or {}
            text += (f"; {chain['distance_from_reference']:+.1f} energy from the reference "
                     f"({ref.get('kind')}, cliques of {ref.get('clique_size')})")
        rest.append(text)
    return rest

