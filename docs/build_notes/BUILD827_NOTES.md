# Build 827: study 170 read from its bundle, and study 171, the baseline, carried: start 171 on this build in a new folder. Only the empty, too dense and disconnected gates and the budget stop a law; every other gate records; the budgets are four times 170's at 4,096 and 16,384.

**Type: study 170's bundle (2026-11-20T09:08:14Z) read first, against its criterion; the operator's answers of
2026-11-20 10:09 to 10:32 carried (the budgets, the baseline study, its size; the gates' counters).**
Changed: `graph_scale_dynamics/resources/readings/study_171_design.json` and `study_171_criterion.json` (new),
`resources/readings/studies.json`, `tests/fixtures/committed_readings.json`,
`tests/unit/test_the_baseline_study_stops_a_law_only_on_the_facts.py` (new), the two tests that name the designs in
the tree, `docs/OPERATIONS.md`, `docs/DECISIONS.md`, `docs/RESEARCH_METHOD.md`, `docs/HISTORY.md`, `docs/ROADMAP.md`,
`docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`.

## Study 170, read against its criterion

2,500 laws in five batches of 500 on build 820, every gate on from 256 with the learned let-through, and the five
standing controls (campaign 6); started 01:48Z, done at 05:26Z. 21,873 seeds, 31.2 core-hours of simulation, the
controls left out.

| | predicted | read | |
|---|---|---|---|
| R1 | every decision replays | 9,843 of 9,843, 0 differ, every one with its inputs | holds |
| R2 | no zero-temperature seed `OPERATIONAL_UNRESOLVED` after a pass at the cap | none among report 23's ranked laws | holds |
| R3 | by 4,096 the gates withhold most laws, as 169's ledger said (837 of 910) | 2,377 of 2,500 withheld by 4,096 (95%) | holds |
| R4 | 40 to 100 core-hours a 1,000 laws | 12.5: 3 drawn laws reached 16,384 and none 65,536 | fails |

R4 fails low because the budgets, not the gates, ended the ladder: almost nothing ran past 4,096.

**What the gates withheld** (`gates_ledger.json`, every batch added):

| size | withheld | let through | held again a size up | missed | open |
|---:|---:|---:|---:|---:|---:|
| 256 | 1,006 (empty 817, too_dense 189) | 110 | 95 | 2 | 0 |
| 1,024 | 614 (disconnected 443, empty 118, too_dense 53) | 67 | 53 | 0 | 1 |
| 4,096 | 755 (starts_alike 461, nothing_read 85, starts_apart_by_history 54, disconnected 60, empty 39, no_steady_chain 35, too_dense 19, kept_shape 2) | 0 | 0 | 0 | 0 |
| 16,384 | 2 (starts_apart_twice) | 0 | 0 | 0 | 0 |

Every gate stayed `testing`: none reached 100 clean in a row, so none dropped to 1%. At 4,096 nothing was let
through: each gate draws its own die, and a law there meets two or three gates, so it goes on only if every one of
them lets it through (about 1 in 100 to 1 in 1,000). The two misses (an `empty` and a `too_dense` verdict at 256 not
held a size up) and the one open law do not score.

**The budgets** (`tools/budget_reading.py`): 784 of 4,096's 2,406 seeds (33%) and 274 laws were cut there, 35% of
the connected laws; 43 of the 46 laws that passed every gate at 4,096 were stopped `over_budget` before 16,384. At
four times the budget at 4,096, 97% of the cut seeds are estimated to reach their end, for about 13 more core-hours
(at most 22). 139 seeds ran past their budget (the budget is read between chunks), one 35 times over.

**What scores** (`tools/score_list.py`): the three standing controls that should (57, 50, 46, every one to 65,536),
and one drawn law, `4b871e50e3b4`, 15 on its triangular start at d 2.14, stopped `over_budget` at 16,384: its longer
chain was predicted at 4.36e12 units against that size's 2e12.

**The pilot's predictions** (`tools/pilot_reading.py`): K1 to K5 and K8 hold, none broken.

## The gates' counters are a batch's

The operator asked at 10:32 whether the gate counters are per batch. They are: `decisions/decider.learned_for` learns
from `store.fixed_points(campaign_id)`, whose laws come from `DecisionStore.learning_laws(campaign_id)` and rows from
`learning_rows`, each `WHERE campaign_id=?`. So each of 170's batches learned from its own 500 laws, while
`gates_ledger.json`, Home's box and `docs/DECISIONS.md` showed or said the study. In 170 it changed nothing: no gate
reached 100 clean even study-wide (`empty` at 256 let 89 through with one miss). The pages now say what the code does,
and making the counters the study's is planned before any gated study runs again (`docs/ROADMAP.md`, "Planned builds",
9a; the operator: "They should technically function as 1 study"). The batches stay as units of work and reporting (the
operator, 10:32: "for later when doing 100k laws, splitting the work seems logically reasonable"); what they cap is a
report's size, and the underlying fix is reports that read their tables in pieces, for study A's batches of 20,000.

