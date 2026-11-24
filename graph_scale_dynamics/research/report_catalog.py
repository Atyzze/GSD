from __future__ import annotations

from dataclasses import dataclass, asdict

REPORT_CATALOG_VERSION = "gsd-report-catalog-12"


@dataclass(frozen=True)
class ReportDefinition:
    code: str
    number: int
    slug: str
    title: str
    question: str
    cadence: str = "heavy"


REPORTS = (
    ReportDefinition("04", 4, "flow", "Dimensional Flow", "How do d_s, d_V and metric geometry evolve with N without preferring a target value?"),
    ReportDefinition("05", 5, "phenotypes", "Phenotype Atlas", "Which recurring multimetric graph-flow regions are actually populated?"),
    ReportDefinition("10", 10, "decisions", "Decision & Barrier Audit", "Why did complete phenotypes park, promote, audit, or remain inconclusive, and how brittle are the barriers?"),
    ReportDefinition("14", 14, "compute", "Compute Ecology", "What limits the fleet right now: CPU slots, RAM admission, work supply, lifecycle, scheduler, or operator underfill?", "fast"),
    ReportDefinition("16", 16, "efficiency", "Scientific Compute Efficiency", "What does each stage, size, sampling and operator cost, and what will a law cost?", "heavy"),
    ReportDefinition("22", 22, "stability-score", "Stability Score", "Does each of the four probes settle as N grows, and when a block scores zero, why: still drifting, never measured, or refused for which reason?", "heavy"),
    ReportDefinition("23", 23, "hang-autopsy", "Hang Autopsy", "Which laws cost the most compute, what stopped them (window cap, seed budget, multiplier ceiling), and what were they doing when they stopped?", "heavy"),
    ReportDefinition("25", 25, "fleet-and-host", "Fleet & Host", "Which campaign owns the executor fleet right now, and how did queue wait, attempt wall, failures and host load evolve hour by hour?", "fast"),
    ReportDefinition("28", 28, "decision-engine", "Decision Engine", "Why did the decision engine start, buy, hold or stop each law, what did each rule cost, and what would each final-verdict stop have lost on the audit sample?", "heavy"),)

REPORT_BY_CODE = {row.code: row for row in REPORTS}
REPORT_BY_NUMBER = {row.number: row for row in REPORTS}


def catalog_payload() -> dict:
    return {
        "version": REPORT_CATALOG_VERSION,
        "reports": [asdict(row) for row in REPORTS],
        "next_report_number": max(row.number for row in REPORTS) + 1,
        "ui_contract": {
            "one_report_per_screen": True,
            "poll_seconds": 4,
            "max_requests_per_poll_cycle": 2,
            "generation_mode": "automatic_immutable_api_snapshot",
            "background_generation": True,
            "requires_pause_and_quiescence": False,
            "report_service_database_access": False,
            "snapshot_transport": "loopback_internal_api",
            "disposable_snapshot_worker": False,
            "snapshot_process_boundary": "disposable_child_process",
            "volatile_snapshot_transport": True,
            "snapshot_preprocessing_progress": True,
            "public_report_identity": "sequential_number",
            "stale_snapshot_is_valid": True,
        },
    }
