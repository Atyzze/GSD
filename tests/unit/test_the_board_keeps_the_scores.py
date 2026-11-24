from __future__ import annotations

from graph_scale_dynamics.observability import law_score as L
from graph_scale_dynamics.observability import score_board as B


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, laws):
        self.laws = sorted(laws)

    def execute(self, sql, params):
        campaign, floor, after, limit = params
        assert "FROM measurements" in sql and floor == 1024
        return _Rows([{"candidate_id": law} for law in self.laws if law > after][:limit])


class _Repo:
    def __init__(self, laws=()):
        self.flags = {}
        self.conn = _Conn(laws)

    def get_flag(self, key, default=""):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value


def scored(value, to_n=65536, by="lattice"):
    return {"score": value, "by": by if value else None, "chain": "honeycomb" if value else None,
            "to_n": to_n if value else None, "top_n": to_n}


def test_a_decision_s_score_is_kept_and_a_zero_ahead_of_the_scan_reads_as_zero():
    repo = _Repo()
    B.keep(repo, "1", {"b": scored(17), "c": scored(0)})
    board = B.board(repo, "1")
    assert board["scores"] == {"b": scored(17)} and board["zeros"] == ["c"]
    assert B.of(board, "b") == scored(17) and B.of(board, "c") == L.zero()
    assert B.of(board, "d") is None, "neither scanned nor decided since 608: not scored yet"
    B.keep(repo, "1", {"b": scored(0)})
    assert B.of(B.board(repo, "1"), "b") == L.zero() and "b" not in B.board(repo, "1")["scores"]


def test_the_scan_reads_a_page_at_a_time_in_id_order_and_ends_complete():
    laws = [f"law{i:02d}" for i in range(7)]
    repo, asked = _Repo(laws), []
    score_of = lambda law: asked.append(law) or scored(13 if law == "law03" else 0)  # noqa: E731
    B._LAST_SCAN.clear()
    assert B.scan(repo, "1", score_of, now=0.0, limit=3) == 3
    assert asked == ["law00", "law01", "law02"] and B.board(repo, "1")["after"] == "law02"
    assert B.scan(repo, "1", score_of, now=1.0, limit=3) == 0, "not again inside its interval"
    assert B.scan(repo, "1", score_of, now=100.0, limit=3) == 3
    assert B.board(repo, "1")["scores"] == {"law03": scored(13)}
    assert B.scan(repo, "1", score_of, now=200.0, limit=3) == 1
    board = B.board(repo, "1")
    assert board["complete"] and B.of(board, "law99") == L.zero(), "every law read: one not listed scores 0"
    assert B.scan(repo, "1", score_of, now=300.0, limit=3) == 0 and len(asked) == 7


def test_another_score_contract_starts_the_board_again():
    repo = _Repo()
    B.keep(repo, "1", {"b": scored(17)})
    stored = B.load(repo, "1")
    stored["score_contract"] = "gsd-law-score-0"
    B._save(repo, "1", stored)
    assert B.board(repo, "1")["scores"] == {} and not B.board(repo, "1")["complete"]


def _store(monkeypatch, every_chain: bool):
    import importlib.util
    from pathlib import Path

    from graph_scale_dynamics.db.decision_store import DecisionStore
    from graph_scale_dynamics.observability import two_chains

    spec_path = Path(__file__).with_name("test_the_score_reads_every_start.py")
    spec = importlib.util.spec_from_file_location("score_fixtures", spec_path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    chains = fixtures.law(lambda n: (fixtures.plane(n), fixtures.random_graph(n), *fixtures.lattices_melted(n)))
    monkeypatch.setattr(two_chains, "chains_per_rung", lambda rows, starts=None: chains)

    class Repo:
        def measurements(self, law, version, campaign_id):
            return [{"n": 65536}]

    campaign = {"campaign_id": "1", "spec": {"engine": {"policy": {"every_chain": True}}} if every_chain else {}}
    return DecisionStore(Repo(), None, campaign)


def test_a_decision_keeps_its_law_s_score_for_the_board_and_never_in_its_facts(monkeypatch):
    store = _store(monkeypatch, every_chain=True)
    facts = store.law_starts_reading("1", "law")
    assert set(facts) == {"starts_reading"} and "score" not in facts["starts_reading"], "the decision records no score"
    assert store.scored["law"]["score"] == 57 and store.scored["law"]["by"] == "empty"


def test_a_campaign_not_decided_chain_by_chain_keeps_the_score_too(monkeypatch):
    store = _store(monkeypatch, every_chain=False)
    assert store.law_starts_reading("1", "law") == {}
    assert store.scored["law"]["score"] == 57


def test_a_score_that_cannot_be_read_never_stops_a_decision(monkeypatch):
    store = _store(monkeypatch, every_chain=False)
    store.scored["law"] = scored(17)

    def broken(*args, **kwargs):
        raise ValueError("no chains")
    monkeypatch.setattr(L, "score", broken)
    assert store.law_starts_reading("1", "law") == {}
    assert "law" not in store.scored, "an old score is not left standing for a law read again"
