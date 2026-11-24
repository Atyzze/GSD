# Build 835: study 172 designed while 171 runs, one die a law a size, `seen_enough` named `repeats_a_known_result`, and the small things of 02:32. Not for study 171's folder: 171 stays on 834; 172 starts in a folder of its own once 171 is stopped.

**Type: a new study's design and criterion, a design field for the gates' pick, a gate's rename read both ways, and
fixes to wording, a button and the test register (the operator, 2026-11-21 02:32 and 02:59, and their choices at
02:59: "Bigger baseline", "Yes, one pick", "2,500 laws").**
Changed: `decisions/engine.py` (`Policy.one_die`, `known_result_after`, `known_result_from`, `known_results`;
`SET_FIELDS` leaves `one_die` out of a fingerprint when off; `FORMER_FIELDS`, `in_today_s_fields`; `over_budget_reason`),
`decisions/gates.py` (`die`, `drawn(..., one_die=)`, `FORMER_NAMES`, `DIE_LABELS`, `today`, `in_today_s_words`),
`decisions/seen_enough.py` moved to `decisions/known_result.py` (`GATE = "repeats_a_known_result"`, its contract
`gsd-seen-enough-1` kept), `decisions/let_through.py`, `decisions/every_chain.py`, `decisions/replay.py`
(`reason_in_today_s_words`; a recorded policy, facts and words read in today's names),
`operations/quiet_report.py` (a second ask joins the bundle under way), `operations/study.py`,
`operations/lifecycle_recovery.py`, `reporting/study_reading.py`, `resources/ui/app.js` (the bundle button, the
ladder's `ended` and `parked` tooltips, the gates box), `tools/counters_reading.py` (compares the shares a law met),
`tools/gates_map.py`, `tools/test_suite.py` (`ALLOWED_SKIPS` empty). New: `resources/readings/study_172_design.json`,
`resources/readings/study_172_criterion.json`, `tests/unit/test_one_die_and_the_gate_s_new_name.py`,
`tests/unit/test_a_park_over_budget_says_which_run_it_priced.py`, `tests/support/criteria.py`, a case in
`tests/unit/test_the_baseline_study_stops_a_law_only_on_the_facts.py`. Removed:
`resources/readings/controls_criterion_5.json`, `tests/unit/test_a_capability_does_not_survive_the_namespace.py`
(its other test kept as `tests/unit/test_a_sidecar_in_the_namespace_says_so.py`) and
`test_the_parallel_path_returns_byte_identical_checks` in `tests/unit/test_benchmark_battery.py`.
`tests/fixtures/committed_readings.json` moved: criterion 5's pin out, 172's design and criterion pinned.
`resources/readings/studies.json`: 171's line as it stands, 172's added. The science freeze was re-anchored
(`tools/science_freeze.py --write`) for `decisions/engine.py`, `every_chain.py`, `gates.py`, `known_result.py`,
`let_through.py` and `replay.py`; no estimator changed, and the table's lock prints `analysis-5.3.0
e639334808716378 89f4fed82d9adc27`. Against 834's record (`tools/outputs_of_a_law.py --against`), 0 outputs moved.
The schema did not change.

## What the operator asked

At 02:32, with 171's progress bundle: the two tests skipped every build removed ("is there a point to either if both
of them have been skipped for so many builds already"); `seen_enough` kept but not acting until the other gates are
tuned, the laws that reach the same result still to be found; the rename ("Yes, that is a better name indeed, its
exact"); the narrower wait left until there is more data; the ladder's tooltip ("park != stop I guess?"); the study
bundle's button disabled on the first click. At 02:59: "do we really need to wait for study 171 final bundle? cant we
instead already move on to designing study 172 instead? ... perhaps we'll make a few new tweaks to the gates, but no
reason to wait with the rest of the work no?" Asked as choices, they took the bigger baseline, one pick, and 2,500
laws.

## Study 172

`study_172_design.json` is 171's design at 2,500 laws in one batch with `engine.one_die` on: the empty, too dense and
disconnected gates act, each on three sizes in a row, with the learned let-through from 256; every other gate's share
is 1, `repeats_a_known_result`'s too; the budget stops a law; every law the three pass runs to 65,536; budgets,
ladder, starts and grid are 171's. Its search seed was drawn with `secrets.randbits(63)` at 2026-11-21T02:17:09Z.
`study_172_criterion.json` was committed before any start: R1 every decision replays and the counters give what was
recorded; R2 no zero-temperature seed unresolved after a pass at the cap; R3 no gate but the three holds a law back;
R4 one die: at 1,024, while the three are testing, 8% to 12% of the laws one or more would hold back go on, and 5% to
16% of those two or more would; R5 the three stop 53% to 66% of the laws at 1,024; R6 at most 4% stopped over_budget;
R7 about 880 core-hours (650 to 1,300). It also reports what one die let past two gates at once, whether a gate
confirms in 2,500 laws, and the laws that reach the same result, grouped by the signature every decision from 4,096
carries.

**The cost**, from 171's progress bundle: 161 core-hours at 01:32Z (simulation 133, probes 28), 65,536 most of it at
about 0.9 core-hours a law read there (128 so far); about 345 core-hours for the whole of 171, so 172 about 880, two
to three days on the host's 16 workers.

**When**: once 171 is stopped and its final bundle made, in a folder of its own, on this build or the one that reads
171. A change to the gates that bundle calls for goes into 172's design before its first start; its pins move with it
and the build says so.

## One die a law a size

Each gate drew its own pick: a hash of the gate, the size and the law (`gates.drawn`). A law two gates would hold back
went on only when both picks fell under the share, so at 10% one time in a hundred. In 171's progress bundle, each
gate replayed alone on every decision at 1,024: 359 laws both the empty and the disconnected gate would hold back,
188 the disconnected gate alone, 64 the too dense gate alone, 384 none. Of the 359, 2 went on; of the 252 one gate
held, 24 did. With `one_die` every gate reads one pick, a hash of the size and the law alone (`gates.die(law, None,
n)`), so a law goes on at the share whichever gates and however many hold it. 171's decisions replayed with one die: at
1,024, 45 laws stopped go on and 28 that went on stop; at 4,096 and 16,384 a handful each way. A design without the
field draws as before, its fingerprint unchanged.

## The rename

`seen_enough` is `repeats_a_known_result`, its fields `known_result_after`, `known_result_from` and `known_results`.
171's design, every recorded policy and every decision in the former names are read in the new
(`engine.FORMER_FIELDS`, `gates.in_today_s_words`: a gate's name in a share, a rule, a facts key, a reason, and the
park's former words "seen enough: "), and a fingerprint maps the fields back, so every recorded fingerprint holds. The
gate draws its pick under its former label (`gates.DIE_LABELS`), so no law's pick moved. 171's design still names it
`seen_enough` and is read so; 172's names it as it is.

## The rest

* **over_budget's words.** A longer chain at the size a law is at is priced from that size's seeds; its park read "its
  first chunk at N=4,096 ... from its own seeds at N=4,096", as if it were the next size. 8 of 171's 21 parks are so.
  It now reads "a longer chain at the size it is at, N=4,096, 8 times the moves, ..." (`engine.over_budget_reason`);
  replay reads the former words of such a park as today's.
* **The ladder's tooltips.** `ended` counts seeds that used up their work budget part way, which ends a run and not a
  law; a law over_budget prices too dear to start is under `parked`, which now says so, and that a parked law stops
  climbing as a stopped one does.
* **The study bundle's button** is disabled from the first click until the fleet shows the bundle under way, the
  server refuses, or two minutes pass; a second ask while one is being made answers 202 with the one under way
  (`already`), not an error.
* **The two skipped tests** are gone: one staged a root-owned capability binary and needed root, the other compared
  against a battery report nobody captured. The sidecar's own test from the first file stays. A skip is declared only
  for a test that runs somewhere; none is.
* **Study 159's controls criterion** went; its two tests' cases are on a criterion of two campaigns made from
  criterion 2 in the test (`tests/support/criteria.py`), the shape still in the code.
* **`tools/counters_reading.py`** holds the shares and signatures a law met at its size, not the rows its decision
  listed. On 171's progress bundle: 2,687 learned decisions, 0 differ (834's 799 determined decisions list none).

## 171's progress bundle, read with 835

Every one of its 4,722 decisions replays under 835's code (0 differ, same rules), its counters give what was recorded,
and at 1,024 the three gates stopped 594 of 995 laws. Read whole on its final bundle, against its criterion, with the
finding above: under separate picks a law both empty and disconnected almost never went on, so what 171 says of those
laws one size up rests on 2 laws.

## Left

The narrower wait for a gate that can confirm, or for a signature, waits for more data (the operator, 02:32); in 172
a fact gate may confirm in 2,500 laws, and a waiting law gives up its place since 834. `repeats_a_known_result` is
tuned after the other gates.

## For the operator

Do not apply 835 to 171's folder: 171 stays on 834 until it is done. Send its final bundle. Then stop it and start
172 in a new folder (`uv run python main.py run --study 172`) on 835, or on the build that reads 171 if that build
changes 172's gates.

## Verification

3721 passed in 1130.43s (3 lanes at once)
