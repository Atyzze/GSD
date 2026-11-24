# Build 834: a law no longer waits for what cannot change its decision, and a law that waits gives up its place. For study 171's running folder, by the operator's word of 2026-11-20 23:37: apply it the moment it is delivered.

**Type: a fix to a running study's scheduling of decisions, by the operator's word ("fix now please, i am not waiting
for it to auto resolve. So new build, that I will apply the moment it's available"; 23:47: "I mainly want it fixed so
that this or similar situations never happen again").**
Changed: `decisions/let_through.py` (`FixedPoints.determined`, `settled`, `records_only`, `determined_policy`;
`learned_policy` learns no signatures for a seen_enough that only records), `decisions/decider.py` (`learned_for`),
`db/decision_store.py` (a held law marked in `learning_laws`; `record_pending` keeps the pass's waiting laws),
`scheduling/admission.py` (`note_waiting_to_learn`, `waiting_to_learn`, `without_the_waiting`, the flag
`learning_waits:<campaign>`), `services/controller/engine_campaign.py`, `services/proposer/main.py`,
`operations/lifecycle_recovery.py` and `services/api/overview.py` (the dashboard names a wait to learn),
`resources/ui/app.js` (an informational wait is not drawn as a warning). New:
`tests/unit/test_a_law_waits_only_for_what_can_change_it.py`, a case in
`tests/integration/test_admission_counts_the_base_block_postgres.py`. The schema did not change. The science freeze
was re-anchored (`tools/science_freeze.py --write`) for `decisions/decider.py` and `decisions/let_through.py`, the
two frozen sources this fix changes; no estimator changed.

## What the operator saw

Study 171 on 830 at 22:20Z: 48 laws `BASE_BLOCK_RUNNING`, every one `pending:learning` in the controller's heartbeat,
the oldest for 291 minutes; 2 laws above the base block (one simulation, one analysis at 65,536); 32 proposed laws
waiting; 14 of 16 workers idle; the dashboard calling it `RECOVERY_BLOCKED` and the laws `STRANDED`.

## Why

Since 806 (learning at fixed points) a law of group g decides at a size only once every law of the groups before it is
past that size: decided one size up, or ended. In 169 and 170 most laws were stopped before 4,096, and an ended law is
past every size, so the wait was short. 171 (827, revised 828: three gates acting, budgets four times 170's, every law
they pass to 65,536) is the first study where most laws go deep: a later law's 4,096 decision waited for earlier laws'
16,384 verdicts, and theirs for 65,536. Those waiting laws held all 48 base-block places (`max_active_candidates` 48,
fewer than a learning group of 100), so no new law was admitted. Not a deadlock: the lowest-numbered law that has not
ended never waits to learn, so it moved, but at the pace of the deepest rung, group by group. 813's notes foresaw it at
65,536; 171 brought it into the base block.

In 171 the wait bought nothing. Every gate but three has its own share; the three can move from 10% to 1% only after
100 clean let-through laws at one size, which needs about 1,000 laws they would stop there; seen_enough records only.
No decision of 171 depended on what the waits waited for, except seen_enough's mark.

## The fix

* **A law decides as soon as no earlier law can change what it learns** (`FixedPoints.determined`): every earlier law
  ended or decided at the size (a held law is not), fewer than `confirm_after` let through there by any one gate whose
  share is learned, the undecided counted as if each would be, and, where seen_enough can withhold there, fewer than
  `seen_enough_after` sharing any one signature, the undecided again counted. Then every learned gate's share is 10%
  and no signature is seen, which is what the whole ledger would give; the decision's inputs say so (`learned.determined`
  with the counts, no shares listed). Otherwise the law waits as before for the whole ledger. The whole ledger, when it
  is ready first, is used as before.
* **A seen_enough that only records learns no signatures**, in either way of learning, so whether a law is marked never
  depends on timing. This is the one thing 171 records differently from 834 on (the operator's word, explained to them
  first).
* **A law waiting to learn gives up its admission place**: the controller writes the base-block laws its pass left
  waiting, at most one learning group (`learn_in_batches_of`), to the flag `learning_waits:<campaign>`; its admission
  and the proposer's window leave them out. Nothing a law decides depends on when it was admitted.
* **The dashboard names the wait**: laws the controller's last pass left `pending: learning` are not counted stranded
  (so not `RECOVERY_BLOCKED`), and both alerts say what they wait for, as information.

## What moved

Against 833's record (the 832 tree's, written before 833's first change; 833 changed no code): **0 outputs**.
`tests/unit/test_a_law_waits_only_for_what_can_change_it.py` decides the same law with and without the whole ledger,
at a mean degree the empty gate withholds and one it passes, and gets the same action, rule, next size, facts and
reason. 806's test of three orders still gives the same shares. In 171: every decision as it would have been, sooner;
seen_enough's mark absent from decisions made on 834.

## Left

Where seen_enough or a gate can still change a share at a size (170's design: seen_enough acting), the wait is the
whole ledger's; the narrower one, for the laws let through by that gate or sharing the law's own signature, is in
`docs/ROADMAP.md`, "Unscheduled". `tools/counters_reading.py` compares the shares listed; a determined decision lists
none, so it compares the shares met before it is read on 171.

## For the operator

Apply 834 to study 171's folder (stop, apply, start, as before; nothing else changes). On the next controller pass
the 48 laws decide and new laws are admitted; the dashboard should show the workers filling within minutes.

## Verification

3712 passed, 2 skipped in 1454.48s (3 lanes at once)
