from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from graph_scale_dynamics.decisions.engine import Policy
from graph_scale_dynamics.resources import committed

DOCUMENT_CLAIMS_CONTRACT = "gsd-document-claims-1"

ROOT = Path(__file__).resolve().parents[2]
READINGS = ROOT / committed.DOCS_READINGS
WHERE_WE_ARE = "docs/WHERE_WE_ARE.md"
RESEARCH_METHOD = "docs/RESEARCH_METHOD.md"
HANDOFF = "docs/agent/HANDOFF.md"
_OPENED: ContextVar[list | None] = ContextVar("document_claims_opened", default=None)
LATTICE_FAMILIES = {"cubic": "periodic_cubic_lattice", "4D": "periodic_hypercubic_lattice_4d"}
READ_FROM_N = 1024


@dataclass(frozen=True)
class Claim:
    claim_id: str
    doc: str
    quote: str
    check: Callable[[], tuple[bool, object]]


def _json(path: Path):
    opened = _OPENED.get()
    if opened is not None:
        opened.append(Path(path).name)
    return json.loads(path.read_text(encoding="utf-8"))


def _chained_cubic() -> tuple[bool, object]:
    survey = _json(ROOT / "graph_scale_dynamics" / "resources" / "configs" / "campaign_engine_survey.json")
    policy = survey["engine"]["policy"]
    threshold = float(policy["gap_exponent_at_most"])
    diameter_at_least = float(policy.get("diameter_exponent_at_least", Policy().diameter_exponent_at_least))
    judged = _json(committed.path("chained_cubic_judged.json", ROOT))
    seeds = judged["chained"]

    def finite_at(gap_at_most: float) -> int:
        count = 0
        for seed in seeds.values():
            gap = re.search(r"gap exponent (-?[0-9.]+)", seed["rule_why"])
            diameter = re.search(r"diameter exponent (-?[0-9.]+)", seed["rule_why"])
            if gap and diameter:
                count += float(gap.group(1)) <= gap_at_most and float(diameter.group(1)) >= diameter_at_least
        return count
    finite = judged["finite_families"]
    measured = {"threshold": threshold, "default": Policy().gap_exponent_at_most, "seeds": len(seeds),
                "sizes": judged["sizes"], "finite_at_survey_threshold": finite_at(threshold),
                "finite_at_the_default": finite_at(Policy().gap_exponent_at_most),
                "refused_by_all_three": sum(not s["three_readings"].get("agree") for s in seeds.values()),
                "families_accepted": [sum(f["three_readings"].get("agree") is True for f in finite.values()), len(finite)],
                "families_unread": sorted(n for n, f in finite.items() if f["three_readings"].get("agree") is None)}
    return measured == {"threshold": -0.309, "default": -0.3752, "seeds": 9, "sizes": [4096, 16384, 65536],
                        "finite_at_survey_threshold": 8, "finite_at_the_default": 6, "refused_by_all_three": 9,
                        "families_accepted": [7, 9], "families_unread": ["sierpinski_carpet", "sierpinski_gasket"]}, measured


def _space_score_on_the_starts() -> tuple[bool, object]:
    known = _json(committed.path("starts_known_answers_judged.json", ROOT))
    measured = {start: bool(found["space"]) for start, found in known["space_score_on_the_starts"].items()}
    return measured == {"periodic_body_centred_cubic_lattice": False, "periodic_cubic_quotient": False,
                        "periodic_face_centred_cubic_lattice": False, "periodic_honeycomb_lattice": True,
                        "periodic_square_lattice": True, "periodic_tesseract_quotient": False,
                        "periodic_triangular_lattice": True}, measured


def _starts_known_answers() -> tuple[bool, object]:
    known = _json(committed.path("starts_known_answers_judged.json", ROOT))
    missed = {case["id"]: sorted({f for row in case["sizes"].values() for f in row["failures"]})
              for case in known["cases"] if not case["passed"]}
    measured = {"passed": [sum(case["passed"] for case in known["cases"]), len(known["cases"])], "missed": missed}
    return measured == {"passed": [8, 11], "missed": {"K1": ["fcc partly, expected melted"],
                                                      "K10": ["fcc partly, expected melted"],
                                                      "K11": ["fcc partly, expected melted"]}}, measured


def _lattice_medians() -> tuple[bool, object]:
    table = _json(ROOT / "calibration" / "seed_table.json")
    cells: dict = defaultdict(lambda: defaultdict(list))
    sizes: dict = defaultdict(list)
    wanted = {family: name for name, family in LATTICE_FAMILIES.items()}
    for key, cell in table["cells"].items():
        family, side, _ = key.rsplit(":", 2)
        if family not in wanted:
            continue
        sizes[(family, side)].append(cell.get("component") or 0)
        for probe in ("d_s", "d_V", "d_B"):
            channel = cell["channels"].get(probe) or {}
            if channel.get("valid") and channel.get("value") is not None:
                cells[(family, side)][probe].append(float(channel["value"]))
    medians: dict = defaultdict(list)
    for (family, side), probes in cells.items():
        if max(sizes[(family, side)]) < READ_FROM_N or len(probes) < 3:
            continue
        means = sorted(statistics.mean(values) for values in probes.values())
        medians[wanted[family]].append(means[1])
    measured = {name: [round(min(values), 2), round(max(values), 2)] for name, values in medians.items()}
    return measured == {"cubic": [2.92, 2.99], "4D": [3.76, 3.95]}, measured


