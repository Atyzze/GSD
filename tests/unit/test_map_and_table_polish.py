from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_cpu_sampler_is_rate_limited_across_callers():
    from graph_scale_dynamics.observability import host_resources as H

    H._CPU_SAMPLE.update(at=0.0, value=None)
    first = H.cpu_percent_sampled(now=1000.0)
    H._CPU_SAMPLE.update(at=1000.0, value=37.5)
    assert H.cpu_percent_sampled(now=1000.2) == 37.5, "inside the interval the last reading is returned"
    assert first is None or isinstance(first, float)
