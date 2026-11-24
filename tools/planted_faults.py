#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULTS = ROOT / "tests" / "fixtures" / "planted_faults.json"
FREEZE = ROOT / "tests" / "fixtures" / "science_freeze.json"
CONTRACT = "gsd-planted-faults-run-1"
TEST_DIRS = ("tests/unit", "tests/scientific")
ABOUT_THE_FAULTS = ("tests/unit/test_the_planted_faults_are_planted_where_they_say.py",)
HOST_STATE = ("calibration/probe_calibration.json",)
FAULT_SECONDS = 1800
NEUTRAL = "\nPLANTED_NEUTRAL_EDIT = None\n"
SHOWN = 10


def faults(path: Path = FAULTS) -> list[dict]:
    return list(json.loads(path.read_text(encoding="utf-8"))["faults"])


def module_of(file: str) -> str:
    return file[:-3].replace("/", ".") if file.endswith(".py") else file


def names_the_module(text: str, module: str) -> bool:
    package, _, name = module.rpartition(".")
    return (module in text or f"from {package} import {name}" in text
            or re.search(rf"from {re.escape(package)} import \([^)]*\b{re.escape(name)}\b", text) is not None
            or re.search(rf"from {re.escape(package)} import [^\n(]*\b{re.escape(name)}\b", text) is not None)


def readers_of(module: str, root: Path = ROOT) -> list[str]:
    package, _, name = module.rpartition(".")
    found = [module]
    for path in sorted((root / "graph_scale_dynamics").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        own = module_of(path.relative_to(root).as_posix())
        if own != module and (names_the_module(text, module)
                              or (own.rpartition(".")[0] == package
                                  and re.search(rf"from \.{re.escape(name)} import|from \. import [^\n]*\b"
                                                rf"{re.escape(name)}\b", text))):
            found.append(own)
    return found


def tests_for(fault: dict, root: Path = ROOT) -> list[str]:
    if fault.get("tests"):
        return list(fault["tests"])
    modules = readers_of(module_of(fault["file"]), root) if fault.get("through_its_readers") else [
        module_of(fault["file"])]
    found = []
    for directory in TEST_DIRS:
        for path in sorted((root / directory).glob("test_*.py")):
            if path.relative_to(root).as_posix() in ABOUT_THE_FAULTS:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(names_the_module(text, module) for module in modules):
                found.append(path.relative_to(root).as_posix())
    return found


def scratch_tree(root: Path, where: Path) -> Path:
    if where.exists():
        shutil.rmtree(where)
    if (root / ".git").exists():
        subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", "--force", str(where), "HEAD"],
                       check=True, capture_output=True)
        changed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--modified", "--others",
                                  "--exclude-standard"], capture_output=True, check=True).stdout
        for rel in (name for name in changed.decode("utf-8", "surrogateescape").split("\0") if name):
            if (root / rel).is_file():
                (where / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / rel, where / rel)
            elif (where / rel).exists():
                (where / rel).unlink()
    else:
        shutil.copytree(root, where, ignore=shutil.ignore_patterns("var", "instance", ".git", "__pycache__"))
    for rel in HOST_STATE:
        if (root / rel).is_file() and not (where / rel).exists():
            (where / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, where / rel)
    return where


def drop_scratch(root: Path, where: Path) -> None:
    if (root / ".git").exists():
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(where)], capture_output=True)
    shutil.rmtree(where, ignore_errors=True)


def failures(stdout: str) -> list[str]:
    found = []
    for line in stdout.splitlines():
        for head in ("FAILED ", "ERROR "):
            if line.startswith(head):
                found.append(line[len(head):].split(" - ")[0].strip())
    return found


def run_tests(tree: Path, tests: list[str], *, first: bool = True, deselect=(),
              timeout: int = FAULT_SECONDS) -> dict:
    env = dict(os.environ, PYTHONPATH=str(tree), PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    command = [sys.executable, "-m", "pytest", "-q", *(["-x"] if first else []), "-p", "no:cacheprovider",
               "--tb=line", "-rfE", *tests, *(f"--deselect={node}" for node in sorted(deselect))]
    try:
        done = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"code": None, "seconds": round(time.monotonic() - started, 1), "failed": "timed out",
                "failures": ["timed out"]}
    found = failures(done.stdout)
    failed = found[0] if found else None
    if failed is None and done.returncode not in (0, 5):
        failed = (done.stdout.strip().splitlines() or ["(no output)"])[-1]
    return {"code": done.returncode, "seconds": round(time.monotonic() - started, 1), "failed": failed,
            "failures": found}


