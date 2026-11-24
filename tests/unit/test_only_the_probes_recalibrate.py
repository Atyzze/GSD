from __future__ import annotations

import ast
from pathlib import Path

from graph_scale_dynamics.calibration import fingerprint as FP
from graph_scale_dynamics.domain.science_identity import FROZEN_TREES

ROOT = Path(__file__).resolve().parents[2]
PROBES = ("graph_scale_dynamics/measurements/", "graph_scale_dynamics/domain/randomness.py")
THE_KEY = ["graph_scale_dynamics/measurements/box_covering.py", "graph_scale_dynamics/measurements/estimators.py",
           "graph_scale_dynamics/measurements/fits.py", "graph_scale_dynamics/measurements/walk_dimension.py"]
NO_PROBE = ("graph_scale_dynamics/measurements/certificate.py", "graph_scale_dynamics/measurements/analysis.py")
OF_A_CHAIN = ("envelope", "trajectory", "measurements", "checkpoint")


def test_the_probes_closure_is_the_probes_and_nothing_the_survey_decides_with():
    closure = FP.measurement_closure()
    assert closure and all(path.startswith(PROBES) for path in closure), closure
    for tree in FROZEN_TREES:
        if not tree.startswith("graph_scale_dynamics/measurements"):
            assert not any(path.startswith(tree + "/") for path in closure), (tree, closure)


def test_the_table_s_key_is_the_probes_files_and_no_other():
    assert FP.measurement_closure() == THE_KEY, "a file joined or left what the calibration table is keyed by"
    assert not set(NO_PROBE) & set(FP.measurement_closure()), "the certificate or the reading of a record is in the key"
    assert all((ROOT / path).is_file() for path in NO_PROBE)


def test_nothing_in_the_key_reads_a_chain_s_record():
    for path in THE_KEY:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                taken = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
                assert not set(taken) & set(OF_A_CHAIN), (
                    f"{path}: {node.name} takes {sorted(set(taken) & set(OF_A_CHAIN))}; what reads a chain is no probe, "
                    "and a change to it would make the calibration table stale")
