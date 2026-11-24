#!/usr/bin/env python3

import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import deque

COUNTER_GLOB = "/sys/fs/resctrl/mon_data/mon_L3_*/mbm_total_bytes"
BLOCKS = " ▁▂▃▄▅▆▇█"
RESET = "\033[0m"

PERF_METRICS = "umc_mem_bandwidth,umc_data_bus_utilization"
CLOCK_EVENT = "amd_umc/umc_mem_clk/"
_UNITS = ("%", "TB/s", "GB/s", "MB/s", "KB/s", "B/s")

DEBUG = False

INTERVAL_LADDER = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]

PLOT_FLOOR_FRAC = 0.02

RATE_BASELINE = 33


def fmt_dur(seconds):
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def parse_interval(text):
    s = str(text).strip().lower()
    try:
        if s.endswith("ms"):
            v = float(s[:-2]) / 1000.0
        elif s.endswith("s"):
            v = float(s[:-1])
        else:
            v = float(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"bad interval {text!r}; try 250ms, 0.5s or 1") from exc
    if v < 0.02:
        raise argparse.ArgumentTypeError("interval must be at least 20ms")
    return v


class Tick:
    def __init__(self, seconds):
        self.value = max(0.02, float(seconds))
        self.generation = 0

    @property
    def ms(self):
        return max(20, int(round(self.value * 1000)))

    def step(self, direction):
        i = min(range(len(INTERVAL_LADDER)),
                key=lambda k: abs(INTERVAL_LADDER[k] - self.value))
        j = max(0, min(len(INTERVAL_LADDER) - 1, i + direction))
        if abs(INTERVAL_LADDER[j] - self.value) < 1e-9:
            return False
        self.value = INTERVAL_LADDER[j]
        self.generation += 1
        return True


def dbg(msg):
    if DEBUG:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


def find_counters():
    return sorted(glob.glob(COUNTER_GLOB))


def read_total(paths):
    total = 0
    for p in paths:
        try:
            with open(p) as f:
                total += int(f.read().strip())
        except (OSError, ValueError):
            pass
    return total


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def vislen(text):
    return len(_ANSI_RE.sub("", text))


def sat_color(frac):
    s = max(0.0, min(1.0, frac))
    if s <= 0.5:
        t = s / 0.5
        r, g, b = int(255 * t), 255, 0
    else:
        t = (s - 0.5) / 0.5
        r, g, b = 255, int(255 * (1 - t)), 0
    return f"\033[38;2;{r};{g};{b}m"


def hbar(frac, width):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled)


def _to_gbps(value, unit):
    u = unit.lower()
    if u.startswith("tb"):
        return value * 1e3
    if u.startswith("mb"):
        return value / 1e3
    if u.startswith("kb"):
        return value / 1e6
    if u == "b" or u.startswith("b/"):
        return value / 1e9
    return value


def parse_perf_row(line):
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    toks = s.split()
    if len(toks) < 2:
        return None
    try:
        ts = float(toks[0])
    except ValueError:
        return None
    for i in range(len(toks) - 1, 0, -1):
        if toks[i] in _UNITS:
            try:
                val = float(toks[i - 1])
            except ValueError:
                return None
            unit = toks[i]
            if unit == "%":
                return ts, "util", val
            return ts, "bw", _to_gbps(val, unit)
    return None


def cap_from_umc_clock(seconds=1.0):
    if shutil.which("perf") is None:
        return None, None
    for events in (f"duration_time,{CLOCK_EVENT}", CLOCK_EVENT):
        got = _clock_probe(events, seconds)
        if got:
            count, window, window_src = got
            gbs = count / window * 2.0 * 8.0 / 1e9
            dbg(f"[cap] umc_mem_clk {count:.0f} in {window:.6f}s "
                f"(window from {window_src}) -> {gbs:.1f} GB/s")
            label = "umc_mem_clk" if window_src == "duration_time" else "umc_mem_clk/wall"
            return gbs, label
    return None, None


