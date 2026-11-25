# The readings in the tree

Every file in this folder, and what it is. The study bundles are the operator's and never in the tree; what was read
from them is, here, written by the tools named beside each file and committed as they wrote it; every criterion,
design and judged run is pinned by its hash in `tests/fixtures/committed_readings.json`
(`tests/unit/test_committed_readings_do_not_change.py`). Every criterion was committed before the run it judges.
`tests/unit/test_the_readings_are_indexed.py` fails when a file here is not named below (a name with `<utc>` in it
stands for every file of that pattern).

This folder keeps what people read, under 100 MB (the operator, 2026-11-03 14:23: "its our working/scratch pad folder
for on-going project-produced data"). Only what the instrument reads on known answers is here (the 2019 model's
readings left at 829, the operator, 2026-11-20 11:48: "we weren't using the budget yet, we also weren't using a modern
probes yet"; into `GSD_readings_archive_829.tar.zst`): no study's data before 169 (the operator, 2026-11-18 16:43: "ALL old data we want GONE"), and a pilot's reading
goes into the notes of the build that reads it. The finds register is made again after study A.

* **The inputs the code reads** (the criteria, the study design, the register of studies, the starts' references
  and known answers) are in `graph_scale_dynamics/resources/readings/`, found through
  `graph_scale_dynamics/resources/committed.py`; below each is written with that path. A path a spec recorded as
  `docs/readings/<name>` still finds it.

## The archives

The readings of the studies before 169, and the instrument's evidence read before the lock, left the tree between 714
and 829, each build sending what it took out as a readings archive beside the release (the 2019 model's in
`GSD_readings_archive_829.tar.zst`; the operator, 2026-11-16 10:37: "so that all data from older studies can be
completely discarded and taken out of our build archive"). A reading a historical passage names that is not here is
as it was in the build that held it. A tool no longer in `tools/` is in a tools archive sent beside its build.

## The register

* `graph_scale_dynamics/resources/readings/studies.json`: every study this tree can start (169 to 172), its
  question, design, size and the line its folder's notes begin with.
* `findings.json`: every finding the standing documents state (`docs/WHERE_WE_ARE.md`, `docs/RESEARCH_METHOD.md`),
  beside the files it rests on and the command that reads it again; since 784 the instrument's alone
  (`tests/unit/test_the_findings_manifest.py`).

## The instrument, on known answers

* The starts' known answers (602's eleven, written again for the eight starts at 819, `tools/starts_check.py`): its
  criterion, `graph_scale_dynamics/resources/readings/starts_known_answers_criterion.json`, committed before any case
  was read on seeds 0 to 2; the run against the calibration table's own references,
  `graph_scale_dynamics/resources/readings/starts_known_answers_judged.json` (8 of 11 cases pass; the three misses are
  the fcc start's fate at 1,024; it does not pass by its own rule).
* `graph_scale_dynamics/resources/readings/noise_floors_analysis-4.0.0.json`: the noise floors the score uses, frozen
  with the estimator that measured them.
* The structure rule's blind spot (read at 537, again on the final probes at 818, `tools/calibrate_structure.py
  --read-chained`): its criterion, `graph_scale_dynamics/resources/readings/chained_cubic_criterion.json`, committed
  before any graph was read; the reading, `graph_scale_dynamics/resources/readings/chained_cubic_judged.json`: random
  cubic graphs whose edges are chains of 100 to 1,000 and the families of known finite dimension, at 4,096 to 65,536
  nodes, through the rule and the three readings (the three readings refuse all 9 chained graphs; they accept 7 of 9
  families and do not read the two Sierpinski fractals at these sizes, so by its own rule it does not pass).
* The dimension test read again on the final probes (build 808, `tools/dimension_test.py --criterion`): its criterion,
  `graph_scale_dynamics/resources/readings/dimension_test_criterion_4.json`, committed 2026-11-19T17:53:00Z before any
  graph was read on analysis 5.3, 729's cases and frozen rule with held-out seeds 21 to 23; the training graphs as
  measured, `graph_scale_dynamics/resources/readings/dimension_test_4_training.json`, from which the dimension rule's
  calibration is read since 808; the held-out graphs, `graph_scale_dynamics/resources/readings/dimension_test_4_held_out.json`;
  and both judged, `graph_scale_dynamics/resources/readings/dimension_test_4_judged.json`, and as a page here,
  `dimension_test_4_judged.md` (every case on every seed).
* Every chain its own count (built at 780, read again on the certificate as 803 to 807 left it at 816,
  `tools/certificate_known_answers.py`): its criterion,
  `graph_scale_dynamics/resources/readings/certificate_known_answers_criterion_3.json`, 780's in today's names,
  committed before it was run; read and judged,
  `graph_scale_dynamics/resources/readings/certificate_known_answers_3_judged.json`, and as a page here,
  `certificate_known_answers_3_judged.md` (fit at 16 on 2 and 8 chains; not at 8; the count on the chain from empty
  alone certifies a rung with a starved chain 99.8% of the time).
* The curvature's known answers (built at 752, read again on the final code at 816,
  `tools/curvature_known_answers.py`): its criterion,
  `graph_scale_dynamics/resources/readings/curvature_known_answers_criterion_2.json`, 752's in today's names, committed
  before it was run; judged, `graph_scale_dynamics/resources/readings/curvature_known_answers_2_judged.json`, and as a
  page here, `curvature_known_answers_2_judged.md` (8 of 8 predictions right; not Ollivier's curvature where triangles
  share edges).

* The engines against exact Boltzmann measures (built at 753, read on the engines as 806 left them at 816,
  `tools/boltzmann_known_answers.py`): its criterion,
  `graph_scale_dynamics/resources/readings/boltzmann_known_answers_criterion_4.json`, committed before it was run;
  judged, `graph_scale_dynamics/resources/readings/boltzmann_known_answers_4_judged.json`, and as a page here,
  `boltzmann_known_answers_4_judged.md` (passes: 260 of 260 cells kept, 112 of 112 reached, the control at twice its
  energy refused in all four cells).
* Which lattices a law can tell from a random graph (built at 757, read again on the final code at 816,
  `tools/start_admission.py`): its criterion, `graph_scale_dynamics/resources/readings/start_admission_criterion_2.json`,
  757's in today's names, committed before it was run; judged,
  `graph_scale_dynamics/resources/readings/start_admission_2_judged.json`, and as a page here,
  `start_admission_2_judged.md` (six of eight lattices admitted, the honeycomb and the diamond lattice told by no term;
  one term list of eight not as expected, the triangular lattice's induced squares).
* What settles means for the score, and the 5th band (built at 783, judged again on the final probes at 817,
  `tools/score_known_answers.py`): its criterion,
  `graph_scale_dynamics/resources/readings/score_known_answers_criterion_3.json`, committed before any structure was
  read, the margins' rule since 783 with seventeen structures on seeds 51 to 53; the structures as read,
  `graph_scale_dynamics/resources/readings/score_known_answers_3_measured.json`; judged,
  `graph_scale_dynamics/resources/readings/score_known_answers_3_judged.json`, and as a page here,
  `score_known_answers_3_judged.md` (passes: K1 72 of 72, K2 15 of 15, K3 20 of 20, K4 16 of 16). The margins the score
  reads, `resources/calibration/score_margins.json`, are this rule's on the installed table. The score's lists are read
  from a pilot's own bundle (`tools/score_list.py`), not kept here.
* The score's rules of 846, in force since 848 (`observability/law_score.py`, `tools/score_known_answers.py`): counted seeds, a piece of
  half the graph, a step whose reach grows as the dimension read and, in criterion 5, whose next step does not break
  it. Criterion 4, `graph_scale_dynamics/resources/readings/score_known_answers_criterion_4.json`, committed before any
  crossover was built or read, on seeds 51 to 53: its rows `graph_scale_dynamics/resources/readings/score_known_answers_4_measured.json`, judged
  `graph_scale_dynamics/resources/readings/score_known_answers_4_judged.json`, and as a page here, `score_known_answers_4_judged.md` (misses S1 on strips that
  are lines, its prediction wrong, and S2 on a tree). Criterion 5, `graph_scale_dynamics/resources/readings/score_known_answers_criterion_5.json`, written fresh
  before any of its structures was read, on seeds 61 to 63: `graph_scale_dynamics/resources/readings/score_known_answers_5_measured.json`, judged
  `graph_scale_dynamics/resources/readings/score_known_answers_5_judged.json`, and as a page here, `score_known_answers_5_judged.md` (K1 to K4, S1 and S3
  hold; S2 misses on trees of long paths, which the score before it settled alike). Its reach rule is the `reach`
  block of `resources/calibration/score_margins.json`; the operator put it in force at 848.
* The calibration table measured on 801, judged against the criterion committed before its zip was seen (802,
  `graph_scale_dynamics/resources/readings/table_known_answers_criterion.json`, 2026-11-19 00:02Z): it passes, every
  held cell within its band and every family without a dimension refused from 4,096 nodes,
  `graph_scale_dynamics/resources/readings/table_known_answers_judged.json` (`tools/table_known_answers.py`) and as a
  page here, `table_known_answers_judged.md`. The table's holds are made from it, by its rule
  (`graph_scale_dynamics/resources/calibration/table_rule_2.json`).

## The code's other inputs

* The pilots' designs and criteria, each committed before its first start (813, 820, 827 revised on 828 before
  any start, and 835): `graph_scale_dynamics/resources/readings/study_169_design.json`, `graph_scale_dynamics/resources/readings/study_169_criterion.json`, `graph_scale_dynamics/resources/readings/study_170_design.json`,
  `graph_scale_dynamics/resources/readings/study_170_criterion.json`, `graph_scale_dynamics/resources/readings/study_171_design.json`, `graph_scale_dynamics/resources/readings/study_171_criterion.json`,
  `graph_scale_dynamics/resources/readings/study_172_design.json` and `graph_scale_dynamics/resources/readings/study_172_criterion.json`; and what the study's
  counters were read for on 170's bundle (831, `tools/counters_reading.py`), `graph_scale_dynamics/resources/readings/study_counters_criterion.json`.
* The certificate's and the probes' fixes before the lock, each judged against a criterion committed first: d_s's
  error the spread of its own probes (800), `graph_scale_dynamics/resources/readings/d_s_error_criterion.json` and `graph_scale_dynamics/resources/readings/d_s_error_judged.json`; the
  certificate's items (803), `graph_scale_dynamics/resources/readings/certificate_fixes_criterion.json` and `graph_scale_dynamics/resources/readings/certificate_fixes_judged.json`; a seed frozen
  two chunks running (804), `graph_scale_dynamics/resources/readings/frozen_early_end_criterion.json` and `graph_scale_dynamics/resources/readings/frozen_early_end_judged.json`; no early end by
  a chain's late descent (807), `graph_scale_dynamics/resources/readings/descent_early_end_criterion.json` and `graph_scale_dynamics/resources/readings/descent_early_end_judged.json`; a pass at
  the cap ends the run (807), `graph_scale_dynamics/resources/readings/cap_pass_criterion.json` and `graph_scale_dynamics/resources/readings/cap_pass_judged.json`.
* `graph_scale_dynamics/resources/readings/work_unit_fit.json`: the engines' work unit, fitted once on sandbox seeds (806, `tools/work_unit_fit.py`).
* The controls' criteria the fleet judges its control campaigns by:
  `graph_scale_dynamics/resources/readings/controls_criterion_2.json` (the standing controls),
  `graph_scale_dynamics/resources/readings/controls_criterion_3.json` (the growth controls),
  `graph_scale_dynamics/resources/readings/positive_control_criterion.json` (the positive control).
* `graph_scale_dynamics/resources/readings/predictor_l2_criterion.json`: the degree predictor's criterion.
* `graph_scale_dynamics/resources/readings/still_lattice_criterion_1.json` (850): whether a lattice chain called still at
  1,024 or 4,096 stays still and never hides a made law, committed before the bundle that judges it; the still lattice
  scores lowest in the score in force only if it passes (`tools/catalogue_reading.py`).
* `graph_scale_dynamics/resources/readings/still_lattice_judged_1.json` (854): that criterion judged on study 174's
  bundle of 2026-11-24 14:22Z: it passes (89 of 89 still chains at 1,024 and 39 of 39 at 4,096 still at every deeper
  size; no made or ring law called still early; 64 of 83 scoring laws still), with the frozen call's miss beside it.
  It put the still lattice at 1 in the score in force at 856 (gsd-law-score-9).
* `graph_scale_dynamics/resources/readings/small_world_criterion_1.json` (856): whether a law the catalogue calls a
  small world at one size is never made at a deeper one, and whether H31's region is one kind; its two numbers chosen
  on the baseline bundles and committed before the next bundle judges it (`tools/catalogue_reading.py`); the random
  reach it assumes is read by `tools/small_world_reach.py`.
* `graph_scale_dynamics/resources/readings/study_176_design.json` and `graph_scale_dynamics/resources/readings/study_176_criterion.json`
  (865, replacing 856's, which never ran): study 176, A's ten blind batches, the focus from its start and a seeded
  campaign filled from bundles, its criterion committed before its first start;
  `graph_scale_dynamics/resources/readings/study_176_first_ten.json` (856): the ten laws 856's map was to start from
  (`tools/map_first_ten.py` on the baseline bundles), read now only by its test.
* `graph_scale_dynamics/resources/readings/study_174_run_on.json` (864): the 193 laws `starts_alike` holds at 16,384 in
  174's bundle of 2026-11-25 09:59Z, each classed by the best reading of its starts there, and the 40 that read
  something, all lines or rings, which the Map page's "run them on" names (`tools/held_by_a_gate.py`).

## Outside this folder

The papers used are cited by arXiv id and the version read in `docs/RESEARCH_METHOD.md`, "The papers read", and
not kept in the tree, which is public. `calibration/seed_table.json`, the calibration table a host starts from (its
`calibration/probe_calibration.json` is the one in force, host state); `docs/origins/`, the operator's first models.