def _dimension_test() -> tuple[bool, object]:
    judged = _json(committed.path("dimension_test_4_judged.json", ROOT))
    cases = {(c["part"], c["family"]): c for c in judged["cases"]}

    def right(part, expected):
        found = [c for c in cases.values() if c["part"] == part and c["expected"] == expected]
        return f"{sum(c['passes'] for c in found)} of {len(found)}"

    def agree(part):
        return round(max(s["signals"]["growth_gap"] for c in cases.values() if c["part"] == part
                         and c["expected"] == "dimensional" for s in c["seeds"]), 2)

    def reads(family):
        found = [s["d"] for s in cases[("held_out", family)]["seeds"]]
        return round(min(found), 2), round(max(found), 2)

    einstein = [s["signals"]["einstein_gap"] for c in cases.values() for s in c["seeds"]]
    measured = {
        "passes": judged["passes"], "training": len([c for c in cases.values() if c["part"] == "training"]),
        "held_out": len([c for c in cases.values() if c["part"] == "held_out"]),
        "every_seed": all(s["right"] for c in cases.values() for s in c["seeds"]),
        "geometries": right("held_out", "dimensional"), "look_alikes": right("held_out", "not_dimensional"),
        "agree_training": agree("training"), "agree_held_out": agree("held_out"),
        "look_alikes_compared": sum(s["signals"]["growth_gap"] is not None for c in cases.values()
                                    if c["expected"] == "not_dimensional" for s in c["seeds"]),
        "threshold": judged["rule"]["growth_agrees_within"], "percolation": reads("percolation_2d"),
        "tree": reads("random_tree"),
        "einstein_on_4d": [s["signals"]["einstein_gap"] for f in ("tesseract", "rgg_4d")
                           for s in cases[("training", f)]["seeds"] if s["signals"]["einstein_gap"] is not None],
        "einstein_most": round(max(g for g in einstein if g is not None), 2),
    }
    expected = {"passes": True, "training": 13, "held_out": 9, "every_seed": True, "geometries": "4 of 4",
                "look_alikes": "5 of 5", "agree_training": 0.05, "agree_held_out": 0.34, "look_alikes_compared": 0,
                "threshold": 0.4, "percolation": (1.52, 1.57), "tree": (1.82, 2.03), "einstein_on_4d": [],
                "einstein_most": 0.38}
    return measured == expected, measured


def _certificate_count() -> tuple[bool, object]:
    judged = _json(committed.path("certificate_known_answers_3_judged.json", ROOT))
    at_16, at_8 = judged["by_threshold"]["16"]["rungs"], judged["by_threshold"]["8"]["rungs"]
    measured = {"fit_at": judged["fit_at"],
                "starved_at_16": round(max(read["starved_pass_worst"] for read in at_16.values()), 3),
                "kept_at_16": sorted(round(read["kept_worst"], 3) for read in at_16.values()),
                "alone_at_16": round(min(read["starved_pass_worst_by_the_chain_from_empty_alone"]
                                         for read in at_16.values()), 3),
                "starved_at_8": round(max(read["starved_pass_worst"] for read in at_8.values()), 3)}
    return measured == {"fit_at": [16], "starved_at_16": 0.05, "kept_at_16": [0.986, 0.997], "alone_at_16": 0.998,
                        "starved_at_8": 0.642}, measured


def _curvature_answers() -> tuple[bool, object]:
    judged = _json(committed.path("curvature_known_answers_2_judged.json", ROOT))
    cases = {case["family"]: case for case in judged["cases"]}
    plane, sparse, flat = cases["random_geometric_2d"], cases["erdos_renyi_4"], cases["triangular_torus"]
    measured = {"right": [judged["predictions_right"], judged["predictions"]], "exact_on": sorted(judged["exact_on"]),
                "triangular": [round(flat["apart_least"], 4), round(flat["apart_most"], 4), flat["exact_mean"]],
                "plane": [plane["edges_agreeing"], plane["edges_read"], round(plane["probe_mean"], 2),
                          round(plane["exact_mean"], 2), plane["apart_least"] >= -1e-6],
                "sparse": [sparse["edges_agreeing"], sparse["edges_read"]]}
    return measured == {"right": [8, 8],
                        "exact_on": ["complete_6", "cubic_torus", "honeycomb_torus", "random_regular_3", "ring",
                                     "square_torus", "tesseract_torus"],
                        "triangular": [0.3333, 0.3333, 0.0], "plane": [47, 300, 0.4, 0.11, True],
                        "sparse": [295, 300]}, measured


