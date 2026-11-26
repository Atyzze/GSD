# Build 877: the assembly engine, grown term by term

**Type: an engine build, the third of the reference set (`docs/agent/APPEND_ONLY_PLAN.md`, "The reference set of
four", R4, with its first question's default: grown term by term, its coverage declared, x86-64 only) and the last of
the roadmap's engines in order (the operator, 2026-11-25 08:35 to 11:10), made on their word of 23:25 to keep
building to the roadmap's end.** No score, kind or decision moves: the default engine stays Rust, and
`tools/outputs_of_a_law.py --against` 870's record: 0 outputs changed. No schema change. The science hash does not
move.

## For the folders

* Nothing to press. `GSD_ENGINE=asm` runs a worker on the assembly engine for a law it covers; a law it does not cover
  is refused by name before a move is made (`OutsideCoverage`), never run some other way.
* Like the C engine, it is compiled on first use into `var/engines/` (`cc` assembles the kernel with the C files),
  and a host without a C compiler, or not on x86-64, reports it unavailable.

## What changed

1. **`engine_asm/kernel.S`** (x86-64, System V, about 300 lines): the Mersenne Twister (the twist and the tempering),
   `random()` from two words, `getrandbits` and `randbelow`, the Metropolis acceptance (`log` from the platform's
   `libm`, as the other engines take it) and the energy change of the five terms it covers, `edge_count`,
   `degree_square_sum`, `wedge_count`, `degree_anchor` and `degree_anchor_abs`, with the exact-zero rule. Everything
   else (the boundary's JSON, the graph's lists, the moves' bookkeeping, the records) is `engine_c/`'s code, built
   with `GSD_ASM`, which hands those steps to the kernel. `engine_asm/engine.toml` holds its version (0.877.0), its
   science version (0.840.0) and what it covers.
2. **Coverage declared** (`services/worker/engine_registry.Engine.covers`, `engine_registry.covers`): an engine that
   covers part of the terms says which; the C door's new fault kind `OutsideCoverage` (`engine/boundary.py`) is a
   `ValueError` that names the term it lacks. The parity tests run each engine on what it covers; a law outside is
   checked to be refused for a term the engine does not cover, and the case is recorded as an expected failure
   with the refusal as its reason, never a skip (`tests/scientific/test_engine_parity.py`, its `other` fixture); the engine contract checks every
   door of every engine on the full terms and on the assembly engine's own, and that the assembly engine refuses the
   first (`test_the_engine_contract.py`). A new parity law, `cooled_cheap` (edge count, wedges and the absolute
   anchor, cooled, with swaps), runs on every engine.
3. The C engine's version moves to 0.877.0 with its sources (the kernel's hooks); it computes as before.

## The measurement

`candidate_sparse_anchor` (edge count and degree anchor, which the assembly engine covers), one seed at 65,536, the
eight starts of 176's design, each in a process of its own; the same digest of every chain on every engine.

| engine and door | time | peak memory | moves a processor second | digest |
|---|---|---|---|---|
| Rust, in process | 12.7 s | 590 MiB | 1,241,000 | `548a4c62` |
| Rust, through the C ABI | 19.5 s | 866 MiB | 812,000 | `548a4c62` |
| C, through the C ABI | 17.6 s | 822 MiB | 899,000 | `548a4c62` |
| assembly, through the C ABI | 17.6 s | 822 MiB | 898,000 | `548a4c62` |

Through the same door the assembly kernel and C run alike: on this law a move's energy change is a few
multiplications, and most of the time beside them is the graph's lists and the JSON the C door carries at each chain's
ends, which the kernel does not touch. Rust in process stays the fastest and the default.

Inside its coverage, the assembly engine runs every parity case to the bit: the reference law, the anchor law, the
power-scaled degree square sum, zero temperature with global and local moves, and the cooled law above.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 876) | the test |
|---|---|
| every parity case inside its coverage passes to the bit | `test_engine_parity.py`, the `asm-c_abi` cases that run |
| a case outside is refused by name, never run wrong | the same cases, 41, each an expected failure whose reason is the refusal; `test_the_engine_contract.py`, the `every_term` case |
| timed beside Rust and C on a law it covers | the measurement above, `tools/engine_diet.py --engine asm` |
| the default stays Rust | `engine_registry.DEFAULT_ENGINE`; `outputs_of_a_law --against`: 0 changed |
| the full lane green | the Verification below |

## What it does not do

* **The rest of the terms**: triangles, squares, the overlaps, the gradient and the curvature need the neighbour lists
  walked, which is the next of the kernel's terms to grow; until then the assembly engine refuses them.
* **R1's conformance vectors** as a file of their own (law, N, seed, the hash of the final edges) are still the parity
  tests themselves; a vector set filed in the ledger, and other hosts' attestations, are for later.
* ARM64 is not written; the plan's default is x86-64 only.

## Verification

4173 passed, 41 skipped in 1308.35s (3 lanes at once)
