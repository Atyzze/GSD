from __future__ import annotations

import builtins

import main as cli


def _rows():
    return [{"campaign_id": "1"}, {"campaign_id": "3"}, {"campaign_id": "5"}]


def _selected(raw: str):
    parts = raw.split()
    known = {str(row["campaign_id"]) for row in _rows()}
    if len(parts) != 2 or parts[1] not in known:
        return None
    return parts[1]


def test_the_argument_is_a_campaign_id_not_a_row_number():
    assert _selected("d 5") == "5", "naming campaign 5 must select campaign 5"
    assert _selected("d 1") == "1"
    assert _selected("d 3") == "3", (
        "row 3 held campaign 5; `d 3` must now mean campaign 3 or nothing, "
        "never 'the third row'")


def test_a_row_number_that_is_not_a_campaign_id_is_refused():
    assert _selected("d 2") is None, (
        "2 is a valid row number and not a campaign id, so it must be refused "
        "rather than silently resolved to campaign 3")
    assert _selected("d 99") is None
    assert _selected("d") is None
    assert _selected("delete campaign 5") is None


def test_deleting_demands_the_id_typed_back(monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    typed = []

    def answer(prompt):
        typed.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(builtins, "input", answer)

    responses = ["y"]
    assert cli._confirm_action("DELETE campaign 5: ...", echo="5") is False, (
        "`y` must no longer confirm a delete; it is what was typed when "
        "campaign 5 was lost")

    responses = ["3"]
    assert cli._confirm_action("DELETE campaign 5: ...", echo="5") is False, (
        "typing a different campaign id must abort")

    responses = ["5"]
    assert cli._confirm_action("DELETE campaign 5: ...", echo="5") is True
    assert any("'5'" in prompt for prompt in typed), (
        "the prompt has to name what must be typed")


def test_the_plain_confirmation_is_unchanged_for_non_destructive_prompts(monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(builtins, "input", lambda prompt: "y")
    assert cli._confirm_action("proceed?") is True
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")
    assert cli._confirm_action("proceed?") is False


def test_non_interactive_still_refuses_without_yes(monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert cli._confirm_action("DELETE campaign 5: ...", echo="5") is False
    assert cli._confirm_action("DELETE campaign 5: ...", echo="5", yes=True) is True
