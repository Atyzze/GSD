#!/usr/bin/env bash
#
# SETUP_HOST.sh -- bring the research host from a base Arch/CachyOS install to
# a state where GSD runs: campaigns, the folder-local PostgreSQL, the Rust
# engine build, the test lanes.
#
# Target environment (docs/agent/TARGET_ENVIRONMENT.md): Arch Linux / CachyOS,
# systemd, KDE, fish, pacman. Python is installed only when the host has none;
# the project runs on the one uv manages. Safe to re-run; every step checks before acting.
#
#   ./tools/setup_host.sh            full bring-up
#   ./tools/setup_host.sh --verify   check only
#
# What it does NOT do: touch a system PostgreSQL. GSD runs its own pinned
# PostgreSQL 17 OCI payload inside an unprivileged user namespace under the
# project folder (tools/postgres_instance.py); the host only needs userns.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-full}"
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
FAILED=0
need_pkgs=()

step "0  Base"
if command -v pacman >/dev/null; then ok "pacman present (Arch lineage)"; else bad "not an Arch lineage host; this script targets Arch/CachyOS only"; exit 2; fi
if [ "$(id -u)" = 0 ]; then bad "run as your user, not root; pacman steps use sudo"; exit 2; fi
MAXNS="$(cat /proc/sys/user/max_user_namespaces 2>/dev/null || echo 0)"
if [ "$MAXNS" -gt 0 ] 2>/dev/null; then ok "unprivileged user namespaces available ($MAXNS)"; else bad "max_user_namespaces is 0; the folder-local PostgreSQL cannot start"; FAILED=1; fi

step "1  Packages"
for pkg in python uv zstd git base-devel; do
  if pacman -Qi "$pkg" >/dev/null 2>&1; then ok "$pkg"; else warn "$pkg missing"; need_pkgs+=("$pkg"); fi
done
# Either the `rust` package or rustup provides cargo; they conflict, so ask
# for cargo, not for a package name (build 323).
if command -v cargo >/dev/null; then ok "cargo ($(cargo --version))"; else warn "no cargo; installing rustup"; need_pkgs+=("rustup"); fi
if [ ${#need_pkgs[@]} -gt 0 ]; then
  if [ "$MODE" = "--verify" ]; then FAILED=1; else
    sudo pacman -S --needed --noconfirm "${need_pkgs[@]}" && ok "installed ${need_pkgs[*]}" || { bad "pacman install failed"; FAILED=1; }
  fi
fi

step "2  Rust toolchain (for the engine extension)"
if command -v cargo >/dev/null && rustc --version >/dev/null 2>&1; then
  ok "$(rustc --version)"
else
  if [ "$MODE" = "--verify" ]; then bad "no rust toolchain"; FAILED=1; else
    rustup default stable && ok "$(rustc --version)" || { bad "rustup default stable failed"; FAILED=1; }
  fi
fi
if command -v maturin >/dev/null || uv tool list 2>/dev/null | grep -q maturin; then ok "maturin"; else
  if [ "$MODE" = "--verify" ]; then warn "maturin not installed (uv tool install maturin)"; else
    uv tool install maturin >/dev/null 2>&1 && ok "maturin (uv tool)" || warn "maturin install failed; the Rust engine build needs it"
  fi
fi

step "3  Python project"
cd "$ROOT"
if [ "$MODE" = "--verify" ]; then
  # What the fleet runs, not the dev extra: `uv run` syncs the environment to the project's own dependencies, so the
  # dev extra's zstandard (686) was removed by every `uv run` and this check failed after `uv sync` too (the
  # operator's host, 2026-10-31).
  uv run python -c "import graph_scale_dynamics, psycopg" 2>/dev/null && ok "project importable" || { bad "project not importable: run ./tools/setup_host.sh"; FAILED=1; }
else
  uv sync --extra dev >/dev/null 2>&1 && ok "uv sync --extra dev" || { bad "uv sync failed"; FAILED=1; }
fi

step "3b Rust engine extension"
if [ "$MODE" = "--verify" ]; then
  uv run python -c "import gsd_engine_rs" 2>/dev/null && ok "gsd_engine_rs importable" || warn "not built (./tools/build_engine.sh)"
else
  ./tools/build_engine.sh >/dev/null 2>&1 && ok "gsd_engine_rs built and installed" || { bad "engine build failed (cargo/maturin?)"; FAILED=1; }
fi

step "4  Folder-local PostgreSQL"
if [ "$MODE" = "--verify" ]; then
  [ -f "$ROOT/.env.postgres" ] && ok ".env.postgres present" || warn "not initialised (python3 tools/postgres_instance.py init)"
else
  uv run python tools/postgres_instance.py init >/dev/null 2>&1; uv run python tools/postgres_instance.py ensure 2>&1 | tail -n 1
  uv run python main.py init >/dev/null 2>&1 && ok "cluster up, schema initialised" || { bad "postgres bring-up failed"; FAILED=1; }
fi

step "Summary"
if [ "$FAILED" = 0 ]; then ok "host ready"; else bad "some steps failed; see above"; fi
echo "  Acceptance: uv run python main.py selftest --quick"
exit $FAILED
