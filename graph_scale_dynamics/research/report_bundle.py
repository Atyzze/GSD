from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
from graph_scale_dynamics.operations.report_cycle import COMPLETE, normalize_state
from graph_scale_dynamics.research.report_catalog import REPORTS, REPORT_BY_CODE
from graph_scale_dynamics.reporting.evidence import evidence_files

BUNDLE_ZSTD_LEVEL = 10

BUNDLE_CONTRACT = "gsd-report-bundle-4-numbered-zstd-evidence"

REPORT_CODES = tuple(definition.code for definition in REPORTS)


class BundleIncoherent(RuntimeError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_bundle_coherence(manifest: Mapping, bodies: Mapping[str, Mapping],
                            *, required_codes: tuple[str, ...] = REPORT_CODES) -> dict:
    state = normalize_state(manifest.get("cycle_state") or manifest.get("generation_status"))
    if state != COMPLETE:
        raise BundleIncoherent(
            f"bundle export requires a COMPLETE cycle; current state is {state or 'unknown'}"
        )
    revision = manifest.get("bundle_revision") or manifest.get("source_revision")
    cycle_id = manifest.get("bundle_cycle_id") or manifest.get("cycle_id")
    if not revision:
        raise BundleIncoherent("manifest carries no bundle revision")
    if not cycle_id:
        raise BundleIncoherent("manifest carries no report cycle id")

    missing = [code for code in required_codes if code not in bodies]
    if missing:
        numbers = [str(REPORT_BY_CODE[code].number) for code in missing if code in REPORT_BY_CODE]
        detail = ",".join(numbers or missing)
        raise BundleIncoherent(f"bundle is missing report bodies: {detail}")

    mismatched: dict[str, str] = {}
    for code in required_codes:
        body = bodies[code] or {}
        body_revision = str(body.get("bundle_revision") or "")
        body_cycle = str(body.get("report_cycle_id") or body.get("bundle_cycle_id") or "")
        definition = REPORT_BY_CODE.get(code)
        label = str(definition.number) if definition is not None else code
        if body_revision != str(revision) or body_cycle != str(cycle_id):
            mismatched[label] = (
                f"bundle_revision={body_revision or 'missing'},"
                f" report_cycle_id={body_cycle or 'missing'}"
            )
    if mismatched:
        detail = "; ".join(f"report {label}: {value}" for label, value in sorted(mismatched.items()))
        raise BundleIncoherent(
            f"reports come from more than one cycle (bundle revision {revision}; cycle {cycle_id}; {detail})"
        )
    return {
        "coherent": True,
        "bundle_revision": str(revision),
        "cycle_id": str(cycle_id),
        "report_numbers": [REPORT_BY_CODE[code].number for code in required_codes],
    }


def _public_manifest(manifest: Mapping) -> dict:
    internal_reports = manifest.get("reports") or {}
    reports = []
    for definition in REPORTS:
        row = internal_reports.get(definition.code) or {}
        reports.append({
            "number": definition.number,
            "slug": definition.slug,
            "title": definition.title,
            "question": definition.question,
            "status": row.get("status"),
            "seconds": row.get("seconds"),
            "revision": row.get("revision"),
        })
    return {
        "contract": "gsd-report-manifest-public-1",
        "build_number": BUILD_NUMBER,
        "build_hash": runtime_fingerprint(),
        "runtime_fingerprint": runtime_fingerprint(),
        "campaign_id": manifest.get("campaign_id"),
        "cycle_state": manifest.get("cycle_state"),
        "generation_status": manifest.get("generation_status"),
        "bundle_revision": manifest.get("bundle_revision") or manifest.get("source_revision"),
        "cycle_id": manifest.get("bundle_cycle_id") or manifest.get("cycle_id"),
        "source_revision": manifest.get("source_revision"),
        "replication_source_revision": manifest.get("replication_source_revision"),
        "generation_started_utc": manifest.get("generation_started_utc"),
        "generation_finished_utc": manifest.get("generation_finished_utc"),
        "cycle_seconds": manifest.get("cycle_seconds"),
        "cycle": dict(manifest.get("cycle") or {}),
        "resolved_error_count": len(manifest.get("resolved_errors") or []),
        "resolved_errors": list(manifest.get("resolved_errors") or []),
        "reports": reports,
        "next_report_number": len(REPORTS) + 1,
    }


def build_bundle_manifest(manifest: Mapping, bodies: Mapping[str, Mapping],
                          checksums: Mapping[str, str]) -> dict:
    coherence = verify_bundle_coherence(manifest, bodies)
    revisions = manifest.get("report_revisions") or {}
    return {
        "contract": BUNDLE_CONTRACT,
        "build_number": BUILD_NUMBER,
        "build_hash": runtime_fingerprint(),
        "runtime_fingerprint": runtime_fingerprint(),
        "campaign_id": manifest.get("campaign_id"),
        "bundle_revision": coherence["bundle_revision"],
        "cycle_id": coherence["cycle_id"],
        "source_revision": manifest.get("source_revision"),
        "replication_source_revision": manifest.get("replication_source_revision"),
        "reports": [
            {
                "number": definition.number,
                "slug": definition.slug,
                "title": definition.title,
                "question": definition.question,
                "revision": revisions.get(definition.code),
            }
            for definition in REPORTS
        ],
        "cycle_diagnostics": dict(manifest.get("cycle") or {}),
        "cycle_seconds": manifest.get("cycle_seconds"),
        "generation_finished_utc": manifest.get("generation_finished_utc"),
        "resolved_error_count": len(manifest.get("resolved_errors") or []),
        "resolved_errors": list(manifest.get("resolved_errors") or []),
        "report_numbers": coherence["report_numbers"],
        "checksums": dict(checksums),
        "compression": {"format": "zstd", "level": BUNDLE_ZSTD_LEVEL, "container": "tar"},
        "exported_utc": (manifest.get("generation_finished_utc") or
                         (manifest.get("cycle") or {}).get("finished_utc")),
    }

def load_report_bodies(report_root: Path,
                       codes: tuple[str, ...] = REPORT_CODES) -> dict[str, dict]:
    bodies: dict[str, dict] = {}
    for code in codes:
        path = Path(report_root) / "reports" / f"{code}.json"
        if not path.is_file():
            continue
        try:
            bodies[code] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            definition = REPORT_BY_CODE.get(code)
            label = definition.number if definition is not None else code
            raise BundleIncoherent(f"report {label} could not be read: {exc}") from exc
    return bodies


def check_coherence(report_root: Path, manifest: Mapping) -> dict:
    checked: dict = {}
    for code in REPORT_CODES:
        body = load_report_bodies(Path(report_root), (code,))
        checked = verify_bundle_coherence(manifest, body, required_codes=(code,))
        del body
    if not checked:
        raise BundleIncoherent("no report code to check")
    return {**checked, "report_numbers": [REPORT_BY_CODE[code].number for code in REPORT_CODES]}


def _public_filename(code: str) -> str:
    definition = REPORT_BY_CODE[code]
    return f"{definition.number:02d}-{definition.slug}.json"


def bundle_files(report_root: Path, manifest: Mapping) -> tuple[dict[str, bytes], str]:
    report_root = Path(report_root)
    bodies = load_report_bodies(report_root)
    coherence = verify_bundle_coherence(manifest, bodies)
    revision = coherence["bundle_revision"]

    serialized: dict[str, bytes] = {}
    for code in REPORT_CODES:
        serialized[_public_filename(code)] = json.dumps(
            bodies[code], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    serialized["manifest.json"] = json.dumps(
        _public_manifest(manifest), sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    ).encode("utf-8")

    for name, path in evidence_files(report_root).items():
        try:
            serialized[name] = path.read_bytes()
        except OSError:
            continue

    checksums = {name: _sha256(payload) for name, payload in sorted(serialized.items())}
    bundle_manifest = build_bundle_manifest(manifest, bodies, checksums)
    serialized["bundle.json"] = json.dumps(
        bundle_manifest, indent=2, sort_keys=True, allow_nan=False, default=str
    ).encode("utf-8")

    return serialized, bundle_stem(manifest, revision)


def bundle_stem(manifest: Mapping, revision: str) -> str:
    campaign = str(manifest.get("campaign_id") or "campaign")
    stamp = str(manifest.get("generation_finished_utc") or
                (manifest.get("cycle") or {}).get("finished_utc") or "")
    stamp = stamp.replace(":", "-").replace(".", "-") if stamp else "unknown-time"
    return f"campaign_{campaign}_reports_{stamp}_{str(revision)[:8]}"
