from __future__ import annotations

import threading
import time

from graph_scale_dynamics.db.repo import Repo


def start_heartbeat_thread(service: str, db_path: str, detail=None,
                           interval_seconds: float = 15.0):
    def _beat() -> None:
        repo = None
        while True:
            try:
                if repo is None:
                    repo = Repo(db_path)
                payload = {}
                if detail is not None:
                    try:
                        payload = dict(detail() or {})
                    except Exception:
                        payload = {"detail_error": True}
                repo.heartbeat(service, payload, paced=True)
            except Exception:
                try:
                    if repo is not None:
                        repo.close()
                except Exception:
                    pass
                repo = None
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_beat, name=f"{service}-heartbeat", daemon=True)
    thread.start()
    return thread
