#!/usr/bin/env python3
from __future__ import annotations

import argparse
import compileall
import hashlib
import signal
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graph_scale_dynamics.operations.process_ownership import owned_env  # noqa: E402

ROOT_FILES = {
    ".gitignore", ".python-version", "BUILD_NUMBER", "CLAUDE.md", "LICENSE", "README.md",
    "main.py", "pyproject.toml", "setup.cfg", "uv.lock",
    "setup.py",
}
OPTIONAL_ROOT_FILES = {
    ".gitignore", ".python-version", "setup.cfg", "uv.lock",
    "LICENSE",
}
REQUIRED_ROOT_FILES = ROOT_FILES - OPTIONAL_ROOT_FILES
ROOT_DIRS = {
    "graph_scale_dynamics",
    "engine_rs",
    "tests",
    "tools",
    "docs",
    "runtime",
    "calibration",
}
EXCLUDED_PARTS = {
    ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__",
    "build", "dist", "var", ".venv", "venv", "target",
    "node_modules",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".dump", ".so", ".tmp", ".before-adopt"}
EXCLUDED_NAMES = {".coverage", ".env.postgres", "probe_calibration.json"}


REQUIRED_RELEASE_PATHS = {
    "engine_rs/Cargo.toml", "engine_rs/pyproject.toml", "engine_rs/src/lib.rs",
    "engine_rs/src/graph.rs", "engine_rs/src/mt.rs", "tools/build_engine.sh",
    "README.md",
    "docs/agent/ENVIRONMENT.md",
    "tools/prepare_environment.sh",
    "tools/selftest.py",
    "tools/adopt_calibration.py",
    "tools/science_freeze.py",
    "calibration/probe_windows.json",
    "calibration/seed_table.json",
    "calibration/baselines/276-certified.json",
    "graph_scale_dynamics/resources/configs/campaign_engine_survey.json",
    "graph_scale_dynamics/resources/configs/candidate_sparse_anchor.json",
    "graph_scale_dynamics/resources/schema/schema.sql",
    "graph_scale_dynamics/resources/ui/index.html",
    "graph_scale_dynamics/resources/ui/app.js",
    "graph_scale_dynamics/resources/ui/candidate.html",
    "graph_scale_dynamics/resources/ui/system.css",
    "graph_scale_dynamics/resources/ui/system.js",
    "graph_scale_dynamics/resources/ui/term_visual.js",
    "graph_scale_dynamics/resources/explorer/explorer.js",
    "graph_scale_dynamics/resources/explorer/explorer.css",
    "graph_scale_dynamics/scheduling/limits.py",
    "graph_scale_dynamics/scaleflow/one_shot.py",
    "graph_scale_dynamics/scaleflow/equilibration.py",
    "graph_scale_dynamics/research/probe_atlas.py",
    "graph_scale_dynamics/research/survey_reports.py",
    "graph_scale_dynamics/research/stability_score.py",
    "docs/ARCHITECTURE.md",
    "docs/RESEARCH_METHOD.md",
    "docs/ROADMAP.md",
}
REQUIRED_NOTES_DIR = "docs/build_notes"


GENERATED_PARTS = {"build", "dist", "__pycache__"}


def remove_generated_files() -> None:
    for path in sorted(ROOT.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if any(part in {".git", "var", ".venv", "venv", "target"} for part in path.relative_to(ROOT).parts):
            continue
        if path.is_dir() and (path.name in GENERATED_PARTS or path.name.endswith(".egg-info")):
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file() and path.suffix in {".pyc", ".pyo"}:
            path.unlink(missing_ok=True)


def current_build() -> int:
    return int((ROOT / "BUILD_NUMBER").read_text().strip())


def synchronized_text(number: int, pyproject_text: str) -> str:
    text, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"', f'version = "{number}"',
        pyproject_text, count=1,
    )
    if count != 1:
        raise RuntimeError("could not locate [project] version in pyproject.toml")
    return text


def tracked_files(root: Path | None = None) -> set[str] | None:
    root = ROOT if root is None else root
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {name for name in out.decode("utf-8", "surrogateescape").split("\0") if name}


