from __future__ import annotations

import numpy as np

from graph_scale_dynamics.domain import chain_list as CL
from graph_scale_dynamics.measurements import certificate

WINDOW = "window"
LATE_FROM = 0.4


def tau_of(phi: float) -> float:
    return (1.0 + phi) / (1.0 - phi)


def phi_for(tau: float) -> float:
    return (tau - 1.0) / (tau + 1.0)


def ar1(phi: float, points: int, replicates: int, rng: np.random.Generator) -> np.ndarray:
    noise = rng.standard_normal((replicates, points))
    out = np.empty((replicates, points))
    out[:, 0] = noise[:, 0] / np.sqrt(1.0 - phi * phi)
    for t in range(1, points):
        out[:, t] = phi * out[:, t - 1] + noise[:, t]
    return out


def envelope_of(series) -> dict:
    trajectory = [{"energy": float(value), "move": float(t)} for t, value in enumerate(series)]
    return {"n": 1, "sweeps": len(series), "chains": [{"start": CL.FROM_EMPTY}],
            "sampling_checkpoint": {"chains": [{"start": CL.FROM_EMPTY, "trajectory": trajectory}]}}


def late_of(series) -> np.ndarray:
    series = np.asarray(series, dtype=float)
    return series[int(len(series) * LATE_FROM):]


def window_count(series) -> float | None:
    found = certificate.equilibration_certificate(envelope_of(series))
    if found is None:
        return None
    counted = found.get("effective_samples_counted")
    return counted["windowed"] if counted else found["effective_samples"]


def batch_means_count(series, batches: int) -> float | None:
    late = late_of(series)
    size = len(late) // batches
    if size < 2 or batches < 2:
        return None
    used = late[len(late) - size * batches:]
    spread = float(used.var(ddof=1))
    if not np.isfinite(spread) or spread <= 0:
        return None
    means = used.reshape(batches, size).mean(axis=1)
    tau = max(1.0, size * float(means.var(ddof=1)) / spread)
    return len(used) / tau


def name_of(batches: int) -> str:
    return f"window_and_batch_means_{batches}"


def counts(series, batch_counts) -> dict:
    window = window_count(series)
    out = {WINDOW: window}
    for batches in batch_counts:
        other = batch_means_count(series, batches)
        out[name_of(batches)] = None if window is None or other is None else min(window, other)
    return out


RUNG_CONTRACT = "gsd-certificate-known-answers-2"
RUNG_CHAIN_NAMES = (CL.FROM_EMPTY, CL.GIVEN, "c2", "c3", "c4", "c5", "c6", "c7")


def rung_envelope(series_list) -> dict:
    names = RUNG_CHAIN_NAMES[:len(series_list)]
    blocks = [{"start": name, "trajectory": [{"energy": float(v), "move": float(t)} for t, v in enumerate(series)]}
              for name, series in zip(names, series_list, strict=True)]
    return {"n": 1, "sweeps": len(series_list[0]), "chains": [{"start": name} for name in names],
            "sampling_checkpoint": {"chains": blocks}}


def own_count_of(series) -> float | None:
    found = certificate.own_count(envelope_of(series), CL.FROM_EMPTY)
    return None if found is None else found["effective_samples"]


def rung_count(counts) -> float | None:
    return None if any(value is None for value in counts) else min(counts)


def _drawn_counts(true_samples: float, chains: int, replicates: int, points: int, seed: int) -> np.ndarray:
    late = len(late_of(np.zeros(points)))
    phi = phi_for(late / true_samples)
    drawn = ar1(phi, points, chains * replicates, np.random.default_rng(seed))
    counts = [own_count_of(row) for row in drawn]
    return np.asarray([np.nan if value is None else value for value in counts], dtype=float).reshape(replicates, chains)


def measure_rungs(criterion: dict) -> list[dict]:
    points, seed = criterion["series"]["points"], criterion["series"]["seed"]
    rows = []
    for rung_index, rung in enumerate(criterion["rungs"]):
        k, replicates = int(rung["chains"]), int(rung["replicates"])
        pools = {true: _drawn_counts(true, k, replicates, points, seed + 1000 * rung_index + index)
                 for index, true in enumerate(criterion["true_samples"])}
        for true, pool in pools.items():
            every = {str(t): int(np.sum(np.all(pool >= t, axis=1))) for t in criterion["thresholds"]}
            alone = {str(t): int(np.sum(pool[:, 0] >= t)) for t in criterion["thresholds"]}
            starved, starved_alone = {}, {}
            for threshold in criterion["thresholds"]:
                plenty = pools[criterion["rule"]["plenty_from"] * threshold]
                mixed = np.concatenate([plenty[:, :k - 1], pool[:, k - 1:]], axis=1)
                starved[str(threshold)] = int(np.sum(np.all(mixed >= threshold, axis=1)))
                starved_alone[str(threshold)] = int(np.sum(mixed[:, 0] >= threshold))
            rows.append({"chains": k, "true_samples": true, "replicates": replicates,
                         "unread_chains": int(np.sum(np.isnan(pool))),
                         "every_chain": every, "the_chain_from_empty_alone": alone,
                         "one_starved": starved, "one_starved_by_the_chain_from_empty_alone": starved_alone,
                         "per_chain": {str(t): round(float(np.mean(pool >= t)), 4) for t in criterion["thresholds"]}})
    return rows


