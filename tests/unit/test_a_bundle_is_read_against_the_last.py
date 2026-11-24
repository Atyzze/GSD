from __future__ import annotations

import json
import sys
from pathlib import Path

from graph_scale_dynamics.decisions import starts_rule as FS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import starts_bundle as FB  # noqa: E402

NAMES = ["empty", "random", "honeycomb", "cubic", "tesseract"]


def _first(classes: dict) -> dict:
    read = [n for n in sorted(classes) if classes[n] != "not_read"]
    top = sorted(classes)[-1]
    label = classes[top] if classes[top] != "not_read" or not read else "not_read"
    return {"campaign": "1", "class": label, "at_n": top if label != "not_read" else None,
            "by_n": {str(n): c for n, c in classes.items()}, "fates": {}, "decision": ["stop", "no_reading", top]}


def test_a_later_reading_is_set_against_the_first_at_the_size_both_read():
    first = {"apart": _first({1024: "remembers", 4096: "remembers"}), "alike": _first({1024: "forgets"}),
             "gone": _first({1024: "forgets"}), "top_alone": _first({1024: "remembers", 4096: "not_read"})}
    second = {"apart": _first({1024: "remembers", 4096: "forgets"}), "alike": _first({1024: "forgets",
                                                                                       4096: "selects"}),
              "top_alone": _first({1024: "forgets", 4096: "remembers"}), "new": _first({1024: "forgets"})}
    found = FB.against(first, second)
    assert (found["laws_in_both"], found["only_in_the_first"], found["only_in_the_second"]) == (3, 1, 1)
    assert found["read_at_a_common_size"] == 3 and found["same_class_at_the_same_size"] == 1
    assert found["at_the_same_size"] == {"forgets": {"forgets": 1}, "remembers": {"forgets": 2}}, (
        "apart at 4,096 then alike there now; the law the first read only below its top compared at 1,024")
    assert found["apart_then_alike_now"] == 2 and found["alike_then_apart_now"] == 0
    assert found["then_and_now"] == {"forgets": {"selects": 1}, "not_read": {"remembers": 1},
                                     "remembers": {"forgets": 1}}


def _five(classes: dict, fates=None) -> dict:
    sizes = sorted(classes)
    return {"class": classes[sizes[-1]], "at_n": sizes[-1], "top_n": sizes[-1], "top_dense": False,
            "by_n": {str(n): [c, [NAMES]] for n, c in classes.items()}, "fates": fates or {}, "references": True}


def _bundle(root: Path, *, decided: dict | None = None) -> Path:
    folder = root / "campaign_1"
    folder.mkdir(parents=True)
    laws = {"law-a": _five({1024: "remembers", 4096: "forgets"}, {"cubic": ["melted", 0.2]}),
            "law-b": _five({1024: "forgets", 4096: "selects"}, {"cubic": ["holds", 0.9]})}
    rows = [{"candidate_id": law, "fate": ["starts_alike", 4096], "admitted_utc": "2026-10-08T01:00:00Z",
             "spec": {"zero_temperature": True, "terms": [["edge", None, 1.0, "one", None]]}} for law in laws]
    every = {"laws": {law: {"top_n": 4096, "starts_reading": five} for law, five in laws.items()},
             "starts_reading": {"contract": "gsd-starts-reading-2"}, **({"starts_decided": decided} if decided else {})}
    engine = {"law_ledger": {"rows": rows}, "every_chain": every,
              "laws": [{"candidate_id": "law-a", "action": "stop", "rule": FS.ALIKE, "at_n": 4096},
                       {"candidate_id": "law-b", "action": "run_next", "rule": FS.SHAPE, "at_n": 4096}]}
    (folder / "28-decision-engine.json").write_text(json.dumps({"body": engine}))
    report_10 = [{"candidate_id": "law-a", "decision_id": "01", "created_utc": "2026-10-08T12:00:00Z", "at_n": 4096,
                  "action": "stop", "rule": "no_reading", "reason": "no reading"},
                 {"candidate_id": "law-a", "decision_id": "02", "created_utc": "2026-10-08T13:00:00Z", "at_n": 4096,
                  "action": "stop", "rule": FS.ALIKE,
                  "reason": "the starts at N=4,096: every start ends alike, no shape held: parked with everything "
                            "it measured kept (d_s's rule: no_reading)"}]
    (folder / "10-decisions.json").write_text(json.dumps({"body": {"decisions": report_10}}))
    control = root / "campaign_2"
    control.mkdir()
    (control / "28-decision-engine.json").write_text(json.dumps({"body": {"law_ledger": {"rows": []}}}))
    (root / "study.json").write_text(json.dumps({"study": "255", "campaigns": [
        {"campaign_id": "1", "name": "blind (1 of 1)", "bundle": folder.name, "law_budget": 2, "laws_held": 2},
        {"campaign_id": "2", "name": "campaign-standing-controls", "bundle": control.name}]}))
    return root