def _candidate_paths() -> list[Path]:
    paths = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for directory in sorted(ROOT_DIRS):
        base = ROOT / directory
        if base.is_dir():
            paths.extend(path for path in base.rglob("*") if path.is_file())
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def release_paths() -> list[Path]:
    paths = _candidate_paths()
    tracked = tracked_files()
    if tracked is None:
        return paths
    return [path for path in paths if path.relative_to(ROOT).as_posix() in tracked]


def left_untracked() -> list[str]:
    tracked = tracked_files()
    if tracked is None:
        return []
    return [path.relative_to(ROOT).as_posix() for path in _candidate_paths()
            if include_in_release(path) and path.relative_to(ROOT).as_posix() not in tracked]


def include_in_release(path: Path) -> bool:
    return included(path.relative_to(ROOT))


def included(rel: Path) -> bool:
    if any(
        part in EXCLUDED_PARTS
        or part.endswith(".egg-info")
        or part.startswith(("var_test_", "var-pre-", "var."))
        for part in rel.parts
    ):
        return False
    return rel.suffix not in EXCLUDED_SUFFIXES and rel.name not in EXCLUDED_NAMES


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


LINK_PREFIX = "link:"
RELEASE_EPOCH = 1767225600


def member_identity(path: Path) -> str:
    return LINK_PREFIX + os.readlink(path) if path.is_symlink() else _sha256(path)


def member_mtime(number: int) -> int:
    return RELEASE_EPOCH + int(number)


def _within_tree(path: Path) -> bool:
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def release_member(path: Path, arcname: str, number: int) -> tarfile.TarInfo:
    rel = path.relative_to(ROOT).as_posix()
    info = tarfile.TarInfo(arcname)
    info.mtime, info.uid, info.gid, info.uname, info.gname = member_mtime(number), 0, 0, "", ""
    if path.is_symlink():
        target = os.readlink(path)
        if os.path.isabs(target) or not _within_tree((path.parent / target).resolve()):
            raise RuntimeError(f"refusing to package {rel}: a link to {target}, outside the tree")
        info.type, info.linkname, info.mode = tarfile.SYMTYPE, target, 0o777
        return info
    if not _within_tree(path.resolve()):
        raise RuntimeError(f"refusing to package {rel}: it is reached through a link out of the tree")
    info.size = path.stat().st_size
    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
    return info


def validate_required_release_paths(paths: set[str] | None = None) -> None:
    present = (paths if paths is not None else {
        path.relative_to(ROOT).as_posix()
        for path in release_paths() if include_in_release(path)
    })
    missing = sorted(REQUIRED_RELEASE_PATHS - present)
    if not any(name.startswith(REQUIRED_NOTES_DIR + "/") for name in present):
        missing.append(REQUIRED_NOTES_DIR + "/ (no build notes in the archive)")
    if missing:
        raise RuntimeError(f"release is missing required research/operator tools: {missing}")


GATE_RESULT_TOKEN = "GATE_RESULT"


def run_gate_and_capture_summary(command: list[str]) -> str:
    summary = ""
    proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=owned_env())
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if re.search(r"\b\d+ passed\b", line) or re.search(r"\b\d+ failed\b", line):
                summary = line.strip()
        proc.wait()
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        raise
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, command)
    return re.sub(r"^=+\s*|\s*=+$", "", summary) or "lane passed; pytest printed no summary line"


def fast_lane_command(number: int) -> list[str]:
    before = notes_path(number - 1)
    text = before.read_text(encoding="utf-8") if before.is_file() else ""
    verification = text[text.rfind("## Verification"):] if "## Verification" in text else ""
    if "(fast lane" in verification:
        raise RuntimeError(f"build {number - 1} was released on the fast lane; build {number} runs the full lane")
    from tools import test_suite
    recorded = test_suite.recorded_build()
    if recorded != number - 1:
        raise RuntimeError(f"the fast lane reads what changed since build {number - 1}'s files and this tree records "
                           f"{'none' if recorded is None else f'build {recorded}'}'s; run the full lane")
    return [sys.executable, "tools/test_suite.py", "--lane", "fast", "--require-postgres"]


