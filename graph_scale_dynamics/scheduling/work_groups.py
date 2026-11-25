from __future__ import annotations

import json
import os

CONTRACT = "gsd-work-groups-1"
SHARES_FLAG = "work_groups"
SYSTEM_FLAG = "system_cores"
BLIND, MAP = "A", "B"
NEIGHBOURS, DEPTH = "N", "D"
GROUP_NAMES = {BLIND: "the blind draw", MAP: "the map of the best", NEIGHBOURS: "the focus law's neighbourhood",
               DEPTH: "the focus law's depth"}


def parse_shares(text) -> dict[str, float]:
    if isinstance(text, dict):
        raw = text
    else:
        try:
            raw = json.loads(text or "{}")
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for group, share in raw.items():
        if isinstance(share, (int, float)) and not isinstance(share, bool) and share > 0:
            out[str(group)] = float(share)
    total = sum(out.values())
    return {group: share / total for group, share in out.items()} if total > 0 else {}


def shares(repo) -> dict[str, float]:
    getter = getattr(repo, "get_flag", None)
    return parse_shares(getter(SHARES_FLAG, "")) if callable(getter) else {}


def set_shares(repo, given: dict) -> dict[str, float]:
    found = parse_shares(given)
    if given and not found:
        raise ValueError(f"{given!r} gives no group a share above zero")
    repo.set_flag(SHARES_FLAG, json.dumps(found, sort_keys=True) if found else "")
    return found


def parse_cpus(text) -> set[int]:
    out: set[int] = set()
    for part in str(text or "").replace(" ", "").split(","):
        if not part:
            continue
        low, _, high = part.partition("-")
        first, last = int(low), int(high or low)
        if first < 0 or last < first:
            raise ValueError(f"{part!r} is not a CPU or a range of CPUs")
        out.update(range(first, last + 1))
    return out


def system_cpus(repo) -> set[int]:
    try:
        return parse_cpus(repo.get_flag(SYSTEM_FLAG, ""))
    except ValueError:
        return set()


