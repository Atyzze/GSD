# Build 871: the seeded laws in the focus on their bundle's score, a bundle read twice refused, the seeds as a selection, every law named SnCnGn, and the Map page saying what the focus does

**Type: a feature build on the focus, the seeds, a law's name, the Map page and the fleet ladder's header, asked for by
the operator on 2026-11-25 from 16:02 to 16:34 (`docs/HISTORY.md`) and made on their word at 17:12 ("make the next
build please").** No score, kind, gate or decision of a law moves: `tools/outputs_of_a_law.py --against` 870's record
on the untouched tree: 0 outputs changed. Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or
`engine_rs/` moved; no schema change; no frozen source. It may be applied to a running folder.

## For the folders

* **Study 176**: apply 871 to its folder and restart. 174's bundle of 13:04Z, seeded twice before (14:14Z and 14:56Z),
  is now one ticked row on the Map page. Its 72 laws' bundle scores were not recorded law by law before 871, so press
  **synchronize** once with that bundle still in `import/`: it reads the bundle again for each law's score and code,
  inserts nothing twice and rewrites nothing measured. Within a minute the focus takes the bundle's best law (38 in
  174) and the depth seeker its best five, each on its bundle's score until this folder reads it at 16,384. The line at
  the top of the Map page says so.
* **Study 174**: nothing needed. Applied, its pages name its laws S174CnGn and its next bundle carries each law's code
  in `tables/laws`, which a seed then shows as the law's origin (S174C2G3187 rather than S174C2-ab12cd34).
* **In 176's next bundle, watch**: `focus.json`'s `current` with `standing: bundle` and its `origin`, the depth
  campaign's laws the seeded ones, and `tables/laws` with a `code` on every row.

## What changed

1. **The seeded laws in the focus** (`operations/focus.py`, `operations/study_seed.py`). A seed records each scoring
   law's bundle score and code (`seeded[].laws`). `focus.best` takes a seeded law on that score until this folder has
   a decision on it at 16,384 or past (`focus.read_here`), and on the folder's own score after; a law the folder reads
   as 0 leaves the lists then. The lists, the queue and the depth table carry the origin ("38 in study 174's bundle").
   Two guards keep a law in focus from being judged before it is read: its neighbours wait for its own kind at 16,384
   (`advance`), and the depth seeker compares only sizes its own campaign has read, or all once it is decided
   (`depth_of`). Before 871 a law in focus without a kind would have ended unconfirmed as soon as its ring at 0.1 was
   read, every neighbour counted as another kind; blind laws are read by the time they score, so none of theirs moves.
2. **A bundle read already is refused** with its reason: "read already" (the same bundle in the map), "identical to"
   (another name, the same laws table by sha256) or "adds nothing" (every scoring law here and no region to add or
   widen). The seed records are one per bundle (`study_seed.records`), so the Map page shows one row.
3. **The seeds as a selection** (`imports.synchronize`, `study_seed.release`, `study_seed.choose`). The Seeds panel is
   one list of the `import/` folder's bundles and of any bundle read from a path; a tick means its laws and regions
   are in this study's map. **Synchronize** reads in what is newly ticked and lets go of what is unticked: its laws
   leave the focus's lists and the depth seeker (the law in focus, if one, is set aside), its regions leave the map
   (kept aside, restored when ticked again), and every reading already taken stays. Each seeded region names the
   bundles that gave or widened it (`sources`); it leaves the map when none is ticked and no law mapped here joined it.
   A line under the list: a merged set is a new bundle, made on Reports.
4. **Every law named SnCnGn** (`operations/law_code.py`): the study, the campaign and its first graph's number, for
   example S176C11G79; the fingerprint stays the identity underneath. Where no graph has run, the study and campaign
   and the id's start (S176C15-ab12cd34); a campaign with no study keeps C11-G79. Read the same way by the focus's
   labels (a running folder's labels are renamed as they are read), the law page's title and its tab, the Top 100, Now
   researching, the Explorer and every label on the Map page, each a link to the law's page; the Explorer finds a law
   by S176C11G79, s176-c11-g79 or C11-G79. A seeded law shows its origin's code and score beside its own ("from
   S174C2G3187, 38 there"), on the Map page and on its law page. The bundle's `tables/laws` carries `code` and
   `graph` on every row. A bundle made before 871 has no graph numbers, so its laws' origin is S174C2-ab12cd34.
   `/api/campaigns` names each campaign's study (moved out of `build_handler`, 13 lines shorter).
5. **The Map page says what the focus is doing and why**, one line at its top: in focus and on what score, waiting for
   its own kind at 16,384, idle because no law scores here, or idle because every scoring law is mapped, with the depth
   seeker's laws and deepest size. The refresh button is gone (the page reads itself every 4 s), and so is "depth 1
   worker" beside the slider.
6. **The fleet ladder's header in whole numbers**: "a law at a size = 3 seeds x 8 starts = 24 graphs", and where the
   merged campaigns differ "3 to 9 seeds x 8 starts = 24 to 72 graphs" (`study_scope.merge_ladder` keeps the least and
   the most, never the mean).

## Acceptance, line by line

| the operator's acceptance | the test |
|---|---|
| a folder seeded from a bundle focuses on its best seeded law at its next step | `tests/integration/test_a_seeded_folder_focuses_on_its_best_seeded_law_postgres.py`, the first test |
| a bundle seeded twice is refused the second time | the same file, the second; `test_study_176_starts_..._postgres.py`, its third seed |
| a bundle unticked and synchronized leaves the lists and the map, its readings kept | the same file, the third (and ticked again, back) |
| every law's code read the same on every page and in the bundle | the same file, the fourth; `tests/ui/dashboard_smoke.js`, the SnCnGn and Map page checks |
| no score, kind or decision of a blind law moves | `tools/outputs_of_a_law.py --against` the record written on 870's untouched tree: 0 changed |
| the full lane green | the Verification below |

Every decision of 174 replaying is not read here: no bundle is in the tree, and nothing under `decisions/` moved.

## What it does not do, and a question

* **A let-go law's own runs go on.** Synchronize takes it out of the focus and the depth seeker and its region off the
  map; its ladder in the seeded campaign, and any depth run already queued, go on to their gates, since stopping a law
  by word is a decision and this build moves none. Recommended: let them run, as a tick brings them back at once; the
  other way is a hold by word for let-go laws, a `decisions/` change of about a build
  (`docs/ROADMAP.md`, "Questions for the operator").
* **The pull request**: this session was not allowed to push to `github.com/Atyzze/GSD`, so the archive is the
  delivery and the branch `build-871` is described for the operator to open (`docs/agent/HANDOFF.md`).

## Verification

4042 passed in 1710.56s (3 lanes at once)