def notes_path(number: int) -> Path:
    return ROOT / REQUIRED_NOTES_DIR / f"BUILD{number}_NOTES.md"


def stamp_gate_result(number: int, summary: str) -> None:
    path = notes_path(number)
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if not re.search(rf"(?<!`){GATE_RESULT_TOKEN}(?!`)", text):
        raise RuntimeError(f"{path.relative_to(ROOT)} carries no {GATE_RESULT_TOKEN} to stamp: its Verification line "
                           "is another run's; put the token back so this run's lane is the one the archive states")
    stamped = re.sub(rf"(?<!`){GATE_RESULT_TOKEN}(?!`)", lambda _m: summary, text)
    journal_intended(notes_key(number), stamped.encode("utf-8"))
    path.write_text(stamped, encoding="utf-8")
    journal_written(notes_key(number))
    print(f"notes: {path.relative_to(ROOT)} full-lane line: {summary}")


def refuse_unstamped_notes(number: int) -> None:
    path = notes_path(number)
    if path.is_file() and re.search(rf"(?<!`){GATE_RESULT_TOKEN}(?!`)", path.read_text(encoding="utf-8")):
        raise RuntimeError(f"{path.relative_to(ROOT)} still carries {GATE_RESULT_TOKEN}; "
                           "the archive would ship an unverified claim")


def release_output_path(requested: Path | None, number: int, *, unverified: bool = False) -> Path:
    name = f"GSD{number}_unverified.tar.zst" if unverified else f"GSD{number}.tar.zst"
    if requested is None:
        return (ROOT.parent / name).resolve()
    requested = Path(requested)
    if requested.is_dir() or not requested.suffix:
        return (requested / name).resolve()
    return requested.resolve()


RELEASE_WRITES = ("BUILD_NUMBER", "pyproject.toml", "uv.lock", "tests/fixtures/science_freeze.json",
                  "tests/fixtures/build_files.json")
NAMED_WHEN_MOVED = ("tests/fixtures/committed_readings.json",)


def written_by_the_release(number: int) -> set[str]:
    return set(RELEASE_WRITES) | {notes_path(number).relative_to(ROOT).as_posix()}


def tested_tree(number: int) -> dict[str, str]:
    written = written_by_the_release(number)
    return {path.relative_to(ROOT).as_posix(): member_identity(path) for path in release_paths()
            if include_in_release(path) and path.relative_to(ROOT).as_posix() not in written}


def refuse_an_untested_tree(before: dict, after: dict) -> None:
    moved = sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))
    if moved:
        raise RuntimeError("the tree changed while its lane ran, so the archive would ship what was not tested: "
                           f"{moved[:20]}{' ...' if len(moved) > 20 else ''}")


def refuse_unnamed_moves(number: int) -> None:
    record = _tracked_paths()["build_files.json"]
    if not record.is_file():
        return
    last = json.loads(record.read_text(encoding="utf-8")).get("files") or {}
    notes = notes_path(number).read_text(encoding="utf-8") if notes_path(number).is_file() else ""
    unnamed = [rel for rel in NAMED_WHEN_MOVED
               if rel in last and (ROOT / rel).is_file() and _sha256(ROOT / rel) != last[rel]
               and Path(rel).stem not in notes]
    if unnamed:
        raise RuntimeError(f"moved since the last build and not named in its notes: {unnamed}; a build that moves a "
                           "guard or a pin says so, naming the file and what moved in it")


def partial_path(output: Path) -> Path:
    return output.with_name(f".{output.name}.partial")


