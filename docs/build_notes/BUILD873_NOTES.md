# Build 873: the depth seeker to the memory limit

**Type: a feature build on the focus's depth seeker, the decision engine's operational gates and a seed's save, the
operator's 2026-11-25 13:11 ("always just 1 worker thread responsible for always pushing the memory limit to the system
max (+ its free buffer zone ofc) but automatically testing how far N is feasible/safe to run without getting oom
killed"), made on their word of 23:25.** No score, kind or decision of a blind law moves: the new rule acts only on a
law the focus wrote down in the depth campaign; `tools/outputs_of_a_law.py --against` 870's record (unchanged through
872): 0 outputs changed. No schema change. It may be applied to a running folder; read "For the folders" first.

## For the folders

* **Study 176** (and any folder whose focus began before 873): at the focus's first step on 873 the depth seeker moves
  to a new depth campaign whose ladder runs to 4,194,304; the old one is paused with every reading kept, and the five
  contenders run again from 64 there (the depth seeker always reran them from 64). Its cost is the contenders' climb
  back to where they were, on its one worker.
* Nothing to press. The Map page's depth table gains a column, "memory ceiling".

## What changed

1. **The depth ladder open to 4,194,304** (`focus_plan_1.json`'s `depth.beyond`: 262,144, 1,048,576, 4,194,304). A
   focus begun on 873 has it from the start; an older one is renewed once (`focus.renew_depth`, its event
   `depth_renewed`, the old campaign in the state's `depth_before`).
2. **A size priced from the law's own peak growth** (`operations/depth_reach.py`): the law's peak memory at each size
   in the depth campaign (its attempts' `peak_rss_bytes`), the growth between its two largest sizes read as a power of
   N held between linear and quadratic, the next size's peak that times 1.1. The focus's step compares it with the
   host's reach (`scheduling/memory_hold.reach`: memory available, what the running seeds hold, the scratch that can
   move, less the free 10 GiB the host keeps), and a size past it is written down once (the flag `memory_ceiling`).
3. **The law settled at its memory ceiling** (`decisions/memory_ceiling.py`): the decider reads the written entries as
   it reads the operator's run-on list, and a decision that would buy that size or a larger one becomes
   `stop memory_ceiling`, parked, its reason the size it reached and the bytes the next would need; the entry goes
   into the decision's inputs, so `decisions/replay.py` replays it. A new operational gate, a limit and not a verdict
   (no let-through), in `docs/DECISIONS.md`'s table and the gates map (40 streams).
4. **The seed's save at 1,048,576 inside the stop's grace** (`artifact_store/resume_state.py`): a saved seed's long
   lists of whole numbers and of pairs (its chains' edges) are written packed, 32-bit where they fit, inside the same
   gzip JSON, and read back to the very lists plain JSON gave; a save made before 873 still reads. Here 400,000 edges
   save in about a third of plain JSON's time, so eight chains of 1,048,576 nodes at mean degree 32 save in about a
   minute against the stop's 120 s, where plain JSON took about 5 minutes (870's plan note).
5. The Map page's depth table says each contender's ceiling: "settled at N=262,144: N=1,048,576 needs 17.6 GiB,
   12.0 GiB reachable", its mouse-over the sizes it was priced from and the growth.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 872) | the test |
|---|---|
| the next size priced from a law's own earlier peaks, refused past the reach less 10 GiB | `tests/unit/test_the_depth_seeker_reaches_the_memory_limit.py`, the first three; `tests/integration/test_the_depth_seeker_opens_its_ladder_to_the_memory_limit_postgres.py`, the second (peaks from attempts, written once, read by the decision store) |
| the depth campaign's ladder past 262,144 | the unit file's fourth; the integration file's first (an old focus renewed once, the old campaign paused); `test_a_focus_runs_beside_the_blind_draw_postgres.py` (a new focus's ladder) |
| the save at 1,048,576 inside the grace | the unit file's last: packed, read back identical, two or more times faster, its extrapolation to 1,048,576 under `STOP_GRACE_SECONDS` |
| no score, kind or decision of a blind law moves | `outputs_of_a_law --against`: 0 changed; the rule needs an entry only the focus writes for its depth campaign |
| the full lane green | the Verification below |

## What it does not do

* A law settled at its ceiling stays parked when memory frees later; the engine diet (Rust's packed graph, in
  `docs/ROADMAP.md`) is what raises the ceiling for every law at once.
* The stop's grace is unchanged; the save fits it.

## Verification

4051 passed in 1425.43s (3 lanes at once)