def judge_rungs(criterion: dict, rows: list[dict]) -> dict:
    rule = criterion["rule"]
    out = {}
    for threshold in criterion["thresholds"]:
        t = str(threshold)
        by_rung = {}
        for k in sorted({row["chains"] for row in rows}):
            mine = [row for row in rows if row["chains"] == k]
            low = [row for row in mine if row["true_samples"] <= threshold * rule["too_few_at_most"]]
            high = [row for row in mine if row["true_samples"] >= threshold * rule["plenty_from"]]

            def rate(row, key):
                return row[key][t] / row["replicates"]
            k1 = max(rate(row, "every_chain") for row in low)
            k2 = min(rate(row, "every_chain") for row in high)
            k3 = max(rate(row, "one_starved") for row in low)
            k3_alone = max(rate(row, "one_starved_by_the_chain_from_empty_alone") for row in low)
            by_rung[str(k)] = {
                "false_pass_worst": round(k1, 4), "kept_worst": round(k2, 4), "starved_pass_worst": round(k3, 4),
                "starved_pass_worst_by_the_chain_from_empty_alone": round(k3_alone, 4),
                "k1": k1 <= rule["false_pass_at_most"], "k2": k2 >= rule["kept_at_least"],
                "k3": k3 <= rule["false_pass_at_most"], "k3_by_the_chain_from_empty_alone": k3_alone <= rule["false_pass_at_most"],
                "kept_by_true_samples": {str(row["true_samples"]): round(rate(row, "every_chain"), 4) for row in mine},
                "kept_by_one_chain": {str(row["true_samples"]): row["per_chain"][t] for row in mine},
                "starved_by_true_samples": {str(row["true_samples"]): round(rate(row, "one_starved"), 4) for row in mine},
                "starved_by_the_chain_from_empty_alone": {
                    str(row["true_samples"]): round(rate(row, "one_starved_by_the_chain_from_empty_alone"), 4)
                    for row in mine}}
            by_rung[str(k)]["passes"] = by_rung[str(k)]["k1"] and by_rung[str(k)]["k2"] and by_rung[str(k)]["k3"]
        out[t] = {"rungs": by_rung, "fit": all(row["passes"] for row in by_rung.values())}
    return {"contract": RUNG_CONTRACT, "rule": rule, "thresholds": criterion["thresholds"], "by_threshold": out,
            "fit_at": [t for t in criterion["thresholds"] if out[str(t)]["fit"]], "rows": rows}


def render_rungs(judged: dict) -> str:
    rule = judged["rule"]
    lines = ["# Every chain its own count, on series whose answer is known", "",
             f"{judged['contract']}, against `{judged.get('criterion', 'its criterion')}`, committed before any rung was "
             "drawn. Each chain of a rung is its own AR(1) series of 240 points, read by the count every chain runs (the "
             "smaller of the windowed sum and the 8-batch means, on its late 60%); the rung's count is the smallest. Beside "
             "it, the count on the chain from empty alone, which cannot see a starved chain.", "",
             f"K1: a rung whose every chain has at most T/8 true samples is certified at most "
             f"{rule['false_pass_at_most']:.0%} of the time. K2: a rung whose every chain has at least 4T, at least "
             f"{rule['kept_at_least']:.0%}. K3: a rung one of whose chains has at most T/8 and every other 4T, at most "
             f"{rule['false_pass_at_most']:.0%}.", ""]
    for threshold in judged["thresholds"]:
        block = judged["by_threshold"][str(threshold)]
        lines += [f"## Asked for {threshold} effective samples", "",
                  "| chains | K1 worst | K2 worst | K3 worst | K3 by the chain from empty alone | verdict |",
                  "|---:|---:|---:|---:|---:|---|"]
        for k, read in block["rungs"].items():
            mark = lambda ok: "held" if ok else "missed"
            lines.append(f"| {k} | {read['false_pass_worst']:.1%} ({mark(read['k1'])}) | {read['kept_worst']:.1%} "
                         f"({mark(read['k2'])}) | {read['starved_pass_worst']:.1%} ({mark(read['k3'])}) | "
                         f"{read['starved_pass_worst_by_the_chain_from_empty_alone']:.1%} "
                         f"({mark(read['k3_by_the_chain_from_empty_alone'])}) | {'fit' if read['passes'] else 'not fit'} |")
        trues = list(next(iter(block["rungs"].values()))["kept_by_true_samples"])
        lines += ["", "Share of rungs certified, by true samples of every chain (one chain alone beside):", "",
                  "| chains | " + " | ".join(trues) + " |", "|---:|" + "---:|" * len(trues)]
        for k, read in block["rungs"].items():
            lines.append(f"| {k} | " + " | ".join(f"{read['kept_by_true_samples'][t]:.1%}" for t in trues) + " |")
        first = next(iter(block["rungs"].values()))
        lines.append("| 1 | " + " | ".join(f"{first['kept_by_one_chain'][t]:.1%}" for t in trues) + " |")
        lines.append("")
    fit = ", ".join(str(t) for t in judged["fit_at"]) or "no threshold"
    lines += [f"Every chain's own count is fit at {fit}.", ""]
    return "\n".join(lines)
