from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

ACCESS_NAME = "api_access.json"
KEEPER_CONTRACT = "gsd-bundle-keeper-2"

_ROUTE_ID = re.compile(r"/[0-9a-f]{16,}|/\d+(?=/|$)")
_WORD = re.compile(r"[a-z][a-z0-9_-]{0,23}")
_SOURCES = ("services/api/main.py", "services/api/readings_route.py", "services/api/gate_route.py",
            "services/api/study_route.py", "services/api/campaign_manager.py", "services/web/main.py")
_KNOWN: frozenset[str] = frozenset()
MAX_ROUTES, MAX_PAGES = 256, 32
OTHER = "{other}"


def _known() -> frozenset[str]:
    global _KNOWN
    if not _KNOWN:
        root, words = Path(__file__).resolve().parents[2], set()
        for name in _SOURCES:
            try:
                words.update(re.findall(r'"([a-z][a-z0-9_-]{0,23})"', (root / name).read_text(encoding="utf-8")))
            except OSError:
                continue
        _KNOWN = frozenset(words | {"api", "reports", "candidate", "candidate-data", "direct", "study", "home",
                                    "explorer", "campaigns", "system", "calibration", "gates", "classify"})
    return _KNOWN


def _words(path: str, keep: int) -> str:
    known = _known()
    parts = [p if (_WORD.fullmatch(p) and p in known) or p == "{id}" else "{x}" for p in path.strip("/").split("/") if p]
    return "/" + "/".join(parts[:keep] + (["{x}"] if len(parts) > keep else []))


def route_pattern(path: str) -> str:
    return _words(_ROUTE_ID.sub("/{id}", path.split("?", 1)[0]), 3)


class AccessCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def record(self, path: str, referer: str | None, page_header: str | None = None) -> None:
        page = "direct"
        if page_header:
            page = _words(str(page_header), 1)
        elif referer:
            tail = referer.split("//", 1)[-1].split("/", 1)
            page = _words(_ROUTE_ID.sub("/{id}", "/" + (tail[1].split("?", 1)[0] if len(tail) > 1 else "")), 1)
        route = route_pattern(path)
        with self._lock:
            if route not in self._counts and len(self._counts) >= MAX_ROUTES:
                route = OTHER
            pages = self._counts[route]
            if page not in pages and len(pages) >= MAX_PAGES:
                page = OTHER
            pages[page] += 1

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self.started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def payload(self) -> dict:
        with self._lock:
            routes = {route: dict(sorted(pages.items())) for route, pages in sorted(self._counts.items())}
        return {"contract": KEEPER_CONTRACT, "started_utc": self.started_utc,
                "sampled_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "routes": routes,
                "totals": {route: sum(pages.values()) for route, pages in routes.items()}}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


class BundleKeeper(threading.Thread):
    POLL_SECONDS = 1.0

    def __init__(self, report_root: Path, counter: AccessCounter, *,
                 interval_seconds: float = 20.0, poll_seconds: float | None = None,
                 log=print):
        super().__init__(name="bundle-keeper", daemon=True)
        self.report_root = Path(report_root)
        self.counter = counter
        self.interval = max(2.0, float(interval_seconds))
        self.poll = min(self.interval,
                        max(0.1, float(self.POLL_SECONDS if poll_seconds is None
                                       else poll_seconds)))
        self.log = log
        self._stop = threading.Event()
        self._active_root = Path(report_root)
        self._last_flush = 0.0

    def stop(self) -> None:
        self._stop.set()

    def tick(self, *, flush_due: bool = True) -> None:
        from graph_scale_dynamics.operations.report_home import current_root
        try:
            root = current_root(self.report_root)
        except Exception as exc:
            self.log(f"[web] report home unresolved: {type(exc).__name__}: {exc}")
            root = self.report_root
        if root != self._active_root:
            self.counter.reset()
            self._active_root = root
        if not flush_due:
            return
        try:
            payload = dict(self.counter.payload())
            payload["report_root"] = str(root)
            _atomic_write(root / ACCESS_NAME,
                          json.dumps(payload, indent=1, sort_keys=True).encode("utf-8"))
        except Exception as exc:
            self.log(f"[web] access counter flush failed: {type(exc).__name__}: {exc}")

    def run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            due = (now - self._last_flush) >= self.interval
            if due:
                self._last_flush = now
            self.tick(flush_due=due)
            self._stop.wait(self.poll)
