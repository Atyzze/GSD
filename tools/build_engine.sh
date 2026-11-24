#!/usr/bin/env bash
# Build and install the Rust engine extension (gsd_engine_rs) into the
# project's Python. Build 321. Idempotent; needs cargo and maturin on PATH
# (tools/setup_host.sh on the research host, tools/prepare_environment.sh in
# the sandbox). Run after every apply_build that changes engine_rs/.
#
#   ./tools/build_engine.sh            release build, install, print fingerprint
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/engine_rs"
OUT="$ROOT/var/wheels"
mkdir -p "$OUT"
# Build against the project's interpreter, never the system one: on an Arch
# host /usr/bin/python3 is ahead of what PyO3 supports and the extension has
# to load in the venv anyway (build 323; the 322 script found 3.14 and failed).
if [ -x "$ROOT/.venv/bin/python" ]; then INTERP="$ROOT/.venv/bin/python"; else INTERP="$(command -v python3)"; fi
maturin build --release -i "$INTERP" -o "$OUT" >/dev/null
WHEEL="$(ls -t "$OUT"/gsd_engine_rs-*.whl | head -n 1)"
if command -v uv >/dev/null && [ -d "$ROOT/.venv" ]; then
  (cd "$ROOT" && uv pip install --force-reinstall "$WHEEL" >/dev/null)
else
  pip install --force-reinstall "$WHEEL" --break-system-packages -q 2>/dev/null || pip install --force-reinstall "$WHEEL" -q
fi
cd "$ROOT"
python3 -c "import gsd_engine_rs; print('gsd_engine_rs', gsd_engine_rs.FINGERPRINT, 'installed')" 2>/dev/null \
  || uv run python -c "import gsd_engine_rs; print('gsd_engine_rs', gsd_engine_rs.FINGERPRINT, 'installed')"
