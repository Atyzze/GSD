#!/usr/bin/env python3
from __future__ import annotations

import copy
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "report_snapshot.json.gz"
OPENERS = (
    (re.compile(r'_body\(\s*\w+,\s*"(\d{2})"\s*\)'), None),
    (re.compile(r'read_report\(\s*\w+,\s*"(\d{2})"\s*\)'), None),
    (re.compile(r'["/](\d{2})-[a-z*-]+\.json"'), None),
    (re.compile(r'REPORT_CODE\s*=\s*"(\d{2})"'), None),
)
KINDS = {"graph_scale_dynamics/reporting/study_reading.py": "the study bundle's reading",
         "graph_scale_dynamics/reporting/study_bundle.py": "the study bundle",
         "tools/read_bundle.py": "the bundle's first read",
         "tools/positive_control.py": "a check"}


class Seen(dict):
    def __init__(self, data, log: set, name: str):
        super().__init__(data)
        self._log, self._name = log, name

    def __getitem__(self, key):
        self._log.add((self._name, key))
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._log.add((self._name, key))
        return super().get(key, default)

    def __contains__(self, key):
        self._log.add((self._name, key))
        return super().__contains__(key)

    def __iter__(self):
        self._log.add((self._name, "*"))
        return super().__iter__()

    def keys(self):
        self._log.add((self._name, "*"))
        return super().keys()

    def items(self):
        self._log.add((self._name, "*"))
        return super().items()

    def values(self):
        self._log.add((self._name, "*"))
        return super().values()


class Paths(dict):
    def __init__(self, data, log: set, path: tuple):
        super().__init__(data)
        self._log, self._path = log, path

    def _at(self, key, value):
        return _paths(value, self._log, self._path + (key,))

    def __getitem__(self, key):
        self._log.add(self._path + (key,))
        return self._at(key, super().__getitem__(key))

    def get(self, key, default=None):
        self._log.add(self._path + (key,))
        return self._at(key, super().__getitem__(key)) if super().__contains__(key) else default

    def __contains__(self, key):
        self._log.add(self._path + (key,))
        return super().__contains__(key)

    def __iter__(self):
        self._log.add(self._path + ("*",))
        return super().__iter__()

    def keys(self):
        self._log.add(self._path + ("*",))
        return super().keys()

    def items(self):
        self._log.add(self._path + ("*",))
        return [(key, self._at(key, value)) for key, value in dict.items(self)]

    def values(self):
        self._log.add(self._path + ("*",))
        return [self._at(key, value) for key, value in dict.items(self)]


class PathList(list):
    def __init__(self, data, log: set, path: tuple):
        super().__init__(data)
        self._log, self._path = log, path

    def __getitem__(self, index):
        self._log.add(self._path + ("[]",))
        value = super().__getitem__(index)
        return [_paths(x, self._log, self._path + ("[]",)) for x in value] if isinstance(index, slice) \
            else _paths(value, self._log, self._path + ("[]",))

    def __iter__(self):
        self._log.add(self._path + ("[]",))
        return iter([_paths(x, self._log, self._path + ("[]",)) for x in list.__iter__(self)])

    def __reversed__(self):
        self._log.add(self._path + ("[]",))
        return iter([_paths(x, self._log, self._path + ("[]",)) for x in reversed(list(list.__iter__(self)))])


def _paths(value, log: set, path: tuple):
    if type(value) is dict:
        return Paths(value, log, path)
    if type(value) is list:
        return PathList(value, log, path)
    return value


def paths_read(part: str, column: str, value_of, codes=None, fixture: dict | None = None) -> dict[str, set]:
    from graph_scale_dynamics.research.report_pipeline import BUILDERS
    fixture = fixture or json.loads(gzip.decompress(FIXTURE.read_bytes()))
    out = {}
    for code in sorted(codes or BUILDERS):
        log: set = set()
        replication = copy.deepcopy(fixture)
        primary = replication["campaign_snapshots"][0]
        for row in primary.get(part) or []:
            row[column] = _paths(value_of(row), log, ())
        try:
            BUILDERS[code](dict(primary, replication_snapshot=replication))
        except Exception:  # noqa: BLE001
            pass
        out[code] = {path for path in log if path}
    return out


def reads(code: str, fixture: dict) -> dict:
    from graph_scale_dynamics.research.report_pipeline import BUILDERS
    log: set = set()
    replication = copy.deepcopy(fixture)
    primary_id = str(replication.get("primary_campaign_id") or replication.get("campaign_id"))
    campaigns = [Seen(c, log, "primary" if str(c.get("campaign_id")) == primary_id else "peer")
                 for c in replication.get("campaign_snapshots") or []]
    replication = Seen(dict(replication, campaign_snapshots=campaigns), log, "replication")
    primary = next((c for c in campaigns if c._name == "primary"), Seen({}, log, "primary"))
    snapshot = Seen(dict(dict.items(primary), replication_snapshot=replication), log, "primary")
    error = None
    try:
        BUILDERS[code](snapshot)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:200]
    held = {"primary": set(dict.keys(primary)), "replication": set(dict.keys(replication)),
            "peer": set().union(*(set(dict.keys(c)) for c in campaigns if c._name == "peer"))}
    parts: dict[str, list] = {}
    absent: dict[str, list] = {}
    for scope, key in sorted(log, key=lambda item: (item[0], str(item[1]))):
        if key == "campaign_snapshots" or (scope == "primary" and key == "replication_snapshot"):
            continue
        (parts if key == "*" or key in held.get(scope, ()) else absent).setdefault(scope, []).append(str(key))
    return {"parts": parts, "asked_for_but_absent": absent, "error": error}


