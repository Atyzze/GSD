# GSD roadmap

What is open, in order; how builds are paced; and the constraints every build keeps. What the data settled is
`docs/RESEARCH_METHOD.md`; the operator's standing decisions are `docs/HISTORY.md`, "The operator's standing decisions".

## The thread

**Three studies make the paper** (the operator, 2026-11-15 14:07: "a perfect 3 studies to describe in the paper which
will most effectively describe the purpose/usecases of our instrument"). **Study A** searches a big set of terms and
scaled couplings, blind, on eight starts, without the curvature term, its gates learning from its own laws alone, and
its interesting laws chosen from its data alone; it is run, then replicated. **Then the gates are closed**: the
confirmed gates carried from study to study, against a study run fresh, to see whether carrying them is worth the
compute it saves. **The curvature term is added** as a study of its own, to see what one term added to the mix does
(the operator, 13:52: keep it out of A, "keeping 1 term out and comparing what adding it to the mix does"; 2026-11-16
14:04 calls it study B): first a small study runs both the exact curvature and the formula the term uses today, which
reads +1/3 on every edge of the triangular torus where the exact one reads 0 (752), to show where they agree and where
they part; then one of them joins the draw pool and the null map with it is compared with A's, the first case of
what adding a term does. Any other new term comes after the paper (14:04: "which will be for after the paper with
studies A, B and C all finished first"): this is the consolidation, scoping down.

**Study A's size and when it starts** (the operator, 2026-11-16 10:50, 11:01 and 14:04). 100,000 laws in ten batches of
10,000 (2026-11-21 04:29, five of 20,000 before) on eight starts and three seeds: 2.4 million graphs at each size of the base block, close to 10 million over the
four, "a good point to stop with the easy story being no single machine can hold more than this". Up to a month on
the host is the limit, less is better. Before it: a handful more pilots until the gates behave; the same trial run
twice to the same numbers, then once on a fresh seed; and A starts once the gates, the code and the calibration offer
no more to gain. **The paper says in advance whether more compute on the same pool would add anything** (14:04: "or
perhaps the paper will conclude that not even a super computer running for a day/week would be able to add anything
meaningful to this data set, that is the standard i'd like to anticipate in advance"): how complete A's null map is,
as the chance that a further draw finds a kind of law A did not, with its criterion committed before A runs, so that
a larger machine is said to be better spent on new terms than on more draws from the same pool, or not, and why.
Each design names its own search seeds, so a study draws a new pool unless its design repeats one, and a design run again on the same build draws the same laws and grows the
same graphs. The random
perturbations of A's most interesting laws (once study B) come after. The published models are reproduced beside
them. **No data from a study before 169** (the operator, 2026-11-15 14:07: "I want all other legacy data OUT";
2026-11-18 16:43: "ALL old data we want GONE"; the readings left in archives sent beside the builds that took them
out). **Pilots run on the host beside the builds** (2026-11-13 19:44 to 20:14): they steer, correct and verify the builds, and no law of one reaches the paper.
Each build's notes say in their first line whether it may be started for a pilot.

## Questions for the operator

Written here in plain words the turn a question is asked; it leaves when answered, the answer going to
`docs/HISTORY.md`, "The operator's standing decisions". Answered 2026-11-22 15:38: the next study's gates
(`nothing_read` from 16,384, `starts_apart_by_history` recording) and 16 workers, SMT decided against.

Open, for after study 174 (the operator, 2026-11-22 15:50):

* **Past 65,536?** No law has run above 65,536 for many studies; it saves compute, but some results may show only
  higher up. 174 says what 65,536 costs (the replay: 56% of the study) and what scores only there; the question is put
  with its reading.
* **A tenth or a hundredth let through?** Every acting gate lets a tenth through in 174 (15:55); its 10,000 laws say
  what each tenth cost and found, and so what a hundredth would save and lose, gate by gate and size by size.
* **The perturbation of the best laws**: answered 2026-11-23 11:21, study 175, designed in 847 (`docs/HISTORY.md`);
  theirs to start.
* **Put the score's candidate in force?**: answered 2026-11-23 15:45, in force at 848, the trees of long paths a known
  limit of both scores (`docs/HISTORY.md`).

Open, from 864 (2026-11-25 11:06):

* **Study 176's standing controls: keep them?** Recommended, keep them and take their card off Home: the five laws of
  known answer (`controls_criterion_2.json`) cost 3.1 core-hours of 174's 750 (0.4%) and are the only laws in a
  folder whose right answer is known, so they catch a build or a host that reads wrong; the map cannot, since a map
  read by a wrong instrument agrees with itself. The map is the control of the search (a blind law inside a known
  region predicts its kind), the controls the control of the instrument. Cost of dropping them: nothing that checks
  the instrument inside a study's own folder and bundle.
* **When 176 starts**: answered, the operator started it on 867 at about 15:00, as designed (`docs/HISTORY.md`); a
  gate change learned from 174 would be study 177.
* **A law's code**: answered 16:34, SnCnGn, the study, the campaign and the graph, its fingerprint underneath (not
  the build: a build can change nothing a law does, a study is one folder across builds).
* **The split** (16:12: "why should I not set the distribution 10-1?"): recommended, 90% focus on the slider; the blind
  draw keeps finding new types beside it, and a group with nothing queued leaves its slots to the others.

Open, from 871 (`docs/build_notes/BUILD871_NOTES.md`):

* **A let-go law's own runs**: decided 2026-11-25 23:25, let them run (the recommendation); a tick takes them back.
* **871's to 873's pull requests**: the session that made them was refused push access to `github.com/Atyzze/GSD`.
  1. Open them from the archives yourself (a branch a build, each on the one before). 2. Give the next session push
  access, and it opens them.

Answered 2026-11-24 10:22 (`docs/HISTORY.md`): study 175 runs to its end; the study after it looks for laws whose
different starts arrive at the same d and mean degree; a lattice that does not change scores lowest; every behaviour
seen goes into a catalogue, with how to spot it early and how it scores.

Open, from 856 (`docs/build_notes/BUILD856_NOTES.md`), none blocking study 176:

* **How far a map variant moves a coupling**: a tenth in 176; 175's smallest real radius was 0.001. Recommended: a
  tenth until the first regions are known and say whether a tenth changes a kind.
* **How many halvings a line gets**: four, a boundary within a sixteenth of its line; a fifth costs one point a line.
* **Which CPUs the system keeps**: none until named (`main.py workload --system-cpus`).
* **Home's refresh every 0.5 s instead of 4, and a control for it on the System page behind the admin link** (18:26):
  held back, since with every hardware thread simulating the API is what waits, and a faster refresh asks more of it
  (`docs/build_notes/BUILD856_NOTES.md`). Recommended: keep one core's two threads for the system first and read the
  header's API round trip; if it holds under a second, the refresh and its control are a small build.

Open, from 860 (`docs/build_notes/BUILD860_NOTES.md`), the first two before study 176 starts:

* **Study 176's first ten**: five of them (M02, M04, M08, M09, M10, `study_176_first_ten.json`) score 0 in the folder,
  their seeds having run to the sweeps' ceiling without stopping; the list was made by a reading that counts every
  seed. Recommended: choose the ten again by the folder's own score, from 174's and 175's newest bundles (175's newest
  is wanted), before 176 starts; the design is committed and not yet run, so this is a new design file.
* **The counts the pages and the paper's draft give** ("83 laws score, 54 of them 1", from 14:22Z): recommended, read
  again by the folder's score (the reader's build above) and restated, the old figure kept in the history beside why.
* **Group D's law**: answered 2026-11-25 07:33 and 07:47, the study's best laws one at a time and the top five's
  depth, made at 861 (the focus).
* **E8**: recommended, no study at a cap of 240 or 1,024: the probes refuse E8 at every size the host holds (860's
  notes); its cells appended to the table as refusals instead ("Unscheduled").

Open, from 861 (`docs/build_notes/BUILD861_NOTES.md`):

