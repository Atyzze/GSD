from __future__ import annotations

import secrets
import threading
import time

from graph_scale_dynamics.observability.console import iso_utc_now

CONTRACT = "gsd-admin-link-1"
SAY_EVERY_SECONDS = 60.0
STATES = ("current", "stale", "none")
ADMIN_RULE = "the admin token (the admin link's #admin=...), from any device, through the dashboard"
STALE_HINT = ("this page's admin link is not this run's: every start makes a new one; open the link the run made "
              "(var/run/dashboard-admin)")


def _said(line: str) -> None:
    print(line, flush=True)


class AdminLink:
    def __init__(self, token: str, *, say=None, clock=time.monotonic, minted_utc: str | None = None):
        self._token = token or ""
        self.minted_utc = minted_utc or iso_utc_now()
        self._say = say or _said
        self._clock = clock
        self._lock = threading.Lock()
        self._refused = {"stale": 0, "none": 0}
        self._unsaid = {"stale": 0, "none": 0}
        self._said_at: float | None = None

    def matches(self, supplied: str) -> bool:
        if not supplied or not self._token:
            return False
        return secrets.compare_digest(supplied.encode("utf-8", "surrogatepass"),
                                      self._token.encode("utf-8", "surrogatepass"))

    def state(self, supplied: str) -> str:
        if not supplied:
            return "none"
        return "current" if self.matches(supplied) else "stale"

    def refused(self, supplied: str, route: str) -> None:
        kind = self.state(supplied)
        if kind == "current":
            return
        with self._lock:
            self._refused[kind] += 1
            self._unsaid[kind] += 1
            now = self._clock()
            if self._said_at is not None and now - self._said_at < SAY_EVERY_SECONDS:
                return
            stale, none = self._unsaid["stale"], self._unsaid["none"]
            self._unsaid = {"stale": 0, "none": 0}
            self._said_at = now
        self._say(f"{iso_utc_now()} [api] admin: refused {stale + none} write(s) since the last such line: {stale} "
                  f"with an admin link that is not this run's (this run's was made {self.minted_utc}), {none} with "
                  f"none; the last on {route}")

    def accepted(self, route: str, action: str | None = None) -> None:
        self._say(f"{iso_utc_now()} [api] admin: {route}{' ' + action if action else ''} accepted, with this run's "
                  f"admin link (made {self.minted_utc})")

    def payload(self, supplied: str, *, loopback: bool) -> dict:
        state = self.state(supplied)
        with self._lock:
            refused = dict(self._refused)
        return {"contract": CONTRACT, "link": state, "admin": bool(loopback and state == "current"),
                "minted_utc": self.minted_utc, "refused": refused}

    def access(self, supplied: str, *, loopback: bool) -> dict:
        payload = self.payload(supplied, loopback=loopback)
        return dict(payload, local_admin=payload["admin"], admin_rule=ADMIN_RULE, can_pause=payload["admin"])

    def refusal(self, supplied: str, said: str) -> dict:
        return {"error": said, "hint": STALE_HINT} if self.state(supplied) == "stale" else {"error": said}