def openers() -> dict[str, list[dict]]:
    found: dict[str, dict[str, str]] = {}
    files = sorted((ROOT / "graph_scale_dynamics").rglob("*.py")) + sorted((ROOT / "tools").glob("*.py"))
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if "__pycache__" in path.parts or rel in ("tools/report_audit.py",
                                                    "graph_scale_dynamics/research/report_pipeline.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern, _ in OPENERS:
            for match in pattern.finditer(text):
                code = match.group(1)
                found.setdefault(code, {})[rel] = KINDS.get(rel, "a tool" if rel.startswith("tools/") else "code")
    return {code: [{"file": f, "kind": k} for f, k in sorted(files.items())] for code, files in found.items()}


def costs(bundle: Path) -> dict[str, dict]:
    if not bundle.is_dir():
        sys.path.insert(0, str(ROOT / "tools"))
        from read_bundle import scratch_dir

        from graph_scale_dynamics.research.bundle_layout import extract
        bundle = extract(bundle, scratch_dir("gsd_audit_"))
    out: dict[str, dict] = {}
    for manifest in sorted(bundle.rglob("campaign_*_reports_*/manifest.json")):
        part = manifest.parent
        data = json.loads(manifest.read_text(encoding="utf-8"))
        campaign = str(data.get("campaign_id"))
        for code, seconds in ((data.get("cycle") or {}).get("report_seconds") or {}).items():
            entry = out.setdefault(code, {"seconds": {}, "bytes": {}})
            entry["seconds"][campaign] = seconds
            files = sorted(part.glob(f"{code}-*.json"))
            if files:
                entry["bytes"][campaign] = files[0].stat().st_size
    return out


def audit(bundle: Path | None = None) -> dict:
    from graph_scale_dynamics.research.report_catalog import REPORT_BY_CODE
    fixture = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    opened = openers()
    spent = costs(bundle) if bundle else {}
    reports = []
    for code, definition in sorted(REPORT_BY_CODE.items()):
        readers = list(opened.get(code) or [])
        cost = spent.get(code) or {}
        seconds = list((cost.get("seconds") or {}).values())
        sizes = list((cost.get("bytes") or {}).values())
        reports.append({
            "code": code, "title": definition.title,
            "reads": reads(code, fixture), "read_by": readers,
            "seconds": {"by_campaign": cost.get("seconds") or {}, "most": max(seconds) if seconds else None},
            "bytes": {"by_campaign": cost.get("bytes") or {}, "most": max(sizes) if sizes else None},
            "unread": not readers,
        })
    return {"contract": "gsd-report-audit-1", "bundle": bundle.name if bundle else None,
            "fixture": FIXTURE.relative_to(ROOT).as_posix(), "reports": reports,
            "unread": [r["code"] for r in reports if r["unread"]],
            "reading": ("a report is read when code opens it by number; every report is also listed in its manifest "
                        "and can be opened there, which is not counted")}


def render(result: dict) -> str:
    lines = [f"numbered reports ({len(result['reports'])}), read by, most seconds and bytes in a campaign"
             + (f" of {result['bundle']}" if result["bundle"] else "")]
    for r in result["reports"]:
        readers = ", ".join(sorted({x["kind"] + (f" ({Path(x['file']).name})" if x["kind"] == "a tool" else "")
                                    for x in r["read_by"]})) or "NOTHING (only the manifest's list)"
        parts = r["reads"]["parts"]
        primary = ", ".join(parts.get("primary", []))
        extra = f" + the peers' {', '.join(parts['peer'])}" if parts.get("peer") else ""
        seconds, size = r["seconds"]["most"], r["bytes"]["most"]
        lines.append(f"  {r['code']} {r['title'][:40]:<40} {seconds if seconds is not None else '-':>7} s "
                     f"{(size or 0) / 2**20:>7.1f} MiB  read by: {readers}")
        lines.append(f"       reads: {primary or '-'}{extra}" + (f"  (fails on the fixture: {r['reads']['error']})"
                                                               if r["reads"]["error"] else ""))
    lines.append("read by nothing but the manifest's list: " + (", ".join(result["unread"]) or "none"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    bundle = Path(args[args.index("--bundle") + 1]) if "--bundle" in args else None
    result = audit(bundle)
    if "--json" in args:
        Path(args[args.index("--json") + 1]).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
