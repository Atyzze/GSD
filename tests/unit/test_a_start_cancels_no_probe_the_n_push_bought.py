from graph_scale_dynamics.scheduling.recovery import superseded_analysis_keys

PUSH = {"study_design": {"focus": {"part": "P"}}, "default_seeds": 3}
BLIND = {"study_design": {"kind": "blind"}, "default_seeds": 3}


def _row(campaign: str, seed: int, spec: dict, *, status: str = "queued", multiplier: int = 1) -> dict:
    return {"campaign_id": campaign, "candidate_id": "8addbb0c", "n": 262144, "seed": seed, "status": status,
            "input_artifact": f"art-{campaign}-{seed}-{multiplier}", "analysis_version": "analysis-5.3.0",
            "created_utc": f"2026-11-27T13:{seed:02d}:00Z", "job_created_utc": f"2026-11-27T12:{seed:02d}:00Z",
            "spec": {"execution": {"sweeps_multiplier": multiplier}}, "campaign_spec": spec}


def test_every_seed_the_n_push_bought_at_a_rung_keeps_its_probe():
    assert superseded_analysis_keys([_row("17", seed, PUSH) for seed in range(16)]) == [], (
        "178 at 14:15Z: the start cancelled seeds 8 to 15 of 262,144, the push's own seeds")


def test_a_blind_rung_s_seeds_past_its_ceiling_are_still_cancelled():
    found = superseded_analysis_keys([_row("1", seed, BLIND) for seed in range(16)])
    assert sorted(key[1] for key in found) == sorted(f"art-1-{seed}-1" for seed in range(6, 16))


def test_a_push_seed_s_shorter_run_is_still_superseded_by_its_longer_one():
    rows = [_row("17", 3, PUSH, status="done", multiplier=2), _row("17", 3, PUSH, multiplier=1),
            *(_row("17", seed, PUSH) for seed in range(4, 16))]
    assert superseded_analysis_keys(rows) == [("17", "art-17-3-1", "analysis-5.3.0")]
