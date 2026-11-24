from __future__ import annotations

import pytest

from graph_scale_dynamics.research import document_claims as C


@pytest.fixture(scope="module")
def evaluated():
    return C.evaluate()["claims"]


def test_every_stated_number_is_what_its_committed_reading_gives(evaluated):
    wrong = [(row["claim_id"], row["doc"], row["measured"]) for row in evaluated if not row["holds"]]
    assert not wrong, f"a number the documents state is not what its reading gives; fix the document: {wrong}"


def test_every_claim_is_still_said_where_it_is_held(evaluated):
    gone = [(row["claim_id"], row["doc"], row["quote"]) for row in evaluated if not row["quoted"]]
    assert not gone, ("a held number left its document or was reworded; move the claim with it, so no number is "
                      f"stated without its check: {gone}")


def test_a_reworded_document_is_caught(tmp_path, monkeypatch):
    page = tmp_path / "docs" / "WHERE_WE_ARE.md"
    page.parent.mkdir(parents=True)
    page.write_text("289 laws\nhold one.", encoding="utf-8")
    claim = C.Claim("holders", "docs/WHERE_WE_ARE.md", "289 laws hold one.", lambda: (True, 289))
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "claims", lambda: [claim])
    assert C.evaluate()["claims"][0]["quoted"]
    page.write_text("290 laws hold one.", encoding="utf-8")
    assert not C.evaluate()["claims"][0]["quoted"]
