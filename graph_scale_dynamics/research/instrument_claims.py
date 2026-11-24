from __future__ import annotations


from graph_scale_dynamics.research import document_claims as S
from graph_scale_dynamics.resources import committed

INSTRUMENT_CLAIMS_CONTRACT = "gsd-instrument-claims-1"


def _boltzmann_answers() -> tuple[bool, object]:
    judged = S._json(committed.path("boltzmann_known_answers_4_judged.json", S.ROOT))
    criterion = S._json(committed.path("boltzmann_known_answers_criterion_4.json", S.ROOT))
    hot = [cell for cell in judged["cells"] if float(cell.get("beta", 1.0)) != 1.0]
    measured = {"passes": judged["passes"], "kept": [judged["kept"]["held"], judged["kept"]["of"]],
                "reached": [judged["reached"]["held"], judged["reached"]["of"]],
                "graphs": judged["energies"]["graphs_checked"],
                "between_engines": judged["energies"]["between_engines"],
                "off_the_ledger": sum(cell["ends_off_the_ledger"] for cell in judged["cells"]),
                "controls": [judged["predictions_right"], len(judged["predictions"])],
                "hot_refused": sum(1 for cell in hot if not cell["kept"]),
                "hot_kept_at_its_beta": sum(1 for cell in hot if cell["given_against_wrong_measures"][
                    f"{float(cell['beta']):g}"] >= judged["alpha"]),
                "wrong": [judged["wrong_measures"][factor]["refused"] for factor in ("2", "1.25")],
                "laws": len(judged["cells"]) // 4, "terms": len(judged["by_term"]),
                "alone": criterion["drawn"]["alone_per_term"], "mixed": criterion["drawn"]["mixed"],
                "runs": [criterion["engines"][name]["runs"] for name in ("rust", "python")],
                "rust": judged["engine_fingerprints"]["rust"].split("+")[0]}
    return measured == {"passes": True, "kept": [260, 260], "reached": [112, 112], "graphs": 71808,
                        "between_engines": 0.0, "off_the_ledger": 0, "controls": [8, 8], "hot_refused": 4,
                        "hot_kept_at_its_beta": 4, "wrong": [221, 77], "laws": 66, "terms": 14,
                        "alone": 2, "mixed": 8, "runs": [2000, 1000], "rust": "rs:0.806.0"}, measured


def _what_the_seed_took() -> tuple[bool, object]:
    seed = S._json(S.ROOT / "calibration" / "seed_table.json")
    measured = {"cells": len(seed["cells"]),
                "hours": round(sum(float(cell.get("elapsed_seconds") or 0.0) for cell in seed["cells"].values()) / 3600)}
    return measured == {"cells": 2584, "hours": 190}, measured


def _which_lattices_a_law_can_tell() -> tuple[bool, object]:
    judged = S._json(committed.path("start_admission_2_judged.json", S.ROOT))
    lattices = {lattice["name"]: lattice for lattice in judged["lattices"]}
    top = str(max(judged["sizes"]))

    def largest(name):
        return round(max(abs(sizes[top]) for sizes in lattices[name]["differences"].values()), 3)

    def by(name):
        return sorted(lattices[name]["told_by"])
    square = ["induced_square_count", "ollivier_curvature", "square_count", "square_edge_overlap"]
    curvature = [lattices[name]["differences"]["ollivier_curvature"] for name in ("body-centred cubic", "4D")]
    measured = {"admitted": judged["admitted"], "not_admitted": judged["not_admitted"], "passes": judged["passes"],
                "told_by_no_term": [by(name) for name in judged["not_admitted"]],
                "largest_left_out": [largest(name) for name in judged["not_admitted"]],
                "by_the_square_terms_and_the_curvature": [by(name) == square for name in
                                                          ("square", "cubic", "body-centred cubic", "4D")],
                "face_centred": by("face-centred cubic") == sorted(
                    square + ["triangle_count", "triangle_edge_overlap"]),
                "not_as_predicted": judged["told_otherwise_than_expected"],
                "triangular_induced_squares": [
                    "induced_square_count" in by("triangular"),
                    round(abs(lattices["triangular"]["differences"]["induced_square_count"][top]), 3)],
                "curvature_alike": [curvature[0] == curvature[1], round(curvature[0][top], 2)], "top": int(top)}
    return measured == {"admitted": ["square", "triangular", "cubic", "body-centred cubic", "face-centred cubic", "4D"],
                        "not_admitted": ["honeycomb", "diamond"], "passes": True, "told_by_no_term": [[], []],
                        "largest_left_out": [0.007, 0.062],
                        "by_the_square_terms_and_the_curvature": [True, True, True, True], "face_centred": True,
                        "not_as_predicted": ["triangular"], "triangular_induced_squares": [False, 0.005],
                        "curvature_alike": [True, 378.53], "top": 16384}, measured


def claims() -> list:
    method, handoff = S.RESEARCH_METHOD, S.HANDOFF
    stated = [
        (_which_lattices_a_law_can_tell, method,
         "All six lattice starts of study A are admitted: the square, cubic, body-centred cubic and 4D lattices "
         "are told by the three square terms and the curvature, the face-centred cubic lattice by those and the "
         "two triangle terms. The honeycomb and the diamond lattice, the two left out, are told by no term: the "
         "largest difference a node at 16,384 nodes is 0.007 on the honeycomb and 0.062 on the diamond lattice, "
         "both in the curvature term and both shrinking as the lattice grows."),
        (_which_lattices_a_law_can_tell, method,
         "One term list of eight is not as predicted: the triangular lattice is not told by its induced squares "
         "(0.005 a node at 16,384), every square of it carrying a chord."),
        (_which_lattices_a_law_can_tell, method,
         "The curvature term reads the body-centred cubic and the 4D lattice alike to the last digit (378.53 a "
         "node above the random graphs' at 16,384), though the first has twelve squares on an edge and the second "
         "six"),
        (_what_the_seed_took, handoff, "the seed's 2,584 cells took 190 hours between them"),
        (_boltzmann_answers, method,
         "The measure is kept in 260 of 260 cells and reached from empty in 112 of 112; the two engines give all "
         "71,808 graphs the same energy to the last bit, and no chain ended carrying an energy that was not its "
         "graph's. The control that runs the toggle's law at twice its energy is refused in all four of its cells, "
         "and its counts agree in all four with the measure of the energies doubled, the one its chain keeps. The "
         "same counts refuse a measure with the energies doubled in 221 of 260 cells and one with them a quarter "
         "larger in 77"),
        (_boltzmann_answers, method,
         "66 laws (each of the fourteen terms alone, twice; eight laws of two to four terms; each term again where "
         "the chain from empty is judged; two controls)"),
        (_boltzmann_answers, method, "2,000 runs a cell on Rust and 1,000 on Python"),
        (_boltzmann_answers, handoff,
         "every one of the fourteen terms keeps its measure (260 of 260 cells) and reaches it from empty (112 of 112) "
         "on both engines"),
    ]
    return [S.Claim(check.__name__.strip("_"), doc, quote, check) for check, doc, quote in stated]
