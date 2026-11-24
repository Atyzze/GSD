from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _main():
    sys.path.insert(0, str(ROOT))
    return importlib.import_module("main")


def test_the_default_campaign_is_valid_on_every_current_contract():
    main = _main()
    from graph_scale_dynamics.scheduling.campaign import validate_campaign
    spec = main.read_config_file(main.DEFAULT_HOME_CAMPAIGN_SPEC)
    assert main.DEFAULT_HOME_CAMPAIGN_SPEC == "campaign_engine_survey.json"
    assert validate_campaign(spec) + main._engine_required(spec) == []
    assert main._scientific_contract_matches_current(spec)


def test_a_campaign_frozen_under_the_old_engine_contract_is_refused_with_its_replacement(capsys):
    main = _main()
    spec = main.read_config_file(main.DEFAULT_HOME_CAMPAIGN_SPEC)
    old = json.loads(json.dumps(spec))
    old["engine"]["contract"] = "decision-engine-1"
    assert not main._scientific_contract_matches_current(old)
    main._refuse_foreign_contract("1", old)
    printed = capsys.readouterr().out
    for needle in ("engine=decision-engine-1", "engine decision-engine-2", "Refusing",
                   "main.py campaign close 1", "main.py campaign start --spec campaign_engine_survey.json",
                   "main.py campaign use <new id>"):
        assert needle in printed, (needle, printed)
