from __future__ import annotations

import math
import os

EXTENSION_FROM_N = int(os.environ.get("GSD_EXTENSION_FROM_N", "16384"))
EXTENSION_SHARE = float(os.environ.get("GSD_EXTENSION_SHARE", "0.5"))


def extension_places(workers: int) -> int:
    return math.floor(EXTENSION_SHARE * max(0, int(workers)))


def extension_first(extension_leased: int, leased: int) -> bool:
    return int(extension_leased) < extension_places(int(leased) + 1)