def archive(number: int, output: Path) -> Path:
    validate_required_release_paths()
    prefix = f"graph_scale_dynamics_build_{number}"
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = partial_path(output)
    partial.unlink(missing_ok=True)
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd is required to create the native .tar.zst release archive")
    with tempfile.TemporaryDirectory(prefix="gsd-release-archive-", dir=output.parent) as raw:
        temporary_dir = Path(raw)
        tar_path = temporary_dir / f"{prefix}.tar"
        compressed = temporary_dir / f"{prefix}.tar.zst"
        with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as tf:
            for path in release_paths():
                if not include_in_release(path):
                    continue
                if path.resolve() in (output.resolve(), partial.resolve()):
                    continue
                info = release_member(path, (Path(prefix) / path.relative_to(ROOT)).as_posix(), number)
                if info.issym():
                    tf.addfile(info)
                    continue
                with path.open("rb") as handle:
                    tf.addfile(info, handle)
        subprocess.run(
            [zstd, "-19", "-T0", "-q", "-f", str(tar_path), "-o", str(compressed)],
            cwd=ROOT, check=True,
        )
        subprocess.run([zstd, "-t", "-q", str(compressed)], cwd=ROOT, check=True)
        os.replace(compressed, partial)
    return partial


def publish_archive(partial: Path, output: Path) -> None:
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(partial, output)
    directory = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


HELD_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def hold_signals() -> set | None:
    if not hasattr(signal, "pthread_sigmask"):
        return None
    return signal.pthread_sigmask(signal.SIG_BLOCK, HELD_SIGNALS)


def release_signals(mask: set | None) -> None:
    if mask is not None:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def package_and_publish(number: int, output: Path, held: list | None = None, tested: dict | None = None) -> None:
    try:
        partial = archive(number, output)
        verify_archive(number, partial, published_as=output, tested=tested)
        if held is not None:
            held.append(hold_signals())
        publish_archive(partial, output)
    except BaseException:
        partial_path(output).unlink(missing_ok=True)
        raise


def verify_archive(number: int, output: Path, published_as: Path | None = None, tested: dict | None = None) -> None:
    excluded = {output.resolve()} | ({published_as.resolve()} if published_as else set())
    prefix = f"graph_scale_dynamics_build_{number}"
    archived_build = (ROOT / "BUILD_NUMBER").read_text(encoding="utf-8").strip()
    if archived_build != str(number):
        raise RuntimeError(
            f"refusing to publish: the archive is named for build {number} but the "
            f"tree it was built from says BUILD_NUMBER is {archived_build}. The "
            "release was interrupted or rolled back between the bump and the "
            "packaging; no archive was written that anyone should keep."
        )
    version_match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if version_match and version_match.group(1) != str(number):
        raise RuntimeError(
            f"refusing to publish: the archive is named for build {number} but "
            f"pyproject.toml declares version {version_match.group(1)}"
        )
    live = {path.relative_to(ROOT).as_posix(): path for path in release_paths()
            if include_in_release(path) and path.resolve() not in excluded}
    written = written_by_the_release(number) if tested is not None else set(live)
    expected = {(Path(prefix) / rel).as_posix(): identity for rel, identity in (
        dict(tested or {}) | {rel: member_identity(path) for rel, path in live.items() if rel in written}).items()}
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd is required to verify the .tar.zst release archive")
    with tempfile.TemporaryDirectory(prefix="gsd-release-verify-") as raw:
        tar_path = Path(raw) / "release.tar"
        subprocess.run(
            [zstd, "-d", "-q", "-f", str(output), "-o", str(tar_path)],
            cwd=ROOT, check=True,
        )
        actual: dict[str, str] = {}
        with tarfile.open(tar_path, "r:") as tf:
            for member in tf.getmembers():
                if member.issym():
                    actual[member.name] = LINK_PREFIX + member.linkname
                    continue
                if not member.isfile():
                    raise RuntimeError(f"release archive contains non-file member: {member.name}")
                extracted = tf.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"cannot read archive member: {member.name}")
                digest = hashlib.sha256()
                for chunk in iter(lambda read=extracted.read: read(1024 * 1024), b""):
                    digest.update(chunk)
                actual[member.name] = digest.hexdigest()
    required_members = {(Path(prefix) / rel).as_posix() for rel in REQUIRED_RELEASE_PATHS}
    missing_required = sorted(required_members - set(actual))
    if missing_required:
        raise RuntimeError(f"release archive is missing required tools: {missing_required}")
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(name for name in expected.keys() & actual.keys()
                     if expected[name] != actual[name])
    if missing or extra or changed:
        raise RuntimeError(
            "release archive differs from source allowlist: "
            f"missing={missing[:5]} extra={extra[:5]} changed={changed[:5]}"
        )


