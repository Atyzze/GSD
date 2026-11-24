# Build 838: study 172's bundle made ready to read in a fresh context. Not for study 172's folder while its laws run: 172 runs on 835 to the end; after its last law it may be applied to make the bundle, as 836 may.

**Type: the handover that reads 172's bundle (the operator, 2026-11-21 14:12: "make sure it includes the needed
handover documents for that build to be ready to read the study Bundle in a new clean context"). Stable was started
too, unasked, and stopped at their word (16:11: "I do not remember approving doing the planted faults at this point
.... this is for much later on the roadmap"); asked as choices, they chose the handover alone, stable's tools and the
checks it found kept and not called stable.**
Changed: `tools/gate_variants.py`, `tools/bundle_growth.py`, `tools/planted_faults.py`, `tools/study_twice.py` (new);
`tests/fixtures/bundle_growth_171.json`, `tests/fixtures/planted_faults.json`, `tests/fixtures/numbers_and_checks.json`
(new); `.gitignore` (the twice folders). Tests: `tests/unit/test_the_gates_under_other_settings.py`,
`tests/unit/test_what_grows_with_the_study.py`, `tests/unit/test_the_planted_faults_are_planted_where_they_say.py`,
`tests/unit/test_every_number_is_traced_to_a_check.py`, `tests/unit/test_the_study_twice_comparison.py`,
`tests/unit/test_what_the_planted_faults_asked_of_the_gates.py`,
`tests/scientific/test_what_the_planted_faults_asked_for.py`. Documents: `docs/agent/NEXT_BUILD.md` (the procedure for
172), `docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`, `docs/HISTORY.md`, `docs/TOOLS.md`,
`docs/OPERATIONS.md`. **Nothing under `graph_scale_dynamics/` changed**: the schema did not, so a folder running now
opens this build; no frozen source moved; against 837's record (`tools/outputs_of_a_law.py --against`) 0 outputs
moved; the table's lock prints `analysis-5.3.0 e639334808716378 89f4fed82d9adc27`.

## 172's bundle, ready to read in a fresh context

`docs/agent/NEXT_BUILD.md`, "Where to begin", is the procedure: what 172 is and which build made its bundle; the tree
and the bundle; every reader in order, each with its command, what it answers, its time and memory on 171's progress
bundle and 171's numbers beside it (R1 to R7 in a table, the replay, the counters, the cap, the gates under other
settings, the budgets, the pilot readers); what grows with the study; what the notes say and what goes to the
operator. 171's numbers are written into it, since no bundle is in the tree. Two readers are new:

* **`tools/gate_variants.py`**: every decision of the study's campaigns replayed from its recorded inputs with one
  policy setting changed, for the roadmap's "the fact gates on three sizes in a row against one and four" and "one die
  against 171's separate dice"; each law whose fate changes counted at the first size it would. On 171's progress
  bundle: with one size in a row, 419 laws that went on would have stopped at 256 and 44 more later; with four, the
  594 the three gates stopped at 1,024 would have gone on, and 38 more later; with one die, at 1,024, 45 stopped
  would have gone on and 28 that went on would have stopped (835's reading by a scratch script, now a tool). It
  streams the decisions: 39 MB at its peak, 11 s.
* **`tools/bundle_growth.py`**: what grows with the study (the roadmap's next build, "measured on 172 before anything is
  built"): the bundle's and tables' sizes, the report cycles, the controller's last pass, each reader's time and peak
  memory as a child of its own, carried to 10,000 and 100,000 laws on a line through two bundles. 171's point is
  committed (`tests/fixtures/bundle_growth_171.json`): 1,005 laws, the decisions table 4,722 rows, 134.8 MB unpacked,
  `counters_reading.py` and `study_172_reading.py` 470 MB at their peak; in proportion alone, about 47 GB at 100,000
  laws, which 172's point tests.

The trend read against the seeds' own spread (the operator, 2026-11-20 11:48) has no reader: its rule is to be said
before it is read, and the procedure says where its data are.

## Stable, begun and stopped

Kept, so the run before study A starts from them (`docs/ROADMAP.md`, "Planned builds", 5): each number the paper states
with the code it passes through and its checks (`tests/fixtures/numbers_and_checks.json`, 18 numbers);
`tools/planted_faults.py` with 35 faults (`tests/fixtures/planted_faults.json`), which plants each alone in a scratch
copy and sets aside the tests that fail on any edit of the file (a neutral line added), since those hold its bytes and
not what it does; `tools/study_twice.py`.

* **The short study twice**: study 172's design cut to 4 laws, 64 to 1,024 and 3 seeds, the standing controls with
  it, run in two folders by the tool, then again in two more: all four bundles the same, every row of the laws,
  rungs, draws, decisions (their facts and inputs) and chains tables and every document, with the host's own fields
  left out. The list of those was set by reading each difference of the first pair: the decisions' `queue_depth`, the
  reports' revisions and cycle ids, the host's reports 14 and 25, report 28's seconds, memory and core columns, report
  23's order (by core-seconds). 11 minutes a folder. A study this short reads no let-through state, no size past 1,024
  and one batch.
* **The faults, as far as the run went** (stopped at the operator's word): of the 12 the whole run judged (the 21 test
  files that read `measurements/estimators.py` and `fits.py`, the 4 that read `walk_dimension.py`), 12 caught, 3 of
  them by checks written for this; of the rest, 9 more caught (3 in a first whole run, 6 on the test files nearest
  each) and 4 let by and given checks. 7 let by in all, each now caught:

  | fault | what it would corrupt | the check that catches it |
  |---|---|---|
  | `d_V_growth_verdict` | balls between a power and an exponential called exponential | `test_balls_that_neither_curve_fits_by_the_margin_are_undecided_and_not_exponential` |
  | `d_s_settled` | a running slope that still moves read as settled | `test_a_running_slope_that_moves_past_its_margin_is_refused_and_one_within_it_is_read` |
  | `fit_exponential_margin` | box counts between the two lose d_B's precondition | `test_box_counts_between_a_power_and_an_exponential_keep_the_power_law_s_precondition` |
  | `kappa_pentagons` | the fallback counts a pentagon through its own vertex | `test_the_fallback_counts_each_edge_s_short_cycles_as_its_simple_paths` |
  | `gate_empty` | a law at ten times the empty mark stopped as empty | `test_a_law_just_above_the_empty_mark_is_not_empty_and_one_at_it_is` |
  | `budget_fits` | a first chunk at twice the budget let run | `test_a_first_chunk_predicted_past_the_budget_does_not_fit_and_one_within_it_does` |
  | `replay_blind` | a record saying another action, rule, size or reason still replays | `test_a_record_that_says_another_decision_than_its_inputs_give_does_not_replay` |

  The fallback's fault moves the curvature only on sparse graphs (3 edges of a 60-node graph with 60 edges), where the
  existing parity test, on denser ones, could not see it. One fault was a change to nothing: `decisions/gates.CONFIRM_AFTER`
  is read by nothing (`Policy.confirm_after` is the default), so the fault now sits there; the constant goes with the
  next change to `decisions/`. Not judged: the score's three faults, the chain's equilibrium, the work count, the draws,
  a start's fate, the finite-size tolerance and the giant fraction (whose only failing test in a first run was one that
  holds the file's bytes).

## For the operator

Nothing to do while 172 runs. When it reads **done**: untick auto extend, and if you want every chain's peak in its
bundle, stop, apply 836 or later (this one changes nothing the fleet reads), start and make the bundle; then send it
with this archive to a new conversation, which reads it by `docs/agent/NEXT_BUILD.md`.

## Verification

3780 passed in 1294.46s (3 lanes at once)
