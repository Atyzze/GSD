from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

from graph_scale_dynamics.dsl import dsl
from graph_scale_dynamics.dsl.dsl import fingerprint
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import standing_controls
from graph_scale_dynamics.operations import study_design as SD
from graph_scale_dynamics.research import control_verdict as CV
from graph_scale_dynamics.research import strata as S
from graph_scale_dynamics.research.hamiltonian_preflight import ZERO_TEMPERATURE_FOLDED, equilibrium_identity
from graph_scale_dynamics.services.proposer import blind

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "graph_scale_dynamics" / "resources" / "readings"


def _spec(index: int = 0) -> dict:
    from tests.support import designs
    design = dict(designs.of_four_starts(), strata=designs.STRATA)
    return SD.campaign_spec(design, control.shipped_spec(), design["campaigns"][index], index)


def _load(path: Path) -> dict:
    from graph_scale_dynamics.resources import committed
    return committed.read(path)


def _batch(spec: dict, count: int, seed: int) -> list[dict]:
    return blind.blind_batch(random.Random(0), count, spec["operator_whitelist"], spec["search_policy"]["grid"],
                             set(), set(), fingerprint=dsl.fingerprint,
                             physical_identity=lambda law: equilibrium_identity(law, version=ZERO_TEMPERATURE_FOLDED)[0],
                             complexity_budget=spec["complexity_budget"], streams=lambda i: blind.law_stream(seed, i))


def test_a_batch_draws_by_the_allocation():
    spec = _spec(0)
    allocation = S.allocation_of(spec["search_policy"]["grid"])
    laws = _batch(spec, 80, 161)
    assert [S.stratum_of(law) for law in laws] == [
        S.draw_stratum(blind.law_stream(161, i), allocation) for i in range(len(laws))]
    held = Counter(S.stratum_of(law) for law in laws)
    assert held["zeroT/sees more/3-4 terms"] > 0.3 * len(laws), "the allocation, not the measure, decides"


def test_a_criterion_of_several_campaigns_gives_each_campaign_its_own_part():
    from tests.support import criteria
    several = criteria.of_two_campaigns()
    name = "campaign-standing-controls"
    made_from = _load(INPUTS / "controls_criterion_2.json")
    part = CV.for_campaign(several, name)
    assert part["campaign"] == name and part["rungs"] == made_from["rungs"] and "campaigns" not in part
    assert part["contract"] == criteria.CONTRACT and part["words"] == made_from["words"]
    assert [fingerprint(law["spec"]) for law in part["laws"]] == [fingerprint(law["spec"]) for law in made_from["laws"]]
    moved = {law["label"] for law, was in zip(part["laws"], made_from["laws"], strict=True)
             if law["expect"] != was["expect"]}
    assert moved == {"P1"}
    assert len(CV.for_campaign(several, "campaign-cooling-controls")["laws"]) == 2
    assert CV.for_campaign(several, "campaign-growth-controls") is None
    assert CV.for_campaign(made_from, name) is made_from and CV.for_campaign(made_from, "campaign-growth-controls") is None


def test_a_law_judged_to_a_size_is_not_judged_above_it():
    from tests.support import criteria
    part = CV.for_campaign(criteria.of_two_campaigns(), "campaign-standing-controls")
    p1 = next(law for law in part["laws"] if law["label"] == "P1")
    readings_ = {n: {probe: {"mean": 2.0} for probe in CV.PROBES} for n in (4096, 16384)}
    readings_[262144] = {probe: {"mean": 3.97 if probe == "d_V" else 2.0} for probe in CV.PROBES}
    assert CV.judge_probes(p1["expect"]["given_probes"], readings_)[0] == "pass"
    two = next(law for law in _load(INPUTS / "controls_criterion_2.json")["laws"] if law["label"] == "P1")
    assert CV.judge_probes(two["expect"]["given_probes"], readings_)[0] == "fail", "criterion 2 judges the top two"


def test_a_control_campaign_records_the_criterion_its_study_s_design_names(tmp_path, monkeypatch):
    var = tmp_path / "var"
    var.mkdir()
    from graph_scale_dynamics.operations import study_record
    from tests.support import criteria
    readings = tmp_path / "readings"
    readings.mkdir()
    criteria.written(readings)
    monkeypatch.setattr(CV, "READINGS", readings)
    designed = {"261": {"study": "261", "controls_criterion": criteria.NAME}}
    monkeypatch.setattr(SD, "design_for", lambda tree, study: designed.get(str(study)))
    assert standing_controls.judged_in_the_study(var, "campaign-standing-controls") is None, "no record"
    study_record.write(var, study="261", kind=study_record.DESIGNED, chosen_by="test", log=lambda *_: None)
    assert standing_controls.judged_in_the_study(var, "campaign-standing-controls") == criteria.NAME
    assert standing_controls.judged_in_the_study(var, "campaign-growth-controls") is None
    other = tmp_path / "other"
    other.mkdir()
    study_record.write(other, study="262", kind=study_record.DESIGNED, chosen_by="test", log=lambda *_: None)
    assert standing_controls.judged_in_the_study(other, "campaign-standing-controls") is None, "no design in the tree"


def test_the_page_judges_a_stamped_campaign_by_the_criterion_it_was_stamped_with(monkeypatch, tmp_path):
    from tests.support import criteria
    criteria.written(tmp_path)
    monkeypatch.setattr(CV, "READINGS", tmp_path)
    seen = []

    def judge(criterion, *args):
        seen.append(criterion)
        return {"criterion": criterion["contract"]}

    class Repo:
        def measurements(self, *args):
            return []

    monkeypatch.setattr(CV, "judge", judge)
    stamped = {"campaign_id": "7", "spec": {"name": "campaign-standing-controls",
                                            "controls_judged_by": criteria.NAME}}
    assert CV.campaign_verdict(Repo(), stamped)["criterion"] == criteria.CONTRACT
    assert seen[-1]["campaign"] == "campaign-standing-controls"
    plain = {"campaign_id": "7", "spec": {"name": "campaign-standing-controls"}}
    assert CV.campaign_verdict(Repo(), plain)["criterion"] == "gsd-controls-criterion-2"
