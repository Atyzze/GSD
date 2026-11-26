# Build 875: the engines' diet, Rust first

**Type: an engine build on the Rust engine and the Python side that holds what it returns, the operator's 2026-11-25
08:35 ("can we not make our engines more memory efficient? Or would that sacrifice speed?") and 09:42 ("replay the
seeds, results should remain identical, but simply grown faster with less memory"), made on their word of 23:25.**
Every chain is the same to the bit: the parity tests (Python against Rust, both doors, every term) pass unchanged, and
`tools/outputs_of_a_law.py --against` 870's record: 0 outputs changed. No schema change. The engine's crate is
0.875.0; the science it computes stays 0.840.0, so the science hash does not move (read "For the folders").

## For the folders

* **Rebuild the engine once** (`tools/build_engine.sh`) when applying 875: the tree's crate is 0.875.0, and a folder
  whose installed engine is 0.840.0 says the engine is stale until it is rebuilt.
* **The science hash is unchanged.** It now reads the engine's science version (`engine_rs/Cargo.toml`,
  `[package.metadata.gsd] science`), which moves only when a chain can come out different, rather than the crate
  version, which moves with every change to the engine's code. So a bundle of 176 made on 874 still seeds a folder on
  875, and a folder on 875 still reads as the same science as one on 874. If a later engine change alters a chain,
  its build moves the science version with it.
* A seed takes about half the memory it did and about half the time; the depth seeker's prices (873) are read from
  each law's own recorded peaks, so they come down by themselves as seeds run on 875.

## What changed

1. **The Rust graph keeps no hash maps per edge** (`engine_rs/src/graph.rs`): the index from an edge to its place in
   the edge list is now a second list beside each node's neighbours (the edge's slot), and each edge's square count
   and cycle counts are arrays by slot instead of hash maps keyed by edge. Per edge: 8 bytes of slots, 8 of squares
   and 24 of cycles where the law needs them, instead of a hash entry of about 26, 26 and 51 bytes. An edge's slot is
   found by reading the shorter of its two ends' lists, as `has_edge` already did. The work counted is unchanged.
2. **One number object per node** (`engine_rs/src/lib.rs`): the in-process door hands back the edge list and the
   lists of neighbours with one Python number per node, shared by every pair that names it, instead of a new one at
   every mention (about 64 bytes an edge on the Python side, for every chain a seed keeps). The starts a seed builds
   (`scaleflow/one_shot.shared_numbers`) share theirs the same way.
3. **A run's state holds its edges and degrees, nothing more** (`services/worker/engine_rs.RanInRust`): the sets of
   neighbours, the set of edges and the index of edges the Python state built after every run in Rust are built
   only if something asks for them; the final reading takes the degrees as they are (`engine/chains.final_of`). The
   edges a run is given are passed as they are, not copied first.
4. **`tools/engine_diet.py`**: one seed of a law in a process of its own, its peak memory, its time and a digest of
   every chain, so two engines are compared on the same seeds.

## The measurement

One seed (seed 0, the eight starts of 176's design, sweeps as each law says), each in a process of its own, on this
sandbox; the same digest of every chain before and after in every row.

| law, N | edges at the end, eight chains | peak memory, 874 | peak memory, 875 | time, 874 | time, 875 |
|---|---|---|---|---|---|
| `candidate_sparse_anchor`, 65,536 | 3,343,227 | 1,255 MiB | 590 MiB (53% less) | 24.5 s | 12.8 s |
| overlaps (square and triangle edge overlap), 65,536 | 2,199,113 | 992 MiB | 450 MiB (55% less) | 20.7 s | 10.1 s |
| curvature (Ollivier), 65,536 | 1,704,130 | 832 MiB | 378 MiB (55% less) | 26.1 s | 17.0 s |
| `candidate_sparse_anchor`, 262,144 | 14,229,158 | 4,928 MiB | 2,322 MiB (53% less) | 140 s | 77 s |

`python3 tools/engine_diet.py --law anchor --law overlaps --law curvature --n 65536` reproduces a row set; the
digests were `548a4c62`, `e4d59ab4`, `e130dcba` and `a8b9b378` on both engines.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 874) | the test |
|---|---|
| every chain the same to the bit, both engines | `tests/scientific/test_engine_parity.py` unchanged; `outputs_of_a_law --against`: 0 changed; the digests above |
| the bytes an edge and the time, before and after, on the same seeds | the measurement above, `tools/engine_diet.py` |
| what the science hash means for a seeded folder | `tests/unit/test_the_engine_keeps_fewer_bytes_an_edge.py`, the third: the crate at 0.875.0, the science at 0.840.0 |
| the lean state and the shared numbers | the same file's first two |
| the full lane green | the Verification below |

## What it does not do

* **A finished chain's edges are still a list of pairs** in memory, about 70 bytes an edge on the Python side, and they
  are the most of what a seed holds now (seven finished chains while the eighth runs). Packing them (8 bytes an edge,
  as the save already does since 873) touches every reader of a chain's edges; it is the next step of the diet.
* **The edge list stays**: drawing an edge through the degree tree instead would save 8 bytes an edge but draw other
  edges from the same random numbers, so every chain would change. It waits for a build that changes the science.
* The starts of a seed are kept for the whole seed, as before, now at half their bytes.

## Verification

4056 passed in 1402.42s (3 lanes at once)
