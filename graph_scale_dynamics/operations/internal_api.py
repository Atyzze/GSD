from __future__ import annotations

import http.client
import json
import os
import random
import time
from pathlib import Path
from urllib import error, request

DEFAULT_ATTEMPTS = 5
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0


def _env_float(name: str, fallback: float) -> float:
    try:
        return float(str(os.environ.get(name, "")).strip() or fallback)
    except ValueError:
        return fallback


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or fallback)
    except ValueError:
        return fallback


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, error.HTTPError):
        return int(getattr(exc, "code", 0)) >= 500
    if isinstance(exc, error.URLError):
        return True
    return isinstance(exc, (
        TimeoutError, ConnectionError, http.client.RemoteDisconnected,
        http.client.IncompleteRead, http.client.BadStatusLine,
    ))


def retry_transient(operation, *, attempts: int | None = None,
                    base_delay: float | None = None,
                    max_delay: float | None = None,
                    sleep=time.sleep, jitter=random.random,
                    on_retry=None):
    attempts = _env_int("GSD_INTERNAL_API_RETRIES", DEFAULT_ATTEMPTS) if attempts is None else int(attempts)
    attempts = max(1, attempts)
    base_delay = _env_float("GSD_INTERNAL_API_RETRY_BASE_SECONDS", DEFAULT_BASE_DELAY_SECONDS) if base_delay is None else float(base_delay)
    max_delay = DEFAULT_MAX_DELAY_SECONDS if max_delay is None else float(max_delay)
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if not is_transient(exc) or attempt >= attempts:
                raise
            last = exc
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += delay * 0.25 * float(jitter())
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)
    raise last if last is not None else RuntimeError("retry_transient exhausted without an error")


def read_internal_token(path: str | Path) -> str:
    token = Path(path).read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("internal API capability file is empty")
    return token


class InternalAPI:
    def __init__(self, base_url: str, token_file: str | Path, *, timeout: float = 30.0,
                 attempts: int | None = None, base_delay: float | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = read_internal_token(token_file)
        self.timeout = float(timeout)
        self.attempts = None if attempts is None else int(attempts)
        self.base_delay = None if base_delay is None else float(base_delay)
        self.retry_events: list[dict] = []

    def _retry(self, operation, label: str):
        def note(attempt: int, exc: BaseException, delay: float) -> None:
            self.retry_events.append({
                "target": label,
                "attempt": attempt,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "retry_in_seconds": round(float(delay), 3),
            })
        return retry_transient(operation, attempts=self.attempts,
                               base_delay=self.base_delay, on_retry=note)

    def fetch_bytes(self, path: str, *, timeout: float | None = None) -> bytes:
        return self._request(path, method="GET", timeout=timeout)

    def _request(self, path: str, *, method: str = "GET", payload: dict | None = None,
                 timeout: float | None = None) -> bytes:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        headers = {"X-GSD-Internal-Token": self.token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = request.Request(self.base_url + path, data=body, headers=headers, method=method)
        effective = self.timeout if timeout is None else timeout

        def attempt() -> bytes:
            with request.urlopen(req, timeout=effective) as response:
                return response.read()

        try:
            return self._retry(attempt, f"{method} {path}")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            size = "" if body is None else f" (request body {len(body)} bytes)"
            raise RuntimeError(f"internal API {method} {path} failed {exc.code}{size}: "
                               f"{detail[:16000]}") from exc

    def get_json(self, path: str, *, timeout: float | None = None) -> dict:
        return json.loads(self._request(path, timeout=timeout).decode("utf-8"))
