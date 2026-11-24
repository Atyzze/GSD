# Build 830: auto extend now acts on a study. 829's switch was hooked to a completion that a study's batches never reach; 830 extends when every batch with a law budget reads done. Apply it to study 171's folder and restart, then tick auto extend; it moves no output 171 runs.

**Type: a fix of 829's auto extend, found reading study 171's bundle of 2026-11-20 13:17Z (the operator, 14:20).**
Changed: `operations/auto_extend.py` (`holds`, `finished`, `extend_if_all_finished` on the folder),
`services/controller/main.py` (`finish_pass`: the completion step and then auto extend, at the end of every pass),
`tests/integration/test_auto_extend_postgres.py` (written again on a study's own batch spec), `docs/ARCHITECTURE.md`,
`docs/OPERATIONS.md`, `docs/LESSONS.md`, `docs/HISTORY.md`, `docs/ROADMAP.md`, `docs/WHERE_WE_ARE.md`,
`docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`.

## What was wrong

829 hooked auto extend to the controller's completion step (`_completion`), which completes a campaign whose laws are
all decided. A study's batches are **continuous** campaigns (`study_design.campaign_spec` keeps the survey's
`"mode": "continuous"`; 171's bundle, `evidence/api_samples/campaigns.json`, and 169's and 170's the same), which that
step skips: they are never completed, so on 171 the switch could never act. 829's tests used the slice's bounded
campaign. The same fact is why a finished study's fleet never ends by itself (170's folder hours after its end): its
batches stay active with nothing to do.

## What it does now

At the end of every controller pass (`controller.finish_pass`), with auto extend on: when every campaign with a law
budget that is active or completed is **finished**, each gets 50 more laws and a completed one is active again.
Finished is the Campaigns page's **done** (`study.budget_state`: its budget reached, no law proposed, running or
extending, no job, analysis or rebuild queued or leased, no law held for a full deep lane), or `completed`. Raising the
budget clears its reached record, so the proposer draws the 50 from the campaign's own seed, as it drew the rest; until
they are drawn and decided the batch is not done, so nothing is extended twice. A campaign without a law budget (the
standing controls, active with laws running) neither counts nor is extended. A bounded campaign with a law budget is
held from completing while it is on (`auto_extend.holds`), so its fleet does not end before the pass extends it. A
stopped fleet (`paused`) passes nothing, so nothing is extended.

Tests (`tests/integration/test_auto_extend_postgres.py`, on PostgreSQL, through `finish_pass`, the batches made from
study 171's design by `study_design.campaign_spec`, continuous): off, two done batches are left as they are; on,
nothing while one batch is under its budget, then both from 3 to 53 laws once it is done, the standing-controls
campaign beside them untouched though busy, the budget no longer reached (room 50), every batch active and the fleet
with work, and the next pass extends nothing; a law in flight keeps a batch from done; a bounded campaign is extended,
not completed, and completes as before once the switch is off; the page's action as at 829.

## The three bundles

Sent at 14:20 with the operator's question, "I believe all of them are operating on the same architecture and only
differ in cleanup stages and gates config right?". Read from each bundle: every one is analysis-5.3.0 with the locked
probes (`estimator_fingerprint` e639334808716378 in each campaign's `evidence/calibration.json`), every decision by
`decision-engine-2` under rules revision 782. They differ by design (169: every gate recording, to 16,384 and the
let-through to 65,536, the tight budgets; 170: every gate on, five batches of 500; 171: the three fact gates on three
sizes in a row, budgets four times 170's at 4,096 and 16,384) and by build (813, 820, 829: no build since 813 moved a
probe, the table or an engine). 171's is a progress bundle (341 of 1,000 laws drawn, on 829): it is read whole when
it is done, against its criterion. Recorded as a standing decision (`docs/HISTORY.md`): 169 to 171 are the baseline,
nothing older is kept, and the baseline moves again after the larger run once the gates are tuned.

## What moved

Against 828's record, which 829 also met: 0 outputs (`tools/outputs_of_a_law.py --against`); the table's lock as at 829. Nothing a law
reads changed; the controller changes only with auto extend ticked.

## Verification

707 passed in 638.19s (fast lane, 117 test files)
