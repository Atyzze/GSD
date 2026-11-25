# The next build is 861

This file names the next build and says how to make it. `tests/unit/test_next_build_is_named.py` parses its first line,
which must read exactly `# The next build is <N>`, one above `BUILD_NUMBER`.

## Where to begin: 861 seeds a study from an earlier bundle

**Starting from nothing but the repository** (the operator, 2026-11-24 23:00): clone `main` and bring it up by
`docs/agent/ENVIRONMENT.md`, section 10, "From the repository"; 859 was made that way. Then `docs/WHERE_WE_ARE.md`,
`docs/agent/HANDOFF.md` and this page, in that order, and `CLAUDE.md`'s rules for a shared repository.

**What 855 to 860 left** (`docs/build_notes/BUILD855_NOTES.md` to `BUILD860_NOTES.md`): 855, `CLAUDE.md` (every
build a pull request the operator merges), the calibration ledger and its first appended probe group, the quantum walk.
856, study 176 designed and committed (groups A, the blind draw, and B, the map of the ten best, half the work slots
each), the still lattice at 1 (gsd-law-score-9), the small-world kind (gsd-catalogue-2, `small_world_criterion_1.json`
waiting on the next bundle), the system's CPUs on the System page, a science hash and the table in every bundle. 857,
Home's filter panel. 858, a consolidation. 859, the handover and the start from the repository alone. 860, made in the
sandbox from 859's archive and delivered as an archive (the session could not reach the repository; the operator
opens the pull request after testing it): the orange banner only when the refreshes fall behind, the frozen and still
lattices back on the landscape, the Top 100 in one order, and every law of a bundle whole (`spec` and `law_score` in
the laws table; `tools/laws_of_a_bundle.py` for an older bundle). The baseline is still 174's bundle of 2026-11-24
14:22Z and 175's of 08:35Z; 174's of 23:19Z was read at 860.

**What 861 makes** (the operator, 2026-11-24 18:04 and 2026-11-25 00:40, `docs/HISTORY.md`): a study started from an
earlier bundle whose science hash (`study.json`, `science`) is the folder's own, so others can join the search from
it: the bundle's laws taken whole (its laws table since 860, or `tools/laws_of_a_bundle.py` for an older one), its map
(`map.json`) loaded, its known regions known from the start and its mapping regions taken up again, so B starts where
the last study stopped; and A's grid leaning toward the regions least explored, the lean drawn and recorded, never
chosen by hand. A bundle of another science is refused, saying which part of the hash differs
(`science_contract.same`). The map's holders are chosen by the folder's own score (`law_score` in the bundle), not by
an offline reading that counts seeds that never stopped (860's notes).

**Where it will press**: `main.py` stands at 129,396 bytes against its ratchet of 130,000
(`tests/unit/test_size_ratchet.py`), so a new flag of `run` is a line there and its work a module's, as 856's
`workload` went to `work_groups.command`.

**Acceptance** of 861: a folder started from a bundle reads the same laws and map the bundle holds; a bundle of
another science is refused; no score, kind or decision moves (`tools/outputs_of_a_law.py --against` 860's record,
written first on the untouched tree); the full lane green.

**Then** the builds of `docs/ROADMAP.md`, "Planned builds", in order: the reader that scores as the folder does, the
fleet ladder under the filters, the map's term axis, group D, the consolidation. A planned build takes its number when
it is made.

**When study 176 sends its first bundle**: `tools/catalogue_reading.py` judges `small_world_criterion_1.json` (W1,
W2), and the map's regions are read from `map.json` against `study_176_criterion.json` (P1, P2 judged; P3 to P5
reported); 174's or 175's next bundle judges the small-world criterion too.

## Reading a study's bundle

