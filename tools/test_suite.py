#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_scale_dynamics.operations.process_ownership import (  # noqa: E402
    STOP_SIGNALS, die_with_owner, interrupt_on, owned_env, stop_process_group,
)

LANES = {
    "all": [],
    "hermetic": ["tests/unit", "tests/contract", "tests/scientific"],
    "postgres": ["tests/integration"],
    "scientific": ["tests/scientific", "tests/contract/test_science_freeze.py"],
    "release": ["tests/unit/test_dashboard_smoke.py",
                "tests/unit/test_candidate_smoke.py",
                "tests/unit/test_layout_check.py",
                "tests/unit/test_the_study_explorer_in_a_browser.py"],
}

ALLOWED_SKIPS: dict[str, str] = {}

POSTGRES_UNAVAILABLE = "folder-local PostgreSQL is unavailable in this test environment"
RECALIBRATION_OWED = "recalibration owed since build "
COLLECTION_SKIPPED = "collection skipped"

SKIPS_REFUSED = 6


def _node_id(case: ET.Element) -> str:
    classname, name = case.get("classname") or "", case.get("name") or ""
    if not classname:
        classname, name = name, ""
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        path = "/".join(parts[:cut]) + ".py"
        if (ROOT / path).is_file():
            return "::".join([path, *parts[cut:], *([name] if name else [])])
    return "::".join([classname.replace(".", "/"), *([name] if name else [])])


def recalibration_is_owed() -> bool:
    from graph_scale_dynamics.calibration import owed
    return owed.recalibration_owed() is not None


def undeclared_skips(junit: Path, *, allowed: dict[str, str] | None = None,
                     postgres_may_skip: bool = False, owed: bool | None = None) -> list[tuple[str, str]]:
    allowed = ALLOWED_SKIPS if allowed is None else allowed
    owed = recalibration_is_owed() if owed is None else owed
    out = []
    for case in ET.parse(junit).getroot().iter("testcase"):
        for skipped in case.findall("skipped"):
            if skipped.get("type") == "pytest.xfail":
                continue
            node = _node_id(case)
            reason = skipped.get("message") or (skipped.text or "").strip()
            if node in allowed or re.sub(r"\[.*\]$", "", node) in allowed or node.split("::")[0] in allowed:
                continue
            if postgres_may_skip and POSTGRES_UNAVAILABLE in reason:
                continue
            if owed and (reason.startswith(RECALIBRATION_OWED)
                         or (reason == COLLECTION_SKIPPED and RECALIBRATION_OWED in (skipped.text or ""))):
                continue
            out.append((node, reason))
    return out


FAST_ALWAYS = (
    "tests/unit/test_next_build_is_named.py", "tests/unit/test_where_we_are_is_current.py",
    "tests/unit/test_build_cadence.py", "tests/unit/test_build_identity.py", "tests/unit/test_claim_ledger.py",
    "tests/contract/test_science_freeze.py", "tests/unit/test_size_ratchet.py",
    "tests/unit/test_tree_is_pyflakes_clean.py", "tests/unit/test_repository_hygiene.py",
    "tests/unit/test_the_read_first_set_is_small.py", "tests/unit/test_a_skip_nobody_declared_fails_the_gate.py",
)
FAST_REFUSED = ("graph_scale_dynamics/resources/schema/", "engine_rs/")
WARM_UP = "tests/integration/test_the_lanes_hold_memory_postgres.py::test_a_paused_campaign_holds_no_room"
WARM_UP_TRIES = 2
HERMETIC_DIRS = ("tests/unit", "tests/contract", "tests/scientific")
DURATIONS = ROOT / "var" / "test_durations.json"


BUILD_FILES = ROOT / "tests" / "fixtures" / "build_files.json"
BUILD_FILES_CONTRACT = "gsd-build-files-1"


def release_files(root: Path = ROOT) -> dict[str, str]:
    import hashlib
    from tools import package_release as PR
    root = Path(root)
    paths = [root / name for name in PR.ROOT_FILES if (root / name).is_file()]
    for directory in sorted(PR.ROOT_DIRS):
        if (root / directory).is_dir():
            paths.extend(path for path in (root / directory).rglob("*") if path.is_file())
    record = BUILD_FILES.relative_to(ROOT).as_posix()
    out = {}
    for path in paths:
        rel = path.relative_to(root)
        if rel.as_posix() == record or not PR.included(rel):
            continue
        out[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(out.items()))


