# Build 833: the consolidation. The notes of 805 to 822 are folded into the history, every standing page was read against the code and made true, and the roadmap holds only what is open. Nothing a fleet runs changed: study 171 stays on 830, nothing to apply.

**Type: consolidation (due, 17 builds since 815; `docs/ROADMAP.md`, "Build cadence"), with study 171 running on 830.**
Changed: `docs/HISTORY.md` (two eras for 805 to 822), `docs/ROADMAP.md` (pruned: the done builds out, the planned
builds renumbered from 171's reading, "What still carries the past" to its last three rows, an answered review item
closed; 422 lines to 365), `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/OPERATIONS.md`, `docs/TOOLS.md`,
`docs/LESSONS.md`, `docs/RESEARCH_METHOD.md`, `docs/readings/README.md`, `docs/WHERE_WE_ARE.md`,
`docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`. Out: `docs/build_notes/BUILD805_NOTES.md` to
`BUILD822_NOTES.md`, 18 files, each in its own build's archive. No file under `graph_scale_dynamics/`,
`engine_rs/src/`, `tools/` or `main.py` changed (`tests/unit/test_build_cadence.py`); the schema did not change.

## The notes folded

The history's eras gain two: the installed table, no clock and study 169 (805 to 815), and the old evidence judged
again, studies 169 and 170 and the cleanup begun (816 to 822). `docs/build_notes/` keeps 823 to 832 beside 833's. The
standing decisions are never folded.

## What reading the pages against the code found

Every backticked path and module name in the standing pages was resolved against the tree, and every page read
against the others. Fixed where the page and the code disagreed:

| page | what it said | what the code says |
|---|---|---|
| `docs/DECISIONS.md` | the certificate compares every pair of chains; "the probes measure the three graphs grown from empty" | since 781 every chain that ran decides on its own and only the twins are compared; every chain not at the cap is read |
| `docs/DECISIONS.md`, `docs/OPERATIONS.md`, `docs/RESEARCH_METHOD.md` | a batch learns its gates from its own decisions | since 832 every batch learns from every batch's laws at the same fixed points |
| `docs/DECISIONS.md` | a new gate lets half of what it would park through | under 784's rule a new gate starts at 10%, as every gate |
| `docs/ARCHITECTURE.md` | the engines' one count of work "decides nothing" | the budget weighs its parts (806) |
| `docs/ARCHITECTURE.md` | the stream labels are held by a test removed at 822; the fingerprints read `research/growth_reading.py` and carry `sources_carried` | neither exists; the labels live in `engine/chains.py` and an outputs record names any moved draw |
| `docs/ARCHITECTURE.md` | the blockers' sizes (`engine/engine.py` 102,343 bytes, `run_simulation` 400 lines, and the rest) | measured again: `engine/engine.py` 63,161 bytes, `run_chain` 350 lines; every bound as the ratchet counts it |
| `docs/ARCHITECTURE.md` | a watchdog kill is a defect; the ladder's "time per run" | no watchdog since 806; "time per seed" since 820 |
| `docs/OPERATIONS.md` | an analysis given back with "the time limit and two hours"; a design "or growth plan"; start on "the build that read that bundle" | the repair gives back only a memory stop; no growth plan since 786; a section that no longer exists |
| `docs/RESEARCH_METHOD.md` | no data before 167; the pilots' mean degree in [0, 16] | no data before 169; the pilots' cap is 32 |
| `docs/TOOLS.md` | the outputs record grows a law "from four of the eight starts" | five: the chain from empty and four given starts |
| `docs/agent/HANDOFF.md` | the score `gsd-law-score-4`, a changed lattice start 1 | `gsd-law-score-5`, a changed lattice start 0.6 |
| `docs/readings/README.md` | studies 167 and 168 in the register; 19 committed inputs unnamed | the register holds 169 to 171; each input named with its build |

Sentences about things that left the tree (the window cut's replay, the extrapolation in N, the null atlas, the salt
ledger, the growth study, older criteria) were deleted rather than qualified, and the lessons' cases no longer cite
removed modules.

## Found, and left for a build that may touch code

* `graph_scale_dynamics/resources/readings/controls_criterion_5.json`, study 159's controls, read by two tests only:
  the cleanup missed it. Out at 834, its tests written on criterion 2.
* `graph_scale_dynamics/resources/readings/studies.json` says study 171 is "not started": written as it stands at 834.

Both are in `docs/ROADMAP.md`, "What still carries the past", and in `docs/agent/NEXT_BUILD.md`.

## What moved

Against 832's record (`tools/outputs_of_a_law.py --write` on the untouched 832 tree first): **0 outputs**. The table's
lock as at 828.

## For the operator

Nothing to apply: study 171 stays on 830 with auto extend. Send its bundle when you want it read.

## Verification

3703 passed, 2 skipped in 1215.41s (3 lanes at once)
