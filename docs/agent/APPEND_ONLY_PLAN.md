# The append-only plan: the table that only grows, and the reference set of four

The operator's direction of 2026-11-24 (19:10 and 19:15): the calibration table becomes append-only, "always/naturally
allowing for more probes/values/rungs for as long as the reference engine implementations are specified and included
with full hash in the shared datablob", validated by others against their own tables, "a different kind of
blockchain, one that isnt transactional"; and "C and ASM included by default as well, next to Python and Rust, to
complete the base-4 reference set which should also be append-able". **Where it stands**: L1 made at 855; the
rest paused at the operator's word (2026-11-24 19:43) after the consolidation of 858, until they say go on. This
page is the road there, as pull requests in
order; each is one coherent pack, tested, merged by the operator (`CLAUDE.md`, "Several workers, one repository").
A step is crossed out here by the pull request that makes it, with its build number.

## What a reader can rely on at each step

The principle, kept by every step: a reading is filed once under the hash of the code that made it and never
rewritten; a new probe, rung or implementation is appended under its own hash; nothing appended votes in the gate,
the score or a decision until a criterion committed before its known answers says what they must be; agreement
between hosts is filed as an attestation and compared by roots.

## The ledger

- **L1, made at 855**: `calibration/ledger.py` (hash-chained JSON lines, one file a probe group and fingerprint,
  attestations, Merkle roots of the set), `calibration/probe_groups.py` (the `geometry` group keyed as the table is;
  every module of `graph_scale_dynamics/probes/` an appended group keyed by its own closure), `tools/ledger.py`, and
  the first appended group, `quantum_walk`. The table is untouched and stays what everything reads.
- **L2, the quantum walk measured and its known answers committed** (host): `tools/ledger.py from-table`, then
  `tools/ledger.py measure --group quantum_walk --max-nodes 1048576 --workers 30` and `attest --sample 32`, the
  ledger files committed in a pull request of their own. From its readings on the 27 families, a criterion for each
  family's expected `q_alpha` and `q_decay` (or refusal), committed before a second host's run reads it. At 855 it
  reads the ring and the square torus as the dimension (1.01, 2.08) and does not spread on the Sierpinski gasket and
  a uniform random tree (0.00 to 0.03) where `d_s` reads 1.37 and 1.29; the cubic lattice refuses below 1,048,576
  (`SATURATES_EARLY`), which the full ladder will settle.
- **L3, the suite files what it measures**: `calibration/suite.py` appends each geometry cell to the ledger as it
  writes it, so the table is a view of the ledger and a recalibration adds a file rather than replacing one. The
  table's format does not change; `tools/ledger.py verify` joins the release's checks.
- **L4, readings pin their snapshot**: every reading that uses the table (the gate's known answers, the score's known
  answers, a study's reading) records `ledger_runs.view_snapshot` for the cells it read, so a reading can be checked
  later against the ledger however much it has grown. This moves `tests/fixtures/committed_readings.json` and is
  named in its build's notes.
- **L5, the geometry group split in four** (the operator's word needed): each of `d_s`, `d_V`, `d_B`, `d_w` its own
  module and its own stream of randomness, so a change to one probe re-measures one column. It is one
  recalibration of the whole table, filed under four new fingerprints beside the old one.
- **L6, attestations from other hosts**: a second machine runs `tools/ledger.py attest` on every group and files the
  agreement; a value confirmed on two hosts is marked so in the view. A host whose libraries differ files its
  environment with each record (`probe_groups.environment`).

## The reference set of four

The engines are the other half of "full hash in the shared datablob": a chain is a function of the law, N and the seed,
so any implementation that runs the same chain to the bit is a reference, and any that does not is not.

- **R1, the conformance vectors**: a fixed set of (law, N, seed, sweeps, start) cases chosen to cover every term,
  every move kind (toggle, swap, triadic, walk), cooling, zero temperature and each start family, each with what the
  Python engine produces: the final edge list's hash, the energy, the accepted moves by kind, and the hash of the
  trajectory record. Filed in the ledger as the group `engine_vectors`, keyed by the vector set's hash; the
  exhaustive Boltzmann check on four and five nodes stays beside it.
- **R2, the implementation registry**: each implementation is registered by the hash of its source and its build
  recipe, with the coverage it declares (terms, moves, starts). Conformance is filed per implementation and vector,
  as attestations; an implementation is a reference for what it reproduces to the bit and for nothing else. Python
  and Rust are registered first and must reproduce every vector.
- **R3, the C engine** (`engine_c/`): a port of `engine_rs/src` to C99 with the same Mersenne Twister stream
  (`engine_rs/src/mt.rs`), the same order of floating-point operations and the platform's `libm`, built as a shared
  library and driven through the same boundary as the Rust engine. Admitted when it reproduces every vector.
- **R4, the assembly engine** (`engine_asm/`, x86-64, System V): the Mersenne Twister, the acceptance rule and the
  cheapest terms first (edge count, degree sums, wedges), driven by the same boundary; it grows term by term, each
  term admitted by the vectors that use it. Its coverage is declared, so a partial engine is still a reference for
  what it covers.
- **R5, appendable**: a fifth implementation (any language) registers its hash and coverage and is admitted by the
  vectors; nothing else in the tree changes for it.

## Questions that steer the end result

Asked at a check-in; until answered, the steps above go on with the default named.

1. **The assembly engine's reach**: the whole engine by hand, the hot kernel only (proposal, acceptance, energy
   deltas), or grown term by term with declared coverage (the default, R4). And the instruction set: x86-64 only
   (the default), or ARM64 beside it.
2. **Where the reference engines live**: outside the frozen trees, each hashed in the registry like an appended
   probe (the default: adding one moves no science fingerprint and stops no study), or inside them.
3. **The ledger in git**: every full geometry pass is about 8 MB of JSON lines; committed to the repository (the
   default for the probe groups' first passes) or published beside it (a Zenodo record per snapshot) once it grows.
4. **The geometry split (L5)**: one full recalibration buys a table where each probe moves alone; when.
