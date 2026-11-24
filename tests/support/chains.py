from __future__ import annotations

from graph_scale_dynamics.domain import chain_list as CL

RANDOM_START = "erdos_renyi_mean_degree_8"
RECORD_FIELDS = ("init", "kernel", "sweeps", "termination", "skipped", "skipped_reason", "ended", "late", "final",
                 "final_structure", "acceptance", "accepted_moves", "accounting", "seconds", "stream")


def chain(name: str, *, block: dict | None = None, **record) -> tuple[dict, dict | None]:
    unknown = set(record) - set(RECORD_FIELDS)
    if unknown:
        raise ValueError(f"not a field of a chain's record: {sorted(unknown)}")
    return dict(record, start=name), (None if block is None else dict(block, start=name))


def envelope(n: int, *chains: tuple[dict, dict | None], **top) -> dict:
    out = dict(top, n=n, chains=[record for record, _block in chains])
    out["sampling_checkpoint"] = dict(out.get("sampling_checkpoint") or {},
                                      chains=[block for _record, block in chains if block is not None])
    return out


def pair(n: int, from_empty: list, given: list | None = None, *, empty: dict | None = None,
         given_record: dict | None = None, empty_block: dict | None = None, given_block: dict | None = None,
         **top) -> dict:
    chains = [chain(CL.FROM_EMPTY, block=dict(empty_block or {}, trajectory=from_empty), **(empty or {}))]
    if given is not None or given_record is not None or given_block is not None:
        block = None if given is None and given_block is None else dict(given_block or {}, trajectory=given or [])
        chains.append(chain(CL.GIVEN, block=block, **{"init": RANDOM_START, **(given_record or {})}))
    return envelope(n, *chains, **top)
