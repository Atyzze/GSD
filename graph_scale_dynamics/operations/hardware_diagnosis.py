from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def diagnose_hardware(args, *, build_number) -> int:
    from graph_scale_dynamics.services.api import host

    exact_energy = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
    exact_value, exact_error = host._read_number_diagnostic(exact_energy)
    stat_info = None
    try:
        st = exact_energy.stat()
        stat_info = {
            "mode": oct(st.st_mode & 0o7777),
            "uid": st.st_uid,
            "gid": st.st_gid,
            "readable_by_process": os.access(exact_energy, os.R_OK),
        }
    except OSError as exc:
        stat_info = {"stat_error": f"{exc.__class__.__name__}: {exc}"}

    host._RAPL_ENERGY_STATE.clear()
    host._stop_btop_sidecar()
    first = host._rapl_power_snapshot_detailed()
    time.sleep(max(0.1, float(args.sample_seconds)))
    second = host._rapl_power_snapshot_detailed()

    temp, temp_source, temp_path = host._cpu_temperature_snapshot()
    configured_sensor, btop_config_path = host._btop_configured_cpu_sensor()
    sensors = host._btop_hwmon_temperature_sensors()
    sidecar = host._btop_telemetry_status()
    membw_sample = host.MEMBW_MONITOR.snapshot(
        start=True, wait_seconds=max(0.0, float(args.membw_wait_seconds))
    )
    membw_status = host.MEMBW_MONITOR.status()

    btop_path = shutil.which("btop")
    btop_version = None
    btop_capabilities = None
    getcap = shutil.which("getcap")
    if btop_path:
        try:
            proc = subprocess.run([btop_path, "--version"], text=True, capture_output=True,
                                  timeout=3, check=False)
            btop_version = (proc.stdout or proc.stderr).strip() or None
        except (OSError, subprocess.SubprocessError):
            pass
        if getcap:
            try:
                proc = subprocess.run([getcap, btop_path], text=True, capture_output=True,
                                      timeout=3, check=False)
                btop_capabilities = proc.stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                pass

    payload = {
        "build": build_number,
        "power": {
            "btop_exact_path": str(exact_energy),
            "exact_counter_readable": exact_value is not None,
            "exact_counter_error": exact_error,
            "exact_counter_value_uj": exact_value,
            "file": stat_info,
            "first_sample": {"watts": first[0], "limit_watts": first[1], "detail": first[2]},
            "second_sample": {"watts": second[0], "limit_watts": second[1], "detail": second[2]},
            "btop_sidecar": sidecar,
            "privileged_setup_required": False,
        },
        "temperature": {
            "selected_celsius": temp,
            "selected_sensor": temp_source,
            "selected_path": temp_path,
            "gsd_override": os.environ.get("GSD_CPU_SENSOR") or None,
            "btop_config_path": btop_config_path,
            "btop_configured_sensor": configured_sensor,
            "discovered": sensors,
        },
        "memory_bandwidth": {
            "sample": membw_sample,
            "backend": membw_status,
        },
        "btop": {
            "path": btop_path,
            "version": btop_version,
            "capabilities": btop_capabilities,
            "usage": "existing btop file capabilities are used only by the btop sidecar; GSD/Python receives none",
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0
