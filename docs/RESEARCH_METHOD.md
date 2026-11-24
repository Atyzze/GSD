# Research method

The question, the design of the pilots on the new probes and of study A, the instrument's known limits, each number
with its source. `docs/readings/findings.json` names every section that states a finding beside its files and
the command that reads them again. `docs/ROADMAP.md` says what is next; `docs/DECISIONS.md` how the fleet decides.

**No data from a study before 169** (the operator, 2026-11-15 14:07: "only the pilot itself should steer the run, let
it learn-from its own CURRENT data, I want all other legacy data OUT"; 2026-11-18 16:43: "ALL old data we want GONE";
2026-11-20 03:09: "all references to studies/data older than 169 out"): each build that took some out sent it as an
archive beside its release (`docs/agent/NEXT_BUILD.md`, "Known blockers"), and nothing here rests on it. A file named
without a directory is in `docs/readings/` or `graph_scale_dynamics/resources/readings/`.

## Question

Can simple local rules make a graph grow a real dimension, of any d, whole or not; which keep one they are given; and
can the null map predict a law before it runs (the operator, 2026-10-13 and 2026-11-06)? Progress is how much of the
space no longer needs running, not how many laws have run.

## The design

Studies 169 to 172, the pilots on the final code after the recalibration (the cap at 32, to 65,536 nodes; the
operator, 2026-11-18 19:15 and 19:18, and 2026-11-20 14:20: "this is our baseline"), and study A after them:

- **Laws.** A few energy terms from the survey's grid, each with a plain coupling (free of N, the operator,
  2026-11-18 10:17), and Metropolis dynamics at zero or finite temperature, drawn blind, each from its own stream (its
  campaign's search seed and its index). A design fixes its campaigns' search seeds, and every law drawn is run; the
  curvature term is out of the pool (`terms_left_out`) and is its own study after A is replicated.
- **Population** (`spec.limits`): mean degree up to the design's cap (32 in the pilots), armed from 64; a connectivity
  floor; since 806 a
  budget per seed in the engines' weighted count of work, fixed per size in the design and the same on every machine
  (no clock ends a seed): a seed whose next chunk would not fit, or whose chunk passes the budget, ends on its last
  whole chunk, read as it stands, and stops no law; a law whose first chunk at the next size would not fit, predicted from its own seeds a size below, is stopped
  there as costing more than its budget (`over_budget`), a price and not a verdict.
- **The starts.** Eight, each a chain: empty, a random graph at a drawn degree, and the square, triangular, cubic,
  bcc, fcc and 4D lattices. Every chain decides alike; a hold counts where a lattice kept its reach, its mean degree,
  and its squares and triangles a node (`observability/starts_reading.py`).
- **Depth and the gates** (784 and 789, `docs/DECISIONS.md`): every gate at every size has its own counter, learned
  from the study's own decisions, every batch's laws at the same fixed points (832). A gate lets a tenth through from 256, each law drawn
  once for each gate and size, or once a size for every gate where a design sets `one_die` (study 172, 835); a design
  may set a gate's share (`gate_shares`); in studies 171 and 172 only the empty, too dense and disconnected gates act,
  every other gate recording. A law the dimension test reads only through lattice starts that kept their shape is
  parked as its own class (`kept_shape`, 789). A law whose every chain repeats a result 100 laws already kept one size
  up is withheld by `repeats_a_known_result` (`seen_enough` until 835), from 4,096.
- **The score** (`observability/law_score.py`): only readings from 4,096 on a piece of 4,096 nodes or more. Each
  probe and the Einstein relation earn 1 read at two sizes, 2 settled, 3 settled again; the twin starts count 1, a
  lattice start that changed 0.6, one that kept its shape 0.3; one no edge of which changed is frozen and its law
  scores 1, the lowest score (841).
- **The instrument**: d_s, d_V, d_B, d_w, the curvature and the structure census, analysis-5.3.0 on engine-3.3.0.
- **Committed before the run**: the design and its criterion, written fresh for each study. Every study is a folder registered in
  `graph_scale_dynamics/resources/readings/studies.json`, up to 100,000 laws (2026-10-02), with no limit on graphs (2026-11-16).

## The instrument and its known limits

- **The calibration table**, `calibration/seed_table.json`: every probe on the 27 calibration families at each size, as
  the operator's host measured it whole under analysis-5.3.0 on build 801 (2,584 cells, PASS), held by the hashes of
  the code that measured it (`graph_scale_dynamics/calibration/fingerprint.py`), and judged against the criterion
  committed before its zip was seen (`table_known_answers_criterion.json`; passes, 805). The lattice starts' references
  are cells of that table (each start a family at every size a law runs, its reading as a start beside its probes).
- **The starts' known answers** (602's eleven, written again for the eight starts at 819, `tools/starts_check.py`;
  its criterion, `graph_scale_dynamics/resources/readings/starts_known_answers_criterion.json`, committed before any
  case was read on seeds 0 to 2; `starts_known_answers_judged.json`): eleven laws of the eight starts' chains whose
  graphs are given, not grown (a lattice moved locally, melted, rewired, untouched, emptied or at the cap; random
  graphs), read by the starts' reading against the calibration table's own references at 1,024 and 4,096 nodes. 8 of
  the 11 cases pass. The three that miss are one fault: at 1,024 nodes a random graph of mean degree 6 in the chain from
  the face-centred cubic start reads partly kept (kept 0.63, where 0.5 to 0.8 is what a lattice with about 1% of its
  edges rewired keeps), half that lattice's degree; at 4,096 it reads melted. In all three the class the starts' rule
  decides by and the groups are as expected. So by its own rule the criterion does not pass; the fault is the fate's,
  which reads the reach alone below 0.8, and its fix waits for 169's bundle (`docs/ROADMAP.md`, "Unscheduled").
