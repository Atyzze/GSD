from __future__ import annotations

import json

import pytest

from graph_scale_dynamics.research.strict_json import sanitize_json
from tests.support.engines import require_rust_engine


class TestSanitizeJsonDeterminism:
    def test_sets_serialize_in_a_canonical_order(self):
        payload = {"members": {"zebra", "apple", "mango", "kiwi", "pear"}}
        first, _ = sanitize_json(payload)
        assert first["members"] == ["apple", "kiwi", "mango", "pear", "zebra"]

    def test_set_order_does_not_depend_on_insertion_order(self):
        a, _ = sanitize_json({"m": {"delta", "alpha", "charlie", "bravo"}})
        b, _ = sanitize_json({"m": {"bravo", "charlie", "alpha", "delta"}})
        assert a == b

    def test_mixed_type_sets_stay_orderable(self):
        cleaned, _ = sanitize_json({"m": {1, "1", 2.5, None, False}})
        assert isinstance(cleaned["m"], list)
        assert len(cleaned["m"]) == 5, cleaned["m"]
        again, _ = sanitize_json({"m": {None, 2.5, "1", False, 1}})
        assert cleaned == again

    def test_stringified_key_collision_is_counted_not_silent(self):
        cleaned, diagnostics = sanitize_json({"k": {1: "int", "1": "str"}})
        assert list(cleaned["k"]) == ["1"]
        assert diagnostics["key_collisions"] == 1
        kinds = {example["kind"] for example in diagnostics["examples"]}
        assert "stringified_key_collision_overwrote_value" in kinds

    def test_clean_payload_reports_no_collisions(self):
        _, diagnostics = sanitize_json({"a": {"b": 1}, "c": [1, 2, 3]})
        assert diagnostics["key_collisions"] == 0


class TestRustEngineIdentity:
    def test_rust_fingerprint_is_content_derived(self):
        require_rust_engine()
        from graph_scale_dynamics.services.worker.engine_registry import available_engines

        fingerprint = available_engines()["rust"]["fingerprint"]
        assert fingerprint.startswith("rs:")
        assert "+" in fingerprint, f"rust fingerprint carries no content digest: {fingerprint}"
        digest = fingerprint.split("+", 1)[1]
        assert len(digest) == 16 and all(c in "0123456789abcdef" for c in digest)

    def test_rust_fingerprint_tracks_the_loaded_binary(self, tmp_path, monkeypatch):
        require_rust_engine()
        import hashlib
        import importlib.machinery
        import sys

        from graph_scale_dynamics.services.worker import engine_registry

        extension = engine_registry.rust_extension_path()
        assert extension is not None and extension.name.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES))
        fingerprint = engine_registry.available_engines()["rust"]["fingerprint"]
        assert fingerprint.endswith("+" + hashlib.sha256(extension.read_bytes()).hexdigest()[:16])
        loaded = next(module for name, module in sys.modules.items()
                      if name.startswith("gsd_engine_rs") and getattr(module, "__file__", "") == str(extension))
        mutated = tmp_path / ("mutated" + importlib.machinery.EXTENSION_SUFFIXES[0])
        mutated.write_bytes(extension.read_bytes() + b"\x00mutated")
        monkeypatch.setattr(loaded, "__file__", str(mutated), raising=False)
        assert engine_registry.available_engines()["rust"]["fingerprint"] != fingerprint, \
            "a different engine binary produced the same fingerprint"

    def test_the_package_shim_is_not_what_is_hashed(self, tmp_path, monkeypatch):
        require_rust_engine()
        import gsd_engine_rs

        from graph_scale_dynamics.services.worker import engine_registry

        before = engine_registry.available_engines()["rust"]["fingerprint"]
        if not str(getattr(gsd_engine_rs, "__file__", "")).endswith("__init__.py"):
            pytest.skip("this install is a bare extension module, not maturin's package layout")
        shim = tmp_path / "__init__.py"
        shim.write_text("# a different shim\n")
        monkeypatch.setattr(gsd_engine_rs, "__file__", str(shim), raising=False)
        assert engine_registry.available_engines()["rust"]["fingerprint"] == before

    def test_rust_source_is_inside_the_science_freeze(self):
        from graph_scale_dynamics.domain.science_identity import frozen_paths

        frozen = frozen_paths()
        assert any(path.startswith("engine_rs/src") and path.endswith(".rs") for path in frozen), (
            "the Rust sampler can move a published number but is not declared science-sensitive"
        )

    def test_python_and_rust_identities_are_symmetric(self):
        require_rust_engine()
        from graph_scale_dynamics.services.worker.engine_registry import available_engines

        engines = available_engines()
        assert engines["python"]["fingerprint"].startswith("py:")
        assert engines["rust"]["fingerprint"].startswith("rs:")
        assert len(engines["python"]["fingerprint"].split(":", 1)[1]) == 16
        assert "+" in engines["rust"]["fingerprint"]


