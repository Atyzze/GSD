# Build 857: one set of filters for Home. Every law says its kind, its group, its batch and its place on the map, and the landscape, the Top 100 and the fleet ladder show only what the filters keep

**Type: a build of the dashboard, asked for by the operator on 2026-11-24 at 17:51 ("putting the filters in the middle
is exactly what I want, above fleet ladder, under macro landscape and let top100 unknowns drape down next to it")
(`docs/HISTORY.md`).** No score, kind, gate or decision moves; nothing under `decisions/`, `scaleflow/`,
`measurements/`, `engine/` or `engine_rs/` changed.

## For the folders

Any folder may take it. On Home, under the macroscopic landscape and beside the Top 100, a **Filters** panel: every
kind of the catalogue with its count, each ticked on or off; one kind chosen from a list; the map (laws in no region
yet, in a region being mapped, in a known region); the group (A blind, B map); the batch; settled or not. The
landscape draws only the laws the filters keep, the Top 100 lists the best of them from every law of the landscape
(not only the hundred best), and the fleet ladder says how deep the laws kept went; the Now researching box is not
filtered. With no filter on, every box reads as it did. The score boards are read again once (their contract moved),
so for the first minutes after a restart a law may show "not read yet" until the board has scanned it.

## What every law now carries

* **Its kind**: the score board keeps each law's catalogue kind at its deepest size beside its score, for every law
  it scans, scored or not (`score_board`, gsd-score-board-2; `decision_store.law_score` reads it with
  `law_kind.kinds` from the same rungs it scores). A law below 1,024 is not scanned and reads "not read yet".
* **Its group and batch**: its campaign's `study_design.group` and id.
* **Its place on the map**: the region it belongs to and whether that region is being mapped or known
  (`study_map.regions_of_laws`).

`landscape_worker.marked` puts the four on every point of the landscape and every law refused a reading, before the
Top 100 is taken, so the study scope's points carry them too.

## What moved

Against 856's record (`tools/outputs_of_a_law.py --against`), 0 outputs moved: the outputs of a law are read below
1,024 and carry no board. The board's contract (gsd-score-board-2) makes every folder's boards scan again once,
and the landscape's inputs stamp (gsd-landscape-inputs-2) now watches the map's state beside the boards, so a
region marked known redraws Home on the next build of the landscape.

## What the ladder can and cannot filter

The fleet ladder's columns count the fleet's live work by size (running, queued, analysing, stopped), which is not
yet tied to a law's kind; with a filter on, a line above it gives the laws the filters keep by their deepest size,
and the live counts stay every law's. Filtering the live counts by kind needs the ladder's rows read per law on the
server (`observability/rung_distribution.py`); it is offered as a later build, not done here.

## Verification

3952 passed in 1278.44s (3 lanes at once)