The readers, in this order, each taking the `.tar.zst` or its folder; copy the bundle out of the uploads first
(`/mnt/user-data/uploads/`, its name prefixed with an id, `.tar.zst` sometimes written `_tar.zst`). A campaign that is
not **done** or **at its law budget** is said first: the reading is then a progress reading, its predictions reported
and not judged (`docs/OPERATIONS.md`, "Reading what the operator sends"). 171's numbers are in 838's notes and 172's
in 839's, 173's predictions in `study_173_criterion.json`; no bundle is in the tree.

    python3 tools/read_bundle.py <bundle>                                   # the first look: build, campaigns, laws
    python3 tools/catalogue_reading.py <bundle> --md <dir>/kinds.md        # every law's kind, the score in force
    python3 tools/study_173_reading.py <bundle>                             # 173's criterion, P1 to P12 (46 s)
    python3 tools/study_172_reading.py <bundle>                             # 172's criterion, R1 to R7 (30 s)
    python3 tools/replay_bundle.py <bundle>                                 # every decision replayed (13 s)
    python3 tools/counters_reading.py <bundle>                              # C1 to C3 (24 s)
    python3 tools/lattice_cost.py <bundle>                                  # the lattice starts above 4,096 (842)
    python3 tools/cap_reading.py <bundle>                                   # what a lower cap would cut (6 s)
    python3 tools/gate_variants.py <bundle>                                 # the fact gates on 1 and 4 sizes, the die
    python3 tools/budget_reading.py <bundle> --md <dir>/budgets.md          # seeds cut, laws stopped, by size
    python3 tools/bundle_growth.py <bundle> --json <dir>/growth.json --md <dir>/growth.md   # what grows (2 min)
    python3 tools/design_on_a_bundle.py <bundle> --design 173                # 173's rules on it, its predictions (12 s)

Then "The pilots" of `docs/OPERATIONS.md`: `pilot_reading.py` and `disordered_reading.py bundle` on the unpacked
folder, `study_baseline.py`, `fleet_reading.py`, `starts_bundle.py`, `score_list.py`. In a clone, copy the tree's
`calibration/probe_calibration.json` first: without the table `pilot_reading.py` calls every scorer irregular. Where
the engine cannot be compiled, `uv sync --frozen --extra dev --no-install-package gsd-engine-rs` runs every reader.
The readers that held every decision (1 GB at 2,500 laws, about 38 GB at 100,000) read them from a disk index since
842 (`tools/decision_index.py`): about 150 to 300 MB at 2,500 laws, flat with the study's size. What still grows with
a batch is a reader of report 28 or of the chains table read whole, one campaign at a time (`cap_reading.py`,
`budget_reading.py`, about 500 MB at 2,500 laws, so about 2 GB at a batch of 10,000), within the host's room.

A pilot's reading goes into the build's notes and its delivery's first lines, and nothing of it into `docs/readings/`.
Say first, in one plain sentence, how the study stands against its criterion; then the choices, each with its numbers,
the recommended one first with its cost.

