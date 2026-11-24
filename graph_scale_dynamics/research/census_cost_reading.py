from __future__ import annotations

from collections import defaultdict

FROM_N = 16384
SLOWEST = 12


def _chains(census: dict) -> dict:
    from graph_scale_dynamics.domain.chain_list import chains_in
    return {name: c for name, c in chains_in(census).items() if isinstance(c, dict)}


def _read(law: str, n: int, seed, chain: str, c: dict) -> dict:
    giant = c.get("largest_component") or {}
    gap = giant.get("spectral_gap") or {}
    diameter = giant.get("diameter") or {}
    return {"law": law[:12], "n": n, "seed": seed, "chain": chain,
            "method": gap.get("method") or "none", "seconds": gap.get("seconds"),
            "reason": (str(gap.get("reason"))[:80] if gap.get("reason") else None),
            "giant": giant.get("size"), "diameter_lower_bound": diameter.get("lower_bound"),
            "census_seconds": c.get("seconds")}


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))], 3)


def census_cost(snapshot: dict, failed: list[dict] | None = None) -> dict:
    wanted = {(str(f["law"])[:12], int(f["n"]) // 4) for f in failed or [] if f.get("n")}
    seconds: dict = defaultdict(list)
    reads, before = [], []
    for m in snapshot.get("measurements") or []:
        n = int(m.get("n") or 0)
        law = str(m.get("candidate_id") or "")
        key = (law[:12], n)
        if n < FROM_N and key not in wanted:
            continue
        for chain, c in _chains(((m.get("metrics") or {}).get("census")) or {}).items():
            read = _read(law, n, m.get("seed"), chain, c)
            if key in wanted:
                before.append(read)
            if n >= FROM_N:
                if isinstance(read["seconds"], (int, float)):
                    seconds[(n, read["method"])].append(float(read["seconds"]))
                reads.append(read)
    by_size: dict = {}
    for (n, method), values in sorted(seconds.items()):
        by_size.setdefault(str(n), {})[method] = {
            "reads": len(values), "median_seconds": _quantile(values, 0.5),
            "p90_seconds": _quantile(values, 0.9), "max_seconds": round(max(values), 3)}
    timed = [r for r in reads if isinstance(r["seconds"], (int, float))]
    slowest = sorted(timed, key=lambda r: (-r["seconds"], r["law"], r["n"], str(r["seed"]), r["chain"]))[:SLOWEST]
    return {"from_n": FROM_N, "by_size_and_method": by_size, "slowest": slowest,
            "failed_laws_before": sorted(before, key=lambda r: (r["law"], r["n"], str(r["seed"]), r["chain"])),
            "interpretation": (
                "Each chain's spectral gap at each size from 16,384: how it was read (shift-invert factorises the "
                "Laplacian, chosen where the diameter's lower bound passes four log2 of the giant component's size; "
                "Lanczos otherwise) and how long it took. A failed analysis leaves no census, so a law whose analysis "
                "failure still stands is shown at the size before, the last its chains finished.")}
