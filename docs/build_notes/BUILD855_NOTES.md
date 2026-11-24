# Build 855: the handover every worker loads, builds as pull requests, and the start of the table that only grows: the calibration ledger and its first appended probe group, the quantum walk. No score, decision or frozen source moved

**Type: a handover and an appended probe group, asked for by the operator on 2026-11-24 from 19:10 to 19:26, on the
fast lane ("can you create me a new handover build on the fast lane, so that the pull request can be merged early so
that all other workers out there share this new root/message containing full instructions for system self
awareness").** New: `CLAUDE.md`, `docs/agent/APPEND_ONLY_PLAN.md`, `graph_scale_dynamics/calibration/ledger.py`,
`graph_scale_dynamics/calibration/ledger_runs.py`, `graph_scale_dynamics/calibration/probe_groups.py`,
`graph_scale_dynamics/probes/__init__.py`, `graph_scale_dynamics/probes/quantum_walk.py`, `tools/ledger.py`, and three
test files (`tests/unit/test_the_calibration_ledger_only_grows.py`,
`tests/unit/test_an_appended_probe_moves_nothing_frozen.py`, `tests/unit/test_the_quantum_walk_reads_known_graphs.py`,
23 tests). Changed: `graph_scale_dynamics/calibration/fingerprint.py` (the import closure of any entry, not only the
estimator's; the estimator's fingerprint is the same bytes), `docs/ARCHITECTURE.md` ("The calibration ledger"),
`docs/TOOLS.md` (`tools/ledger.py`), `tools/package_release.py` (`CLAUDE.md` among the root files a release carries), `docs/HISTORY.md` (two standing decisions under "Delivery"), `docs/ROADMAP.md`
(item 10), `docs/agent/NEXT_BUILD.md` (855 first; 854's plan for 855 and 856 now 856 and 857; delivery by pull
request), `docs/agent/HANDOFF.md` (its opening paragraph), `docs/WHERE_WE_ARE.md` ("What comes next"). Made in a
context of its own, beside the one that made 853 and 854, from an outside review of 852 that went on into this.

## Why

Three of the operator's messages of the evening. 19:10, of the quantum walk proposed as a fifth probe: "why not be able
to append the callibration table with this new probe? its the perfect test so that the science table becomes
append-only instead of this bs immutable sales tactics, always/naturally allowing for more probes/values/rungs for as
long as long as the reference engine implementations are specified and included with full hash in the shared
datablob". 19:15: "I want C and ASM included by default as well, next to Python and Rust, to complete the base-4
reference set which should also be append-able". 19:22: several contexts now share the repository, so every delivery
is "one coherent pack of code updates" as "a pull request [...] let me click the final merge button myself".

## The table only grows: the calibration ledger

The table keys every cell by one fingerprint over every probe (`calibration/fingerprint.cell_fingerprint`): a fifth
probe or an edit to one of the four makes all 2,584 cells stale, and the last full measurement took 7 h 10 min on 31
workers (the table's own `runs`). The ledger keys readings by probe group and never rewrites one
(`docs/ARCHITECTURE.md`, "The calibration ledger"):

- `geometry` is the table's four probes under the table's own key (analysis and estimator); `tools/ledger.py
  from-table` files the shipped table's 2,584 cells in it measuring nothing, and its fingerprint equals this tree's
  (`7eef56b509dbe3c4`), so the table is current under it.
- Every module of `graph_scale_dynamics/probes/` is an appended group under its own version and import closure. The
  folder is outside the frozen trees and the estimator's closure: the science fingerprint (`95494cdfcbbe128a`) and the
  estimator's (`e639334808716378`) are 854's, measured on both trees.
- One file a group and fingerprint, each line hashing its content and the line before it; a cell measured once a
  fingerprint, read again only as an attestation; a new fingerprint a new file beside the old. A snapshot prints a
  Merkle root of the records and one of their values alone, each the set's and not the order's.
- No appended group votes: nothing in the gate, the score, a decision or a reading reads it.

The ledger files themselves are not in this build: the geometry file is the shipped table filed again (7.8 MB,
`from-table` writes it to the same bytes on any host), and the quantum walk's first full pass is the host's to make
(`docs/agent/APPEND_ONLY_PLAN.md`, L2). In the sandbox: `from-table` wrote 2,584 records and wrote none on its
second run; `measure` filed 20 quantum-walk cells, `attest` re-measured three of them to the same bytes, and `verify`
found nothing.

## The quantum walk, against d_s

`probes/quantum_walk.py`: a continuous-time quantum walk under the degree-normalised adjacency of the largest
component, from four starts drawn on its own stream, stepped by an exact Chebyshev expansion (one step agrees with
`scipy`'s exponential to 1e-12). `q_alpha` is the exponent of its mean squared graph distance (2: a wave that
travels), `q_decay` that of its smoothed return probability (the dimension, on a clean lattice). `d_s` reads the
spectrum alone; the walk reads where the eigenvectors sit, so the two agree on a clean lattice and part where a graph
traps a wave. In the sandbox, `d_s` from the shipped table at its largest sizes:

| family | nodes read by the walk | `q_alpha` | `q_decay` | `d_s` (table) |
|---|---|---|---|---|
| periodic ring | 16,384; 65,536 | 2.00; 2.00 | 1.01; 1.01 | 1.00 |
| periodic square lattice | 16,384; 65,536 | 2.00; 2.00 | 2.13; 2.08 | 2.00 |
| Sierpinski gasket | 9,843; 29,526 | 0.77; 0.82 | 0.00; 0.01 | 1.37 |
| uniform random tree | 16,384; 65,536 | 0.42; 0.43 | 0.01; 0.03 | 1.29 |
| random 4-regular | 16,384; 65,536 | refused | refused | refused |
| periodic cubic lattice | 15,625; 64,000 | refused | refused | 3.0 |

The random regular graph is refused by name (`SATURATES_EARLY`: the walk fills it before four times the earliest time
read), as the four probes refuse it. The cubic lattice is refused below the sizes where the walk has room before it
reaches half the torus; the host's pass to 1,048,576 says where it starts reading. What each family must read is the
criterion of L2, committed before a second pass reads it.

## Several workers, one repository

`CLAUDE.md` is loaded by every agent that opens the repository. It says what the system is and which page holds
what, the rules for sharing it (a branch each, a pull request each, the operator merges, `main` fetched before every
pull request, the shared pages left to the build being released, a check-in about every four hours), and the
principle of the table that only grows. `docs/agent/NEXT_BUILD.md`, step 6 onward, now delivers by pull request in
place of a push to `main`; `docs/HISTORY.md` holds both decisions with the operator's words.

## What did not move

Against 854's record (`tools/outputs_of_a_law.py --write` on the untouched tree with the same calibration table, then
`--against` on this one): **0 outputs changed**. No frozen source, no schema, no engine, no score, no decision, no
reading. 854's plan for its next build is kept whole as 856's.

## What the operator decides

The four questions of `docs/agent/APPEND_ONLY_PLAN.md`, each with the default the work follows until answered: the
assembly engine's reach (grown term by term with declared coverage) and instruction set (x86-64); where the
reference engines live (outside the frozen trees, each hashed in a registry); whether ledger files are committed to the
repository (yes, for each group's first pass) or published beside it; and when the four probes are split into groups
of their own (one recalibration).

## Verification

3919 passed in 1483.91s (3 lanes at once)
