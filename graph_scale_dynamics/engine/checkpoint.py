from __future__ import annotations


def check_edges(n: int, edge_list) -> None:
    seen = set()
    for raw in edge_list:
        u, v = int(raw[0]), int(raw[1])
        if not (0 <= u < n and 0 <= v < n):
            raise ValueError(f"checkpoint edge ({u}, {v}) has an endpoint outside 0..{n}")
        if u == v:
            raise ValueError(f"checkpoint edge ({u}, {v}) is a loop")
        key = (u, v) if u < v else (v, u)
        if key in seen:
            raise ValueError(f"checkpoint edge ({u}, {v}) appears twice")
        seen.add(key)
