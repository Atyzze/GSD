# Build 831: the gates' counters are the study's. Every batch of a study learns from every batch's laws at the same fixed points; read on study 170's bundle, the shares 527 of its 4,808 learned decisions met would have changed, all from 4,096, and not one decision would have. Nothing study 171 runs moves (one batch): no need to apply it there.

**Type: the operator's word of 2026-11-20 10:32 built ("They should technically function as 1 study"), with study
170's bundle sent again at 14:20.**
New: `tools/counters_reading.py`, `graph_scale_dynamics/resources/readings/study_counters_criterion.json` (committed
before the tool first read a bundle), `tests/integration/test_the_study_learns_as_one_postgres.py`,
`tests/unit/test_the_counters_reading.py`. Changed: `db/decision_store.py` (`study_batches`, `learning_laws` and
`learning_rows` over every batch), `decisions/let_through.py` (`FixedPoints`: `campaigns`, and the asking batch's own
numbers), `decisions/decider.py` (`learned_for` records `campaigns` where there are two or more; the science freeze
written again, the table's lock unmoved), `tests/fixtures/committed_readings.json` (the criterion's pin),
`tests/fixtures/science_freeze.json`, `docs/DECISIONS.md` ("784's one let-through rule"), `docs/TOOLS.md`,
`docs/HISTORY.md`, `docs/ROADMAP.md`, `docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`.
Missing from 830's notes: `tests/unit/test_the_controller_outlives_a_busy_database.py` changed there, its fake counting
a pass by the pause flag alone, since the pass now also reads the auto-extend flag.

## What changed

Until 831 a gate's counters were a batch's: `DecisionStore.learning_laws` read one campaign, so in 170 a gate learned
from at most 400 laws of its own batch while `gates_ledger.json` and `docs/DECISIONS.md` spoke of the study. Now
`learning_laws` reads every campaign of the folder's study (the same `study_design.study`) on the same rules (the same
policy fingerprint, the same let-through rule), each in its place in the study's design (`study_batches`). The groups
are cut as before by each law's number within its batch (`learn_in_batches_of`, 100), so group g holds those numbers of
every batch, and a law of group g learns once every law of the earlier groups, in every batch, is past the size: the
batches go on side by side, as they run. A batch numbers only its own laws (`FixedPoints.refresh(..., own=)`), since one
law can be drawn in two batches. A campaign outside a study, or alone in it, reads itself: for one batch every
learning is what it was, and a decision records what it recorded (`campaigns` only where two or more are read), so 171,
169 and every single campaign learn and record as before.

**What it costs**: a batch given a smaller share, or paused, holds the other batches' later laws at `pending: learning`
until its own earlier laws are past the size; with equal shares, as the studies so far, they keep pace.

## Read on 170's bundle, criterion first

`study_counters_criterion.json`, committed at 14:01Z before the tool read any bundle; `python3 tools/counters_reading.py
study_170_2026-11-20T09-08-14Z.tar.zst`, about 15 s:

| | |
|---|---|
| C1, every decision replays | held: 9,843 of 9,843 |
| C2, the tool's own per-batch learning gives every learned decision what it recorded | held: 4,808 of 4,808 |
| C3, the first group alike both ways | held |
| C4, the standing controls (another policy) read by neither | held: batches 1 to 5 read together, campaign 6 not |

Study-wide, what 170's laws would have met (reported):

| size | learned decisions | the same learning | learning changes, decision does not | decision changes |
|---|---:|---:|---:|---:|
| 256 | 2,500 | 2,500 | 0 | 0 |
| 1,024 | 1,486 | 1,486 | 0 | 0 |
| 4,096 | 819 | 294 | 525 | 0 |
| 16,384 | 3 | 1 | 2 | 0 |

The shares that change, by gate: `kept_shape` 525 at 4,096, `starts_apart_by_history` 71, `empty` 33 and `too_dense` 33
at 4,096, `starts_apart_twice` 2 at 16,384. A law learned from up to 400 laws of its own batch; study-wide up to 2,000.
At 256 and 1,024 every learned decision meets the same shares either way. Of the 527 that meet other shares, none
changes its action or rule when replayed on them; why each does not is not read here (its draw against both shares
would say). On a larger study, or one whose batches differ, decisions can change: the next gated study is read for it.

169 read the same way: one batch, 277 learned decisions, every one the same both ways.

## What moved

Against 828's record (829 and 830 met it): 0 outputs. The table's lock as at 828.

## Left

The consolidation, due (16 builds since 815): 832, unless 171's final bundle comes first. 171's bundle is read whole
by the build it reaches.

## Verification

3702 passed, 2 skipped in 1097.35s (3 lanes at once)
