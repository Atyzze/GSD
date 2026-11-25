# Build 860: Home says what is true. The orange banner only when the refreshes fall behind, the frozen and still lattices back on the landscape, the Top 100 in one order, and every law of a study's bundle whole

**Type: a fix build, asked for by the operator on 2026-11-25 between 00:25 and 00:47 (their words in
`docs/HISTORY.md`), with the readings their questions asked for.** No score, kind, gate or decision moves; nothing
under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` changed; `tools/outputs_of_a_law.py
--against` 859's record, written first on the untouched tree: 0 outputs changed. The planned seeded study moves to 861.

## For the folders

Any folder may take it, 174's included: it changes what the API answers about freshness, what Home draws and lists,
and what the next bundle carries; nothing a fleet runs. After the restart each landscape is built once more (it now
carries the score's lattice names), so Home's plot fills a few seconds later than usual the first time. The next bundle
is about 2 MB larger: its laws table carries every law whole.

## The orange banner

**What it was.** "The dashboard is serving a stale snapshot" showed whenever the snapshot was older than three of the
API's refresh periods, 12 s. Home's "All batches" view answers with the oldest of eleven snapshots, one a batch, each
rebuilt inside the API's one process, one after another as the polls find them due, four at most at a time, and a
rebuild that waited more than 5 s for a database slot gave up and waited for the next poll. So the oldest of eleven
was held to a bound sized for one, and on a busy host the eleven rebuilds could not all land inside it.

**Measured.** Each batch's snapshot took 0.73 to 0.88 s to build on the quiet fleet (`build_ms` in every batch's
`evidence/system.json`, study 174's bundle of 2026-11-24 23:19Z). A model of the polls, the slots and the rebuilds,
driven through the real `study_scope.Scope` and the page's own `freshnessOf`, gives, over twenty minutes of polls:

| a batch's rebuild, the API's CPU shared | before: banner on | before: age median, max | after: banner on | after: age median, max |
|---|---|---|---|---|
| 0.8 s | 0% | 8.9 s, 11.9 s | 0% | 9.0 s, 11.9 s |
| 1.2 s | 70% | 13.6 s, 24.7 s | 0% | 13.2 s, 15.9 s |
| 1.5 s | 100% | 23.9 s, 60.3 s | 0% | 15.7 s, 19.9 s |
| 2.0 s | 100% | 112 s, 427 s | 0% | 21.6 s, 27.8 s |
| 3.0 s | 100% | 92 s, 397 s | 94% | 40.0 s, 81.2 s |

The operator's screenshots read 14 s and 20 s, the 1.2 to 1.5 s rows. Where the rebuilds run side by side in the
database instead (the other end of what a host can be), neither rule shows the banner up to 3 s a rebuild. Before, at
2 s and up, the rebuilds that gave up waiting kept the eleven from ever catching up: the ages ran to minutes.

**What it is now** (`services/api/freshness.py`). The banner says something is wrong, not that the numbers are a few
seconds old: the FRESHNESS tile shows the age as before. A snapshot is late past twice the time one round of its
refreshes takes, by their own measured build time: the refresh period, plus the page's poll, plus the slowest
rebuild times the waves the eleven need through the API's database slots; never below three refresh periods, as
before, and never above a minute, whatever the load. A rebuild waits up to 16 s for a slot instead of 5. A batch
whose rebuild failed is named in the study's answer with its error (`last_refresh_error`, `refresh_errors`), which the
study view used to drop. One campaign's view keeps its bound: 17.6 s at a 0.8 s build, and three of its own longer
period while paused, as before (48 s). Every answer carries how its bound was made (`freshness`).
`tests/unit/test_home_says_its_snapshot_is_old_only_when_its_refreshes_fall_behind.py` runs the model: no banner at
0.8 to 4 s a rebuild side by side or 0.8 to 2 s shared, ten minutes each; a banner within its bound once the rebuilds
stop; a failing batch named; a minute at most.

## Where the lattice strips went

Two causes, one a bug and one a finding.

**The bug.** With "include lattice starts" ticked, Home drew a law at its scoring lattice start only when the score
named that start "lattice" (changed) or "kept". Since 841 a lattice that changed no edge scores as "frozen", and since
856 one at its own degree with few moves as "still", and the page was never told: the server merges them into the
landscape (`study_scope.LATTICE_KINDS`) and the page dropped them. In 174's bundle of 23:19Z that is 39 points, 24 at
d near 3 (21 of them bcc) and 15 at d near 2 (11 triangular), 22 of them in the Einstein band and 16 in the
two-probe band: the two strips. The landscape now carries the score's own list of lattice names (`lattice_who`,
`services/api/law_order.LATTICE_WHO`, read from `law_score.WEIGHTS`, so a fifth name arrives by itself), and the page
reads it for the toggle and for the line that says which start built a law.

**The finding.** The score in force (848) counts a seed only where its chain stopped changing (certified, at rest or
frozen). In the folder, 46 laws score on 23:19Z's bundle. `tools/catalogue_reading.py`, which wrote "83 laws score,
54 of them 1" for 14:22Z's bundle into the handoff and the paper's draft, reads the bundle's report 28, whose values
are each chain's mean over every seed: it cannot see which seeds stopped, so it counts them all. On 23:19Z's bundle
it scores 122. Of the 79 laws only it scores, 535 of their 629 seeds from 4,096 ended at the sweeps' ceiling, never
certified; of the laws both score, 127 of 316 completed certified. So part of what looked settled never settled by
today's rule, and five of study 176's first ten (M02, M04, M08, M09 and M10, `study_176_first_ten.json`) score 0 in
the folder. The bundle now carries the folder's own score of every law (below), so a reader need not guess again;
the reader's fix and 176's ten are the operator's (`docs/ROADMAP.md`, "Questions for the operator").

## The Top 100 in one order

Laws of equal score swapped places when a filter was set: unfiltered the server ordered ties by depth and then the
campaign's id as text ("10" before "2"), filtered the page ordered them by the law's hash. One order now, the same on
the server and the page, filtered or not: score, then the campaign's number, then the graph's number, then the id
(`services/api/law_order.law_rank`; the page's `lawOrder`). With the scores of the operator's screenshot: C1-G6940,
C2-G64, C6-G1015, then C3-G7363 at 7. The smoke checks both orders and the toggle's frozen and still lattices; both
fail on 859's page.

## Every law of a bundle whole

**The bundle's laws table carries each law** (`reporting/study_tables.law_rows`): `spec`, its terms, couplings and
dynamics as the folder holds them, whose fingerprint is its id, and `law_score`, the folder's own score board's
entry for it. Before, a bundle carried a law whole only where a report happened to list it: 1,449 of 174's 10,005.

**An older bundle's laws are drawn again** (`tools/laws_of_a_bundle.py`): a blind batch's laws from its design's
search seed on this tree, each checked by its fingerprint, and the standing controls' from their criterion; a bundle
of another design is refused. On 174's bundle of 23:19Z: all 10,005, the 10,000 blind laws drawn again bit for bit in
3.4 s, the five controls from `controls_criterion_2.json`. So study 174 is whole: its laws, its readings, its decisions
and its calibration table; the engine is named by its version (0.840.0, crate and science hash) and its source is
this tree's `engine_rs/`, not inside the bundle.

## Read in the sandbox, nothing to apply

**The terms against what the laws did, all 10,000 of 174** (the laws drawn again, each law's kind from the
landscape or its stopping rule from the decisions). Thirteen terms are drawn, the curvature left out by design, and
every one appears in every outcome of twenty laws or more: no term is absent from any region. What tells the outcomes
apart is the temperature and a few signs and sizes. A random forest on the law alone (which terms, their signs and
sizes, zero temperature, beta, locality, swap share) names its outcome in 69.3% of laws, five-fold, against 37.3% for
always guessing the commonest; it names a law that empties the graph in 95%, falls apart 80%, ends alike 79%, fills to
the cap 73%, but a melted lattice in 36%, a ring in under 1% and a rewired lattice never. So the null map predicts the
big stops before a law runs and not the kinds that read.

**The 533 melted lattices** (531 among the laws read here) are not one rule: 239 different sets of terms, 299 with
their signs. They run at finite temperature (89%, against 49% of the draw), most often one positive degree term
alone: degree_fourth_sum alone 47 times, wedge_count 25, degree_cube_sum 22, degree_square_sum 13. Grouped by which
terms they hold, no split is clean (silhouette 0.17 to 0.21 for two to eight groups); the five loosest groups are the
quartic degree term (189), the wedge (118), the cubic (95), the square sum (69) and the degree anchor with the quartic
at zero temperature (60). Where the terms lean: degree_anchor_abs in the rings (twice the draw's share),
degree_neighbor_gradient where starts stay apart or nothing reads (3.3 to 3.4 times), square_edge_overlap among the
laws that ran the whole ladder unread (4.1), induced_square_count where a dimension shows (4.9), degree_anchor where
every start ends alike (2.3) or fills the cap (2.1), and a graph fills the cap where the quartic is missing (0.17 of
its share).

**E8** (the operator's question of 00:25 and 00:40). The paper (K. L. Meyer, "Persistence Mechanics of the Quantum
Vacuum I", 2026-10-27, not peer reviewed) chooses a static lattice by postulates and computes one number from its
integers. What can be reproduced from it was: Zgeo = 43 pi + 2 - 1/167 - 2/43 + 334/(32^3 5 172) + 1/(31 6 43^2) =
137.035999212381397211..., all 18 certified decimals, and its 0.58, 3.09, 6.16 and 1.68 standard deviations from
Morel, Fan, Parker and CODATA 2022. It has no dynamics, no graph that grows, no data and no dimension reading; its Lean
proofs are in a repository the paper does not link. Nothing in it is a reading this instrument makes. What the
instrument can say about eight dimensions, the probes on this tree on the graphs themselves: the 8D cubic torus at
65,536 nodes (side 4, 16 neighbours) reads d_V 5.07 and d_s 6.7, and d_B and d_w refuse; at 6,561 nodes it is too
small. E8's torus at 256 and 6,561 nodes (120 and 240 neighbours) refuses: every point is two or three steps from
every other. At 65,536 nodes (side 4, 7,864,320 edges) all four refuse too: a ball holds 241 nodes at one step,
9,241 at two, 56,761 at three and the whole graph at four. Side 5 (390,625 nodes) is the largest the host could hold
and is five steps across. For a scaling window of a few steps at d 8, a side near 20 is needed, about 2.6 x 10^10
nodes with 240 neighbours each: no single machine. So raising the cap to 1,024, or to 240 (E8's kissing number, its
own degree), would let a law keep E8 and the probes still could not say it is eight-dimensional. A known-answer cell
of E8 and of the 8D cubic lattice is worth appending to the table as a refusal the probes must make at these sizes
(`docs/ROADMAP.md`, "Unscheduled").

## Left for a later build

The fleet ladder under the filters (`docs/ROADMAP.md`, "Planned builds"): today a line says how deep the laws the
filters keep went; its columns are the whole fleet's, summed on the server per rung, and filtering them needs the
server to sum them again over the filters' laws.

## What did not move

No score, kind, gate or decision: `tools/outputs_of_a_law.py --against` 859's record, 0 outputs changed. The Top 100
lists the same laws; only the order of equal scores changed.

## Verification

3970 passed in 1155.36s (3 lanes at once)
