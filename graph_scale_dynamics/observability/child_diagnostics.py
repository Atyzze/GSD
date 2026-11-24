from __future__ import annotations

import errno
import faulthandler
import hashlib
import json
import os
import signal
import traceback
from pathlib import Path

NO_SPACE_EXIT_CODE = 74
NO_SPACE_CLASS = "no_space_left"
NO_SPACE_STOP = 7
NO_SPACE_STOP_SECONDS = 24 * 3600.0
NO_SPACE_COST_FROM = 2
NO_SPACE_STOP_TEXT = "full scratches in a row"


def is_no_space(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def exit_code_of(run) -> int:
    try:
        return run()
    except BaseException as exc:
        if is_no_space(exc):
            return NO_SPACE_EXIT_CODE
        raise


def enable_fatal_tracebacks() -> None:
    try:
        faulthandler.enable(all_threads=True)
    except (RuntimeError, OSError):
        pass


def write_terminal_receipt(path: Path | str | None, *, status: str, stage: str,
                           exc: BaseException | None = None, extra: dict | None = None) -> None:
    if path is None:
        return
    target = Path(path)
    payload: dict[str, object] = {
        "schema": "gsd-child-terminal-receipt-v1",
        "status": status,
        "stage": stage,
        "pid": os.getpid(),
    }
    if exc is not None:
        payload.update({
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-32768:],
        })
    if extra:
        payload.update(extra)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    try:
        fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _capture_file(path: Path, *, tail_bytes: int = 16384) -> dict:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"bytes": None, "sha256": None, "tail": "", "read_error": f"{type(exc).__name__}: {exc}"}
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "tail": data[-tail_bytes:].decode("utf-8", errors="replace"),
    }


def process_diagnostics(*, returncode: int | None, stdout_path: Path, stderr_path: Path,
                        receipt_path: Path) -> dict:
    receipt = None
    receipt_error = None
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            receipt_error = f"{type(exc).__name__}: {exc}"

    signal_number = -int(returncode) if returncode is not None and returncode < 0 else None
    signal_name = None
    if signal_number is not None:
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIG{signal_number}"

    if receipt and receipt.get("status") == "success" and returncode == 0:
        classification = "success"
    elif returncode == NO_SPACE_EXIT_CODE:
        classification = NO_SPACE_CLASS
    elif receipt and receipt.get("status") == "failure":
        classification = "python_exception"
    elif signal_number is not None:
        classification = "signal_termination"
    elif receipt_error:
        classification = "invalid_terminal_receipt"
    elif returncode == 0:
        classification = "missing_success_receipt"
    else:
        classification = "missing_failure_receipt"

    return {
        "schema": "gsd-child-process-diagnostics-v1",
        "returncode": returncode,
        "exit_code": returncode if returncode is not None and returncode >= 0 else None,
        "signal": signal_number,
        "signal_name": signal_name,
        "classification": classification,
        "terminal_receipt": receipt,
        "terminal_receipt_error": receipt_error,
        "stdout": _capture_file(stdout_path),
        "stderr": _capture_file(stderr_path),
    }


def concise_failure(diagnostics: dict) -> str:
    receipt = diagnostics.get("terminal_receipt") or {}
    classification = diagnostics.get("classification")
    rc = diagnostics.get("returncode")
    if classification == "python_exception":
        stage = receipt.get("stage") or "child"
        kind = receipt.get("exception_type") or "Exception"
        message = receipt.get("message") or "(exception message empty)"
        return f"child Python exception at {stage}: {kind}: {message}; returncode={rc}"
    if classification == "signal_termination":
        return f"child terminated by {diagnostics.get('signal_name') or diagnostics.get('signal')}; returncode={rc}"
    if classification in ("missing_failure_receipt", "invalid_terminal_receipt"):
        stderr = ((diagnostics.get("stderr") or {}).get("tail") or "").strip()
        suffix = f"; stderr_tail={stderr[-1000:]}" if stderr else "; captured stderr was empty"
        return ("child terminated outside the Python terminal-receipt protocol "
                f"({classification}); returncode={rc}{suffix}")
    if classification == "missing_success_receipt":
        return "child returned 0 without its required success receipt"
    if classification == NO_SPACE_CLASS:
        return f"child could not write: no space left on its filesystem (the RAM scratch); returncode={rc}"
    return f"child process failure ({classification}); returncode={rc}"


SAME_REASON_STOP = 3


def failure_class(diagnostics: dict) -> str:
    receipt = diagnostics.get("terminal_receipt") or {}
    classification = str(diagnostics.get("classification") or "")
    if receipt.get("error_class") == "deployment_provenance_fence":
        return "provenance_fence"
    if classification == NO_SPACE_CLASS:
        return NO_SPACE_CLASS
    if classification == "python_exception":
        kind = str(receipt.get("exception_type") or "Exception")
        if kind in ("MemoryError",):
            return "oom_python"
        return f"exception:{kind}"
    if classification == "signal_termination":
        name = str(diagnostics.get("signal_name") or diagnostics.get("signal") or "SIG?")
        if name == "SIGKILL":
            return "oom_killed"
        return f"signal:{name}"
    if classification in ("missing_success_receipt", "missing_failure_receipt"):
        return "no_result"
    if classification == "invalid_terminal_receipt":
        return "corrupt_receipt"
    return "unknown"


def same_reason_exhausted(classes: list[str], limit: int = SAME_REASON_STOP) -> str | None:
    from graph_scale_dynamics.domain.model import INTERRUPTED_ATTEMPT_CLASSES
    counts: dict[str, int] = {}
    for cls in classes:
        if cls in INTERRUPTED_ATTEMPT_CLASSES:
            continue
        counts[cls] = counts.get(cls, 0) + 1
        if counts[cls] >= limit:
            return cls
    return None
