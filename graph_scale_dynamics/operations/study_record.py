from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

RECORD_CONTRACT = "gsd-study-record-1"
RECORD_NAME = "study.json"
DESIGNED, GROWTH, DEFAULT, NAMED_SPEC = "designed", "growth", "default", "spec"
KINDS = (DESIGNED, GROWTH, DEFAULT, NAMED_SPEC)
BY_FLAG, BY_DEFAULT, BY_SPEC, BY_CAMPAIGNS = "--study", "no --study", "--spec", "the campaigns' specs"
COMPLETE = "complete_utc"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def path(var) -> Path:
    return Path(var) / RECORD_NAME


def valid_id(study: str) -> bool:
    return bool(_SAFE_ID.match(str(study or "")))


def read(var) -> dict | None:
    if var is None:
        return None
    try:
        document = json.loads(path(var).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or document.get("contract") != RECORD_CONTRACT or not document.get("study"):
        return None
    return document


def write(var, *, study: str, kind: str, chosen_by: str, source: dict | None = None, now: str | None = None,
          search_seed: int | None = None, spec_sha256: str | None = None, log=print) -> dict | None:
    if var is None:
        return None
    existing = read(var)
    if existing is not None:
        return existing
    if kind not in KINDS:
        raise ValueError(f"unknown kind of study {kind!r}")
    if not valid_id(study):
        raise ValueError(f"{study!r} is not a study id (letters, digits, '.', '_', '-')")
    from graph_scale_dynamics.domain.version import BUILD_NUMBER
    document = {"contract": RECORD_CONTRACT, "study": str(study), "kind": kind, "chosen_by": chosen_by,
                "source": source or {}, "written_utc": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "build_number": BUILD_NUMBER, COMPLETE: None,
                "search_seed": None if search_seed is None else int(search_seed), "spec_sha256": spec_sha256,
                "reading": ("Which study this folder is, chosen at its first start and never from the folder's name. "
                            "The bundle's name and the register's note read it; "
                            "nothing a campaign runs does.")}
    target = path(var)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, target)
    log(f"study: this folder is study {study} ({kind}, chosen by {chosen_by}); recorded in {target}")
    return document


def of_campaigns(specs) -> str | None:
    named = set()
    for spec in specs:
        spec = spec or {}
        for key in ("study_design",):
            study = (spec.get(key) or {}).get("study")
            if study not in (None, ""):
                named.add(str(study))
    if len(named) > 1:
        raise ValueError(f"this folder's campaigns name more than one study: {sorted(named)}")
    return next(iter(named), None)


def _specs(repo) -> list[dict]:
    listed = getattr(repo, "all_campaigns", None)
    return [] if listed is None else [c.get("spec") or {} for c in listed()]


def study_id(var, repo=None) -> str:
    record = read(var)
    if record is not None:
        return str(record["study"])
    return of_campaigns(_specs(repo)) or DEFAULT


def ensure(var, repo, *, log=print) -> dict | None:
    if var is None or read(var) is not None:
        return read(var)
    specs = _specs(repo)
    if not specs:
        return None
    named = of_campaigns(specs)
    kind = DEFAULT if named is None else DESIGNED
    return write(var, study=named or DEFAULT, kind=kind, chosen_by=BY_CAMPAIGNS,
                 source={"campaigns": len(specs)}, log=log)


def _set(var, key: str, value: str) -> dict | None:
    record = read(var)
    if record is None or record.get(key):
        return record
    record = dict(record, **{key: value})
    target = path(var)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, target)
    return record


def add_note(var, line: str, *, log=print) -> dict | None:
    had = (read(var) or {}).get("note")
    record = _set(var, "note", str(line).strip())
    if record is not None and not had:
        log(f"note: {record['note']}")
    return record


def finish(var, kind: str | None = None) -> dict | None:
    record = read(var)
    if kind is not None and record is not None and record.get("kind") != kind:
        return record
    return _set(var, COMPLETE, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def forget_unmade(var) -> bool:
    record = read(var)
    if record is None or record.get("kind") != NAMED_SPEC or complete(record):
        return False
    path(var).unlink(missing_ok=True)
    return True


def complete(record: dict | None) -> bool:
    return record is None or record.get(COMPLETE, True) is not None or record.get("chosen_by") == BY_CAMPAIGNS


def note(var) -> str | None:
    return (read(var) or {}).get("note")


def reset_phrase(var) -> str:
    record = read(var)
    return f"reset study {record['study']}" if record is not None else "reset this folder"
