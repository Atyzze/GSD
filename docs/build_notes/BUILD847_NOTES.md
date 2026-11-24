# Build 847: study 175, the perturbation side study, is designed and committed, and a reader of what the top laws share reads study 174. It may be started in a folder of its own; it changes nothing in force.

**Type: a study's design and two readers, asked for by the operator on 2026-11-23 at 11:21 ("a specific side study to
randomly perturb all the best candidates and see whether or not theres a region or if its all one-off flukes where
changing even 0.001 changes the entire thing"; "a deeper analysis on the similarities between the top scores is in
order too").** New: `graph_scale_dynamics/research/perturb.py`, `tools/perturb_reading.py`, `tools/top_laws_alike.py`,
`graph_scale_dynamics/resources/readings/study_175_holders.json`, `study_175_design.json` and `study_175_criterion.json`
(the criterion committed before any start, naming the design and the holders by sha256); tests
`tests/unit/test_the_perturbation_side_study.py`, `tests/unit/test_what_the_top_laws_share.py`,
`tests/integration/test_study_175_starts_its_laws_postgres.py`. Changed: `graph_scale_dynamics/operations/study_design.py`
(a campaign of kind `perturb`, `perturb_laws`, `fixed_laws`), `graph_scale_dynamics/resources/readings/studies.json` (175
registered), `tests/unit/test_study_174_is_the_stable_trial.py` (174 found in the register by its id, not as the last
entry). Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/`, `engine_rs/` or `observability/` moved; no
frozen source moved; the score in force is still `gsd-law-score-6`. Against 846's record (`tools/outputs_of_a_law.py
--against`) 0 outputs moved.

## The holders

The 35 drawn laws of study 174's first bundle (2026-11-23 09:52Z) that the score in force and its candidate both
settle, their scoring start not frozen, each rebuilt from its law ledger row and kept only because its fingerprint is
its id (`study_175_holders.json`, with what each read in 174: its chain, d, mean degree, top size and the values of its
chain at every size). Every one reads a lattice start: 22 bcc, 3 triangular, 3 cubic, 3 fcc, 2 square, 2 tesseract;
26 reach 65,536 and 9 stop at 16,384; 19 are zero-temperature laws. The standing controls are left out (their chain
starts at their answer), as are the 7 frozen lattices (score 1) and the 16 laws that only read at two sizes.

## The design

Each holder runs again as it is, on the same seeds: the fleet is deterministic, so it reads what it read in 174 (P1).
Then four variants at each of four radii. Every real parameter of the law (each term's coefficient, a power's
exponent, beta at finite temperature, the locality and the swap share where drawn) moves together by between half
the radius and the radius, up or down, from a stream keyed by the study, the holder, the radius and the variant, and
is kept to 12 significant figures. A zero-temperature law keeps its beta, which its dynamics never read. 1e-9 moves
nothing a chain can feel; it only gives the law new random numbers, because a chain's stream is keyed by its law's
fingerprint, and so it is the matched control: the spread of the law itself. 0.001 is the operator's question; 0.01
and 0.1 say how wide a region is. A variant must stay in the declared space (the language's checks and the proposer's:
a sparse phase, bounded below, within the coefficient bound); none of the 560 had to be drawn again, and the largest
change at each radius is 0.999 of it or more. 595 laws in one hand campaign on 174's ladder, starts, budgets and fact gates;
starts_alike and nothing_read record, so that no variant is stopped on a judgment its holder passed. The laws' sha256
is in the design and `start` refuses a tree that draws them otherwise; started on PostgreSQL, it makes one campaign of
595 proposed laws and draws none (the integration test).

## The verdict, committed first

A holder's behaviour is what its scoring chain reads at its top size in 174: the median of its probes there (its d)
and its mean degree. A variant is alike when the same chain reads at that size with its d and mean degree each within
a tenth of the holder's. With fewer than 3 of the 4 stream variants alike, the holder's reading was its random
numbers', not its law's (a stream verdict). Otherwise a radius holds when 3 of its 4 variants are alike, and the holder
is a region to the largest radius up to which every radius holds, or a point when 0.001 does not hold. How many of
each is the question and is not predicted. P1: every holder run again reads its 174 values; P2: every planned law is
in the bundle read; P3: 400 to 900 core-hours, from the holders' own cost in 174 (13.4 engine core-hours, times 174's
2.67 core-hours an engine core-hour, times 17 laws each: about 600, a day and a half on 16 workers).

## What the top laws share, read on 174's first bundle

`tools/top_laws_alike.py`, the same 35 laws beside the 2,583 that reached 4,096:

* **Squares.** `square_edge_overlap` is in 16 of the 35, always with a negative coefficient (an energy that squares
  lower), 3.7 times its share among the laws that reached 4,096; `induced_square_count` 2.4 times (7 of 10 negative),
  `square_count` 2.0 times (7 of 8 negative). Degree anchors are half as common (0.53; their absolute form 0.29), and
  `triangle_edge_overlap` 0.47.
* **Cold.** At finite temperature their median beta is 12.1 against 1.8; they move more locally (locality 0.67 against
  0.51) and swap more (0.66 against 0.52). 54% are zero-temperature laws against 46%.
* **By the dimension read.** About 3: 26 laws (bcc 20, fcc 3, cubic 3), `square_edge_overlap` in 15 of them. About 2:
  5 laws (triangular 3, square 2). About 4: 4 laws (tesseract 2, bcc 2), `induced_square_count` in 3.
* **No recipe.** The 35 laws hold 32 different term sets; no set appears more than twice. What they share is a trait
  (rewarding squares, cold), not a formula, and every one keeps or partly keeps the lattice it was given: none grows its
  dimension from empty or random. Whether that trait is a region of laws or 35 points is what study 175 reads.

## Running it

In a folder of its own: `uv run python main.py run --study 175`. Beside 174 on the same host, give each folder part
of the workers on its System page (846). Its bundle is read by `tools/perturb_reading.py` and
`tools/top_laws_alike.py`.

## Verification

3885 passed in 1590.53s (3 lanes at once)
