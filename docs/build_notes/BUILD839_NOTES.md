# Build 839: study 172's progress bundle read, and the pages made to say what it showed. It may be applied to any folder: the schema did not change and no output of a law moves. Study 172's folder needs it for nothing: its last bundle is made on the build it is on.

**Type: the reading of 172, and the fixes to the pages the operator named while reading it (2026-11-21 17:00 and
17:24), the first of the builds agreed at 18:08 ("I agree with all recommendations ... go ahead, start rebuilding
exactly with all your recommendations").**
Changed: `graph_scale_dynamics/resources/ui/app.js`, `observability/rung_distribution.py`, `observability/work_left.py`,
`services/api/campaign_manager.py`, `services/api/study_scope.py`, `db/repo_records.py`. Tests:
`tests/ui/dashboard_smoke.js`, `tests/unit/test_the_work_left.py`, `tests/integration/test_the_work_left_postgres.py`,
`tests/integration/test_the_ladder_shows_the_slowest_run_postgres.py`. Documents: `docs/agent/NEXT_BUILD.md` (840),
`docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`, `docs/HISTORY.md`, `docs/DECISIONS.md`,
`docs/OPERATIONS.md`. Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` changed;
the schema did not; no frozen source moved; against 838's record (`tools/outputs_of_a_law.py --against`) 0 outputs
moved; the table's lock prints `analysis-5.3.0 e639334808716378 89f4fed82d9adc27`.

## Study 172 at its progress bundle

The bundle is `study_172_2026-11-21T15-58-19Z`, made on 838 in 172's folder while it ran: 2,500 laws drawn (at its law
budget since 12:51Z), 757 still going, so this is a progress reading and R7 is reported, not judged. Every reader of
838's procedure ran; 171's numbers are in 838's notes.

| item | predicted | 172 at 15:58Z |
|---|---|---|
| R1 | every decision replays, counters as recorded | holds: 11,532 replay, 0 differ; 0 of 6,497 learned decisions differ |
| R2 | no zero-temperature seed unresolved after the cap | holds: 0 (1 finite-temperature seed, the budget) |
| R3 | only the three gates hold, none before 1,024 | holds: stopped by the three 1,629, done 61, over_budget 53, going 757 |
| R4 | at 1,024, 8% to 12% of the laws held back go on | misses: one gate 661 held, 51 went on (7.7%); two or more 838, 61 went on (7.3%) |
| R5 | the three stop 53% to 66% at 1,024 | holds: 1,423 of 2,485 (57.3%) |
| R6 | at most 4% over_budget before 65,536 | holds: 53 of 2,500 (2.1%) |
| R7 | 650 to 1,300 core-hours | 173.2 so far: 64 4.4, 256 6.3, 1,024 12.9, 4,096 39.9, 16,384 60.0, 65,536 49.7 |

R4 misses by the rule working: the disconnected gate confirmed (100 held back again a size up) and fell to 1% (315
decisions met that share), which the prediction of 8% to 12% did not allow for. The work to come was forecast by hand
at about 673 core-hours, 872 in all against 880 predicted, about 43 hours more on the host at its 15.7 cores.

* **The replay and the counters**: 11,532 decisions, 0 differ, all on the same rules; C1 to C3 hold, 0 decisions change
  study-wide.
* **The gates under other settings** (`tools/gate_variants.py`): with the fact gates on one size in a row 1,143 laws
  change fate (1,016 would stop at 256); on four, 1,509 (the 1,423 stopped at 1,024 would go on); with separate dice
  193.
* **The cap** (`tools/cap_reading.py`, from every chain's peak degree): a cap of 12, 16, 20 or 24 each holds back one
  of the 22 scoring laws (`dfd97f6ae8c9`, score 10, at 1,024) and 32, 27, 23 or 18 laws as too dense. A seed at 65,536
  whose densest chain reaches 12 takes a median of 1.6 GB and at most 6.28 GB.
* **The budgets** (`tools/budget_reading.py`): seeds cut by size 3, 35, 216, 261, 43 and 3; laws stopped with the next
  run not fitting 15 at 256, 5 at 1,024 and 33 at 4,096, 27 of those 33 a longer chain refused at 4,096 by a median of
  31%. 127 seeds ran past their budget and 27 past twice it, since the budget is read only between chunks. The worst:
  law `3df93c635ccd` at 65,536, a chunk of 5.2 hours on each of three seeds (about 54 T units against 24 T), killed at
  the restart that made this bundle with 1,060 seconds of it saved.
* **Where the compute goes**: 64% above 4,096; a tenth of the laws take 71%; the 61 laws that finished the ladder cost
  56.9 core-hours and 5 of them score.
* **The scorers** (`tools/score_list.py`, `tools/pilot_reading.py` with the calibration table in the tree): 22 drawn laws
  score, every one through a lattice start and none from empty or random. By kind: 10 changed no edge, 9 are a lattice
  thinning (the top law `4c5892bd611b`, score 18, a cubic start at mean degree 32 at 64 to 1,024 that falls to 6.2 by
  65,536), 1 reshaped the same at every node (`f87d383b5a5c`), 2 irregular. It is the roadmap's open question from 795
  in the data: a run changes a count of edges that does not grow with the graph, so a lattice start is taken apart at
  the small sizes and holds only at the larger ones.
* **Rings**: `tools/read_bundle.py` matches 37 laws to the ring's calibration family, and about 45 laws have a chain
  from empty or random that reads d near 1 on all four probes at mean degree near 2, in several pieces (median largest
  piece 0.48 of the graph). None scores: a score needs a piece of 4,096 nodes at two sizes from 4,096, and most are
  still at 16,384.
* **What grows** (`tools/bundle_growth.py`, a line through 171 and 172): the decisions table is 316 MB unpacked for
  11,532 rows; the two readers that hold every decision peak at 1,038 MB, 3.9 GB at a batch of 10,000 laws and about
  38 GB at 100,000, past the sandbox. A batch fits; study A whole needs those two readers to stream.

**What the recorded gates would have done**, each replayed on 172's own laws with a tenth let through (scratch
scripts beside the readers; 841 carries the reader and commits its numbers as study 173's predictions): `starts_alike`
alone withholds 569 laws and saves 54% of the compute with no scorer lost; `nothing_read` with its piece set at 0.9 of
the graph 675 laws and 67%, none lost (as built, a piece of 4,096 nodes at N=4,096, it withholds two of the thinning
scorers, `4c5892bd611b` at 3,993 nodes and `dfd97f6ae8c9` at 4,071); those two with `starts_apart_by_history` 778 laws
and 73%, none lost; `starts_apart_twice` saves 7% and loses 3; `no_steady_chain` would save 79% and lose 19 of the 22.

## What the pages said, fixed

Each is the operator's observation, measured on the bundle or the code before it was changed.

* **The landscape lost its lattice starts on a phone's scroll** (17:00, A). A phone fires `resize` when its address bar
  hides, and the redraw on a resize drew the plain points whatever the toggle said. It draws what the toggle chose
  (`repaintLandscape`).
* **The d_B probe read 0.0s** (17:00, B). The probe returns at once where too few box radii fit
  (`box_covering_profile`, `WINDOW_TOO_SHORT`), on 92% of 172's seeds at 256 and 52% at 65,536, so its median over every
  seed is exactly zero. A probe's cell is now its median over the seeds it ran on, in milliseconds under a second, with
  the share of seeds it ran on beneath where leaving the others out moves the median: 25 ms on 8% at 256, 11 s on 48%
  at 65,536. The ladder keeps 787's rule, headers only and one fixed line each, so the share stands in the cell and
  not on a mouse-over. `rung_distribution` gives `<probe>_ran`, `<probe>_timed` and `<probe>_ran_median_seconds`.
* **The fleet table's columns** (17:00, E; agreed 18:08). The stops are `empty`, `dense`, `discon`, `gated` (every gate
  that reads the probes, the starts or the structure), `budget` (laws stopped `over_budget`) and `total`; `parked` is
  gone. `ended` is `cut`: laws with a seed cut at its budget part way, which ends the run and not the law. A budget is
  its work alone ("400 G", "24 T"): the word "units" and the sandbox's time beside it are gone, the time having read
  20 minutes where seeds ran for hours.
* **The group titles** (18:10) say "a law at a size = 3 seeds × 8 starts = 24 graphs".
* **A seed's hours vanished from the slowest** (17:24). A seed counted at the time its save recorded, so the three
  seeds above read 1,060 seconds after the restart and 5.2 hours were nowhere. A seed's time is now every second its
  runs took, the stopped ones counted, while it waits, while it runs again and once it is done
  (`Repo.interrupted_run_seconds`); etime and the interrupted seconds are counted as before.
* **The core-hours left** counted the queued seeds at their size's median and nothing a law would buy later: about 191
  core-hours at the bundle against the 673 forecast by hand. That figure stays, said as "at least". Beside it the page
  now gives the work expected: the queued seeds at their size's mean, which the slow seeds raise, and the sizes the
  laws still climbing are expected to buy, from the share of laws that went on at each size
  (`work_left.sizes_to_come`; a size is priced from five finished seeds, as the queue is). On 172's state at the
  bundle it gives 622 core-hours.
* **d_V is not a Hausdorff dimension** (17:00, C). Two lines of the page called it one; the code and the law's page
  already said it is the volume-growth exponent (`NO_CHANNEL_MEASURES_HAUSDORFF_DIMENSION`). The name d_V stays.

Not changed, with the reason: the probe queue (17:00, D) is measured first, at the build that reads study 173; the
score (18:08: "perhaps it's too early to change the scoring mechanism").

## A run's seed, as the code stands

Asked at 18:08. A start without `--study` and without `--search-seed` draws a fresh 63-bit seed for each campaign
(`secrets.randbits(63)`, `operations/study.py`), so two machines draw different laws; `--search-seed` makes it
reproducible; a study's design may fix its own seeds (`search_seeds`, `operations/study_design.seed_of`), as 172's
does, so `--study 172` grows the same laws in any folder and refuses another seed. The seed is in the start's log and
on the campaign. Nothing to build.

## What comes next

840: no seed runs past its budget and no chunk is lost to a restart. 841: the rules of the gated pilot and study
173's design, its predictions committed from 172's replay. `docs/agent/NEXT_BUILD.md` and `docs/ROADMAP.md`, "Planned
builds".

## Verification

3791 passed in 1063.43s (3 lanes at once)
