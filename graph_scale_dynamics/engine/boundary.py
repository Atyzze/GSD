from __future__ import annotations

import ctypes
import json
from pathlib import Path

CONTRACT = "gsd-engine-boundary-1"
OPERATIONS = ("init_random_graph", "init_declared", "run_chain", "rebuild_graph")
IN_PROCESS, C_ABI = "in_process", "c_abi"
DOORS = (IN_PROCESS, C_ABI)


class UnknownOperation(ValueError):
    pass


class OutsideCoverage(ValueError):
    pass


FAULTS = {"ValueError": ValueError, "KeyError": KeyError, "FloatingPointError": FloatingPointError,
          "RuntimeError": RuntimeError, "OutsideCoverage": OutsideCoverage}


def _asked(operation: str) -> str:
    if operation not in OPERATIONS:
        raise UnknownOperation(f"the boundary has {OPERATIONS}, not {operation!r}")
    return operation


def in_process(extension):
    def call(operation: str, request: dict) -> dict:
        return extension.call(_asked(operation), request)
    call.door = IN_PROCESS
    return call


def through_the_c_abi(library_path: Path):
    library = ctypes.CDLL(str(library_path))
    library.gsd_engine_call.restype = ctypes.c_void_p
    library.gsd_engine_call.argtypes = (ctypes.c_char_p, ctypes.c_char_p)
    library.gsd_engine_free.restype = None
    library.gsd_engine_free.argtypes = (ctypes.c_void_p,)

    def call(operation: str, request: dict) -> dict:
        answered = library.gsd_engine_call(_asked(operation).encode("utf-8"), json.dumps(request).encode("utf-8"))
        if not answered:
            raise RuntimeError(f"the engine gave no answer to {operation}")
        try:
            text = ctypes.string_at(answered).decode("utf-8")
        finally:
            library.gsd_engine_free(answered)
        found = json.loads(text)
        fault = found.get("fault")
        if fault is not None:
            raise FAULTS.get(str(fault.get("kind")), RuntimeError)(str(fault.get("message")))
        return found["answer"]
    call.door = C_ABI
    return call