def test_the_tool_writes_every_law_s_classes_and_reads_a_bundle_against_them(tmp_path):
    bundle = _bundle(tmp_path / "bundle")
    laws, page, out = tmp_path / "laws.json", tmp_path / "page.md", tmp_path / "out.json"
    assert FB.main([str(bundle), "--laws", str(laws), "--md", str(page), "--json", str(out)]) == 0
    written = json.loads(laws.read_text())
    assert written["contract"] == FB.LAWS_CONTRACT and written["reading"] == ["gsd-starts-reading-2"]
    assert written["laws"]["law-b"] == {"campaign": "1", "class": "selects", "at_n": 4096,
                                        "by_n": {"1024": "forgets", "4096": "selects"}, "fates": {"cubic": "holds"},
                                        "decision": ["run_next", FS.SHAPE, 4096]}
    assert len(laws.read_text().splitlines()) == 4, "a law to a line"
    assert FB.main([str(bundle), "--against", str(laws), "--json", str(out), "--md", str(page)]) == 0
    found = json.loads(out.read_text())["against"]
    assert (found["laws_in_both"], found["same_class_at_the_same_size"]) == (2, 2), "a bundle against itself"
    assert found["earlier"] == "bundle" and "## Against bundle, law by law" in page.read_text()


def test_what_the_starts_decided_is_report_28_s_count_or_report_10_s_rules(tmp_path):
    before = FB.read(_bundle(tmp_path / "602"))["decided"]
    assert before["from"] == "report 10's rules and reasons" and before["campaigns"] == 1
    assert (before["decisions"], before["at_the_switch"]["laws"]) == (1, 1)
    assert before["against_d_s"] == [{"starts_reading": "parks", "d_s": "parks", "decisions": 1, "laws": 1}]
    from graph_scale_dynamics.reporting import starts_decided as FD
    own = FD.decided({"law-c": [{"decision_id": "01", "at_n": 4096, "action": "run_next", "rule": FS.SHAPE,
                                 "facts": {"starts_reading": {"decided": True, "class": "selects"},
                                           "d_s": {"action": "stop", "rule": "no_reading"}}}]})
    after = FB.read(_bundle(tmp_path / "603", decided=own))["decided"]
    assert after["from"] == "the decisions' facts" and after["climbed_where_d_s_parked"] == ["law-c"]
    page = FB.render(FB.read(_bundle(tmp_path / "603b", decided=own)))
    assert "## What the starts decided" in page and "climbed where it would have parked: 1" in page


def test_every_law_with_a_lattice_that_held_is_named_with_its_temperature(tmp_path):
    bundle = _bundle(tmp_path / "bundle")
    report = bundle / "campaign_1" / "28-decision-engine.json"
    body = json.loads(report.read_text())
    for row in body["body"]["law_ledger"]["rows"]:
        if row["candidate_id"] == "law-b":
            row["spec"].update(zero_temperature=False, beta=13.6123)
    report.write_text(json.dumps(body))
    result = FB.read(bundle)
    held = result["held"]
    assert held["laws_named"] == [{"law": "law-b", "campaign": "1", "class": "selects", "at_n": 4096,
                                   "temperature": 13.6, "terms": ["edge"], "lattices": {"cubic": ["holds", 0.9]},
                                   "reads": {}, "start_reads": {"cubic": None}, "holds_another_dimension": []}], (
        "no chain scored, so no dimension read (606 reads each chain's beside its start's)")
    assert (held["at_a_finite_temperature"], held["from_16384"]) == (1, 0)
    page = FB.render(result)
    assert "Every law with a lattice that held, by name: 1, 1 of them at a finite temperature" in page
    assert "| `law-b` | 1 | selects | 4096 | beta 13.6 | edge | -, - | holds 0.90 |" in page
    assert "| terms | empty, random | cubic |" in page, "a column for each lattice the named laws were given, no other"


