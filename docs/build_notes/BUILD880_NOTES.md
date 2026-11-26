# Build 880: the outliers' queue

**Type: a focus build, the operator's 2026-11-25 08:04 ("any outlier should automatically be added to the list of
potential zones to investigate its area") and 08:07 ("But only if all the top scorers are already done being
mapped"), made on their word of 23:25 to keep building to the roadmap's end.** No score, kind or decision of a blind
law moves: the focus only chooses which law it maps next; `tools/outputs_of_a_law.py --against` 870's record: 0
outputs changed. No schema change. It may be applied to a running folder.

## For the folders

* Nothing to press. When every scoring law of the study is mapped, inside a mapped region or skipped, the focus no
  longer waits idle: it takes the study's strongest outlier next and maps it as it maps a scoring law (its seeds, its
  rings, a region with the next GG number). An outlier one seed shows is a lucky strike, kept in the focus's state
  (`lucky`) and not opened; an outlier inside a region already mapped joins it (`inside`).

## What changed

1. **The criterion, committed before any law is read by it** (`resources/readings/outliers_1.json`,
   `gsd-outliers-1`): an outlier reads d_w over 3.5 or d_V over 3.0 on any chain of a seed at 1,024 nodes or more,
   where 174's bulk ended (99% of its laws under 2.87 and 2.24); its strength is its highest reading over the line as
   a multiple of the line; fewer than two seeds showing it is a lucky strike.
2. **`operations/outliers.py`**: the laws whose rung summaries read over a line (`over_the_line`), each law's
   readings seed by seed and chain by chain from its measurements (`seed_readings`, through
   `observability/two_chains.seed_values`), the verdict (`judged`), the study's outliers strongest first
   (`outliers`) and the next one the focus takes (`next_outlier`), which passes over a lucky strike and joins one
   inside a mapped region to it.
3. **The focus** (`operations/focus._chosen`): with no scoring law free, the next law is `next_outlier`'s.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 879) | the test |
|---|---|
| the criterion in a file before any law is read by it | `tests/unit/test_the_focus_takes_the_outliers_once_its_laws_are_mapped.py`, the first |
| an outlier one seed of three shows is a lucky strike, its region not opened | the same test, and the second: kept in `lucky`, passed over |
| with every scoring law mapped, the focus's next law is the strongest outlier | the second and third: strongest first, one inside a region joins it, asked only when no scoring law is free |
| no score, kind or decision of a blind law moves | `outputs_of_a_law --against`: 0 changed |
| the full lane green | the Verification below |

## What it does not do

* The lines are 174's; a study whose bulk ends elsewhere needs its own lines, a new criterion file read before it.
* The Map page lists the lucky strikes only through the focus's state; a panel of them is for the page's next build.

## Verification

4182 passed, 41 skipped in 1376.69s (3 lanes at once)
