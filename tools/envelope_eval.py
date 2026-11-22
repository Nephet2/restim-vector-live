"""Offline evaluation of V0/C0/P0/P3/P1 output smoothing for Vector.

Runs VectorEngine on a simulated clock (no Tk, no network, no hardware),
captures the engine's released V0 and primary pulse commands (C0, P0, P3, P1)
for synthetic input scenarios, and applies a prototype processor:

  1. Asymmetric attack/release: first-order exponential filter; tau_attack is
     used when the target is above the filtered value, tau_release when below.
     Each tau is the time to cover ~63% of a sustained step.
  2. Jerk limiting: three cascaded trailing moving averages of N samples.
     N is chosen so |third difference| / dt^3 <= J for any input confined to
     the axis range R (bound 4 R / W^3, W = N dt).  Delay = 3 (N - 1) / 2 samples.
  3. Smoothing-delay compensation: the processed curve is advanced by d
     seconds (value from t + d plotted at t), with linear interpolation for
     fractional samples.  Traces are trimmed to the interval all share.

Nothing here changes Vector; it only drives vector1a.engine offline.

Usage (from the project root):
    python -B tools/envelope_eval.py [--out DIR] [--quick] [--table AXIS]
    python -B tools/envelope_eval.py --inspect pause_gap_3s
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vector1a.engine import VectorEngine  # noqa: E402

RATE_HZ = 50
DT = 1.0 / RATE_HZ
LOOKAHEAD = 2.0
WARMUP = 10.0          # 1 Hz strokes so speed normalisation settles first.
DURATION = 12.0        # Scenario length that is measured.
TAIL = 2.0             # Extra steady strokes so advanced traces have data.
AXES = ("V0", "C0", "P0", "P3", "P1")
STROKE_COUPLED = ("P0", "P1")   # Engine derives these from alpha / output_l0.
JERK_K = 4.0           # Worst-case third-difference factor for inputs within R.

# Pass criteria.
MAX_RISE_DELAY = 0.02          # s: onset must stay on time after compensation.
MIN_STROKE_RETENTION = 0.90    # stroke-coupled axes keep 90% of their swing.
MIN_BURST_RETENTION = 0.80     # short bursts keep 80% of their peak.
MAX_SETTLE = 2.0               # s: 95% of the stop-input drop is covered by then.

GAP_START, GAP_END = 4.0, 7.0  # Input gap / hold window in the pause scenarios.


# --------------------------------------------------------------------------
# Scenarios: each returns (cycle frequency in Hz, mode) for scenario time t.
#   "move": positions advance; "hold": same position keeps arriving;
#   "gap": no input packets at all (MFP silent).
# --------------------------------------------------------------------------
def steady(freq):
    return lambda t: (freq, "move")


def sweep(t):
    return 0.3 + (3.0 - 0.3) * t / DURATION, "move"


def pause(mode):
    return lambda t: (1.0, mode if GAP_START <= t < GAP_END else "move")


def burst(t):
    return (3.0 if 5.0 <= t < 6.5 else 0.5), "move"


SCENARIOS = {
    "strokes_0.5hz": steady(0.5),
    "strokes_1.5hz": steady(1.5),
    "strokes_3hz": steady(3.0),
    "sweep_0.3_to_3hz": sweep,
    "pause_gap_3s": pause("gap"),
    "pause_hold_3s": pause("hold"),
    "burst_3hz_1.5s": burst,
}
STROKE_SCENARIOS = ("strokes_0.5hz", "strokes_1.5hz", "strokes_3hz")


def run_engine(scenario):
    """Return (times, {axis: values}, ranges) for released samples."""
    now = [0.0]
    released = []
    engine = VectorEngine(released.append, rate_hz=RATE_HZ,
                          lookahead_seconds=LOOKAHEAD, clock=lambda: now[0])
    engine.resume()
    phase, position = 0.0, 0.1
    steps = int(round((WARMUP + DURATION + TAIL + LOOKAHEAD) / DT)) + 1
    for index in range(steps):
        t = index * DT
        now[0] = t
        local = t - WARMUP
        if 0.0 <= local < DURATION:
            freq, mode = scenario(local)
        else:
            freq, mode = 1.0, "move"
        if mode == "move":
            phase += 2.0 * math.pi * freq * DT
            position = 0.1 + 0.8 * (0.5 - 0.5 * math.cos(phase))
        if index == 0:
            # As VectorApp._prepare_local_input does with the first live sample.
            engine.rebase_input(position, t)
        if mode != "gap":
            engine.receive_l0(position, 0, t)
        engine.step(t, t)
    times = [s.calculated_at for s in released]
    values = {axis: [] for axis in AXES}
    values["speed"] = [s.speed_percent for s in released]
    values["L0"] = [s.raw_l0 for s in released]
    for s in released:
        values["V0"].append(s.volume)
        for axis, value in zip(AXES[1:], s.shifted_primary_pulse or s.primary_pulse):
            values[axis].append(value)
    ranges = {"V0": 1.0}
    for axis, (low, high) in zip(AXES[1:], engine.pulse_command_ranges()):
        ranges[axis] = max(1e-6, high - low)
    return times, values, ranges


# --------------------------------------------------------------------------
# Prototype processing stages.
# --------------------------------------------------------------------------
def attack_release(x, tau_attack, tau_release):
    up = -math.expm1(-DT / tau_attack) if tau_attack > 0 else 1.0
    down = -math.expm1(-DT / tau_release) if tau_release > 0 else 1.0
    out, value = [], x[0]
    append = out.append
    for target in x:
        value += (target - value) * (up if target > value else down)
        append(value)
    return out


def jerk_window(jerk, axis_range):
    if not jerk:
        return 1
    width = (JERK_K * axis_range / jerk) ** (1.0 / 3.0)
    return max(1, math.ceil(width / DT - 1e-9))


def moving_average(x, n):
    if n <= 1:
        return list(x)
    buffer = [x[0]] * n
    total, j, out = x[0] * n, 0, []
    append = out.append
    for value in x:
        total += value - buffer[j]
        buffer[j] = value
        j = (j + 1) % n
        append(total / n)
    return out


def jerk_limit(x, n):
    for _ in range(3):
        x = moving_average(x, n)
    return x


def ma_delay(n):
    return 3.0 * (n - 1) / 2.0 * DT


def sample_at(y, position):
    """Linear interpolation at a fractional sample index."""
    i0 = int(math.floor(position))
    if i0 < 0:
        return y[0]
    if i0 + 1 >= len(y):
        return y[-1]
    return y[i0] + (y[i0 + 1] - y[i0]) * (position - i0)


def advance(y, seconds):
    if seconds <= 0:
        return list(y)
    shift = seconds / DT
    usable = len(y) - int(math.ceil(shift)) - 1
    return [sample_at(y, i + shift) for i in range(max(0, usable))]


# --------------------------------------------------------------------------
# Metrics on [start, end) sample indices.
# --------------------------------------------------------------------------
def max_jerk(y, start, end):
    best = 0.0
    for i in range(max(start, 3), end):
        best = max(best, abs(y[i] - 3.0 * y[i - 1] + 3.0 * y[i - 2] - y[i - 3]))
    return best / DT ** 3


def max_step(y, start, end):
    return max((abs(y[i] - y[i - 1]) for i in range(max(start, 1), end)), default=0.0)


def spread(y, start, end):
    window = sorted(y[start:end])
    if len(window) < 2:
        return 0.0
    return (window[int(0.95 * (len(window) - 1))]
            - window[int(0.05 * (len(window) - 1))])


def level(times, y, t_from, t_to):
    picked = [v for t, v in zip(times, y) if WARMUP + t_from <= t < WARMUP + t_to]
    return statistics.median(picked) if picked else None


def crossing(times, y, t_from, threshold, rising, limit=3.0):
    """Interpolated time (scenario s) of the first threshold crossing."""
    for i in range(1, len(y)):
        t0, t1 = times[i - 1] - WARMUP, times[i] - WARMUP
        if t1 < t_from or t0 > t_from + limit:
            continue
        a, b = y[i - 1], y[i]
        if (rising and a < threshold <= b) or (not rising and a > threshold >= b):
            return t0 + (t1 - t0) * (threshold - a) / (b - a)
    return None


def edge_delays(times, proc, raw):
    """Fall/rise delay at 50% and fall settle for the input-gap scenario."""
    active = level(times, raw, GAP_START - 1.0, GAP_START)
    rest = level(times, raw, GAP_START + 1.0, GAP_END)
    if active is None or rest is None or active - rest < 1e-3:
        return None, None, None
    half = (active + rest) / 2.0
    # Advanced curves may cross before the raw edge, so search from 1 s earlier.
    raw_fall = crossing(times, raw, GAP_START - 1.0, half, rising=False, limit=4.0)
    proc_fall = crossing(times, proc, GAP_START - 1.0, half, rising=False, limit=4.0)
    raw_rise = crossing(times, raw, GAP_END - 1.0, half, rising=True, limit=4.0)
    proc_rise = crossing(times, proc, GAP_END - 1.0, half, rising=True, limit=4.0)
    fall = (proc_fall - raw_fall) if raw_fall is not None and proc_fall is not None else None
    rise = (proc_rise - raw_rise) if raw_rise is not None and proc_rise is not None else None
    settle = None
    if raw_fall is not None:
        target = rest + 0.05 * (active - rest)
        settled = crossing(times, proc, GAP_START - 1.0, target, rising=False, limit=4.0)
        settle = None if settled is None else settled - raw_fall
    return fall, rise, settle


def burst_peak_retention(proc, raw, times):
    base = level(times, raw, 3.0, 5.0)
    window = [(p, r) for t, p, r in zip(times, proc, raw)
              if WARMUP + 5.0 <= t < WARMUP + 7.0]
    if base is None or not window:
        return None
    raw_peak = max(r for _, r in window) - base
    if raw_peak < 1e-4:
        return None
    return (max(p for p, _ in window) - base) / raw_peak


# --------------------------------------------------------------------------
# Grid evaluation.
# --------------------------------------------------------------------------
def grid(quick):
    attacks = (0.01, 0.02, 0.05, 0.1, 0.2) if not quick else (0.05, 0.1)
    releases = ((0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0) if not quick
                else (0.25, 1.0))
    jerks = ((None, 50000.0, 10000.0, 2000.0, 500.0, 100.0, 20.0) if not quick
             else (None, 500.0))
    pairs = [(None, None)] + [(a, r) for a in attacks for r in releases if r >= a]
    return pairs, jerks, ("none", "ma", "ma+attack")


def evaluate(out_dir: Path, quick: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs, jerks, d_modes = grid(quick)
    rows, traces = [], {}
    for name, scenario in SCENARIOS.items():
        times, values, ranges = run_engine(scenario)
        start = next(i for i, t in enumerate(times) if t >= WARMUP)
        window_end = next(i for i, t in enumerate(times) if t >= WARMUP + DURATION)
        for axis in AXES:
            raw = values[axis]
            axis_range = ranges[axis]
            windows = {j: jerk_window(j, axis_range) for j in jerks}
            max_d = (max(ma_delay(n) for n in windows.values())
                     + max((a or 0.0) for a, _ in pairs))
            # Shared interval: every advanced trace still has data here.
            end = min(window_end, len(raw) - int(math.ceil(max_d / DT)) - 2)
            raw_jerk, raw_step = max_jerk(raw, start, end), max_step(raw, start, end)
            raw_spread = spread(raw, start, end)
            traces[(name, axis, "raw")] = (times, raw)
            for tau_a, tau_r in pairs:
                filtered = raw if tau_a is None else attack_release(raw, tau_a, tau_r)
                for jerk in jerks:
                    n = windows[jerk]
                    limited = jerk_limit(filtered, n)
                    for d_mode in d_modes:
                        if tau_a is None and jerk is None and d_mode != "none":
                            continue
                        d = {"none": 0.0, "ma": ma_delay(n),
                             "ma+attack": ma_delay(n) + (tau_a or 0.0)}[d_mode]
                        proc = advance(limited, d)
                        diffs = [p - r for p, r in zip(proc[start:end], raw[start:end])]
                        fall = rise = settle = None
                        if name == "pause_gap_3s":
                            fall, rise, settle = edge_delays(times[:len(proc)], proc, raw)
                        rows.append({
                            "axis": axis, "scenario": name,
                            "tau_attack": tau_a, "tau_release": tau_r,
                            "jerk_limit": jerk, "ma_samples": n,
                            "ma_delay_s": round(ma_delay(n), 4),
                            "advance_mode": d_mode, "advance_s": round(d, 4),
                            "max_jerk": max_jerk(proc, start, end), "raw_max_jerk": raw_jerk,
                            "max_step": max_step(proc, start, end), "raw_max_step": raw_step,
                            "retention": (spread(proc, start, end) / raw_spread
                                          if raw_spread >= 0.01 * axis_range else None),
                            "bias": sum(diffs) / len(diffs),
                            "rms": math.sqrt(sum(x * x for x in diffs) / len(diffs)),
                            "fall_delay_s": fall, "rise_delay_s": rise, "settle_s": settle,
                            "burst_peak_retention": (burst_peak_retention(proc, raw, times)
                                                     if name.startswith("burst") else None),
                        })
                        traces[(name, axis, (tau_a, tau_r, jerk, d_mode))] = (times, proc)
        print(f"  evaluated {name}", flush=True)
    write_rows(out_dir / "envelope_eval_grid.csv", rows)
    summary = summarise(rows)
    (out_dir / "envelope_eval_summary.md").write_text(summary, encoding="utf-8")
    write_traces(out_dir, traces, summary_choices(rows))
    print(summary)
    return rows


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def config_key(row):
    return (row["tau_attack"], row["tau_release"], row["jerk_limit"], row["advance_mode"])


def aggregate(rows, axis):
    """Combine scenarios per configuration for one axis."""
    by_config = {}
    for row in rows:
        if row["axis"] == axis:
            by_config.setdefault(config_key(row), {})[row["scenario"]] = row
    combined = []
    for key, scenarios in by_config.items():
        retentions = [scenarios[s]["retention"] for s in STROKE_SCENARIOS
                      if scenarios[s]["retention"] is not None]
        gap = scenarios["pause_gap_3s"]
        combined.append({
            "axis": axis, "key": key,
            "min_stroke_retention": min(retentions) if retentions else None,
            "worst_abs_bias": max(abs(r["bias"]) for r in scenarios.values()),
            "pause_max_step": gap["max_step"], "pause_raw_max_step": gap["raw_max_step"],
            "worst_max_jerk": max(r["max_jerk"] for r in scenarios.values()),
            "worst_raw_max_jerk": max(r["raw_max_jerk"] for r in scenarios.values()),
            "fall_delay_s": gap["fall_delay_s"], "rise_delay_s": gap["rise_delay_s"],
            "settle_s": gap["settle_s"],
            "burst_peak_retention": scenarios["burst_3hz_1.5s"]["burst_peak_retention"],
            "advance_s": gap["advance_s"],
        })
    return combined


def failures(entry):
    reasons = []
    if entry["axis"] in STROKE_COUPLED and (
            entry["min_stroke_retention"] is not None
            and entry["min_stroke_retention"] < MIN_STROKE_RETENTION):
        reasons.append("stroke")
    if entry["burst_peak_retention"] is not None and \
            entry["burst_peak_retention"] < MIN_BURST_RETENTION:
        reasons.append("burst")
    if entry["rise_delay_s"] is not None and abs(entry["rise_delay_s"]) > MAX_RISE_DELAY:
        reasons.append("rise")
    if entry["settle_s"] is not None and entry["settle_s"] > MAX_SETTLE:
        reasons.append("settle")
    if entry["fall_delay_s"] is not None and entry["settle_s"] is None:
        reasons.append("no-settle")   # Never reached 95% before input resumed.
    return reasons


def ranked(rows, axis):
    entries = aggregate(rows, axis)
    candidates = [e for e in entries if not failures(e) and e["key"][0] is not None]
    candidates.sort(key=lambda e: (round(e["pause_max_step"], 4), e["worst_max_jerk"]))
    raw = next(e for e in entries if e["key"] == (None, None, None, "none"))
    return raw, candidates, entries


def summary_choices(rows):
    choices = {}
    for axis in AXES:
        _, candidates, _ = ranked(rows, axis)
        if candidates:
            choices[axis] = candidates[0]["key"]
    return choices


def fmt(value, digits=3):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.0f}" if abs(value) >= 1000 else f"{value:.{digits}f}"
    return str(value)


def describe(key):
    tau_a, tau_r, jerk, mode = key
    ar = "A/R off" if tau_a is None else f"A {tau_a:g}s / R {tau_r:g}s"
    return f"{ar}, J {'off' if jerk is None else f'{jerk:g}'}, advance {mode}"


def summary_line(entry):
    return (f"| {describe(entry['key'])} | {fmt(entry['pause_max_step'], 4)} "
            f"| {fmt(entry['worst_max_jerk'])} | {fmt(entry['min_stroke_retention'])} "
            f"| {fmt(entry['burst_peak_retention'])} | {fmt(entry['rise_delay_s'])} "
            f"| {fmt(entry['fall_delay_s'], 2)} | {fmt(entry['settle_s'], 2)} "
            f"| {fmt(entry['worst_abs_bias'], 4)} | {fmt(entry['advance_s'], 2)} |")


def summarise(rows):
    lines = [
        "# Vector output smoothing: offline evaluation", "",
        f"Engine at {RATE_HZ} Hz, lookahead {LOOKAHEAD:g} s, engine defaults otherwise. "
        f"Pass: rise delay within ±{MAX_RISE_DELAY:g} s; 95% of the stop-input drop "
        f"within {MAX_SETTLE:g} s; burst peak retention >= {MIN_BURST_RETENTION:g}; "
        f"stroke retention >= {MIN_STROKE_RETENTION:g} for {', '.join(STROKE_COUPLED)}. "
        "Ranked by largest per-sample change in the 3 s input gap, then worst jerk.", "",
        "Jerk is in normalized units/s³; delays and settle are seconds after the raw "
        "curve's own 50% crossing.", ""]
    header = ("| Config | Gap max step | Worst jerk | Stroke retention | Burst peak | "
              "Rise delay | Fall delay | Settle | Worst bias | Advance |")
    for axis in AXES:
        raw, candidates, entries = ranked(rows, axis)
        lines += [f"## {axis}", "", header, "|" + "---|" * 10, summary_line(raw)]
        lines += [summary_line(e) for e in candidates[:6]]
        lines += ["", f"{len(candidates)} of {len(entries) - 1} processed "
                      f"configurations pass.", ""]
    return "\n".join(lines) + "\n"


def write_traces(out_dir, traces, choices):
    """Raw vs best-ranked processed trace per axis for three key scenarios."""
    for name in ("pause_gap_3s", "strokes_1.5hz", "burst_3hz_1.5s"):
        columns = []
        for axis in AXES:
            columns.append((f"{axis}_raw", traces[(name, axis, "raw")][1]))
            if axis in choices:
                columns.append((f"{axis}_best", traces[(name, axis, choices[axis])][1]))
        times = traces[(name, AXES[0], "raw")][0]
        length = min(len(values) for _, values in columns)
        with (out_dir / f"envelope_trace_{name}.csv").open(
                "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["t_s"] + [label for label, _ in columns])
            for i in range(length):
                if WARMUP <= times[i] < WARMUP + DURATION:
                    writer.writerow([round(times[i] - WARMUP, 4)] +
                                    [round(values[i], 6) for _, values in columns])


def print_table(rows, axis):
    _, _, entries = ranked(rows, axis)
    entries.sort(key=lambda e: e["pause_max_step"])
    print(f"\nAll configurations for {axis}:")
    for e in entries:
        reasons = failures(e)
        print(f"{'PASS ' if not reasons else ','.join(reasons):12} {describe(e['key']):46} "
              f"step {fmt(e['pause_max_step'], 4)} jerk {fmt(e['worst_max_jerk'])} "
              f"ret {fmt(e['min_stroke_retention'])} burst {fmt(e['burst_peak_retention'])} "
              f"rise {fmt(e['rise_delay_s'])} fall {fmt(e['fall_delay_s'], 2)} "
              f"settle {fmt(e['settle_s'], 2)} bias {fmt(e['worst_abs_bias'], 4)}")


def inspect(name):
    times, values, ranges = run_engine(SCENARIOS[name])
    print("ranges", ranges)
    columns = ("L0", "speed") + AXES
    print("t_s   " + "  ".join(f"{axis:>8}" for axis in columns))
    for i, t in enumerate(times):
        if WARMUP <= t < WARMUP + DURATION and i % 10 == 0:
            print(f"{t - WARMUP:5.2f} " + "  ".join(f"{values[a][i]:8.4f}" for a in columns))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "tools" / "envelope_eval_results")
    parser.add_argument("--quick", action="store_true", help="small grid for a smoke run")
    parser.add_argument("--inspect", metavar="SCENARIO",
                        help="print raw engine output for one scenario and exit")
    parser.add_argument("--table", metavar="AXIS",
                        help="after evaluating, print every configuration for one axis")
    args = parser.parse_args()
    if args.inspect:
        inspect(args.inspect)
        return
    rows = evaluate(args.out, args.quick)
    if args.table:
        print_table(rows, args.table)


if __name__ == "__main__":
    main()
