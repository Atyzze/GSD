from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "fixtures" / "committed_readings.json"


def test_every_committed_reading_is_the_bytes_it_was_committed_with():
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    changed = {name: digest for name, digest in files.items()
               if not (ROOT / name).is_file() or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest}
    assert not changed, (
        f"changed or gone after it was committed: {sorted(changed)}. A criterion, design or reading is never "
        "edited after the run it describes; a new one is a new file with its own line in the manifest")
