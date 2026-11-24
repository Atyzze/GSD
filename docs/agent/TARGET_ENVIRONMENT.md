# Target environment

One base lineage. Every design decision, script and doc in this tree assumes it; nothing reasons about alternatives.

## The research host

The operator's one research host: AMD Ryzen 9 9950X3D (16 cores, 32 threads), about 92 GiB of RAM, **Arch Linux /
CachyOS** (systemd, KDE Plasma, fish as the interactive shell, pacman). GSD folders are `/data/projects/GSD/<n>/main`,
one folder a study: the next study, or a reset build, is a new folder, and an in-place upgrade reuses the folder.
Other folders may still run on the host and take memory from this one without appearing in it (the memory ledger's
`shared_memory_holders` names them).

The project runs on Python 3.13 in the folder's `.venv`, an interpreter uv manages. The system `python3` is newer than
the Rust engine's PyO3 builds for (0.23, whose ceiling is 3.13), so nothing project-related runs on it; the lock stops
below 3.14 (`requires-python >=3.12, <3.14`) for the same reason, until a later PyO3 lifts it. The host's Rust is
rustup's stable toolchain, not the `rust` package (`docs/OPERATIONS.md`, "The worker count and the Rust toolchain",
says what a broken one looks like and what mends it).

Bring-up from a base install, idempotent:

    ./tools/setup_host.sh            # pacman deps, rust toolchain, uv sync, folder PostgreSQL
    ./tools/setup_host.sh --verify   # check only

It installs whichever of `python uv zstd git base-devel` is missing via pacman, and `rustup` when there is no cargo,
sets the stable Rust toolchain, installs maturin as a uv tool, syncs the project with `uv sync --extra dev`, builds the
Rust engine (`tools/build_engine.sh`), and brings up the folder-local PostgreSQL 17 (the pinned OCI payload in an
unprivileged user namespace; no system PostgreSQL, no sudo for the database). A build arrives as `GSD<N>.tar.zst` and
is deployed with the operator's own `apply_build.py`, which lives on the host. They run a tool as `uv run python
tools/<tool>.py`.

Fish, not bash. Exports are `set -x NAME value`; globs that match nothing are an error; heredocs do not exist, so
multi-line Python goes through `uv run python -c '...'` with double quotes inside and no backslash escapes. Every
command the operator is asked to type (`docs/OPERATIONS.md`, the README's "Running it") is written for fish; the
sandbox's (`docs/agent/ENVIRONMENT.md`) are bash.

## The agent sandbox

Ubuntu 24.04 (the assistant's container; 2 cores and 7 GB, Python 3.12), root by default, with `uv` for root.
Outbound traffic goes through a proxy whose CA bundle only root can read. PyPI has been reachable, crates.io and rustup
in some sandboxes and not others, Docker Hub never. **The route that works is `docs/agent/ENVIRONMENT.md`, section 10,
the cold start in order**, which `./tools/prepare_environment.sh` does as root: host PostgreSQL 16 binaries (the OCI
image cannot be fetched), root's Rust toolchain, the venv and the engine from `uv.lock`, handed to the unprivileged
user, who runs everything project-related.

## What both guarantee, and what neither does

After `tools/setup_host.sh`, or a completed `tools/prepare_environment.sh`, the unit, contract, integration and
scientific lanes run and the Rust engine extension is installed; the folder-local PostgreSQL starts at the first lane.
Neither starts or uses a system PostgreSQL cluster or edits a shell profile, and the sandbox script builds its venv
outside the tree, never in the system Python. Neither is run mid-campaign: both are for a fresh host or sandbox.
