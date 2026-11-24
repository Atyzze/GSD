# GSD: what every worker on this repository reads first

This file is loaded by every agent that opens the repository. It says what the system is, how several workers share
it, and the principle the operator set for its data. The detail lives in the pages it names; where a page and the code
disagree, the code is right and the page is fixed in the same pull request.

## What this is

Graph Scale Dynamics asks whether a local energy rule on a sparse graph, sampled by Metropolis dynamics, makes a graph
whose dimension settles as the graph grows. A law is drawn, run from eight starts at sizes 64 to 1,048,576, and read by
four dimension probes calibrated on 27 families of known graphs; a score and a decision engine say which laws go
deeper. The question, the method and what is known: `docs/WHERE_WE_ARE.md` (one page), then `docs/agent/HANDOFF.md`
(what is true now), then `docs/agent/NEXT_BUILD.md` (what to do next and how a build is made).

The loop, each part with its section of `docs/ARCHITECTURE.md`: the proposer draws laws; the fleet runs their chains
on the engines (`engine/` in Python, `engine_rs/` in Rust, the same chain to the bit); the probes read each chain
(`measurements/`, keyed by the calibration table); the score and the decisions (`observability/`, `decisions/`)
choose what runs deeper; a study's bundle is read by `docs/agent/NEXT_BUILD.md`, "Reading a study's bundle". The
instrument's known answers (the calibration table, the dimension test, the Boltzmann check) are checks of the
instrument, never data of a study.

## Several workers, one repository

The operator runs more than one context against `github.com/Atyzze/GSD` at once (2026-11-24 19:22: "when delivering
your build, do it as one coherent pack of code updates and create a pull request, and test it too, and when all
approved, let me click the final merge button myself, so that I remain in charge of the build releases while you
internally can work on your own builds/branches to be merged into the main public one").

1. **Work on a branch of your own**, never on `main`; nothing is pushed to `main` and nothing is force-pushed.
2. **Deliver one coherent, tested pack as a pull request** against `main`: the gate's result in the build's notes, the
   tests it adds, and its description saying what changed, what did not, and what the operator decides. The
   operator merges; a merged pull request is the release.
3. **Fetch `main` before you open or update a pull request** and rebase onto it. The build number is taken when the
   pull request is made ready: if `main` has moved past your number, renumber the build (`BUILD_NUMBER`, its notes,
   `docs/agent/NEXT_BUILD.md`, `docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`) and run the gate again.
4. **The shared pages belong to the build being released**: `BUILD_NUMBER`, `docs/agent/NEXT_BUILD.md`,
   `docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`. A pull request that is not a build leaves
   them alone, so two workers do not rewrite the same page.
5. **What is live is not touched without the operator's word**: a running study, a folder's database, a criterion
   after its run started (`docs/agent/HANDOFF.md`, "Start here").
6. **Long work checks in** with the operator about every four hours: what is done, what is next, and only the
   questions whose answer could change the outcome.

## The science table only grows

The operator, 2026-11-24 19:10: the table becomes "append-only instead of [...] immutable", "always/naturally
allowing for more probes/values/rungs for as long as the reference engine implementations are specified and included
with full hash in the shared datablob", with others validating it against their own tables.

- **Nothing measured is rewritten.** A reading is filed once under the fingerprint of the code that made it
  (`calibration/ledger/`, `docs/ARCHITECTURE.md`, "The calibration ledger"); a change of code files its readings
  under a new fingerprint beside the old, and every past reading stays checkable against exactly what it used.
- **Probes, rungs and reference implementations are appended**, each under its own hash. An appended probe group
  (`graph_scale_dynamics/probes/`) moves no frozen source, no science fingerprint, no running study and no cell of
  the table. It has no vote in the gate, the score or a decision until a criterion committed before its known answers
  says what they must be.
- **Agreement is filed, not assumed**: another host re-measures a cell and files an attestation (`tools/ledger.py
  attest`); two views are compared by their roots (`tools/ledger.py snapshot`).
- **The reference set is four implementations of the engine**: Python and Rust today, C and x86-64 assembly to come,
  and more appendable, each registered by its source hash and admitted by the conformance vectors it reproduces to the
  bit. The plan, build by build: `docs/agent/APPEND_ONLY_PLAN.md`.

## How code is written here

`docs/agent/NEXT_BUILD.md`, "How to make a build", is the rule; the three that trip a newcomer: no comment or
docstring in the code (names say what it does, the why goes in the pages: `tests/contract/test_the_code_carries_no_comments.py`);
tests that run the code rather than read its text; and the estimator's import closure and every frozen source
(`graph_scale_dynamics/domain/science_identity.py`) are not edited without the operator's word.
