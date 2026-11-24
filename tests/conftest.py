from __future__ import annotations

import os

from graph_scale_dynamics.operations.process_ownership import die_with_owner

die_with_owner()

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"

os.environ.setdefault("GSD_MEMBW_SOURCE", "off")
if not os.environ.get("GSD_VOLATILE_DIR") and os.path.isdir("/dev/shm"):
    _suite_scratch = os.path.join("/dev/shm", f"gsd-tests-{os.getuid()}")
    os.makedirs(_suite_scratch, exist_ok=True)
    os.environ["GSD_VOLATILE_DIR"] = _suite_scratch


pytest_plugins = ["tests.support.postgres"]