class TestAccessEvidenceFollowsHomeCampaign:
    def test_tick_writes_evidence_into_the_current_home_root(self, tmp_path, monkeypatch):
        from graph_scale_dynamics.services.web import bundle_keeper as bk

        launch_root = tmp_path / "campaign_7"
        switched_root = tmp_path / "campaign_8"
        launch_root.mkdir()
        switched_root.mkdir()

        monkeypatch.setattr(
            "graph_scale_dynamics.operations.report_home.current_root",
            lambda root: switched_root,
        )

        counter = bk.AccessCounter()
        counter.record("/reports/1", None)
        keeper = bk.BundleKeeper(launch_root, counter, log=lambda *_: None)
        keeper.tick()

        assert (switched_root / bk.ACCESS_NAME).exists(), (
            "access evidence was not written into the current home campaign"
        )
        assert not (launch_root / bk.ACCESS_NAME).exists(), (
            "access evidence leaked into the previous campaign root"
        )

    def test_switching_home_does_not_carry_previous_counts(self, tmp_path, monkeypatch):
        from graph_scale_dynamics.services.web import bundle_keeper as bk

        first = tmp_path / "campaign_7"
        second = tmp_path / "campaign_8"
        first.mkdir()
        second.mkdir()

        active = {"root": first}
        monkeypatch.setattr(
            "graph_scale_dynamics.operations.report_home.current_root",
            lambda root: active["root"],
        )

        counter = bk.AccessCounter()
        keeper = bk.BundleKeeper(first, counter, log=lambda *_: None)
        for _ in range(5):
            counter.record("/reports/1", None)
        keeper.tick()
        before = json.loads((first / bk.ACCESS_NAME).read_text())
        assert sum(before["totals"].values()) == 5

        active["root"] = second
        keeper.tick()
        after = json.loads((second / bk.ACCESS_NAME).read_text())
        assert sum(after["totals"].values()) == 0, (
            "the new campaign's evidence inherited the previous campaign's counts"
        )
        assert after["report_root"] == str(second)


class TestPeerSnapshotProjection:
    def test_rung_rows_drop_the_redundant_raw_json(self):
        from graph_scale_dynamics.research.report_pipeline import RUNG_ROWS_SQL
        from graph_scale_dynamics.research.snapshot_rows import parsed_rows

        row = {
            "candidate_id": "cand-1", "n": 256, "summary_json": json.dumps({"d_s": 1.87}),
            "created_utc": "2026-09-08T00:00:00Z",
        }
        conn = type("Conn", (), {"stream": lambda self, sql, args, size: iter([row])})()
        projected = parsed_rows(conn, RUNG_ROWS_SQL, ("c", "v"), "summary_json", "summary")[0]
        assert projected == {"candidate_id": "cand-1", "n": 256, "created_utc": "2026-09-08T00:00:00Z",
                             "summary": {"d_s": 1.87}}
        assert "summary_json" not in projected, (
            "peer rungs carried the summary twice, as a string and as an object"
        )
