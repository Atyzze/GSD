# Handoff: the state of GSD at build 848

What is true now, for a context that has just opened this archive. Each fact has one home; the last section says
where. **Think from the data, not from this page**: where the data and a document disagree, the data wins and the
document is fixed in the same build.

**Where things stand.** **Study 173 ran twice on 841**: the first run on 16 workers (2026-11-21 about 22:30 local
to 2026-11-22 09:43Z, 12.6 h, 2,500 laws decided, stopped near its end) and the rerun with `--workers 32` (stopped
after 1.35 h). Both bundles were read on 2026-11-22 (842's readers; 843's notes): every decision of the first run
replays; P11 misses (six scoring laws went on only by a judgment gate's tenth, `nothing_read` losing about 20), and
the operator is asked which gates the next study keeps (`docs/ROADMAP.md`, "Questions for the operator"). The two runs
are the same law by law but for four laws, none scoring: two failed on a memory bound guessed from the fleet, one
gap read on a Lanczos solve at its step limit in one run only, one apart past one part in 10^8. The rerun held 23
slots, not 32 (on 841 `--workers` only started the ramp, whose floor was one slot, and the ramp gives slots back
above 83% host CPU), so its SMT figure is muddled (the operator, 12:35). **843** (`docs/build_notes/BUILD843_NOTES.md`):
`--workers K` holds K slots; a seed or an analysis stopped on its guessed memory bound runs again with a larger grant;
no code, test or printed line names a rule's author and date; the ledger counts a budget stop as held only by a gate
that acts; `tools/two_runs.py` reads slots from the occupancy series and compares the hour each run reached the same
decisions. **173 ran again on 843 with `--workers 32`**, holding 32, and was read on 2026-11-22: every decision replays,
the same as the first run law by law but for the law 841 failed on memory; SMT makes a whole study about 1.12 times
faster. Gates and 16 workers decided at 15:38. **844 is the stable build** (15:50, 15:51;
`docs/build_notes/BUILD844_NOTES.md`): those gates and study 174, 10,000 laws in ten batches of 1,000 on new seeds, every
acting gate a tenth through, run for days on 16 workers; nothing else goes in until it has run. Study 174 started on 844 on 2026-11-22 about 17:00 local; Home never showed
its map of ten batches (one landscape built at a time went to batches 1 and 2 for ever), fixed in **845**
(`docs/build_notes/BUILD845_NOTES.md`), which changes no decision and may be applied to 174's folder. A new
conversation read 845 and 174's first bundle and found the score settling seeds still on their way, a piece of half
the graph and strips whose reach does not grow by the dimension read; **846** (`docs/build_notes/BUILD846_NOTES.md`)
judged a mended score on known answers committed first, twice: it is a candidate beside the score in force, not in
force, because trees of long paths still settle under it (the operator's decision now), and 846 adds the System page's
worker count. **847** (`docs/build_notes/BUILD847_NOTES.md`) designed study 175, the perturbation side study:
174's 35 settled laws each run again and perturbed at four radii, 595 laws, its verdict committed first, and a reader
of what the top laws share. **848** (`docs/build_notes/BUILD848_NOTES.md`) puts 846's score in force, as the operator
agreed (2026-11-23 15:45). **Next**: 849 reads what the operator sends (`docs/agent/NEXT_BUILD.md`).

**Build 841 carries study 173, the gated pilot** (`docs/build_notes/BUILD841_NOTES.md`,
`resources/readings/study_173_design.json` and its criterion, committed before any start): 172's design on a seed of
its own, six gates stopping a law with a tenth let through at every size (the three fact gates, `starts_alike`,
`starts_apart_by_history`, `nothing_read` on 0.9 of the graph), the new **cut gate recording only** (the operator,
21:03, "Record only", after 172's replay showed a stopping cut gate losing 7 of 22 scoring laws), a longer chain on
twice its budget, the ledger counting a priced law's verdicts, a frozen lattice scoring 1, each chain's work in the
bundle. Replayed on 172 (`tools/design_on_a_bundle.py`): about 150 core-hours against 172's 750, no scorer lost.
**Study 172 was stopped and study 173 started in its place** (the operator, 2026-11-21
18:08: "I will probably just run the study bundle of the current study one last time, and then just abort it and
start the new study with the new gates and the new seeds"). 172 is the bigger baseline of 2,500 laws they asked for
at 02:59 (`resources/readings/study_172_design.json`): one die a law a size, only the empty, too dense and
disconnected gates acting, every other gate recording, every law they pass to 65,536. It started on 835 and its
folder is on 838 since its progress bundle of 15:58Z, which **839 read** (`docs/build_notes/BUILD839_NOTES.md`):
11,532 decisions and every one replays; R1 to R3, R5 and R6 hold, R4 misses by the disconnected gate confirming; 173
core-hours spent of about 870, 64% of them above 4,096; 22 drawn laws score, every one through a lattice start and
none from empty or random; 127 seeds ran past their budget, the worst a chunk of 5.2 hours that a restart then lost.
Replayed on 172's own laws, three of the recorded gates (`starts_alike`, `starts_apart_by_history`, and `nothing_read`
with its piece at 0.9 of the graph) withhold 778 laws and 73% of the compute and lose no scorer. **The builds agreed
at 18:08** ("I agree with all recommendations"): **839**, the reading and the pages (the fleet table's stops, a
probe's time over the seeds it ran on, a seed's time with its stopped runs, the work expected beside the work
queued); **840**, no seed past its budget and no chunk lost (`docs/build_notes/BUILD840_NOTES.md`): both engines stop
a chunk at the same move when the seed's work reaches its budget, the seed ending on its last whole chunk; a stop
waits 120 s for a save, a seed saves inside a long chunk every 8 T units, and a saved state carries its last whole
chunk; the crate is 0.840.0 and the Boltzmann reading, run again, is the same in every cell; **841**, the gated
pilot's rules and study 173's design. **Decided while 840 was made** (19:26 to 20:02, `docs/HISTORY.md`): a law with
a cut seed is stopped by a gate of its own, a tenth let through; the let-through stays a tenth after a gate confirms;
a frozen lattice scores 1; the fleet table's budget stops are `cut` and `priced`; each open question gets its
experiment (what the lattice starts cost above 4,096, a run's scaling with N, the 2019 model as a control that grows
from random to 4,096 with every study); 172 is not touched, and its last bundle is the last check before 173. A month
is the most study A may take (18:08). **Study 171** (the baseline of 1,000 laws) was stopped for 172 at 04:23.
**838** made the reading of 172 ready for a fresh context and added `tools/gate_variants.py` and
`tools/bundle_growth.py`; the stable work it started unasked waits until right before study A (16:11), its tools kept
(`tools/planted_faults.py`, `tools/study_twice.py`, the numbers' checks).
**837** took the cleanups that touch nothing a study decides (`docs/build_notes/BUILD837_NOTES.md`): a seed whose
worker commits reads `committing`; the release ships only what git tracks; the Campaigns page divides the fleet all
or nothing and answers a failure; a deletion checks its guard under the lock; the disordered reader leaves the
controls out; the rest kept or closed with the reason; nothing built for size until 172 measures it (the operator,
06:01). **836** made 172's reading ready while it runs: every chain's peak degree in the bundle (`tables/chains.ndjson.gz`,
from each run's compact evidence; applied to 172's folder, if at all, only after its last law, to make its bundle),
`tools/cap_reading.py` (what a lower mean degree cap would cut, asked at 03:54) and `tools/study_172_reading.py` (R1
to R7 in one command, dry-run on 171's progress bundle) (`docs/build_notes/BUILD836_NOTES.md`). **835** carried
172's design, one die, the rename of `seen_enough` to **`repeats_a_known_result`** (every former name read in the new,
fingerprints and picks unchanged), the wording of a park over budget for a longer chain, the study bundle's button
answering the first click, and took out the two tests skipped every build and study 159's controls criterion.
**Study A's full run is ten batches of 10,000** (the operator, 04:29). **834** let a
law decide as soon as no earlier law can still change what it learns, after 171's 48 base-block laws had waited
`pending: learning` for hours on 1 to 3 of 16 workers, and let a waiting law give up its place. **833** was the
consolidation. Before it: **829** ended the cleanup and added **auto extend**, which **830** made act on a study's
batches; **831 and 832** made the gates' counters the study's (the operator, 10:32; `DecisionStore.study_batches`):
every batch learns from every batch's laws at the same fixed points. **Study 170** (820) was read at 827: every
decision replays, its gates withheld 95% of the laws by 4,096, its budgets stopped 43 of the 46 laws that passed every
gate there. **Study 169** (813) was read at 821. The operator sent 169's, 170's and 171's bundles at 14:20 ("this is
our baseline"); none is in the tree.

**The cutoff decides the order** (the operator, 2026-11-18 16:31 to 16:48, `docs/HISTORY.md`, "The operator's standing
decisions"): every fault called out fixed, every legacy data structure and data set thrown away, the instrument's own
evidence included, the probes fixed and the code locked, the table measured again on their host and installed, and
then study 169. Done: the studies before 169 left at 799; the probes were locked at 800 and the table measured on 801
and installed at 805; no result depends on the machine's speed since 806; 807 made no early end by a chain's descent;
808 read the dimension test again on the final probes; 809 to 812 took the probes' rounds before the lock, the older
fits' readings, the dimension test's older criteria and 759's and 735's readings out; 813 carries 169's design; 814
sorted the unscheduled items; 816 to 819 judged every remaining set again; 822 to 826 and 829 took out the old
names, the guards and fixtures of removed things, every mention of an older study and the 2019 model's readings
(`docs/ROADMAP.md`, "What still carries the past", says what is left: the frozen noise floors of 4.0.0).

**The project.** Can simple local rules make a graph grow a dimension of any d, whole or not, like space; which keep one
they are given; and can the null map predict a law before it runs (the operator, 2026-10-13 and 2026-11-06 17:08: "I
think we're looking for all interesting dimensional behavior no?")? A law is an energy over a graph (a few of fourteen
terms, each with a coupling and a scale in N) and its dynamics (the toggle move, locality, zero or finite temperature,
a swap share). The survey draws laws blindly, grows each from eight starts at sizes from 64 nodes up, reads four
dimension probes (d_s, d_V, d_B, d_w) and the curvature, and spends the large sizes only on laws that earn them. What
is known is `docs/WHERE_WE_ARE.md`, with its numbers in `docs/RESEARCH_METHOD.md`. **No data from a study before 169 is
in the tree** (the operator, 2026-11-15 14:07 and 2026-11-18 16:43): each build that took some out sent it as an
archive beside its release, and nothing is designed, predicted or decided from an earlier study's laws.

**The paper is three studies** (the operator, 2026-11-15 14:07, `docs/ROADMAP.md`, "The thread"): study A, the broad
blind search on eight starts without the curvature term, its gates learning from its own laws alone, run and then
replicated; the gates then closed and carried from study to study, against a study run fresh; and the curvature term
added as a study of its own. Study A runs first as a trial of five batches of 1,000 laws, then in full, 100,000 laws in
ten batches of 10,000 (2026-11-21 04:29). **The 2019 model is run again only after these three studies** (2026-11-19 22:05).

## Start here, in a fresh context

Every build from 762 on was made from the archive before it, sometimes with the operator's words typed above it; a
context that opens this archive is in the same place, and `docs/agent/NEXT_BUILD.md` is the page to work from.

1. **Unpack the archive and make one commit of it as distributed** ("Baseline: Build <N> as distributed"; it carries
   no `.git` and no `var/`), bring the environment up by `docs/agent/ENVIRONMENT.md`, section 10, and run the full
   lane once on the untouched tree, detached (20 to 24 minutes on two cores): its count is the newest notes'.
2. **Read what the operator sent** first (`docs/OPERATIONS.md`, "Reading what the operator sends"); answer in one plain
   sentence first (`docs/agent/WORKING_WITH_THE_OPERATOR.md`). **A study's bundle is read by
   `docs/agent/NEXT_BUILD.md`, "Reading a study's bundle"**, every reader in order. Then make the next build.
3. **What is live is not touched without their word.** Ask them to apply a build to a running folder only if it fixes
   something the folder runs or shows, or they asked for what it changes. A study's criterion is never revised after
   its run started.

## What is live

* **Study 173**: its first run (on 841, 16 workers) and its rerun (on 841, `--workers 32`, 23 slots held) are
  stopped and read. Its run on 843 with `--workers 32` (32 slots held, 1.65 h) is stopped and read.
* **Study 174** on 844 in a folder of its own, running since 2026-11-22 16:05Z on 16 workers; its first bundle
  (2026-11-23 09:52Z, 6,173 laws) was read at 845 and 846: every one of its 27,571 decisions replays. 845 and 846 may
  be applied to its folder (846 for the worker count, one restart of the same command); neither changes a decision.
  172's folder, stopped on 838 after its last bundle, is theirs to delete.
* **The worker count while a study runs** (846, System page, Workers): `compute_worker_target`, read by the
  supervisor every half second; a lower count stops the slots above it at once, each saving its seed and giving its
  rung back uncharged (`docs/ARCHITECTURE.md`, "What the fleet does").
* **Study 171**, stopped on 834 (2026-11-21 04:23); its folder is theirs to delete, its progress bundle read.
* **Study 170 on 820**, ended and read at 827; its folder's dashboard, left open, was the core at 100% of 12:45 (a
  landscape worker every 16 s on 828's code and before). Its folder is theirs to stop and delete, as are study 169's
  (813, read at 821) and every older pilot's. The calibration's folder holds a table and nothing else.
* **Auto extend** (829, acting from 830, `operations/auto_extend.py`): the flag `auto_extend`, off in every folder
  until ticked on the Campaigns page; at the end of every controller pass (`controller.finish_pass`), when every
  budgeted campaign reads **done** (`study.budget_state`) or completed, each gets 50 more laws. A study's batches are
  continuous, never completed. `auto_extend_last` keeps the last one.
* **The dashboard's landscape** (829, `services/api/landscape_inputs.py`): due at 16 s, built only when the write
  counters of the tables it reads, or a score board, moved since the last build; the tables are held to what a build
  reads by `tests/integration/test_the_landscape_s_inputs_postgres.py`.
* **The budgets in work** (806): a seed's budget is its size's entry in the design's `ladder.budgets` (the shipped
  spec's `engine.policy.work_budgets`), in units of the engines' weighted count of work (`engine.policy.work_unit`,
  fitted once on 288 sandbox seeds, `graph_scale_dynamics/resources/readings/work_unit_fit.json`); a seed ends with
  reason `budget` when the next chunk would not fit or, since 840, inside a chunk that passes it, read on its last
  whole chunk, and `rung_terminal.work` says what it did, refused and where it was cut. A
  law whose first chunk at the next size would not fit is stopped `over_budget`. The fleet table shows each size's
  budget in work alone (839; `engine.policy.seconds_a_unit` is the sandbox's rate, no clock on a host); report 28's seed table carries each seed's
  `work_budget`, `work_units` and `budget_fraction`. A bundle carries every decision's inputs in
  `tables/decisions.ndjson.gz`, the group and the batches a law learned from among them (`learned`);
  `tools/replay_bundle.py <bundle>` replays each.
* **The finds** (795): every study bundle carries `finds.json` (each law scoring above zero with its spec, score, `d`,
  mean degree and which terms scale with N), the study's own data. A register across studies is made again after study
  A from the candidates chosen there.
* **The work** (794): both engines count each move's work and its parts in every chain's move accounting, equal on the
  parity suite, replayed from the seed; since 806 a seed's budget is counted in it.
* **The host**: their own `apply_build.py` applies a build to a folder; the MEM BW tile reads their collector
  (`/run/membw/latest.json`) and shows zeros after the host suspends until they restart it. Studies 156 and 158's
  folders are theirs to keep; no build goes onto either.

## The instrument on known answers

Judged on the final code:

* **The calibration table** (805): measured whole on the host on 801 under analysis 5.3 (`tools/probe_calibration.py
  --whole`, 2,584 cells, 27 families), the seed's 2,584 cells took 190 hours between them (about 8 hours on the host's
  clock with 31 workers); judged first against the criterion committed before its zip was seen
  (`table_known_answers_criterion.json`, 802), which it passes: every held cell inside its band, the two close-packed 4D
  lattices held from where their own cells read, every graph without a dimension refused from 4,096 nodes. The table's
  rule rests on that criterion and its judged reading (`resources/calibration/table_rule_2.json`). The lock: `python3 -c
  "from graph_scale_dynamics.calibration import fingerprint as F, start_reading as S; print(F.analysis_version(),
  F.estimator_fingerprint(), S.fingerprint())"` prints `analysis-5.3.0 e639334808716378 89f4fed82d9adc27`.
* **The dimension test** (729, read again at 808, `research/dimension_test.py`, `tools/dimension_test.py`): a chain
  shows dimensional behaviour of some d when its reach grows as a power of N and the d that power implies agrees with
  the d its balls read (within 0.4, relative); set on 13 training graphs and frozen, read again on the final probes
  with 9 held-out graphs on fresh seeds, criterion first: every case on every seed
  (`docs/readings/dimension_test_4_judged.md`). The dimension rule's calibration is read from it
  (`research/dimension_rule.CALIBRATED_ON`).
* **The certificate's count** (built at 780, read again at 816, `tools/certificate_known_answers.py`,
  `certificate_known_answers_criterion_3.json`): on AR(1) series of known correlation time every chain's own count
  certifies at 16 a rung with one chain of at most 2 true samples in at most 5.0% of chunks and keeps 98.6% to 99.7% of
  rungs of plenty; no rung is fit at 8. The certificate's other items were judged at 803
  (`certificate_fixes_criterion.json`).
* **The engines on exact Boltzmann measures** (built at 753, read on the engines as 806 left them at 816,
  `tools/boltzmann_known_answers.py`, `boltzmann_known_answers_criterion_4.json`): every one of the fourteen terms keeps
  its measure (260 of 260 cells) and reaches it from empty (112 of 112) on both engines, which give every graph the same
  energy to the last bit, and the control, the toggle's law at twice its energy, is refused in all four cells. It is
  read again whenever an engine changes: at 840, on crate 0.840.0, every number of all 264 cells is the same.
* **The curvature** (built at 752, read again at 816, `tools/curvature_known_answers.py`): the term and the probe are
  Ollivier's curvature on every edge of the lattices without shared triangles, and on the triangular torus read +1/3
  where it is 0; on a random geometric graph in the plane they agree on 47 of 300 edges.
* **Which lattices a law can tell from a random graph** (built at 757, read again at 816, `tools/start_admission.py`):
  all six lattice starts are told by at least one term, the honeycomb and the diamond lattice by none. It reads
  energies, no chain.
* **What settles means for the score** (783, judged again at 817, `tools/score_known_answers.py`,
  `score_known_answers_criterion_3.json`): the margins, twice the widest step of the table's exact lattices, judged on
  seventeen structures on seeds 51 to 53 read by the final probes: every held probe settles (72 of 72), every structure
  held on all four reaches the fifth band (15 of 15), nothing that must refuse settles (20 of 20).
* **The score's rules of 846, in force since 848** (`observability/law_score.py`, `gsd-law-score-8`; criteria 4 and 5
  of `tools/score_known_answers.py`): counted seeds, a piece of half the graph, a step whose reach grows as the
  dimension read and whose next step does not break it. On seeds 61 to 63 they pass every known answer of criterion 3
  again, read strips and tubes only as lines (9 of 9) and soups under half the graph as nothing (3 of 3), and miss on
  trees of long paths (4 of 6 pairs, d 1.1 to 1.4), which the score before them settled alike.
* **The structure rule's blind spot** (537, read again at 818, `tools/calibrate_structure.py --read-chained`,
  `chained_cubic_criterion.json`): chained cubic graphs fool the rule alone in 8 of 9 seeds at the survey's threshold
  and are refused by the three readings together in all 9, at 4,096 to 65,536 nodes; the two Sierpinski fractals
  are not read at those sizes, so by its own rule it does not pass.
* **The starts' known answers** (602's eleven, written for the eight starts at 819, `tools/starts_check.py`,
  `starts_known_answers_criterion.json`): 8 of 11 cases pass on the table's references; the three misses are one
  label, a random graph in the fcc start's chain reading partly kept at 1,024, the class the rule decides by right in
  all three.

The 2019 model (`tools/replication.py`): its readings and criteria left at 829 (the operator, 11:48); it is run
again after the paper's three studies, on the final probes, with a criterion written fresh.

## The tree

* **The score** (783, `observability/law_score.py`, gsd-law-score-5; `docs/ARCHITECTURE.md`): a probe that settles
  between two sizes from 4,096 is a point, all four agreeing by the Einstein relation a fifth (the landscape's 5th band,
  `landscape_worker.BAND_EINSTEIN`), times who (the twins 1, a changed lattice start 0.6, a kept one 0.3) and depth; its
  margins are `resources/calibration/score_margins.json`.
* **The decisions** (`decisions/engine.py`, rules revision 782): the base block (64 to 4,096, three seeds), then the
  starts decide depth; every gate lets a share run one size past it, learned from the study's own decisions at fixed
  points in the laws' own order (`decisions/let_through.py`, `repeats_a_known_result`), its ledger in the bundle
  (`gates_ledger.json`). The first gate on the base block (`decisions/nothing_read.py`, on unless a design turns it off
  by `engine.nothing_read_gate`) parks at 4,096 a law none of whose chains read any probe. A later seed is priced from
  its law's own peak at that size (`memory.own_earlier_seed_bytes`). No seed is lost (786): a fleet's stop gives its
  workers longer than they give their simulations, a start queues again every seed the last fleet held, a seed whose
  worker vanished runs again and is never charged to its law (`docs/OPERATIONS.md`).
* **The operator's one rule** (781): every graph must stop changing, every chain that ran deciding the chunk loop by its
  own certificate (its count, drift and structural trend, its rest at zero temperature; its late overlap read from the
  edges it changed since 85% of its moves, no copy), only **the twin starts**, the chain from empty and the random
  start's, meeting at a finite temperature, a rung frozen only when every chain is, every chain at the cap ending alone
  and the rung refused when both twins have crossed it (`docs/ARCHITECTURE.md`, "The certificate"). A seed ends
  certified, frozen two chunks running (804), at a pass at the cap (807), at the degree cap or at its budget in work,
  never by a clock; a seed's chains share one budget (`scaleflow/one_shot.run_one_shot`).
* **The engines** (engine-3.3.0, the Rust crate 0.840.0; Python and Rust in parity through the engine contract,
  `services/worker/engine_registry.ENGINES`, the plain-data boundary `engine/boundary.py`, `docs/ARCHITECTURE.md`, "The
  engines"): one list of chains in one code path (`engine/chains.py`), the toggle the one local move
  (`dsl.LOCAL_MOVES`), every regime equilibrium or zero temperature, each chain's running energy held to its graph's at
  every chunk's end; **no final graph** (797): a chain's record keeps its graph's edge count and digest
  (`chain-record-4`), the graph had again by running its seed. The sampler is `blind-sampler-2`.
* **The probes and the table's key** (758): `measurements/estimators.py` with `box_covering.py`, `walk_dimension.py`
  and `fits.py`; the certificate (`measurements/certificate.py`) and the reading of a chain's record
  (`measurements/analysis.py`) are outside it (`tests/unit/test_only_the_probes_recalibrate.py`). Analysis 5.3 is the
  only analysis in the code (`measurements/version.py`); a design made on another is refused
  (`operations/study.instrument_refusal`). The decision engine's finite-size tolerance
  (`resources/calibration/finite_size_tolerance.json`) and the d_s margin bands are made from the table, the
  tolerance's fits frozen into the shipped spec; a new folder adopts the seed by measuring one cell a family again
  (`docs/ARCHITECTURE.md`, "Calibration").
* **The eight starts** (769), defined once in `measurements/starts.py`: empty, `random` (a random graph at a mean degree
  drawn for the law), and the lattices `square` (2 dimensions, 4 neighbours), `triangular` (2, 6), `cubic` (3, 6),
  `bcc` (3, 8), `fcc` (3, 12) and `tesseract` (4, 8). A chain is named by its start (756); what reads the starts
  against each other is the starts' reading (`observability/starts_reading.py`), what decides depth by it the starts'
  rule (`decisions/starts_rule.py`). Every lattice start has a band and its own d in the dimension rule.
* **The old names left at 822**: every committed file and bundle is read as written, in today's names; a gate
  renamed at 773 keeps its old label in its let-through's stream (`gates.SALT_STREAM_LABELS`).
* **The code carries no comment or docstring** (`tests/contract/test_the_code_carries_no_comments.py`), bar the engines'
  sources until their next change. The bundles are the operator's and never in the tree; what was read from a pilot's
  is in the notes of the build that read it (`docs/readings/README.md`). A file a historical passage names is as it was
  in the build that held it.

## What waits on the operator

* **Study 174's bundles**, a progress bundle whenever they send one and the last at its end.
* **848 in the folders of 174 and 175**: theirs to apply; it changes no decision.
* **Study 175, the perturbation side study** (847, `study_175_design.json`): in a folder of its own on all the
  workers, 174 stopped meanwhile (the operator, 2026-11-23 15:45); about 600 core-hours, its bundle to read.
* **Three questions are open and none waits** (`docs/ROADMAP.md`, "Questions for the operator"): the noise floors as
  each law's own measured errors, criterion first (offered at 805); the score's list and whether a geometry needs all
  four probes and the Einstein relation; whether exponential growth is flagged in its own right.
* **Folders**: every pilot folder once read is theirs to delete, 170's with it. A scratch holder parks its files and
  ends ten minutes after its folder's last process.

Builds go on without them while nothing waits on them.

## The system, in brief

* **A folder is a study**: its first start creates the study `--study` names (`operations/study_design.py`) and
  records it in `var/study.json`. A campaign's spec is frozen at creation; its share and budget can change.
* **One-shot jobs**: a simulation job runs a rung for one seed in one child, in chunks whose certificate decides
  whether to go on. A pause resumes byte for byte on either engine; Rust is the default.
* **Decisions** (`decisions/engine.py`): the base block, then the starts decide depth; every gate lets a share run one
  rung past it, and every decision replays from its inputs.
* **The readings**: report 28 scores every chain of every law from 1,024 and reads the starts against each other; the
  study bundle carries its pages and its gates' ledger.
* **The host**: one worker per physical core; memory admission keeps 10 GiB free; the RAM scratch is a tmpfs of half
  the RAM, moved to disk past 60%; nothing of a fleet outlives its folder.
* **Outside the fleet**: the replication harnesses (`tools/replication.py`) run a published model by its own rules;
  none of their readings is in the tree since 829.

## Where everything else lives

| what | its one home |
|---|---|
| the project on one page, in the operator's words | `docs/WHERE_WE_ARE.md` |
| the next build, how to make and release one | `docs/agent/NEXT_BUILD.md` |
| how the operator sends, decides and wants answers | `docs/agent/WORKING_WITH_THE_OPERATOR.md` |
| the cold start, and the sandbox's traps | `docs/agent/ENVIRONMENT.md`, section 10 |
| the questions for the operator, the planned builds, the constraints, the cadence | `docs/ROADMAP.md` |
| the operator's standing decisions, with their dates and words; the eras | `docs/HISTORY.md` |
| what is known, each number with its source | `docs/RESEARCH_METHOD.md`; `docs/readings/findings.json` |
| every reading in the tree and what it is | `docs/readings/README.md` |
| how to read what the operator sends; the recipes | `docs/OPERATIONS.md` |
| how the fleet decides | `docs/DECISIONS.md` |
| the loop, the child, the scores, the reports; the blockers | `docs/ARCHITECTURE.md` |
| what each tool is for and how it runs | `docs/TOOLS.md` |
| the rules learned by shipping their opposite; what not to do | `docs/LESSONS.md` |
| the research host and the sandbox | `docs/agent/TARGET_ENVIRONMENT.md` |
| the notes since the last consolidation and of the ten builds before it; every build's, in its own archive | `docs/build_notes/`; `GSD<N>.tar.zst` |
| the published papers the project builds on | `docs/references/` |
