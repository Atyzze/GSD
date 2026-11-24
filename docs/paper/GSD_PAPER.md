# Graph Scale Dynamics: a pre-registered blind survey of local energy rules on sparse graphs, and the instrument that sorts what they do

**A working draft, 2026-11-24 (build 854).** No result is claimed in this draft. It describes an instrument, the two data
sets it rests on, what the instrument reads on them, and what it cannot do yet. Where we offer a reading of the data
we say so and give the other readings we can think of. We ask for yours (section 9).

Code: <https://github.com/Atyzze/GSD>. Every number below is from the two study bundles named in section 4, the
calibration table, or a measurement this draft describes, and each says where it comes from.

## Abstract

We built a pipeline that takes a rule for how a graph changes (an energy made of a few local counts, such as how many
triangles or squares there are, plus a temperature), grows a graph under it from eight different starting graphs at
sizes from 64 to 65,536 nodes, and measures how the result behaves as it grows: four estimates of dimension, how far
apart nodes are, how much of the graph is one piece, and whether it still looks like where it started. Before any
study runs, its design and the criterion it will be judged by are written down with a time stamp, and a criterion
revised after its run counts as a new one. On two data sets (a blind draw of laws, 8,131 of them read so far, and 595
small variations around 35 laws that the first draw singled out) the instrument sorts laws into eleven kinds of
behaviour. We report what it sorts, how early each kind can be recognised, and three things we got wrong on the way.
The most important limit: under our dynamics, a law whose lowest-energy state is a flat square lattice does not reach
that lattice from an empty graph (it gets 68% to 81% of the way in energy). So the survey cannot yet tell a law that
grows no geometry from a law whose geometry the dynamics cannot reach.

## 1. The question, in plain words

Can a simple local rule, applied over and over to a graph, make the graph look like a space of some dimension when you
step back? Which rules keep a space they are given? And can we tell what a rule will do before running it?

"Look like a space" has a concrete meaning here. In a d-dimensional space the number of points within distance r grows
like r to the power d, a random walker spreads at a predictable rate, and these readings agree with each other and stay
the same as the graph gets bigger. A graph whose readings change with its size, or disagree with each other, is not
read as having a dimension.

## 2. What was built

**Laws.** A law is an energy made of up to a few terms from a fixed list of fourteen (counts of edges, triangles,
squares, wedges; sums of powers of the degrees; a pull toward a chosen degree; the difference of degree between
neighbours; terms for triangles or squares that share an edge; and a curvature term), each with a coupling that does not depend on the graph's size, plus a temperature. At
zero temperature a move is taken only if it does not raise the energy. At a finite temperature a move that raises it
is taken with the usual Metropolis probability. The moves add an edge, delete one, or swap one; a share of them is local
(toggling an edge between two neighbours of a node).

**Engines.** Two independent engines (Rust and a Python reference) give every graph of 4 and 5 nodes, all 1,088 of
them, the same energy to the last bit. On those graphs each engine was checked to keep and to reach the exact
Boltzmann distribution of each term (`docs/readings/boltzmann_known_answers_4_judged.md`). This checks the move
probabilities; it says nothing about how fast a large graph gets anywhere.

**Starts.** Every law is run as eight chains: from the empty graph, from a random graph, and from six lattices (square,
triangular, cubic, body-centred cubic, face-centred cubic and four-dimensional). The empty and random starts are the
"twins": anything they share was made by the law, not given to it.

