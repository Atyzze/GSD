from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.operations import campaign_control
from graph_scale_dynamics.research import strata as S
from graph_scale_dynamics.research.hamiltonian_preflight import equilibrium_identity
from graph_scale_dynamics.services.proposer import blind
from tests.support.proposer_repo import ProposerRepo, top_up_blind

ROOT = Path(__file__).resolve().parents[2]
SURVEY = json.loads((ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
                    .read_text(encoding="utf-8"))
TERM = ["degree_square_sum"]
DISCRETE = dict(json.loads((ROOT / "tests" / "fixtures" / "discrete_grid.json").read_text(encoding="utf-8")),
                term_counts=[1], sampler=blind.SAMPLER_631)
VERSION = blind.identity_version(DISCRETE)


def _identity(law: dict) -> str:
    return equilibrium_identity(law, version=VERSION)[0]


def _spec(grid: dict, whitelist: list[str], **changes) -> dict:
    spec = json.loads(json.dumps(SURVEY))
    spec["search_policy"]["grid"] = grid
    spec["operator_whitelist"] = whitelist
    spec.update(changes)
    return spec


def _space() -> tuple[dict[str, dict], str]:
    rng, counts, laws = random.Random(3), Counter(), {}
    for _ in range(4000):
        law = dsl.normalize(blind.blind_law(rng, TERM, DISCRETE, complexity_budget=SURVEY["complexity_budget"]))
        counts[_identity(law)] += 1
        laws.setdefault(_identity(law), law)
    assert len(laws) == 23, "499's 23 laws"
    return laws, min(counts, key=lambda identity: (counts[identity], identity))


def _holding(laws) -> ProposerRepo:
    repo = ProposerRepo()
    repo.laws.extend((dsl.fingerprint(law), law) for law in laws)
    return repo


def test_one_stream_s_run_of_duplicates_no_longer_ends_the_survey():
    laws, rare = _space()
    held = [law for identity, law in laws.items() if identity != rare]
    stops: list = []
    assert blind.blind_batch(random.Random(0), 1, TERM, DISCRETE, {dsl.fingerprint(law) for law in held},
                             {_identity(law) for law in held}, fingerprint=dsl.fingerprint, physical_identity=_identity,
                             complexity_budget=SURVEY["complexity_budget"], streams=lambda i: blind.law_stream(4, i),
                             first_index=22, survey_duplicates=60, stops=stops) == []
    assert stops == [{"stream_index": 22, "reason": blind.DUPLICATES, "valid": 60, "duplicates": 60,
                      "unfilled": None}], "the stream that ended the survey under the old 60"
    repo = _holding(held)
    added = top_up_blind(repo, _spec(DISCRETE, TERM), 1, search_seed=4)
    assert [_identity(law) for law in added] == [rare], "the stream drew on and found the unheld law"
    assert campaign_control.survey_state(repo, "1") is None
    rows = [row for row in repo.ledger("1") if row["stream_index"] == 22]
    assert sum(row["outcome"].startswith("duplicate") for row in rows) > 60 and rows[-1]["outcome"] == "admitted"


def test_a_space_held_whole_is_surveyed_on_the_draws_actually_made():
    laws, _ = _space()
    repo = _holding(laws.values())
    assert top_up_blind(repo, _spec(DISCRETE, TERM), 9, search_seed=3) == []
    record = campaign_control.survey_state(repo, "1")
    assert record is not None and record["held"] == 23
    rows = repo.ledger("1")
    assert {row["stream_index"] for row in rows} == {23}, "one stream drawn, the first that found nothing"
    duplicates = [row for row in rows if row["outcome"].startswith("duplicate")]
    assert record["rounds"] == len(duplicates) == blind.SURVEY_DUPLICATES != 60 * 9
    assert top_up_blind(repo, _spec(DISCRETE, TERM), 9, search_seed=3) == [] and len(repo.ledger("1")) == len(rows)


def test_a_stream_out_of_valid_draws_is_not_a_surveyed_space(monkeypatch):
    monkeypatch.setattr(blind, "GRID_RETRIES", 1)
    laws, _ = _space()
    repo = _holding(list(laws.values())[:3])
    assert top_up_blind(repo, _spec(DISCRETE, TERM, complexity_budget=0), 4, search_seed=3) == []
    assert repo.ledger("1") and all(row["outcome"].startswith("invalid:") for row in repo.ledger("1"))
    assert campaign_control.survey_state(repo, "1") is None


def test_an_unfillable_stratum_no_longer_pins_the_proposer_to_one_index(monkeypatch):
    monkeypatch.setattr(blind, "STRATUM_DRAWS", 100)
    whitelist = ["edge_count", "degree_square_sum", "triangle_count"]
    unfillable = "finiteT/sees more/3-4 terms"
    grid = dict(SURVEY["search_policy"]["grid"], term_counts=[1, 2, 4],
                strata={"allocation": {unfillable: 1.0, "finiteT/sees more/1-2 terms": 1.0}})
    assert blind.validate_grid(grid) == [] and S.strata_problems(grid, whitelist) == []
    spec = _spec(grid, whitelist)
    split, whole = ProposerRepo(), ProposerRepo()
    top_up_blind(split, spec, 4, search_seed=5)
    top_up_blind(split, spec, 4, search_seed=5)
    top_up_blind(whole, spec, 8, search_seed=5)
    assert len(split.laws) == 8 and split.laws == whole.laws, "eight laws, the same however the top-ups fell"
    admitted = [row["stream_index"] for row in split.ledger("1") if row["outcome"] == "admitted"]
    assert admitted == list(range(8)), "one law a stream, none skipped"
    allocation = S.allocation_of(grid)
    drew = [i for i in range(8) if S.draw_stratum(blind.law_stream(5, i), allocation) == unfillable]
    assert drew, "some of eight streams drew the stratum no law falls in"
    events = [payload for kind, payload in split.events if kind == blind.STRATUM_UNFILLED]
    assert [event["stream_index"] for event in events] == drew
    assert all(event["stratum"] == unfillable and event["valid_draws"] > 100 for event in events)
    assert all(S.stratum_of(split.laws[i][1]) != unfillable for i in drew)
