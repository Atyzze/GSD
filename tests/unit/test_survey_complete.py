from __future__ import annotations

from graph_scale_dynamics.operations import campaign_control as control


class FakeRepo:
    def __init__(self):
        self.flags: dict[str, str] = {}
        self.events: list[tuple[str, dict]] = []

    def set_flag(self, key: str, value: str) -> None:
        self.flags[key] = value

    def get_flag(self, key: str, default: str = "") -> str:
        return self.flags.get(key) or default

    def emit(self, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))


def test_nothing_is_recorded_until_a_draw_comes_back_empty():
    assert control.survey_state(FakeRepo(), "2") is None


def test_the_record_carries_both_numbers_and_what_they_mean():
    repo = FakeRepo()
    record = control.record_survey_complete(repo, "2", held=23, wanted=32, rounds=540)
    assert record["state"] == control.SURVEYED
    assert record["held"] == 23 and record["pool_min"] == 32
    assert "23" in record["reading"] and "32" in record["reading"]
    assert control.survey_state(repo, "2") == record


def test_the_survey_is_on_the_record_and_not_only_on_the_page():
    repo = FakeRepo()
    control.record_survey_complete(repo, "2", held=23, wanted=32, rounds=540)
    kinds = [kind for kind, _ in repo.events]
    assert "campaign_space_surveyed" in kinds
    payload = dict(repo.events[0][1])
    assert payload["campaign_id"] == "2" and payload["held"] == 23


def test_a_draw_that_finds_something_new_reopens_the_space():
    repo = FakeRepo()
    control.record_survey_complete(repo, "2", held=23, wanted=32, rounds=540)
    control.clear_survey(repo, "2")
    assert control.survey_state(repo, "2") is None


def test_one_campaign_being_surveyed_says_nothing_about_another():
    repo = FakeRepo()
    control.record_survey_complete(repo, "2", held=23, wanted=32, rounds=540)
    assert control.survey_state(repo, "1") is None


def test_a_corrupt_record_reads_as_open_rather_than_raising():
    repo = FakeRepo()
    repo.set_flag(f"{control.SURVEYED_PREFIX}2", "not json")
    assert control.survey_state(repo, "2") is None
    repo.set_flag(f"{control.SURVEYED_PREFIX}2", "[1,2,3]")
    assert control.survey_state(repo, "2") is None
