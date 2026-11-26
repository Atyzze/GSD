# Build 876: the C engine

**Type: an engine build, the second of the reference set (`docs/agent/APPEND_ONLY_PLAN.md`, "The reference set of
four", R3) and of the roadmap's engines in order (the operator, 2026-11-25 08:35, 09:42 and 11:10: Rust, then C,
then x86-64 assembly, each proven by replaying the same seeds to the bit and timed on them), made on their word of
23:25 to keep building to the roadmap's end.** No score, kind or decision moves: the default engine stays Rust, and
`tools/outputs_of_a_law.py --against` 870's record: 0 outputs changed. No schema change. The science hash does not
move: the C engine computes the chains the Rust one does, so its science version is Rust's (0.840.0).

## For the folders

* Nothing to press. A folder runs on Rust as before; `GSD_ENGINE=c` runs a worker on C instead, the same chains.
* The C engine is compiled the first time it is asked for (`cc`, about two seconds) into `var/engines/`, named by
  the hash of its sources, so a changed source builds a new library and an old one is never run in its place. A host
  without a C compiler reports the engine as not available and runs on Rust.

## What changed

1. **`engine_c/`**: a port of `engine_rs/src` to C (GNU C99, for the 128-bit integers the node terms use), about
   2,300 lines in four files: `value.c` (the JSON the boundary speaks, a list of pairs kept packed as it is read),
   `graph.c` (875's layout from the start: each edge's slot beside its ends' neighbour lists, the square and cycle
   counts in arrays by slot, the per-move maps as open-addressed tables), `accounting.c` (the move accounting) and
   `engine.c` (the four operations, the Mersenne Twister in `mt.h`, and `gsd_engine_call`, `gsd_engine_free`,
   `gsd_engine_version`). The same Mersenne Twister stream, the same order of every floating-point operation, the
   platform's `libm`, `-ffp-contract=off` so no multiply and add are fused. `engine_c/engine.toml` holds its version
   (0.876.0) and its science version (0.840.0), read as the Rust engine's are.
2. **The registry** (`services/worker/engine_registry.py`): `c` beside `python` and `rust`, its one door the C ABI,
   built on demand (`library_path`); `simulate_of("c")` takes that door. Every test that walks the registry's
   engines now walks C too: the parity tests (`tests/scientific/test_engine_parity.py`, every law, start, kernel,
   stop, checkpoint and resume, Python against each engine and door) and the engine contract
   (`test_the_engine_contract.py`: every door of every engine answers every operation alike, and every fault the
   same). `tools/outputs_of_a_law.py` keeps its record on Python and Rust, so the record of 870 still holds.
3. **`tools/engine_diet.py --engine`** times any engine and door: `rust`, `rust:c_abi`, `c`.

## The measurement

One seed (seed 0, the eight starts of 176's design), each in a process of its own, on this sandbox; the same digest
of every chain on every engine and door in each row.

| law at 65,536 | Rust, in process | Rust, through the C ABI | C, through the C ABI | digest |
|---|---|---|---|---|
| `candidate_sparse_anchor` | 14.2 s, 590 MiB | 21.2 s, 875 MiB | 18.2 s, 822 MiB | `548a4c62` |
| overlaps | 10.8 s, 451 MiB | 16.8 s, 661 MiB | 15.2 s, 567 MiB | `e4d59ab4` |
| curvature | 18.9 s, 378 MiB | 22.6 s, 561 MiB | 19.2 s, 495 MiB | `e130dcba` |

Through the same door C is 10% to 15% faster than Rust; both pay for the JSON the C ABI carries (the edge lists in and
out at every chain), which the in-process door does not, so Rust in process stays the default. Reproduce with
`python3 tools/engine_diet.py --law anchor --law overlaps --law curvature --n 65536 --engine rust --engine rust:c_abi
--engine c`.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 875) | the test |
|---|---|
| every parity test passes on C as on Rust | `tests/scientific/test_engine_parity.py`, its cases for `c-c_abi`; `test_the_engine_contract.py` |
| the three laws timed on Rust and C, the same digest | the measurement above, `tools/engine_diet.py --engine` |
| the default stays Rust | `engine_registry.DEFAULT_ENGINE`; `outputs_of_a_law --against`: 0 changed |
| the full lane green | the Verification below |

## What it does not do

* **No in-process door for C**: the C engine answers only through the C ABI, which costs the JSON at each chain's
  ends. A door that hands the edge lists across as packed arrays would serve every compiled engine, Rust's included.
* **The curvature probe** keeps its own Rust door (`measurements/curvature_probe.py`), its source being in the
  calibration table's key until the recalibration.
* The C engine lives outside the frozen science trees (the plan's default for the reference engines): adding it moves
  no science fingerprint.

## Verification

4125 passed in 1334.46s (3 lanes at once)
