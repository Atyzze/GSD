# Graph Scale Dynamics

A blind survey of graph-ensemble laws. Every law is drawn from a declared grid and runs a base block of 64, 256, 1024
and 4096 nodes unless a named rule stops it; above that one decision engine buys deeper rungs, one at a time, for laws
whose readings settle, to 1,048,576; four dimension probes (d_s, d_V, d_B, d_w) report whether a law's geometry
settles as N grows. Each stop lets a share of the laws it would stop run one rung past it (its let-through), so its
cost is measured (`docs/DECISIONS.md`).

Live on-going research: [www.snekpas.nl/research](https://snekpas.nl/research/)

demo show case pictures

<img width="2340" height="1423" alt="Screenshot_20261124_142449" src="https://github.com/user-attachments/assets/764b74e1-8f01-44f7-bd0e-e520b5a59b2d" />

<img width="1714" height="1354" alt="Screenshot_20261124_141132" src="https://github.com/user-attachments/assets/ec8bebd1-798c-4674-a650-7166f7d18cb9" />

<img width="1899" height="1341" alt="Screenshot_20261124_141344" src="https://github.com/user-attachments/assets/21424449-f2c9-4a27-8484-64d13518598d" />

<img width="2229" height="1317" alt="Screenshot_20261124_141514" src="https://github.com/user-attachments/assets/f4f185b3-7b35-4b08-8353-e899c62218cf" />

## Read these first

Held under about 30,000 tokens by `tests/unit/test_the_read_first_set_is_small.py`.

    docs/WHERE_WE_ARE.md         the whole project on one page, in plain words (the operator's page)
    docs/agent/HANDOFF.md        what is true right now, and where everything else lives
    docs/agent/NEXT_BUILD.md     the next build: what it is, what blocks it, how to make and release it
    docs/agent/WORKING_WITH_THE_OPERATOR.md   how the operator sends, decides and wants answers
    docs/agent/ENVIRONMENT.md    section 10 only: the cold start in order
    docs/build_notes/            the newest build's notes

Then as needed:

    docs/ROADMAP.md              questions for the operator, planned builds, constraints, open questions, cadence
    docs/RESEARCH_METHOD.md      the question, the design, what the data settled, each number with its source
    docs/readings/README.md      every reading in the tree and what it is
    docs/OPERATIONS.md           campaign recipes, and how to read what the operator sends
    docs/DECISIONS.md            how the decision engine decides which laws get compute
    docs/ARCHITECTURE.md         the loop, the score, the fingerprints, the reports; where the tree has no room
    docs/TOOLS.md                what each tool in tools/ and main.py is for and how it is run
    docs/LESSONS.md              the rules learned by shipping their opposite; where defects cluster
    docs/HISTORY.md              the programme's aim, its eras, and the operator's standing decisions
    docs/build_notes/            the notes since the last consolidation and of the ten builds before it
    docs/agent/TARGET_ENVIRONMENT.md   the research host and the agent sandbox

**Only the code is real.** When you fix something a document describes, fix the description in the same pass, and
prefer deleting a sentence to qualifying it; a consolidation comes when one is needed
(`docs/ROADMAP.md`, "Build cadence").

## Bring up the host first

In an agent sandbox, bring the host up **before** concluding that any lane cannot run here: as root, from the tree,
the script does `docs/agent/ENVIRONMENT.md`, section 10, skipping each step already done.

    setsid nohup ./tools/prepare_environment.sh > /home/claude/prepare.log 2>&1 < /dev/null &
    ./tools/prepare_environment.sh --check    # each step's state; writes nothing

The research host's is `./tools/setup_host.sh` (`docs/agent/TARGET_ENVIRONMENT.md`).

## Running it

    uv run python main.py init
    uv run python main.py run          # fleet, database and dashboard on :8765
    uv run python main.py serve        # dashboard and reports, no fleet
    uv run python main.py pause / resume
    uv run python main.py campaign list | start | close | delete | archive | provenance | use | reopen
    uv run python tools/probe_calibration.py --whole   # the calibration table measured whole, collected; then it stops

`run` brings up the folder-local PostgreSQL over a Unix socket, verifies the calibration table, creates the study on
an empty database (`--study <id>` for one whose design the tree holds), repairs what a dead fleet left and starts the
fleet; Ctrl-C stops it cleanly and the same command resumes durable work. A campaign created under another policy
contract is refused, never adapted. The rest is `docs/OPERATIONS.md` ("Starting from an empty folder", "What every
start gives back").

## Verifying a tree before you change it

In a sandbox each command runs as the user through the prefix file (`docs/agent/ENVIRONMENT.md`, section 10), `su
claude -s /bin/bash -c ". /home/claude/prefix.sh && <command>"`; on the research host each `python3` is `uv run
python`. In the order they usually fail:

    python3 -m pytest tests/unit tests/contract -q     # expect 0 failures
    python3 tools/science_freeze.py                    # expect 0 drifted
    python3 tools/adopt_calibration.py --sample 1      # expect every sampled cell reproduced
    node tests/ui/dashboard_smoke.js graph_scale_dynamics/resources/ui
    python3 tools/baseline.py                          # the science is where it was
    python3 tools/test_suite.py --lane all --require-postgres    # what the release runs

The unit lane runs the Rust engine (`tools/build_engine.sh` rebuilds it) against no database; the PostgreSQL lane
finds what it cannot.

## Releasing

Only `tools/package_release.py` makes an archive, and every archive that leaves this machine bumps the build number
(`docs/agent/NEXT_BUILD.md`, "How to make a build"; the archive's contract, `docs/agent/ENVIRONMENT.md`, section 9).
`apply_build.py` on the research host refuses a tar made any other way.

## Four things that will cost you a campaign

**The clean start is three paths, together**: `instance/` (the cluster), `var/` and `.env.postgres` (the only copy of
its password), removed by `uv run python main.py reset` or, with the database stopped, `rm -rf instance/ var/
.env.postgres`. Deleting the credentials alone locks the folder out of its own database, and the obvious next move
destroys a live campaign; `uv run python tools/postgres_instance.py reset-credentials` recovers it, keeping the data.

**The probe calibration table is host state.** `calibration/probe_calibration.json` is gitignored; a folder without
one adopts `calibration/seed_table.json` after verifying every cell (`docs/OPERATIONS.md`, "The calibration table").
If a startup begins recalibrating, read its line (the candidate it examined and why it was not used) before stopping
it.

**The science fingerprint is not the survey.** `measurements/estimators.py` and its closure are frozen: a change to
their program forces a recalibration and stops the fleet (`docs/ARCHITECTURE.md`, "Fingerprints"). `tools/baseline.py`
says whether you moved it; the lane runs its freeze and calibration checks
(`tests/scientific/test_instrument_reads_known_objects.py`), not its estimator and cost checks.

**`schema.sql` has no in-place upgrade**: it is checksummed whole, so an edit strands every live database
(`docs/OPERATIONS.md`, "Resetting onto a new schema").

## Layout

    graph_scale_dynamics/engine/         the Metropolis engine (Rust in engine_rs/)
    graph_scale_dynamics/measurements/   the four probes; estimators.py is the fingerprint
    graph_scale_dynamics/scheduling/     spec validation, limits, admission, continuation
    graph_scale_dynamics/services/       proposer, controller, executor, worker, analyzer, maintenance, reporter,
                                         api, web, telemetry
    graph_scale_dynamics/operations/     the study, campaign control, the RAM scratch
    graph_scale_dynamics/reporting/      the study bundle and the study reading
    graph_scale_dynamics/decisions/      the decision engine, the evidence it reads, the decider
    graph_scale_dynamics/observability/  the readings the dashboard panels are views of
    graph_scale_dynamics/research/       the numbered reports, the stability score, the atlas
    calibration/                         probe windows, the seed table, the cost baseline
    tools/                               bring-up, release, audits, benchmarks

A render function of `resources/ui/app.js` (one long IIFE) needs a case in `tests/ui/dashboard_smoke.js` that executes
it with real rows and asserts what is drawn, including that an element survives a poll (`docs/LESSONS.md`, "Where
defects cluster").