- **The noise floors** (`graph_scale_dynamics/resources/readings/noise_floors_analysis-4.0.0.json`), kept until the
  floors are each law's own errors (`docs/ROADMAP.md`, "Questions for the operator").
- **The structure rule has a blind spot** (read again on the final probes at 818, `tools/calibrate_structure.py
  --read-chained`; its criterion, `graph_scale_dynamics/resources/readings/chained_cubic_criterion.json`, committed
  before any graph was read; `chained_cubic_judged.json`): a random cubic graph with every edge a chain of 100 to 1,000,
  at 4,096 to 65,536 nodes, reads finite in 8 of 9 seeds by the rule alone at the gap threshold the survey runs (-0.309;
  6 of 9 at the engine's default, -0.3752), and the three readings together (rule, half-volume radius, local d_s
  against the gap's) refuse all 9. At these sizes they accept 7 of the 9 families of known finite dimension and say
  nothing of the Sierpinski gasket and carpet, which have two sizes each under 65,536, too few for the half-volume
  radius's exponent; so by the criterion's own rule (every family read accepted) it does not pass, nothing refused that
  has a dimension.
- **What the probes are**: until 761 d_s read near mean degree less one on a graph with no dimension (the tree line:
  the early slope of a decay, steady in N), which is why the decisions, the scores and the pages carried the line;
  since 761 no probe reads a graph whose balls grow exponentially, so the line's logic left at 790 and
  `tests/scientific/test_known_objects.py` holds the refusal on sparse random graphs. d_s has a ceiling that grows
  with N; a d_s that settles is not by itself a dimension.
- **The space score is narrow**: it calls the exact square, triangular and honeycomb lattices a space and none of the
  cubic, body-centred cubic, face-centred cubic and 4D lattices one, at the sizes from 1,024 to 1,048,576
  (`starts_known_answers_judged.json`, 819, on the table's own references). On the host's table of 2026-11-13 the probes are no longer why: its margins are
  0.15 about a whole dimension, and the instrument now reads the exact
  cubic lattice's probes at a median of 2.92 to 2.99 and the 4D lattice's at 3.76 to 3.95
  (`calibration/seed_table.json`; 2.58 to 2.86 and 2.77 to 3.69 on the table measured under 5.1). What refuses every
  lattice start of three and four dimensions is the reach: on an exact lattice it is a whole number of steps (7 at
  1,024 nodes and 73 at 1,048,576 on the cubic start), so from one size to the next it grows by a power of 0.29 to
  0.39 where the score allows 1/3 within 0.017, and on the 4D start by 0.23 to 0.34 where it allows 1/4 within 0.009;
  the 4D start's probes also lie 0.83 apart at 1,024. The square, the triangular and the honeycomb lattice are each
  called a space (`tests/unit/test_every_ladder_has_its_references.py`). The new score is designed with this in view
  (`docs/ROADMAP.md`).
- **The dimension test** (`research/dimension_test.py`): the reach must grow as a power of N, and the d that power
  implies must agree with the d the balls read at the top size (d_V and d_B). Its thresholds were set at 729 on 13
  training graphs (random geometric graphs in 2, 3 and 4 dimensions, the Sierpinski gasket, a ring, the three lattices;
  random graphs, a ring with shortcuts, chained regular graphs, hubs) and frozen. It was read again on the final probes
  at 808, its criterion committed first (`graph_scale_dynamics/resources/readings/dimension_test_criterion_4.json`),
  with 9 held-out graphs on seeds never read (`dimension_test_4_judged.json`). Every case passed on every seed: 4 of 4
  held-out geometries dimensional and inside their bands (critical percolation and a random tree among them), 5 of 5
  look-alikes not. On the geometries the two d's agree within 0.05 on training and 0.34 held out (the threshold is 0.4);
  every look-alike is refused at its top size before the two are compared, the probes reading no mass dimension there.
  The d it reports reads low on fractals (1.52 to 1.57 on percolation, whose d is 1.90; 1.82 to 2.03 on trees, d 2).
  The Einstein relation, d_s = 2 d_f / d_w, is not read on the 4D graphs at these sizes and missed by up to 0.38
  elsewhere, so it is reported and not judged. Its second and third criteria (750, 752) and 748's lattices with
  shortcuts, all read on older probes, left at 811.
- **Every chain's own count is fit at the survey's 16 samples** (built at 780, read again on the certificate as 803 to
  807 left it at 816; `research/certificate_known_answers.py`, `tools/certificate_known_answers.py`; its criterion,
  `graph_scale_dynamics/resources/readings/certificate_known_answers_criterion_3.json`, committed before it was run;
  `docs/readings/certificate_known_answers_3_judged.md`). Each chain of a rung is a stationary AR(1) series of known
  correlation time, 240 points read as the fleet reads a chain, by the count every chain runs (the smaller of the
  windowed sum and a batch-means count on 8 batches, on its late 60%); the rung's count is the smallest. At 16, a rung
  of 2 or 8 chains certifies a rung with one chain of at most 2 true samples in at most 5.0% of chunks and keeps 98.6%
  to 99.7% of rungs of plenty, where the count on the chain from empty alone certified such a rung 99.8% of the time.
  At the policy's default of 8 no rung is fit, a starved chain passing a rung up to 64.2% of the time, a batch-means
  count reading no lower than about its number of batches; the survey's campaigns and every design ask 16. Not a known
  answer for a chain still relaxing; the split between the chains, the drift and the structure's trend are the
  certificate's other readings, judged at 803 (`certificate_fixes_criterion.json`).
- **The curvature is Ollivier's only where triangles share no edge** (752, read again on the final code at 816,
  `research/curvature_known_answers.py`, `tools/curvature_known_answers.py`; its criterion,
  `graph_scale_dynamics/resources/readings/curvature_known_answers_criterion_2.json`, committed before it was run;
  `docs/readings/curvature_known_answers_2_judged.md`). The term `ollivier_curvature` and the curvature probe are Kelly,
  Trugenberger and Biancalana's formula from the triangles, squares and pentagons on an edge. Against Ollivier's
  curvature of the same edge, solved exactly as a transport, 8 of 8 predictions were right: it is exact on every edge
  read of the square, cubic and 4D tori, the ring, the honeycomb torus, the complete graph on 6 nodes and a random
  3-regular graph, and on the triangular torus it reads +1/3 on every edge where Ollivier's curvature is 0. On a random
  geometric graph in the plane it agrees on 47 of 300 edges and reads a mean of 0.40 against 0.11, never below; on a
  random graph of mean degree 4, on 295 of 300. So it over-reads the curvature of exactly the graphs a geometry is made
  of, and it is named for what it is in the paper; the exact curvature beside the formula is the small study before the
  curvature term's study (`docs/ROADMAP.md`). Nothing here says a law ran wrongly: the engines minimise the formula as written.
- **Which lattices a law of the fourteen terms can tell from a random graph** (757, read again on the final code at
  816, `research/start_admission.py`, `tools/start_admission.py`; its criterion,
  `graph_scale_dynamics/resources/readings/start_admission_criterion_2.json`, committed before it was run;
  `docs/readings/start_admission_2_judged.md`). A start no
  law can tell from a random graph of its degree can be kept or preferred by no law. A term tells a lattice when its
  energy a node there, taken alone with coupling 1, differs from its mean on random regular graphs of the same size and
  degree by at least 0.05 at 16,384 nodes and by at least half its difference at 1,024: an amount a node that does not
  shrink with N. All six lattice starts of study A are admitted: the square, cubic, body-centred cubic and 4D lattices
  are told by the three square terms and the curvature, the face-centred cubic lattice by those and the two triangle
  terms. The honeycomb and the diamond lattice, the two left out, are told by no term: the largest difference a node at
  16,384 nodes is 0.007 on the honeycomb and 0.062 on the diamond lattice, both in the curvature term and both shrinking
  as the lattice grows. One term list of eight is not as predicted: the triangular lattice is not told by its induced
  squares (0.005 a node at 16,384), every square of it carrying a chord. The curvature term reads the body-centred cubic
  and the 4D lattice alike to the last digit (378.53 a node above the random graphs' at 16,384), though the first has
  twelve squares on an edge and the second six: the formula saturates, reading a regular graph of degree 8 without
  triangles as flat from six squares an edge. The predictions were those of a scratch calculation made after a pilot
  had held no honeycomb, so the reading predicts only study A. It reads energies, no chain: whether a law keeps a lattice it can tell is what the study measures.
- **The probes' rounds before the lock** (760 to 764) left the tree at 809 with their criteria and readings: they
  judged the probes of their day, which 800 locked. What the final probes read on known answers is the calibration
  table, judged against the criterion committed before its zip was seen (802, passes at 805), and the dimension test
  read again (808, `dimension_test_criterion_4.json`). 764's criterion and rows, the score's first judgement, left at
  817.
- **What settles means for the score** (783, judged again on the final probes at 817; `research/score_known_answers.py`,
  `tools/score_known_answers.py`; its criterion,
  `graph_scale_dynamics/resources/readings/score_known_answers_criterion_3.json`, committed before any structure was
  read; `docs/readings/score_known_answers_3_judged.md`). Each probe's margin at each size is twice the widest step of
  the calibration table's exact lattices and fractals, three seeds a mean, on its grid, and the Einstein relation's
  tolerance the smallest of its grid above every training residual (0.075 of d_s). Judged on seventeen structures the
  table never measured, built to 65,536 nodes on seeds 51 to 53 and read by the final probes: every probe held at both
  sizes of a pair settles there (72 of 72), every structure held on all four is in the fifth band (15 of 15), no probe
  that must refuse settles (20 of 20: the random graphs, the small world, preferential attachment and the hyperbolic
  geometric graph), and the law score is 0 for each of those and 5 points at the top pair of the rest (16 of 16). The
  margins this rule trains on the installed table are the ones the score reads.
- **What a settled reading must also show, in force since 848** (846; `observability/law_score.py`, criteria
  `score_known_answers_criterion_4.json` and `_5.json`, each committed before its structures were built or read;
  `docs/readings/score_known_answers_4_judged.md` and `_5_judged.md`). Study 174's first bundle showed scoring laws
  whose seeds were still relaxing at their cap, a soup of cycles scoring on a piece of 14% of the graph, and laws
  whose reach grew far slower than the dimension their probes read. The candidate counts only settled seeds, holds
  the decision engine's connectivity floor, and lets a step settle only where the reach grows as the dimension read
  (q 0.2, twice the widest excess of the table's lattices) and the next step does not break it. On seeds 61 to 63
  every exact structure still settles (56 of 56 held probes, 11 of 11 in the fifth band), nothing that must refuse
  does (16 of 16), every strip or tube settles only as the line it is at that size (9 of 9: strips 40 and 56 wide,
  which the score in force settles at d 2, earn nothing), and a piece under half the graph earns nothing (3 of 3).
  It missed on trees of long paths (2 of 6): they settle at d 1.1 to 1.4, a ring by the score's label, under the score
  in force as under the candidate. Criterion 4, the first try on seeds 51 to 53, had also missed on strips 16 wide,
  which are lines at those sizes and settle correctly as lines: the criterion's prediction was wrong there, not the
  rule. By the criteria's own rule the score stayed `gsd-law-score-6` at 846; the operator put the candidate in force
  at 848 (2026-11-23 15:45), the trees of long paths a limit it shares with the score before it.
- **What the calibration table is held to** (since 805, `graph_scale_dynamics/resources/calibration/table_rule_2.json`:
  every family to what `table_known_answers_criterion.json` holds it to, as its passing judged reading found it; A4
  and D4 to the 4D lattice's bands from where their own cells read; random graphs of degree 16 and 32 refused like
  every graph without a dimension; `tools/table_rule.py`). Before it, 765's rule
  (committed 2026-11-12 14:43Z before any tolerance or size was computed from it;
  build 765's notes, in its archive), whose bands the criterion carries unchanged: A family with a dimension is held, probe by probe, to the band the fifth judged
  set held the same structure to, from the smallest size at which that set read it on every seed, and at a size between
  two judged ones to the band of the one below; a family without a dimension must be given no value by any probe from
  4,096 nodes; every other cell is measured and shown. No tolerance is typed by hand. The table has 23 families: the 17
  it had, four lattice starts as the fleet builds them at the eight sizes a law runs, and a hyperbolic tiling and a
  hyperbolic geometric graph it must refuse (27 since 800).
- **The engines keep and reach the Boltzmann measure of every term** (read on the engines as 806 left them, at 816;
  `research/boltzmann_known_answers.py`, `tools/boltzmann_known_answers.py`; its criterion,
  `graph_scale_dynamics/resources/readings/boltzmann_known_answers_criterion_4.json`, committed before it was run;
  `docs/readings/boltzmann_known_answers_4_judged.md`). On all 64 graphs of 4 nodes and all 1,024 of 5 the engine's own
  energy gives a law's exact measure at a finite temperature. Each run starts one chain at a graph drawn from that
  measure and one at the empty graph, and the graphs they end on are counted against it: a chain in balance ends
  distributed as it started, whether or not it mixed. 66 laws (each of the fourteen terms alone, twice; eight laws of
  two to four terms; each term again where the chain from empty is judged; two controls), their couplings set by their
  energy's span, their locality and swap share drawn, on both sizes and both engines, 2,000 runs a cell on Rust and
  1,000 on Python. The measure is kept in 260 of 260 cells and reached from empty in 112 of 112; the two engines give
  all 71,808 graphs the same energy to the last bit, and no chain ended carrying an energy that was not its graph's. The
  control that runs the toggle's law at twice its energy is refused in all four of its cells, and its counts agree in
  all four with the measure of the energies doubled, the one its chain keeps. The same counts refuse a measure with the
  energies doubled in 221 of 260 cells and one with them a quarter larger in 77, which is what the count can tell apart.
  Graphs of 4 and 5 nodes only; zero temperature and cooling are not read. It is read again whenever an engine changes.
- **A chain is a function of its law, N and seed**; only its wall-clock window can change it, so every study runs one
  worker a physical core.
- **An exactly neutral move is taken at zero temperature** (`engine.swap_change`), and `AT_REST` says the energy stopped
  falling and the structure stopped drifting over the same late window, not that every edge stopped moving (803): a
  graph that keeps swapping edges on a level energy with its measurements flat is at rest, as a finite-temperature
  chain whose measurements hold is equilibrated.

## The pilots on the new probes

None before 169 is kept. The pilots before it ran on probes that were about to change, and their designs, criteria,
readings and finds left the tree at 799 (the operator, 2026-11-18 16:43: "ALL old data we want GONE, and DEFINITELY
not in the paper"; 16:45: "why the hell are we even running pilots without first having fixed our probes??"). Study
169, on the fixed probes and the new table, is the first pilot whose numbers are read; the finds register is made
again after study A, from the candidates chosen there.

A pilot's numbers steer the builds and are thrown away: none is a finding (the operator, 2026-11-15 14:07).

## What study A tests

Each a hypothesis, read on study A alone (its laws, eight starts, no term the study leaves out), and on its replication.

* Almost every law drawn blind makes a random graph, whose d_s sits on the tree line.
* No law drawn blind grows a geometry, of any d, from empty or from a random graph under the tree's dynamics.
* A law that holds a lattice holds it with its structure as N grows; a law that changes a lattice changes some and
  keeps others (in the pilots, the triangular and fcc lattices kept where the bcc is not).
* A d_s that settles where no other reading finds a dimension is local structure, not a dimension.
* Every gate confirms itself on the study's own laws (784): what a gate withholds is withheld again one size up.
* The batches are one sample; the controls grow no lattice from empty and hold the one they start on.

## The programme

The positive control first: until the survey has recognised a geometry it was shown, its "no" means "not reached this
way". Then, each study read on its own data alone (a map fitted on a
study's own trial may come back, by the operator's word): map the declared
space and remember every outlier; retire known patterns; a focus campaign on the best anchor, sampled around its lineage (single changes, `lineage_parent` filled, held out by family, never built);
the literature as a test set (`tools/replication.py`; the 2019 model of Kelly, Trugenberger and Biancalana run again
after the paper's three studies, its criterion written fresh on the final probes, its earlier readings out at 829); new terms one at a time against a control arm; publish and ask
for untried terms. A stage is done when the map stops gaining structure, the model predicts held-out laws within a
stated error, and the compute saved is counted. The guard against fitting what was seen: a prediction committed before
the run, never revised; a criterion revised after its run is a new criterion.

## What is not claimed

A settled probe is not a true dimension; probe agreement and the Einstein relation are diagnostics. A refusal is a
finding about the law under this sampler at this N. Nothing read before study 169 is claimed, but what the instrument
reads on known answers. What is open is
`docs/ROADMAP.md`.

## The papers read

Cited by arXiv id and the version read. The tree is public and keeps no copy of any paper (the operator, 2026-11-24); until 848 a copy of each was kept, and the 848 archive holds them.

| Authors | Title | Source | Use |
| --- | --- | --- | --- |
| Christy Kelly, Carlo A. Trugenberger, Fabio Biancalana | Self-assembly of geometric space from random graphs | arXiv:1901.09870v2 | replicated (paper 1) |
| Christy Kelly, Carlo Trugenberger, Fabio Biancalana | Emergence of the circle in a statistical model of random cubic graphs | arXiv:2008.11779v3 | replicated (paper 1) |
| Christy Kelly | Emergent geometry and discrete curvature in random graphs | handle 10399/4591 | paper 1's thesis |
| Florian Conrady | Space as a low-temperature regime of graphs | arXiv:1009.3195v3 | replicated (paper 2) |
| Tomasz Konopka, Fotini Markopoulou, Simone Severini | Quantum graphity: a model of emergent locality | arXiv:0801.0861v2 | replicated (paper 3) |
| Tomasz Konopka, Fotini Markopoulou, Lee Smolin | Quantum graphity | arXiv:hep-th/0611197v1 | paper 3's model |
| J. Ambjorn, J. Jurkiewicz, Y. Watabiki | On the fractal structure of two-dimensional quantum gravity | arXiv:hep-lat/9507014v1 | slot 4, unbuilt |
| Ginestra Bianconi, Christoph Rahmede | Network geometry with flavor: from complexity to quantum geometry | arXiv:1511.04539v2 | slot 4's alternative |
| Yann Ollivier | Ricci curvature of Markov chains on metric spaces | arXiv:math/0701886v4 | the curvature read |
| Juyong Park, M. E. J. Newman | The statistical mechanics of networks | arXiv:cond-mat/0405566v1 | related work |
| Sourav Chatterjee, Persi Diaconis | Estimating and understanding exponential random graph models | arXiv:1102.2650v5 | related work |
| J. Ambjorn, J. Jurkiewicz, R. Loll | Emergence of a 4D world from causal quantum gravity | arXiv:hep-th/0404156v4 | related work |
| J. Ambjorn, J. Jurkiewicz, R. Loll | Spectral dimension of the universe | arXiv:hep-th/0505113v2 | related work |
| D. P. Rideout, R. D. Sorkin | A classical sequential growth dynamics for causal sets | arXiv:gr-qc/9904062v3 | related work |
| Joe Henson | The causal set approach to quantum gravity | arXiv:gr-qc/0601121v2 | related work |
| Jonathan Gorard | Some relativistic and gravitational properties of the Wolfram model | arXiv:2004.14810v2 | related work |
| Dmitri Krioukov, Fragkiskos Papadopoulos, Maksim Kitsak, Amin Vahdat, Marian Boguna | Hyperbolic geometry of complex networks | arXiv:1006.5169v2 | related work |
| Zhihao Wu, Giulia Menichetti, Christoph Rahmede, Ginestra Bianconi | Emergent complex network geometry | arXiv:1412.3405v2 | related work |
| Carlo A. Trugenberger | Combinatorial quantum gravity: geometry from random bits | arXiv:1610.05934v3 | related work |
| Alessandro Bisio, Giacomo Mauro D'Ariano, Alessandro Tosini | Quantum field as a quantum cellular automaton: the Dirac free evolution in one dimension | arXiv:1212.2839v2 | related work, abstract read: the fixed graph with a derived rule, the other end from a grown graph; its bound on telling the automaton from the Dirac evolution is the bar for any claim of physics |
| G. M. D'Ariano, P. Perinotti | Derivation of the Dirac equation from principles of information processing | arXiv:1306.1934v2 | related work, abstract read: homogeneity makes the graph a Cayley graph, so the automaton runs on no grown graph with defects; the quantum walk (855) is what runs on any graph |
