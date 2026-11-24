from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from graph_scale_dynamics.observability.evidence_sources import runtime_import_record

EVIDENCE_CONTRACT = "gsd-bundle-evidence-1"
EVIDENCE_DIR = "evidence"

EVIDENCE_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("calibration", "/api/calibration", "json"),
    ("probe_calibration", "/api/calibration/table", "json"),
    ("system", "/api/overview/{c}", "json"),
    ("performance", "/api/performance/{c}", "json"),
    ("runtime_imports", "/api/runtime-imports", "json"),
    ("schema", "/api/schema", "json"),
    ("stranded", "/api/stranded/{c}", "json"),
    ("supervisor_tail", "/api/supervisor-log?lines=2000", "text"),
    ("memory_ledger", "/api/memory-ledger", "json"),
    ("api_samples/campaigns", "/api/campaigns", "json"),
    ("api_samples/landscape", "/api/landscape/{c}", "json"),
)

ROOT_COPIES: tuple[str, ...] = ("catalog.json", "api_access.json")


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def _discard(target: Path) -> None:
    for path in (target, target.with_name(target.name + ".tmp")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


CANDIDATE_SECTIONS: tuple[str, ...] = (
    "active", "dimension_points", "proposed", "best", "past", "candidates", "rows",
)


def _candidate_rows(payload) -> list[list[dict]]:
    def usable(rows) -> list[dict]:
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict) and row.get("candidate_id")]

    if isinstance(payload, list):
        return [usable(payload)]
    if not isinstance(payload, dict):
        return []
    return [usable(payload.get(key)) for key in CANDIDATE_SECTIONS]


def _sample_candidate_id(landscape_payload, campaign_payload) -> str | None:
    for payload in (landscape_payload, campaign_payload):
        for rows in _candidate_rows(payload):
            if not rows:
                continue
            best = max(rows, key=lambda row: (str(row.get("updated_utc") or ""),
                                              str(row.get("candidate_id"))))
            return str(best["candidate_id"])
    return None


def collect_evidence(fetch, root: Path, campaign_id: str, *, own_service: str = "reporter",
                     items: tuple[tuple[str, str, str], ...] = EVIDENCE_ITEMS) -> dict:
    root = Path(root)
    out_dir = root / EVIDENCE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    index: dict = {"contract": EVIDENCE_CONTRACT, "collected_utc": _utc_now(),
                   "campaign_id": str(campaign_id), "items": {}}
    payloads: dict[str, dict | None] = {}
    for name, template, kind in items:
        path = template.replace("{c}", str(campaign_id))
        started = time.monotonic()
        entry = {"source": path, "kind": kind}
        target = out_dir / (f"{name}.json" if kind == "json" else f"{name}.log")
        try:
            raw = fetch(path)
            if kind == "json":
                body = json.loads(raw.decode("utf-8"))
                if name == "runtime_imports" and isinstance(body, dict) and "services" in body:
                    body["services"].append(runtime_import_record(own_service))
                    for module in body["services"][-1]["modules"]:
                        body.setdefault("module_union", {}).setdefault(module, [])
                        if own_service not in body["module_union"][module]:
                            body["module_union"][module].append(own_service)
                    body["module_count"] = len(body.get("module_union") or {})
                payloads[name] = body
                data = json.dumps(body, indent=1, sort_keys=True, default=str).encode("utf-8")
            else:
                data = raw
            _atomic_write(target, data)
            entry.update({"file": str(target.relative_to(root)), "bytes": len(data),
                          "seconds": round(time.monotonic() - started, 3)})
            if isinstance(payloads.get(name), dict) and payloads[name].get("error"):
                entry["error"] = str(payloads[name]["error"])
                entry.pop("file", None)
                entry.pop("bytes", None)
                _discard(target)
        except Exception as exc:
            entry.update({"error": f"{type(exc).__name__}: {exc}"[:500],
                          "seconds": round(time.monotonic() - started, 3)})
            _discard(target)
        index["items"][name] = entry

    candidate_target = out_dir / "api_samples" / "candidate.json"
    candidate_id = _sample_candidate_id(payloads.get("api_samples/landscape"),
                                        payloads.get("api_samples/campaigns"))
    entry = {"source": None, "kind": "json"}
    if candidate_id:
        path = f"/api/campaign/{campaign_id}/candidate/{candidate_id}"
        entry["source"] = path
        try:
            raw = fetch(path)
            body = json.loads(raw.decode("utf-8"))
            data = json.dumps(body, indent=1, sort_keys=True, default=str).encode("utf-8")
            _atomic_write(candidate_target, data)
            entry.update({"file": str(candidate_target.relative_to(root)), "bytes": len(data),
                          "candidate_id": candidate_id})
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
            _discard(candidate_target)
    else:
        entry["error"] = "no candidate id in the landscape or campaigns payloads"
        _discard(candidate_target)
    index["items"]["api_samples/candidate"] = entry

    for name in ROOT_COPIES:
        source = root / name
        entry = {"source": name, "kind": "copy"}
        target = out_dir / name
        if source.is_file():
            try:
                shutil.copyfile(source, target)
                entry.update({"file": f"{EVIDENCE_DIR}/{name}", "bytes": source.stat().st_size})
            except OSError as exc:
                entry["error"] = str(exc)
                _discard(target)
        else:
            entry["error"] = "not present in the report root"
            _discard(target)
        index["items"][name] = entry

    index["ok"] = sorted(k for k, v in index["items"].items() if "error" not in v)
    index["failed"] = sorted(k for k, v in index["items"].items() if "error" in v)
    _atomic_write(out_dir / "index.json", json.dumps(index, indent=1, sort_keys=True).encode("utf-8"))
    return index


def evidence_files(root: Path) -> dict[str, Path]:
    out_dir = Path(root) / EVIDENCE_DIR
    if not out_dir.is_dir():
        return {}
    files: dict[str, Path] = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and not path.name.endswith(".tmp"):
            files[f"{EVIDENCE_DIR}/{path.relative_to(out_dir).as_posix()}"] = path
    return files
