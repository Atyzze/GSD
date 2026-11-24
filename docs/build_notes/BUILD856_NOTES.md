# Build 856: one study in two groups. The still lattice scores 1, the small world is a kind of its own, study 176 draws blind with half the fleet and maps the ten best with the other half, the system keeps the CPUs it is given, and every bundle says which science read it

**Type: a build of the next study, asked for by the operator on 2026-11-24 at 16:33 ("both searches will have to
merge into 1, the top 10 scores being auto-explored/mapped automatically"), 17:37 (one workload of groups A, B and a
system C whose cores no work may take), 17:39 ("the simply 50-50 default split in two") and 18:04 (a science contract
and the calibration table in every bundle), on the two baseline bundles sent at 17:31 (`docs/HISTORY.md`).** It changes
what the fleet scores (the still lattice, gsd-law-score-9), what the catalogue calls a law (the small world,
gsd-catalogue-2), how the fleet's slots are shared between a study's groups and on which CPUs its children run, and
adds study 176 with its map. Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/`
moved; the science freeze and the table's key are untouched.

## For the folders

* **174 and 175** may take 856: their boards are scored again under gsd-law-score-9 (the board's contract moved), so
  a still lattice's law drops to 1 on Home and the landscape; no decision, gate or rung changes. Not applying it
  costs nothing but that view.
* **Study 176** starts on 856 in a folder of its own: `uv run python main.py run --study 176`. It creates eleven
  campaigns, ten blind batches of 1,000 (group A) and the map (group B, 125 laws to begin with), sets the split to
  50-50 and writes the map's state. In btop on 16 workers: 8 simulations of the map and 8 blind while both have work;
  all 16 blind when the map waits on its decisions. `uv run python main.py workload` says the split and the CPUs;
  `--system-cpus 0,1` keeps those two for the database, the controller and the dashboard (none until named).

## The still lattice scores 1 (gsd-law-score-9)

`still_lattice_criterion_1.json` passed at 854; what it said follows: a lattice chain at a size where its mean degree
is within 5% of its lattice's, most of its seeds not at the cap, and the median over its seeds of its accepted moves an
edge at most 0.05 scores 1, the lowest, as the frozen lattice does (`observability/law_score.still_at`, the catalogue's
own `still`). The moves reach the score from each seed's move accounting (`two_chains.accepted_moves_of`, kept by the
snapshot as `accepted_moves` when it drops the accounting); report 28's values gain a `moved` column (the median), so
a bundle re-scores as the fleet scores. A chain with no accepted moves read scores as 8 did, so no known answer moved:
criterion 5's judged reading is rebuilt the same on 856's code (`tests/scientific/test_the_score_settles_on_known_answers.py`).

Against 854's record (`tools/outputs_of_a_law.py --against`), which 855 left as it was, 8 outputs moved, all the score's: its contract, and the
`still` slot in its parts, weights and words, on both engines. On the baseline (`tools/catalogue_reading.py`, which now
scores each law with its chains' moves from `tables/chains.ndjson.gz`): 174, 83 laws score and 54 of them now 1; 175,
264 score and 230 of them now 1.

## The small world (gsd-catalogue-2)

Placed before made: two starts or more agree, and every agreeing chain read at the size and at a quarter of it reads,
at both, a reach (the half-volume radius) at most 2.0 times a random graph's of its own mean degree,
ln(N/2)/ln(k) + 0.63, and a d that rises by at least 0.1 between them. The random reach was read on the random start
itself by the estimator's own reach (`tools/small_world_reach.py`): 90 graphs, mean degree 2 to 32, 1,024 to 16,384
nodes, all within 1.05 steps, none above 1.08 times it. The lattices as built read 1.38 to 3.16 times it at 1,024
(cubic, bcc, fcc and tesseract inside 2.0), 1.86 to 5.32 at 4,096 (the tesseract inside) and 2.22 to 9.19 at 16,384:
the reach alone cannot tell a 3D or 4D lattice at 1,024 from a random graph, so the rise and the agreement decide.

The two numbers were chosen on the baseline: H31 (3931d03e8edf) reads 1.55 and 1.76 times the random reach at 4,096
and 16,384, d 3.48 to 4.02; fdc563a72c98 1.30 and 1.45, d 4.02 to 4.58. Both are small worlds at 16,384 and stay made
at 4,096, where 1,024 read nothing to judge. Of 3,513 chain sizes read with the size below them, 10 pass the chain rule:
those 3, 5 rewired lattice chains, 1 melted and 1 ring whose starts do not agree; no frozen or still chain, no chain of
a law grown from the twins. 175's 17 made laws (H31 and its variants) are read to 4,096 only, so none is judged.
`small_world_criterion_1.json` is committed before any later bundle: W1, no law called a small world at one size is
made deeper; W2, at least half of 175's H31 variants that two starts agree on at 16,384 are small worlds.

## Study 176

`study_176_design.json`, `study_176_criterion.json` and `study_176_first_ten.json`, committed before any start.

* **Group A**: 174's design on ten new search seeds (drawn 2026-11-24 with `secrets.randbits(63)`), batches of 1,000.
* **Group B**: the map (`operations/study_map.py`, `research/neighbourhood.py`). It begins with the ten best laws of
  both bundles under gsd-law-score-9 that score above 1, each rebuilt exactly by its fingerprint
  (`tools/map_first_ten.py`): each run again, each real parameter moved alone a tenth up and down, and a line toward
  its nearest law of the same terms whose kind at 4,096 differs, at least 0.001 away, halved four times where the kind
  flips. Every controller pass, at most once a minute, it reads the points decided, halves the lines, and marks a
  region known when every point is decided and its lines are done: its kind, the size from which that kind is called
  on all its points, its boundaries. A known region leaves the ten; the best law of the study in no region comes in,
  from either group, its own points run in B and the law itself not run again. B's gates are 175's.
* **The first ten**: 218bd85aa40b (21, toward a ring), 18856793523d, 3a8569fc6094, 61e41fb7b3cb, 99e25674e37a and
  b4d17dcdb34a (19 each, the laws grown from the twins; two with a partner, empty and melted), b27787393b3f (15, toward
  still), 1b42427547af (11, H15, toward full at 0.007), 58d863971205 (9, toward empty) and 823f886deb4b (9, toward
  rewired at 0.007): 108 variants, 7 line points, 125 laws.
* **The criterion**: P1, every holder run again reads what it read in its bundle; P2, every law of the map campaign is
  a point of the map's state, none drawn; P3 to P5 reported (each group's core-hours, every region known, A's batches
  beside 174's).

## The work groups and the system's CPUs

A campaign carries its group (`study_design.group`); the folder flag `work_groups` gives each group a share. A worker
claiming a simulation takes it from the group furthest below its share of the simulations running, among the groups
with work queued, and inside the group as before (`scheduling/work_groups.in_shares`); a group with nothing queued
leaves its slots to the others, so a study with nothing to map yet runs all blind and settles to its split as the map
finds work. The flag `system_cores` names CPUs no simulation or analysis may run on: the worker and the analyzer pin
themselves to the others just before they start each child, which inherits it (`work_groups.pin_to_work`).
`main.py workload [--split A=1,B=1] [--system-cpus 0,1]` reads and sets both.

## The System page's Workload panel, and why Home went stale on the host

The operator's screenshot of 2026-11-24 18:26: CPU 100% at 87 C and 200 W, 32 slots active of 32, the API's round
trip and the snapshot both 463 s old, and `/api/reports/status/1` answered 503 `TimeoutError`. With a simulation on
every hardware thread, the API process most likely waits behind them for CPU; the web server stops waiting for it and
answers 503, and the page shows the last snapshot it has. Faster retries or a refresh every 0.5 s instead of 4 s
(`GSD_HOST_SNAPSHOT_INTERVAL_SECONDS`) would ask more of the process that is starved, so neither changed. What frees
it is CPU kept for the system: the System page's new **Workload** panel, under Workers and behind the admin link like
it, sets the system CPUs and the groups' split (`campaign_manager.workload`, action `workload`), and a running child is
moved off the kept CPUs within five seconds (`work_groups.Pinned`, every thread of the child), a new one never starts
there. The panel says which CPU shares a core with which, from `/sys` (keeping one CPU leaves its twin to the
simulations). What to watch after keeping a core's two threads: the header's API round trip under a second, and in
btop two CPUs quiet of simulations.

The Explorer finds every law of a campaign by its code alone (`C6`), beside `C6-G7` and `G7` as before, and takes a
full code with its build (`B856-C6-G7`); the header names the build `B856`.

## Every bundle says which science read it

`study.json` carries `science` (`reporting/science_contract.py`): the analysis version, the estimator's and the starts'
fingerprints, the score and catalogue contracts, the engine crate and the calibration table's SHA-256, and one hash over
them; the bundle carries the table (`calibration/probe_calibration.json`), the map's state (`map.json`) and the split.
On 856: analysis-5.3.0, e639334808716378, 89f4fed82d9adc27, gsd-law-score-9, gsd-catalogue-2, 0.840.0, table
efb101091bb0c894..., science cd32c479943794ab... in this sandbox's table, the seed.

## Pins and freezes that moved

`tests/fixtures/committed_readings.json` pins four new readings: `small_world_criterion_1.json`,
`study_176_design.json`, `study_176_criterion.json` and `study_176_first_ten.json`. The science freeze was written again
(`tools/science_freeze.py --write`) for the two frozen files the still lattice moved, `observability/law_score.py` and
`observability/two_chains.py`; the estimator and its closure, the table's key, are untouched (`analysis-5.3.0
e639334808716378 89f4fed82d9adc27`). Report 28's value columns end with `moved`; every reader takes its columns by
name.

## Asked of the operator

* A variant moves a coupling by a tenth; 175's smallest real radius was 0.001. Recommended: a tenth until the first
  regions are known, whose points say (P4) whether a tenth changes a kind at all; 108 variants for the first ten, at
  175's estimate of about a core-hour a law.
* Four halvings place a boundary within a sixteenth of its line; a fifth halves it again for one point a line.
* Which CPUs the system keeps (none until named).

## Planned after it (the operator, 17:51 to 18:08)

857 the dashboard's filter panel; 858 a study seeded from any bundle with the same science hash; 859 group D, the best
law taken up the ladder until memory refuses a size; 860 the consolidation; after the paper, the shared atlas
(`docs/ROADMAP.md`).

## Verification

3949 passed in 1384.51s (3 lanes at once)
