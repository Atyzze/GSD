from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def partial_path(output, name: str) -> Path:
    if output:
        out = Path(output)
        return out.with_name(out.name + ".partial")
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    return ROOT / "var" / "readings" / f"{name}_{stamp}.partial.json"


@contextmanager
def kept_on_failure(rows: list, path: Path, **about):
    try:
        yield
    except BaseException as exc:
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"complete": False, "error": f"{type(exc).__name__}: {exc}"[:500],
                                        "rows_so_far": len(rows), **about, "rows": list(rows)},
                                       indent=1, default=str) + "\n", encoding="utf-8")
            print(f"the run failed; its {len(rows)} row(s) so far are in {path}", file=sys.stderr, flush=True)
        except Exception as written:
            print(f"the run failed, and its rows could not be kept: {written}", file=sys.stderr, flush=True)
        raise
