# Build 854: the baseline of two bundles, the still criterion judged, the sampler's trap from empty measured, an outside review answered, the paper drafted and the handover made for the next context. It changes no code, no decision and no score

**Type: a consolidation and a handover, asked for by the operator on 2026-11-24 at 16:30 ("lets make the next build a
best possible hand over from this iteration onto the next consolidation, the recycle/analyze-revisit past-data sets
for potential new decisions in the present, learn from mistakes etc"; "write the paper around, in the most grounded
way possible with 0 zero overclaims"), with an outside review of the code attached, and the baseline set at 16:33 and
16:34 (`docs/HISTORY.md`, "Studies").** New: `docs/paper/GSD_PAPER.md`,
`graph_scale_dynamics/resources/readings/still_lattice_judged_1.json` (pinned in
`tests/fixtures/committed_readings.json`, named in `docs/readings/README.md`). Changed: `docs/agent/HANDOFF.md` (its
opening, what is live and what waits rewritten on the baseline), `docs/agent/NEXT_BUILD.md` (855 and 856),
`docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md` (item 3, item 4 with the measurement), `docs/LESSONS.md` (six lessons
under "Evidence"), `docs/HISTORY.md` (three standing decisions), `README.md` (the paper in the reading list, below the
operator's opening). No file under `graph_scale_dynamics/`, `engine_rs/src/`, `tools/` or `main.py` changed but the new
judged reading; against 852's record (`tools/outputs_of_a_law.py --against`; 853 moved none against it either) 0
outputs moved.

## The baseline

Study 174's bundle of 2026-11-24 14:22Z (built on 850; sent at 15:56 and again at 16:33, the same bytes) and study
175's of 2026-11-24 08:35Z (sent again at 16:33, the same as at 09:53), with the calibration table, and nothing older.
The paper rests on them alone; the instrument's known answers stay, as checks of the instrument rather than data of a
study. Every older study's files leave the tree at 856 (`docs/agent/NEXT_BUILD.md`).

## The still criterion, judged

`still_lattice_criterion_1.json` (committed 2026-11-24 09:41:48Z) on 174's bundle of 14:22Z, the first sent after it,
by `tools/catalogue_reading.py`: **it passes.** S1: 89 of 89 lattice chains still at 1,024 with a deeper size are
still at every deeper size, and 39 of 39 at 4,096. S2: the 13 laws called still at 1,024 and the 21 at 4,096 are all
still at their deepest size; none is made or a ring. S3 (reported): 64 of the 83 laws the score in force scores are
still at the size they score at. Beside it, outside what the criterion asks: de7ab4a85198 was called frozen at 256,
1,024 and 4,096 and is made at 16,384, so an early stop by the frozen call would have stopped it. What follows, by the
criterion: the still lattice scores 1 in the score in force (855); stopping a law early by the still call is offered
with its saving, and the frozen call is not offered.

## The trap from empty

An outside review (2026-11-24) ran P1, the square-lattice law at beta 2, and found its run from empty stuck near 80%
of the lattice's energy at 256 and 1,024 nodes, with up to 64 times more sweeps and with annealing. 854 ran P1 and P2
under the survey's own policy (`tools/benchmark_campaign.control_spec`, 4,000 sweeps at every size), on the Rust
engine, seeds 0 and 1, on 853's code, and compared each chain's final energy:

| law | N | from empty | from the torus | share |
|---|---|---|---|---|
| P1 | 256 | -824, -811 | -1020, -1024 | 0.81, 0.79 |
| P1 | 1,024 | -3102, -3145 | -4096, -4096 | 0.76, 0.77 |
| P1 | 4,096 | -11206, -11154 | -16384, -16384 | 0.68, 0.68 |
| P2 | 256 | -848, -840 | -1024, -1024 | 0.83, 0.82 |
| P2 | 1,024 | -3227, -3175 | -4096, -4096 | 0.79, 0.78 |
| P2 | 4,096 | -11471, -11502 | -16384, -16384 | 0.70, 0.70 |

The review's measurement holds, and the share falls as N grows. The standing controls in 174's bundle say the same in
their own terms (`tools/positive_control.py check`): every positive control (P1, P2, C1) reads no finite dimension from
empty, as their criterion expected; P1 fails on its given chain (d_V 2.36 at 65,536 against 2 within 0.1), P2, N1, N2
and C1 pass. The script, run from the tree with the project's interpreter:

```
import json, sys
sys.path.insert(0, "tools")
import positive_control as PC
from benchmark_campaign import DEFAULT_SPEC, control_spec
from graph_scale_dynamics.services.worker.engine_registry import resolve_engine
from graph_scale_dynamics.scaleflow.one_shot import run_one_shot
from graph_scale_dynamics.scheduling.job_creation import initial_sweeps_multiplier, one_shot_policy
campaign = control_spec(json.loads(DEFAULT_SPEC.read_text()))
engine, simulate, _ = resolve_engine({})
laws = {law["label"]: law for law in PC.control_laws(PC.load_criterion())}
for label in ("P1", "P2"):
    for n in (256, 1024, 4096):
        for seed in (0, 1):
            law = laws[label]
            envelope = run_one_shot(law["spec"], n, seed, one_shot=one_shot_policy(campaign, n, law["candidate_id"]),
                                    initial_multiplier=initial_sweeps_multiplier(campaign, n), simulate=simulate)
            chains = envelope["descent"]["chains"]
            print(label, n, seed, chains["empty"]["final_energy"], chains["given"]["final_energy"])
```

## The outside review, point by point

| the review says | where it stands |
|---|---|
| Pre-registration, the engine's corrections, the probes' refusals, the let-through audit are sound | kept as they are |
| The runs from empty cannot succeed with this sampler | measured again here (above); `docs/ROADMAP.md`, item 4; a decision for the operator, the remedy recommended before more compute from empty (`docs/WHERE_WE_ARE.md`) |
| What settles is mostly the start remembered | the baseline agrees (64 of 83 scoring laws still); the still lattice scores 1 at 855 |
| Predict a lattice's hold by the energy change of every single move, before running | not built; offered after 855 (`docs/ROADMAP.md`) |
| Criteria that failed were adopted | listed as fails in the paper, section 3, and in `docs/LESSONS.md` |
| The deleted older data should be archived publicly | the archives exist beside the builds that took the data out; where they go public is the operator's (856) |
| Clean-clone tests fail for missing setup and should skip | the standing decision of 2026-11-21 removes a test that cannot run rather than skipping it; the cases the review saw are read at 856 |
| A five-minute path for a referee | asked of readers in the paper (section 9); planned, not built |
| Docs for outsiders | the paper is written for a reader new to the project, dates rather than build numbers |
| Git history is one commit a build | the operator's rule (2026-11-24 09:40); the commit message names the notes |
| The swap block duplicated in `run_chain`, `p_swap` unused | an engine change: with the sampler's, whenever that comes |
| The title overclaims | the paper's title follows the review's ("a pre-registered blind survey of local energy rules") and adds the instrument |
| How many phase-transition types | no finite list; the paper's musings name the ones this ensemble can show (percolation, the sparse/dense collapse, crystallisation) only as directions |
| An edge-triangle anchor for the fcc lattice | the same term was proposed in the conversation; in the paper's musings, not built |

## Past data read again for decisions now

* **H31 and fdc563a72c98 are small worlds** on the baseline (the reach from 3 to 4 steps over 1,024 to 16,384 nodes,
  every seed flagged small world, the mean degree the same on every start). The study after 175 was to look first at
  laws whose starts agree, H31 first; the merged study (855) reads such agreement through the small-world kind first.
* **The ten laws grown from the twins** are five open strings, four loops with 13, 35, 108 and 284 edges more than a
  ring at 65,536, and one chain of cliques; none settles under the score, rightly for the loops.
* **The early calls** (paper, 5.6): still and empty held at every size, frozen did not once, a ring 30 of 47 at 4,096:
  an early stop is offered for still only.

## For the folders

Nothing a folder decides or scores changes; 854 may be given to any folder or none.

## Verification

3896 passed in 1496.47s (3 lanes at once)
