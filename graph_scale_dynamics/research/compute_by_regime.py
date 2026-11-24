from __future__ import annotations

from collections import defaultdict

REGIMES = ("zero_temperature", "finite_temperature", "unrecorded")

BY_RUNG_SQL = (
    "SELECT c.work_kind, c.n, s.zero_temperature, count(*) AS attempts, "
    "count(DISTINCT c.candidate_id) AS laws, COALESCE(sum(c.attributed_core_seconds), 0) AS core_seconds "
    "FROM compute_ledger c LEFT JOIN candidate_specs s ON s.candidate_id = c.candidate_id "
    "WHERE (? = '' OR c.campaign_id = ?) GROUP BY c.work_kind, c.n, s.zero_temperature"
)
LAWS_SQL = (
    "SELECT cc.candidate_id, s.zero_temperature, d.rule, d.action, d.at_n, r.top_n "
    "FROM campaign_candidates cc LEFT JOIN candidate_specs s ON s.candidate_id = cc.candidate_id "
    "LEFT JOIN engine_decisions_latest d ON d.campaign_id = cc.campaign_id AND d.candidate_id = cc.candidate_id "
    "LEFT JOIN (SELECT campaign_id, candidate_id, max(n) AS top_n FROM rung_summaries "
    "GROUP BY campaign_id, candidate_id) r ON r.campaign_id = cc.campaign_id AND r.candidate_id = cc.candidate_id "
    "WHERE (? = '' OR cc.campaign_id = ?)"
)


def regime(zero_temperature) -> str:
    if zero_temperature is None:
        return "unrecorded"
    return "zero_temperature" if bool(zero_temperature) else "finite_temperature"


def share(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def summarise(by_rung_rows: list[dict], law_rows: list[dict]) -> dict:
    seconds = defaultdict(float)
    by_rung: dict[str, dict] = defaultdict(dict)
    for row in by_rung_rows:
        name = regime(row.get("zero_temperature"))
        core = float(row.get("core_seconds") or 0.0)
        seconds[name] += core
        key = f"{row.get('work_kind')}:{row.get('n') if row.get('n') is not None else '-'}"
        by_rung[name][key] = {"attempts": int(row.get("attempts") or 0), "laws": int(row.get("laws") or 0),
                              "core_seconds": round(core, 1)}
    laws = defaultdict(int)
    by_rule: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    reached: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for row in law_rows:
        name = regime(row.get("zero_temperature"))
        laws[name] += 1
        by_rule[name][str(row.get("rule") or "no decision yet")] += 1
        reached[name][str(row.get("top_n") or "none")] += 1
    total_seconds, total_laws = sum(seconds.values()), sum(laws.values())
    cold_seconds, cold_laws = seconds["zero_temperature"], laws["zero_temperature"]
    readings = [
        f"zero temperature: {cold_laws} of {total_laws} laws "
        f"({(share(cold_laws, total_laws) or 0) * 100:.1f}%) and {cold_seconds / 3600:.1f} of "
        f"{total_seconds / 3600:.1f} core hours ({(share(cold_seconds, total_seconds) or 0) * 100:.1f}%)",
    ]
    if cold_laws:
        top = sorted(((int(k), v) for k, v in reached["zero_temperature"].items() if k != "none"), reverse=True)
        readings.append("deepest rung a zero-temperature law finished: "
                        + (f"N={top[0][0]} ({top[0][1]} laws)" if top else "none"))
        common = sorted(by_rule["zero_temperature"].items(), key=lambda kv: -kv[1])[:3]
        readings.append("their latest decisions: " + ", ".join(f"{rule} {count}" for rule, count in common))
    if laws["unrecorded"]:
        readings.append(f"{laws['unrecorded']} laws have no recorded dynamics")
    return {
        "readings": readings,
        "laws": {name: laws[name] for name in REGIMES},
        "core_seconds": {name: round(seconds[name], 1) for name in REGIMES},
        "law_share": {name: share(laws[name], total_laws) for name in REGIMES},
        "core_second_share": {name: share(seconds[name], total_seconds) for name in REGIMES},
        "top_rung_reached": {name: dict(reached[name]) for name in REGIMES if reached[name]},
        "by_rung": {name: by_rung[name] for name in REGIMES if by_rung[name]},
        "by_rule": {name: dict(by_rule[name]) for name in REGIMES if by_rule[name]},
    }
