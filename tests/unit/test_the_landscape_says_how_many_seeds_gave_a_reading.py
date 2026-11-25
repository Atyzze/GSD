from __future__ import annotations

from graph_scale_dynamics.services.api import landscape_worker as W


def _rung(n: int, share: float | None, refusals: dict | None = None) -> dict:
    return {"n": n, "summary": {"seeds": 3, "d_w_valid_fraction": share, "probe_refusals": {"d_w": refusals or {}}}}


def test_a_reading_one_seed_of_three_gave_says_so_and_what_every_larger_size_said():
    entry = {"rungs": [_rung(64, 0.0, {"NO_SCALING_WINDOW": 3}), _rung(256, 1 / 3, {"NO_SCALING_WINDOW": 2}),
                       _rung(1024, 0.0, {"NO_SCALING_WINDOW": 3}),
                       _rung(4096, 0.0, {"EXPONENTIAL_GROWTH": 2, "GROWTH_UNDECIDED": 1})]}
    assert W.reading_support(entry, "d_w", 256) == {
        "n": 256, "seeds": 1, "of": 3,
        "refused_above": [[1024, "NO_SCALING_WINDOW"], [4096, "EXPONENTIAL_GROWTH"]]}, \
        "study 174's d_w of 8.6 (f1307c3a2c, 06:26Z): one seed at 256, every seed refused at 1,024 and 4,096"


def test_a_reading_every_seed_gave_at_the_top_has_nothing_above_it():
    entry = {"rungs": [_rung(1024, 2 / 3), _rung(4096, 1.0)]}
    assert W.reading_support(entry, "d_w", 4096) == {"n": 4096, "seeds": 3, "of": 3, "refused_above": []}
    assert W.reading_support(entry, "d_w", 1024)["refused_above"] == [], "a size that read it is not a refusal"
    assert W.reading_support(entry, "d_w", 16384) is None


def test_a_size_with_no_reason_recorded_is_still_a_refusal_named_as_unknown():
    entry = {"rungs": [_rung(256, 1 / 3), {"n": 1024, "summary": {"seeds": 3}}]}
    assert W.reading_support(entry, "d_w", 256)["refused_above"] == [[1024, None]]
