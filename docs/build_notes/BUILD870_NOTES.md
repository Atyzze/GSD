# Build 870: the handover of the context that made 864 to 869, with what it read, what the operator decided and the plan from 871, so a fresh context starts from the repository alone

**Type: a handover, asked for by the operator on 2026-11-25 at 16:05 ("lets focus the next build to be a handover for
the new build agent context to start from, we've done plenty of good work, onto the next window! so 870 still here
please, which should be ready for 871 and beyond").** Only pages change: no code, no score, kind, gate or decision;
`tools/outputs_of_a_law.py --against` 865's record: 0 outputs changed.

## For the folders

Nothing to do: a folder on 869 runs the same on 870. Study 176 runs on in its own folder; study 174 is the operator's
to pause or run on.

## Where things stand

* **Pull requests**: 864 to 867 (#11 to #14) merged; 868 (#15) and 869 (#16) open, 869 built on 868 (it shows 868's
  changes until #15 merges); 870 is #17, built on 869. Each is the tree of the archive its gate wrote.
* **Study 176** runs since about 15:00, started by the operator on 867, then 869 applied. Its gates are 174's word for
  word (the two designs differ only in the focus, its groups N and D beside A, ten new search seeds and the seeded
  campaign). Seeded at 14:14Z from 174's bundle of 13:04Z (73 scoring laws, 72 new) and again at 14:56Z (0 new).
* **The zones run.** Read on 176's bundle of 15:09Z (`study_176_2026-11-25T15-09-14Z`, on 869): the 72 seeded laws
  were on their ladder, 48 in their base block (36 just sent from 1,024 to 4,096), 8 extending, 16 not yet started,
  their jobs waiting their turn behind the blind draw's queue; nothing held them. At 16:12 the zoned side ran 11, had
  172 queued and its deepest at 65,536. **One gap**: the focus was idle at 15:09Z (no law in focus, no depth
  contender), since it takes only laws that score in this folder (`focus.best`) and a score needs a reading at 16,384;
  it took the first seeded law that scored here, C11-G79 at 1, instead of the bundle's best (38 in 174). 865 meant a
  seeded law to stand on its bundle's score until read here, and did not make it so (871).
* **The second seed** of the same bundle (14:56:57Z, 0 new laws) should have been refused as nothing new (871).
* **Study 174** on 865: its bundle of 13:04Z is the latest. Its focus on C8-G2983 since 11:59Z, 47 neighbours, none past
  4,096; its depth campaign's five, one at 65,536.

## The operator's words of the day, and where each went

Their words are in `docs/HISTORY.md`; the builds' notes say how each was met.

* 11:06 to 11:10: no law is ever done (864); study 176 seeded from the map so far beside a blind draw, one bar of
  blind against zoned on Home (865); the engines in order, Rust, C, assembly, each timed on the same seed, then a
  shared effort once one node has proven the zone mapping (planned, below).
* 11:58 to 12:12: C2-G3187 is rings, a type, shown where DONE stood (865); scores relative to known types, a matrix
  of laws by types (planned); each term switched off to find a law's core (865); the phenotype as the shortest
  description of its sixteen charts, a null map, then new terms, the Ricci curvature in two forms first (planned).
* 13:11: the split as a slider, the focus's and the depth's lists, the earliest identification, one depth worker,
  "I cant tell whether work has started" (866); the depth seeker to the memory limit (planned, 873).
* 13:28, 13:34, 14:11, 14:16 to 14:22: the law page (867, 868).
* 14:23 to 14:29: study 176 tonight (it needed no build); the zoned laws in the fleet ladder (869); Home's four boxes
  as one, a consolidation checked against the main table (planned, 872).
* 15:08 to 15:18: the import folder, the settings out of sight, each running law's group (869).
* 16:02: the seeds as a selection, not an append-only list; the refresh button and "depth 1 worker" off the Map page;
  the seed map behind the admin token; the zones not running (planned, 871).
* 16:05: this handover.
* 16:12: the zones run after all (176's bundle); the second seed should have been refused; why more than a tenth of the
  compute on the blind draw, whose gates 174 tested: the slider at 90% focus, about 10 to 1 (recommended; it idles
  nothing, a group with no work leaving its slots to the others).
* 16:15 to 16:34: every seeded law explorable on its law page, each law named by a code across all the data sets,
  earlier rather than later; first BnCnGn with the build, then, at 16:34, SnCnGn with the study ("build numbers can
  arbitrarily change trivial/nothing in the code ... whereas study is very different and can contain multiple
  builds"), its fingerprint the identity underneath (871).
* 16:19 and 16:20: the study bar in core-hours, not laws, with a third part for the depth seeker and a fourth for the
  system's own use; a second bar of memory held over time; the fleet ladder's header without decimals (871, 872).

## What this context read, worth keeping

1. **The kept share is a dimension ratio** (14:11; `research/reach.kept`): log(R / R_random) / log(R_start /
   R_random), 0 a random wiring, 1 its start; above 1 a lower dimension, below 0 denser than a random wiring. As reach
   grows as N^(1/d), at large N it tends to d of the start over d of the chain: C2-G3187's chains, rings, read about 7
   (tesseract), 5 (the cubic lattices) and 3 (the 2-D ones) at 65,536, falling towards 4, 3 and 2. The operator's
   reading (14:16): 1 kept dimension, higher a reduction, lower an increase, negative denser than random.
2. **The two run plots differ** (13:34): the energy gap is how far apart the chains from different starts end; the
   checks are the stopping rule's reading inside each chain. A law can be at rest on every chain and still apart.
3. **The rainbow curves** (13:28): one line a seed and a start, both axes logarithmic, a power law a straight line
   whose slope is the dimension; at 64 every start saturates alike, at 65,536 they fan out (a random start's walk
   falls to the 1/N floor, an expander; a lattice keeps a power law).
4. **174's bundle of 13:04Z** (`study_174_2026-11-25T13-04-19Z`, 180 MB): no `run_on` decision, so the 40 held laws
   never ran on, and every one of them is "a line or a ring" (`study_174_run_on.json`). Its let-through ledger
   (`gates_ledger.json`): disconnected at 1,024 580 clean in a row, empty at 1,024 376, starts alike at 4,096 208, none
   missed; empty at 4,096 6 missed of 62 judged and disconnected at 4,096 7 of 96, the two leaking gates. Empty and
   disconnected never confirm (the design pins them at a tenth, `gate_shares`, so `let_through.share` returns their
   own share); why starts alike at 4,096 still reads "testing" at 208 clean is not read yet.
5. **176's bundle of 15:09Z**: the same science as 174's (the seed checked it); work groups A 28%, N 66%, D 6% at the
   slider's 70%; the fleet ladder's header reads "3.0049875311720697 seeds x 8 starts" once campaigns of 3 and 9 seeds
   are merged (the S campaign runs more seeds), a mean shown unrounded.
6. **How 174's 72 scoring laws passed its gates**: mostly where the gate only records (`no_steady_chain`,
   `kept_shape`, `cut`), a handful let through `empty` and `disconnected` at a tenth; none by `run_on`.

## The plan from 871

In `docs/ROADMAP.md`, "Planned builds, in order", "From 870"; the first in `docs/agent/NEXT_BUILD.md`. In short:
871 the seeded laws in the focus on their bundle's score, a bundle read twice refused, the seeds as a selection, every
law named SnCnGn and every label a link, the Map page saying what the focus does; 872 Home's four boxes as one, its
study bar in core-hours and a second in memory held, each with the depth seeker's and the system's parts; 873 the depth seeker to the memory limit; then the neighbours read at the earliest
identification, the build numbers in words, the engines' diet (Rust, C, assembly, timed on 176's seeds), the lexicon
and the matrix of laws by types, the phenotype and the null map and new terms, study 177 on the gates learned, and the
shared effort.

## How this context worked, for the next

* **A release** runs as the user `claude`: `su claude -c "setsid nohup bash release<N>.sh &"`, the script sourcing a
  prefix with `GSD_POSTGRES_SYSTEM_BIN`, `GSD_VOLATILE_DIR` and the venv, then `python3 tools/package_release.py
  --output <dir>`; the full lane takes about 22 minutes and stamps `GATE_RESULT` in the build's notes. The tree is
  read by the gate while it runs: work on the next build in a second clone and bring it over after the release.
* **A pull request** is one signed commit on `main` (or on the open build it follows) whose tree equals the released
  archive's (`git read-tree -u --reset <released commit>`), pushed with `git -c push.negotiate=true push`, opened with
  `gh api repos/Atyzze/GSD/pulls`.
* **A page is looked at, not only tested**: Playwright's Chromium renders `candidate.html` or `index.html` with the
  API answered by `page.route` from the smoke tests' fixtures; a screenshot and a scripted pointer catch what the node
  smoke tests cannot (a tooltip behind the chart, a table wider than its numbers).
* **A bundle is read in its own folder**, by `python3 -I` scripts over `tables/*.ndjson.gz`, `study.json`,
  `focus.json` and `gates_ledger.json`.

## Verification

4037 passed in 1277.42s (3 lanes at once)