**The rules a build keeps**: no schema change without need (`init_db` holds a folder to the schema's checksum); every
build says which outputs move (`python3 tools/outputs_of_a_law.py --write <file>` on the untouched tree, `--against
<file>` after); nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` moves without
saying why; the lock holds: no file of the table's key changes without the operator's word
(`docs/agent/HANDOFF.md`, "The instrument on known answers"). The fleet ladder carries a mouse-over on its headers only,
one fixed line each (787); a new number goes into a cell or a header's line.

## The road from there to study A

Study 173, the gated pilot, its run on 843 holding 32 workers and the build that reads it, with the next study's gates;
a control that grows from random, the 2019 model to 4,096 with every study; a run's scaling with N at two scalings;
the readers of report 28 measured at a batch of 10,000; pilots until the gates behave, the same trial twice and once on
a fresh seed; a small test of perturbing the best laws before 100,000 are drawn (the operator, 2026-11-21 18:08);
stable; study A's trial (5 x 1,000) and its full
run (10 x 10,000, 100,000 laws, a month on the host at the most) on eight starts without the curvature term, then
replicated; the gates closed and carried; the
curvature term as a study of its own after a small study of the exact curvature beside the formula; after those three,
the 2019 model run again (`docs/ROADMAP.md`, "Planned builds, in order").

* **What went wrong, so it is not repeated** (`docs/LESSONS.md`). Twice a thing was said of the code before the code
  was read. A turn was ended on a request to go on. Print a key's or a diff's size before its value; grep code files
  only. Wait inside a call: the sandbox runs only while a call is open, a detached lane included. Grep for every reader
  of what a step removes. A file created as root in the tree or under `/dev/shm/gsd-claude` stops the PostgreSQL lane
  run as `claude`; `chown -R claude:claude` both before a lane. Edit in a clone while a lane runs in the tree. A page's
  test goes through the path the page reads. The code carries no docstring either, a test included, and every `zip` says
  `strict=` (821 and 828 each failed their release lane on one). Make each build's changes on the
  tree it delivers. 806: a clock hides in more places than the engine: grep for every reader of time, and for every
  rule that reads what is in flight. 807: a confirmation must do work. 809: the fast lane runs in one process; when it
  touches most of the tree the full lane is faster on two cores.
* **Before an engine is touched**: `tools/outputs_of_a_law.py --write` on the untouched tree, and the Boltzmann known
  answer read again after (`docs/ARCHITECTURE.md`, "The engines"); it takes 25 minutes of two cores, and nothing else
  may install an engine into the venv while it runs. The sandbox's clock stops between calls: a detached run moves
  only while a call is open.
* 839 planned a mouse-over on the fleet ladder's cells before reading 787's rule (headers only): read the standing
  decisions on a page before changing it. 840's plan named `stop_at_move`, which the engines no longer have: a name
  in a plan is checked against the code. 840's notes said no top scorer had a cut seed, read from an earlier score;
  841's replay of the whole design found 7 scoring laws a stopping cut gate would lose: a gate is replayed on a
  bundle's decisions under the whole design (`tools/design_on_a_bundle.py`) before it is called safe.

## Known blockers

The full list is `docs/ARCHITECTURE.md`, "The blockers: where the tree has no room". Those a bundle's reading or a
sandbox tool meets: a reader is a tool of its own beside the others, never more of report 28; a reader
that reads report 28 whole holds one campaign's at a time (45 to 200 MB of JSON each). The sandbox has about 7 GB and two cores: an analysis that needs 32 GiB is
measured at smaller sizes or under a limit and its growth read, never run to the host's ceiling. The readings'
blocker is the bundles: the tree holds none, and only the operator can send them. The readings from before 169 are
not in the tree; one is read again only from the readings archive sent beside the build that took it out (from
`GSD_readings_archive_714.tar.zst` on), and never as a reference. The 2019 model's readings and criteria are in `GSD_readings_archive_829.tar.zst`, sent beside
829; its run again is judged by a criterion written fresh, never by them.

## Before anything

Bring the environment up detached: `docs/agent/ENVIRONMENT.md`, section 10, is the cold start in order, and the
bring-up script does its steps: `setsid nohup ./tools/prepare_environment.sh >
prepare.log 2>&1 < /dev/null &` as root, about three minutes on a warm cache; `--check` says which steps are done. The
trap that costs most time: **the sandbox pauses between tool calls**, so wait for a detached lane or release inside a
call.

## How to make a build

1. Make the change. Keep to the tree's conventions: no comment or docstring in the code (names say what the code does;
   why goes in the .md files: `docs/ARCHITECTURE.md` for how a part works, `docs/TOOLS.md` for a tool, the build's
   notes for why it changed; `tests/contract/test_the_code_carries_no_comments.py` holds it), tests that run the code
   rather than read its text, and a guard that fires is usually right.
2. If a frozen source changed, re-anchor: `python3 tools/science_freeze.py --write`. **The estimator and its import
   closure are not edited** without the operator's word (the table's key). A build that moves
   `tests/fixtures/committed_readings.json` names it in its notes, or the release refuses. After a new seed: `python3
   tools/calibrate_margins.py --write`, `python3 tools/finite_size_tolerance.py --write`, the fits' rows written into
   the shipped spec's `engine.policy.finite_size_fits`, and the freeze again. If `engine_rs/src` changed, bump the crate
   version in `engine_rs/Cargo.toml`, `engine_rs/pyproject.toml`, `engine_rs/Cargo.lock` and the `gsd-engine-rs` entry
   of `uv.lock` together, and run `tools/build_engine.sh` before any lane. If a size-ratchet bound moved, move the code
   or raise the bound deliberately and say so in the notes: both are allowed, silence is not.
3. Write the build's notes as `docs/build_notes/BUILD<N>_NOTES.md`. They open with a `**Type: ...` line, "consolidation"
   in it only for a build that changes no behaviour (`tests/unit/test_build_cadence.py`), and end with a `##
   Verification` heading whose line is the literal token `GATE_RESULT`; the packager replaces it with the full-lane
   result. Anywhere else in the notes the token is written in backticks, which the packager leaves alone.
4. Update `docs/ROADMAP.md` (what is done leaves it; a consolidation comes when one is needed, on no schedule),
   and rewrite `docs/agent/HANDOFF.md`
   and `docs/WHERE_WE_ARE.md` for the build. The handoff is what is true now. `docs/WHERE_WE_ARE.md` is one page of at
   most 90 lines in the operator's words (`tests/unit/test_where_we_are_is_current.py`), and its findings move only
   with `docs/readings/findings.json` and `docs/RESEARCH_METHOD.md` (`tests/unit/test_the_findings_manifest.py`). The
   read-first set stays under 30k tokens (`tests/unit/test_the_read_first_set_is_small.py`), the newest notes among
   it: a fact goes to its home (`docs/agent/HANDOFF.md`, "Where everything else lives"), a list to the file that holds
   it, not into the pages read first.
5. **Rewrite this file for the build after**, its first line exactly `# The next build is <N>`.
6. Commit, then run the gate **detached** (22 to 24 minutes on two cores, the PostgreSQL lane beside the rest; a
   foreground call is cut off). The gate prints only each lane's tail: `PYTEST_ADDOPTS="-rf --tb=line"` in the lane's or
   the release's script puts every failure's name in that tail. A small fix may take the fast lane, `package_release.py
   --fast`: the tests that touch what changed since the last build's record of its files
   (`tests/fixtures/build_files.json`) and the release's own checks; refused for a frozen source, the schema or the
   engine, and for two releases in a row; `tools/gate.py fast` runs it alone. By `docs/agent/ENVIRONMENT.md`, section 10
   (a script that sources the prefix file, started from root with `su claude`):

```
setsid nohup python3 tools/package_release.py --output <dir> > release.log 2>&1 < /dev/null &
```

   An interrupted release is recovered on the next run (the journal puts the tree back and spends no number), but it
   costs a full run, so detach it.
7. The gate refuses the release if any test fails and reverts `BUILD_NUMBER`. That is the system working; read the
   failure, fix the cause rather than the test, and run it again. Build every replacement in memory, assert every
   anchor, then write all files; anchor on structure (a heading, a numbered item's prefix), not on last build's prose.

**The archive the gate writes is the delivery, and the only one**: never a patch, a tar you made, or edits to apply by
hand. If the gate will not run, fix what stops it. Before the gate, every file you created is owned by the user that
runs it (a file owned by another user fails at `stamp_gate_result`, after the whole lane).

**Then open a pull request with what the gate passed** against `main` of `github.com/Atyzze/GSD`, which is public
(the operator, 2026-11-24 19:22: "create a pull request, and test it too, and when all approved, let me click the
final merge button myself"; `CLAUDE.md`, "Several workers, one repository"): the released commit on a branch of your
own, one commit `Build <N>`, its description the notes' opening, what moved and what the operator decides. Fetch
`main` first and rebase onto it: other workers deliver to the same repository and the operator edits on GitHub too
(the README's opening, 2026-11-24), so anything of theirs since the last build is taken into the tree before the gate
runs. From this sandbox the pull request is opened by the REST call, `gh pr create` being refused
(`docs/agent/ENVIRONMENT.md`, section 10, step 14). If `main` has moved past your number before the merge, renumber and run the gate again. Nothing is pushed to
`main` and nothing is force-pushed; the operator's merge is the release.

The tests that read a build's number (`tests/unit/test_next_build_is_named.py`, `test_build_identity.py`,
`test_where_we_are_is_current.py`, `test_claim_ledger.py`, `test_build_cadence.py`) accept the documents naming either
the tree's build or the one being made, so a local lane is green between releases and a page left a build behind
still fails.

## What not to do

`docs/LESSONS.md` is the list, with the cases behind each. The three that cost most often: do not ask the operator to
run a query or a command of your own (what the database holds belongs in the bundle); do not ship a fix for a fault
you have not measured; and do not change scoring or decision semantics in a build about something else.
