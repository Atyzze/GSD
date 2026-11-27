# Build 881: the focus mended, one depth worker, and study 177 from nothing

**Type: a fix build and a new study's design, on the operator's words of 2026-11-26 11:46 ("I mainly want to see the
zoning and the depth worker fixed first"; "there is supposed to be only 1 depth worker that 1 by 1 pushes a single
seed to the highest N before it hits system memory cap, no more than 50% of total system") and 11:55 ("can we just
start a new study from scratch first without any prior seeding at all, and just see the mechanism of the focus group
and dev worker kick in automatically").** No score, kind or decision of a blind law moves, no frozen source and no
schema: a bundle's science (`reporting/science_contract`, f5c045e195fdb4d2) is 176's, so its bundles seed 177. It may be applied to 176's folder,
and 177 is started on it in a new folder.

## For the folders

* **Study 176**: since 2026-11-25 15:39Z every one of its focus's steps failed (below), so nothing the focus read
  since was saved: its 48 neighbours were measured to 16,384 and done for hours and never read. On 880 the same
  failure made a new depth campaign every minute (16 to 28 in the bundle of 10:38Z, 31 on the page). 881 makes one
  depth campaign once, saved the moment it is made, and pauses every other depth campaign of the focus, each with
  everything it measured kept. Its first step then reads the neighbours.
* **Study 177**: `uv run python main.py run --allow-host <host> --study 177` in a new folder, every other fleet on the
  host stopped. Ten blind batches of 1,000, the focus begun at the start, the seeded campaign empty and the import
  folder left empty. The first law that scores here is taken by the zone worker (its neighbours, its terms switched
  off and its seeds) and by the depth worker at the focus's next step, nothing to press.

## What was wrong

1. **The step's failure** (`operations/focus.seeds_of`): the law in focus's seeds, read seed by seed in its own
   campaign (0 to 2) and in the seeds' campaign (0 to 5), were merged as `dict(own, **more)`, and keyword names must be
   strings, so seeds 3 to 5 raised `TypeError: keywords must be strings` the first time the seeds' campaign had ended
   (176's C13 at 15:39:32Z). The controller logs a failed step (`study_focus_failed`) and goes on, so the page showed
   the state of 15:38 for 19 hours. The test of the focus replaced `seeds_of` with a stand-in, so no test ran it.
2. **The renewal every minute** (873's `renew_depth`): it made the new depth campaign, then the rest of the step
   failed before the state was saved, so the next step found the old campaign again and made another. Every failing
   step also inserted the study's top five into the depth campaign, which the state never recorded: 21 laws in 176's
   C14, 15 in each of 16 to 28, each copy holding a worker of its own.

## What changed

1. **The step** (`operations/focus.step`): the merge is a plain union; a failing step writes the flag
   `study_focus_failed` (since when, how many times, the error) before it raises, and a step that passes clears it.
   The Map page's first line says so in amber ("the focus's step has failed ... nothing it reads is saved until it
   passes"), so a failure is seen within a minute and not in a log.
2. **One depth campaign** (`renew_depth`, `tidy_depth`): a renewal adopts a depth campaign of the focus that already
   fits the plan before it makes one, and saves the state the moment it is made; every other active depth campaign
   of the focus is paused at each step, its readings kept.
3. **One depth worker, one law at a time** (`depth_next`, `depth_line`): the contenders are chosen as before (the
   depth list's top five and the law in focus), but the depth campaign holds one of them at a time: the law in focus
   first, then the depth list in its order (the operator's, else by score). The next enters when the decider ends the
   last (done, stopped, or settled at its memory ceiling); the Map page's depth table says which is on now, which
   ended and how, and which wait. Its one worker runs one seed at a time: a size's three seeds one after another.
   One seed a size is refused by the campaign's own validation (`scheduling/base_block.py`: with fewer than three
   "there is no repeat to measure reproducibility from"), so three it is.
4. **Half the host's memory** (`operations/depth_reach.room_for`, the plan's `depth.memory_share` 0.5, recorded in the
   depth campaign's spec): a law's next size is priced from its own peaks as at 873 and bought only while it needs no
   more than half the host's total memory; past that it is settled at its memory ceiling, the reason saying "past the
   host's reach of 46.0 GiB with 46.0 GiB kept free" on a 92 GiB host. The decider prices it at its own decision
   (`DecisionStore.memory_ceilings` refreshes the price first), so a size past the line is never queued between two
   of the focus's steps.
5. **A law in focus read while it climbs** (`focus.verdict`): its own kind at 16,384 is read once its own campaign
   has decided at 16,384 or above, not only once that campaign has ended it; a blind law that scores is often still
   climbing, or waiting for a place at the next size.
6. **"The study now" on Home** (`resources/ui/app.js`, `services/web/main.py`): the campaigns' overview reads every
   campaign and was cut by the dashboard's edge after its default 1.5 s, so the panel stayed on "loading" until a
   reload happened to be quick. The route has 30 s (`SLOW_ROUTES`); a failed ask says so in the panel and asks again
   within 4 s; one ask at a time; and the panel's first drawing is never held back by the pointer resting on it.
7. **The groups' words**: "Now researching" names its rows blind, zone, zone seeds and depth (the zone worker is the
   focus's group N, the depth worker its group D); the Map page's line reads "zone worker, neighbours", "zone worker,
   more seeds" and "depth worker".
8. **Study 177** (`resources/readings/study_177_design.json` and its criterion, committed before its first start):
   176's design on eleven new search seeds drawn at 2026-11-26T11:05:28Z, nothing seeded. Its criterion: the focus
   takes a law at the first step after one scores; one depth campaign with one worker and one law at a time; no size
   bought past half the host's memory; the focus's step never fails; the first law's story reported.

## What the bundles read

* **870 against 880, the same law, size, seed and chain** (176's C11 and C14 on 870 against the duplicate depth
  campaigns 16 to 28 on 880, sizes 64 to 1,024): 8,632 chains, every one identical in its moves, accepted moves,
  edges, largest degree, work and its parts. The engine's seconds and a seed's peak memory are the same at these sizes
  (medians 1.00 to 1.02, 0.92 at 1,024); 875's gains are at 65,536 and are read on the next bundle with the sizes.
* **The outlier at d_w 11.8** (S176C9G4024, C9's 4,024th graph): one seed of three at N=256, its error 5.0, on a
  graph whose pieces hold 82% of its nodes; at 1,024 and 4,096 every probe refuses it (no scaling window), mean
  degree 14, a small world. The landscape draws a law's reading at the largest size that has one, so a reading the
  larger sizes refuse stays drawn, faint. 880's outliers start at 1,024 and pass it over.
* **The seeds a bundle carries**: `focus.json`'s `seeded` record names the 72 laws of 174's bundle of 13:04Z with
  their 174 codes and scores, and `tables/laws` holds them whole as C11; 145 laws of the after bundle score here, 71
  of them seeded. Both bundles, on 870 and on 880, read science f5c045e195fdb4d2 (`reporting/science_contract`:
  probes, score, catalogue, engine 0.840.0, the table's cells), as 881 does, so either seeds 177; the frozen
  sources' fingerprint that moved between them (389f23182b482f6f to a8da39df180df8e1) is the calibration gate's,
  not the seed's. Every scoring law of the 870 bundle is in the 880 one.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| seeds a law's own campaign never ran are read by number | `tests/unit/test_the_focus_reads_seeds_its_own_campaign_never_ran.py` |
| a step failing after its renewal makes the new depth campaign once, and the page says it failed | `tests/integration/test_a_failing_focus_step_makes_its_depth_campaign_once_postgres.py`, the first |
| one depth campaign: an existing one adopted, every other paused, one worker, the law in focus first | the same file, the second |
| one law at a time, a better law waiting its turn | `tests/integration/test_study_177_starts_from_nothing_and_its_workers_take_its_first_scoring_law_postgres.py` |
| study 177 starts with nothing seeded and its workers take its first scoring law | the same test |
| half the host's memory, and the ceiling's reason | `tests/unit/test_the_depth_seeker_reaches_the_memory_limit.py`, the last |
| the study now drawn at once and asked again within seconds | `tests/ui/dashboard_smoke.js` (`tests/unit/test_dashboard_smoke.py`), `tests/unit/test_slow_routes_get_their_time.py` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 880's record, written on the untouched tree: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* The study bundle is still called a study bundle, and it carries no `attempts` table yet (the handover's 881): both
  belong to the next step, importing a bundle into 177, which the operator takes once 177 runs on its own.
* A bundle of another science is still refused whole (`study_seed.seed`); reading its scoring laws alone, their
  specs run here from nothing, is the import step's (the operator, 12:55).
* A depth law in progress is not set aside for a better one: a law at 4,194,304 can hold the depth worker a day, and
  the focus's boundaries wait for its own law's depth.
* 176's state from 15:39Z yesterday is read again by its first step on 881, not repaired: the operator has moved on
  to 177.

## Verification

4189 passed, 41 skipped in 1116.38s (3 lanes at once)