* **The gates of the next study** (07:33: "perhaps its also time to revisit the gates"; 860's reading of 174's bundle
  of 06:26Z): `starts_alike` at 16,384 is the costly one: 2 of the 23 it let through score 19, the top score, and
  of the 165 it holds, 53 are lines or rings, 12 read d 1.3 to 2.5 and 100 read nothing; the fact gates,
  `starts_alike` at 4,096 and `nothing_read` at 16,384 lost nothing a let-through found. Recommended for the next
  study: `starts_alike` at 16,384 to act only where the starts' shared end reads no dimension, the rest as in 174.
  Answered 2026-11-25 09:42, option 3 of four: the 65 that read something (the 53 lines or rings and the 12 at d 1.3
  to 2.5) run on in 174, about 300 core-hours, with a "run on" action the decisions respect (863); the next study's
  gates are set on what they show.
* **Which law first**: recommended the folder's order (C1-G6940, then the other rings at 19, then C3-G7363 at 18);
  the Map page's "focus now" takes another at any time, 175's H12 (aba936bffa) the one to tell seeds from digits on.

Open, none waiting:

* **The noise floors** (offered with 805): the installed table's own floors are its cells' median errors, and its
  d_V floor is 4e-16, every seed of an exact lattice reading the same d_V, so no law's d_V step could fall inside
  twice it; the frozen floors of analysis 4.0.0 stay until then. Recommended: each law's own measured errors, as d_s's
  step tolerance is since 629, with a criterion committed first and judged on laws it was not set on.
* **The score's list** (made at 783, `docs/ARCHITECTURE.md`): what "settles" means for each probe (a relative step
  within a margin set on the table's exact lattices, judged on seeds it never saw), a line scoring as any other value,
  a kept lattice 0.3 and a lattice start that changed 0.6, the twins 1 (gsd-law-score-5); put to them with its list on
  the pilots' laws. Asked with it since 776 (the operator, 2026-11-14 10:33: "can it ever be any meaningful
  geometry if any of the probes doesnt return a value? does d_s alone by itself ever mean anything ... that einstein
  rule too right?"): whether a chain is a geometry at a size only where all four probes read and the Einstein relation
  d_s = 2 d_V / d_w holds, from 16,384, where the box and walk probes can read a small three- or four-dimensional
  lattice; the landscape's 5th band reads that relation since 783.