def _fingerprint(cwd: Path, pythonpath: Path | None = None) -> str:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from graph_scale_dynamics.domain.version import runtime_fingerprint; "
            "print(runtime_fingerprint())",
        ],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()[-1]


def validate_wheel() -> None:
    remove_generated_files()
    source_fingerprint = _fingerprint(ROOT)
    with tempfile.TemporaryDirectory(prefix="gsd-release-wheel-") as raw:
        temporary = Path(raw)
        wheel_dir = temporary / "wheel"
        install_dir = temporary / "install"
        wheel_dir.mkdir()
        subprocess.run(
            [
                sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                "--no-build-isolation", "--wheel-dir", str(wheel_dir),
            ],
            cwd=ROOT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            check=True,
        )
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected one wheel, found {len(wheels)}")
        if not wheels[0].name.endswith("-py3-none-linux_x86_64.whl"):
            raise RuntimeError(
                "wheel embeds the Linux x86-64 bootstrap runtime but is not platform-tagged: "
                f"{wheels[0].name}"
            )
        with zipfile.ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())
            forbidden = [name for name in names
                         if name.endswith((".pyc", ".pyo")) or "__pycache__/" in name
                         or ".egg-info/" in name]
            required_runtime = {
                "tools/postgres_instance.py",
                "runtime/bootstrap/linux-amd64/unshare",
                "runtime/bootstrap/linux-amd64/ld-linux-x86-64.so.2",
                "runtime/bootstrap/linux-amd64/libc.so.6",
            }
            missing_runtime = sorted(required_runtime - names)
        if forbidden:
            raise RuntimeError(f"wheel contains generated files: {forbidden[:5]}")
        if missing_runtime:
            raise RuntimeError(f"wheel is missing normal-runtime bootstrap assets: {missing_runtime}")
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--no-deps", "--target",
                str(install_dir), str(wheels[0]),
            ],
            cwd=temporary,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            check=True,
        )
        installed_fingerprint = _fingerprint(temporary, install_dir)
        if installed_fingerprint != source_fingerprint:
            raise RuntimeError(
                "wheel runtime fingerprint differs from source checkout: "
                f"{source_fingerprint[:12]} != {installed_fingerprint[:12]}"
            )
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from importlib.resources import files; "
                "from graph_scale_dynamics.domain.version import BUILD_NUMBER; "
                "r=files('graph_scale_dynamics.resources'); "
                "assert r.joinpath('schema/schema.sql').is_file(); "
                "assert r.joinpath('configs/campaign_engine_survey.json').is_file(); "
                "assert r.joinpath('configs/candidate_sparse_anchor.json').is_file(); "
                "assert r.joinpath('ui/index.html').is_file(); "
                "from graph_scale_dynamics.db.connection import POSTGRES_INSTANCE_HELPER; "
                "assert POSTGRES_INSTANCE_HELPER.is_file(); "
                "from tools import postgres_instance as pg; pg._assert_local_paths(); "
                "assert pg.BUNDLED_UNSHARE.is_file() and pg.BUNDLED_LOADER.is_file() and pg.BUNDLED_LIBC.is_file(); "
                "import main; print(json.dumps({'build': BUILD_NUMBER, 'main': bool(main.main)}))",
            ],
            cwd=temporary,
            env=dict(os.environ, PYTHONPATH=str(install_dir)),
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(probe.stdout.strip().splitlines()[-1])
        if payload["build"] != current_build() or not payload["main"]:
            raise RuntimeError("clean wheel import probe returned invalid build metadata")


def synchronize_uv_lock_if_present(*, required: bool = False) -> None:
    lock = ROOT / "uv.lock"
    if not lock.exists():
        if required:
            raise RuntimeError("promoted releases require a committed uv.lock")
        return
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv.lock exists but uv is unavailable to validate it")

    text = lock.read_text()
    pattern = (r'(?ms)(\[\[package\]\]\nname = "gsd"\n)'
               r'version = "[^"]+"')
    replacement = rf'\g<1>version = "{current_build()}"'
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError("could not locate editable gsd package in uv.lock")
    journal_intended("uv.lock", updated.encode())
    lock.write_text(updated)
    subprocess.run([uv, "lock", "--check", "--offline"], cwd=ROOT, check=True)


