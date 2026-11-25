from __future__ import annotations

import json
import time

import pytest

pytestmark = pytest.mark.usefixtures("isolated_postgres_schema")


class _Log:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _law(name: str) -> str:
    return f"law-run-on-{name}".ljust(64, "0")


def _decide(repo, campaign, law, *, rule, n, action="stop", next_n=None):
    repo.conn.execute(
        "INSERT INTO engine_decisions(campaign_id,decision_id,candidate_id,at_n,next_n,action,rule,reason,"
        "priority,queue_order,jobs_created,rows_changed,released_hold,jobs_seen,engine,facts_json,created_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (campaign, f"{time.time_ns():020d}-{law[-6:]}", law, n, next_n, action, rule, f"{rule} at {n}", None, None,
         0, 1, False, "3:mark", "decision-engine-2", "{}", "2026-11-25T09:00:00Z"))


@pytest.fixture
def world(isolated_postgres_schema, tmp_path):
    from graph_scale_dynamics.db.repo import Repo, init_db
    init_db(isolated_postgres_schema.dsn)
    repo = Repo(isolated_postgres_schema.dsn)
    campaign = str(repo.create_campaign({"name": "run on", "study_design": {"study": "1", "kind": "blind"}},
                                        search_seed=7)["campaign_id"])
    laws = {name: _law(name) for name in ("held", "moved_on", "nothing", "absent", "elsewhere")}
    rows = [{"campaign": campaign, "law": laws[name], "number": i, "class": cls}
            for i, (name, cls) in enumerate((("held", "a line or a ring"), ("moved_on", "d 1.3 to 2.5"),
                                            ("nothing", "nothing read"), ("absent", "a line or a ring")))]
    listing = {"contract": "gsd-held-by-a-gate-1", "study": "1", "gate": "starts_alike", "at_n": 16384,
               "held": 4, "classes": {}, "bundle": {"name": "study_1_x"}, "laws": rows}
    readings = tmp_path / "graph_scale_dynamics" / "resources" / "readings"
    readings.mkdir(parents=True)
    (readings / "study_1_run_on.json").write_text(json.dumps(listing), encoding="utf-8")
    for name in ("held", "moved_on", "nothing"):
        repo.insert_candidate(laws[name], campaign, {"terms": []}, "equilibrium", 1, "PARKED")
    _decide(repo, campaign, laws["held"], rule="starts_alike", n=16384)
    _decide(repo, campaign, laws["nothing"], rule="starts_alike", n=16384)
    _decide(repo, campaign, laws["moved_on"], rule="starts_alike", n=4096)
    yield repo, campaign, laws, tmp_path
    repo.close()


def test_the_page_s_action_names_the_listed_laws_that_read_something_and_are_in_this_folder(world):
    from graph_scale_dynamics.decisions import by_word
    from graph_scale_dynamics.operations import focus
    repo, campaign, laws, tree = world
    done = focus.act(repo, {"do": "run_on", "study": "1"}, tree=tree)
    assert done["run_on"]["named"] == 2 and done["run_on"]["missing"] == [f"{campaign}:{laws['absent'][:12]}"]
    entries = by_word.entries_of(repo.get_flag(by_word.FLAG, ""), campaign)
    assert sorted(entries) == sorted([laws["held"], laws["moved_on"]]), "a law that read nothing is not named"
    assert entries[laws["held"]]["gate"] == "starts_alike" and entries[laws["held"]]["at_n"] == 16384


def test_the_store_offers_a_named_law_only_while_its_gate_still_holds_it_there(world):
    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.decisions import by_word
    from graph_scale_dynamics.operations import focus, run_on
    repo, campaign, laws, tree = world
    focus.act(repo, {"do": "run_on", "study": "1"}, tree=tree)
    store = DecisionStore(repo, _Log(), {"campaign_id": campaign, "spec": {}})
    assert list(store.run_on_laws(campaign)) == [laws["held"]], "a law held at another size is not run on"
    assert run_on.reading(repo)["stages"] == {"waiting": 2}
    _decide(repo, campaign, laws["held"], rule=by_word.RULE, n=16384, action="run_next", next_n=65536)
    repo.conn.execute("UPDATE campaign_candidates SET state='EXTENDING' WHERE candidate_id=?", (laws["held"],))
    assert store.run_on_laws(campaign) == {}, "a law run on is not offered again"
    assert run_on.reading(repo)["stages"] == {"running on": 1, "waiting": 1}
    focus.act(repo, {"do": "run_on", "clear": True}, tree=tree)
    assert run_on.reading(repo) is None and store.run_on_laws(campaign) == {}


def test_the_page_says_what_each_study_s_list_holds(world):
    from graph_scale_dynamics.operations import run_on
    _repo, _campaign, _laws, tree = world
    found = run_on.lists([{"study": "1", "campaigns": 1}, {"study": "2", "campaigns": 1}], tree)
    assert [(f["study"], f["held"], f["run_on"], f["gate"], f["at_n"]) for f in found] == [
        ("1", 4, 3, "starts_alike", 16384)]
