from __future__ import annotations

BASE, EXTENSION, LONGER = "base", "extension", "longer"
RUNG_STAGE, LONGER_STAGE, WINDOW_RERUN_STAGE = "rung", "longer", "window_rerun"


def simulation_role(job: dict, base_sizes) -> str | None:
    stage = str(job.get("stage") or "")
    requested_by = str(job.get("requested_by") or "")
    n = int(job.get("n") or 0)
    if stage.startswith(f"{LONGER_STAGE}_n") or stage.startswith(f"{WINDOW_RERUN_STAGE}_n"):
        return LONGER
    if stage.startswith(f"{RUNG_STAGE}_n"):
        return BASE if n in {int(size) for size in base_sizes or ()} else EXTENSION
    if requested_by == "campaign_rule:base_block" or stage.startswith("base_n"):
        return BASE
    if "extension" in requested_by.lower() or stage.startswith("extension_n"):
        return EXTENSION
    return None
