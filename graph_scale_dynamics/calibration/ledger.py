from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

LEDGER_CONTRACT = "gsd-calibration-ledger-1"
LEDGER_DIR = "calibration/ledger"
MEASURE = "measure"
ATTEST = "attest"
KINDS = (MEASURE, ATTEST)
EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


class LedgerError(ValueError):
    pass


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def record_hash(record: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != "hash"})).hexdigest()


def genesis(group: str, fingerprint: str) -> str:
    return hashlib.sha256(canonical({"contract": LEDGER_CONTRACT, "group": group,
                                     "fingerprint": fingerprint})).hexdigest()


def ledger_dir(root) -> Path:
    return Path(root) / LEDGER_DIR


def ledger_path(root, group: str, fingerprint: str) -> Path:
    return ledger_dir(root) / group / f"{fingerprint}.jsonl"


def ledger_files(root) -> list[Path]:
    base = ledger_dir(root)
    return sorted(base.glob("*/*.jsonl")) if base.is_dir() else []


def read(path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check(group: str, fingerprint: str, records: list[dict], name: str) -> list[str]:
    out = []
    previous = genesis(group, fingerprint)
    measured: set[str] = set()
    known: set[str] = set()
    for number, record in enumerate(records, start=1):
        where = f"{name}:{number}"
        if record.get("group") != group or record.get("group_fingerprint") != fingerprint:
            out.append(f"{where}: filed under another group or fingerprint")
        if record.get("prev") != previous:
            out.append(f"{where}: does not follow the line before it")
        if record.get("hash") != record_hash(record):
            out.append(f"{where}: its hash is not its content's")
        kind = record.get("kind")
        if kind not in KINDS:
            out.append(f"{where}: kind {kind!r} is none of {', '.join(KINDS)}")
        elif kind == MEASURE:
            if record.get("cell") in measured:
                out.append(f"{where}: cell {record.get('cell')} measured twice under one fingerprint")
            measured.add(str(record.get("cell")))
        elif record.get("of") not in known:
            out.append(f"{where}: attests a record that is not before it")
        known.add(str(record.get("hash")))
        previous = record.get("hash")
    return out


def problems(path) -> list[str]:
    path = Path(path)
    return _check(path.parent.name, path.stem, read(path), f"{path.parent.name}/{path.name}")


def append(path, records: list[dict]) -> list[dict]:
    path = Path(path)
    group, fingerprint = path.parent.name, path.stem
    existing = read(path)
    found = _check(group, fingerprint, existing, path.name)
    if found:
        raise LedgerError("the ledger does not verify before the append: " + "; ".join(found[:3]))
    previous = existing[-1]["hash"] if existing else genesis(group, fingerprint)
    measured = {str(r.get("cell")) for r in existing if r.get("kind") == MEASURE}
    known = {str(r.get("hash")) for r in existing}
    written = []
    for record in records:
        entry = {k: v for k, v in record.items() if k != "hash"}
        entry.update(group=group, group_fingerprint=fingerprint, prev=previous)
        if entry.get("kind") == MEASURE:
            if str(entry.get("cell")) in measured:
                raise LedgerError(f"cell {entry.get('cell')} is already measured under {group}/{fingerprint}: "
                                  "a second reading of it is an attestation")
            measured.add(str(entry.get("cell")))
        elif entry.get("kind") == ATTEST:
            if str(entry.get("of")) not in known:
                raise LedgerError(f"an attestation of {entry.get('of')}, which this ledger does not hold")
        else:
            raise LedgerError(f"kind {entry.get('kind')!r} is none of {', '.join(KINDS)}")
        entry["hash"] = record_hash(entry)
        written.append(entry)
        known.add(entry["hash"])
        previous = entry["hash"]
    if not written:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for entry in written:
            handle.write(canonical(entry).decode("utf-8") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return written


def measured(root, group: str, fingerprint: str) -> dict[str, dict]:
    return {str(r["cell"]): r for r in read(ledger_path(root, group, fingerprint)) if r.get("kind") == MEASURE}


def attestations(root, group: str, fingerprint: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for record in read(ledger_path(root, group, fingerprint)):
        if record.get("kind") == ATTEST:
            out.setdefault(str(record["of"]), []).append(record)
    return out


def merkle_root(hashes) -> str:
    level = [bytes.fromhex(h) for h in sorted(set(hashes))]
    if not level:
        return EMPTY_ROOT
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0].hex()


def snapshot(root, fingerprints: dict[str, str], cells=None) -> dict:
    wanted = None if cells is None else {str(c) for c in cells}
    hashes = []
    per_group = {}
    for group, fingerprint in sorted(fingerprints.items()):
        records = [r for key, r in measured(root, group, fingerprint).items() if wanted is None or key in wanted]
        per_group[group] = {"fingerprint": fingerprint, "records": len(records),
                            "root": merkle_root(r["hash"] for r in records)}
        hashes += [r["hash"] for r in records]
    return {"contract": LEDGER_CONTRACT, "groups": per_group, "records": len(hashes), "root": merkle_root(hashes)}