def allowed_cpus() -> set[int]:
    try:
        return set(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return set(range(os.cpu_count() or 1))


def work_cpus(system: set[int], allowed: set[int] | None = None) -> set[int]:
    allowed = set(allowed if allowed is not None else allowed_cpus())
    left = allowed - set(system)
    return left if left else allowed


def set_system(repo, text: str, allowed: set[int] | None = None) -> set[int]:
    found = parse_cpus(text)
    every = set(allowed if allowed is not None else os_cpus())
    outside = found - every
    if outside:
        raise ValueError(f"this host has no CPU {', '.join(str(c) for c in sorted(outside))}")
    if found and not every - found:
        raise ValueError("the system cannot keep every CPU: no simulation would have one to run on")
    repo.set_flag(SYSTEM_FLAG, ",".join(str(c) for c in sorted(found)))
    return found


def os_cpus() -> set[int]:
    return set(range(os.cpu_count() or 1))


def pin_to_work(repo, *, allowed: set[int] | None = None, setter=None) -> set[int] | None:
    try:
        system = system_cpus(repo)
    except Exception:  # noqa: BLE001
        return None
    every = set(allowed if allowed is not None else os_cpus())
    wanted = work_cpus(system, every)
    setter = setter or os.sched_setaffinity
    try:
        setter(0, wanted)
    except (AttributeError, OSError):
        return None
    return wanted


KEEP_PINNED_SECONDS = 5.0


def pin_process(pid: int, cpus: set[int], *, tasks=None, setter=None) -> int:
    setter = setter or os.sched_setaffinity
    if tasks is None:
        try:
            tasks = [int(name) for name in os.listdir(f"/proc/{int(pid)}/task")]
        except OSError:
            tasks = [int(pid)]
    done = 0
    for tid in tasks:
        try:
            setter(int(tid), set(cpus))
            done += 1
        except (OSError, ValueError):
            continue
    return done


class Pinned:
    def __init__(self, repo, pid: int, *, clock=None, setter=None, allowed: set[int] | None = None):
        import time
        self.repo, self.pid, self.setter, self.allowed = repo, int(pid), setter, allowed
        self.clock = clock or time.monotonic
        self.at, self.cpus = self.clock(), None
        try:
            self.cpus = work_cpus(system_cpus(repo), set(allowed if allowed is not None else os_cpus()))
        except Exception:  # noqa: BLE001
            self.cpus = None

    def keep(self) -> bool:
        now = self.clock()
        if now - self.at < KEEP_PINNED_SECONDS:
            return False
        self.at = now
        try:
            wanted = work_cpus(system_cpus(self.repo), set(self.allowed if self.allowed is not None else os_cpus()))
        except Exception:  # noqa: BLE001
            return False
        if wanted == self.cpus:
            return False
        self.cpus = wanted
        pin_process(self.pid, wanted, setter=self.setter)
        return True


def split_of(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in [p for p in str(text or "").replace(" ", "").split(",") if p]:
        group, sign, share = part.partition("=")
        if not group or not sign:
            raise ValueError(f"{part!r} is not GROUP=SHARE")
        try:
            out[group] = float(share)
        except ValueError as exc:
            raise ValueError(f"{share!r} is not a share") from exc
    return out


def siblings(cpus: set[int], sysfs: str = "/sys/devices/system/cpu") -> dict[int, list[int]]:
    out = {}
    for cpu in sorted(cpus):
        try:
            with open(f"{sysfs}/cpu{int(cpu)}/topology/thread_siblings_list", encoding="utf-8") as handle:
                found = parse_cpus(handle.read().strip())
        except (OSError, ValueError):
            continue
        out[int(cpu)] = sorted(found - {int(cpu)})
    return out


def in_shares(allocation: list[dict], given: dict[str, float]) -> list[dict] | None:
    if not given:
        return None
    groups: dict[str | None, list[dict]] = {}
    for row in allocation:
        group = row.get("work_group") or BLIND
        groups.setdefault(group if group in given else None, []).append(row)

    def working(rows: list[dict]) -> bool:
        return any(int(row.get("queued") or 0) > 0 and row.get("workers_target") != 0 for row in rows)

    named = {group: rows for group, rows in groups.items() if group is not None and working(rows)}
    if not named:
        return None
    total = sum(int(row.get("leased") or 0) for row in allocation) + 1
    owed = {group: given[group] * total - sum(int(row.get("leased") or 0) for row in rows)
            for group, rows in named.items()}
    most = max(owed.values())
    chosen = [group for group in sorted(named) if owed[group] == most]
    return [row for group in chosen for row in named[group]] + list(groups.get(None) or [])


def reading(repo) -> dict:
    given, system = shares(repo), system_cpus(repo)
    every = os_cpus()
    shared = {cpu: mates for cpu, mates in siblings(system).items() if set(mates) - system}
    return {"contract": CONTRACT, "shares": given, "system_cpus": sorted(system),
            "work_cpus": sorted(work_cpus(system, every)), "cpus": len(every),
            "split": ",".join(f"{group}={share:g}" for group, share in sorted(given.items())),
            "shares_a_core": {str(cpu): mates for cpu, mates in shared.items()},
            "words": ("each group with work is given slots toward its share of the simulations running; a group with "
                      "nothing queued leaves its slots to the others until it has work again; every simulation and "
                      "analysis runs only on the work CPUs, never on the system's, a running one moved off them within "
                      "five seconds of a change")}


def command(repo, split: str | None, system: str | None) -> tuple[int, str]:
    try:
        if split is not None:
            set_shares(repo, split_of(split))
        if system is not None:
            set_system(repo, system)
    except ValueError as exc:
        return 2, f"refused: {exc}"
    found = reading(repo)
    lines = [f"work groups: {', '.join(f'{g} {v:.0%}' for g, v in sorted(found['shares'].items())) or 'none: every campaign alike'}",
             f"system CPUs: {', '.join(str(c) for c in found['system_cpus']) or 'none'}; simulations and analyses run "
             f"on {len(found['work_cpus'])} of {found['cpus']} CPUs"]
    lines += [f"CPU {cpu} shares its core with CPU {', '.join(str(m) for m in mates)}, which simulations may still use"
              for cpu, mates in found["shares_a_core"].items()]
    return 0, "\n".join(lines + [found["words"]])
