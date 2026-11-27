# Build 901: a resumed seed in a fresh seed's memory

**Type: an operations build, the first of `docs/ROADMAP.md`'s "Next, in order" as laid out for the operator with 897
and continued on their word of 2026-11-27 19:39 ("can you continue on your own through all the remaining work?")**,
made on 900. It needs a restart of the fleet, as 899 and 900 do: apply them with one. No score, kind, gate or
decision of any law moves; no frozen source, no file under `scaleflow/` or the engines, no schema;
`tools/outputs_of_a_law.py --against` 900's record: 0 outputs changed.

## What 178 showed

At 262,144 the two seeds of G73 that were stopped and resumed peaked at 3.05 and 3.19 GiB, the 14 that ran through at
1.47 to 1.53; at 1,048,576 the running seeds, all resumed, sat at 9.0 to 10.6 GiB where a seed run through from its
start held about 6.6 GiB (897's notes).

## The criterion, set before the change

One seed of G73 (law 8addbb0c, seed 2, study 178's design) at 16,384, which this sandbox runs in about 5 minutes: run
through; stopped at the first save inside its third chunk (a save every 4 × 10^11 work units, so the state carries a
checkpoint inside a chunk and its last whole chunk, as a seed of 1,048,576 stopped by a restart does); resumed from
that save. The resumed seed's peak within 10% of the fresh one's, its chains identical to the bit.

## What was measured

| the seed at 16,384 | resident, sampled every 0.5 s, at most (MiB) | right after its saved state is read (MiB) | chains |
|---|---|---|---|
| run through, a save every 4 × 10^11 units | 170 | | `509aae0b6e8babb1` |
| resumed, as 900 | 304 | 238 | the same |
| resumed, the checkpoint let go at its next save alone | 255 | 238 | |
| resumed, as 901 | 181 | 168 | the same |

The process is about 35 MiB before it reads anything. Its own peak (`ru_maxrss`, which the child reports as
`peak_rss_bytes`) catches moments the sampling misses: 175 MiB run through, 309 resumed as 900, 261 with the
checkpoint let go alone; in the runs that also wrote a digest of their chains at the end, 224 run through, 364 resumed
as 900 and 221 as 901, the digest's own cost in each. The engine's own state at that save holds 56 MiB in its
checkpoint and 52 MiB in its last whole chunk; read back as 900 read it, 77 and 74 MiB. Two things made the
difference, neither in frozen code:

1. **The state read back larger than the engine wrote it** (`artifact_store/resume_state.unpacked`, since 873): every
   packed pair came back as a list of two numbers of its own, where the engine keeps a tuple. Since 901 a pair comes
   back as a tuple and equal numbers as one object (`unpacked_list`), decoded while the JSON is parsed (`unpacking`,
   `json.load`'s `object_hook`), so the file's base64 arrays are never all held beside what they decode to.
2. **The child held the saved state for the whole run** (`services/worker/child.py`): its `resume` stayed alive for
   `cpu_speed`'s count of the moves before, and the run's own `resume` argument held the same dict. The run needs it
   only before its first chunk and, after that, only its `history` (`chunks_before`). Since 901 the child counts the
   moves at the load (`cpu_speed(envelope, moves_before, ...)`) and, at the first state the run hands out, lets the
   saved checkpoint and its whole chunk go (`resume_state.let_go_of_its_states`, `HELD_STATES`). From there the run
   holds what a fresh seed holds.

A fresh seed between its saves holds the checkpoint of its last save and its last whole chunk, each every chain's
edges, about 56 bytes an edge as tuples, beside the engine's own graph: that is where the unscheduled profile of the
Rust engine's bytes an edge would start (`docs/ROADMAP.md`).

## For the folders

* **Study 178**: `main` holds 898 to 900 (#40 to #42); merge this pull request, apply 898 to 901 and restart the
  fleet's services once. G73's three
  seeds of 1,048,576 resume in about a fresh seed's memory. Their admission still asks from their own earlier peaks,
  read under 900 (`push_ladder.pushed_ask`), until a seed of that size finishes; the seeds after them ask from the
  typical one.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a seed resumed inside a chunk, its saved state let go at the next save, is the seed never stopped, on both engines | `tests/unit/test_a_resumed_seed_holds_what_a_fresh_one_holds.py` |
| the state read back holds what the engine's own holds: a pair a tuple, equal numbers one object, its edges within a list's spare room, its checkpoint within 10% | the same |
| the child counts the moves from the saved state and lets it go once the run hands out its next | the same |
| a packed save reads back as it was written | `tests/unit/test_the_depth_seeker_reaches_the_memory_limit.py` |
| the moves of an attempt, from the count before it | `tests/unit/test_each_seed_s_cpu_speed.py` |
| no output of the sparse anchor law moves | `tools/outputs_of_a_law.py --against` 900's record: 0 changed |
| the full lane green | the Verification below |

## What it does not do

* **A fresh seed's two checkpoints between saves**: the run (`scaleflow/one_shot.py`, frozen) keeps its last whole
  chunk beside the checkpoint of its last save, as it always has; 901 makes a resumed seed hold the same, not less.
* **The moment a state is read**: the file's text is parsed whole (`json.load`), so a resumed seed's highest moment
  can still be the read itself; 901 measured its own peak only with the digest beside it (221 MiB at 16,384,
  against 224 run through).

## Verification

4270 passed, 41 skipped in 1353.44s (3 lanes at once)