def _clock_probe(events, seconds):
    cmd = ["perf", "stat", "-a", "-x", ",", "-e", events,
           "--", "sleep", str(seconds)]
    env = dict(os.environ, LC_ALL="C")
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           timeout=seconds + 15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        dbg(f"[cap] perf clock probe failed: {exc}")
        return None
    elapsed = time.monotonic() - t0
    if elapsed <= 0:
        return None

    count = None
    window, window_src = elapsed, "wall clock"
    for line in p.stderr.splitlines():
        parts = line.split(",")
        if len(parts) < 3:
            continue
        name = parts[2].strip()
        try:
            value = float(parts[0])
        except ValueError:
            continue
        if name == "duration_time":
            if value > 0:
                window, window_src = value / 1e9, "duration_time"
        elif "umc_mem_clk" in name and value > 0:
            count = value if count is None else count + value
    if count is None:
        dbg(f"[cap] no umc_mem_clk row for {events!r}; "
            f"perf said: {p.stderr.strip()[:200]}")
        return None
    return count, window, window_src


def cap_from_dmidecode():
    if shutil.which("dmidecode") is None:
        return None, None
    try:
        out = subprocess.run(["dmidecode", "--type", "17"], capture_output=True,
                             text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    total = 0.0
    for block in out.split("Memory Device")[1:]:
        if "No Module Installed" in block:
            continue
        mt = re.search(r"Configured Memory Speed:\s*(\d+)", block)
        dw = re.search(r"Data Width:\s*(\d+)", block)
        if not mt:
            continue
        width_bytes = (float(dw.group(1)) / 8.0) if dw else 8.0
        total += float(mt.group(1)) * 1e6 * width_bytes / 1e9
    if total > 0:
        dbg(f"[cap] dmidecode -> {total:.1f} GB/s")
        return total, "dmidecode"
    return None, None


def detect_cap(probe_seconds=1.0):
    for fn in (lambda: cap_from_umc_clock(probe_seconds), cap_from_dmidecode):
        cap, src = fn()
        if cap and cap > 0:
            return cap, src
    return None, None


class Scale:
    def __init__(self, cap=None, cap_src="manual", autocap=True):
        self.cap = cap
        self.cap_src = cap_src if cap else "unknown"
        self.autocap = autocap
        self.observed_max = 0.0
        self.observed_min = None
        self.note = None
        self._ratios = deque(maxlen=64)
        self.started = None
        self._last_ts = None
        self._area = 0.0
        self._elapsed = 0.0

    @property
    def mean(self):
        return self._area / self._elapsed if self._elapsed > 0 else 0.0

    @property
    def window(self):
        return (time.monotonic() - self.started) if self.started else 0.0

    def reset_stats(self, current=0.0):
        self.observed_max = current or 0.0
        self.observed_min = current if current else None
        self.started = time.monotonic()
        self._last_ts = self.started
        self._area = 0.0
        self._elapsed = 0.0

    def observe(self, bw, util):
        if bw is not None:
            if bw > self.observed_max:
                self.observed_max = bw
            if self.observed_min is None or bw < self.observed_min:
                self.observed_min = bw
            ts = time.monotonic()
            if self.started is None:
                self.started = ts
            elif self._last_ts is not None:
                dt = ts - self._last_ts
                if 0.0 < dt < 60.0:
                    self._area += bw * dt
                    self._elapsed += dt
            self._last_ts = ts
        if not self.autocap or bw is None or util is None or util < 15.0:
            return
        self._ratios.append(bw / (util / 100.0))
        if len(self._ratios) < 8:
            return
        live = sorted(self._ratios)[len(self._ratios) // 2]
        if self.cap is None:
            self.cap, self.cap_src = live, "bus util"
        elif abs(live - self.cap) / self.cap > 0.10:
            self.note = (f"cap {self.cap:.1f} disagrees with bus util "
                         f"({live:.1f} GB/s) - check the source")

    def adopt(self, cap, src):
        if cap and cap > 0:
            self.cap, self.cap_src = cap, src


def gen_demo(tick, peak):
    import random
    val = peak * 0.1
    while True:
        time.sleep(tick.value)
        if random.random() < 0.05:
            val = random.uniform(peak * 0.4, peak * 0.95)
        val += random.uniform(-1, 1) * peak * 0.05
        val = max(0.0, min(peak, val))
        util = min(100.0, val / peak * 100.0) if peak else None
        yield val, util, None


def gen_mbm(tick, peak):
    paths = find_counters()
    if not paths:
        raise SystemExit(
            "No MBM counters at " + COUNTER_GLOB + "\n"
            "The runtime will not mount/configure resctrl or request root. "
            "Use an already-accessible unprivileged source, or disable this optional telemetry."
        )
    prev = read_total(paths)
    prev_t = time.monotonic()
    last_change = prev_t
    last_glitch = 0.0
    while True:
        time.sleep(tick.value)
        cur = read_total(paths)
        now_t = time.monotonic()
        dt = now_t - prev_t
        delta = cur - prev
        prev, prev_t = cur, now_t
        if dt <= 0 or delta < 0 or dt > tick.value * 10:
            if delta < 0:
                last_glitch = now_t
            status = None
            if now_t - last_glitch < 4:
                status = "MBM returned garbage - unreliable on this CPU (use --source perf)"
            elif now_t - last_change > 3:
                status = "MBM counter not advancing (use --source perf, or reboot)"
            yield None, None, status
            continue
        gbps = delta / dt / 1e9
        if gbps > peak * 1.5:
            last_glitch = now_t
            yield None, None, "MBM returned garbage - unreliable on this CPU (use --source perf)"
            continue
        if delta > 0:
            last_change = now_t
        status = None
        if now_t - last_change > 3:
            status = "MBM counter not advancing (use --source perf, or reboot)"
        yield gbps, None, status


def gen_perf(tick, peak):
    if shutil.which("perf") is None:
        raise SystemExit("perf not found; the runtime does not install host graph_scale_dynamics. Disable this optional telemetry or provide an already-installed unprivileged perf binary.")
    import pty
    import fcntl
    import select
    import struct
    import termios

    env = dict(os.environ, LC_ALL="C")
    t0 = time.monotonic()

    while True:
        spawned_at = tick.generation
        ms = max(50, tick.ms)
        cmd = ["perf", "stat", "-a", "-M", PERF_METRICS, "-I", str(ms), "-x", "\t"]
        dbg(f"[perf] spawning: {cmd!r}")

        master_fd, slave_fd = pty.openpty()
        try:
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", 50, 250, 0, 0))
        except OSError:
            pass
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=slave_fd, close_fds=True, env=env,
            )
        except OSError as e:
            os.close(master_fd)
            os.close(slave_fd)
            raise SystemExit(f"could not start perf: {e}") from e
        os.close(slave_fd)
        dbg(f"[perf] pid={proc.pid} interval={ms}ms")

        group = {}
        last_ts = None
        buf = b""
        respawn = False
        try:
            while True:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if tick.generation != spawned_at:
                    dbg(f"[perf] interval changed -> respawn at {tick.ms}ms")
                    respawn = True
                    break
                if not ready:
                    continue
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    rawb, buf = buf.split(b"\n", 1)
                    raw = rawb.decode("utf-8", "replace")
                    dbg(f"[{time.monotonic()-t0:6.2f}s] raw: {raw!r}")
                    low = raw.lower()
                    if ("permission" in low or "paranoid" in low
                            or "not permitted" in low or "access denied" in low
                            or "consider tweaking" in low):
                        proc.kill()
                        raise SystemExit(
                            "perf lacks unprivileged access to counters. The runtime will not "
                            "change capabilities, sysctls, or request root; disable this optional "
                            "telemetry unless the host already grants access.\n" + raw.strip()
                        )
                    p = parse_perf_row(raw)
                    dbg(f"          parsed: {p}")
                    if p is None:
                        continue
                    ts, kind, value = p
                    if last_ts is not None and ts != last_ts:
                        group = {}
                    last_ts = ts
                    group[kind] = value
                    if "bw" in group and "util" in group:
                        yield group["bw"], group["util"], None
                        group = {}
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                pass
        if not respawn:
            raise SystemExit(f"perf exited (code {proc.poll()}).")


FILE_POLL = 0.01


def gen_file(tick, path, scale=None):
    emit_ts = None
    emit_at = 0.0
    seen_ts = None
    seen_at = None
    cadence = None

    while True:
        time.sleep(FILE_POLL)
        now = time.monotonic()
        due = (now - emit_at) >= max(0.0, tick.value - FILE_POLL)
        try:
            st = os.stat(path)
            with open(path) as fp:
                rec = json.load(fp)
        except FileNotFoundError:
            if due:
                emit_at = now
                yield None, None, f"no collector file at {path} (is the collector running?)"
            continue
        except PermissionError:
            if due:
                emit_at = now
                yield None, None, f"cannot read {path} (permission denied - not world-readable?)"
            continue
        except (OSError, ValueError):
            if due:
                emit_at = now
                yield None, None, "collector file unreadable"
            continue

        if scale is not None and rec.get("cap"):
            scale.adopt(rec["cap"], rec.get("cap_src", "collector"))

        ts = rec.get("ts")
        if ts is not None and ts != seen_ts:
            if seen_at is not None:
                dt = now - seen_at
                cadence = dt if cadence is None else cadence * 0.7 + dt * 0.3
            seen_ts, seen_at = ts, now

        age = time.time() - st.st_mtime
        if age > max(3 * tick.value, 3):
            if due:
                emit_at = now
                yield (rec.get("bw"), rec.get("util"),
                       f"collector data is stale ({age:.0f}s) - collector may be stopped")
            continue

        if ts is not None and ts == emit_ts:
            continue
        if not due:
            continue

        status = rec.get("status")
        floor = rec.get("interval") or cadence
        if status is None and floor and tick.value < floor * 0.9:
            status = (f"collector writes every {floor*1000:.0f}ms; the graph "
                      f"cannot go faster than that (lower the collector's "
                      f"--interval, not the GUI's)")
        emit_ts, emit_at = ts, now
        yield rec.get("bw"), rec.get("util"), status


def make_source(args, tick, scale=None):
    fallback = (scale.cap if scale and scale.cap else None) or args.cap or 96.0
    if args.source == "demo":
        return gen_demo(tick, fallback)
    if args.source == "perf":
        return gen_perf(tick, fallback)
    if args.source == "file":
        return gen_file(tick, args.file, scale)
    return gen_mbm(tick, fallback)


def run_serve(gen, path, frames=0, scale=None, tick=None):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    sys.stderr.write(f"[collector] writing samples to {path}\n")
    sys.stderr.flush()
    n = 0
    for bw, util, status in gen:
        if scale is not None:
            scale.observe(bw, util)
        rec = {"bw": bw, "util": util, "ts": time.time(), "status": status}
        if tick is not None:
            rec["interval"] = round(tick.value, 4)
        if scale is not None and scale.cap:
            rec["cap"] = scale.cap
            rec["cap_src"] = scale.cap_src
        with open(tmp, "w") as fp:
            json.dump(rec, fp)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        n += 1
        if frames and n >= frames:
            break


def build_frame(history, scale, interval, cols, rows, use_color,
                latest_util=None, status=None, keys=False):
    def c(frac):
        return sat_color(frac) if use_color else ""

    def rst():
        return RESET if use_color else ""

    bws = [b for (b, _u, _t) in history]
    now = bws[-1] if bws else 0.0
    wavg = scale.mean or now

    cap = scale.cap
    top = scale.observed_max if scale.observed_max > 0 else max(cap or 0.0, 1e-3)
    rel = min(1.0, now / top) if top else 0.0

    sat_ref = cap if cap else top

    def sat(value):
        return min(1.0, max(0.0, value / sat_ref)) if sat_ref else 0.0

    lines = []
    src = "measured" if latest_util is not None else "estimated"
    LEFT = 20

    left = (f" bus  {latest_util:6.1f}% used" if latest_util is not None
            else f" bus  {'n/a':>6}")
    if cap:
        right = f"theoretical upper cap {cap:7.1f} GB/s   (from {scale.cap_src})"
    else:
        right = "theoretical upper cap       n/a   (no readout available)"
    lines.append(f"{left:<{LEFT}}{right}"[:cols])

    of_cap = f"{scale.observed_max / cap * 100:.1f}% of cap" if cap else "cap unknown"
    left = f" avg  {wavg:7.2f} GB/s"
    right = f"observed max          {scale.observed_max:7.1f} GB/s   ({of_cap})"
    lines.append(f"{left:<{LEFT}}{right}"[:cols])

    lo = scale.observed_min
    if lo is not None:
        left = f" base {lo:7.2f} GB/s"
        right = (f"observed range        {scale.observed_max - lo:7.1f} GB/s"
                 f"   (max - base)")
    else:
        left = f" base {'n/a':>7}"
        right = "observed range              n/a   (no sample yet)"
    lines.append(f"{left:<{LEFT}}{right}"[:cols])

    now_line = (f" now  {c(sat(now))}{now:7.2f} GB/s{rst()}  "
                f"{c(sat(now))}{hbar(rel, 22)}{rst()}  {rel*100:5.1f}% of observed max")
    if lo is not None:
        tail = f"   {now - lo:+7.2f} over base"
        if vislen(now_line) + len(tail) <= cols:
            now_line += tail
    lines.append(now_line)

    note = status or scale.note
    if note:
        warn = "\033[38;2;255;80;80m" if use_color else ""
        lines.append(f" {warn}! {note}{rst()}")

    header_n = len(lines)
    graph_rows = max(6, rows - header_n - 1 - 1)
    gutter = 7
    graph_w = max(10, cols - gutter - 1)

    vis = list(history)[-graph_w:]
    pad = graph_w - len(vis)

    win_max = max((b for (b, _u, _t) in vis), default=0.0)
    floor_ref = cap or scale.observed_max or 0.0
    ceiling = max(win_max, floor_ref * PLOT_FLOOR_FRAC, 1e-3)

    col_e = [0] * pad
    col_c = [""] * pad
    for (b, _u, _t) in vis:
        e = int(round((b / ceiling) * graph_rows * 8))
        col_e.append(max(0, min(graph_rows * 8, e)))
        col_c.append(c(sat(b)))

    for r in range(graph_rows - 1, -1, -1):
        if r == graph_rows - 1:
            label = f"{ceiling:6.1f} "
        elif r == graph_rows // 2:
            label = f"{ceiling/2:6.1f} "
        elif r == 0:
            label = f"{0.0:6.1f} "
        else:
            label = " " * gutter
        row = [label]
        base = r * 8
        for i in range(graph_w):
            filled = col_e[i] - base
            filled = 0 if filled < 0 else (8 if filled > 8 else filled)
            ch = BLOCKS[filled]
            if use_color and ch != " ":
                row.append(col_c[i] + ch + RESET)
            else:
                row.append(ch)
        lines.append("".join(row))

    span = (vis[-1][2] - vis[0][2]) if len(vis) > 1 else 0.0
    tail = min(RATE_BASELINE, len(vis))
    actual = ((vis[-1][2] - vis[-tail][2]) / (tail - 1)) if tail > 1 else None
    if actual and abs(actual - interval) > max(0.02, interval * 0.25):
        rate = f"{interval*1000:.0f}ms asked / {actual*1000:.0f}ms actual"
    else:
        rate = f"{interval*1000:.0f}ms sample"
    bits = [f"{span:5.1f}s shown", rate, f"[{src}]"]
    if keys:
        bits.append("+/- rate   r reset   q quit")
    bits.append(f"stats over {fmt_dur(scale.window)}")
    line = " " + "   ".join(bits)
    while len(line) > cols and len(bits) > 2:
        del bits[-2]
        line = " " + "   ".join(bits)
    lines.append(line[:cols])
    return lines


def main():
    from graph_scale_dynamics.operations.process_ownership import die_with_owner
    die_with_owner()
    ap = argparse.ArgumentParser(description="Live DRAM bandwidth monitor (AMD).")
    ap.add_argument("-s", "--source", choices=["perf", "file", "mbm", "demo"],
                    default="mbm", help="data source (default mbm)")
    ap.add_argument("-i", "--interval", type=parse_interval, default=0.25,
                    metavar="T",
                    help="sample interval, e.g. 250ms / 0.5s / 2 "
                         "(default 250ms; adjust live with +/-)")
    ap.add_argument("-p", "--peak", "--cap", dest="cap", type=float, default=None,
                    help="override the theoretical upper cap in GB/s "
                         "(default: derive it from the machine)")
    ap.add_argument("--no-autocap", action="store_true",
                    help="do not derive or refine the cap; use --cap verbatim")
    ap.add_argument("--cap-probe", type=float, default=1.0,
                    help="seconds to sample the UMC clock when deriving the cap")
    ap.add_argument("--file", default="/run/membw/latest.json",
                    help="path for --source file and --serve (default /run/membw/latest.json)")
    ap.add_argument("--serve", action="store_true",
                    help="collector mode: write samples to --file instead of drawing")
    ap.add_argument("--no-color", action="store_true", help="disable color")
    ap.add_argument("--demo", action="store_true", help="alias for --source demo")
    ap.add_argument("--debug", action="store_true",
                    help="print raw source lines and samples instead of the graph")
    ap.add_argument("--frames", type=int, default=0, help="exit after N samples (0=forever)")
    args = ap.parse_args()

    if args.demo:
        args.source = "demo"

    global DEBUG
    DEBUG = args.debug

    autocap = not args.no_autocap
    scale = Scale(cap=args.cap, cap_src="manual", autocap=autocap)
    if autocap and scale.cap is None and args.source != "file":
        cap, csrc = detect_cap(args.cap_probe)
        scale.adopt(cap, csrc)

    tick = Tick(args.interval)

    if args.serve:
        gen = make_source(args, tick, scale)
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        run_serve(gen, args.file, args.frames, scale, tick)
        return

    gen = make_source(args, tick, scale)

    if args.debug:
        sys.stderr.write(f"[debug] source={args.source} interval={tick.value}s\n")
        sys.stderr.flush()
        t0 = time.monotonic()
        try:
            for bw, util, status in gen:
                sys.stderr.write(
                    f"[{time.monotonic()-t0:6.2f}s] bw={bw} util={util} status={status}\n"
                )
                sys.stderr.flush()
        except KeyboardInterrupt:
            pass
        return

    use_color = not args.no_color and sys.stdout.isatty()
    it = iter(gen)
    first = next(it)

    history = deque(maxlen=8192)
    latest_util = None

    keys_on = False
    tty_saved = None
    try:
        import termios as _termios
        import tty as _tty
        if sys.stdin.isatty():
            tty_saved = _termios.tcgetattr(sys.stdin.fileno())
            _tty.setcbreak(sys.stdin.fileno())
            keys_on = True
    except Exception:
        keys_on, tty_saved = False, None

    def untty():
        if tty_saved is not None:
            try:
                _termios.tcsetattr(sys.stdin.fileno(), _termios.TCSADRAIN, tty_saved)
            except Exception:
                pass

    def read_keys():
        if not keys_on:
            return True
        import select as _select
        while _select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if not ch or ch in "qQ\x03\x04":
                return False
            if ch in "+=":
                tick.step(-1)
            elif ch in "-_":
                tick.step(+1)
            elif ch in "rR":
                scale.reset_stats(history[-1][0] if history else 0.0)
        return True

    sys.stdout.write("\033[2J\033[?25l")
    sys.stdout.flush()

    def restore(*_):
        untty()
        sys.stdout.write("\033[?25h\033[0m\n")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, restore)
    signal.signal(signal.SIGTERM, restore)

    frame = 0
    sample = first
    try:
        while True:
            arrived = time.monotonic()
            bw, util, status = sample
            if util is not None:
                latest_util = util
            if bw is not None:
                history.append((bw, latest_util, arrived))
            scale.observe(bw, latest_util)
            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            lines = build_frame(history, scale, tick.value,
                                cols, rows, use_color, latest_util, status,
                                keys_on)
            buf = ["\033[H"]
            for ln in lines:
                buf.append(ln + "\033[K\n")
            buf.append("\033[J")
            sys.stdout.write("".join(buf))
            sys.stdout.flush()
            frame += 1
            if args.frames and frame >= args.frames:
                break
            if not read_keys():
                break
            sample = next(it)
    except StopIteration:
        pass
    finally:
        untty()
        sys.stdout.write("\033[?25h\033[0m\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
