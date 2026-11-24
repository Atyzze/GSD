# Build 842: study 173's readers, two runs compared, the readers that held every decision read from disk, and no wait where nothing is learned. For a new folder; not for study 173's folders: 173 runs on 841, and so does its rerun on 32 workers, so that only the worker count differs.

**Type: the build agreed at 22:57 ("Agree with the recommendations"), made while study 173 runs: what reads 173's
bundle and its rerun, the readers made ready for study A's size, and one fix to when a law decides that changes no
decision.**
Changed: `graph_scale_dynamics/decisions/let_through.py`, `tools/counters_reading.py`, `tools/study_172_reading.py`,
`tools/design_on_a_bundle.py`. New: `tools/decision_index.py`, `tools/study_173_reading.py`, `tools/lattice_cost.py`,
`tools/two_runs.py`. Tests: `tests/unit/test_a_law_waits_only_for_what_can_still_change_it.py`,
`tests/unit/test_the_study_173_reading.py`, `tests/unit/test_the_lattice_starts_cost.py`,
`tests/unit/test_two_runs_of_one_design.py` (new). Documents: `docs/agent/NEXT_BUILD.md` (843),
`docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`, `docs/HISTORY.md`, `docs/DECISIONS.md`,
`docs/OPERATIONS.md`, `docs/TOOLS.md`. The schema did not change and neither engine did. One frozen source moved
(`decisions/let_through.py`) and was anchored again. Against 841's record (`tools/outputs_of_a_law.py --against`) no
output moved.

## A law waits only where something is still learned

The gates of study 173 each carry a share of their own, 0.1 for the six that act and 1 for every other, so no share
is learned from earlier laws and no known result either (repeats_a_known_result only records). Yet on 841 a law still
waited to decide at a size while 100 or more earlier laws were undecided there (`FixedPoints.determined`, 834's rule,
which counts the earlier laws still open as if each could move a learned share). It changed no decision, only when one
was made. `let_through.learns` now asks whether anything is learned: a gate without a share of its own
(`learned_gates`; in 172, empty, too dense and disconnected) or a repeats_a_known_result that acts
(`known_results_learned`). Where nothing is, a law decides on its own rungs at once and its inputs carry no `learned`.
172's design learns from 256 as before. Study 173 runs on 841, so its two runs both have the wait.

## Study 173's reading

`tools/study_173_reading.py` reads P1 to P12 of `study_173_criterion.json` in one command, each held, missed or not
read, and says when the study is not done (a progress reading) or the bundle is another study's (a dry run). Dry run
on 172's last bundle (46 s, about 150 MB): P1, P2, P5, P9, P10 and P12 hold; P3, P4, P6, P7, P8 and P11 miss, as 172's
rules should (its judgment gates record only, so 81% of the laws they would stop went on at 4,096, and nothing_read on
4,096 nodes would have withheld `4c5892bd611b` and `dfd97f6ae8c9`).

## What the lattice starts cost

`tools/lattice_cost.py` reads 841's chains table: by size the twins' work and the six lattices', by start, the lattice
chains frozen (no move accepted on any seed of the law at the size), the lattices' share of the work and seconds from
4,096, and for each scoring law its lattices' share of its work and whether a twin earned any of its points. 172's
bundles were made before 841 and carry no chain's work; on them it says so. On 172's last bundle all 29 scoring laws
earn their points through a lattice start alone.

## Two runs of one design

`tools/two_runs.py` reads the rerun against the first run (the operator, 22:57). The same: the laws, rungs, draws and
chains tables row by row without what is the host's own, every law's decisions in order without the deep lane's holds
and releases and without what records when a decision was made (the lane, what the law learned from and waited for,
counted apart), and report 28's seeds without their timing; each difference by law id. The speed: wall time from the
campaign's creation to its last decision, worker-hours, the workers busy on average, the gain (the same work in both
runs, so the ratio of wall times) and, size by size, each seed's seconds in the rerun over the first run. A run
stopped part way (the operator, 23:21: the first run may be restarted "whatever number it is") is compared on what
both finished: a law's row where both ended it, a rung with its chains and seeds where both were past it (ended there
or decided at a larger size, so a longer chain still to come cannot change it), each law's decisions as far as the
shorter goes; and the speed is then the work of the rungs each run decided in the same window from its start, the
shorter run's length, by size. 172's progress bundle against its last bundle, the same folder five hours apart: the
same on 1,743 laws, 8,186 rungs and 196,464 chains both had finished, window gain 1.0. On 172's last
bundle against itself: the same, 61 s, 261 MB; against 172's progress bundle it names the 164 laws that decided again
and the 176 seeds that finished since.

## The readers that held every decision

`tools/decision_index.py` copies a bundle's decisions table once into a SQLite file in a scratch folder and serves
them law by law, by size, or one by one. `tools/counters_reading.py`, `tools/study_172_reading.py` and
`tools/design_on_a_bundle.py` read from it: on 172's last bundle 139, 144 and 273 MB where they held 1,032, 1,033 and
1,278, each reading byte for byte as before. At 100,000 laws they would have held about 38 GB; now their memory is flat
and the disk holds the decisions' own size. The readers of report 28 and of the chains table still read a campaign
whole, about 500 MB at 2,500 laws, so about 2 GB at a batch of 10,000.

## 172's last bundle, read at 22:05

Every decision replays; R1 to R3, R5 and R6 hold, R4 misses (the disconnected gate confirmed), R7 not judged (727 laws
going, 236 core-hours spent). 29 drawn laws score, every one through a lattice start; replayed under 173's design none
is stopped, nor with its six gates closed; every prediction of 173 stays in its range. Nothing in it changed 841.

## The rerun on 32 workers

Make the first run's bundle (it may be stopped part way), then unpack 841 again in a new folder and run `uv run python
main.py run --study 173 --workers 32`: the same seed, laws and chains; `--workers 32` holds 32 slots from the start
(the ramp never goes below the count given), where `GSD_MAX_WORKERS=32` alone would let it stop near 24 at its 75% CPU
target. Run to its end, the rerun also gives 173's whole reading, its laws the same. The host has 92 GiB and admission lends about 43: at 65,536 a seed takes 1.65 GB at the median
and 6.3 GB at the most, so the governor will hold some back there, and the gain at the top sizes may be memory's, not
the cores'. Send both bundles; `tools/two_runs.py first second` reads them.

## Verification

3833 passed in 1054.36s (3 lanes at once)
