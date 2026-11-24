from __future__ import annotations

from decimal import Decimal
import datetime as dt
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np


def _json_path(parent: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    text = str(key)
    return f"{parent}.{text}" if parent else text


def sanitize_json(payload: Any, *, max_examples: int = 32) -> tuple[Any, dict]:
    clean, diagnostics = _sanitizer(max_examples)
    return clean(payload, "$"), _totals(diagnostics)


def _sanitizer(max_examples: int):
    diagnostics = {
        "nonfinite_values_replaced": 0,
        "converted_values": 0,
        "key_collisions": 0,
        "examples": [],
    }

    def note(path: str, kind: str, value: Any) -> None:
        if len(diagnostics["examples"]) < int(max_examples):
            diagnostics["examples"].append({
                "path": path or "$",
                "kind": kind,
                "value": str(value),
            })

    def clean(value: Any, path: str) -> Any:
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            diagnostics["nonfinite_values_replaced"] += 1
            note(path, "nonfinite_float_replaced_with_null", value)
            return None
        if isinstance(value, Decimal):
            try:
                out = float(value)
            except (TypeError, ValueError, OverflowError):
                diagnostics["converted_values"] += 1
                note(path, "decimal_converted_to_string", value)
                return str(value)
            if not math.isfinite(out):
                diagnostics["nonfinite_values_replaced"] += 1
                note(path, "nonfinite_decimal_replaced_with_null", value)
                return None
            diagnostics["converted_values"] += 1
            return out
        if isinstance(value, np.generic):
            diagnostics["converted_values"] += 1
            return clean(value.item(), path)
        if isinstance(value, np.ndarray):
            diagnostics["converted_values"] += 1
            return clean(value.tolist(), path)
        if isinstance(value, (dt.datetime, dt.date, dt.time)):
            diagnostics["converted_values"] += 1
            return value.isoformat()
        if isinstance(value, Path):
            diagnostics["converted_values"] += 1
            return str(value)
        if isinstance(value, memoryview):
            diagnostics["converted_values"] += 1
            return bytes(value).hex()
        if isinstance(value, (bytes, bytearray)):
            diagnostics["converted_values"] += 1
            return bytes(value).hex()
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                skey = key if isinstance(key, str) else str(key)
                if skey != key:
                    diagnostics["converted_values"] += 1
                if skey in out:
                    diagnostics["key_collisions"] += 1
                    note(_json_path(path, skey), "stringified_key_collision_overwrote_value", key)
                out[skey] = clean(item, _json_path(path, skey))
            return out
        if isinstance(value, (set, frozenset)):
            diagnostics["converted_values"] += 1
            cleaned_members = [clean(item, _json_path(path, i)) for i, item in enumerate(value)]
            try:
                return sorted(cleaned_members, key=lambda m: (type(m).__name__, repr(m)))
            except TypeError:  # pragma: no cover
                diagnostics["converted_values"] += 1
                note(path, "unorderable_set_left_in_iteration_order", type(value).__name__)
                return cleaned_members
        if isinstance(value, (list, tuple)):
            if not isinstance(value, list):
                diagnostics["converted_values"] += 1
            return [clean(item, _json_path(path, i)) for i, item in enumerate(value)]

        diagnostics["converted_values"] += 1
        note(path, "unsupported_scalar_converted_to_string", type(value).__name__)
        return str(value)

    return clean, diagnostics


def _totals(diagnostics: dict) -> dict:
    diagnostics["total_values_changed"] = (
        diagnostics["nonfinite_values_replaced"] + diagnostics["converted_values"]
    )
    diagnostics["examples_truncated"] = (
        diagnostics["total_values_changed"] > len(diagnostics["examples"])
    )
    return diagnostics


def _path_of(chain) -> str:
    keys = []
    while type(chain) is tuple:
        chain, key = chain
        keys.append(key)
    for key in reversed(keys):
        chain = _json_path(chain, key)
    return chain


def _plain(value: Any) -> Any:
    kind = type(value)
    if kind is dict:
        if any(type(key) is not str for key in value):
            return {(key if type(key) is str else str.__str__(key)): _plain(item) for key, item in value.items()}
        for key, item in value.items():
            if type(item) not in _PLAIN:
                value[key] = _plain(item)
        return value
    if kind is list:
        for index, item in enumerate(value):
            if type(item) not in _PLAIN:
                value[index] = _plain(item)
        return value
    if kind in _PLAIN:
        return value
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, int):
        return int.__int__(value)
    if isinstance(value, float):
        return float.__float__(value)
    return value


_PLAIN = frozenset({str, int, float, bool, type(None)})


def _alone_in_dict_loop() -> int:
    for _key, item in {"probe": []}.items():
        return sys.getrefcount(item)
    raise AssertionError("unreachable")


def _alone_in_list_loop() -> int:
    for _index, item in enumerate([[]]):
        return sys.getrefcount(item)
    raise AssertionError("unreachable")


def sanitize_json_in_place(payload: Any, *, max_examples: int = 32) -> tuple[Any, dict]:
    clean, diagnostics = _sanitizer(max_examples)
    getrefcount, isfinite = sys.getrefcount, math.isfinite
    alone_in_dict, alone_in_list = _alone_in_dict_loop(), _alone_in_list_loop()
    plain = _PLAIN - {float}

    def copied(item, chain):
        return _plain(clean(item, _path_of(chain)))

    def settle(value, chain):
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    return copied(value, chain)
                kind = type(item)
                if kind in plain or kind is float and isfinite(item):
                    continue
                if (kind is dict or kind is list) and getrefcount(item) <= alone_in_dict:
                    value[key] = settle(item, (chain, key))
                else:
                    value[key] = copied(item, (chain, key))
            return value
        for index, item in enumerate(value):
            kind = type(item)
            if kind in plain or kind is float and isfinite(item):
                continue
            if (kind is dict or kind is list) and getrefcount(item) <= alone_in_list:
                value[index] = settle(item, (chain, index))
            else:
                value[index] = copied(item, (chain, index))
        return value

    converted = settle(payload, "$") if type(payload) in (dict, list) else copied(payload, "$")
    return converted, _totals(diagnostics)
