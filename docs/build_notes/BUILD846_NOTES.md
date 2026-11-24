# Build 846: the score's mended rules are judged twice on known answers and kept beside the score as a candidate, and the worker count changes while a study runs. It may be applied to study 174's folder: it changes no decision and no score.

**Type: a reading and a control, asked for by the operator on 2026-11-23 at 11:21 ("if you say the current scoring is
off ... then that is of course the thing we need to do first") and 11:48 (the worker count on the System page).**
Changed: `main.py` (the run loop calls `worker_count.tick`; `--total-slots` is the most a folder holds),
`graph_scale_dynamics/services/api/campaign_manager.py` (`fleet_workers`), `graph_scale_dynamics/services/api/overview.py`,
`graph_scale_dynamics/resources/ui/app.js` and `index.html` (System, Workers),
`graph_scale_dynamics/research/score_known_answers.py`, `research/probes_known_answers.py`,
`research/known_structures.py` (`cycle_soup`), `tools/score_known_answers.py`, `tools/score_list.py` (`--candidate`),
New: `graph_scale_dynamics/scheduling/worker_count.py`, `graph_scale_dynamics/research/score_candidate.py` and its
trained reach rule `graph_scale_dynamics/resources/readings/score_candidate_reach.json` (the margins in force,
`score_margins.json`, did not move),
criteria `score_known_answers_criterion_4.json` and `_5.json` with their measured rows, judged readings and pages, each
committed before any structure it names was built or read (git: d7f5a64 at 10:32Z, 963a6bf at 11:20Z); tests
`tests/unit/test_the_worker_count_changes_while_running.py`, `tests/unit/test_the_score_reads_what_settled_at_its_own_scale.py`,
`tests/scientific/test_the_score_settles_on_known_answers.py`, `tests/ui/dashboard_smoke.js`. The manifest of committed
readings, `tests/fixtures/committed_readings.json`, gains the eight new files and moves no line. Nothing under
`decisions/`, `scaleflow/`, `measurements/`, `engine/`, `engine_rs/` or `observability/` moved; no frozen source moved;
the schema did not change. Against 845's record (`tools/outputs_of_a_law.py --against`) 0 outputs moved, and every one
of study 174's 27,571 decisions in its first bundle replays (`tools/replay_bundle.py`, 0 differ).

## What the review found, and what the score does about it

The review of 845 and of 174's first bundle (2026-11-23 09:52Z) found three ways the score settles a reading that does
not describe the graph: seeds still relaxing at their cap (53 of 61 finds score on rungs the decisions call never
equilibrated), a largest piece of 14% of the graph (a soup of cycles), and laws whose reach grew far slower than the
dimension their probes read (a strip reads 2, grows as a line). The candidate (`research/score_candidate.py`,
`gsd-law-score-8`) counts a seed only when its rung settled or its chain's last chunk changed no edge, reads a chain
only where its largest piece is half the graph, and lets a step settle only where the reach grows as the dimension
read (q 0.2, twice the widest excess of the calibration table's lattices, half a hop at each end, two standard errors)
and the next step does not break that.

## Criterion 4: missed, its strip prediction wrong

Seeds 51 to 53, 201 reads (`docs/readings/score_known_answers_4_judged.md`). K1 to K4 held (every exact structure
settles, nothing that must refuse does), S3 held (a soup under half the graph earns nothing). S1 missed on 5 of 9:
a strip 16 wide and tubes 8 by 8 and 16 by 16 are lines at 4,096 to 65,536 nodes, the probes read 1.0 to 1.2 and the
reach grows as 1.0, so they settle, correctly, as lines; the criterion had said no strip may settle. S2 missed once: a
tree of paths of 8 settled at d 1.30 from 4,097 to 16,385, and its reach then grew as 3.0 at the next size. By its
rule the score stayed as it was until a criterion written fresh passes.

## Criterion 5: written fresh, missed on trees only

Committed before any read, on seeds 61 to 63, new strips (24, 40, 56 wide), tubes (6 by 6, 12 by 12), trees of paths
of 4, 8 and 16 and two soups, with one rule added (the next step) and S1 restated (a strip settles only as a line), 219
reads, 31 minutes (`docs/readings/score_known_answers_5_judged.md`). K1 56 of 56, K2 11 of 11, K3 16 of 16, K4 16 of 16,
S1 9 of 9 (the strips 40 and 56 wide, which the score in force settles at d 2 with 4 or 5 points, earn nothing), S3 3
of 3. S2 missed 4 of 6: trees of paths of 8 and 16 settle at d 1.12 to 1.38 at both pairs, their reach growing as 1.6
to 2.0, inside the allowance because the reach of three random trees spreads widely. The score in force settles them
the same. A random tree's spectral dimension is 4/3, so d 1.36 is what the probes should read there; the "ring" label
below 1.5 is what is wrong for a tree. Twice a prediction about a fooling case was the thing that was wrong
(`docs/LESSONS.md`). By criterion 5's own rule the score in force stays `gsd-law-score-6`; putting the candidate in
force is put to the operator (`docs/ROADMAP.md`, "Questions").

## What the candidate reads on study 174's first bundle

`tools/score_list.py <bundle> --candidate`: a bundle carries no seed's settle class, so on it the candidate reads its
floor, its scale and its next step. 61 laws score above zero (the score in force: 63), 4 with every point, as before;
what moves is which points settle. 35 drawn laws settle at least one probe under the candidate, none frozen, every one
from a lattice start (22 bcc, 3 triangular, 3 cubic, 3 fcc, 2 square, 2 tesseract; 26 to 65,536, 9 to 16,384); 16 more
only read at two sizes, 7 are frozen lattices (score 1) and 3 are the standing controls. Of the 35, report 23 calls one
rung pair settled for one law (`0fa748ea2652`, cubic, at rest); the rest relax at their cap or are metastable there,
which the candidate reads seed by seed only in a folder. These 35 are 847's holders.

## The worker count while a study runs

System, Workers: a number and **set** (the admin link), or **let the ramp decide**. The count is the flag
`compute_worker_target`, from 1 to one a hardware thread within the connections the folder's PostgreSQL was sized for
(`compute_worker_most`, 32 on the research host, or `GSD_MAX_WORKERS`); the supervisor reads it every half second and
the ramp stands aside while it is set. A lower count sends SIGTERM to the executors above it at once: the child saves
its seed where it is (the stop file), the rung goes back to the queue uncharged (`release_job` gives the attempt back),
a slot that stays resumes it from the save, and an executor still alive after the stop grace is killed. A higher count
restarts held executors once they have ended and starts new ones. A pause and a resume keep the held ones held. The
tick is tested on fake processes (stop, reap, kill after the grace, restart, spawn, pause, hand back), the route on its
bounds, and the panel in the dashboard harness.

## For the folder running study 174

846 changes no decision and no score, so 174 may take it in its own folder for the worker count; the supervisor
changed, so the folder runs the same command once more after it is applied, and its seeds resume from their saves.

## Verification

3875 passed in 1551.43s (3 lanes at once)