def test_a_held_lattice_s_chain_is_read_beside_its_exact_start_at_the_same_sizes(tmp_path):
    from tests.support.calibration_table import skip_if_recalibration_owed
    skip_if_recalibration_owed()
    assert (FB.start_dimension("tesseract", [1024]), FB.start_dimension("tesseract", [1024, 4096, 16384, 65536])) == (
        4, 4), "four dimensions at every size on the host's table of 2026-11-13; the table measured under 5.1 read three"
    assert (FB.start_dimension("cubic", [1024]), FB.start_dimension("honeycomb", [1024]), FB.start_dimension("x", [64])
            ) == (3, 2, None)
    for read, marked in ((5, ["cubic"]), (4, []), (2, [])):
        bundle = _bundle(tmp_path / f"reads_{read}")
        report = bundle / "campaign_1" / "28-decision-engine.json"
        body = json.loads(report.read_text())
        body["body"]["every_chain"]["laws"]["law-b"].update(given="random", chains={
            "empty": {"d": 2, "rungs": [[1024, 3.0, "walk"], [4096, 4.0, "walk"]]},
            "given": {"d": 2, "rungs": [[1024, 3.0, "walk"], [4096, 4.0, "walk"]]},
            "cubic": {"d": read, "rungs": [[1024, 1.0, "agree"], [4096, 2.0, "agree"]]}})
        report.write_text(json.dumps(body))
        named = FB.read(bundle)["held"]["laws_named"]
        assert len(named) == 1 and named[0]["reads"] == {"empty": 2, "random": 2, "cubic": read}
        assert named[0]["start_reads"] == {"cubic": 3} and named[0]["holds_another_dimension"] == marked, read
        page = FB.render(FB.read(bundle))
        assert ("(start 3) *" in page) == bool(marked) and "a fate reads a lattice's reach and degree" in page


def test_a_count_that_failed_in_report_28_is_read_from_report_10(tmp_path, monkeypatch):
    from graph_scale_dynamics.reporting import every_chain_report as ECR
    from graph_scale_dynamics.reporting import starts_decided as FD
    with monkeypatch.context() as patched:
        patched.setattr(FD, "decided", lambda *_args, **_kwargs: 1 / 0)
        section = ECR.every_chain_section({"measurements": [], "engine_decisions": {"law-x": []}})
    assert "error" not in section and section["laws_scored"] == 0, "the section stands"
    assert section["starts_decided"] == {"contract": FD.CONTRACT, "error": "ZeroDivisionError: division by zero"}
    failed = {"contract": FD.CONTRACT, "error": "ValueError: a row the count could not read"}
    result = FB.read(_bundle(tmp_path / "failed", decided=failed))
    decided = result["decided"]
    assert decided["from"] == "report 10's rules and reasons" and decided["decisions"] == 1
    assert decided["failed_in_report_28"] == [{"campaign": "1", "error": failed["error"]}]
    assert "count failed in report 28" in FB.render(result)


def test_the_scores_are_read_where_report_28_carries_them(tmp_path):
    before = FB.read(_bundle(tmp_path / "607"))
    assert before["scores"] is None
    assert "None in this bundle: its report 28 carries no law's score." in FB.render(before)
    bundle = _bundle(tmp_path / "608")
    report = bundle / "campaign_1" / "28-decision-engine.json"
    body = json.loads(report.read_text())
    laws = body["body"]["every_chain"]["laws"]
    laws["law-a"]["score"] = {"score": 0, "by": None, "chain": None, "to_n": None, "top_n": 4096}
    laws["law-b"]["score"] = {"score": 9, "by": "lattice", "chain": "cubic", "to_n": 4096, "top_n": 4096}
    report.write_text(json.dumps(body))
    found = FB.read(bundle)["scores"]
    assert (found["laws"], found["above_zero"], found["by"], found["values"]) == (2, 1, {"lattice": 1}, {"9": 1})
    assert found["top"] == [{"law": "law-b", "campaign": "blind (1 of 1)", "score": 9, "by": "lattice", "chain": "cubic",
                             "to_n": 4096, "top_n": 4096, "temperature": "zero", "terms": ["edge"]}]
    page = FB.render(FB.read(bundle))
    assert "1 of 2 laws score above zero; by who built the geometry: lattice 1; by score: 9 1." in page
    assert "| `law-b` | blind (1 of 1) | 9 | lattice | cubic | 4096 | 4096 | zero | edge |" in page
