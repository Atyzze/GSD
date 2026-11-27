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

Open, from 864 (2026-11-25 11:06):

* **Study 176's standing controls: keep them?** Recommended, keep them and take their card off Home: the five laws of
  known answer (`controls_criterion_2.json`) cost 3.1 core-hours of 174's 750 (0.4%) and are the only laws in a
  folder whose right answer is known, so they catch a build or a host that reads wrong; the map cannot, since a map
  read by a wrong instrument agrees with itself. The map is the control of the search (a blind law inside a known
  region predicts its kind), the controls the control of the instrument. Cost of dropping them: nothing that checks
  the instrument inside a study's own folder and bundle.

Open, from 897 (2026-11-27), deciding build 899:

* **A pushed seed's hold.** The admission asks 1.35 times its prediction to start a seed and holds a running one at 1.5
  times its peak, sized for a law whose memory is unknown. A pushed law's seeds agree: G73's 14 seeds that ran through
  262,144 peaked within 4% of each other (1.47 to 1.53 GiB). Recommended: hold a pushed seed at 1.1 times the typical
  peak of its own whole runs at the size below grown to its size, and ask 1.1 times it to start. Gain at 1,048,576 with
  898: about 8 at once instead of about 6, the 8-seed rung in one pass (about 9 h) instead of two (about 18 h). Cost:
  less margin for a seed that outgrows its siblings; the host's 10 GiB floor and the hard stop at 60% of the host still
  hold. Other choice: keep the admission as it is for every law.
* **A bundle beside the N-push.** A quiet bundle pauses every campaign: each running seed saves and resumes, and in 178
  the bundle of 14:27Z stopped the 4 seeds of 1,048,576 minutes after the restart had. Recommended: a bundle leaves the
  N-push's seeds running, its report noting they shared the host (no clock decides a seed since 806, so only their
  wall-clock readings move). Cost: those seeds' times in that bundle read a few minutes of the report's CPU. Other
  choice: as now, every seed stopped for a bundle.

Open, from 886:

* **A topology probe** (886): the probes tell a circle from a torus (d 1 from d 2) but not a torus from a plane patch
  or a sphere; a new appended probe group would count the cycles a graph keeps that its triangles and squares do not
  fill, its known answers first. Recommended after the first zones, if a zone reads d near 2.

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
* **E8**: recommended, no study at a cap of 240 or 1,024: the probes refuse E8 at every size the host holds (860's
  notes); its cells appended to the table as refusals instead ("Unscheduled").

Open, from 861 (`docs/build_notes/BUILD861_NOTES.md`):

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

