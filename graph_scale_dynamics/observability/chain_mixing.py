from __future__ import annotations

import math

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements.certificate import integrated_autocorrelation_time
from graph_scale_dynamics.observability.meeting_reading import rung_meeting_reading
from graph_scale_dynamics.scaleflow.equilibration import CHAINS_DISAGREED_CODES, failure_codes

CONTRACT = "rung-chain-mixing-2"
OBSERVABLES = ("energy_per_node", "mean_degree", "isolated_fraction")
MIN_POINTS = 8


def _series(trajectory: list, observable: str, n: int) -> list[float]:
    values = []
    for point in trajectory or []:
        raw = (point.get("energy") / n if observable == "energy_per_node" and point.get("energy") is not None
               else point.get(observable))
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(float(raw)):
            values.append(float(raw))
    return values


def chain_halves(trajectory: list, n: int) -> dict:
    out: dict = {}
    for observable in OBSERVABLES:
        values = _series(trajectory, observable, n)
        kept = values[len(values) // 2:]
        if len(kept) < MIN_POINTS:
            out[observable] = None
            continue
        half = len(kept) // 2
        tau = integrated_autocorrelation_time(np.asarray(kept, dtype=float))
        out[observable] = {
            "halves": [{"count": half, "mean": float(np.mean(part)), "variance": float(np.var(part, ddof=1))}
                       for part in (kept[:half], kept[half:2 * half])],
            "effective_samples": (len(kept) / tau) if tau else None,
        }
    return out


SEED_KEYS = ("contract", "chain_seconds")


def seed_chain_moments(envelope: dict) -> dict:
    n = max(1, int(envelope.get("n") or 1))
    timing = ((envelope.get("rung_terminal") or {}).get("timing")) or {}
    out = {"contract": CONTRACT, "chain_seconds": dict(timing.get("chain_seconds") or {})}
    for row in CL.records(envelope):
        name = str(row.get("start"))
        if name in (CL.FROM_EMPTY, CL.GIVEN) or not row.get("skipped"):
            out[name] = chain_halves(CL.trajectory(envelope, name), n)
    return out


def seed_chains(seed: dict) -> dict:
    return {name: value for name, value in CL.chains_in(seed).items() if name not in SEED_KEYS}


def seed_seconds(seed: dict) -> dict:
    seconds = (seed or {}).get("chain_seconds") or {}
    if "empty_chain_seconds" in seconds or "given_chain_seconds" in seconds:
        out = {CL.FROM_EMPTY: seconds.get("empty_chain_seconds"), CL.GIVEN: seconds.get("given_chain_seconds")}
        out.update(seconds.get("more_given_chain_seconds") or {})
        return out
    return dict(seconds)


def split_rhat(halves: list[dict]) -> float | None:
    if len(halves) < 2:
        return None
    draws = min(int(h["count"]) for h in halves)
    if draws < 2:
        return None
    within = float(np.mean([h["variance"] for h in halves]))
    between = draws * float(np.var([h["mean"] for h in halves], ddof=1))
    if within <= 0.0:
        return 1.0 if between == 0.0 else None
    pooled = (draws - 1) / draws * within + between / draws
    return math.sqrt(pooled / within)


def rung_mixing(seed_metrics: list[dict]) -> dict:
    moments = [m.get("chain_mixing") for m in seed_metrics if isinstance(m.get("chain_mixing"), dict)]
    observables: dict = {}
    for observable in OBSERVABLES:
        halves, ess = [], []
        for seed in moments:
            for chain in ("empty", "given"):
                entry = (seed.get(chain) or {}).get(observable)
                if not entry:
                    continue
                halves.extend(entry["halves"])
                if entry.get("effective_samples"):
                    ess.append(float(entry["effective_samples"]))
        rhat = split_rhat(halves)
        per_chain = float(np.mean(ess)) if ess else None
        expected = math.sqrt(1.0 + 2.0 / per_chain) if per_chain else None
        observables[observable] = {
            "split_rhat": None if rhat is None else round(rhat, 6),
            "half_chains": len(halves),
            "effective_samples_per_chain": None if per_chain is None else round(per_chain, 3),
            "equilibrium_rhat": None if expected is None else round(expected, 6),
            "excess": None if rhat is None or expected is None else round(rhat - expected, 6),
        }
    chains_disagreed = sum(
        1 for m in seed_metrics
        if failure_codes(((m.get("health") or {}).get("rung_terminal") or {}).get("failures")) & CHAINS_DISAGREED_CODES)
    seconds = [seed_seconds(m.get("chain_mixing") or {}) for m in seed_metrics]
    out = {
        "contract": CONTRACT,
        "seeds": len(seed_metrics),
        "seeds_with_moments": len(moments),
        "observables": observables,
        "seeds_with_chains_disagreement": chains_disagreed,
        "meeting_reading": rung_meeting_reading(seed_metrics),
        "chain_seconds": {
            "empty": round(sum(float(s.get(CL.FROM_EMPTY) or 0.0) for s in seconds), 3),
            "given": round(sum(float(s.get(CL.GIVEN) or 0.0) for s in seconds), 3),
        },
    }
    more = sorted({str(name) for seed in moments for name in seed_chains(seed)
                   if name not in (CL.FROM_EMPTY, CL.GIVEN)})
    if more:
        out.update(every_chain_mixing(moments, more, seed_metrics, seconds))
    return out


def every_chain_mixing(moments: list[dict], names: list[str], seed_metrics: list[dict], seconds: list[dict]) -> dict:
    observables: dict = {}
    for observable in OBSERVABLES:
        halves = []
        for seed in moments:
            chains = list(seed_chains(seed).values())
            for chain in chains:
                entry = (chain or {}).get(observable)
                if entry:
                    halves.extend(entry["halves"])
        rhat = split_rhat(halves)
        observables[observable] = {"split_rhat": None if rhat is None else round(rhat, 6), "half_chains": len(halves)}
    more_seconds = {name: round(sum(float(s.get(name) or 0.0) for s in seconds), 3) for name in names}
    return {"every_chain": {"given_chains": names, "observables": observables,
                            "meeting_readings": {name: rung_meeting_reading(seed_metrics, name) for name in names},
                            "chain_seconds": more_seconds}}
