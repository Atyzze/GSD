from __future__ import annotations

import pytest

from graph_scale_dynamics.scheduling import work_groups as W
from graph_scale_dynamics.services.worker.main import allowed_campaigns


class _Flags:
    def __init__(self, **flags):
        self.flags = dict(flags)

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value


def _row(campaign, group, leased, queued, target=None):
    return {"campaign_id": campaign, "work_group": group, "leased": leased, "queued": queued, "workers_target": target}


def test_each_group_with_work_is_given_slots_toward_its_share_of_what_runs():
    shares = {"A": 0.5, "B": 0.5}
    blind = [_row("1", "A", 3, 50), _row("2", "A", 2, 50)]
    assert allowed_campaigns(blind + [_row("3", "B", 1, 9)], shares) == ("3",), "B holds 1 of 6: it is owed"
    assert allowed_campaigns(blind + [_row("3", "B", 6, 9)], shares) == ("2",), (
        "A holds 5 of 12: A is owed, and inside A the campaign furthest behind its equal part")
    assert allowed_campaigns(blind + [_row("3", "B", 5, 9)], shares) == ("2",)


def test_a_group_with_nothing_queued_leaves_its_slots_to_the_others_until_it_has_work():
    shares = {"A": 0.5, "B": 0.5}
    found = allowed_campaigns([_row("1", "A", 15, 50), _row("3", "B", 0, 0)], shares)
    assert found == ("1",), "a study with nothing to map yet is all blind"
    assert allowed_campaigns([_row("1", "A", 15, 50), _row("3", "B", 0, 4)], shares) == ("3",)


def test_a_campaign_outside_every_group_competes_beside_the_group_that_is_owed():
    shares = {"A": 0.5, "B": 0.5}
    found = allowed_campaigns([_row("1", "A", 4, 50), _row("3", "B", 1, 9), _row("9", None, 0, 2)], shares)
    assert set(found) <= {"3", "9"} and found


def test_a_study_s_batches_made_before_its_groups_are_the_blind_draw():
    shares = W.parse_shares({"A": 2, "N": 1, "D": 1})
    batches = [_row("1", None, 4, 50), _row("2", None, 4, 50)]
    focus = [_row("11", "N", 1, 40), _row("12", "N", 0, 1), _row("13", "D", 2, 6)]
    assert allowed_campaigns(batches + focus, shares) == ("12",), (
        "the batches hold 8 of 12, over their half, N 1 of its 3: N is owed, its campaign furthest behind first")
    assert allowed_campaigns([_row("1", None, 1, 50), _row("2", None, 3, 50), _row("11", "N", 3, 40),
                              _row("13", "D", 3, 6)], shares) == ("1",), (
        "the batches hold 4 of 11, under their half: A is owed, and an ungrouped batch is A")
    assert {r["campaign_id"] for r in W.in_shares([_row("1", None, 4, 50), _row("3", "B", 1, 9)], {"B": 1.0})} == {"1", "3"}, (
        "with no A among the shares, a campaign outside every group still competes beside the owed one")


def test_no_shares_is_the_fleet_as_it_was():
    rows = [_row("1", "A", 3, 50), _row("3", "B", 1, 9)]
    assert allowed_campaigns(rows) == allowed_campaigns(rows, {}) == allowed_campaigns(rows, None)


def test_shares_are_read_normalised_and_refused_when_empty():
    repo = _Flags()
    assert W.shares(repo) == {}
    assert W.set_shares(repo, {"A": 1, "B": 1}) == {"A": 0.5, "B": 0.5}
    assert W.shares(repo) == {"A": 0.5, "B": 0.5}
    assert W.set_shares(repo, {"A": 3, "B": 1}) == {"A": 0.75, "B": 0.25}
    with pytest.raises(ValueError):
        W.set_shares(repo, {"A": 0})
    assert W.parse_shares("not json") == {} and W.shares(object()) == {}


def test_the_system_keeps_the_cpus_it_is_given_and_every_child_runs_on_the_others():
    repo = _Flags()
    assert W.parse_cpus("0-1, 16,17") == {0, 1, 16, 17}
    with pytest.raises(ValueError):
        W.parse_cpus("3-1")
    assert W.set_system(repo, "0,1", allowed=set(range(8))) == {0, 1}
    pinned = {}
    assert W.pin_to_work(repo, allowed=set(range(8)), setter=lambda pid, cpus: pinned.update({pid: set(cpus)})) == \
        set(range(2, 8))
    assert pinned == {0: set(range(2, 8))}
    with pytest.raises(ValueError):
        W.set_system(repo, "0-7", allowed=set(range(8)))
    with pytest.raises(ValueError):
        W.set_system(repo, "9", allowed=set(range(8)))
    assert W.set_system(repo, "", allowed=set(range(8))) == set()
    assert W.pin_to_work(repo, allowed=set(range(8)), setter=lambda pid, cpus: pinned.update({pid: set(cpus)})) == \
        set(range(8)), "with no system CPUs a child may run anywhere again"
    assert W.work_cpus({0, 1}, {0, 1}) == {0, 1}, "a system set holding every CPU leaves the children where they are"


def test_a_repo_that_cannot_answer_leaves_the_child_where_it_is():
    class _Broken:
        def get_flag(self, *_a):
            raise RuntimeError("away")
    assert W.pin_to_work(_Broken(), setter=lambda *_a: pytest.fail("pinned")) is None