## Study 171, the baseline

The operator, 10:09: "a bigger study with no gates at all just to gather data on the absolute baseline of what
happens if nothing at all is gated and all of them are run to 64k though with only the 4 absolute basic gates left
on that is empty/dense/disconnect and out of budget". Its design is 170's, with:

* 1,000 laws in one batch (the operator's choice of size), its own search seed `1455932840332106939` drawn with
  `secrets.randbits(63)` at 09:35:55Z;
* `gate_shares` at 1 for every let-through gate but `empty`, `too_dense` and `disconnected`: they record their
  verdicts and hold no law back. The three act from 256 with the learned let-through; `over_budget` and `failed` stop
  as always; `deep_lane_full` only holds a law until the deep lane frees;
* budgets 1.6e12 at 4,096 and 8.0e12 at 16,384 (four times 170's), 4e11 below and 2.4e13 at 65,536 as before.

Its criterion (`study_171_criterion.json`, committed before its first start): R1 every decision replays; R2 as 170's;
R3 no gate but the three holds a law back, and every law they pass ends at 65,536, `over_budget` or failed; R4 the
three leave 20% to 40% of the laws at 4,096; R5 at most 3% stopped `over_budget` before 65,536 and under 10% of
4,096's seeds cut; R6 about 280 core-hours a 1,000 laws (150 to 630), about 18 hours on the host's 16 workers (9 to
40). It reports every recorded gate replayed on the whole ladders at its own size and on a law's last four sizes (the
operator, 10:09), and the one die a law a size measured beside the gates' own dice, which waits for this bundle.

### 171's policy on 170's decisions

Every one of 170's 9,843 decisions replayed with 171's gate shares and budgets in its policy (each decision's own
inputs, nothing else changed): the only stops left are `empty` 945, `disconnected` 487, `too_dense` 258 and
`over_budget` 18; no other gate stops a law. 792 of 170's stops run on: 461 `starts_alike`, 105 `over_budget`, 85
`nothing_read`, 56 by the starts' history or twice apart, 35 `no_steady_chain`, 2 `kept_shape`, and 48 of 170's
fact stops. Those 48 are laws a fact gate stopped on some chains while another chain met a judgement gate: with every
chain deciding, a law stops only when every chain stops, so in 171 such a law goes on with the chain still running.
The 18 `over_budget` stops left are 8 at 1,024 (whose budget the operator kept) and 10 at 4,096. In
`tests/unit/test_the_baseline_study_stops_a_law_only_on_the_facts.py`: only the three fact gates have a share below 1
at any size, and the budgets are as decided.

## What moved

Against 826's record (`tools/outputs_of_a_law.py --write` on the untouched 826 tree first): **0 outputs**. No code
changed: a design, its criterion, the register, tests and pages.

## Left

The gates' counters the study's (828, criterion first, replayed on 170's bundle both ways). 171's bundle read first by
the build it reaches. The budget a hard stop inside a chunk, the ledger's `over_budget` verdicts and the fcc fate,
each measured on the bundles first.

## Verification

3676 passed, 2 skipped in 1369.40s (3 lanes at once)