def bytes_holders(tree: Path, file: str, tests: list[str]) -> list[str]:
    path = tree / file
    original = path.read_text(encoding="utf-8")
    path.write_text(original + NEUTRAL, encoding="utf-8")
    try:
        return sorted(set(run_tests(tree, tests, first=False)["failures"]))
    finally:
        path.write_text(original, encoding="utf-8")


def plant(tree: Path, fault: dict) -> str:
    path = tree / fault["file"]
    text = path.read_text(encoding="utf-8")
    if text.count(fault["find"]) != 1:
        raise ValueError(f"{fault['id']}: its site is not once in {fault['file']}")
    path.write_text(text.replace(fault["find"], fault["replace"]), encoding="utf-8")
    return text


def run(chosen: list[dict], *, root: Path = ROOT, where: Path | None = None, log=None) -> dict:
    log = log or (lambda line: print(line, flush=True))
    where = where or Path(tempfile.mkdtemp(prefix="gsd-planted-faults-")) / "tree"
    tree = scratch_tree(root, where)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                          text=True).stdout.strip() or None
    results, baselines, holders = [], {}, {}
    try:
        for fault in chosen:
            tests = tests_for(fault, tree)
            key = tuple(tests)
            row = {"id": fault["id"], "numbers": fault["numbers"], "tests": len(tests)}
            if not tests:
                results.append(dict(row, outcome="no test reads it"))
                log(f"{fault['id']}: no test reads {fault['file']}")
                continue
            if key not in baselines:
                baselines[key] = run_tests(tree, tests, first=False)
            base = baselines[key]
            if base["code"] != 0:
                results.append(dict(row, outcome="its tests fail unplanted", failed=base["failed"]))
                log(f"{fault['id']}: its {len(tests)} test files fail without the fault ({base['failed']})")
                continue
            if (fault["file"], key) not in holders:
                holders[(fault["file"], key)] = bytes_holders(tree, fault["file"], tests)
            aside = holders[(fault["file"], key)]
            original = plant(tree, fault)
            try:
                found = run_tests(tree, tests, deselect=aside)
            finally:
                (tree / fault["file"]).write_text(original, encoding="utf-8")
            outcome = "caught" if found["code"] not in (0, 5) else "let by"
            results.append(dict(row, outcome=outcome, failed=found["failed"], seconds=found["seconds"],
                                set_aside=len(aside), set_aside_shown=aside[:SHOWN]))
            log(f"{fault['id']}: {outcome} ({len(tests)} test files, {len(aside)} tests set aside that fail on any "
                f"edit, {found['seconds']} s" + (f", {found['failed']}" if found["failed"] else "") + ")")
    finally:
        drop_scratch(root, where)
    counts = {}
    for row in results:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    return {"contract": CONTRACT, "commit": head, "faults": results, "counts": counts}


def render(found: dict) -> str:
    lines = [f"planted faults ({found['contract']}) on {found.get('commit')}: "
             + ", ".join(f"{k} {v}" for k, v in sorted(found["counts"].items())),
             "", "| fault | the numbers | outcome | the test that failed |", "|---|---|---|---|"]
    for row in found["faults"]:
        lines.append(f"| {row['id']} | {', '.join(row['numbers'])} | {row['outcome']} | {row.get('failed') or ''} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/planted_faults.py: see docs/TOOLS.md")
    parser.add_argument("ids", nargs="*", help="the faults to plant; every one when none is named")
    parser.add_argument("--list", action="store_true", help="name each fault and the tests that read its module")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    every = faults()
    chosen = [f for f in every if not args.ids or f["id"] in args.ids]
    unknown = sorted(set(args.ids) - {f["id"] for f in every})
    if unknown:
        print(f"no such fault: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if args.list:
        for fault in chosen:
            print(f"{fault['id']}: {fault['file']} ({', '.join(fault['numbers'])}): {len(tests_for(fault))} test files")
        return 0
    found = run(chosen)
    if args.json:
        args.json.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    if args.md:
        args.md.write_text(render(found) + "\n", encoding="utf-8")
    print(render(found))
    return 0 if all(row["outcome"] == "caught" for row in found["faults"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
