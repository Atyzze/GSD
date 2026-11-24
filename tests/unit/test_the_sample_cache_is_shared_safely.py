from __future__ import annotations

import os
import threading


def test_a_sample_written_while_the_cache_is_pruned_breaks_nothing(monkeypatch):
    from graph_scale_dynamics.services.api import host
    monkeypatch.setattr(host, "_SERVICE_PROC_SAMPLES", {2 ** 22 + i: (0.0, 0.0, None, None) for i in range(80)})
    real = host.psutil.pid_exists

    def another_thread_writes(pid):
        host._SERVICE_PROC_SAMPLES[2 ** 23 + pid % 7] = (0.0, 0.0, None, None)
        return real(pid)

    monkeypatch.setattr(host.psutil, "pid_exists", another_thread_writes)
    out = host._service_process_sample(os.getpid())
    assert out["process_state"] != "missing"
    assert os.getpid() in host._SERVICE_PROC_SAMPLES and not any(2 ** 22 <= p < 2 ** 22 + 80
                                                                  for p in host._SERVICE_PROC_SAMPLES)


def test_threads_sampling_at_once_all_answer(monkeypatch):
    from graph_scale_dynamics.services.api import host
    monkeypatch.setattr(host, "_SERVICE_PROC_SAMPLES", {2 ** 22 + i: (0.0, 0.0, None, None) for i in range(200)})
    failures = []

    def sample():
        try:
            for _ in range(50):
                host._service_process_sample(os.getpid())
                host._service_process_sample(2 ** 22 + 5)
        except Exception as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [threading.Thread(target=sample) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures, failures
