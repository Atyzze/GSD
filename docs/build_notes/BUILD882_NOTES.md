# Build 882: the dex, and the focus on scoring laws first

**Type: a data build, on the operator's words of 2026-11-26 14:21 and 14:55 ("continue working until we have our dex
functionality working so that our new studies can be seeded with the top scores properly from the past studies [...]
for now we still need to support the old study export bundles, but start working on a new export archive that is
fully dex compatible/designed from the start and isn't bothered with containing any reporting but is just meant as
data transfer to append/verify-against the growing dex") and 12:55 (a law of another science "simply [added] to the
list of laws to test").** No score, kind or decision of any law moves, no frozen source and no schema; the science
is 881's (f5c045e195fdb4d2), so every bundle of 176 and 174's of 2026-11-25 13:04Z seed with their scores. It may be
applied to 177's running folder.

## For the folders

* **Study 177**: apply 882 and restart. The folder writes its first dex into `export/` at once, then every hour. Put the dex
  that came with this build (`dex_176_177_<utc>.tar.zst`, 176's 130 scoring laws with their chains, 72 of them
  carrying 174's codes and scores) into `import/`: within a minute it is read in, and the focus sets the outlier
  S177-C4-G10 aside and takes 176's best law (score 38) at its next step, the depth worker leaving the outlier for it.
  Older study bundles go into `import/` too, ticked and synchronized on the Map page as before.
* **Every next study**: put the newest dex from the last folder's `export/` into the new folder's `import/`.

## What changed

1. **The dex** (`operations/dex.py`, `gsd-dex-1`; `docs/ARCHITECTURE.md`, "The dex"): a data-only archive of every
   law that scores, its spec, every code it was known by, every reading of its score with the study and the science
   that read it, its chains (what a run again must reproduce to the bit) and its rungs, the mapped regions, and the
   checks of its runs again. It reads old study bundles and dexes alike, merges them by law, and ranks them by the
   score under its own science; `top` is the first hundred. From a running folder it adds the folder's own scoring
   laws, every seed record's laws and the chains of all of them from the blob store
   (`study_tables.chain_rows(..., laws=...)`), and checks each chain run here against the one recorded for it.
2. **A folder writes its dex** into `export/` every hour (`controller.dex_pass`, `dex.keep`, the first at once) and when the Map page's
   "write the dex now" is pressed; the Seeds panel says when the last was written, how many laws, how many
   verified here and how many differ.
3. **A dex seeds a study** (`study_seed.read` through `dex.seeding`): a dex put into `import/` is read in by the
   controller within a minute (`dex.absorb`); the import folder lists dexes beside bundles.
4. **Another science brings its laws alone** (`study_seed.seed`): a dex or bundle read by another science is no
   longer refused; its laws go into the seeded campaign, each run here from nothing, with no score and no region
   carried (`laws_only` in its record), and an untick lets them go as any seed's.
5. **The focus on scoring laws first** (`focus._chosen`, `set_aside`, `depth_restart`): 880's outliers came "once
   every scoring law is mapped", which holds when no law scores at all, so 177's focus took an outlier sixteen
   minutes after its start (S177-C4-G10: d_V 3.5 at 1,024 on three seeds that all ran out of their budget before they
   settled). An outlier now comes only once the study has a scoring law and every one is mapped; one in focus is set
   aside the moment a scoring law is free, and the depth worker leaves it for a new depth campaign. The Map page's
   line says why the law in focus was taken (its score, its score in a dex or bundle, an outlier's reading, or the
   operator's choice).
6. **`tools/dex.py`**: `make` merges dexes and bundles on a disk into one dex; `show` lists one best first.
7. **A law's code is dashed** (the operator, 14:55: "S178-C11-G4766 instead of S178C11G4766";
   `operations/law_code.code`, `resources/ui/system.js` and the law page): every page, table and dex writes
   S178-C11-G4766, or S176-C11-a60c2358 where no graph has run. The old form is read as before (`law_code.parse`,
   the Explorer's search), and an old code in a focus's state, a seed record or a dex is written again dashed
   (`law_code.upgraded`, keeping its own study).

## What the 177 bundle of 13:10Z read

* 45 minutes in, no law of the blind draw read past 4,096 and none scored; the focus was on the outlier above.
* **The engines, old against new**, per chain of the blind draw, 176's bundle of 10:21Z (crate 0.840.0) against 177's
  (0.875.0): work a second 1.04, 1.04 and 0.99 times at 64, 256 and 1,024; a seed's peak memory 0.99, 0.99 and 0.95.
  At these sizes a run's fixed cost hides the graph; 875's gains are at 65,536. 177's 592 chains at 4,096 are its
  fastest laws only and are not read. Seeding 177 from the dex runs 176's laws again on their seeds up to 65,536, the
  same chains on the new engine, which is the comparison seed for seed.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a bundle's scoring laws and its earlier study's seeds are carried, with their chains, written and read back | `tests/unit/test_the_dex_carries_every_scoring_law_and_checks_a_run_again.py`, the first |
| parts merge by law; a score of another science does not stand; its laws come alone | the same file, the second |
| a run again agrees to the bit or says where it differs | the same file, the third |
| a dex in the import folder is listed as a dex | the same file, the fourth |
| a dex dropped in seeds the study once, the focus takes its best law, the study's dex carries it on, hourly and on the button | `tests/integration/test_a_study_is_seeded_from_a_dex_and_writes_its_own_postgres.py`, the first |
| no outlier before a law scores; an early one yields and the depth worker leaves it | the same file, the second |
| the dex reads the chains of its own laws alone | the same file, the third |
| a bundle of another science brings its laws alone | `tests/integration/test_study_176_starts_its_blind_draw_its_seed_and_its_focus_postgres.py`, the last |
| 176's three bundles make a dex of 130 laws, 72 with 174's scores | `tools/dex.py make` on the bundles of 10:21Z, 10:38Z and 177's of 13:10Z |
| codes are dashed, the old form read the same | the same unit file, the last; `tests/ui/dashboard_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 880's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* The study bundle stays as it is, reports and all; the dex is beside it. Naming the bundle a map part, and a panel of
  what each worker is doing and why, are the next builds' (`docs/ROADMAP.md`, "From 881").
* A dex holds the laws that score; a law that never scored anywhere is not carried.
* The checks of a run again are filed in the next dex the folder writes, not shown law by law on a page yet.

## Verification

4198 passed, 41 skipped in 1123.32s (3 lanes at once)
