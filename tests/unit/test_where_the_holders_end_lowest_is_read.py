from __future__ import annotations

import json

from tools import holders_lowest_energy as H


def _entry(group, apart, fates):
    return {"lowest": None if group is None else {"group": group, "apart": apart},
            "fates": {name: [fate, 1.0] for name, fate in fates.items()}, "at_n": 65536}


def test_the_lowest_end_is_placed_against_the_held_lattices():
    fates = {"cubic": "holds", "tesseract": "unmoved", "honeycomb": "melted"}
    assert H.where_lowest(_entry(["cubic"], True, fates))[0] == H.ALONE
    assert H.where_lowest(_entry(["cubic"], False, fates))[0] == H.NOT_APART
    assert H.where_lowest(_entry(["cubic", "random"], True, fates))[0] == H.AMONG
    assert H.where_lowest(_entry(["random"], True, fates))[0] == H.ELSEWHERE
    assert H.where_lowest(_entry(["honeycomb"], True, fates))[0] == H.ELSEWHERE
    assert H.where_lowest(_entry(None, None, fates))[0] == H.UNREAD


def test_another_start_lower_within_the_margin_is_a_near_tie_not_a_win():
    fates = {"cubic": "holds", "tesseract": "melted"}
    assert H.where_lowest(_entry(["random"], True, fates))[0] == H.ELSEWHERE
    assert H.where_lowest(_entry(["random"], False, fates))[0] == H.ELSEWHERE_NOT_APART
    assert H.where_lowest(_entry(["empty", "random"], None, fates))[0] == H.ELSEWHERE_NOT_APART
    assert H.ELSEWHERE_NOT_APART in H.WORDS and len(set(H.WORDS)) == len(H.WORDS)


def test_a_law_that_converts_is_read_as_a_holder(tmp_path):
    folder = tmp_path / "campaign_1_reports_x"
    folder.mkdir()
    laws = {"a" * 64: _entry(["empty"], False, {"cubic": "holds", "honeycomb": "melted"}),
            "b" * 64: _entry(["empty"], True, {"cubic": "holds"}),
            "c" * 64: _entry(["cubic"], True, {"cubic": "holds", "tesseract": "melted"})}
    body = {"every_chain": {"laws": {law: {"starts_reading": entry} for law, entry in laws.items()}}}
    (folder / "28-decision-engine.json").write_text(json.dumps({"body": body}), encoding="utf-8")
    laws_file = tmp_path / "laws.json"
    laws_file.write_text(json.dumps({"laws": {"a" * 64: {"class": "converts"}, "b" * 64: {"class": "holds"},
                                              "c" * 64: {"class": "converts"}, "d" * 64: {"class": "remembers"}}}))
    out = tmp_path / "out.json"
    assert H.main([str(tmp_path), "--laws", str(laws_file), "--json", str(out), "--md", str(tmp_path / "out.md")]) == 0
    result = json.loads(out.read_text())
    assert result["holders"] == 3 and result["read"] == 3, "converts is a holder; remembers is not"
    assert result["where"][H.ELSEWHERE] == 1 and result["where"][H.ELSEWHERE_NOT_APART] == 1
    assert result["where"][H.ALONE] == 1
    assert result["by_class"]["converts"] == {H.ELSEWHERE_NOT_APART: 1, H.ALONE: 1}
    assert result["elsewhere_not_apart_by_group"] == {"empty": 1} and result["elsewhere_by_group"] == {"empty": 1}
    assert "Not apart: empty 1." in (tmp_path / "out.md").read_text()


def test_a_bundle_s_holders_are_counted_from_every_survey_campaign(tmp_path):
    for number, laws in ((1, {"a" * 64: _entry(["empty"], True, {"cubic": "holds"})}),
                         (2, {"b" * 64: _entry(["tesseract"], True, {"tesseract": "holds"})}),
                         (6, {"c" * 64: _entry(["empty"], True, {"cubic": "holds"})})):
        folder = tmp_path / f"campaign_{number}_reports_x"
        folder.mkdir()
        body = {"every_chain": {"laws": {law: {"starts_reading": entry} for law, entry in laws.items()}}}
        (folder / "28-decision-engine.json").write_text(json.dumps({"body": body}), encoding="utf-8")
    holders = {"a" * 64: {"class": "holds"}, "b" * 64: {"class": "selects"}, "d" * 64: {"class": "holds"}}
    result = H.read(tmp_path, holders)
    assert result["read"] == 2 and result["not_in_report_28"] == ["d" * 12]
    assert result["where"][H.ELSEWHERE] == 1 and result["where"][H.ALONE] == 1
    assert result["elsewhere_by_group"] == {"empty": 1}
    assert "| holds |" in H.markdown(result, "test")
