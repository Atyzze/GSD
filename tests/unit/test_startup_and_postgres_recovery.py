from __future__ import annotations

import inspect
from types import SimpleNamespace

import main
from graph_scale_dynamics.db.connection import _qmark_to_format
from graph_scale_dynamics.db.repo import Repo
from graph_scale_dynamics.scheduling.provenance import (
    CAMPAIGN_PROVENANCE_CONTRACT, experiment_config_hash, freeze_campaign_spec, policy_hashes,
)


class _RunRepo:
    def __init__(self, *, home="", campaigns=None, active=None, links=None):
        self.home = home
        self.campaigns = campaigns or {}
        self.active = active or []
        self.links = links or {}

    def get_flag(self, key, default=""):
        assert key == "home_campaign"
        return self.home or default

    def campaign(self, campaign_id):
        return self.campaigns.get(campaign_id)

    def active_campaigns(self):
        return list(self.active)

    def campaign_link(self, campaign_id):
        return self.links.get(campaign_id)


def _continuous(campaign_id: str) -> dict:
    spec = freeze_campaign_spec({
        "mode": "continuous", "ladder": [256],
        "analysis_version": main.ANALYSIS_VERSION,
        "search_space_version": main.SEARCH_SPACE_VERSION,
        "policy": {"rule_version": main.POLICY_RULE_VERSION},
        "engine": {"contract": "decision-engine-2"},
    })
    seed = 17
    hashes = policy_hashes(spec)
    return {
        "campaign_id": campaign_id, "status": "active", "spec": spec,
        "provenance_contract": CAMPAIGN_PROVENANCE_CONTRACT, "search_seed": seed,
        "experiment_config_hash": experiment_config_hash(spec, seed), **hashes,
    }


def test_default_run_resumes_home_campaign_without_reading_default_spec(monkeypatch):
    stored = _continuous("camp-old")
    repo = _RunRepo(home="camp-old", campaigns={"camp-old": stored})
    monkeypatch.setattr(main, "read_spec_file", lambda value: (_ for _ in ()).throw(
        AssertionError(f"unexpected spec read: {value}")
    ))

    selected = main._resolve_run_target(
        SimpleNamespace(campaign=None, spec=None), repo
    )

    assert selected == ("camp-old", stored["spec"])


def test_default_run_uses_sole_active_primary_when_home_is_missing(monkeypatch):
    stored = _continuous("camp-only")
    repo = _RunRepo(active=[stored])
    monkeypatch.setattr(main, "read_spec_file", lambda value: (_ for _ in ()).throw(
        AssertionError(f"unexpected spec read: {value}")
    ))

    selected = main._resolve_run_target(
        SimpleNamespace(campaign=None, spec=None), repo
    )

    assert selected == ("camp-only", stored["spec"])


def test_default_run_resolves_between_campaigns_the_way_the_page_does():
    older = _continuous("camp-a") | {"created_utc": "2026-09-01T00:00:00Z"}
    newer = _continuous("camp-b") | {"created_utc": "2026-09-02T00:00:00Z"}
    repo = _RunRepo(active=[older, newer], campaigns={"camp-a": older, "camp-b": newer})

    assert main._resolve_run_target(
        SimpleNamespace(campaign=None, spec=None), repo
    ) == ("camp-b", newer["spec"])


def test_explicit_spec_is_the_only_implicit_new_campaign_path(monkeypatch):
    expected = {"mode": "continuous", "ladder": [256]}
    monkeypatch.setattr(main, "read_spec_file", lambda value: expected)

    selected = main._resolve_run_target(
        SimpleNamespace(campaign=None, spec="custom.json"), _RunRepo()
    )

    assert selected == (None, expected)


def test_reclaim_expired_uses_postgres_typed_null_safe_comparisons():
    translated = _qmark_to_format(
        "lease_owner IS NOT DISTINCT FROM ?::text AND claim_token IS NOT DISTINCT FROM ?::text"
    )
    assert translated == (
        "lease_owner IS NOT DISTINCT FROM %s::text "
        "AND claim_token IS NOT DISTINCT FROM %s::text"
    )


def test_closed_home_campaign_is_cleared_before_startup_selects_another(monkeypatch):
    closed = _continuous("camp-old") | {"status": "closed"}
    active = _continuous("camp-new")
    repo = _RunRepo(home="camp-old", campaigns={"camp-old": closed}, active=[active])
    repo.flags = {}
    repo.set_flag = lambda key, value: repo.flags.__setitem__(key, value)
    monkeypatch.setattr(main, "read_spec_file", lambda value: (_ for _ in ()).throw(
        AssertionError(f"unexpected spec read: {value}")
    ))

    selected = main._resolve_run_target(SimpleNamespace(campaign=None, spec=None), repo)

    assert repo.flags == {"home_campaign": ""}
    assert selected == ("camp-new", active["spec"])


def test_reclaim_expired_is_bounded_and_skip_locked():
    assert inspect.signature(Repo.reclaim_expired).parameters["batch_size"].default == 200


def test_default_run_refuses_legacy_scientific_contract():
    stored = _continuous("camp-old")
    stored["spec"]["analysis_version"] = "analysis-2.5.0"
    repo = _RunRepo(home="camp-old", campaigns={"camp-old": stored})
    assert main._resolve_run_target(SimpleNamespace(campaign=None, spec=None), repo) is None


def test_an_active_campaign_of_another_policy_contract_is_detected():
    current = _continuous("camp-new")
    legacy = _continuous("camp-old")
    legacy["spec"]["policy"]["rule_version"] = "policy-contract-6"
    repo = _RunRepo(active=[current, legacy])
    incompatible = main._incompatible_active_campaigns(repo, excluding="camp-new")
    assert [row["campaign_id"] for row in incompatible] == ["camp-old"]


def test_default_run_refuses_legacy_search_space_contract():
    stored = _continuous("camp-old")
    stored["spec"]["search_space_version"] = "hamiltonian-search-1"
    repo = _RunRepo(home="camp-old", campaigns={"camp-old": stored})
    assert main._resolve_run_target(SimpleNamespace(campaign=None, spec=None), repo) is None
