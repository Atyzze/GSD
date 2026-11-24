# Build 832: the gates' counters are the study's, and now they're deterministic too. 831 made them study-wide but could feed a group a slower batch hadn't finished drawing; a second reader found it before 831 was delivered, so 831 was never sent. On study 170's bundle, 527 of 4,808 learned decisions would have met other shares, and none would have decided otherwise. Nothing study 171 runs moves (one batch).

**Type: the second reader's findings on 831's study-wide counters, fixed before delivery (the operator's word of
2026-11-20 10:32 carried, with 170's bundle of 14:20).**
Changed: `decisions/let_through.py` (`FixedPoints`: `read`, `drawing`, `closed`, `members`), `decisions/decider.py`
(`learned_for` records the batches read with their places), `db/decision_store.py` (`study_batches` reads each spec
once, catches a malformed one, reads only active batches with a share; `batches_drawing`), the science freeze written
again (the table's lock unmoved), `tests/integration/test_the_study_learns_as_one_postgres.py`, `docs/DECISIONS.md`,
`docs/LESSONS.md`, `docs/ROADMAP.md`, `docs/HISTORY.md`, `docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`,
`docs/agent/NEXT_BUILD.md`. 831 (`docs/build_notes/BUILD831_NOTES.md`) is in the tree as released and was not sent.

## What the second reader found in 831, and what was done

The diff was given to a second reader with what to look for (`docs/agent/ENVIRONMENT.md`, section 9: does every
decision replay, what the SQL selects, odd inputs). Checked against the code:

| finding | what | fixed |
|---|---|---|
| 1, medium-high | a group was fed once its existing laws were past the size; within one batch a later number means the earlier ones are drawn, across batches it does not, so a slower batch's later laws of that group, or laws a raised budget adds, were never read by a running controller while a fresh one would read them | a group is fed only once it is closed in every batch (`FixedPoints.closed`: the batch has drawn past it, or holds its whole law budget), and a fed group whose members change is learned from again (`FixedPoints.members`) |
| 2, medium | a paused batch's laws are never past the size, so it held every other batch's later laws | a batch paused by its share (0 workers), or not active, is not read but by itself |
| 3, low-medium | every batch's pass read every batch: batches² queries, specs read per call | each spec is read once (`_study_place`); the laws are still read per batch's pass (left: one `FixedPoints` a study) |
| 4, low | a malformed sibling spec raised outside the per-law guard and stopped the controller | `TypeError`, `ValueError`, `AttributeError` and `KeyError` read as "not this study's" |
| 5, low | `campaigns` named the campaigns with numbered laws, sorted as text | the batches read with their places, in the study's order |

Its other checks found nothing: every earlier decision replays (the replay reads `inputs["policy"]`, unchanged); both
queries select what they should (the same law in two batches kept apart, empty keys, null numbers); one batch, as 171,
learns and records exactly as before (`study_batches` returns it alone, `drawing` is not read, `campaigns` not recorded).

## Tested

`tests/integration/test_the_study_learns_as_one_postgres.py`, on PostgreSQL: the study's batches read in their places
and the standing controls not; a law of the second group learns from both batches and records them; one batch records
as before; and new, the reviewer's case: a law waits while the other batch has not drawn its group, learns once that
batch holds its whole budget (7 laws), and when a raised budget adds a law to a group already learned from, the group is
learned from again (8 laws, 8 decisions), as a fresh process would. Every let-through and decision-store test: 296
passed. 170 read again by `tools/counters_reading.py` (which reads a finished bundle, every group closed): as at 831,
C1 to C4 held, 527 learned decisions meet other shares, 0 decide otherwise.

## What moved

Against 828's record (829 to 831 met it): 0 outputs. The table's lock as at 828.

## Left

The consolidation, due (17 builds since 815): 833, unless 171's final bundle comes first. One `FixedPoints` a study,
the laws read once a pass (finding 3), with the reports in pieces for study A.

## Verification

3703 passed, 2 skipped in 1131.38s (3 lanes at once)
