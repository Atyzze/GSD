from __future__ import annotations

import threading
import time
from collections import OrderedDict

ANSWER_SECONDS = 30.0
ANSWER_ENTRIES = 64


class AnswerCache:
    def __init__(self, *, seconds: float = ANSWER_SECONDS, entries: int = ANSWER_ENTRIES, clock=time.monotonic):
        self.seconds, self.entries, self.clock = float(seconds), int(entries), clock
        self.computed = 0
        self._answers: OrderedDict = OrderedDict()
        self._computing: dict = {}
        self._lock = threading.Lock()

    def _fresh(self, key):
        found = self._answers.get(key)
        if found is None or self.clock() - found[0] >= self.seconds:
            return None
        self._answers.move_to_end(key)
        return found

    def answer(self, key, compute):
        with self._lock:
            found = self._fresh(key)
            if found is not None:
                return found[1]
            gate = self._computing.setdefault(key, threading.Lock())
        with gate:
            with self._lock:
                found = self._fresh(key)
                if found is not None:
                    return found[1]
            try:
                value = compute()
                with self._lock:
                    self.computed += 1
                    self._answers[key] = (self.clock(), value)
                    self._answers.move_to_end(key)
                    while len(self._answers) > self.entries:
                        self._answers.popitem(last=False)
            finally:
                with self._lock:
                    if self._computing.get(key) is gate:
                        del self._computing[key]
        return value

    def forget(self, kind: str, db_path: str) -> None:
        with self._lock:
            for key in [k for k in self._answers if k[:2] == (kind, db_path)]:
                del self._answers[key]


ANSWERS = AnswerCache()
