# Build 872: Home's four boxes as one, the study bar in core-hours and memory held, the fleet ladder in two

**Type: a feature build on Home, the operator's 2026-11-25 14:24, 14:29, 16:19 and 16:20 (`docs/HISTORY.md`), made on
their word of 23:25 ("keep building til you're finished with the road map").** No score, kind, gate or decision of a
law moves: Home reads what the folder holds, and nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/`
or `engine_rs/` moved; no schema change. It may be applied to a running folder.

## For the folders

* **Study 176 and 174**: apply and reload Home. Nothing to press. "The study now" opens on two bars, core-hours and
  memory held, each in four parts; "Which laws" leads; the landscape, the Top 100 and "The selection, size by size"
  read what it chooses; "The fleet's work, size by size" is the machine's, every law's.
* The system's part waits for the host's telemetry (`resource_telemetry`); a folder whose telemetry was off shows it
  as 0 and says so in the bar's mouse-over.

## What changed

1. **The study bar in core-hours, four parts** (`observability/study_hours.py`, `GET /api/study-hours/study`): the
   blind draw (A), the focus's neighbours, seeds and seeded laws (N), the depth seeker (D), each the wall time of its
   campaigns' attempts (one worker one core, as `campaign_manager.compute_seconds` counts it), and the system's own use,
   the host's core-hours (`resource_telemetry`: each window's CPU share times its seconds times the host's cores) less
   the workers'; the standing controls fall in the system's part. Whole numbers, each part's share beside it; the
   blind and zoned halves below say their hours (zoned is N and D).
2. **A second bar of memory held over time**, GiB-hours in the same four parts: each attempt's peak memory times its
   wall time, and the system's the host's memory in use over time less the workers'. A peak held the whole run is an
   upper bound for the workers, so the system's part is a lower bound.
3. **"Which laws" leads** (the filters, moved to the top of Home and renamed): the kinds, one kind, the map region,
   the group, the batch, settled, and two new, **scoring only** and **deepest size at least**; one line under them
   says what is chosen ("1,204 of 10,058 laws: kind ring, scoring only, deepest size at least N=16,384"). The
   landscape and the Top 100 read it as before.
4. **The fleet ladder in two.** **The selection, size by size** (`observability/selection_ladder.py`,
   `GET /api/selection-ladder/<campaign or study>`, `resources/ui/selection.js`): for the laws chosen, at each size,
   how many reached it (a reading there), are running or queued toward it, were settled there by each gate (a column a
   rule, the commonest first), wait there to be extended, and were scored there. Each law's facts come from the
   folder (its rungs, its state and latest decision through `law_status.of_row`, its score), one row a law, and the
   page counts the ones the filters keep; the study's scope reads every blind batch and the focus's and seeded
   campaigns, so the zoned laws are in it. **The fleet's work, size by size** is the old table less its law and stop
   columns: graphs, the seeds running and queued, time a seed, budgets, the cut, memory, the reservation ratio, the
   evolving and probing time, the probes and the totals.
5. `selection.js` is a module of its own, served beside `map.js`; `app.js` lost the stop columns and the "laws the
   filters keep" line, both now the selection's ladder.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 871) | the test |
|---|---|
| the selection's ladder recomputed from a bundle's tables for the same filters, matching to the law | `tests/integration/test_the_selection_ladder_reads_the_same_from_a_bundle_postgres.py`, the first: the live folder's facts and `tables/laws`' facts the same law by law, and the page's own `selection.js` the same ladder as the server's, whole and for a selection |
| the four parts' core-hours add to the folder's total | the same file, the second: 3.5 worker core-hours and a host's 4 give the system 0.5 and a total of 4 |
| no score, kind or decision moves | `tools/outputs_of_a_law.py --against` 871's record: 0 changed |
| the full lane green | the Verification below |

`tests/ui/dashboard_smoke.js` reads both bars in whole numbers, the selection's ladder with and without filters
(scoring only and deepest size among them) and the fleet's work without its law columns.

## What it does not do

* The selection's ladder counts a law's present state: a law settled at 4,096 and run on later counts where it stands
  now. The fleet's old per-size stop counts (`rung_distribution`'s `stopped_by_rule`) are still in the overview's
  payload for the reports; Home no longer draws them.
* Now researching is not filtered (the operator's 14:24 named the ladder, the landscape and the Top 100).

## Verification

4044 passed in 1399.52s (3 lanes at once)
