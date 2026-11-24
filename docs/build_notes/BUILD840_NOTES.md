# Build 840: no seed runs past its budget, and a restart loses no chunk. For a new folder, or one whose study has stopped: both engines changed, so a seed an earlier build saved starts its size again. Not for study 172's folder while its laws run.

**Type: the fix the bundles measured since 169 and the operator agreed on 2026-11-21 18:08, the second of that plan's
builds: the budget a stop inside a chunk, in both engines, and a stop that waits for the save.**
Changed: `engine_rs/src/lib.rs` (the crate is 0.840.0: `engine_rs/Cargo.toml`, `pyproject.toml`, `Cargo.lock`,
`uv.lock`), `graph_scale_dynamics/engine/engine.py`, `engine/chains.py`, `services/worker/engine_rs.py`,
`scaleflow/one_shot.py`, `services/worker/child.py`, `artifact_store/resume_state.py`. Tests:
`tests/unit/test_a_seed_ends_at_its_budget_in_work.py`, `tests/unit/test_resume_after_a_stop.py`,
`tests/contract/test_one_tick.py`, `tests/fixtures/engine_rs_sources.json`. Documents: `docs/agent/NEXT_BUILD.md`
(841), `docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`, `docs/HISTORY.md`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, `docs/OPERATIONS.md`, `docs/RESEARCH_METHOD.md`. The schema did not change. Four frozen sources
moved (the two engines' chain runners, the chain driver, the seed loop) and were anchored again; against 839's record
(`tools/outputs_of_a_law.py --against`) 0 outputs moved on either engine, since a seed inside its budget runs the
moves it ran; the table's lock prints `analysis-5.3.0 e639334808716378 89f4fed82d9adc27`.

## The budget, a stop inside a chunk

A seed's budget was read only between chunks: a chunk was admitted when the last chunk's work a move, times its own
moves, fitted, and then ran whole. Work a move can climb, so it did not always fit.

* **Both engines stop a chain at the same move.** Every 64 moves (`WORK_CHECK_MOVES`) a chain's work so far in the
  segment, its six parts times the unit's weights (`engine.units_spent`; in Rust beside the cap's check), is read
  against the room the seed has left (`work_room`), and the chain stops there as it does for a stop asked from
  outside, so the state it returns can be gone on from. `engine/chains.run_chains` gives each chain the room left
  after every chain's work so far. A chunk the limit does not reach is the chunk it was: 0 outputs moved.
* **The seed ends on its last whole chunk** (`scaleflow/one_shot.run_one_shot`), with reason `budget` as before. The
  chains of a seed run one after another inside a chunk, so the moment of the cut has some chains a chunk ahead of
  others and is no state to read; the cut chunk's work is spent and dropped. What such a seed reads is exactly what
  it would have read had that chunk been refused: the tests hold the two alike, edges and classification, on both
  engines. `rung_terminal.work.cut_inside_a_chunk` says where (the multiplier, the chain, the move, the units spent).
* **The first chunk runs whole.** It has no whole chunk before it to end on, and a law's first chunk is weighed before
  its size is bought (`first_chunk_prediction`). In 172 none of 27,036 seeds passed its budget in its first chunk.
* A seed stops within one check of its budget, 64 moves' work, on any machine.

## A stop waits for the save, and a seed saves inside long chunks

* **The wait is 120 seconds, not 8** (`STOP_GRACE_SECONDS`; a fleet's stop 132). A save is JSON of every chain's
  edges: measured, 19 s for the largest, densest state at 65,536 (eight chains at mean degree 32, 52 MB). At 8 s the
  restart that made 172's progress bundle ended 5 of 14 seeds unsaved. A seed that has saved exits at once, so a
  stop is as quick as it was for all but the largest seeds; the lease (180 s) outlasts the wait.
* **A seed saves inside a long chunk**, every 8 T units of its work (`SAVE_EVERY_UNITS`, a quarter to three quarters
  of an hour on the host): the engines stop at that point of work as they do at the budget, the loop saves and goes
  on from the saved state in the same process. A chunk saved so is byte for byte the chunk never stopped (held on
  both engines). A kill, the machine's memory killer among them, now costs at most that much work, where it cost the
  chunk. Measured at 16,384 nodes on two chains: 1.2 s to write a save, 0.5 s to stop and go on.
* **A saved state carries the seed's last whole chunk** (`whole` beside a state inside a chunk, `whole_envelope`
  where a chunk ended), so a seed resumed from disk and then cut at its budget ends where one never stopped does. It
  doubles a save inside a chunk (38 s at the worst case above). A whole chunk JSON refuses is left out and the state
  says so (`whole_chunk_left_out`), and that seed's next chunk then runs whole, as before.

## Measured on 172 before it was built

From the progress bundle's seeds (27,036 with their work): 127 seeds of 46 laws ran past their budget, 27 past twice
it; every one in a chunk after its first (final multiplier 4, 16 or 128). With this build each ends cut on its last
whole chunk. 78 of them ended at their budget anyway, one chunk later. The other 49 ended in the chunk that overran:
39 at the multiplier's ceiling, 7 at the mean degree cap and 3 certified (`2fd53ec181a0` at 1,024); those now end
cut, so their laws' rungs read a chunk earlier, and the 7 are no longer seen at the cap (`93cbf73f1bd6`,
`971ab1b46824`, `9c3fb2fb0dad`, `b0b62a3dea84`). Five scoring laws have such a seed (`4335e4d252a3`, `4dafa634fd79`,
`8a45be901ece`, `93cbf73f1bd6`, `f3fa2927afde`), each also cut at 4,096 by the budget as it was. The finished seeds
spent 3.1 core-hours past their budgets; the cost was the tail: the three seeds of `3df93c635ccd` at 65,536 ran a
chunk of about 54 T units against 24 T for 5.2 hours each, and the restart ended them with 1,060 seconds saved.

## The engines on their known answers

Read again, as whenever an engine changes (`tools/boltzmann_known_answers.py run`, criterion 4, both engines as
this build has them, `rs:0.840.0`): it passes, 260 of 260 cells kept and 112 of 112 reached, the control at twice its
energy refused in all four, and every number of all 264 cells is the one the judged reading of 816 holds
(`boltzmann_known_answers_4_judged.json`), as it must be for chains no budget stops. That reading stays the committed
one.

The parity tests, the stop and resume tests and the eight starts' run pass on both engines (284 in the engines' files).

## What the operator decided while it was made

On 839's picture of the fleet table (19:26 to 19:52, `docs/HISTORY.md`): a law with a cut seed is stopped by a gate of
its own, a tenth let through, and the fleet table names the two budget stops `cut` (ran out while running) and
`priced` (priced over its budget before starting); the let-through stays a tenth after a gate confirms, through the
pilot; the budgets stay as 172's; each chain's work goes into the bundle so 173 measures what the lattice starts cost
above 4,096; the 2019 model becomes a growth control run to 4,096 with every study; a run's scaling with N is tested
at two scalings. The first four are 841's; the rest are on the roadmap. Measured for them on 172: a law with a cut
seed is cut again at the next size in 68% of cases (62 of 71 from 1,024 to 4,096) against 2% otherwise, and all 15
laws cut at 16,384 were cut at 4,096; the 93 cut laws that went on spent 26 core-hours above their first cut, 14% of
the study so far; 8 of the 22 scoring laws have a cut seed (scores 7, 7 and six of 3), none of the top eight. A price
on the whole seed, from its law's work a size below, foresees 4 of the 91 laws cut at 4,096.

## Verification

3803 passed in 1190.42s (3 lanes at once)
