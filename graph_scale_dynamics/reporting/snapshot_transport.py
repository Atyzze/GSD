from __future__ import annotations

import json
from typing import Any

from graph_scale_dynamics.research.strict_json import sanitize_json_in_place

DIAGNOSTICS_KEY = "_snapshot_json_sanitization"
SAMPLE_ROWS = 200
NAMED_PARTS = 24


def in_transport_types(snapshot: Any) -> Any:
    converted, diagnostics = sanitize_json_in_place(snapshot)
    if isinstance(converted, dict):
        converted[DIAGNOSTICS_KEY] = json.loads(json.dumps(diagnostics))
    return converted


def json_bytes(value: Any, *, sample: int = SAMPLE_ROWS) -> tuple[int, bool]:
    if isinstance(value, dict):
        keys = list(value)
        picked = _spread(len(keys), sample)
        sizes = [len(json.dumps(keys[i])) + 1 + _text(value[keys[i]]) for i in picked]
    elif isinstance(value, list):
        picked = _spread(len(value), sample)
        sizes = [_text(value[i]) for i in picked]
    else:
        return _text(value), False
    count = len(value)
    if not count:
        return 2, False
    estimated = len(picked) < count
    rows = sum(sizes) * count / len(picked) if estimated else sum(sizes)
    return int(round(2 + (count - 1) + rows)), estimated


def volume(replication: Any, *, sample: int = SAMPLE_ROWS, named: int = NAMED_PARTS) -> dict:
    if not isinstance(replication, dict):
        size, estimated = json_bytes(replication, sample=sample)
        return {"json_bytes": size, "estimated": estimated, "sample_rows": sample, "parts": [], "other_json_bytes": 0}
    parts, total, estimated = [], 2 + max(0, len(replication) - 1), False
    for key, value in replication.items():
        total += len(json.dumps(key)) + 1
        if key == "campaign_snapshots" and isinstance(value, list):
            total += 2 + max(0, len(value) - 1)
            for campaign in value:
                if not isinstance(campaign, dict):
                    size, guessed = json_bytes(campaign, sample=sample)
                    total, estimated = total + size, estimated or guessed
                    continue
                total += 2 + max(0, len(campaign) - 1)
                for part, rows in campaign.items():
                    size, guessed = json_bytes(rows, sample=sample)
                    total, estimated = total + len(json.dumps(part)) + 1 + size, estimated or guessed
                    if isinstance(rows, (list, dict)):
                        parts.append({"campaign_id": str(campaign.get("campaign_id")),
                                      "scope": str(campaign.get("snapshot_scope") or ""), "part": str(part),
                                      "rows": len(rows), "json_bytes": size})
            continue
        size, guessed = json_bytes(value, sample=sample)
        total, estimated = total + size, estimated or guessed
    parts.sort(key=lambda row: -row["json_bytes"])
    return {"json_bytes": int(total), "estimated": estimated, "sample_rows": sample, "parts": parts[:named],
            "other_json_bytes": int(sum(row["json_bytes"] for row in parts[named:]))}


def _spread(count: int, sample: int) -> list[int]:
    if count <= sample:
        return list(range(count))
    return sorted({round(i * (count - 1) / (sample - 1)) for i in range(sample)})


def _text(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")))