def claims() -> list[Claim]:
    return [
        Claim("chained_cubic", WHERE_WE_ARE,
              "reads finite by the rule in 8 of 9 seeds at the threshold the survey runs (6 of 9 at the engine's "
              "default), and all three readings refuse all 9", _chained_cubic),
        Claim("chained_cubic", RESEARCH_METHOD,
              "8 of 9 seeds by the rule alone at the gap threshold the survey runs (-0.309; 6 of 9 at the engine's "
              "default, -0.3752)", _chained_cubic),
        Claim("chained_cubic", RESEARCH_METHOD,
              "accept 7 of the 9 families of known finite dimension and say nothing of the Sierpinski gasket and "
              "carpet", _chained_cubic),
        Claim("space_score_on_the_starts", RESEARCH_METHOD,
              "it calls the exact square, triangular and honeycomb lattices a space and none of the cubic, "
              "body-centred cubic, face-centred cubic and 4D lattices one, at the sizes from 1,024 to 1,048,576",
              _space_score_on_the_starts),
        Claim("starts_known_answers", WHERE_WE_ARE,
              "The starts' reading passes 8 of its 11 known answers on the eight starts (819)", _starts_known_answers),
        Claim("starts_known_answers", RESEARCH_METHOD,
              "8 of the 11 cases pass. The three that miss are one fault: at 1,024 nodes a random graph of mean "
              "degree 6 in the chain from the face-centred cubic start reads partly kept", _starts_known_answers),
        Claim("lattice_medians", RESEARCH_METHOD,
              "cubic lattice's probes at a median of 2.92 to 2.99 and the 4D lattice's at 3.76 to 3.95",
              _lattice_medians),
        Claim("certificate_count", RESEARCH_METHOD,
              "At 16, a rung of 2 or 8 chains certifies a rung with one chain of at most 2 true samples in at most 5.0% "
              "of chunks and keeps 98.6% to 99.7% of rungs of plenty, where the count on the chain from empty alone "
              "certified such a rung 99.8% of the time. At the policy's default of 8 no rung is fit, a starved chain "
              "passing a rung up to 64.2% of the time", _certificate_count),
        Claim("certificate_count", HANDOFF,
              "certifies at 16 a rung with one chain of at most 2 true samples in at most 5.0% of chunks and keeps "
              "98.6% to 99.7% of rungs of plenty", _certificate_count),
        Claim("curvature_answers", RESEARCH_METHOD,
              "8 of 8 predictions were right: it is exact on every edge read of the square, cubic and 4D tori, the "
              "ring, the honeycomb torus, the complete graph on 6 nodes and a random 3-regular graph, and on the "
              "triangular torus it reads +1/3 on every edge where Ollivier's curvature is 0. On a random geometric "
              "graph in the plane it agrees on 47 of 300 edges and reads a mean of 0.40 against 0.11, never below; on "
              "a random graph of mean degree 4, on 295 of 300.", _curvature_answers),
        Claim("curvature_answers", HANDOFF,
              "on the triangular torus read +1/3 where it is 0; on a random geometric graph in the plane they agree "
              "on 47 of 300 edges", _curvature_answers),
        Claim("dimension_test", WHERE_WE_ARE,
              "read again on the final probes (808): 4 of 4 geometries dimensional and inside their bands on every "
              "seed, 5 of 5 look-alikes not", _dimension_test),
        Claim("dimension_test", RESEARCH_METHOD,
              "Every case passed on every seed: 4 of 4 held-out geometries dimensional and inside their bands",
              _dimension_test),
        Claim("dimension_test", RESEARCH_METHOD,
              "the two d's agree within 0.05 on training and 0.34 held out (the threshold is 0.4)", _dimension_test),
        Claim("dimension_test", RESEARCH_METHOD,
              "(1.52 to 1.57 on percolation, whose d is 1.90; 1.82 to 2.03 on trees, d 2)", _dimension_test),
        Claim("dimension_test", RESEARCH_METHOD, "missed by up to 0.38 elsewhere", _dimension_test),
        *instrument_claims(),
    ]


def instrument_claims() -> list[Claim]:
    from graph_scale_dynamics.research import instrument_claims as found
    return found.claims()


def _span(values) -> list:
    found = [v for v in values if v is not None]
    return [round(min(found), 2), round(max(found), 2)] if found else []


def _flat(text: str) -> str:
    return " ".join(text.replace("**", "").split())


def _checked(check: Callable[[], tuple[bool, object]]) -> tuple[bool, object]:
    opened: list = []
    token = _OPENED.set(opened)
    try:
        holds, measured = check()
    except Exception as error:
        holds, measured = False, f"{type(error).__name__}: {error}"
    finally:
        _OPENED.reset(token)
    return bool(holds), measured


def evaluate() -> dict:
    rows = []
    for claim in claims():
        holds, measured = _checked(claim.check)
        document = (ROOT / claim.doc).read_text(encoding="utf-8")
        rows.append({"claim_id": claim.claim_id, "doc": claim.doc, "quote": claim.quote, "holds": holds,
                     "quoted": _flat(claim.quote) in _flat(document), "measured": measured})
    return {"contract": DOCUMENT_CLAIMS_CONTRACT, "claims": rows}