def reanchor_science_freeze(number: int) -> None:
    manifest = ROOT / "tests" / "fixtures" / "science_freeze.json"
    if not manifest.exists():
        return
    baseline = json.loads(manifest.read_text(encoding="utf-8"))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from graph_scale_dynamics.domain.science_identity import digest as science_digest
    drifted = [
        name for name, recorded in (baseline.get("files") or {}).items()
        if science_digest(name) != recorded
    ]
    if drifted:
        raise RuntimeError(
            "refusing to package: these science-sensitive sources changed since the "
            "freeze was taken, which is a science change and must be re-anchored "
            "deliberately with `python tools/science_freeze.py --write` and recorded "
            "in the build notes: " + ", ".join(sorted(drifted))
        )
    baseline["baseline_build"] = int(number)
    manifest.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")


JOURNAL = ROOT / "var" / "release_journal.json"
NOTES_KEY = "notes:"


def notes_key(number: int) -> str:
    return NOTES_KEY + notes_path(number).relative_to(ROOT).as_posix()


def _journal_path(name: str) -> Path | None:
    if name.startswith(NOTES_KEY):
        return ROOT / name[len(NOTES_KEY):]
    return _tracked_paths().get(name)


def _write_journal(record: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    partial = JOURNAL.with_name(JOURNAL.name + ".partial")
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=1) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, JOURNAL)


