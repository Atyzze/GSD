# Handoff: the state of GSD at build 895

What is true now, for a context that has just opened this archive. Each fact has one home; the last section says
where. **Think from the data, not from this page**: where the data and a document disagree, the data wins and the
document is fixed in the same build.

**The heading** (the operator, 2026-11-26 19:06 to 19:59): the dex becomes a list of zones, each named by its central
law pushed to the largest N, every other law a distance from it; one zone at a time with every worker, the blind draw
only when no zone has work; a zone told by what its laws do (the curves of the four probes on every start over N),
not by its term set. **`docs/agent/ZONE_MAP.md`** holds it, with what the data and the code already say; it is read
before any build from 887.

**The fleet now** (893, 894; the operator, 2026-11-27 10:35: "always doing 1 of the three, never combining any of
them though the N-push is the natural end-station of the zoned-searched"): the fleet is always in one of three modes
(`operations/modes.py`, the flag `fleet_mode`), named on Home beside Now researching and on the Top page. **The
N-push** while the Top page's push list holds a law: the first law runs its whole ladder again from N=64 in a
campaign of its own (part P, `operations/push_ladder.py`), as many seeds a rung as the worker count, all at once; as
memory binds, fewer at once and fewer seeds, down to 3, then in passes, on two workers, then on one; when not one
seed of the next size fits the host's memory the law leaves the list and the next is pushed. **The zone search**
while a zone has work: the dex read in checked law by law, then the zone chosen, its laws judged, each parameter
stepped and halved, the edges read again, its central law pushed (it joins the end of the list); the slots the zone
leaves free run its lines' next points ahead. **The blind ladder** with its gates only when the list is empty and
no zone has work. A run of another mode stops within two seconds, its seed saved. Every page follows an event stream
fed by Postgres's notifications and reads again when the work changes; a pushed law keeps the code it was pushed with
on every page, and a law page draws each size from the campaign of the law with the most seeds there.

**The builds since the handover (886), 887 to 894** (each build's notes in `docs/build_notes/`; the operator's words
in `docs/HISTORY.md`):

* 887: study 178 designed (`study_178_design.json`): the blind draw as the base load; the first dex read in makes its
  own campaign (kind `seed`), every law run again and checked chain by chain against the dex
  (`operations/dex_check.py`: confirmed, denied or unmatched); then the first zone (`operations/zone_choice.py`: the
  most confirmed laws of one term set within 0.1 of one centre), its centre taken into focus.
* 888: the import folder ships in the tree, a dex in it read in at the study's start, read again to N=4,096 law by
  law; Working now one row per law; a new copy of the dex written when it learns something.
* 889: "push to the N limit" on every law page; the Top page.
* 890: the first zone searched by stepping and halving each parameter (`operations/zone_search.py`, part E), its laws
  judged at 4,096 by their locked-in curves (`observability/likeness.py`), the edges read again at 16,384, its central
  law pushed; benchmarked against the ring method (3.2 core-hours on the same zone in 176).
* 891: the zones one after another; a zone kept on its region and carried in the dex with its central law; the dex's
  lucky hits.
* 892: the push list holds the host, in the operator's order; a zone's central law joins its end.
* 893: the three modes; the N-push its own ladder from 64, its forecast and break-points plotted on the Top page; the
  law page reads every campaign of its law; Home's fleet ladder one box, live values for rungs under way; the zone
  search's look-ahead on free slots.
* 894: one code for a pushed law on every page; each size of a law page from the campaign with the most seeds; the
  pages told of every change of the work (`services/api/events.py`, our own stack: the operator, 13:00).

**Before that, 871 to 885** (the handover of 886 read them):

* 871: seeded laws in the focus on their bundle's score; every law named by study, campaign and graph (`law_code`).
* 872: Home's "The study now" in core-hours and memory; "Which laws" leads; the fleet ladder in two tables.
* 873: the depth seeker to the memory limit (`depth_reach`, the decider's `memory_ceiling`).
* 874: pages and reports say what a build number stood for, in words.
* 875 to 877: a seed in half the memory with the same chains; the C engine and the assembly kernel, Rust the default.
* 878, 879: the lexicon (every law's distance to 24 known types) and the phenotype (each curve's fewest form).
* 880: the outliers' queue, taken once every scoring law is mapped.
* 881: the focus's step mended (19 hours failed on 176), one depth worker to half the memory, study 177 designed.
* 882: the dex (`operations/dex.py`): every scoring law, its codes, scores, chains, written hourly into `export/`,
  read in from `import/`; codes dashed (S178-C11-G4766).
* 883: the first zone unblocked (the depth list, seeds compared at one size, nothing judged before the law's kind);
  every law opens; the dex checks a run again like for like (8,000 of 177's chains against 176's: identical).
* 884: the zone live on the Map page (`operations/zone_live.py`): who runs, every law of the zone where it stands with
  a clock, the work left.
* 885: one order for runs and probes (`work_groups.ordered`: the zone of the law in focus, the depth worker, the Dex
  laws, the blind draw, earlier laws' leftovers); the slider gone; a zone standing at ring 0.01 when 0.1 fails, else a
  lucky hit; zones named Z1.

**Before that**: 855 `CLAUDE.md` and the calibration ledger (`docs/agent/APPEND_ONLY_PLAN.md`, paused); 856 to 859
study 176's first design, a science hash in every bundle, Home's filters, a handover; 860 Home says what is true; 861
and 862 the focus and the Map page; 864 to 869 no law done, study 176 seeded from bundles, the law page in words, the
`import/` folder; 870 a handover. The baseline the paper rests on (174's bundle of 2026-11-24 14:22Z, 175's of 08:35Z,
the calibration table) and what it shows: `docs/WHERE_WE_ARE.md` and `docs/paper/GSD_PAPER.md`.

**Open threads at 895**, each with its home:

* **Pull requests**: 864 to 893 (#11 to #35) merged by the operator, #34 and #35 at 2026-11-27 11:21Z; `main` holds
  893. Open: 894 (#36) and 895's, made on it; merged in that order.
* **Study 178** (`/data/projects/GSD/178/main`, `study_178_design.json`, criterion `study_178_criterion.json`) runs
  on 893 since 2026-11-27 about 11:20Z. 177's dex of 19:33Z was read in at its start (C15) and checked: 192 laws
  confirmed, 1 unmatched, at 07:18Z; the first zone (S178-C15-G2302, 177's S176-C12-G100, G79's family) was chosen at
  once and searched from 07:19Z, its 28 laws within 0.1 alike to the centre. Under 892 G2302 was pushed to N=262,144
  (rule `memory_ceiling`). At 12:06Z the fleet was in the N-push on S178-C15-G73 (law 8addbb0c), its ladder again from
  64 in C17 on 16 seeds a rung, 262,144 under way on 16 workers; S178-C15-G133 next on the list. Its forecast then put
  1,048,576 on 6 workers at once from about 13:31Z and 4,194,304 on one worker, three seeds in three passes, from
  about 22:23Z, the push ending about 171 hours on (around 2026-12-04 15:20Z); **the operator reads the N-push as
  confirmed once its first worker runs 4,194,304** (13:06).
* **Study 177** (`/data/projects/GSD/177/main`) and its dex of 19:33Z (193 laws, 76 term sets, 26,366 chains) are the
  operator's; 178 read that dex in.
* **Studies 176 and 174** stopped or the operator's; their bundles were read at 881 and 865.
* **Open questions** (`docs/ROADMAP.md`, "Questions for the operator", and "Still open from 884 to 894"): the zone
  search's slots still idle while its members are read or its edges at 16,384; a size started before any run below it
  has finished; a topology probe; 176's standing controls.

## Start here, in a fresh context

Every build from 762 on was made from the archive before it, and since 855 from `main` of `github.com/Atyzze/GSD`,
sometimes with the operator's words typed above it; a context that opens either is in the same place, and
`docs/agent/NEXT_BUILD.md` is the page to work from.

1. **Clone `main`** (`docs/agent/ENVIRONMENT.md`, section 10, "From the repository"), **or unpack the archive and make
   one commit of it as distributed** ("Baseline: Build <N> as distributed"; it carries no `.git` and no `var/`); bring
   the environment up by section 10 and run the full lane once on the untouched tree, detached (20 to 24 minutes on
   two cores): its count is the newest notes'.
2. **Read what the operator sent** first (`docs/OPERATIONS.md`, "Reading what the operator sends"); answer in one plain
   sentence first (`docs/agent/WORKING_WITH_THE_OPERATOR.md`). **A study's bundle is read by
   `docs/agent/NEXT_BUILD.md`, "Reading a study's bundle"**, every reader in order. Then make the next build.
3. **What is live is not touched without their word.** Ask them to apply a build to a running folder only if it fixes
   something the folder runs or shows, or they asked for what it changes. A study's criterion is never revised after
   its run started.

## What is live

* **Study 178** (887) runs on 893 (above); 894 and 895 apply to it without a restart of the fleet (the pages and the
  push's naming change; the fleet's work does not). Its mode is the flag `fleet_mode`, its push list and the N-push's
  ladder the focus state's `pushed`, `depth_now` and `campaigns.P` (`docs/ARCHITECTURE.md`, "The fleet's three
  modes", "A law pushed to the N limit").
* **Studies 174 to 176** in folders of their own, stopped or the operator's; the baseline bundles are 174's of
  2026-11-24 14:22Z and 175's of 08:35Z. Every older folder (169 to 173, 156, 158) is the operator's to delete.
* **The worker count while a study runs** (846, System page, Workers): `compute_worker_target`, read by the
  supervisor every half second; a lower count stops the slots above it at once, each saving its seed and giving its
  rung back uncharged (`docs/ARCHITECTURE.md`, "What the fleet does").
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

* **The score** (783, `observability/law_score.py`, gsd-law-score-9 since 856: a lattice chain still at a size, its
  own degree within 5% and at most 0.05 accepted moves an edge, scores 1 as a frozen one does; `docs/ARCHITECTURE.md`): a probe that settles
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

* **894's and 895's pull requests** (#36 and the next): theirs to merge, in that order (895 is made on 894).
* **Study 178 on 895**: applied to its folder (`docs/build_notes/BUILD894_NOTES.md`, "For the folders"); its next
  bundle or dex once the N-push reaches 4,194,304 or a zone is mapped, read by `docs/agent/NEXT_BUILD.md`.
* **The push list's order** on the Top page: "first", "up", "stop pushing"; any law page's "push to the N limit".
* **Study 176's standing controls**: kept as a tick (recommended; `docs/ROADMAP.md`, "Questions for the operator").
* **Where the older data's archive goes public** (the consolidation): the review asks for a public archive (Zenodo or a tag) so a
  referee can see nothing was dropped selectively; the operator wants it out of the tree. Both hold if the archive
  goes beside the build and its place is theirs to name.
* **The sampler** (`docs/ROADMAP.md`, "Still open from before 886", item 1): whether a known law must grow its geometry from empty before more
  compute goes to blind laws from empty; parallel tempering is the cheapest remedy and changes the engine.
* **Home's refresh** (18:26 of 2026-11-26): since 894 the pages follow the fleet's events and read again when the work
  changes; a faster fixed refresh is not needed unless the operator still sees a page lag.
* **Folders**: every pilot folder once read is theirs to delete. A scratch holder parks its files and ends ten minutes
  after its folder's last process.

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
| where the project is heading: zones, their behaviour, how one is mapped | `docs/agent/ZONE_MAP.md` |
| the next build, how to make and release one | `docs/agent/NEXT_BUILD.md` |
| the paper, a working draft resting on the baseline, claiming nothing | `docs/paper/GSD_PAPER.md` |
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
| the published papers the project builds on, by arXiv id and version | `docs/RESEARCH_METHOD.md`, "The papers read" |