**Sizes.** 64, 256, 1,024, 4,096, 16,384 and 65,536 nodes, three seeds at each. A law goes to the next size only if
gates let it (an empty graph or a graph at the density cap stops it; a tenth of what a gate would stop goes on anyway,
so the gates' own error rate is measured).

**Probes.** Four estimates of dimension: spectral (d_s, from how a random walk returns), volume (d_V, from how balls
grow), boundary (d_B) and walk (d_w), plus the relation d_s = 2 d_V / d_w between them. Each probe may refuse to give a
number, and does on graphs where it cannot be trusted.

**Calibration.** The probes were run on 27 families of graphs whose answers are known (lattices, fractals, random
graphs, a ring, and others) at every size, 2,584 cells, and the table was judged against a criterion written before
the table was seen; it passes (`docs/readings/table_known_answers_judged.md`). The table has not changed since and is
part of the baseline.

**The score.** A law earns points when a probe's reading at one size agrees with the next size's within a margin set by
the calibration table, more for agreeing again, and only on graphs where the distance between nodes grows as the
dimension read says it should (`observability/law_score.py`). A lattice start that no edge of which changed earns the
lowest score.

**The catalogue.** Eleven kinds of behaviour, each with a rule that recognises it and the numbers the rule uses
(`graph_scale_dynamics/resources/catalogue/catalogue.json`): *grown* (a probe settles on a twin start), *made* (two or
more starts end at the same dimension and degree), *ring* (they agree on a dimension below 1.5), *empty*, *full* (at
the density cap), *frozen* (a lattice start no edge of which changed), *still* (a lattice start that barely changed),
*rewired*, *moved* (melted), *broken* and *unread*.

**Pre-registration.** Every study's design and criterion, and every check of the instrument, has a file with a time
stamp from before its data was read (`graph_scale_dynamics/resources/readings/`).

## 3. What the instrument gets right, and where it fails its own tests

Passed, each against a criterion written first:

- The calibration table (above).
- The dimension test: 9 graphs held out from its training, 4 with a dimension and 5 look-alikes, every one sorted right
  on every seed (`docs/readings/dimension_test_4_judged.md`).
- What "settles" means for the score: 17 structures the table never measured, read at 65,536 nodes; every probe that
  should settle does, none that should refuse does (`docs/readings/score_known_answers_3_judged.md`).
- The engines' Boltzmann check (section 2).

Failed by their own rule, and still in use. We list them as fails:

- **The score in force** (since 2026-11-23). Its criterion missed on trees whose branches are long paths: they settle at
  d 1.1 to 1.4, read as a ring (2 of 6 cases; `docs/readings/score_known_answers_5_judged.md`). It was put in force
  anyway, by a decision recorded with its reason; the previous score has the same blind spot.
- **The reading of whether a lattice start kept its shape**: 8 of 11 known cases right; the three misses are one fault
  (a random graph started from the face-centred cubic lattice reads as partly kept at 1,024 nodes).
- **The structure rule**: a random cubic graph whose every edge is a long chain reads as having a finite dimension in 8
  of 9 seeds by the rule alone (the three readings together refuse all 9).
- **The positive control** in the latest bundle: P1, a law whose lowest-energy state is the square lattice, started on
  that lattice, reads d_V 2.36 at 65,536 nodes where its criterion asks 2 within 0.1 (its other probes read 1.98 to
  2.12). The other four controls pass. Every one of the four positive controls reads no finite dimension from the empty
  start, which their criterion expected.

## 4. The data: two bundles

Everything this draft reads from the survey comes from two bundles, the baseline from 2026-11-24 on. Studies before
these, and their data, are not used.

**Study 174, the blind draw** (bundle built 2026-11-24 14:22Z). Laws drawn blind from the fourteen terms, in ten
batches of 1,000, each law on the eight starts. So far 8,131 laws have been read (plus 5 control laws, read apart). The
deepest size each reached: 4,671 laws at 1,024 nodes, 3,024 at 4,096, 362 at 16,384, 74 at 65,536.

**Study 175, the neighbourhoods** (bundle built 2026-11-24 08:35Z). The 35 laws that study 174's first bundle singled
out, each with 16 small variations of its couplings: 595 laws, read at the same sizes.

## 5. What the data show

These are readings of two data sets, not findings. Each is reproducible with the command named.

**5.1 What the blind laws do** (`tools/catalogue_reading.py`, study 174):

| kind | laws | kind | laws |
|---|---|---|---|
| empty | 3,202 | ring | 303 |
| moved (melted) | 2,889 | unread | 87 |
| full | 996 | still | 72 |
| rewired | 475 | frozen | 56 |
| broken | 33 | grown | 10 |
| made | 8 | | |

Most blind laws empty the graph, fill it to the cap, or melt the lattices they are given.

**5.2 What "settles" mostly is.** Of the 83 laws the score in force gives points in study 174, 64 are a lattice start
that barely changed. In study 175, 32 of the 35 central laws accept moves on fewer than 5% of their edges, and for 34
of them no other start reaches the same dimension and degree. Our reading: what settles is mostly a start being
remembered, not a dimension the law selects. The score in force does not yet tell these apart; a criterion written
before the latest bundle (`still_lattice_criterion_1.json`) asked whether a still lattice can be recognised early, and
on the latest bundle it can: every lattice start called still at 1,024 nodes (89) or at 4,096 (39) stayed still at
every larger size, and no early still call hid a law that turned out *made* or *ring*.

**5.3 What grows from nothing.** Ten laws settle a probe on a twin start at three sizes in a row, by its value. All are
one-dimensional by their probes (d_s 0.98 to 1.06 at 65,536 nodes). Five end as open strings with no cycle at all. Four
end as one loop holding nearly every node (99.7% to 100%) plus a few extra edges: about 13, 35, 108 and 284 at 65,536
nodes. One ends as small, nearly complete clusters strung into strands (clustering 0.96, every node on a cycle). A
clean loop of 65,536 nodes has a half-volume radius of 16,384 steps; with 10 random chords added it is 5,706, with 30
chords 2,598; the loops with 13 and 35 extra edges read 4,891 and 2,512. Our reading: the loops are one-dimensional only
up to a few thousand nodes, after which their few shortcuts make them a web. The score in force gives none of the ten
points for settling, which agrees with that reading for the loops; for the open strings it does not say why.

**5.4 When different starts agree.** Eight laws are *made*: two or more starts end at the same dimension and degree. In
two of them (3931d03e8edf and fdc563a72c98), every start ends at nearly the same mean degree (fdc563a72c98: 17.02 to
17.05 on all eight), the chain from empty is flagged small-world on every seed, clustering is low (0.005 to 0.09), and
distances barely grow: from 1,024 to 16,384 nodes the empty start's half-volume radius goes from 3 to 4 steps, where a
3.5-dimensional space would need it to more than double. Their dimension readings rise with size (fdc563a72c98 on the
fcc start: d_s 3.5 at 4,096 and 3.6 at 16,384, d_V 4.6 and 5.5). Our reading: these starts agree because each forgets
where it began, as a random graph does. The other reading, a space of dimension near 3.5 to 4 seen too small, predicts
a radius that keeps growing like a power of N; the next sizes would tell.

**5.5 A law that changes its behaviour with size.** de7ab4a85198 (squares rewarded, high degrees penalised, zero
temperature): at 256, 1,024 and 4,096 nodes, no edge changed on any lattice start that kept its degree (the
catalogue's *frozen*). At 16,384 its cubic start lost about a third of its edges (mean degree 6 to 4.15) and reads
about two dimensions, like its square start, while its bcc start stayed untouched. One
reading: a metastable lattice that escapes only when the graph is large enough for an escape to begin somewhere
(nucleation). Another: a run-length effect, since larger graphs get longer runs. It is one law and three seeds.

**5.6 How early a kind can be recognised.** Of the laws read from 16,384 nodes, the kind called at 4,096 held to the
deepest size for still lattices 21 of 21, frozen 9 of 10, empty 10 of 10, rewired 46 of 50, melted 145 of 202, and
ring 30 of 47. In study 175, every early frozen or still call held (211 of 211 at 4,096). Stopping a law early by its
kind is therefore safe for some kinds and not for others; section 5.5 is a case where an early frozen call would have
stopped a law that later changed.

## 6. What the instrument cannot do yet

**The runs from empty do not reach a known geometry.** P1's lowest-energy state is the square lattice. We ran it (and
P2, the same law colder) under the survey's own policy, 4,000 sweeps, on the Rust engine, two seeds a size, and
compared the energy each chain ended at with the lattice's:

| law | 256 nodes | 1,024 | 4,096 |
|---|---|---|---|
| P1, from empty, share of the lattice's energy | 0.79, 0.81 | 0.76, 0.77 | 0.68, 0.68 |
| P2, colder | 0.82, 0.83 | 0.78, 0.79 | 0.70, 0.70 |

Started on the lattice, both stay within 0.4% of its energy. The share falls as the graph grows. An outside review of
the code (2026-11-24) measured the same trap independently, with up to 64 times more sweeps and with annealing, and
found it holds. So the hypothesis "no law drawn blind grows a geometry from empty" would come out true under these
dynamics whatever the laws are, and we do not test it until a known law grows its geometry from empty. The standard
remedies are parallel tempering (copies at several temperatures that swap), moves that change a whole square or
triangle at once, and growing the graph node by node.

**Every size gets the same number of sweeps.** A larger graph is therefore given less time per node to relax.

**Trees of long paths settle as rings** (section 3).

**Studies before the two bundles are not used here.** Their data were taken out of the working tree and kept in
archives beside the builds that removed them. They are not public yet.

## 7. Interpretations we offer, and the others we can think of

1. *Most of what scores is memory.* If the survey's points go mostly to lattices left alone (5.2), the useful signal is
   in the twins and in laws where different starts agree. Other reading: lattices left alone are what a local energy
   should do with a lattice that is already its minimum, and they are a result about those laws.
2. *Agreement of starts is not enough.* Starts can agree because the law selects a structure, or because every start
   forgets itself (5.4). The two are told apart by how distances grow with size.
3. *The strings and loops are the simplest thing a law can make.* Ten of the laws that make something from nothing make
   something one-dimensional (5.3). Other reading: the sampler's trap (section 6) lets only one-dimensional structures
   form in the time given.
4. *Size can change a law's kind* (5.5). If this is nucleation, the boundary it sits near is a first-order transition,
   and the hysteresis between the run from empty and the run from the lattice (section 6) is its signature too.

## 8. Musings, not claims

These are the directions the project's operator and its contributors talk about. Nothing in sections 1 to 7 supports
them yet; they are here so a reader knows where the instrument is meant to go.

- **A map of phases.** Materials science keeps maps of where each phase of a material is stable: one database holds
  more than 40,000 binary and ternary alloy phase diagrams, and computed databases build zero-temperature phase
  diagrams from the energies of competing crystal structures. The catalogue (section 2) is a first, coarse legend for
  such a map over graph laws; the map itself (where each kind meets each other kind) is not drawn yet. The cheapest way
  we see to draw a boundary is to run the laws on the straight line between two laws of different kinds and halve the
  interval where the kind flips.
- **Planted laws as known answers.** Laws others built to make a space (the curvature action of Kelly, Trugenberger and
  Biancalana; Conrady's; quantum graphity) can be put into the search as known answers: a survey that is working should
  find them again, and find their neighbours. Today one of them (the curvature action, control C1) holds the cubic
  lattice when started there, and reads no dimension from empty, like the other controls.
- **A term for close packing.** A pull on how many triangles each edge sits in, toward 4, together with a degree near
  12, should favour the face-centred cubic lattice (the structure of gold, in which every bonded pair of atoms shares
  exactly four neighbours). It would be a known answer for "made" from the twins, and a temperature sweep would show
  whether it melts sharply. It is not built.
- **Energy as bookkeeping.** In the sampler energy is only the weight that sets the odds of a move; nothing conserves
  it. Whether any law here has a conserved quantity is not asked yet.

## 9. What we ask of readers

1. Is the trap in section 6 a known first-order (degenerate) transition of these energies, as in exponential random
   graph models, and which sampler would you trust to get past it for these moves?
2. How would you tell a small-world graph from a space of dimension 3.5 to 4 at 65,536 nodes, beyond how distances grow?
3. Which laws from your own work would you plant as known answers (8)?
4. Is there a reading of 5.3 (strings and loops from nothing) that we are missing?
5. Which of the fails in section 3 would stop you trusting the rest?
6. What would you need to rerun one law yourself in five minutes? (Today it needs the project's database; a path
   without it is planned.)

Comments are welcome as issues on the repository.

## References

Cited by arXiv id; the tree keeps no copy of any paper.

- C. Kelly, C. A. Trugenberger, F. Biancalana, *Self-assembly of geometric space from random graphs*, arXiv:1901.09870.
- C. Kelly, C. Trugenberger, F. Biancalana, *Emergence of the circle in a statistical model of random cubic graphs*,
  arXiv:2008.11779.
- F. Conrady, *Space as a low-temperature regime of graphs*, arXiv:1009.3195.
- T. Konopka, F. Markopoulou, S. Severini, *Quantum graphity: a model of emergent locality*, arXiv:0801.0861.
- T. Konopka, F. Markopoulou, L. Smolin, *Quantum graphity*, arXiv:hep-th/0611197.
- J. Ambjorn, J. Jurkiewicz, R. Loll, *Emergence of a 4D world from causal quantum gravity*, arXiv:hep-th/0404156.
- J. Ambjorn, J. Jurkiewicz, R. Loll, *Spectral dimension of the universe*, arXiv:hep-th/0505113.
- J. Ambjorn, J. Jurkiewicz, Y. Watabiki, *On the fractal structure of two-dimensional quantum gravity*,
  arXiv:hep-lat/9507014.
- J. Park, M. E. J. Newman, *The statistical mechanics of networks*, arXiv:cond-mat/0405566.
- S. Chatterjee, P. Diaconis, *Estimating and understanding exponential random graph models*, arXiv:1102.2650.
- Y. Ollivier, *Ricci curvature of Markov chains on metric spaces*, arXiv:math/0701886.
- D. P. Rideout, R. D. Sorkin, *A classical sequential growth dynamics for causal sets*, arXiv:gr-qc/9904062.
- J. Henson, *The causal set approach to quantum gravity*, arXiv:gr-qc/0601121.
- J. Gorard, *Some relativistic and gravitational properties of the Wolfram model*, arXiv:2004.14810.
- D. Krioukov et al., *Hyperbolic geometry of complex networks*, arXiv:1006.5169.
- G. Bianconi, C. Rahmede, *Network geometry with flavor*, arXiv:1511.04539.
- ASM International, *Alloy Phase Diagram Database* (more than 40,000 binary and ternary diagrams).
- The Materials Project, *Phase diagrams*, docs.materialsproject.org (the convex-hull construction).
- Z. Wu, G. Menichetti, C. Rahmede, G. Bianconi, *Emergent complex network geometry*, arXiv:1412.3405.
- C. A. Trugenberger, *Combinatorial quantum gravity: geometry from random bits*, arXiv:1610.05934.

## Where each number comes from

| section | source |
|---|---|
| 3 | the judged files named there, in `docs/readings/` and `graph_scale_dynamics/resources/readings/` |
| 3, the controls | `tools/positive_control.py check` on study 174's bundle of 2026-11-24 14:22Z |
| 4, 5.1, 5.2, 5.6 | `tools/catalogue_reading.py` on each bundle; `still_lattice_judged_1.json` |
| 5.3 | the bundles' `tables/rungs.ndjson.gz` (the chain from empty) and `measurements/estimators.volume_growth` on rings with chords (build 853's notes) |
| 5.4, 5.5 | `finds.json` and `tables/rungs.ndjson.gz` of the bundles |
| 6 | `docs/build_notes/BUILD854_NOTES.md`, "The trap from empty", with the script that measured it |
