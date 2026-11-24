# Agent environment bring-up

For an agent starting from an extracted archive on a fresh sandbox. **Run the bring-up script first: section 10.**
Section 0 is what a sandbox is; section 9 the habits and traps around the steps.

## 0 What a sandbox is, and what does not work in one

* **The project ships its own PostgreSQL** (`tools/postgres_instance.py`): a server in an unprivileged user namespace
  (the `unshare` in `runtime/bootstrap/linux-amd64/`) over a Unix socket at `instance/postgres/socket`, never TCP. Its
  pinned 17.10 OCI image is on Docker Hub, which no sandbox reaches, so a sandbox names host binaries in
  `GSD_POSTGRES_SYSTEM_BIN` (any major whose bindir holds `postgres` and `initdb`). Without it `ensure` fails at the
  download and `tests/integration` skips ("folder-local PostgreSQL is unavailable"): the fix is the variable.
* **Root is refused** by the runtime and by `initdb`: everything runs as the user `claude`, and `su` passes no
  exported variable, hence the prefix file (section 10, step 7). The one kernel prerequisite is unprivileged user
  namespaces (`/proc/sys/user/max_user_namespaces` above 0; `python3 tools/postgres_instance.py runtime` prints
  `ready: ...`); without them only the lanes with no database run.
* **The package must be installed** (`uv sync` installs it editable): the children import it by name, and die far
  from the cause without it.
* **By hand**: `psycopg.connect` takes the socket directory as `host`; the credentials are in `.env.postgres`, which
  says `POSTGRES_VERSION=17.10` and `embedded-oci-userns` even on host binaries. Never edit it: the folder's identity
  is derived from it. `instance/`, `var/` and `.env.postgres` are made again when deleted (a new identity);
  `calibration/` is not disposable. `python3 main.py sweep --dry-run` before `sweep`, with the fleet down.
