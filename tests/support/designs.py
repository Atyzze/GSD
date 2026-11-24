from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOUR_STARTS = "tests/fixtures/a_design_of_four_starts.json"
A_DESIGN = "tests/fixtures/a_design.json"
DESIGNS = Path("graph_scale_dynamics") / "resources" / "readings"


def a_design() -> dict:
    raw = (ROOT / A_DESIGN).read_bytes()
    return dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=A_DESIGN)


def tree_with_a_design(tree: Path, study: str = "test", **changes) -> Path:
    design = dict(json.loads((ROOT / A_DESIGN).read_text(encoding="utf-8")), study=str(study), **changes)
    folder = Path(tree) / DESIGNS
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"study_{study}_design.json").write_text(json.dumps(design, indent=1) + "\n", encoding="utf-8")
    return Path(tree)


def of_four_starts() -> dict:
    raw = (ROOT / FOUR_STARTS).read_bytes()
    return dict(json.loads(raw), sha256=hashlib.sha256(raw).hexdigest(), path=FOUR_STARTS)


STRATA = {"allocation": {"zeroT/sees more/3-4 terms": 0.4, "finiteT/sees more/3-4 terms": 0.15,
                         "zeroT/sees more/1-2 terms": 0.15, "finiteT/sees more/1-2 terms": 0.1,
                         "zeroT/degree-only/1-2 terms": 0.05, "finiteT/degree-only/1-2 terms": 0.05,
                         "zeroT/degree-only/3-4 terms": 0.05, "finiteT/degree-only/3-4 terms": 0.05},
          "source": "the tests' own allocation, leaning on one stratum so a batch shows the allocation decides"}
