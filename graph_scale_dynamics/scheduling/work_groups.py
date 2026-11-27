from __future__ import annotations

import json
import os

CONTRACT = "gsd-work-groups-1"
SHARES_FLAG = "work_groups"
SYSTEM_FLAG = "system_cores"
BLIND, MAP = "A", "B"
NEIGHBOURS, DEPTH = "N", "D"
LAWS_IN_KINDS = ("seed",)
FOCUS_KIND = "focus"
ZONE_PARTS = ("N", "S", "E")
BEHIND = 10_000_000_000
ZONE_TIER, DEPTH_TIER, DEX_TIER, BLIND_TIER, LEFTOVER_TIER = range(5)
TIER_NAMES = ("the zone of the law in focus", "the depth worker", "the Dex laws read again", "the blind draw",
              "earlier laws' leftovers")
TIER_SQL = ("CASE WHEN (c.spec_json::jsonb #>> '{study_design,kind}')='focus' "
            "AND (c.spec_json::jsonb #>> '{study_design,focus,part}') IN ('N','S','E') THEN 0 "
            "WHEN (c.spec_json::jsonb #>> '{study_design,kind}')='focus' "
            "AND (c.spec_json::jsonb #>> '{study_design,focus,part}')='D' THEN 1 "
            "WHEN (c.spec_json::jsonb #>> '{study_design,kind}')='seed' THEN 2 ELSE 3 END")
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


def group_of(row: dict) -> str:
    if row.get("design_kind") in LAWS_IN_KINDS:
        return BLIND
    return row.get("work_group") or BLIND


BY_LAW = "by_law"
VERIFY_TO = 4096


VERIFYING_FLAG = "dex_verifying_to"


def verifying(repo) -> int | None:
    getter = getattr(repo, "get_flag", None)
    raw = getter(VERIFYING_FLAG, "") if callable(getter) else ""
    return int(raw) if str(raw or "").isdigit() and int(raw) > 0 else None


def claim_bounds(tier: int, verifying_to: int | None = None) -> list[dict]:
    if tier == DEX_TIER:
        return [{"order": BY_LAW, "max_n": int(verifying_to or VERIFY_TO)}] + ([] if verifying_to else [{"order": BY_LAW}])
    return [{}]


def tier_of(row: dict) -> int:
    kind, part = row.get("design_kind"), row.get("focus_part")
    if kind == FOCUS_KIND:
        return ZONE_TIER if part in ZONE_PARTS else DEPTH_TIER if part == DEPTH else BLIND_TIER
    if kind in LAWS_IN_KINDS:
        return DEX_TIER
    return BLIND_TIER


def _open(row: dict) -> bool:
    target = row.get("workers_target")
    return target != 0 and (target is None or int(row.get("leased") or 0) < int(target))


def _first(row: dict) -> int:
    return int(row.get("queued") or 0) - int(row.get("behind") or 0)


def ordered(allocation: list[dict]) -> list[tuple[int, list[dict]]] | None:
    if not any(row.get("design_kind") == FOCUS_KIND for row in allocation):
        return None
    tiers: dict[int, list[dict]] = {}
    for row in allocation:
        if not _open(row) or tier_of(row) == DEPTH_TIER:
            continue
        if _first(row) > 0:
            tiers.setdefault(tier_of(row), []).append(row)
        if int(row.get("behind") or 0) > 0:
            tiers.setdefault(LEFTOVER_TIER, []).append(row)
    out = [(tier, tiers[tier]) for tier in sorted(tiers)]
    held = [row for row in allocation if row.get("workers_target") not in (None, 0) and _open(row) and _first(row) > 0
            and tier_of(row) != DEPTH_TIER]
    if out:
        first, rows = out[0]
        out[0] = (first, rows + [row for row in held if row not in rows])
    return out


def now_on(allocation: list[dict]) -> dict:
    found = ordered(allocation)
    if found is None:
        return {"ordered": False, "tier": None, "name": None}
    if not found:
        return {"ordered": True, "tier": None, "name": "nothing queued"}
    tier = found[0][0]
    queued: dict[str, int] = {}
    for row in allocation:
        if row.get("workers_target") == 0:
            continue
        for at, count in ((tier_of(row), _first(row)), (LEFTOVER_TIER, int(row.get("behind") or 0))):
            if count > 0:
                queued[TIER_NAMES[at]] = queued.get(TIER_NAMES[at], 0) + count
    return {"ordered": True, "tier": tier, "name": TIER_NAMES[tier], "queued": queued}


def in_shares(allocation: list[dict], given: dict[str, float]) -> list[dict] | None:
    if not given:
        return None
    groups: dict[str | None, list[dict]] = {}
    for row in allocation:
        group = group_of(row)
        groups.setdefault(group if group in given else None, []).append(row)

    def working(rows: list[dict]) -> bool:
        return any(int(row.get("queued") or 0) > 0 and row.get("workers_target") != 0
                   and (row.get("workers_target") is None or int(row.get("leased") or 0) < int(row["workers_target"]))
                   for row in rows)

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
            "order": list(TIER_NAMES),
            "words": ("in a folder with a focus the fleet takes its work in one order, runs and probes alike: the zone "
                      "of the law in focus, the Dex laws read again (only to the level they are verified at while a "
                      "dex is checked), the blind draw, earlier laws' leftovers; each takes a worker only when the ones "
                      "before it have nothing queued, and a run under way is never stopped for one before it. While the "
                      "Top page's push list holds a law, every slot runs it alone and every other run is stopped with its "
                      "seed saved; with the list empty the depth worker runs on a slot of its own above the worker "
                      "count. Elsewhere each group with work is given slots "
                      "toward its share. Every simulation and analysis runs only on the work CPUs, never on the "
                      "system's, a running one moved off them within five seconds of a change")}


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
