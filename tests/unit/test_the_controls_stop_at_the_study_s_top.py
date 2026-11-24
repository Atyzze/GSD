from __future__ import annotations

from graph_scale_dynamics.operations import standing_controls as SC

CRITERION = SC.load_criterion()


class _Repo:
    def __init__(self, specs):
        self.specs = specs

    def all_campaigns(self):
        return [{"campaign_id": str(i), "spec": spec} for i, spec in enumerate(self.specs, start=1)]


def test_the_study_s_top_is_its_own_campaigns_ladder_not_the_controls():
    study = {"name": "study 254: blind", "ladder": [64, 256, 1024, 4096, 16384, 65536]}
    controls = {"name": SC.NAME, "controls_criterion": "x", "ladder": CRITERION["rungs"]}
    assert SC.study_top(_Repo([study, controls])) == 65536
    assert SC.study_top(_Repo([controls])) is None


def test_the_rungs_are_cut_at_the_top_and_the_criterion_is_otherwise_the_same():
    cut = SC.capped(CRITERION, 65536)
    assert cut["rungs"] == [64, 256, 1024, 4096, 16384, 65536] and cut["capped_at"] == 65536
    assert cut["laws"] == CRITERION["laws"] and cut["contract"] == CRITERION["contract"]
    assert SC.capped(CRITERION, 4194304) is CRITERION, "a survey to 4,194,304 runs the full ladder, as before"
    assert SC.capped(CRITERION, None) is CRITERION
    spec = SC.campaign_spec(cut)
    assert max(spec["ladder"]) == 65536 and spec["controls_capped_at"] == 65536 and "N=65,536" in spec["description"]
