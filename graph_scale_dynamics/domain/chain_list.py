from __future__ import annotations

FROM_EMPTY = "empty"
GIVEN = "given"
RANDOM_START_LABELS = ("family_random_mean_degree_", "erdos_renyi_mean_degree_")


def is_a_random_start(label) -> bool:
    return isinstance(label, str) and label.startswith(RANDOM_START_LABELS)


def is_a_twin(name: str, label) -> bool:
    return name == FROM_EMPTY or (name == GIVEN and is_a_random_start(label))


def twin_names(envelope: dict | None) -> list[str]:
    return [str(row.get("start")) for row in records(envelope) if is_a_twin(str(row.get("start")), row.get("init"))]


def records(envelope: dict | None) -> list[dict]:
    return list((envelope or {}).get("chains") or [])


def blocks(envelope: dict | None) -> list[dict]:
    return list(((envelope or {}).get("sampling_checkpoint") or {}).get("chains") or [])


def record(envelope: dict | None, name: str) -> dict:
    return next((row for row in records(envelope) if row.get("start") == name), {})


def block(envelope: dict | None, name: str) -> dict:
    return next((row for row in blocks(envelope) if row.get("start") == name), {})


def more_names(envelope: dict | None) -> list[str]:
    return [str(row.get("start")) for row in records(envelope) if row.get("start") not in (FROM_EMPTY, GIVEN)]


def has_more(envelope: dict | None) -> bool:
    return bool(more_names(envelope))


def trajectory(envelope: dict | None, name: str = FROM_EMPTY) -> list:
    return list(block(envelope, name).get("trajectory") or [])


def edges(envelope: dict | None, name: str) -> list:
    return block(envelope, name).get("edge_list") or []


def sorted_edges(envelope: dict | None, name: str = FROM_EMPTY) -> list[tuple[int, int]]:
    return sorted((int(edge[0]), int(edge[1])) for edge in edges(envelope, name))


def move_accounting(envelope: dict | None) -> dict:
    return {str(row["start"]): row.get("accounting") for row in records(envelope) if not row.get("skipped")}


def timing(envelope: dict | None) -> dict:
    rows = records(envelope)
    if not rows:
        return {}
    return {"chain_seconds": {str(row["start"]): float(row.get("seconds") or 0.0) for row in rows}}


MORE = "more_given"


def of_chain(section: dict | None, name: str):
    section = section if isinstance(section, dict) else {}
    if name in section and name != MORE:
        return section[name]
    if name in (FROM_EMPTY, GIVEN):
        return None
    return (section.get(MORE) or {}).get(name)


def chains_in(section: dict | None) -> dict:
    section = section if isinstance(section, dict) else {}
    out = {str(name): value for name, value in section.items() if name != MORE}
    out.update({str(name): value for name, value in (section.get(MORE) or {}).items()})
    return out


def chain_probes(metrics: dict | None) -> dict:
    found = (metrics or {}).get("chain_probes")
    return dict(found) if isinstance(found, dict) else {}


def probes_of(metrics: dict | None, name: str) -> dict | None:
    return chain_probes(metrics).get(name)


def checkpoint_block(checkpoint: dict | None, name: str) -> dict:
    return next((row for row in (checkpoint or {}).get("chains") or [] if row.get("start") == name), {})


def ran_names(envelope: dict | None) -> list[str]:
    return [str(row.get("start")) for row in records(envelope)
            if not row.get("skipped") and block(envelope, str(row.get("start")))]
