#!/usr/bin/env bash
# Bring a fresh agent sandbox up to where every lane and the release run: docs/agent/ENVIRONMENT.md,
# section 10, steps 1 to 10, in order (rewritten at 644; the script before it had not completed since 537).
# The operator, 2026-10-22: it is for the agent's side, "so that whenever I upload the archive in a new text
# window the agent doesnt waste time setting up their environment".
#
#   setsid nohup ./tools/prepare_environment.sh > /home/claude/prepare.log 2>&1 < /dev/null &   # as root
#   ./tools/prepare_environment.sh --check     # reports each step's state and writes nothing
#
# Every step looks first and skips what is done, so it runs again safely on a sandbox that holds the project.
# A step that needs the network says what failed and stops. Paths are the section's defaults, each overridable:
set -uo pipefail

TREE="${GSD_TREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
USER_NAME="${GSD_USER:-claude}"
HOME_DIR="${GSD_HOME:-/home/$USER_NAME}"
VENV="${GSD_VENV:-$HOME_DIR/venv}"
PREFIX="${GSD_PREFIX:-$HOME_DIR/prefix.sh}"
BIN="${GSD_BIN:-$HOME_DIR/bin}"
CA="${GSD_CA:-$HOME_DIR/ca-bundle.crt}"
SCRATCH="${GSD_SCRATCH:-/dev/shm/gsd-$USER_NAME}"
PG_BIN="/usr/lib/postgresql/${GSD_PG_MAJOR:-16}/bin"
PYTHON="${GSD_PYTHON:-/usr/bin/python3.12}"
ROOT_CA="${SSL_CERT_FILE:-}"
[ -d /root/.cargo/bin ] && PATH="/root/.cargo/bin:$PATH"
[ -d /root/.local/bin ] && PATH="/root/.local/bin:$PATH"
ROOT_UV="$(command -v uv || true)"

CHECK=0
case "${1:-}" in
  --check) CHECK=1 ;;
  "") ;;
  *) echo "usage: $0 [--check]"; exit 2 ;;
esac
[ "$(id -u)" = 0 ] || { echo "run as root: the user '$USER_NAME' is made to own what this sets up"; exit 2; }

PENDING=0
step() { printf '\n%s\n' "$*"; }
done_() { echo "  done: $*"; }
todo() { echo "  to do: $*"; PENDING=1; }
stop() { echo "  FAILED: $*"; echo "stopped; fix the above and run again (every step done is skipped)"; exit 1; }
as_user() { su "$USER_NAME" -s /bin/bash -c ". '$PREFIX' && $*"; }

step "1  Packages: PostgreSQL ${GSD_PG_MAJOR:-16}, zstd, btop, and a Rust toolchain for root"
missing=""
[ -x "$PG_BIN/postgres" ] && [ -x "$PG_BIN/initdb" ] || missing="$missing postgresql-${GSD_PG_MAJOR:-16}"
command -v zstd >/dev/null || missing="$missing zstd"
command -v btop >/dev/null || missing="$missing btop"
if [ -z "$missing" ]; then done_ "packages present"
elif [ "$CHECK" = 1 ]; then todo "apt-get install$missing"
else
  apt-get update >/dev/null 2>&1   # often exits non-zero on an unreachable third-party source: the install decides
  # shellcheck disable=SC2086
  apt-get install -y $missing >/dev/null 2>&1 || stop "apt-get install$missing (the Ubuntu archives unreachable?)"
  done_ "installed$missing"   # "policy-rc.d denied execution of start" is wanted: the system cluster is never used
fi
if command -v cargo >/dev/null; then done_ "cargo for root ($(cargo --version))"
elif [ "$CHECK" = 1 ]; then todo "rustup for root"
else
  curl -sSf https://sh.rustup.rs -o /tmp/rustup-init.sh && sh /tmp/rustup-init.sh -y --profile minimal \
    --default-toolchain stable >/dev/null 2>&1 || stop "rustup (sh.rustup.rs unreachable?): the engine cannot be built"
  PATH="/root/.cargo/bin:$PATH"; done_ "rustup installed ($(cargo --version))"   # Ubuntu's cargo is too old for PyO3
fi
[ -n "$ROOT_UV" ] || stop "no uv for root; install it (pip install --break-system-packages uv) and run again"

step "2  The tree: one commit of it as distributed"
if [ -d "$TREE/.git" ]; then done_ "git history present ($(git -c safe.directory='*' -C "$TREE" log --oneline -1))"
elif [ "$CHECK" = 1 ]; then todo "git init and the baseline commit in $TREE"
else
  git -C "$TREE" init -q && git -C "$TREE" add -A && git -c safe.directory='*' -C "$TREE" commit -qm \
    "Baseline: Build $(cat "$TREE/BUILD_NUMBER") as distributed" || stop "the baseline commit (root's git identity?)"
  done_ "baseline committed"
fi
git config --global --get-all safe.directory 2>/dev/null | grep -qx '\*' || {
  [ "$CHECK" = 1 ] && todo "git config --global --add safe.directory '*' (root clones the user's tree)" \
    || git config --global --add safe.directory '*'; }

step "3  Signing"
echo "  commit.gpgsign=$(git config --global --get commit.gpgsign || echo unset): where true, commit as root and chown after"

step "4  What the user cannot reach under /root: the CA bundle and uv"
if [ -z "$ROOT_CA" ]; then done_ "no proxy CA in root's SSL_CERT_FILE; nothing to copy"
elif cmp -s "$ROOT_CA" "$CA"; then done_ "$CA"
elif [ "$CHECK" = 1 ]; then todo "copy $ROOT_CA to $CA"
else install -D -m 644 "$ROOT_CA" "$CA" && done_ "copied $CA"; fi
if cmp -s "$ROOT_UV" "$BIN/uv"; then done_ "$BIN/uv"
elif [ "$CHECK" = 1 ]; then todo "copy $ROOT_UV to $BIN/uv"
else install -D -m 755 "$ROOT_UV" "$BIN/uv" && done_ "copied $BIN/uv"; fi