def _process_start(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = stat[stat.rfind(")") + 2:].split()
    return fields[19] if len(fields) > 19 else None


def _tracked_paths() -> dict[str, Path]:
    return {
        "BUILD_NUMBER": ROOT / "BUILD_NUMBER",
        "pyproject.toml": ROOT / "pyproject.toml",
        "science_freeze.json": ROOT / "tests" / "fixtures" / "science_freeze.json",
        "uv.lock": ROOT / "uv.lock",
        "build_files.json": ROOT / "tests" / "fixtures" / "build_files.json",
    }


def _process_alive(pid: int, started: str | None = None) -> bool:
    if pid <= 0:
        return False
    if started is not None:
        return _process_start(pid) == started
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def write_release_journal(number: int, originals: dict[str, str | None]) -> None:
    _write_journal({
        "contract": "gsd-release-journal-1",
        "number": int(number),
        "pid": os.getpid(),
        "pid_started": _process_start(os.getpid()),
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "originals": originals,
    })


def journal_intended(name: str, data: bytes) -> None:
    if not JOURNAL.is_file():
        return
    record = json.loads(JOURNAL.read_text(encoding="utf-8"))
    record.setdefault("written", {})[name] = hashlib.sha256(data).hexdigest()
    _write_journal(record)


def journal_written(name: str) -> None:
    if not JOURNAL.is_file():
        return
    record = json.loads(JOURNAL.read_text(encoding="utf-8"))
    path = _journal_path(name)
    record.setdefault("written", {})[name] = (hashlib.sha256(path.read_bytes()).hexdigest()
                                              if path is not None and path.exists() else None)
    _write_journal(record)


def _ancestors(pid: int) -> set[int]:
    found: set[int] = set()
    while pid > 1 and pid not in found:
        found.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            break
        fields = stat[stat.rfind(")") + 2:].split()
        pid = int(fields[1]) if len(fields) > 1 else 0
    return found


def live_release() -> tuple[int, int] | None:
    try:
        record = json.loads(JOURNAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    owner = record.get("pid")
    if (isinstance(owner, int) and owner not in _ancestors(os.getpid())
            and _process_alive(owner, record.get("pid_started"))):
        return int(record.get("number") or 0), owner
    return None


def restore_from_journal() -> int | None:
    if not JOURNAL.is_file():
        return None
    try:
        record = json.loads(JOURNAL.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"warning: release journal at {JOURNAL} is unreadable ({exc}); ignoring it")
        return None
    if record.get("contract") != "gsd-release-journal-1":
        print(f"warning: release journal at {JOURNAL} has an unknown contract; ignoring it")
        return None
    number = record.get("number")
    owner = record.get("pid")
    if isinstance(owner, int) and _process_alive(owner, record.get("pid_started")):
        print(f"a release of build {number} is already running (pid {owner}); "
              "leaving its journal alone")
        return None
    paths = _tracked_paths()
    restored, kept = [], []
    written = record.get("written")
    for name, content in (record.get("originals") or {}).items():
        path = paths.get(name) or _journal_path(name)
        if path is None:
            continue
        now = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        original = None if content is None else hashlib.sha256(content.encode("utf-8")).hexdigest()
        if written is not None and now != original and now != written.get(name, original):
            kept.append(name)
            continue
        if content is None:
            if path.exists():
                path.unlink()
                restored.append(f"{name} (removed)")
            continue
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            restored.append(name)
    JOURNAL.unlink(missing_ok=True)
    print(f"recovered an interrupted release of build {number}: "
          + (", ".join(restored) if restored else "nothing to restore")
          + (f"; left as they are, changed since the killed run wrote them: {', '.join(kept)}" if kept else "")
          + f"; the tree is back at build {current_build()}")
    return number


FIXTURE_REWRITES = ("GSD_WRITE_REPORT_SNAPSHOT_FIXTURE",)


def before_a_release(root: Path = ROOT, environ=None) -> str | None:
    environ = os.environ if environ is None else environ
    rewriting = [name for name in FIXTURE_REWRITES if environ.get(name)]
    if rewriting:
        return (f"{', '.join(rewriting)} is set, which makes a test write its own fixture and compare it with itself; "
                "unset it and run this again")
    from tools.gate import refusal
    return refusal(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-bump", action="store_true",
                        help="package the current build instead of incrementing it")
    parser.add_argument("--skip-tests", action="store_true",
                        help="skip the normal pytest suite")
    parser.add_argument("--promote", action="store_true",
                        help="enforce dependency-lock and live PostgreSQL release gates")
    parser.add_argument("--skip-compile", action="store_true",
                        help="skip Python syntax compilation before packaging")
    parser.add_argument("--skip-wheel", action="store_true",
                        help="skip wheel build, clean-install, and fingerprint validation")
    parser.add_argument("--output", type=Path,
                        help="archive path, or a directory to write GSD<N>.tar.zst into; "
                             "default: GSD<N>.tar.zst beside the tree")
    parser.add_argument("--fast", action="store_true",
                        help="the fast lane (670): only the tests that touch what changed since the last build, and "
                             "the release's own checks; refused for a frozen source, the schema or the engine, and for "
                             "two releases in a row (the build after a fast one runs the full lane)")
    parser.add_argument("--number", type=int,
                        help="release under this exact number instead of current+1. "
                             "Must be above the current number, "
                             "and the notes for it must declare the number they follow.")
    args = parser.parse_args(argv)

    build_path = ROOT / "BUILD_NUMBER"
    pyproject_path = ROOT / "pyproject.toml"
    running = live_release()
    if running is not None:
        raise SystemExit(f"a release of build {running[0]} is running (pid {running[1]}); wait for it to finish or end "
                         "it, then run this again")
    restore_from_journal()
    original_build = build_path.read_text()
    original_pyproject = pyproject_path.read_text()
    lock_path = ROOT / "uv.lock"
    original_lock = lock_path.read_text() if lock_path.exists() else None
    freeze_path = ROOT / "tests" / "fixtures" / "science_freeze.json"
    original_freeze = freeze_path.read_text() if freeze_path.exists() else None
    files_path = _tracked_paths()["build_files.json"]
    original_files = files_path.read_text(encoding="utf-8") if files_path.exists() else None
    original_notes: tuple[Path, str] | None = None
    if args.number is not None:
        if args.no_bump:
            raise SystemExit("--number and --no-bump contradict each other")
        if int(args.number) <= current_build():
            raise SystemExit(f"--number {args.number} is not above the current build {current_build()}; "
                             "a released number is spent")
        number = int(args.number)
    else:
        number = current_build() if args.no_bump else current_build() + 1
    skipped = [flag for flag, on in (("--skip-tests", args.skip_tests), ("--skip-compile", args.skip_compile),
                                     ("--skip-wheel", args.skip_wheel)) if on]
    if skipped and not args.no_bump:
        raise SystemExit(f"release refused: {', '.join(skipped)} spends no build number; with --no-bump it writes "
                         f"GSD{current_build()}_unverified.tar.zst, which no folder should be given")
    output = release_output_path(args.output, number, unverified=bool(skipped))
    why = before_a_release()
    if why:
        raise SystemExit(f"release refused: {why}")
    notes_original = notes_path(number).read_text(encoding="utf-8") if notes_path(number).is_file() else None

    previous_handlers: dict = {}
    held: list = []
    try:
        write_release_journal(number, {
            "BUILD_NUMBER": original_build,
            "pyproject.toml": original_pyproject,
            "science_freeze.json": original_freeze,
            "uv.lock": original_lock,
            "build_files.json": original_files,
            **({notes_key(number): notes_original} if notes_original is not None else {}),
        })
        def _interrupted(signum, _frame):
            raise KeyboardInterrupt(f"release interrupted by signal {signum}")

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                previous_handlers[sig] = signal.signal(sig, _interrupted)
            except (ValueError, OSError):
                pass
        if notes_path(number).is_file():
            original_notes = (notes_path(number), notes_path(number).read_text(encoding="utf-8"))
        journal_intended("BUILD_NUMBER", f"{number}\n".encode())
        build_path.write_text(f"{number}\n")
        journal_written("BUILD_NUMBER")
        new_pyproject = synchronized_text(number, original_pyproject)
        journal_intended("pyproject.toml", new_pyproject.encode())
        pyproject_path.write_text(new_pyproject)
        journal_written("pyproject.toml")
        reanchor_science_freeze(number)
        journal_written("science_freeze.json")
        if args.promote and (args.skip_tests or args.skip_compile or args.skip_wheel):
            raise RuntimeError(
                "--promote requires tests, syntax compilation, and wheel validation; "
                "skip flags are not allowed"
            )
        synchronize_uv_lock_if_present(required=args.promote)
        journal_written("uv.lock")
        refuse_unnamed_moves(number)
        for rel in left_untracked():
            print(f"left out, not tracked by git: {rel}")
        tested = tested_tree(number)
        if not args.skip_tests:
            test_command = (fast_lane_command(number) if args.fast else
                            [sys.executable, "tools/test_suite.py", "--lane", "all", "--require-postgres",
                             "--shards", "auto"])
            summary = run_gate_and_capture_summary(test_command)
            stamp_gate_result(number, summary)
        else:
            stamp_gate_result(number, "tests skipped (--skip-tests); this archive is not verified")
        if not args.skip_compile and not compileall.compile_dir(ROOT, quiet=1):
            raise RuntimeError("syntax compilation failed")
        if not args.skip_wheel:
            validate_wheel()
        refuse_an_untested_tree(tested, tested_tree(number))
        refuse_unstamped_notes(number)
        from tools import test_suite
        files_text = test_suite.build_files_text(number)
        journal_intended("build_files.json", files_text.encode("utf-8"))
        test_suite.write_build_files(number, text=files_text)
        journal_written("build_files.json")
        package_and_publish(number, output, held=held, tested=tested)
        JOURNAL.unlink(missing_ok=True)
    except BaseException:
        build_path.write_text(original_build)
        pyproject_path.write_text(original_pyproject)
        if original_freeze is not None:
            freeze_path.write_text(original_freeze)
        if original_notes is not None:
            original_notes[0].write_text(original_notes[1], encoding="utf-8")
        if original_lock is None:
            lock_path.unlink(missing_ok=True)
        else:
            lock_path.write_text(original_lock)
        if original_files is None:
            files_path.unlink(missing_ok=True)
        else:
            files_path.write_text(original_files, encoding="utf-8")
        JOURNAL.unlink(missing_ok=True)
        print(f"release failed; the tree is back at build {current_build()} "
              "and no number was spent")
        raise
    finally:
        for sig, handler in previous_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        for mask in held:
            release_signals(mask)

    print(f"build {number}: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
