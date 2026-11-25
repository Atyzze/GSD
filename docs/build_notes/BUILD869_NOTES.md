# Build 869: an import folder beside main.py, its bundles listed on the Map page to tick; the focus's settings folded away; each running law's group, and the focus's laws on Home

**Type: a feature build, asked for by the operator on 2026-11-25 at 15:08 to 15:18 (their words in `docs/HISTORY.md`).**
It may be applied to study 176's folder while it runs: no score, kind or decision of a law moves
(`tools/outputs_of_a_law.py --against` 865's record: 0 outputs changed). A seed reads a bundle and inserts its scoring
laws into the study's seeded campaign, as 865's seed does; nothing else is written.

## For the folders

**Study 176**: apply it and restart. An `import/` folder appears beside `main.py`, `var/`, `calibration/` and
`instance/`. Copy `study_174_2026-11-25T13-04-19Z.tar.zst` into it (174's folder keeps its bundles in
`var/reports/study/bundles/`), open Map, tick it under Seeds and press "seed from the ticked".

## The import folder (15:08, 15:11, 15:13)

"import folder would do think, next to var/calibration/instance ... thats where the archive goes and thats where the
server checks for imports and then the map page lists which it sees there and lets you select which to include, so
there is no uploading via the browser and not needing to set a path either, the folder is clearly listed with a button
that opens an explorer there". The Map page's Seeds panel, now the first under the Map's controls, names the folder by
its full path with "open the folder" (the host's file manager: `xdg-open`, `open` or Explorer) and "copy the path";
lists every study bundle in it, its `.tar.zst` as downloaded (a browser's `_tar.zst` too) or its unpacked folder, each
with its study, build, date, size, its scoring laws and regions, whether its science is this folder's (another's
cannot be ticked) and when it was seeded; and seeds the ticked ones (`operations/imports.py`; `do: seed`,
`bundles`, and `do: open_import` on `POST /api/focus`). A bundle is read once and remembered in
`var/import_index.json` until its size or time changes; one still being copied is listed as not readable yet. The
path box is gone; nothing in the folder is changed. `import/` is ignored by git.

## The focus's settings folded away (15:11)

"these ... input(??) fields at the top are confusing as hell, feels like a puzzle". The rings, confirm share, deep
laws, widest ring, inside share and the type count are in a closed "the focus's settings" section, each said in a line
of plain words; nobody needs them to run a study.

## Each running law's group, and the focus's laws on Home (14:24, 15:18)

"the now researching should have an extra colum or marker somewhere so we can see the split between which ones are
coming from the blind draw vs the focused group". Every law in Now researching carries its group: blind (A),
neighbour or seeds (N), depth (D), seeded, control; the heading counts them. "the zoned/focused laws should be
included in the fleet ladder": the study's view on Home now reads the focus's and the seeded campaigns beside its blind
batches (`dashboard_workers.batches`), so their laws are in Now researching, the fleet ladder, the landscape and the Top
100, and the group filter tells them apart. The ladder following every filter, and Home's four boxes as one, is 870.

## Smaller

A reload of `/map` opened Home; it opens Map.

## Verification

4037 passed in 1309.52s (3 lanes at once)