def build_files_text(number: int, root: Path = ROOT) -> str:
    return json.dumps({"contract": BUILD_FILES_CONTRACT, "build": int(number), "files": release_files(root)},
                      indent=0) + "\n"


def write_build_files(number: int, root: Path = ROOT, text: str | None = None) -> Path:
    target = Path(root) / BUILD_FILES.relative_to(ROOT)
    target.write_text(build_files_text(number, root) if text is None else text, encoding="utf-8")
    return target


def recorded_build(root: Path = ROOT) -> int | None:
    try:
        record = json.loads((Path(root) / BUILD_FILES.relative_to(ROOT)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return int(record["build"]) if record.get("contract") == BUILD_FILES_CONTRACT else None


def changed_since_the_build(root: Path = ROOT) -> list[str]:
    try:
        record = json.loads((Path(root) / BUILD_FILES.relative_to(ROOT)).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"no record of the build's files ({BUILD_FILES.relative_to(ROOT)}): {exc}") from exc
    then, now = record.get("files") or {}, release_files(root)
    return sorted(path for path in set(then) | set(now) if then.get(path) != now.get(path))


def changed_files(since: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", since], cwd=ROOT, capture_output=True, text=True, check=True)
    new = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                         text=True, check=True)
    return sorted({line.strip() for line in (out.stdout + new.stdout).splitlines() if line.strip()})


def fast_refusal(changed: list[str]) -> str | None:
    from graph_scale_dynamics.domain.science_identity import frozen_paths
    frozen = set(frozen_paths())
    for path in changed:
        if path in frozen or any(path == r or path.startswith(r) for r in FAST_REFUSED):
            return f"{path} moves what the science reads or what the database holds: the full lane"
    return None


def fast_selection(changed: list[str]) -> list[str]:
    tests = sorted(str(p.relative_to(ROOT)) for d in (*HERMETIC_DIRS, "tests/integration")
                   for p in (ROOT / d).glob("test_*.py"))
    texts = {t: (ROOT / t).read_text(encoding="utf-8", errors="replace") for t in tests}
    chosen = (set(FAST_ALWAYS) & set(tests)) | {t for t in tests if t.startswith("tests/contract/")}
    for path in changed:
        if path in texts:
            chosen.add(path)
            continue
        if path.endswith((".js", ".html", ".css")):
            chosen.update(t for t in tests if "smoke" in t or "browser" in t or "layout_check" in t or
                          Path(path).name in texts[t])
            continue
        if not path.endswith(".py"):
            chosen.update(t for t in tests if path in texts[t] or Path(path).name in texts[t])
            continue
        reached = importers(path)
        chosen.update(t for t in tests if reached & (imports_of(t) | launched_by(t)))
        if path.startswith("tests/"):
            chosen.update(helper_users(reached, tests, texts))
        dotted = path[:-3].replace("/", ".")
        package, _, name = dotted.rpartition(".")
        marks = [dotted, path, f"from {package} import {name}" if package else f"import {name}"]
        if path.startswith("tools/"):
            marks += [f"import {name}", f"from {name} import", f"tools/{name}.py", f"tools import {name}"]
        if path == "main.py":
            marks += ["import main", "main.py"]
        chosen.update(t for t in tests if any(m in texts[t] for m in marks)
                      or (package and f"from {package} import (" in texts[t] and f" {name}," in texts[t]))
    return sorted(chosen)


@functools.lru_cache(maxsize=1)
def _module_files() -> dict[str, str]:
    out = {"main": "main.py"}
    for path in sorted((ROOT / "graph_scale_dynamics").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "__pycache__" in rel:
            continue
        dotted = rel[:-3].replace("/", ".")
        out[dotted[:-len(".__init__")] if dotted.endswith(".__init__") else dotted] = rel
    for path in sorted((ROOT / "tools").glob("*.py")):
        out.setdefault(path.stem, path.relative_to(ROOT).as_posix())
        out.setdefault(f"tools.{path.stem}", path.relative_to(ROOT).as_posix())
    for path in sorted((ROOT / "tests").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "__pycache__" in rel or path.name.startswith("test_"):
            continue
        dotted = rel[:-3].replace("/", ".")
        out[dotted[:-len(".__init__")] if dotted.endswith(".__init__") else dotted] = rel
    return out


def _tree(rel: str):
    import ast
    try:
        return ast.parse((ROOT / rel).read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return None


_IMPORTS: dict[str, frozenset] = {}


def imports_of(rel: str) -> frozenset:
    if rel in _IMPORTS:
        return _IMPORTS[rel]
    import ast
    modules = _module_files()
    tree = _tree(rel)
    if tree is None:
        _IMPORTS[rel] = frozenset()
        return _IMPORTS[rel]
    base = rel[:-3].replace("/", ".").rpartition(".")[0]
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = base.split(".")
                module = ".".join(parts[:len(parts) - node.level + 1] + ([module] if module else []))
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "pytest_plugins" for t in node.targets):
            names = [n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for name in names:
            if name in modules:
                found.add(modules[name])
    _IMPORTS[rel] = frozenset(found)
    return _IMPORTS[rel]


_LAUNCHED: dict[str, frozenset] = {}


def _is_executable(node) -> bool:
    return getattr(node, "attr", None) == "executable" and getattr(getattr(node, "value", None), "id", None) == "sys"


def launched_by(rel: str) -> frozenset:
    if rel in _LAUNCHED:
        return _LAUNCHED[rel]
    import ast
    modules, tree = _module_files(), _tree(rel)
    nodes = list(ast.walk(tree)) if tree is not None else []
    files, found, by_name = set(modules.values()), set(), False
    for node in nodes:
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        items = node.elts
        for flag, target in zip(items, items[1:], strict=False):
            if isinstance(flag, ast.Constant) and flag.value == "-m":
                if isinstance(target, ast.Constant):
                    found.update(modules[v] for v in [target.value] if v in modules)
                else:
                    by_name = by_name or getattr(target, "id", None) != "__name__"
        if len(items) > 1 and _is_executable(items[0]):
            found.update(n.value for n in ast.walk(items[1]) if isinstance(n, ast.Constant) and n.value in files)
    if by_name:
        found.update(modules[n.value] for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and "." in n.value and n.value in modules)
    _LAUNCHED[rel] = frozenset(found - {rel})
    return _LAUNCHED[rel]


CONFTEST = "tests/conftest.py"


def fixtures_of(rel: str) -> set[str]:
    import ast
    tree = _tree(rel)

    def fixture(decorator) -> bool:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        return getattr(target, "attr", getattr(target, "id", None)) == "fixture"
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            and any(fixture(d) for d in n.decorator_list)} if tree is not None else set()


def helper_users(reached: set[str], tests: list[str], texts: dict[str, str]) -> set[str]:
    helpers = {f for f in reached if f.startswith("tests/")}
    names = set().union(*(fixtures_of(f) for f in helpers)) if helpers else set()
    used = {t for t in tests if any(re.search(rf"\b{re.escape(name)}\b", texts[t]) for name in names)}
    return used | ({t for t in tests if t.startswith("tests/integration/")} if CONFTEST in helpers else set())


@functools.lru_cache(maxsize=1)
def _reverse_imports() -> dict[str, frozenset]:
    reverse: dict[str, set] = {}
    for f in sorted(set(_module_files().values())):
        for dep in imports_of(f) | launched_by(f):
            reverse.setdefault(dep, set()).add(f)
    return {k: frozenset(v) for k, v in reverse.items()}


def importers(rel: str) -> set[str]:
    reverse = _reverse_imports()
    seen, todo = {rel}, [rel]
    while todo:
        for parent in reverse.get(todo.pop(), ()):
            if parent not in seen:
                seen.add(parent)
                todo.append(parent)
    return seen


FOLDER_PROCESS_MARKS = ('which("btop")', "_btop_telemetry_snapshot", "ensure_publisher(", "ensure_holder(",
                        "enter_scratch(", "scratch_namespace import enter")


def with_the_folder_s_processes(files: list[str]) -> list[str]:
    return [f for f in files if any(mark in (ROOT / f).read_text(encoding="utf-8", errors="replace")
                                    for mark in FOLDER_PROCESS_MARKS)]


def plan_shards(paths: list[str], shards: int, durations: dict | None = None) -> list[list[str]]:
    files = sorted({str(p.relative_to(ROOT)) for d in paths for p in (ROOT / d).glob("test_*.py")})
    files = sorted(set(files) - set(with_the_folder_s_processes(files)))
    known = durations or {}
    weight = {f: float(known.get(f) or (ROOT / f).stat().st_size / 2000.0) for f in files}
    groups: list[list[str]] = [[] for _ in range(max(1, shards))]
    loads = [0.0] * len(groups)
    for f in sorted(files, key=lambda x: -weight[x]):
        i = loads.index(min(loads))
        groups[i].append(f)
        loads[i] += weight[f]
    return [sorted(g) for g in groups if g]


def _junit_counts(junit: Path) -> dict:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "seconds_by_file": {}}
    if not junit.is_file():
        return counts
    root = ET.parse(junit).getroot()
    for suite in ([root] if root.tag == "testsuite" else root.iter("testsuite")):
        for key in ("tests", "failures", "errors", "skipped"):
            counts[key] += int(suite.get(key) or 0)
    for case in root.iter("testcase"):
        node = _node_id(case).split("::")[0]
        counts["seconds_by_file"][node] = counts["seconds_by_file"].get(node, 0.0) + float(case.get("time") or 0.0)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tools/test_suite.py: see docs/TOOLS.md")
    parser.add_argument("--lane", choices=sorted(LANES) + ["fast"], default="all")
    parser.add_argument("--require-postgres", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--marker", default=None, help="a pytest -m expression (selftest's --quick)")
    parser.add_argument("--allow-skips", action="store_true",
                        help="report skips ALLOWED_SKIPS does not declare without failing (development only)")
    parser.add_argument("--shards", default="1",
                        help="the full lane in this many processes at once (670): the PostgreSQL lane in one, the "
                             "rest split by time; 'auto' is the CPUs this process may use")
    parser.add_argument("--changed-since", default=None,
                        help="the fast lane (670) against this git revision instead of the build's record of its "
                             "files (706, tests/fixtures/build_files.json)")
    args = parser.parse_args(argv)

    env = dict(os.environ, GSD_MEMBW_SOURCE="off", PYTHONDONTWRITEBYTECODE="1")
    for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        env[name] = "1"
    if args.require_postgres:
        env["GSD_REQUIRE_NATIVE_POSTGRES_TESTS"] = "1"

    if args.lane == "fast":
        try:
            changed = (changed_files(args.changed_since) if args.changed_since else changed_since_the_build())
        except RuntimeError as exc:
            _say(f"fast lane refused: {exc}; run the full lane")
            return 2
        if not args.changed_since:
            _say(f"fast lane against build {recorded_build()}'s files")
        refused = fast_refusal(changed)
        if refused:
            _say(f"fast lane refused: {refused}")
            return 2
        targets = fast_selection(changed)
        _say(f"fast lane: {len(targets)} test file(s) for {len(changed)} changed file(s): {', '.join(changed)}")
        groups = [targets]
    elif args.lane == "all" and str(args.shards) != "1":
        count = (min(8, len(os.sched_getaffinity(0))) + 1) if str(args.shards) == "auto" else int(args.shards)
        try:
            durations = json.loads(DURATIONS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            durations = {}
        hermetic = sorted(str(p.relative_to(ROOT)) for d in HERMETIC_DIRS for p in (ROOT / d).glob("test_*.py"))
        groups = ([["tests/integration", *with_the_folder_s_processes(hermetic)]]
                  + plan_shards(list(HERMETIC_DIRS), max(1, count - 1), durations))
    else:
        groups = [LANES[args.lane]]

    if needs_warming(groups, args.require_postgres):
        _say(warm_postgres(env))
    with tempfile.TemporaryDirectory(prefix="gsd-lane-") as scratch:
        lanes, logs = [], []
        started = time.monotonic()
        for index, targets in enumerate(groups):
            junit = Path(scratch) / f"lane{index}.xml"
            command = [sys.executable, "-m", "pytest", "-vv" if args.verbose else "-q", "-rs",
                       f"--junitxml={junit}", "-o", "junit_family=xunit2", *targets]
            if args.marker:
                command.extend(["-m", args.marker])
            log = (Path(scratch) / f"lane{index}.log").open("w") if len(groups) > 1 else None
            lanes.append((subprocess.Popen(command, cwd=ROOT, env=owned_env(env), start_new_session=True,
                                           stdout=log, stderr=subprocess.STDOUT if log else None), junit))
            logs.append(log)
        if len(groups) > 1:
            _say(f"{len(groups)} lanes at once: the PostgreSQL lane and {len(groups) - 1} of the rest"
                 if args.lane == "all" else f"{len(groups)} lanes")
        with interrupt_on((*STOP_SIGNALS, signal.SIGINT)):
            try:
                statuses = []
                for proc, _junit in lanes:
                    while proc.poll() is None:
                        time.sleep(1.0)
                    statuses.append(proc.returncode)
            except KeyboardInterrupt:
                _say("test lane interrupted; stopping its process groups")
                for proc, _junit in lanes:
                    stop_process_group(proc, log=_say)
                return 130
        for log in logs:
            if log is not None:
                log.close()
        status = next((s for s in statuses if s != 0), 0)
        if len(groups) > 1:
            for index, (proc, _junit) in enumerate(lanes):
                text = (Path(scratch) / f"lane{index}.log").read_text(errors="replace")
                if proc.returncode not in (0,):
                    _say(f"--- lane {index} (exit {proc.returncode}) ---")
                    _say(text[-20000:])
        if not all(junit.is_file() for _proc, junit in lanes):
            return status if status else 1
        counts = [_junit_counts(junit) for _proc, junit in lanes]
        if len(groups) > 1 and args.lane == "all":
            seconds: dict = {}
            for c in counts:
                seconds.update(c["seconds_by_file"])
            try:
                DURATIONS.parent.mkdir(parents=True, exist_ok=True)
                DURATIONS.write_text(json.dumps(dict(sorted(seconds.items())), indent=0), encoding="utf-8")
            except OSError:
                pass
        if len(groups) > 1 or args.lane == "fast":
            tests = sum(c["tests"] for c in counts)
            failed = sum(c["failures"] + c["errors"] for c in counts)
            skipped = sum(c["skipped"] for c in counts)
            wall = time.monotonic() - started
            words = ", ".join(part for part in (
                f"{failed} failed" if failed else "", f"{tests - failed - skipped} passed",
                f"{skipped} skipped" if skipped else "") if part)
            lane_words = (f"fast lane, {len(groups[0])} test files" if args.lane == "fast"
                          else f"{len(groups)} lanes at once")
            _say(f"{words} in {wall:.2f}s ({lane_words})")
        skips = [s for _proc, junit in lanes
                 for s in undeclared_skips(junit, postgres_may_skip=not args.require_postgres)]
        return _judge_skips(status, skips, allow=args.allow_skips)


def _judge_skips(status: int, skips: list[tuple[str, str]], *, allow: bool) -> int:
    if not skips:
        return status
    _say(f"{len(skips)} skipped test(s) not declared in tools/test_suite.py ALLOWED_SKIPS:")
    for node, reason in skips:
        _say(f"  SKIPPED {node}: {reason}")
    if allow:
        _say("--allow-skips: reported, not refused; a release refuses them")
        return status
    _say("a skipped test did not run: make it run here, or declare it in ALLOWED_SKIPS with the reason it cannot")
    return status if status else SKIPS_REFUSED


def needs_warming(groups: list, require_postgres: bool) -> bool:
    return bool(require_postgres) and len(groups) > 1 and any(
        str(target).startswith("tests/integration") for group in groups for target in group)


def warm_postgres(env: dict, run=subprocess.run) -> str:
    tail = ""
    for attempt in range(1, WARM_UP_TRIES + 1):
        done = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", WARM_UP], cwd=ROOT,
                   env=owned_env(env), capture_output=True, text=True, timeout=900)
        if done.returncode == 0:
            return f"PostgreSQL warmed before the lanes ({WARM_UP}, attempt {attempt})"
        tail = ((done.stdout or "") + (done.stderr or ""))[-1500:]
    return f"PostgreSQL warm-up failed {WARM_UP_TRIES} times; the lanes start anyway:\n{tail}"


def _say(line: str) -> None:
    try:
        print(line, flush=True)
    except OSError:
        pass


if __name__ == "__main__":
    die_with_owner()
    raise SystemExit(main())