def test_a_running_child_is_moved_off_the_system_s_cpus_within_seconds_of_a_change():
    repo, moved, clock = _Flags(), [], [0.0]
    pinned = W.Pinned(repo, 4242, clock=lambda: clock[0], allowed=set(range(4)),
                      setter=lambda tid, cpus: moved.append((tid, set(cpus))))
    assert pinned.cpus == {0, 1, 2, 3} and not pinned.keep()
    W.set_system(repo, "0", allowed=set(range(4)))
    clock[0] = 1.0
    assert not pinned.keep() and moved == [], "read again only every few seconds"
    clock[0] = 6.0
    assert pinned.keep() and moved and all(cpus == {1, 2, 3} for _tid, cpus in moved)
    clock[0] = 12.0
    assert not pinned.keep(), "nothing changed: nothing moved"
    assert W.pin_process(7, {1}, tasks=[7, 8], setter=lambda tid, cpus: None) == 2


def test_a_split_is_read_as_group_equals_share_and_refused_otherwise():
    assert W.split_of("A=1, B=1") == {"A": 1.0, "B": 1.0} and W.split_of("") == {}
    for wrong in ("A", "A=x", "=1"):
        with pytest.raises(ValueError):
            W.split_of(wrong)


def test_a_cpu_that_shares_its_core_says_with_which(tmp_path):
    for cpu, mates in ((0, "0,2"), (1, "1,3")):
        topology = tmp_path / f"cpu{cpu}" / "topology"
        topology.mkdir(parents=True)
        (topology / "thread_siblings_list").write_text(mates + "\n")
    assert W.siblings({0, 1, 5}, sysfs=str(tmp_path)) == {0: [2], 1: [3]}


def test_the_manager_sets_the_workload_and_refuses_what_cannot_be(monkeypatch):
    from graph_scale_dynamics.services.api import campaign_manager as CM

    class _Repo(_Flags):
        def emit(self, *_a):
            pass

    repo = _Repo()
    monkeypatch.setattr(CM, "_mark_stale", lambda: None)
    monkeypatch.setattr(W, "os_cpus", lambda: set(range(4)))
    found, status = CM.handle(repo, {"action": "workload", "split": "A=1,B=1", "system_cpus": "0"})
    assert status == 200 and found["shares"] == {"A": 0.5, "B": 0.5} and found["system_cpus"] == [0]
    assert found["work_cpus"] == [1, 2, 3]
    found, status = CM.handle(repo, {"action": "workload", "system_cpus": "0-3"})
    assert status == 400 and "every CPU" in found["error"] and found["system_cpus"] == [0]


def test_the_dex_laws_read_again_count_with_the_laws_coming_in_never_with_the_zone():
    dex = dict(_row("11", "N", 6, 50), design_kind="seed")
    rows = [_row("1", "A", 1, 5), dex, _row("13", "N", 3, 40)]
    assert W.group_of(dex) == W.BLIND and W.group_of(rows[2]) == W.NEIGHBOURS
    assert {r["campaign_id"] for r in W.in_shares(rows, {"A": 0.1, "N": 0.9})} == {"13"}, (
        "the zone owes 9.9 of 11 and holds 3: its own campaign takes the next worker, not the Dex laws")


def _focus_row(campaign, kind, part, leased, queued, behind=0, target=None):
    return {"campaign_id": campaign, "work_group": "N", "design_kind": kind, "focus_part": part, "leased": leased,
            "queued": queued, "behind": behind, "workers_target": target}


def test_a_folder_with_a_focus_takes_its_work_in_one_order_the_depth_worker_on_a_slot_of_its_own():
    from graph_scale_dynamics.services.worker.main import offers
    rows = [_focus_row("1", "blind", None, 2, 900), _focus_row("11", "seed", None, 5, 40),
            _focus_row("12", "focus", "N", 8, 30, behind=20), _focus_row("13", "focus", "S", 0, 0),
            _focus_row("14", "focus", "D", 0, 2, target=1)]
    found = W.ordered(rows)
    assert [(tier, [r["campaign_id"] for r in got]) for tier, got in found] == [
        (W.ZONE_TIER, ["12"]), (W.DEX_TIER, ["11"]), (W.BLIND_TIER, ["1"]), (W.LEFTOVER_TIER, ["12"])], (
        "the depth worker is never offered to the fleet's slots: it runs on the depth slot above them")
    assert [under for _c, under, _b in offers(rows)] == [W.BEHIND, W.BEHIND, W.BEHIND, W.BEHIND, None, None]
    assert [(c, b) for c, _u, b in offers(rows)][1:3] == [
        (("11",), {"order": W.BY_LAW, "max_n": W.VERIFY_TO}), (("11",), {"order": W.BY_LAW})], (
        "the Dex laws are taken law by law, every law's sizes to N=4,096 before any law's deeper sizes")
    assert offers(rows)[-1][0] == ("1", "11", "12", "13")
    assert W.now_on(rows)["queued"] == {"the zone of the law in focus": 10, "the N-push": 2,
                                        "the Dex laws read again": 40, "the blind draw": 900,
                                        "earlier laws' leftovers": 20}
    rows[2]["queued"] = 20
    assert W.now_on(rows)["name"] == "the Dex laws read again", "the zone's queue holds only earlier laws' runs"
    rows[4]["leased"] = 1
    assert W.now_on(rows)["name"] == "the Dex laws read again"
