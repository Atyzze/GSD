# The zone map: where the project is heading

The heading the operator set on 2026-11-26, 19:06 to 19:59, and what the data and the code already say about it.
Builds from 887 follow it; `docs/agent/NEXT_BUILD.md` says the next step, `docs/ROADMAP.md` ("From 886") the order.

## The aim

The dex ends as a list of **zones**, not laws. A zone is a region of law space where every law does the same thing.
Each zone is named by its **central law**: the law in the middle of its boundaries, run and pushed to the largest N
the host allows. That run is the zone's signature, its pillar of data; every other law of the zone is described by its
distance from it. A law with no zone around it is **a lucky hit**: its readings are kept, to be revisited.

The operator's words: "the central last law pushed to the highest N becomes its real signature then, all other laws
are then simply a derivation/distance/range-from the central data pillar" (19:49); "the DEX should in the end just be a
list of zones" (19:21); "laws can obviously belong in multiple zones, there will be overlap regions between terms"
(19:59).

## Law space

* **Every coupling of every term.** A term a law lacks is a coupling of 0, so the term sets are not separate spaces:
  each is a face of one space, and two term sets meet where a coupling goes to 0. A zone can cross from one term set
  into another through such a face; switching a term off, and setting it to 0, are the steps that find out.
  `focus_regions` already counts a missing term as 0 in a region's ranges.
* **The dynamics**: the inverse temperature or zero temperature, the locality, the move mix.
* **N, the axis of resolution.** The same law shows more of itself the larger it is run; see "Zones over N".

The term sets of the dex of 2026-11-26 15:11Z (`dex_177_2026-11-26T15-11-31Z`, read at 886): 132 laws in 76 term sets,
so most laws have no relative near enough to share a zone with. The exception is 45 laws of one term set
(`degree_anchor`, `degree_anchor_abs`, `degree_neighbor_gradient`, `induced_square_count`, zero temperature), every
pair within 0.41 and 400 of the 990 pairs within 0.1: S176-C11-G79 (S174-C3-f270d87c) and 44 of the neighbours study
176's focus drew around it before that focus froze (881's notes). With the three drawn with one term switched off, 47
of its 48 neighbours score here, every one 1, none judged for its kind. S176-C15-G1, scoring 17, is a standing control, a law of known answer, not a find.

## What separates two zones: behaviour, read from the curves

Not the term set and not the couplings: what the law does. What a law does is read, for each of its eight starts,
from its probes as curves over N: the four dimensions (d_s, what a random walk feels; d_V, how balls grow; d_B, the
box dimension; d_w, how far a walk gets), and beside them the mean degree, the giant piece and the reach. Everything
else the project reads (the kind, the score, the lexicon's nearest type) is made from those.

**The phenotype (879) is the quantizer already in the code** (`observability/phenotype.py`,
`resources/catalogue/phenotype.json`): each curve from 256 described by the fewest of three forms, a constant (within
5% of its weighted mean), a power of N or a line in log N, and named in categories ("reach as N^(1/2), d near 2",
"reach as log N, an expander or a tree"). Twenty geometries of the calibration table take the forms they predict, the
exponents within 0.06. Two phenotypes are as alike as the share of categories they hold in common.

**Proposed, for the operator** ("What makes a neighbour alike", `docs/ROADMAP.md`): two laws are alike at N when every
curve both have **locked in** by N takes the same form, at the same value or exponent within the score's own margins,
and their starts relate the same way (the twins, empty and random, agreeing or not; the lattice starts kept, changed
or lost). A curve is locked in when its form holds over at least three sizes; one that is not yet locked in does not
count either way. More readings lock in more curves, so more readings give more structure, never less: two laws alike
at 4,096 may be told apart at 65,536, never the reverse.

**The kind** (`observability/catalogue.kind`) is a one-word summary of the same curves (made, ring, small_world,
frozen, still, rewired, moved, broken, apart, empty, full, grown): a first sort, too coarse for a zone's edge. G37, in
focus on 177, reads "made" on one of its own three seeds and "moved" on all six of its seeds' campaign; two of its
ring at 0.1 read "made". **The score is not a zone's measure either**: G37 scores 27 on its seeds, and its two
neighbours at 1e-9, the same physics on new random streams, score 7. The kind held there; the score did not.

## Zones over N

A zone is stated with the size it holds to: "Z1 at N = 16,384". Over N a zone can only split, as curves lock in; the
central law's run to the largest N is where the zone's finest description is read. **A law can be in more than one
zone** in two ways: nested (in Z1 at 4,096 and in one of Z1's parts at 65,536), and on a boundary, where its curves
sit inside the margins of two zones at once: a boundary law, marked as such, not forced into either. Where the
boundary itself lies, and what grows there, is a later question (the operator, 19:21).

## Shapes: what the probes can tell apart, and what they cannot

* **A circle from a torus**: told apart. A ring reads d near 1 and its reach grows as N; a two dimensional torus reads
  d near 2, its reach as N^(1/2) (the phenotype's known answers: the ring as N, the square and triangular lattices as
  N^(1/2)).
* **Growth**: a power of N is a geometry; log N is a small world, an expander or a tree; d_w tells normal diffusion
  (2) from a fractal's or a tree's.
* **A torus from a plane patch or a sphere**: not told apart today. All three read d near 2 and reach as N^(1/2); they
  differ in topology, the cycles that wrap around and the boundary, which no probe reads. A topology probe would be
  a new appended group (the ledger, 855): for instance the number of independent cycles a graph keeps that its
  triangles and squares do not fill, as N grows (two for a torus, none for a sphere or a disc), its known answers
  committed first on the calibration table's tori and open patches.

## How a zone is mapped (the operator's order)

1. **Study 178, clean**: the blind draw as the base load, run only when nothing else has work (885's order).
2. **A dex read in becomes its own campaign**: every law run again on its seeds and each chain checked like for like
   against the dex's (`dex.verify`); each law confirmed or denied, listed in the Top 100 as it reads, opened like any
   law of the folder.
3. **One zone at a time, the one most likely to confirm fast** (19:49: "not the most special/unique one but the one
   most likely to confirm fast"): the verified group with the most laws of one term set nearest one centre. In the dex
   of 15:11Z that is G79 and its 47 neighbours; controls are never chosen.
4. **Its edges, as efficiently as possible, over every parameter and N**: judge the laws already there first, with
   no new run; then, per parameter, step out both ways, doubling until the behaviour changes, and halve the gap three
   times; each point judged at 4,096, and only the two points either side of an edge run to 16,384. N by the central
   law, made from the middle of the points read alike, run, and pushed to half the host's memory.
5. **Benchmarked, before anything is automated over several zones**: for every edge, its runs, core-hours and hours;
   how often the call at 4,096 matched 16,384; the zone's ranges and its N. Each zone may behave differently; they are
   learned one by one (19:49). G79's 47 neighbours already in the dex are the ring method's run on the same law, so
   the step-and-halve search is compared against it at no extra cost.
