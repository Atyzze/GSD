from __future__ import annotations

import hashlib
import json
import random
from typing import Any

STREAM_VERSION = "rr-rng-stream-v1"


def _canonical_material(namespace: str, components: tuple[Any, ...]) -> bytes:
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("random stream namespace must be a non-empty string")
    payload = {
        "version": STREAM_VERSION,
        "namespace": namespace,
        "components": components,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def derive_seed(namespace: str, *components: Any) -> int:
    return int.from_bytes(hashlib.sha256(_canonical_material(namespace, components)).digest(), "big")


def stream_id(namespace: str, *components: Any) -> str:
    return hashlib.sha256(_canonical_material(namespace, components)).hexdigest()


def rng(namespace: str, *components: Any) -> random.Random:
    return random.Random(derive_seed(namespace, *components))
