from __future__ import annotations

from graph_scale_dynamics.operations import study


def test_the_note_names_the_study_the_default_and_the_way_to_start_another(tmp_path):
    tree = tmp_path / "256" / "main"
    (tree / "graph_scale_dynamics" / "resources" / "readings").mkdir(parents=True)
    note = study.default_study_note(tree)
    assert note.startswith("study default: no --study given, so the default study")
    assert "256" not in note, "the folder's name says nothing"
    assert "cap of 16 or 32" in note and "10,000 laws each" in note
    assert "main.py run --spec <file>" in note and "campaign_engine_survey.json" in note
    assert "main.py run --study <id>" in note and "this tree holds none" in note
    shipped = study.default_study_note()
    assert "this tree holds designs 169, 170, 171" in shipped and "growth plans" not in shipped, (
        "the designs in the tree are study 169's (813), study 170's (820) and study 171's (827)")