step "5  The venv, from the lock, with the Rust engine"
crate="$(sed -n 's/^version *= *"\(.*\)"/\1/p' "$TREE/engine_rs/pyproject.toml" | head -1)"
venv_ok() {
  [ -x "$VENV/bin/python" ] && [ -x "$VENV/bin/maturin" ] && "$VENV/bin/python" - "$crate" <<'EOF' 2>/dev/null
import sys, importlib.metadata as m
import graph_scale_dynamics, gsd_engine_rs, pytest, psycopg, zstandard  # noqa: F401
sys.exit(m.version("gsd-engine-rs") != sys.argv[1])
EOF
}
if venv_ok; then done_ "$VENV (engine $crate)"
elif [ "$CHECK" = 1 ]; then todo "uv sync into $VENV (engine $crate)"
else
  (cd "$TREE" && UV_PROJECT_ENVIRONMENT="$VENV" nice -n 19 uv sync --frozen --extra dev --python "$PYTHON") \
    || stop "uv sync (PyPI or crates.io unreachable, or no cargo): see the lines above"
  uv pip install -q --python "$VENV/bin/python" pip setuptools zstandard maturin || stop "uv pip install (PyPI?)"
  venv_ok && done_ "$VENV (engine $crate)" || stop "the venv is made but does not import the engine $crate"
fi

step "6  The calibration table"
if [ -f "$TREE/calibration/probe_calibration.json" ]; then done_ "the tree has its table (never overwritten)"
elif [ "$CHECK" = 1 ]; then todo "copy the seed into calibration/probe_calibration.json"
elif [ -f "$TREE/calibration/seed_table.json" ]; then
  cp "$TREE/calibration/seed_table.json" "$TREE/calibration/probe_calibration.json"
  done_ "seeded from calibration/seed_table.json, unverified until the suite's gate re-checks a sample of its cells"
else echo "  no table and no seed: the first start measures the startup gate's cells in the foreground"; fi

step "7  The prefix file every command the user runs sources first"
if [ -f "$PREFIX" ]; then done_ "$PREFIX (it enters $(sed -n 's/^cd //p' "$PREFIX"))"
elif [ "$CHECK" = 1 ]; then todo "write $PREFIX"
else
  cat > "$PREFIX" <<EOF
export GSD_POSTGRES_SYSTEM_BIN=$PG_BIN
export GSD_VOLATILE_DIR=$SCRATCH
export PATH=$VENV/bin:$BIN:/opt/node22/bin:/usr/local/bin:/usr/bin:/bin
export PIP_CERT=$CA SSL_CERT_FILE=$CA
export REQUESTS_CA_BUNDLE=$CA NODE_EXTRA_CA_CERTS=$CA
export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
export NODE_PATH=/opt/node22/lib/node_modules
unset PIP_CONFIG_FILE RUSTUP_HOME
export HOME=$HOME_DIR
cd $TREE
EOF
  chmod 644 "$PREFIX"; done_ "wrote $PREFIX"
fi

step "8  The RAM scratch and the owner"
owned() { [ -z "$(find "$@" ! -user "$USER_NAME" -print -quit 2>/dev/null)" ]; }
if [ -d "$SCRATCH" ] && owned "$SCRATCH" "$VENV" "$BIN" "$TREE" "$HOME_DIR/.cache" "$HOME_DIR/.local"; then done_ "all owned by $USER_NAME"
elif [ "$CHECK" = 1 ]; then todo "mkdir $SCRATCH and chown -R $USER_NAME the scratch, venv, bin, tree, ~/.cache and ~/.local"
else
  mkdir -p "$SCRATCH" "$HOME_DIR/.cache" "$HOME_DIR/.local"
  chown -R "$USER_NAME:$USER_NAME" "$SCRATCH" "$VENV" "$BIN" "$TREE" "$HOME_DIR/.cache" "$HOME_DIR/.local"
  done_ "owned by $USER_NAME (again after a sandbox restart, and before every lane once root has run anything)"
fi

step "9  The lock's cache, for the release's offline check"
if [ "$CHECK" = 1 ] && [ ! -f "$PREFIX" ]; then todo "uv lock --check, once the prefix exists"
elif as_user "uv lock --check --offline" >/dev/null 2>&1; then done_ "uv lock --check --offline passes"
elif [ "$CHECK" = 1 ]; then todo "uv lock --check, online, as $USER_NAME"
else as_user "uv lock --check" || stop "uv lock --check (PyPI unreachable?)"; done_ "the lock's cache filled"; fi

step "10 A quick check: PostgreSQL, the engine and node (about 70 seconds)"
if [ "$CHECK" = 1 ]; then echo "  not run by --check"
else
  as_user "nice -n 19 python3 -m pytest -q -p no:cacheprovider tests/unit/test_build_identity.py \
    tests/unit/test_the_starts_decide_depth.py tests/integration/test_parked_laws_are_decided_again_postgres.py \
    tests/unit/test_candidate_smoke.py tests/unit/test_the_starts_are_read.py \
    tests/scientific/test_engine_parity.py" | tail -3 || stop "the quick check: read its failures above"
  done_ "the quick check passed"
fi

[ "$CHECK" = 1 ] && [ "$PENDING" = 1 ] && { echo; echo "some steps are not done"; exit 1; }
echo; echo "ready: every command as the user starts with: su $USER_NAME -s /bin/bash -c \". $PREFIX && ...\""
