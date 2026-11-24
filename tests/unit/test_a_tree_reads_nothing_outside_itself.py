from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from graph_scale_dynamics.calibration import contract as C
from graph_scale_dynamics.operations import study_record as R
from graph_scale_dynamics.operations import campaign_control as control
from graph_scale_dynamics.operations import study as S
from graph_scale_dynamics.reporting import study_bundle as B

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "graph_scale_dynamics" / "resources" / "readings"

_SEEN: list[tuple[str, str]] = []
_SEEING = [False]
_EVENTS = {"open": 0, "os.listdir": 0, "os.scandir": 0, "glob.glob": 0, "os.walk": 0}


def _hook(event, args):
    if not _SEEING[0] or event not in _EVENTS or not args:
        return
    target = args[0]
    if isinstance(target, (str, bytes, Path)):
        _SEEN.append((event, str(target if not isinstance(target, bytes) else target.decode(errors="replace"))))


sys.addaudithook(_hook)


def _write(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


OTHER_ANALYSIS = "analysis-0.0.0"


def _a_design_on_another_analysis(tree: Path, study: str = "261") -> None:
    design = json.loads((ROOT / "tests" / "fixtures" / "a_design.json").read_text(encoding="utf-8"))
    design.update(study=study, instrument={"analysis": OTHER_ANALYSIS})
    _write(tree / "graph_scale_dynamics" / "resources" / "readings" / f"study_{study}_design.json", design)


def _poisoned_host(tmp_path: Path) -> tuple[Path, Path]:
    studies = tmp_path / "GSD"
    tree = studies / "261" / "main"
    (tree / "graph_scale_dynamics" / "resources" / "readings").mkdir(parents=True)
    (tree / C.DURABLE_DIR).mkdir(parents=True)
    _a_design_on_another_analysis(tree)
    seed = json.loads((ROOT / C.DURABLE_DIR / C.SEED_TABLE_NAME).read_text(encoding="utf-8"))
    (tree / C.DURABLE_DIR / C.SEED_TABLE_NAME).write_text(json.dumps(seed), encoding="utf-8")
    stale = dict(seed, cells=dict(list(seed["cells"].items())[:2]))
    older = studies / "255" / "main"
    _write(older / C.DURABLE_DIR / C.DURABLE_NAME, stale)
    _write(older / "var" / "salt" / "ledger.json", {
        "contract": "gsd-salt-ledger-2", "written_utc": "2099-01-01T00:00:00Z", "study_id": "255",
        "ledger": {"empty": {"cheap": {"clean": 5000, "missed": 0, "clean_since_last_miss": 5000}}}})
    _write(studies / "257" / "main" / "docs" / "readings" / "study_257_design.json", {"contract": "poison"})
    _write(studies / "graph_scale_dynamics_build_631" / C.DURABLE_DIR / C.DURABLE_NAME, stale)
    _write(tmp_path / "host-state" / C.DURABLE_NAME, stale)
    return studies, tree


class _Repo:
    def __init__(self):
        self.flags, self.made = {}, []

    def get_flag(self, key, default=None):
        return self.flags.get(key, default)

    def set_flag(self, key, value):
        self.flags[key] = value

    def campaign(self, campaign_id):
        return {"campaign_id": campaign_id}

    def all_campaigns(self):
        return [{"campaign_id": str(i), "spec": spec} for i, spec in enumerate(self.made, start=1)]

    def record_campaign_event(self, *args):
        pass

    class conn:
        @staticmethod
        def execute(sql, params=()):
            class Result:
                @staticmethod
                def fetchone():
                    return {"c": 0}
            return Result()


def _outside(seen, studies: Path, tree: Path, allowed=()) -> list[tuple[str, str]]:
    studies, tree = str(studies.resolve()), str(tree.resolve())
    out = []
    for event, raw in seen:
        path = str(Path(raw).resolve()) if raw else raw
        if path in allowed:
            continue
        if path == studies or path.startswith(studies + "/") or "host-state" in path:
            if not (path == tree or path.startswith(tree + "/")):
                out.append((event, path))
    return out


def test_a_first_start_beside_poisoned_folders_reads_none_of_them(tmp_path, monkeypatch):
    studies, tree = _poisoned_host(tmp_path)
    monkeypatch.setenv("GSD_CALIBRATION_DIR", str(tmp_path / "host-state"))
    repo, lines = _Repo(), []

    def create(_repo, spec, *, reason, search_seed):
        repo.made.append(spec)
        return {"campaign_id": str(len(repo.made))}

    monkeypatch.setattr(control, "create_campaign", create)
    var = tree / "var"
    _SEEN.clear()
    _SEEING[0] = True
    try:
        candidates = C.candidate_table_paths(tree)
        refused = S.study_choice(None, repo=repo, var=var, root=tree, starting=True)
        first = S.start_study(repo, control.shipped_spec(), search_seed=1, log=lines.append, var=var, tree=tree)
        named = B.study_id(var / "reports", repo)
    finally:
        _SEEING[0] = False
    seen = list(_SEEN)
    assert seen, "the audit hook saw the start's reads"
    assert _outside(seen, studies, tree) == [], "nothing outside the tree is opened, written or listed (634)"
    assert not list(studies.rglob("notes.txt")), "no note beside the tree (634)"

    assert candidates == [tree / C.DURABLE_DIR / C.SEED_TABLE_NAME], "the tree's own seed, and nothing else"
    assert refused is None and first == "1" and len(repo.made) == 4, "the default study's four quadrants"
    assert not any(spec.get("study_design") for spec in repo.made), "the folder's name started no design"
    assert R.read(var)["study"] == R.DEFAULT and R.read(var)["chosen_by"] == R.BY_DEFAULT
    assert named == R.DEFAULT, "its bundles are the default study's, not the folder's name's"
    policies = [((spec.get("engine") or {}).get("policy") or {}) for spec in repo.made]
    assert all(p.get("let_through_rule") and "salt_shares" not in p for p in policies), (
        "the default study learns its gates from its own decisions, no other folder's ledger (the poisoned one's)")
    assert any(line.startswith("study default: no --study given") for line in lines)


def test_the_study_is_named_at_the_first_start_and_kept(tmp_path, monkeypatch):
    studies, _ = _poisoned_host(tmp_path)
    tree = studies / "257 the paper" / "main"
    (tree / "graph_scale_dynamics" / "resources" / "readings").mkdir(parents=True)
    _a_design_on_another_analysis(tree)
    var = tree / "var"
    assert "no design for it" in S.study_choice("999", root=tree, var=var, starting=True)
    assert "--spec" in S.study_choice("261", spec="x.json", root=tree, var=var, starting=True)
    assert "a study id is" in S.study_choice("../255", root=tree, var=var, starting=True)
    assert f"designed on {OTHER_ANALYSIS}" in S.study_choice("261", root=tree, var=var, starting=True)
    assert S.instrument_refusal(tree, None) is None and S.instrument_refusal(tree, "999") is None
    with pytest.raises(S.UnknownStudy, match="holds no design for it"):
        S.start_study(_Repo(), control.shipped_spec(), var=var, tree=tree, study="999", log=lambda *_: None)
    assert R.read(var) is None and not (var / "salt").exists(), "a refused start makes nothing"
    R.write(var, study="261", kind=R.DESIGNED, chosen_by=R.BY_FLAG, log=lambda *_: None)
    assert "chose study 261" in S.study_choice("255", root=tree, var=var, starting=True)

    class Started(_Repo):
        def all_campaigns(self):
            return [{"campaign_id": "1", "spec": {"study_design": {"study": "261"}}}]

    for wanted in (None, "261"):
        refused = S.study_choice(wanted, repo=Started(), var=var, root=tree, starting=False)
        assert f"designed on {OTHER_ANALYSIS}" in refused and "stays on the build it runs" in refused
    assert "one study for its whole life" in S.study_choice("255", repo=Started(), var=var, root=tree, starting=False)


def test_no_module_reads_the_folder_s_name_or_the_folders_beside_it():
    package = ROOT / "graph_scale_dynamics"
    offenders = [str(p.relative_to(ROOT)) for p in sorted(package.rglob("*.py")) + [ROOT / "main.py"]
                 if any(token in p.read_text(encoding="utf-8") for token in (
                     "other_study_trees", "folder_study_id", "SIBLING_TREE_GLOB", "parent.parent.glob(",
                     "domain.layout", "STUDY_TREE_NAME", "notes.txt\"", "root.parent.name"))]
    assert offenders == []
