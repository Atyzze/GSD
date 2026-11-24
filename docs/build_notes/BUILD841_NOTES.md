# Build 841: the gated pilot's rules and study 173's design. For a new folder, to start study 173 in once study 172's last bundle is read and shows nothing new; not for study 172's folder, which makes its last bundle on the build it is on.

**Type: the third build of the plan the operator agreed on 2026-11-21 at 18:08, the one that changes what a study
decides and how a law scores, each change named here with its number on 172; the cut gate as the operator chose at
21:03, after 172's replay showed what stopping on it would lose.**
Changed: `graph_scale_dynamics/decisions/engine.py`, `decisions/every_chain.py`, `decisions/gates.py`,
`decisions/let_through.py`, `decisions/nothing_read.py`, `decisions/depth.py`, `observability/law_score.py`,
`reporting/study_tables.py`, `reporting/study_bundle.py`, `db/decision_store.py`, `services/api/landscape_worker.py`,
`services/api/study_scope.py`, `resources/ui/app.js`, `resources/ui/candidate.html`,
`resources/readings/studies.json`, `tools/gates_map.py`, `docs/diagrams/gates_and_streams.json` and `.svg`. New:
`decisions/cut.py`, `resources/readings/study_173_design.json`, `resources/readings/study_173_criterion.json`,
`tools/design_on_a_bundle.py`. Tests: `tests/unit/test_a_cut_law_is_stopped_by_a_gate_of_its_own.py`,
`tests/unit/test_study_173_is_the_gated_pilot.py`, `tests/unit/test_a_design_is_replayed_on_a_bundle.py` (new);
`test_an_unread_lattice_fate_is_not_a_move.py`, `test_the_score_reads_every_start.py`, `test_gates_map_is_current.py`,
`test_the_inputs_are_committed_in_one_place.py`, `tests/integration/test_the_bundle_carries_every_chain_s_peak_postgres.py`,
`tests/ui/dashboard_smoke.js`. `tests/fixtures/committed_readings.json` moved: 173's design and criterion pinned.
Documents: `docs/agent/NEXT_BUILD.md` (842), `docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`,
`docs/HISTORY.md`, `docs/DECISIONS.md`, `docs/OPERATIONS.md`, `docs/ARCHITECTURE.md`, `docs/RESEARCH_METHOD.md`,
`docs/TOOLS.md`. The schema did not change and neither engine did. Seven frozen sources moved (the decision rules and
the score) and one was added (`decisions/cut.py`), anchored again. Against 840's record (`tools/outputs_of_a_law.py
--against`) 8 outputs moved, all of the score's record: its contract (`gsd-law-score-6`) and the new kind `frozen` in
its weights, parts and names, on both engines; no simulation or probe output moved.

## What 841 changes

Every rule below is a design's to switch on, its default 172's, so 172's decisions replay as recorded and their
fingerprints hold (`engine.SET_FIELDS`). Study 173's design switches all of them on.

1. **nothing_read reads a piece of 0.9 of the graph** at 4,096 (`nothing_read_piece_share`; 4,096 nodes as before
   above). As built it withheld two of 172's scoring laws, `4c5892bd611b` (its largest piece 3,993 nodes) and
   `dfd97f6ae8c9` (4,071); at 0.9 it withholds neither.
2. **The ledger counts the verdicts of a law stopped over_budget** (`ledger_counts_priced`): a price is not a gate,
   but the gates that law carried had judged it, and those verdicts were lost. 6 of 172's 53 such laws carried one.
3. **A longer chain is priced on twice its size's budget** (`longer_chain_budget_scale`), and runs on it: 27 of 172's
   33 over_budget stops at 4,096 were a longer chain refused, by a median of 31%; 23 of the 27 fit twice the budget.
4. **The cut gate** (`decisions/cut.py`, `cut_gate`): a law with a seed that ended at its budget at the size it is at
   carries the verdict `cut` on any decision that buys a larger size or a longer chain. At a share of 1 the law goes
   on with the verdict recorded; below 1 it stops there, its share let through. See the next section.
5. **A gate's own share holds when it confirms**: study 173 gives each acting gate 0.1, so the tenth stays a tenth
   through the pilot (asked at 19:41).
6. **A frozen lattice scores 1**: a lattice start whose fate is `unmoved`, no edge changed, is `frozen`, and a law it
   leads scores 1, the lowest score there is (19:54, 20:02). On 172 it takes 6 of the 22 scoring laws to 1:
   `09d2c6a28f26` and `e52e8977d2ef` from 9, `0cb505d91226`, `6384df0c26d0`, `68fbea14f8c1` and `697cb47d0785` from
   3; `613fda38b56b` keeps 3, now by its tesseract start, which held and moved.
7. **The fleet table's budget stops**: `priced` (the over_budget stop, before a run) among the stops; `stopped cut`
   beside it once a design's cut gate has stopped a law; the evolving `cut` column stays, since a cut does not stop a
   law in 172 or 173.
8. **The chains table carries each chain's work**: its moves, its accepted moves (none: no edge changed), its work in
   the campaign's unit with the six counts the unit weighs, and its seconds in the engine, all from the run's compact
   evidence. 173 measures with it what the lattice starts cost above 4,096 and whether a kept lattice moved.
9. **Study 173's design and criterion**, committed before any start.

## The cut gate, and what the operator chose

At 19:26 the operator asked whether a cut law should be stopped as `cut` rather than let climb, and agreed at 19:41
to a gate that stops it, a tenth let through. 840's notes said that 8 of the 22 scoring laws had a cut seed, "none of
the top eight". That was wrong: it read an earlier score. Replaying 172's decisions under 173's design
(`tools/design_on_a_bundle.py`) showed the gate stopping 7 scoring laws at 4,096, below the size they score at:
`93cbf73f1bd6` (16, 172's second best; one of its three seeds cut, all three finished at 65,536), `4dafa634fd79` (7),
`8a45be901ece` (3, one seed cut), `19b4e3f4dd0a`, `4335e4d252a3` and `f3fa2927afde` (3 each, every seed of a longer
chain cut on the single budget) and `0cb505d91226` (now 1, frozen). Laws with a cut seed score about 12 times as
often as the rest: 8 of 117 against 14 of 2,383. Asked with the two options, the operator chose at 21:03 to record
it only ("Record only"): no scoring law lost, about 25 core-hours more, and about 85 cut laws followed a size up to
judge the gate on, against about 9.

## 172 replayed under 173's design

The tool replays each law's decisions in order under the design's policy, follows a law until the design stops it,
and carries each size's shares to 2,500 laws. Under 172's own design it gives back 172's recorded stops (empty 896,
disconnected 519, too dense 214, over_budget 53) and about 750 core-hours, against the 880 committed for it.

| size | laws (2,500) | a gate would hold | let through | stopped | core-hours |
|---:|---:|---:|---:|---:|---:|
| 64 | 2,500 | 0 | 0 | 0 | 4.4 |
| 256 | 2,500 | 0 | 0 | 15 | 6.3 |
| 1,024 | 2,485 | 1,540 | 154 | 1,391 | 12.9 |
| 4,096 | 1,094 | 970 | 113 | 891 | 39.5 |
| 16,384 | 203 | 50 | 5 | 130 | 25.4 |
| 65,536 | 72 | 0 | 0 | 0 | 68 |

About 150 core-hours in all (144 at the bundle's mean a law), against about 750 for 172: half a day on the host's 16
workers. At that rate study A's 100,000 laws would take about 6,000 core-hours, some 16 days, inside the month. The
starts_alike, starts_apart_by_history and nothing_read gates together hold back 778 of 172's laws and none of its 22
scoring laws. Over_budget stops fall from 53 to 24, 4 of them at 4,096. Of the cut laws followed a size up, 68 of 84
are cut there again. The 65,536 row rests on 7 laws, the least sure number here; the criterion's ranges say so.

## Study 173

`study_173_design.json`: 172's design, its grid, starts, ladder and budgets, on a search seed drawn with
`secrets.randbits(63)` at 2026-11-21T19:43:46Z (7464432861296460523); six gates acting at a tenth (empty, too dense,
disconnected, starts_alike, starts_apart_by_history, nothing_read), every other gate at 1, cut among them, and the
four settings above. `study_173_criterion.json`, committed at 20:07Z: P1 to P12, each from the replay with its range
(the six's tenth 7% to 13% at 1,024 and 4,096; the fact gates stop 51% to 61% at 1,024; the six stop 75% to 87% at
4,096; 150 to 260 laws reach 16,384 and 30 to 110 reach 65,536; at most 12 over_budget at 4,096; 60% to 92% of cut laws
cut again a size up; cut laws score at least twice as often; at most one law let through past the three judgment
gates scores; about 150 core-hours, 100 to 260), and what is reported beside them, the lattice starts' cost above
4,096 among it.

Started in a scratch folder on this tree with two workers (`main.py run --study 173`): the campaign carries the
design's rules (the six acting gates, `cut_gate`, the piece share, the longer chain's scale, the ledger's count);
within minutes 85 laws were admitted and the first 19 decided at 64, each going on to 256, and at its ten minutes'
wall the fleet drained and its PostgreSQL stopped cleanly.

## What the operator does

Make study 172's bundle one last time on the build its folder is on, and send it. I read it as the last check; unless
it shows something 173 should take, unpack this archive in a new folder and run `uv run python main.py run --study
173`. If it does, one more build first.

## Verification

3823 passed in 1095.31s (3 lanes at once)
