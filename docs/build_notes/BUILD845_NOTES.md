# Build 845: the study's map of ten batches arrives, and the ten batch buttons stay on one row. It may be applied to study 174's folder: it changes the dashboard only, no decision.

**Type: a fix to 844, the stable build, asked for by the operator on 2026-11-22 at 17:13 with a picture of Home on
study 174 stuck on "loading campaign study: its overview is here, its landscape is on its way".** Changed:
`graph_scale_dynamics/services/api/study_scope.py`, `graph_scale_dynamics/resources/ui/app.js`,
`graph_scale_dynamics/resources/ui/system.css`; tests `tests/unit/test_home_reads_every_batch.py`,
`tests/ui/dashboard_smoke.js`. Documents: `docs/agent/NEXT_BUILD.md` (846), `docs/agent/HANDOFF.md`,
`docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`, `docs/HISTORY.md`. Nothing under `decisions/`, `scaleflow/`,
`measurements/`, `engine/` or `engine_rs/` moved; no frozen source moved; the schema did not change. Against 844's record
(`tools/outputs_of_a_law.py --against`) no output moved.

## Why Home never showed study 174's map

The study's map (All batches) is merged from each batch's own landscape once every batch has one. The API builds one
landscape at a time, and a landscape is rebuilt when it is older than 16 seconds. On every poll of the page the study
scope went through the batches in order and gave the one slot to the first batch that was missing **or** stale, so
batches 1 and 2, stale again 16 seconds after they were built, took the slot back each time it came free, and batches 9
and 10 were never built. The map waited for them for ever. Study 170's five batches had fitted inside the 16 seconds;
174's ten do not. Now a batch that has no landscape yet is built first, then the one built longest ago
(`study_scope.Scope.landscape`). `test_a_batch_never_built_is_built_before_one_gone_stale_so_ten_batches_all_arrive`
fails on 844's code (batches 1 and 2 rebuilt for ever) and passes on 845's. While the map is on its way the line says
how many batches have theirs ("7 of 10 batches read").

## One row of ten

The batch buttons on the study's card (`.draw-batches`) no longer wrap: a button is narrower (16 px at least, 3 px
either side) and the row keeps to one line, so batch 10 sits beside batch 9.

## For the folder running study 174

845 changes what the dashboard shows, not what a law decides, so 174 may take it in its own folder, as a build is
applied there; its running seeds save their chunk and go on. Its decisions, its criterion and its reading are 844's.

## Verification

3847 passed in 1320.43s (3 lanes at once)
