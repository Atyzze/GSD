from __future__ import annotations

import os
import signal
import subprocess


def kill_process_group(child: subprocess.Popen, *, timeout: float = 5) -> None:
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return


def descendant_pids(pid: int) -> list[int] | None:
    found: list[int] = []
    frontier = [int(pid)]
    seen = {int(pid)}
    offered = False
    while frontier:
        current = frontier.pop()
        try:
            tasks = os.listdir(f"/proc/{current}/task")
        except OSError:
            continue
        for tid in tasks:
            try:
                with open(f"/proc/{current}/task/{tid}/children", encoding="ascii") as handle:
                    text = handle.read()
            except FileNotFoundError:
                continue
            except OSError:
                continue
            offered = True
            for word in text.split():
                child = int(word)
                if child not in seen:
                    seen.add(child)
                    found.append(child)
                    frontier.append(child)
    if not offered and os.path.exists(f"/proc/{int(pid)}"):
        return None
    return found


def process_tree(pid: int) -> list:
    import psutil
    root = psutil.Process(int(pid))
    children = descendant_pids(root.pid)
    if children is None:
        return [root, *root.children(recursive=True)]
    members = [root]
    for child in children:
        try:
            members.append(psutil.Process(child))
        except psutil.NoSuchProcess:
            continue
    return members


def yield_to_the_fleet(env_key: str = "GSD_DASHBOARD_NICE", default: int = 10) -> int | None:
    try:
        return os.nice(int(os.environ.get(env_key, str(default))))
    except (AttributeError, OSError, ValueError):
        return None


def yield_this_thread(env_key: str = "GSD_DASHBOARD_NICE", default: int = 10) -> bool:
    import threading
    try:
        tid = threading.get_native_id()
        current = os.getpriority(os.PRIO_PROCESS, tid)
        os.setpriority(os.PRIO_PROCESS, tid, min(19, current + int(os.environ.get(env_key, str(default)))))
        return True
    except (AttributeError, OSError, ValueError):
        return False