* **Exponential growth flagged in its own right** (offered after their question of 2026-11-11 10:48: "Are we 100%
  sure this wont prevent us from spotting exotic/interesting geometry though?"): a graph whose balls grow exponentially
  has no dimension and reads no probe, and a negatively curved geometry is among them; whether such a graph is flagged
  by a steady growth rate over N (kept since 761 in `volume_growth`) with local structure a random graph lacks (the
  growth class, below). Not asked for; theirs to say.

## Planned builds, in order

**From 870** (the handover, 2026-11-25 16:05; the operator's words of the day in `docs/HISTORY.md` and in
`docs/build_notes/BUILD870_NOTES.md`), each its own build, in this order; a planned build takes its number when it is
made. The blocks after this one are the plans as they were made, kept for their reasons.

1. **871, made** (`docs/build_notes/BUILD871_NOTES.md`): the seeded laws in the focus on their bundle's score, a
   bundle read twice refused, the seeds as a selection, every law named SnCnGn, the Map page's line, the ladder's header.
2. **872, made** (`docs/build_notes/BUILD872_NOTES.md`): Home's study bar in core-hours and memory held, four parts;
   "Which laws" leading; the fleet ladder in two, the selection's checked against a bundle's tables law by law.
3. **873, made** (`docs/build_notes/BUILD873_NOTES.md`): the depth seeker's ladder open to 4,194,304, each size priced
   from the law's own peak memory and bought only where it fits; a seed's save packed to fit the stop's grace.
4. **The neighbours read at a law's earliest identification** (13:11), once 866's early call says the early size
   agrees with 16,384 often enough; the rule is the operator's to choose on that reading.
5. **The pages' and reports' build numbers in words** (10:00; item 5's "866" below).
6. **The engines' diet: Rust, then C, then x86-64 assembly** (08:35, 09:42, 11:10; item 6 below), each proven by
   replaying 176's seeds to the bit and timed on the same seeds, so each engine is compared by how fast it moves
   through the same search.
7. **The lexicon and every law against every known type** (12:03; item 5's text below), then **the phenotype as the
   shortest description of a law's sixteen charts**, the null map complete, and new terms, the Ricci curvature in its
   two forms first (12:12).
8. **Study 177, on the gates 174 and 176 teach** (a reading of their two ledgers: the clean gates confirmed, the two
   leaking at 4,096 read again), seeded from 176's last bundle.
9. **The outliers' queue** (08:04; item 4 below), if the focus's lists have not taken it in by then.
10. **The shared effort** (11:08, 11:10): an invitation to run one's own node and add one's own terms, once one node
    has proven the zone mapping and the engines are timed.

**After 859** (the operator, 2026-11-24 17:51 to 18:32 and 2026-11-25 00:25 to 00:47, `docs/HISTORY.md`), each its
own build, in this order; a planned build takes its number when it is made:

**After 860** (the operator, 2026-11-25 07:33 to 09:02, `docs/HISTORY.md`), each its own build, in this order:

1. **861, made**: the focus (`docs/build_notes/BUILD861_NOTES.md`): the study's best laws one at a time inside its own
   folder and beside its blind draw (groups N and D, nothing to switch), each law's rings from 1e-9 to 0.4, its seeds
   read alone and three fresh ones (its seeds, its exact parameters, or robust), the top five to 262,144, confirmed,
   then rings outward or boundaries halved, a scoring law inside a mapped region passed over; the reports late, not
   offline, while a bundle is made; a reading one seed of three gave drawn faint (174's d_w outliers near 4 to 8.6);
   the science hash over the table's cells.
2. **862, made: the Map page and a GG number for every mapped region** (08:10 and 08:55;
   `docs/build_notes/BUILD862_NOTES.md`): the focus started, steered (the split, a law now, skip, put back, the next
   law's settings), stopped and started again from the page behind the admin link, and shown there: the law in focus
   and its rings filling in, its seeds and its sensitivity, the depth, the queue, the ended laws, and every mapped
   region as GG#n with each axis's range (a term a law lacks at 0), a region of the same kind that overlaps joining the
   lower number, regions of other kinds that overlap said to touch.
3. **863, made: the handover** (09:14 and 10:01; `docs/build_notes/BUILD863_NOTES.md`): what the context that made
   860 to 862 read and what the operator decided, so a fresh context starts from the repository alone.
   **864, made: the held laws run on, the law page as a 4x4 grid, no law done** (09:42, 09:53, 10:03, 11:06;
   `docs/build_notes/BUILD864_NOTES.md`): the run-on list committed first with its rule (40 of the 193 `starts_alike`
   holds at 16,384 in 174's bundle of 09:59Z read something, all lines or rings, not 65), the Map page's "run them on"
   the decisions respect, outside the gates' counts; the law page's 16 charts, one size, in two styles; every page's
   status "waiting to be extended" or "settled at N=..." by what. Their reading when they end, against the 23 let
   through at random, sets 176's `starts_alike`. **The pages' build numbers in words** (10:00) moved after 865.
4. **The outliers' queue** (08:04: "any outlier should automatically be added to the list of potential zones to
   investigate its area"; 08:07: "But only if all the top scorers are already done being mapped"): once every scoring
   law is mapped or inside a mapped region, the focus takes the study's outliers, strongest first: a probe's reading
   far outside its bulk (a criterion committed first; in 174, d_w over about 3.5 and d_V over about 3, where 99% read
   under 2.87 and 2.24), its own seeds and tiny rings telling a lucky strike (one seed, not repeated) from a region
   (its neighbours repeat it), a new region given the next GG number and a later outlier inside it joining it.
5. **865, made: study 176 designed again, seeded from the map so far, Home's top one bar** (09:42, 11:06;
   `docs/build_notes/BUILD865_NOTES.md`): A's ten blind batches on 176's seeds, the focus begun by the study's start,
   an empty seeded campaign the Map page's "seed from a bundle" fills from any bundle of the same science (its scoring
   laws run again, its GG regions joined with their numbers, a newer bundle of the same study widening its regions);
   "The study now" one bar, blind against zoned, the standing controls a tick. Its gates are 174's until the 40 run
   on say otherwise (the questions above).
   **866, made: one slider, two ordered lists, one depth worker, the earliest identification** (13:11;
   `docs/build_notes/BUILD866_NOTES.md`). **867, made: the law page read in one pass** (13:28, 13:34 and 14:11;
   `docs/build_notes/BUILD867_NOTES.md`): every plot answers the pointer, one table of every value plotted, the
   curves a row a size, the sections lettered and the plots numbered. **868, made: plain words behind every plot**
   (14:17 to 14:22; `docs/build_notes/BUILD868_NOTES.md`), a line between two readings naming both, a click pinning the
   card. **869, made: the import folder, the focus's settings folded, each running law's group** (15:08 to 15:18;
   `docs/build_notes/BUILD869_NOTES.md`); the focus's laws on Home. **870, made: the handover** (16:05). Then, as planned
   at 869, **Home's four boxes as one** (14:24, 14:29), 872 since 870: the fleet ladder, the landscape, the Top 100 and the filters
   drawn from one selection of the laws, the focus's laws in the ladder, every box following the filters so the
   statistics can be read per phenotype; a consolidation build, each box checked against the bundle's tables.
   **The depth seeker to the memory limit**, 873 since 870 (13:11: "always just 1 worker
   thread responsible for always pushing the memory limit to the system max (+ its free buffer zone ofc) but
   automatically testing how far N is feasible/safe to run without getting oom killed"): the depth campaign's ladder
   open past 262,144, its next size priced from the law's own peak growth (`memory.own_earlier_seed_bytes`) and bought
   only when it fits the host's reach less the free 10 GiB, else the law settled at its memory ceiling with the size it
   reached and the bytes the next would need; 1,048,576's save past the stop's grace (the focus plan's note) met
   first. Then the neighbours read at a law's earliest identification once 866's early call says it holds (the
   operator's choice on that reading).
   **Then, the lexicon and every law against every known type** (12:03: "all laws should instead carry multiple
   scores/probabilities vs all known phenotypes and how similar they are to the other phenotypes, a giant matrix 2d"):
   a law's name is its type (the catalogue's kind, how its starts end, and its form, what was grown: a ring, a line,
   d 2) and its GG region where it sits; a table of laws by known types, each cell how near the law reads to that
   type (its d, degree, largest piece, curvature and reach's growth, against the type's laws, in the units of the
   table's own spread), a law near none of them the sign of a new zone; Home's Top 100 and the filters read it, the
   single score kept for what the extender pushes deepest. Its known answers first: the table's families each read
   as their own type.
   **Then the phenotype as the shortest description of a law's sixteen charts** (12:12): each of the 4x4 law page's
   quantities over N, every start, fitted by the fewest forms that describe it (a constant, a power of N, a log), each
   weighted by how many probe readings it rests on, a law's phenotype the set of those forms and a new law read
   against the set already seen; a few dozen categories, overlapping, from them, judged first on the calibration
   table's families. With every term's load read (865's terms switched off), that is the null map complete; then new
   terms join the pool, the curvature first in its two forms, the exact one and today's formula, compared by outcome
   and by speed.
   **866, the pages' and reports' build numbers in words** (10:00): every citation of a build in what the pages and
   the reports say (863's notes: about 90 in the code, 27 in the pages) checked against today's code and said
   plainly, anything worth keeping folded into `docs/HISTORY.md`; a decision's reason keeps its words.
6. **867, the engine's diet, Rust first** (08:35: "can we not make our engines more memory efficient? Or would that sacrifice speed?"),
   profiled first (the profile in "Unscheduled"): by the code, a seed at 65,536 nodes and mean degree 29 holds every
   finished chain's edges as Python tuples (about 120 bytes an edge, eight chains, about 0.9 of the 1.46 GiB
   C1-G6940's seed peaked at) and saves them as JSON (19 s); the Rust graph holds about 40 to 150 bytes an edge (both
   adjacency lists, an edge list, a hash index of edges, and per-term caches as hash maps). Finished chains as packed
   int32 arrays saved in binary (about 15 times less there, the save under a second, which clears 1,048,576's stop
   grace), the caches as flat arrays by edge slot (fewer bytes and no hashing), and edges sampled through the degree
   tree the engine already keeps: about 25 bytes an edge, a seed about 20 times smaller, no slower. The floor for that
   graph is about 4 MB a chain in 17-bit indices; below about 16 bytes an edge costs speed. Every chain the same to
   the bit before and after (`tools/outputs_of_a_law.py`), both engines. Proven on 176 itself (09:42: "replay the
   seeds, results should remain identical, but simply grown faster with less memory"): its seeds run again from
   scratch on the new engine, every chain and reading the same to the bit (`tools/two_runs.py`), the time and memory
   each took compared; D's ceiling then rises by itself as memory admission allows.
7. **The study after 174, its gates revisited and seeded from 174** (865 made the seed and 176; the gates wait on the 40) (07:33: "when we modify that, then its also time
   for a new study, but we can still seed it with the best-scorers and more specifically their phenotype map of
   behaviors so that we dont lose that and already have regions to start probing/mapping straight away"): the gates
   chosen on the question above, the study started from 174's last bundle whose science hash is the folder's (what
   was planned for 861 below, item 2): its laws taken whole, its focus's regions and GG numbers known from the start,
   the best laws not yet mapped queued for the focus.

**After 859** (the operator, 2026-11-24 17:51 to 18:32 and 2026-11-25 00:25 to 00:47), as planned then; items 2 and 6
are taken up above:

1. **860, made**: Home says what is true (`docs/build_notes/BUILD860_NOTES.md`): the orange banner only when the
   refreshes fall behind (00:25: "I'm still seeing that too often"), the frozen and still lattices back on the
   landscape (00:40), the Top 100 in one order (00:45), every law of a bundle whole (00:40: "generalize it so we can
   bootstrap new studies with that seed-data set").
2. **A study seeded from an earlier bundle** (now items 5 and 7 above), the bundle a seed set others can join from: any bundle whose
   science hash (`study.json`, `science`) is the folder's, its laws taken whole, its map's regions and known kinds
   loaded, so B starts where the last one stopped and A's grid can lean toward the regions least explored (the lean
   drawn and recorded, never chosen by hand) (`docs/agent/NEXT_BUILD.md`).
3. **The reader that scores as the folder does**: `tools/catalogue_reading.py` and `tools/score_list.py` read each
   law's `law_score` from the bundle (since 860) and say where they cannot (an older bundle: report 28 to carry each
   chain's counted seeds); the counts in the handoff, `docs/readings/findings.json`, `docs/RESEARCH_METHOD.md` and the
   paper's draft read again by it (the folder scores 46 laws on 174's bundle of 23:19Z, the reader 122); study 176's
   first ten chosen again by it, on the operator's word (questions below).
4. **The fleet ladder under the filters** (00:45: "none of the data in the fleet ladder table seems to actually update
   the filter"; 857 was asked for it at 17:51): the server sums the ladder again over the laws the filters keep, kinds,
   groups and batches, on request and cached by the filters, each rung's laws, graphs, stops, times, budgets, memory
   and each probe's time; the live counts (running, queued) stay the fleet's. About a build; the probes' times by
   region come with it.
5. **The map's term axis** (00:25: "exploring the parameter zones and overlaps automatically between term presence
   and their couple-strength"): 176's map moves each coupling alone and halves a line toward a law of the same terms.
   Then each holder's terms switched off one at a time, a line toward its coupling at zero halved where the kind flips,
   and each term it lacks switched on at a small coupling, both sides of zero; two regions that meet are joined, their
   boundary recorded once. About a region's cost again (16 to 30 more laws a holder, by its terms); the split with A
   stays half and half.
6. **Group D** (2026-11-24 18:06; 00:27: "our auto extender to seek out the memory boundary for our current top
   scoring candidate"; to 262,144 at 861, the rest here): one core takes the study's best law up the ladder past 65,536 until memory admission refuses
   the next size, the size it stops at recorded in the bundle as the host's limit. From 174's bundle: C1-G6940's seed
   peaked at 1.46 GiB at 65,536 (its random and lattice starts at mean degree 29; 266 MiB at 16,384), so about 7 GiB
   at 262,144, 30 to 45 GiB at 1,048,576 and 150 GiB or more at 4,194,304 against the single job's ceiling of 60% of
   the host's 92 GiB: the boundary is expected at 1,048,576. Before it: the ladder past 1,048,576, the seed's save at
   depth (19 s at 65,536 and mean degree 32, growing with N), and the fixed points of what reads the fleet's state
   above 65,536 ("Unscheduled", below).
7. **Then the consolidation**: every study before the baseline out of the tree into
   `GSD_readings_archive_<N>.tar.zst`, `<N>` its own build's, sent beside the release (`docs/agent/NEXT_BUILD.md`);
   and the notes of 823 to 845 folded into `docs/HISTORY.md`'s eras.

8. **After the paper**: the atlas shared, peers in a browser or a container contributing runs checked against one
   science hash and calibration table; a front end to watch it grow; a formal check in Lean of the countability of
   the phases (`docs/paper/GSD_PAPER.md`, musings); the engine contract (`engine/boundary.py`, the parity suite and
   the Boltzmann known answers) opened to engines in C or assembly, each admitted only by the same parity and known
   answers, and its work count read as a benchmark of a device's graph-simulation throughput, logical cores beside
   physical ones (2026-11-24 18:12); a peer joins by measuring a sample of the calibration table again and matching it
   within its cells' bands, as `tools/adopt_calibration.py --sample` does for a folder now (18:14), and its CPU model
   and timings go beside its runs, so a device that reads slower or otherwise than its model's peers is seen (18:19),
   only when that peer opts in, as a data submission of its own, never by default (18:28); from those, a table of
   devices by their throughput, a high score among peers (18:32).
   **A language with directed edges** (18:19): the DSL's edges are undirected and its vertices identical; a second
   edge kind (directed, standing for charge) would be a new language with its own known answers, judged before any
   reading of it is offered as physics. Whether such laws grow long strands of a few repeating units (18:20) is a
   question for that language, not one the present data bear on.

**After study 172** (the operator, 2026-11-21 18:08: "I agree with all recommendations ... go ahead, start rebuilding
exactly with all your recommendations"; "I will probably just run the study bundle of the current study one last
time, and then just abort it and start the new study with the new gates and the new seeds"). 172's progress bundle was
read at 839 (`docs/build_notes/BUILD839_NOTES.md`); its last bundle is read beside those numbers by whichever build it
reaches. Every build says which outputs of a law move (`tools/outputs_of_a_law.py --against` the build before's
record), and nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` moves without saying
why.

1. **841, made** (`docs/build_notes/BUILD841_NOTES.md`): `nothing_read`'s piece at 0.9 of the graph; the ledger
   counting a priced law's verdicts; a longer chain on twice its size's budget; **the cut gate, recording only in 173**
   (the operator, 2026-11-21 21:03, "Record only", after 172's replay showed a stopping cut gate losing 7 of 22
   scoring laws); a design's own share held when a gate confirms; **a frozen lattice scores 1**; `priced` among the
   fleet table's stops; each chain's work and accepted moves in the bundle; study 173's design and criterion, its
   predictions from 172's replay (`tools/design_on_a_bundle.py`: about 150 core-hours, no scorer lost). The gates are
   efficiency against accuracy (18:08), so each is read by what it saves and which scoring laws it withholds, by law
   id.
2. **172's last bundle, the last check before 173 starts** (20:01): read at 22:05, nothing new for 173, which runs on
   841. **842, made while 173 runs** (22:57): the wait for earlier laws only where a gate still learns; the readers
   that held every decision read from disk; `tools/study_173_reading.py`, `tools/lattice_cost.py` and
   `tools/two_runs.py`. **Then 173 run again on 841 with 32 workers** (22:57), the same seed: replay and SMT's gain,
   read by `tools/two_runs.py`. Both runs read on 2026-11-22: the same but for four laws, none scoring (two failed on a
   memory bound guessed from the fleet, one gap read on a solve at its step limit in one run, one apart past 10^-8);
   the rerun held 23 slots, not 32, so its SMT figure is muddled (12:35). **843, made** (12:11 and 12:35):
   `--workers K` holds K; a seed stopped on a guessed memory bound runs again; no rule with its author and date in the
   code; the ledger and `tools/two_runs.py` read cleanly (`docs/build_notes/BUILD843_NOTES.md`). **Then 173 run again
   on 843 with `--workers 32`**, holding 32: read 2026-11-22, every decision replays, the same as the first run law by
   law but for the law 841 failed on memory; SMT makes a whole study like 173 about 1.12 times faster (1.28 at 64,
   1.06 at 65,536), the results the same (`docs/agent/NEXT_BUILD.md`).
3. **844, made: the stable build, carrying study 174** (2026-11-22 15:50 and 15:51; `docs/build_notes/BUILD844_NOTES.md`):
   the gates chosen at 15:38 and 10,000 laws in ten batches of 1,000, run for days on 16 workers, nothing else.
   **845, made**: Home's map of ten batches arrives (one landscape built at a time had gone to batches 1 and 2 for
   ever) and the ten batch buttons keep to one row (`docs/build_notes/BUILD845_NOTES.md`); it may be applied to 174's
   folder. **846, made** (2026-11-23 11:21 and 11:48; `docs/build_notes/BUILD846_NOTES.md`): the score's candidate
   (counted seeds, the connectivity floor, a step that holds its scale and whose next step does not break it), judged
   on known answers committed first; criterion 4 missed on strips that are lines (its own prediction wrong) and on a
   tree, criterion 5 written fresh missed only on trees of long paths, so the score in force stays as it was and the
   candidate was read beside it; every decision of 174 replays. With it the System
   page's worker count, changed while a study runs. **847, made: study 175, the perturbation side study** (11:21;
   `docs/build_notes/BUILD847_NOTES.md`): the 35 laws both scores settle in 174's first bundle, each run again and
   perturbed at random at four radii, from a change that moves only the random stream to a tenth, 595 laws, about 600
   core-hours, its region-or-point verdict committed first (`study_175_criterion.json`); and `tools/top_laws_alike.py`,
   which reads in 174 that the settled laws reward squares and run cold, with no shared recipe. **848, made**
   (2026-11-23 15:45; `docs/build_notes/BUILD848_NOTES.md`): 846's score in force, `gsd-law-score-8`. **849, made** (2026-11-24; `docs/build_notes/BUILD849_NOTES.md`): 175's
   second bundle read by a reader that keeps unread apart from unlike, kept or made beside each holder; the
   tree public, its papers out. **850, made** (2026-11-24 10:22 and
   10:43; `docs/build_notes/BUILD850_NOTES.md`): the catalogue of behaviours and its reader, every law placed with how
   early its kind was known; the still lattice scored lowest as a candidate, `still_lattice_criterion_1.json` committed
   first; no consolidation schedule. **Then 175's last reading** at its end (`tools/perturb_reading.py`,
   `tools/catalogue_reading.py`): the criterion judged on it or on 174's next bundle, whichever comes first, and if it
   passes the still lattice scores 1 in the score in force and stopping a law early by the still call is offered with
   its cost. **851, made** (2026-11-24 14:10): the home page on the
   README; the reach rule does not refuse a clean loop, which its known answers settle at full points, so the 8 laws
   that settle by value from the twins are not clean loops. **852, made**: the README the operator wrote on GitHub
   (14:26 to 14:32), taken into the tree. **853, made** (15:24): every start's admin link checked on a real
   fleet stopped three ways, a page holding an earlier run's link says so and greys its writes, and the 8 laws
   read again: open strings, loops with a few shortcuts, cliques strung into strands, no trees. **854, made** (16:30):
   the baseline of two bundles (16:34), the still criterion judged (it passes), the sampler's trap from empty measured,
   an outside review's points answered or placed, the paper drafted (`docs/paper/GSD_PAPER.md`). **856, made**: study
   176, 174 and 175 merged into one, groups A (blind) and B (the map of the ten best) half the fleet each (16:33,
   17:37, 17:39), the still lattice scored 1, the small-world kind, the system's CPUs, a science hash and the table in
   every bundle (18:04). **857 to 859, made**; **next**, the three planned builds above. **Then 174's reading** (a progress bundle while it runs, its last at the end): its criterion, P1 to P9,
   each batch beside the others, and what study A would take. 174's rules cost about 1.8 times 173's on the same
   laws (the replay carried to 10,000: about 1,270 core-hours against 720), study A about 33 days against 19 on 16
   workers, nearly all of it nothing_read letting laws on at 4,096 and the laws that then reach 65,536; 174 says what
   those laws find. If it holds, a last cleanup marks 844 the stable point and the data
   before it goes (15:50). Waiting until then, each to be agreed with the operator, in this order of their interest:
   the perturbation of the best laws (questions above); going past 65,536 (above); each scoring law's kind on the
   pages (`tools/pilot_reading.kind`; 18:08: "rings forming themselves is interesting enough to classify and predict
   as well"); what the six lattice starts read above 4,096 that the twin starts did not (19:52); probing straight
   after the evolve, measured before it is built (17:00). The trend read against the seeds' own spread (2026-11-20
   11:48) still has no reader: its rule is said before it is read.
4. **A control that grows from random, with every study** (19:52): the 2019 model (`tools/replication.py`, by its own
   rules, outside the fleet) run to 4,096, the paper's largest size, beside the standing controls, each of which only
   starts a chain at its answer; a criterion written fresh before its first run, saying what must show at the paper's
   sizes (the operator recalls the effect fading at larger N); its cost measured in the sandbox first. Until it
   passes, a study in which no law scores from empty or random (172: 0 of 2,500) cannot tell a search that finds none
   from one that cannot get there. A build of its own, before study A. **Measured at 854** (an outside review of
   2026-11-24 and 854's own run under the survey's policy, `docs/build_notes/BUILD854_NOTES.md`): P1, whose lowest
   energy is the square lattice, reaches 68% to 81% of the lattice's energy from empty, P2 70% to 83%, worse as N
   grows, where started on the lattice each stays within 0.4%. The review recommends this item before any more compute
   on laws from empty, and names the remedies cheapest first: parallel tempering, moves of a whole square or triangle,
   growth node by node; each changes the engine, so the Boltzmann known answers are read again after it. The
   operator's to order (`docs/agent/HANDOFF.md`, "What waits on the operator").
5. **A run's scaling with N, at two scalings** (19:52: "I agree, let's test that as well"): an experiment on 173's
   scoring laws and a sample of the rest, its rule said before it runs; 19 of 172's 22 scoring laws are a lattice that
   changed no edge or thinned, the effect of a run that is the same sweeps at every size ("Open questions", from 795).
6. **Pilots until the gates behave**, the same trial twice to the same numbers and once on a fresh seed; **a small
   test of perturbing the best laws** before 100,000 are drawn (18:08: "it might be interesting to do a small test of
   that before we commit to 100,000 laws"). **Study A inside a month** (18:08: "I don't want to wait for more than a
   month on the data set ... it's the upper limit, and ideally we can get it even lower"): replaying 172's decisions
   (`tools/design_on_a_bundle.py`) and carrying them to 100,000 laws, 172's rules are about 30,000 core-hours (78 days
   with 16 workers busy), 173's about 6,600 (17 days; 21 at 172's pace of 13 workers busy), and the six gates closed
   about 5,500 (14); 173's bundle measures the cost a law, its rerun on 32 workers what SMT adds.
7. **Stable, then study A** (below; the planted faults and the rest left out of 844, the stable build, until 174 has
   run: the operator, 2026-11-22 15:51): stable right before study A's trial, on the code the trial runs (the operator,
   2026-11-21 16:11: "this is for much later on the roadmap"; 838 had read 04:29's "3 is only at the very very last"
   as the last of the builds that wait on no data, and started it unasked). Its tools are in the tree since 838:
   `tests/fixtures/numbers_and_checks.json` (each number the paper states, the code it passes through, its checks),
   `tools/planted_faults.py` with `tests/fixtures/planted_faults.json` (35 faults, one at a time, the tests that fail on
   any edit set aside) and `tools/study_twice.py` (a short study in two folders, its bundles compared). Run in part at
   838: 7 faults no test caught were each given one, and the short study gave the same bundle twice
   (`docs/build_notes/BUILD838_NOTES.md`); the whole run is made again here. `decisions/gates.CONFIRM_AFTER` is read
   by nothing (the default is `Policy.confirm_after`): it goes with the next change to `decisions/`. Then study A's
   trial (5 x 1,000) and its full run (10 x 10,000, 100,000 laws, up to a month on the host; the operator, 04:29) on
   eight starts without the curvature term, then replicated.
8. **The gates closed and carried** from study to study, against a study run fresh; **the curvature term as a study
   of its own**, after a small study of the exact curvature beside the formula (below).
9. **After the paper's three studies** (the operator, 2026-11-19 22:05: "for after we're doing with our A, B and C
   study"): the 2019 model run again by its own procedure (`tools/replication.py`), on the final probes and with the
   budget, against a criterion written fresh before its first run (its earlier readings and criteria left at 829, the
   operator, 2026-11-20 11:48: "we weren't using the budget yet, we also weren't using a modern probes yet"): a sandbox
   measurement to its paper's sizes, and its two dimensions to 1,048,576 on the host; the authors asked with the paper
   near finished (2026-11-08 21:57). Then the paper, and what comes after it (the last item below).
10. **The table that only grows, and the reference set of four** (the operator, 2026-11-24 19:10 and 19:15; 855
   made the ledger and the first appended probe group): the quantum walk measured on the host and its known answers
   committed, the suite filing into the ledger, readings pinning their snapshot, the four probes split into groups of
   their own, attestations from other hosts; then the engine's conformance vectors, a registry of implementations by
   their hash, and the C and x86-64 assembly engines beside Python and Rust, each admitted by the vectors it
   reproduces to the bit. Step by step, with the questions it waits on: `docs/agent/APPEND_ONLY_PLAN.md`. Paused at the
   operator's word (2026-11-24 19:43) after 858, until they say go on.

**What each of those holds**, open:

* **Past 65,536** (2026-11-14 10:33: "1M can wait for now"; 2026-11-18 19:15): study 169's ladder ends at 65,536, and
  262,144 and 1,048,576 for study A are set from the pilots' timings (169 to 171), measured. What reads the fleet's state above
  65,536 is under "Unscheduled".
* **Stable, then study A** (the operator, 2026-11-10 19:38: "I want to reach a point where asking for (code) reviews
  doesnt surface anything anymore"; 19:54: "how should we go about making sure the list of actual defects is actually
  zero?"). Zero cannot be proved; "none found" is given a meaning the way the instrument's is, by planted faults: each
  number the paper states is traced to a check (a known answer, two implementations that agree, or a replay); faults
  are planted one at a time in the code a number passes through (the science freeze's files) and each one the gate
  lets by gets a check; a short study run twice, in two folders, gives the same bundle. Agreed 2026-11-11 04:50 and
  05:07: the operator's review in a fresh context is the gate before study A, and the planted faults and the study run
  twice are made before a build is called ready.
* **Study A's design**: a new design file on this tree's analysis, eight starts, the curvature term out of its pool
  (`terms_left_out`), drawn blind over its whole declared space, its gates learning from its own decisions, no rule
  named for a study; its criterion committed before its first draw. The trial has no predictions from an earlier study
  (the operator, 2026-11-13): what it is read for is committed before it runs (the pipeline end to end, each rate with
  its error, the score's list, the cost), and the full run's predictions are written from the trial, so that the full
  run tests them. What is stored of a chain is what runs it again (its law, size, seed, start and engine).
* **Study A, a trial round first** (the operator, 2026-11-11 11:22): batches of 1,000 laws as a trial of everything end
  to end; once it is read and checked, the full run from scratch at 10,000 a batch, 100,000 laws drawn (2026-11-16
  10:50; ten batches of 10,000 since 2026-11-21 04:29, "so that the work-sizes remain workable"). One design with the batch size as its one difference; the calibration table serves both; the full run's
  criterion committed after the trial is read and before the full run starts. Its cost on the host is read from the
  pilots' bundles. **The build that is ready for study A** says so in its notes' first line; the operator unpacks it in a
  new folder and starts it.
* **Study B's rule** waits (the operator, 2026-11-11 04:50: "study B doesn't need to be decided yet") and is committed
  as the last thing before A starts, so the choice is not made with A's results in view: which 100 laws are the most
  interesting and how each is perturbed (2026-11-08 20:47: "select the most interesting candidates and randomly perturb
  the values slightly to see whether or not theres a valley"). **Its design, after A is run**: starting laws chosen by
  that rule, no driven laws, prediction bands from the spread of the pilot's own batches, variants told apart by
  physical identity, random joint changes at three radii, each starting law run again on three fresh seed sets,
  matched controls, a valley-or-point verdict committed before any run, its cost in core-hours shown first. Open: how
  many reruns a law, whether a change may leave the declared space, the step sizes, which other laws start beside them.
* **The curvature, exact beside the formula, as a small study before the curvature study** (2026-11-16 14:04: "a
  separate small study that implements both the 'original' and the 'short cut' to show their results/behavior are the
  same, and then in study B add one of them to the draw-pool"). The term's formula reads +1/3 on every edge of the
  triangular torus, whose Ollivier curvature is 0 (752), and reads the triangular and face-centred cubic lattices as
  strongly positive for the same reason; the body-centred cubic and 4D lattices it cannot tell apart (757). The small
  study runs both side by side, edge by edge on the eight starts and on a sample of laws, its criterion committed
  first, and the study draws the one it chooses.
* **The growth class, a fifth reading** (2026-11-11 12:37 and 18:36, `docs/HISTORY.md`): kept, and guarded. Three
  things are recorded for every chain's last state: the balls' verdict and growth rate (since 761), the four-point
  thinness of the distances against the diameter (`research/known_structures.four_point_thinness`, 763), and the local
  structure a random graph lacks (the census of short cycles, the curvature). A class is called a finding only if a
  classifier passes a judged set of its own, its criterion committed first: hyperbolic tilings and hyperbolic
  geometric graphs classed hyperbolic-like; random regular and random graphs, recursive and uniform trees, trees with
  hubs and lattices with shortcuts not; the lattice starts a dimension. It must not move the table's key. Left for after
  the trial is read, on the operator's word; if it is not sound when study A is ready it is left out.
* **One error a probe.** d_s still gives two: `se`, a pointwise error a median of 11 times its seeds' spread, and
  `measured_se`, the honest one. Before it is made, every reader of a probe's `se` downstream is read
  (`scaleflow/flow.py`, `research/stability_score.py`, `decisions/`). It is made in the readers, outside the table's
  key: a cell keeps both errors since 766, so nothing is measured again for it. It changes what a study decides, so it
  is measured on the pilots' bundles first and made between studies, before the trial.
* **The score** (783, `observability/law_score.py`): judged again on the final probes with the old evidence, criterion
  first; its list read on a pilot's own laws, the top shown with why each law is there, then theirs to choose. A score
  that an exact lattice cannot pass at the ladder's sizes is not kept. It orders the deep lane and names study B's 100;
  it decides nothing else. A reading under 4,096 nodes is kept and not relied on (2026-11-12 11:14).
* **The starts' screen and the calculations**, after the trial is read and on the operator's word. *The screen*
  (2026-11-10 20:17: "how do we make a final decision as to what starts to consider?"): a start is admissible when its
  degree is under the cap, at least one term tells it from a random graph of its degree by an amount a node, and it can
  be built at the ladder's sizes; each candidate run as an extra start on a sample of the trial's laws at 1,024 nodes;
  it decides the kagome lattice. *Mathematics before compute* (18:22: "perhaps we can"), each written as predictions
  and checked against the trial's data with no new compute, criterion first: whether a lattice survives one move of the
  law at zero temperature; the coupling a geometry needs at a finite temperature; the degree-only terms as one family
  (`research/hamiltonian_preflight.effective_basis`, `research/degree_prediction.py`).
* **With the next schema, before study A's folder** (a schema change opens no running folder: `init_db` holds the
  folder to the schema's checksum): an index on `events(topic)` and a pruning rule for it and `resource_telemetry`; a
  partial index for the claim lock's scan of `analysis_queue`, which grows with the history, measured on a large queue
  first (moved here at 837); the tables nothing uses (`read_model_facts`, `read_model_state`, `resource_calibration_runs`)
  and `schema.sql`'s comments go; report 05 is parsed once at bundle time (report 23 has a reader since 836,
  `tools/study_172_reading.py`).
* **The paper**, on studies A and B run from scratch on one code base (2026-11-10 19:38 and 21:43), nothing from before
  them, until the operator calls it locked; one line says the instrument was developed through earlier pilot runs the
  paper does not use (2026-11-04). The 2019 model is reported as it reads when run again after the three studies
  (item 9). The authors are written to with the paper (2026-11-04 21:06). After study A,
  `docs/readings/findings.json`, `docs/RESEARCH_METHOD.md` and `docs/WHERE_WE_ARE.md` hold only what the instrument
  reads on known answers, what the published models gave and what study A found.
* **After the paper is locked**: the engines' benchmark (2026-11-13 18:47), every registered engine driven over a
  fixed set of laws and timed, the same bits on each, with a pure C engine and an assembly engine beside Python and
  Rust; the gauge field (a sandbox screen with and without it, its prediction committed first, then a study); new moves
  and terms for geometry, each through an "add your term" kit and a screen; a finding from them is reported against the
  null map of the paper's studies, never instead of it. A campaign beyond 10,000 laws needs its reports built in
  streams. The engines' comments go with their next change.

### What still carries the past

The cleanup the operator asked for (2026-11-18 16:43: "ALL old data we want GONE"; 2026-11-20 03:09: "all references
to studies/data older than 169 out") ended at 829. What carries the past now is this history, the build notes, the
archive pointers (`docs/agent/NEXT_BUILD.md`, "Known blockers") and these rows, each for a build that may touch code:

| Area | What it keeps alive | Where | What to do |
| --- | --- | --- | --- |
| Calibration remnants | `noise_floors_analysis-4.0.0.json` (used for every table since 4.0.0, and through the control-family match a deep decision's lane) | `research/noise_floors.py`, `graph_scale_dynamics/resources/readings/` | The frozen floors stay until the floors are each law's own errors (asked with 805: the installed table's own d_V floor is 4e-16). Kept, read at 802: `calibration/baselines/276-certified.json`, the cost check's reference (`tools/baseline.py`), and `probe_windows.json`, current (measured again at 805, unmoved). |

**Searches that find the rest:** `gesd` (none left in the code or the readings since 829), `RETIRED`, `LEGACY`, `ACCEPTED_`,
`OLD_`, constants named `*_FROM = 6..` or `7..`, `before 7` and `since 7` in code and tests, `study_16`, `studies 16`,
`159`, and the build numbers inside test names and fixture names. **Not ours, so it stays**: the code that measures known
answers, which is run again rather than deleted.

Whichever build a bundle of the operator's reaches reads it first. **A pilot's bundle** is read against its design's
criterion with the readers `docs/OPERATIONS.md`, "The pilots", names; its reading opens that build's notes and goes
nowhere else, and the folder is then theirs to delete.

### The pilots beside the builds

Studies 169 to 172 are the pilots; none before 169 is kept (the operator, 2026-11-18 16:45: no pilot on probes
about to change; 2026-11-20 14:20: "this is our baseline"). **The rules** (2026-11-13 19:58): a
pilot's folder stays on the build that started it and is deleted once read; what it is read for is committed before it
runs and no law of it is a finding; no build waits for a pilot or is made for one beyond a design file, and a
difference nobody declared is fixed first in the next build; a run answers something a coming build needs. Their part
a build: a new folder, one command, one bundle. Since 806 no clock ends a seed, so a study run twice gives the same
bundle on any machine. Each build's notes say in their first line whether it may be started for a pilot.

## Unscheduled

* **A shared mapping effort, once one node has proven it** (the operator, 2026-11-25 11:08 and 11:10): when the zone
  mapping is confirmed on the host and only needs more compute, a node's bundle seeds another's study (865's seed is
  that path already, append-only, by science hash), its regions with their laws, ranges and the law sets that sustain
  them shared; the paper's invitation is to run a node and add terms to the collective map. Before it, the engines in
  order, each proven by replaying a study's seeds to the bit and timed on the same seeds through the same search:
  Rust to the limit of the language (the engine's diet, planned), then C, then x86-64 assembly
  (`docs/agent/APPEND_ONLY_PLAN.md`, the reference set of four).

* **Is the Rust engine as lean as it can be, in memory and in speed?** (the operator, 2026-11-24 18:28): not
  measured. A profile at 65,536 nodes, the bytes a node and an edge and the moves a second against a plain adjacency
  list of the same graph, says what is left; it comes before group D, whose depth memory sets.
* **The square lattice's hysteresis, a phase transition the instrument can report now** (2026-11-24): P1 holds its
  torus and stalls near 80% of its energy from empty (854's table). Run P1 with beta swept up from empty and down
  from the torus at 256 to 4,096, the energy a node and the induced squares at each beta: two branches that meet
  only at the ends are a first-order crystallisation, measured, and the loop's width at each N says how the trap
  grows.
* **The quantum walk beside a law's reading**, once its known answers are committed (`docs/agent/APPEND_ONLY_PLAN.md`,
  L2): on a chain's final graph, as the four probes are read, so a state that diffuses but holds a wave is named.
* **A release path for pages and appended files** (the operator, 2026-11-24 19:56: "that fast lane path for docs only
  updates shouldnt take that long"): `package_release.py --fast` taking a build whose only changes are pages, readings
  and files that no frozen source imports, without the PostgreSQL lane; today any change under
  `graph_scale_dynamics/calibration/` or a frozen source takes the full lane, about 22 minutes on two cores.

* **Can the probes see eight dimensions?** (the operator, 2026-11-24 19:49, and 2026-11-25 00:25: "is there enough data
  provided in their paper to reproduce their claims?"): read at 860 on this tree's probes. The 8D cubic torus at
  65,536 nodes reads d_V 5.07 and d_s 6.7 and refuses d_B and d_w; E8's torus at 256, 6,561 and 65,536 nodes refuses
  all four, the whole graph within four steps. A scaling window at d 8 needs a side near 20, about 2.6 x 10^10 nodes.
  So E8 is appended to the table as a known refusal at the host's sizes (side 4 and 5), with the 8D cubic lattice
  beside it, under the append-only plan's rule (a criterion before its readings vote), and no study at a cap above
  32 is run for it. The paper itself has no reading the instrument makes: its one number reproduces by arithmetic.

* **Calling a lattice left alone before it runs** (850): the early call from a chain's own moves catches a quarter to two
  thirds of the still lattices at 1,024 or 4,096; whether any single move of the law pays at the perfect lattice could
  call them before any chain runs, starting from `tools/neutral_moves_check.py`.
* **A law stopped `empty` while its other starts are full** (849): when every start but the empty one stops at the
  mean degree cap of 32, the law's own reading falls to the empty start and the stop is named `empty`, as in three
  of H15's four 1e-9 twins in study 175. A truer name changes a decision's words, so it is the operator's to agree.
* **Distribution: every folder its own seed** (the operator, 2026-11-21 23:21: "if 1,000 people run it, that 1,000 different starting seats have been tried out ... for later"): a run without `--study`, or of a design with no `search_seeds`, draws its own seed already; what is left is study A's design for others to run without fixed seeds, each bundle carrying its seeds so the runs pool and any one can be run again.

Each is fixed or closed before study A's trial, in builds held to move no output a running study runs; 814 sorted
them.

**Touches what a study decides, records or replays** (measured on the pilots' bundles first, each fix named in the
notes):

* Where repeats_a_known_result or a gate can still change a law's share or signature at a size, the law waits, as
  before 834, for every earlier law to be past that size: a gate with `confirm_after` let-through laws there, or
  `known_result_after` laws sharing a signature. The narrower wait is for the laws let through by that gate, or sharing
  the law's own signature, alone; measured on 170's bundle (where the gate acted, as seen_enough) before a gated study
  runs, once there is more data to measure it on (the operator, 2026-11-21 02:32: "wait with this until we have
  more/better data"). In 172 a fact gate may confirm in 2,500 laws, so its laws may wait there; since 834 a waiting law
  gives up its place.
* **repeats_a_known_result tuned after the other gates** (the operator, 2026-11-21 02:32: "A gate we definitely want to
  keep, but not enabled at this time"): until then it records only and marks no law, and the laws that reach the same
  result are found by the signature every decision from 4,096 carries, in the study's tables; 172's criterion reports
  them so.

* The fate of a lattice chain whose mean degree is more than a tenth from its start's reads the reach alone below a
  kept of 0.8, so a random graph of half the fcc start's degree reads `partly` at 1,024 (819's K1, K10, K11): read on
  169's bundle how often a chain's fate is `partly` with its degree off by more than a tenth, by start and size, before
  `observability/starts_reading.lattice_fate` reads such a chain `melted`; then 819's criterion run again on the fix.
* **The let-through ledger leaves out the verdicts of a law stopped `over_budget`** (821; done at 841 as a design's
  `ledger_counts_priced`, on in study 173): `Ledger.feed` read `salted` only on `run_next` or `hold`, so 11 laws of
  169 that gates would have withheld were in no gate's count.
* **What a gate withholds that scores** (821, on 169's score's list; corrected at 825): all 10 of 169's drawn laws
  that score come through a lattice start and meet a gate read off the twin starts (at 256, 1,024 or 4,096); the
  ledger counts them held. (Its other three scorers are the standing controls.) Read on 170's
  let-through laws before any gate is confirmed for study A: what the withheld laws score a size later, by law id.

* The score names a standing control's given chain "given (random)" where it starts at the declared answer (825, on
  169's controls): report 28's entry for a control lacks its `given_family`; read on 170's bundle, fixed in the report.
* `complete_rung` records a decision and its core-seconds when no job is created (`decisions/depth.complete_budget`,
  `decisions/decider`): read on 169's decisions how often, before changing what a decision records.
* From the code review of 2026-10-20 (`GSD626_review_reports.md`, the operator's; not in the tree, so each is checked
  against today's code when it is taken up): memory kills classified the wrong way round
  (`observability/child_diagnostics.failure_class` reads a SIGKILL as `oom_killed`); report 28 and the law page reading
  the space score's stage differently; the worker reading a child's whole output into memory.
* What still reads the fleet's state when it decides, none of it acting where a ladder ends at 65,536, as 169's does
  (806 found them): a deep size's lane (`deep_lane_full`, `lane_resumed`, `lane_yielded`), `hold_released` when the
  queue is empty, the structure gate's audit and plateau follow under their in-flight counts, the gate's early stage on
  its five-minute cache. Each takes a fixed point of its own before a study deeper than 65,536 is run twice.
* The control-family match compares a law only at a size the calibration table holds a cell at exactly
  (`research/stability_score.control_family_match`), so the balanced binary tree (2^k - 1 nodes), the gaskets and the
  close-packed 4D lattices are never matched; a match withholds the law's points from the score, so a match at a
  nearby size changes the score, read on the pilots' laws first (moved here at 837).
* `REFUSED_COMPUTE_BUDGET`, which nothing has written since 782, is still a bucket (`scaleflow/probes.py`,
  `decisions/gates.REFUSAL_LIMITS`, the law page, two tests); taking it out moves every report's bucket counts.

**Touches nothing a study decides**: none left; 837 took the list (below, and closed). Its notes say which were fixed
and which were closed.

**Closed, with the reason**:

* **The budget is read only between chunks** (821 on 169, 99 seeds past it; 172, 127): made at 840, a stop inside the
  chunk in both engines at the same move, the seed ending on its last whole chunk; a stop waits 120 s for the save
  and a seed saves inside a long chunk (`docs/build_notes/BUILD840_NOTES.md`). Left open by it: the first chunk runs
  whole; a save is JSON of every chain's edges, 19 s at 65,536 at mean degree 32, and grows with N, so before a study
  deeper than 65,536 the state is written faster or the wait is scaled.

* Taken at 837 (`docs/build_notes/BUILD837_NOTES.md`): a seed whose worker commits reads `committing`; the release
  ships only what git tracks and names what it left; `tests/integration/test_operator_path.py` runs its fleet in a
  folder of its own; the Campaigns page divides the fleet all or nothing and answers a failure as what failed; a
  deletion checks its guard again under the maintenance lock; the disordered reader leaves a study's controls out;
  the last dashboard test that read the page's source as text runs its code; two timing assertions count work instead.
* Kept at 837, each with its reason: the three connectivity floors', `DEGRADED_WITH_N`'s and `audit_sample`'s names
  are recorded keys (a campaign's spec, a policy's fingerprint, every report's bucket counts), and
  `docs/DECISIONS.md` says what each means; the CPU tile's btop is the publisher's child and dies with it
  (`power_sidecar._die_with_parent`), and an orphan one is ended at every fleet start (`leftovers`, `orphan_tile`);
  a re-made folder's old PostgreSQL is ended by `leftovers` (`replaced`), now held by a test; the staleness probe the
  2026-10-20 review named is not in today's code (the source fingerprint hashes every byte, the landscape counts
  inserts, updates and deletes).

* The d_s shape's errors are generous (`measurements/d_s_shape.py`) and the spectral gap is reproducible to its
  solver's tolerance, not to the bit: each touches a frozen file of the table's key or the start reading's
  fingerprint, so only on the operator's word; both stay as they are.
* The Rust engine on Python 3.14 waits for a PyO3 that builds it: outside the tree.
* Decisions of the starts' rule with two held lattices not replaying from their own row (the review of 2026-10-20):
  every decision of 169 and 170 replays from its own row (821, 827).
* The work unit weighs an energy evaluation alike at every degree (814): measured at 821 on 169's seeds, a unit at
  4,096 takes about twice the host's seconds at mean degree 16 and up as at 1 to 4; it decides nothing, the budget
  being in units, and the hours beside the units are an estimate.
* Readouts split by dynamics regime and by bands of each axis, budgets that scale with locality or swap share, causal
  structure as an axis: features, each offered when a study's data asks for it; the MEM BW tile after a suspend is
  parked by the operator.

## Open questions, gated on data

* How each reading of two chains' meeting scores; whether a rung's uncertainty should be the between-seed dispersion;
  seeds per rung at low N; geometry on budget-terminated envelopes; how large a budget (read on 169 at 821: 4,096 binds
  most; 171 runs four times 170's there); two consecutive certificate passes; does a seed at the multiplier's ceiling read
  what a certified one does.
* Is a hold a shape, read against its start's census and largest piece?
* Is the second number the cycles: beyond the degree, does d_s fall with the cycles a node sits in?
* Do the controls pass on the whole ladder (`tools/positive_control.py check <bundle>`), and what does each gate cost?
* The mean degree k (the operator, 2026-11-17 19:32): does a law under k 3 at a size ever score at a larger one, and
  what would a gate on k cost? Read on every pilot from 169.
* Rings (19:17): can they be parked before 4,096 from the energy (degrees alone, least degree 2) or from k, at what
  cost? Read on every pilot from 169. In 172 at its progress bundle 37 laws match the ring's calibration family and
  about 45 have a chain from empty or random reading d near 1 at mean degree near 2 in several pieces; none scores
  yet, a score needing a piece of 4,096 nodes at two sizes. They are classed and predicted, not parked (the operator,
  2026-11-21 18:08).
* Coefficients scaled by N (19:35, not strictly local): does a law with a coupling scaled by N ever score? Studies 169
  and 170 draw only laws free of N (the operator, 2026-11-18 01:04 and 10:17); asked again when a study draws such laws.
* What the sizes to 4,096 say (2026-11-18 00:12): a chain steady from 1,024 to 4,096, the kind of law, the starts
  alike at 1,024, the squares a node; read on 169's and 170's bundles before any gate moves.
* Additions draw from every pair of nodes and a run is the same number of sweeps at every size, so a law adds near
  a node a count of edges that does not grow with the graph (795): is that the dynamics the search wants at 65,536?
  The operator's to weigh; nothing changed.

## Standing constraints

Not to be re-litigated; a build that breaks one says why in its notes. The operator's own are `docs/HISTORY.md`,
"The operator's standing decisions"; these are the engineering rules every build keeps.

**Code and release**

* **A tree is self-contained**: what a new study starts from is in the archive
  (`tests/unit/test_a_tree_reads_nothing_outside_itself.py`).
* **A folder's scratch outlives a restart, and a superseded folder's does not.**
* **Nothing is kept in RAM without a ceiling and a place to overflow** (the scratch is half the host's RAM, moved to
  disk past 60%). A write that can fail belongs inside the `try` that gives the work back.
* **The Rust engine is the default, in the lane too.** `GSD_ENGINE=python` skips its cases only when set on purpose.
* **Only `tools/package_release.py` produces an archive.** If the gate will not run, fix what stops it.
* **No Python file over 100 KB and no function over ~400 lines.** The offenders are an allowlist that forbids silent
  growth: a build that grows one raises its bound and says why.
* **Every archive that leaves this machine bumps the build number**, its notes ending in `## Verification` with the
  token `GATE_RESULT`, which the release tool replaces with the full-lane line.
* **A projection between a producer and a report carries new fields by default** and names what it drops.
* **A concept that can grow is imported, never retyped**; a set of names is derived from its enum.
* **Every periodic interval is whole ticks of `domain/cadence.py`** (`tests/contract/test_one_tick.py`).

**Contracts and campaigns**

* **A recorded contract does not change without a reader for the old one** while a live database holds it.
* **A change a live campaign cannot satisfy is a bug in the build.** Silence never selects the dangerous configuration.
* **`schema.sql` has no in-place upgrade**: an edit strands every live database; prefer an existing table.
* **Depth is earned, and the operator sets how strictly.** Held laws are released only into an empty simulation queue.
* **Limits are population definitions, not tuning knobs.**

**Measurement and selection**

* **Three seeds a rung is a floor.**
* **Frozen and fingerprinted sources change deliberately**, re-anchored with evidence that no measured output moved.
* **The score is triage**: only rungs above the connectivity floor, and a usable top rung inside the tolerance.
* **A stop rule is not adopted until its loss is measured on the audit sample**, judged on what its predicate reads.

**Evidence, reports and tests**

* **A field is read from where it is written**; a report field is only as real as the SELECT that fills it.
* **A report that examined nothing must not look like one that found nothing.**
* **A measurement is not shipped until something has read it end to end on real data.**
* **Every dashboard render function ships with a smoke case that runs it with real rows**; a repository method with
  a case against a live database.
* **A guard protects the thing, not the thing next to it**, and a refusal names a recovery that exists.
* **A collector** runs from the project root with no required arguments, never writes to the database, records its
  failures inside its zip, samples on the four-second tick and prints the zip's path last.
* **Two environments only**: the research host and the agent sandbox (`docs/agent/TARGET_ENVIRONMENT.md`).

## Build cadence

Feature and fix builds change what the fleet does or shows. Consolidation builds change no behaviour: they fold the
notes of every build but the ten before them into a few lines of `docs/HISTORY.md`'s eras and keep their own notes
and those ten in `docs/build_notes/` (the operator, 2026-11-19 22:05; each build's notes stay in its own archive);
rewrite every standing document to say what is true now; check the documents against each other and the code; and
prune this roadmap. A feature or fix found on the way is recorded here.

Consolidation builds: when one is felt to be needed, on no schedule (the operator, 2026-11-24 10:22): when the notes
pile up or the standing documents drift, never in the middle of a fix a live folder waits for; the operator can call
one or skip one. A consolidation changes no behaviour and says so in its notes' Type line.

`tests/unit/test_build_cadence.py` reads the line above, holds that no line plans the next one, and holds a
consolidation to changing no behaviour.
