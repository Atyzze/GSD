from __future__ import annotations

from pathlib import Path

from graph_scale_dynamics.resources import committed


class Readings(type(Path())):
    def __truediv__(self, name):
        here = super().__truediv__(name)
        if here.exists() or not isinstance(name, str) or "/" in name:
            return here
        moved = committed.directory(self.parent.parent) / name
        return moved if moved.exists() else here


def readings(root) -> Readings:
    return Readings(Path(root) / "docs" / "readings")