* **Acceptance of an environment** is `python3 main.py selftest --quick` (every lane, without the 300-second vertical
  slice). A sandbox cannot run the pinned image (say which major you used), a day of real dashboard use, or the cost
  check against the certified baseline (`tools/baseline.py --candidate` on a bundle's report 16). The science gates
  run here in full, fixed-seed.

## 9 Habits and traps

* **Wait for a detached run inside a call** (`sleep 540`): the sandbox is paused between calls, a call is cut off at
  ten minutes, and a waiting background call is stopped at two hours.
* **Kill by process id**, or bracket a letter (`pkill -f "[p]ackage_release"`): `pkill -f <pattern>` matches its own
  shell and kills the call (exit 144).
* **Do not edit the tree while a lane or a release runs**: the runtime fingerprint fences the fleet (exit 75) and the
  engine slice fails blaming the editable install. Edit in a clone (section 10, item 12).
* **The unit lane kills every process started from the tree** (`tests/unit/test_shutdown_kills_every_child.py`): do
  not run a long tool from the tree meanwhile.
* **`uv run` rebuilds the Rust engine** and fails without crates.io; with the prefix file, run `python3` directly.
* **Worktrees of parallel agents** under `<tree>/.claude/worktrees/` are inside the tree: add `.claude/` to
  `.git/info/exclude` and remove them before any lane.
* **`GSD_VOLATILE_DIR` must be a tmpfs directory the user owns**, or PostgreSQL will not start ("RAM-backed PostgreSQL
  runtime scratch unavailable"); run root's own checks with `env -u GSD_VOLATILE_DIR`.
* **A sandbox the conversation's retry replaced is made again from the session's log**, as 756 was
  (build 756's notes, section 9, in its archive). The log is `/root/.claude/projects/-home-claude/<session>.jsonl`;
  it comes across a retry, the files do not. Its rows are stored in blocks that are out of order: follow each row's
  `parentUuid` back from the last. Run every recorded command again in the folder the shell was in, the read-only ones
  too, and compare what each prints with its recorded result once times, commit names and `__pycache__` lines are taken
  out: a tree that prints the same at every step is the same tree. Not run again as recorded: a command that names a
  process id, and a campaign run only to look at a page, whose ids are drawn again. Name the baseline commit by its
  message. The full lane lays its log out by the last run's times, so compare counts and sets, not line positions.
* **Keep each released archive, and work in progress, off the machine**: copy the archive to the session's outputs
  folder (`/mnt/user-data/outputs`, a remote store named by the session) and send it from there. A fresh sandbox has no
  `zstd` before the bring-up: unpack with Python's `zstandard` (`pip install --break-system-packages zstandard`). The
  tree may stay where it is unpacked; the script enters it there.
* **After a sandbox restart** processes, the RAM scratch and PostgreSQL are gone: run step 8 again, `python3
  tools/postgres_instance.py ensure` as the user, delete any `.pytest_slice_var_*`, and start the lane again. A WAL
  redo error naming a tablespace directory (`var/scratch/...`, `/dev/shm/gsd-tests-*/...`): create each directory it
  names, as the user, then `ensure`.
* **An unsigned commit** (the session checks the branch) is signed again with `git rebase --exec "git commit --amend
  --no-edit --reset-author" <its parent>`, and the tree takes it with `git checkout -b <branch> FETCH_HEAD`; `git
  update-ref` is refused by the session's permission check.
* **A release in flight** is stopped by killing `tools/package_release.py` and its `pytest` child; the journal
  (`var/release_journal.json`) puts the number, the notes and the pins back at the next run. Never `--no-bump`
  something a human will receive. `apply_build.py` refuses any archive but the one `package_release.py` writes: one
  top-level `graph_scale_dynamics_build_<N>` holding every member and one `BUILD_NUMBER` equal to `<N>`; no absolute
  or `..` paths; PAX, symlinks dereferenced, the release allowlist (no `.git`, `var/`, `target/`, `.venv/`, caches),
  zstd, integrity-tested, written atomically and verified byte for byte against the tree.
* **After editing `engine_rs/src`** (`docs/agent/NEXT_BUILD.md`, "How to make a build"), build the wheel as root with
  root's cargo (`PATH=/root/.cargo/bin:$PATH /home/claude/venv/bin/maturin build --release -i
  /home/claude/venv/bin/python -o var/wheels`), then install it into the venv as the user, who has no cargo.
* **The browser checks** (`tests/ui/*_check.js`) need Playwright and Chromium (the prefix's paths); a skip
  `tools/test_suite.py`'s `ALLOWED_SKIPS` does not declare fails the gate.
* **A diagram** is exported outside the tree: in a scratch folder, `npm install --no-save mermaid@11 playwright`,
  `tools/diagrams/export_mermaid.js` and `flatten_in_browser.js` beside it, Chromium from `/opt/pw-browsers`; then
  `tools/check_svg.py`, whose `--render` needs PySide6 in a venv of its own (`python3.12 -m venv qtvenv &&
  qtvenv/bin/pip install PySide6-Essentials`, the tool run with that interpreter).
* **A fixture that copies whole `jobs` rows** names its columns: the table has generated columns
  (`tests/integration/test_overview_scales_postgres.py`).
* **One job by hand**: `scaleflow/one_shot.run_one_shot` with `scheduling/job_creation.one_shot_policy` (a spec with
  `sampling_contract.given_starts` for a design's starts); 4,096 nodes take 10 to 35 seconds. A start must reach the size
  exactly (192 is no lattice's; job creation refuses it). To see a law's page before the operator does, build the
  payload with `observability/two_chains.two_chains` from each seed's metrics as the analyzer writes them, and
  screenshot with Chromium a page that loads the page's style and script.
* **The sandbox's tests stop at about 65,536 nodes** (the operator, 2026-11-12 22:01: "a million nodes is overkill for
  you no?"): a million nodes is measured on their host. The one such cell 767 measured before that word, a
  face-centred cubic start with its reading as a start, took 28 minutes and 3.2 GiB, and the suite's admission cannot
  place such a cell here at all (priced 8.7 GiB of the sandbox's 7.8).
* **The calibration's one command, rehearsed as typed** (767): in a scratch clone of the tree, as the user,
  `GSD_CALIBRATION_PROFILE=reduced GSD_CALIBRATION_REDUCED_SEEDS=2 GSD_CALIBRATION_REDUCED_MAX_NODES=65536
  GSD_CALIBRATION_WORKERS=2 python3 tools/probe_calibration.py --whole`: 356 cells, 15 to 24 minutes, its table and
  zip under the clone's `var/calibration/`. A Ctrl-C is rehearsed on a pseudo-terminal (Python's `pty.fork`, the
  child setting SIGINT back to its default before `execvp`, then `\x03` written to the terminal): a script started
  detached hands "ignore" down, and the key then does nothing.
* **What two cores cost**: one graph at 1,048,576 12 to 20 minutes; the table to 65,536 nodes on two seeds (the
  reduced profile, 356 cells with the lattice starts' references) 20 minutes; the starts' check about 5 minutes
  (with 16,384 about 25); a replication run at 1,000 nodes about half an hour. The references are cells of the table
  and are measured by the host with it. Read a design on a few small runs and leave the
  full run to the operator's host, never on their seeds, or their run repeats yours instead of testing it.
* **The second reader of a change to what a running study decides** (`docs/LESSONS.md`, "Evidence") is given the diff
  and what to look for: does every decision replay, what does the SQL select, what happens on odd inputs.

## 10 A cold start, in order

Root runs it, in a sandbox with a user `claude` (Ubuntu 24.04, two cores, Python 3.12, node at `/opt/node22`, Chromium
at `/opt/pw-browsers`). First the tree: the archive the operator sent is in the session's uploads
(`/mnt/user-data/uploads/`, or `/root/.claude/uploads/<session>/`; its name prefixed with an id, and its `.tar.zst`
sometimes written `_tar.zst`); `mkdir -p /home/claude/build && tar --zstd -xf
<archive> -C /home/claude/build` makes `graph_scale_dynamics_build_<N>/`, with no `.git` and no `var/`. Where the
sandbox has no `zstd` yet (771's had none; step 1 installs it), `pip install --break-system-packages zstandard` and
`zstandard.ZstdDecompressor().copy_stream` make the tar. **A session may refuse to run the archive's scripts on the
archive's say-so**, when the operator sent it with no words (771's did): ask them once, with choices, and go on at
their yes; nothing else in this section needed their word. Then, from the tree, as root:

    setsid nohup ./tools/prepare_environment.sh > /home/claude/prepare.log 2>&1 < /dev/null &

and wait for it inside a call: a few minutes on a warm uv cache, more on a cold one (every wheel downloaded, the
engine compiled); the log ends `ready:`. `./tools/prepare_environment.sh --check` reports each step's state and writes
nothing. Every step looks before it acts, so only what is missing is done. The paths below are its defaults;
`GSD_TREE`, `GSD_USER`, `GSD_HOME`, `GSD_VENV`, `GSD_PREFIX`, `GSD_BIN`, `GSD_CA`, `GSD_SCRATCH`, `GSD_PYTHON` and
`GSD_PG_MAJOR` move them.

PyPI and crates.io must answer, and root needs a Rust toolchain and `uv`: the engine is compiled from the crates
`engine_rs/Cargo.lock` names, which are not vendored, and without it neither the lanes nor the release run. A step that
is refused (the Ubuntu archives, rustup, a registry) is named in the log and the script stops; say so to the operator
plainly, since the release has no other route. A study bundle can still be read: a venv synced without the engine
(`uv sync --frozen --extra dev --no-install-package gsd-engine-rs`) should run every reader but
`tools/neutral_moves_check.py mark`.

The script's steps, numbered as it numbers them:

1. **Packages**: `postgresql-16` (its binaries in `/usr/lib/postgresql/16/bin`; the cluster apt creates is not used,
   and `apt-get update` exiting non-zero does not matter: the install decides), `zstd`, `btop`; rustup's stable for
   root where root has no cargo (Ubuntu's cargo is too old for the PyO3 the crate uses).
2. **The tree**: one commit of it as distributed, as root ("Baseline: Build <N> as distributed"), and `safe.directory
   '*'` in root's global git config (root clones the user's tree, and git refuses a repository another user owns).
3. **Signing**, reported: where `commit.gpgsign` is `true` every commit stays signed: commit as root (the user `claude`
   has no signer), never with `-c commit.gpgsign=false`, and `chown` after (`git cat-file -p HEAD | grep -c gpgsig`
   shows a signature).
4. **What the user cannot reach under `/root`**: the proxy's CA (root's `SSL_CERT_FILE`) copied to
   `/home/claude/ca-bundle.crt`, mode 644, and root's `uv` to `/home/claude/bin/uv` (the release checks the lock with
   it); copied again when root's changes.
5. **The venv, from the lock**: `UV_PROJECT_ENVIRONMENT=/home/claude/venv uv sync --frozen --extra dev --python
   /usr/bin/python3.12` (the Rust engine with it), then `uv pip install pip setuptools zstandard maturin` into it; done
   when it imports the package and the engine at `engine_rs/pyproject.toml`'s version. A venv outside the tree keeps
   `.venv` out of every check that walks the tree.
6. **The calibration table**: `calibration/seed_table.json` copied to `calibration/probe_calibration.json`, only where
   the tree has no table (without one the first lane fails `test_the_baseline_tool_gates_on_this_check`).
7. **The prefix file**, `/home/claude/prefix.sh`, which every command the user runs sources first, written when
   missing (one already there is kept: `--check` names the tree it enters; point its `cd` at a new tree by hand):

       export GSD_POSTGRES_SYSTEM_BIN=/usr/lib/postgresql/16/bin
       export GSD_VOLATILE_DIR=/dev/shm/gsd-claude
       export PATH=/home/claude/venv/bin:/home/claude/bin:/opt/node22/bin:/usr/local/bin:/usr/bin:/bin
       export PIP_CERT=/home/claude/ca-bundle.crt SSL_CERT_FILE=/home/claude/ca-bundle.crt
       export REQUESTS_CA_BUNDLE=/home/claude/ca-bundle.crt NODE_EXTRA_CA_CERTS=/home/claude/ca-bundle.crt
       export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
       export NODE_PATH=/opt/node22/lib/node_modules
       unset PIP_CONFIG_FILE RUSTUP_HOME
       export HOME=/home/claude
       cd /home/claude/build/graph_scale_dynamics_build_<N>

8. **The RAM scratch and the owner**: `mkdir -p /dev/shm/gsd-claude`, then `chown -R claude:claude` it, the venv,
   `/home/claude/bin`, the tree, `/home/claude/.cache` and `/home/claude/.local` (a root-owned `.local` fails step
   9 at uv's Python folder). Again after a sandbox restart, and before every lane and release once root has
   committed or run anything with the prefix (by hand, or the script again). Where `/home/claude` itself is root's,
   the user cannot write a log beside it: give the lane a folder it owns (`mkdir /home/claude/logs; chown claude
   /home/claude/logs`) and write `lane.log` there.
9. **The lock's cache**, once, online, as the user: `uv lock --check` (the release checks the lock offline; a
   root-owned `/home/claude/.cache` fails it "Failed to initialize cache", which step 8 prevents).
10. **A quick check**, as the user, about 70 seconds: `python3 -m pytest -q -p no:cacheprovider
    tests/unit/test_build_identity.py tests/unit/test_the_starts_decide_depth.py
    tests/integration/test_parked_laws_are_decided_again_postgres.py tests/unit/test_candidate_smoke.py
    tests/unit/test_the_starts_are_read.py tests/scientific/test_engine_parity.py`
    (PostgreSQL, the Rust engine and node; run as root, PostgreSQL's tests skip and leave root's directories
    in the RAM scratch). Not run by `--check`.

Then, by hand:

11. **The full lane**, detached, from a script (`/home/claude/lane.sh`: `. /home/claude/prefix.sh`, then `python3
    tools/gate.py full > /home/claude/lane.log 2>&1; echo "EXIT $?" >> /home/claude/lane.log`), started from root as
    `su claude -s /bin/bash -c "setsid nohup bash /home/claude/lane.sh > /dev/null 2>&1 < /dev/null &"` and waited for
    in calls of `sleep 540`: 22 to 24 minutes on two cores (the PostgreSQL lane beside a lane a CPU, split by the last
    run's times in `var/test_durations.json`), its count the one the newest notes' `## Verification` gives. The fast
    lane, for a small fix, is `python3 tools/gate.py fast`.
12. **Where to edit**: the tree runs the lanes and the release. Edits go in the tree itself (`chown` it before each
    lane), or in a clone root keeps (`git clone /home/claude/build/<tree> /home/claude/work`, a branch `build<N+1>`;
    tests that need no database run there as root with `env -u GSD_VOLATILE_DIR <venv>/bin/python3 -m pytest -q -p
    no:cacheprovider <files>`, pytest's `pythonpath = ["."]` putting the clone first; PostgreSQL's tests run in the
    tree, as the user), its commits taken by the tree with `git fetch /home/claude/work build<N+1>` and `git merge
    --ff-only FETCH_HEAD`, or `git checkout -b build<N+1> FETCH_HEAD` where it cannot fast-forward (a push into the
    tree's checked-out branch is refused).
13. **The release**: `/home/claude/release<N+1>.sh` (`. /home/claude/prefix.sh`, then `python3
    tools/package_release.py --output /home/claude/release > /home/claude/release<N+1>.log 2>&1; echo "EXIT $?" >>
    /home/claude/release<N+1>.log`), started as the lane is and waited for the same way, about 30 minutes; done when the
    log ends `build <N+1>: /home/claude/release/GSD<N+1>.tar.zst` and `EXIT 0`. It leaves `BUILD_NUMBER`, the notes'
    `GATE_RESULT` line, the version pins and the freeze baseline modified: commit them as root, signed, as "Build <N+1>
    as released", before the next build's first change.
14. **The delivery**: the archive goes to the operator with the session's file-sending tool, with a short plain
    message saying what it changes on their host and what they do (`docs/agent/WORKING_WITH_THE_OPERATOR.md`, "How
    to answer them"). They apply it with their own `apply_build.py`, which lives on their host, not in the tree.