**Made, 885 to 891**, the zone map's road (`docs/agent/ZONE_MAP.md`; the operator's words in each build's notes and
in `docs/HISTORY.md`): 885 one order for runs and probes, zones named Z1, a lucky hit; 887 study 178, a dex read in as
its own campaign and verified first, the first zone chosen to confirm fast; 888 the dex read again to 4,096 law by
law from the start, "Working now" by law, a new dex on a find; 889 a law pushed to the N limit from its page and the
Top page; 890 the first zone searched by stepping and halving each parameter, a law alike by its locked-in curves, its
central law pushed, benchmarked against the ring method; 891 the zones one after another, the dex a list of zones
with their central laws, a zone read in not searched again, the lucky hits kept to revisit; 892 the push list holding
the host in the operator's order; 893 the fleet in one of three modes (the N-push, the zone search, the blind ladder),
the N-push its own ladder again from 64 on every worker with its break-points forecast, the law page reading every
campaign of its law; 894 a pushed law keeping its code on every page, each size drawn from the campaign with the most
seeds, the pages told of every change of the work (our own stack, the operator, 13:00); 895 the handover, the plans
before 886 moved to `docs/agent/ROADMAP_BEFORE_886.md`; 896 the N-push's probes given its slots, the sizes being read
said on the law page; 897 every seed the N-push buys read (a start cancelled 8 of G73's 16 at 262,144), its forecast
priced as the admission holds a seed with the rung under way said, the push stopped at N=1,048,576 unless a law is
pushed past it (the operator, 2026-11-27 15:47), the bundle carrying the N-push (`focus.json`'s `push_now`).

**Next, in order** (laid out for the operator with 897; each its own build):

1. **898: a resumed seed in a fresh seed's memory.** In 178 the two seeds of G73's 262,144 that were stopped and
   resumed peaked at 3.05 and 3.19 GiB, the 14 that ran through at 1.47 to 1.53; the 4 seeds running at 1,048,576 were
   all resumed (1 to 3 stops each, the restart for 896 and the bundle of 14:27Z) and sit at 9.0 to 9.4 GiB, where a
   fresh one should be near 6 (about 190 bytes an edge at 65,536 and 262,144). The child keeps the saved state it
   resumed from (`artifact_store/resume_state.py`, `scaleflow/one_shot.run_one_shot`'s `resume`) beside the engine's
   graph. Measured first in the sandbox (a seed of 65,536 run through, and stopped and resumed: both peaks, the chains
   identical to the bit), then the state let go once the engine holds it. The admission's ask falls with it (it grows
   from the doubled peak). Gain at 1,048,576: about 6 at once instead of 4; a restart or a bundle stops costing memory.
   It touches `scaleflow/`, named why; no engine change; `tools/outputs_of_a_law.py --against` unchanged. Then the
   unscheduled "Is the Rust engine as lean as it can be" profile, the bytes an edge against a plain adjacency list.
2. **899: the two questions below** ("A pushed seed's hold", "A bundle beside the N-push"), as the operator answers.
3. **A consolidation**: 39 builds since 858's; no behaviour changes; after the N-push's fixes, never in the middle of
   one.
4. **The zone map's road**, once the push list empties (G73 ends at 1,048,576, then G133): "Still open from 884 to
   896" below, the zone search's hours and idle slots read from 178's first mapped zone first.

**Still open from 884 to 896**, each its own build, the first two waiting on study 178's first zones:

1. **The search's hours** (890's benchmark): a line's steps follow one another, each a ladder to 4,096; since 893 the
   free slots run each line's two possible next points ahead (item 6), the one not needed left unread.
2. **A law taken by its score searched as a zone is** (884's "a smarter zone"): once the zones run out the focus goes
   back to the score and draws rings (861); the search would judge it the same way, its members the laws already read
   near it. Recommended once 178's benchmark is read.
3. **Each term set to 0 beside switched off** (884, law space's faces).
4. **Several sizes of a pushed law at once** (the operator, 09:19; 892's notes): since 893 the N-push buys its own
   rungs (`push_ladder.step`, outside the decision engine), the next once the size below has one finished run, and
   every slot not taken by the rung below runs the next. Open: starting a size before any run below it has finished,
   priced from the forecast alone, the price corrected as the size below reads. Since 897 the push stops at
   1,048,576, so this matters below it.
6. **The zone search's idle slots** (893; the operator, 11:37: "those free slots should be used to speed up the zoning
   mapping"): its lines run their two possible next points on the free slots since 893. Its members' readings and its
   edges at 16,384 could use them too, read from 178's next bundle.
5. **A topology probe** (886; "Questions for the operator"), if a zone reads d near 2.

**Still open from before 886** (the plans from 870 and 881 are in `docs/agent/ROADMAP_BEFORE_886.md`, moved there
unchanged by the handover of 895, each marked made where it was):

1. **The sampler's trap from empty** ("After study 172", item 4 there, measured at 854): whether a known law must grow its geometry from empty
   before more compute goes to blind laws from empty; parallel tempering the cheapest remedy, an engine change, its
   Boltzmann known answers read again after. The operator's to order.
2. **Bundles as parts of the map** ("From 881", item 5 there): made in part by the dex (882 to 891: a dex written,
   read in, verified, its zones carried); open: a study bundle itself exported and imported as a map part, several at
   once, and a bundle of another science read for its laws alone.
3. **The neighbours read at a law's earliest identification** ("From 870", item 4 there), the operator's rule to
   choose once an early size is shown to agree with 16,384 often enough; the zone search's judging at 4,096 (890) is
   the first such rule in use.

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
