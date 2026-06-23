#!/usr/bin/env python3
"""
Extract lap-level swimming data from an Apple Health export.xml.

Apple Watch logs one HKQuantityTypeIdentifierSwimmingStrokeCount record per
pool length: the record's start/end span is the time taken for that length and
its value is the number of strokes. This script streams the export (memory-safe
on 500MB+ files), collects every Swimming workout and every stroke record,
associates strokes to the right workout by time, infers the pool length, and
writes a per-length CSV with efficiency metrics:

    seconds            time for the length
    strokes            stroke count for the length
    dist_per_stroke_m  pool_length / strokes   (higher = more efficient)
    swolf              seconds + strokes        (lower  = more efficient)

Open-water swims have no per-length stroke records and are skipped (expected).

Usage:
    python3 extract_swim_laps.py /path/to/export.xml swim_laps.csv
"""
import csv
import re
import bisect
import calendar
import argparse
import statistics as st
import xml.etree.ElementTree as ET
from datetime import datetime

STROKE = "HKQuantityTypeIdentifierSwimmingStrokeCount"
SWIM = "HKWorkoutActivityTypeSwimming"
HEART = "HKQuantityTypeIdentifierHeartRate"   # exact; not HeartRateVariability…
STYLE_MAP = {"0": "unknown", "1": "mixed", "2": "freestyle",
             "3": "backstroke", "4": "breaststroke", "5": "butterfly"}


def pdate(s):
    # e.g. "2024-11-07 07:55:36 -0400"
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")


def fast_epoch(s):
    # "2024-11-07 07:55:36 -0400" -> UTC epoch seconds. Hand-parsed (no strptime) because
    # pass 2 calls this on every heart-rate sample, of which there can be millions.
    try:
        y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        h, mi, se = int(s[11:13]), int(s[14:16]), int(s[17:19])
        off = (int(s[21:23]) * 3600 + int(s[23:25]) * 60) * (1 if s[20] == "+" else -1)
        return calendar.timegm((y, mo, d, h, mi, se, 0, 0, 0)) - off
    except (ValueError, IndexError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml_path")
    ap.add_argument("out_csv")
    args = ap.parse_args()

    workouts = []   # swimming workouts: start, end, dist, lap_len, source
    strokes = []    # per-length stroke records: start, end, value, style

    context = ET.iterparse(args.xml_path, events=("start", "end"))
    _, root = next(context)

    for event, elem in context:
        if event != "end":
            continue
        tag = elem.tag

        if tag == "Workout":
            if elem.get("workoutActivityType") == SWIM:
                w = {"start": elem.get("startDate"), "end": elem.get("endDate"),
                     "dist": None, "lap_len": None, "source": elem.get("sourceName", "")}
                d = elem.get("totalDistance")
                if d:
                    w["dist"] = float(d)
                for stat in elem.findall("WorkoutStatistics"):
                    if "Distance" in stat.get("type", "") and w["dist"] is None:
                        try:
                            w["dist"] = float(stat.get("sum"))
                        except (TypeError, ValueError):
                            pass
                for md in elem.findall("MetadataEntry"):
                    if "LapLength" in md.get("key", ""):
                        m = re.search(r"([\d.]+)\s*([a-zA-Z]*)", md.get("value", ""))
                        if m:
                            ll = float(m.group(1))
                            if m.group(2).lower() in ("yd", "yard", "yards"):
                                ll *= 0.9144  # yards -> metres, so all metrics stay in metres
                            w["lap_len"] = ll
                workouts.append(w)
            elem.clear()
            root.clear()

        elif tag == "Record":
            if elem.get("type") == STROKE:
                style = None
                for md in elem.findall("MetadataEntry"):
                    if "StrokeStyle" in md.get("key", ""):
                        v = md.get("value", "").strip()
                        style = STYLE_MAP.get(v, v)
                strokes.append({"start": elem.get("startDate"), "end": elem.get("endDate"),
                                "value": float(elem.get("value", "0") or 0), "style": style})
            elem.clear()
            root.clear()

    for w in workouts:
        w["s"], w["e"] = pdate(w["start"]), pdate(w["end"])
    for r in strokes:
        r["s"], r["e"] = pdate(r["start"]), pdate(r["end"])
    workouts.sort(key=lambda w: w["s"])
    strokes.sort(key=lambda r: r["s"])

    rows = []
    windows = []   # (start_epoch, end_epoch, row) per length, for the heart-rate pass
    for w in workouts:
        laps = [r for r in strokes if w["s"] <= r["s"] < w["e"]]
        if not laps:
            continue
        n = len(laps)
        if w["lap_len"]:
            pool = w["lap_len"]
        elif w["dist"]:
            pool = w["dist"] / n
        else:
            pool = None
        for i, r in enumerate(laps, 1):
            secs = (r["e"] - r["s"]).total_seconds()
            sn = r["value"]
            dps = (pool / sn) if (pool and sn) else None
            swolf = (secs + sn) if sn else None
            row = {
                "workout_start": w["s"].strftime("%Y-%m-%d %H:%M"),
                "lap_index": i,
                "lap_count": n,
                "pool_length_m": round(pool, 2) if pool else "",
                "seconds": round(secs, 1),
                "strokes": int(sn) if sn == int(sn) else sn,
                "dist_per_stroke_m": round(dps, 3) if dps else "",
                "swolf": round(swolf, 1) if swolf else "",
                "stroke_style": r["style"] or "",
                "hr": "",
            }
            rows.append(row)
            windows.append((r["s"].timestamp(), r["e"].timestamp(), row))

    # Second pass: average per-sample heart rate into each length's time window. The window
    # set isn't known until all workouts are read, so HR needs its own streaming pass.
    if windows:
        swim_days = {r["workout_start"][:10] for r in rows}
        windows.sort(key=lambda x: x[0])
        starts = [x[0] for x in windows]
        gmin, gmax = windows[0][0], max(x[1] for x in windows)
        hr_sum = [0.0] * len(windows)
        hr_cnt = [0] * len(windows)
        ctx = ET.iterparse(args.xml_path, events=("start", "end"))
        _, root2 = next(ctx)
        for event, elem in ctx:
            if event != "end":
                continue
            if elem.tag == "Record" and elem.get("type") == HEART:
                sd = elem.get("startDate", "")
                if sd[:10] in swim_days:          # cheap reject of the all-day HR firehose
                    t = fast_epoch(sd)
                    if t is not None and gmin <= t < gmax:
                        try:
                            v = float(elem.get("value"))
                        except (TypeError, ValueError):
                            v = None
                        if v is not None:
                            idx = bisect.bisect_right(starts, t) - 1
                            if idx >= 0 and t < windows[idx][1]:
                                hr_sum[idx] += v
                                hr_cnt[idx] += 1
            elem.clear()
            root2.clear()
        for i, x in enumerate(windows):
            if hr_cnt[i] > 0:
                x[2]["hr"] = int(round(hr_sum[i] / hr_cnt[i]))

    cols = ["workout_start", "lap_index", "lap_count", "pool_length_m", "seconds",
            "strokes", "dist_per_stroke_m", "swolf", "stroke_style", "hr"]
    with open(args.out_csv, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=cols)
        wtr.writeheader()
        wtr.writerows(rows)

    swims_with = len({r["workout_start"] for r in rows})
    print(f"Swimming workouts total:        {len(workouts)}")
    print(f"Workouts with lap/stroke data:  {swims_with}")
    print(f"Total lengths captured:         {len(rows)}")
    dps = [r["dist_per_stroke_m"] for r in rows if r["dist_per_stroke_m"] != ""]
    sw = [r["swolf"] for r in rows if r["swolf"] != ""]
    if dps:
        print(f"Median distance/stroke:         {st.median(dps):.2f} m")
    if sw:
        print(f"Median SWOLF:                   {st.median(sw):.1f}")
    print(f"\nWrote {len(rows)} lengths to {args.out_csv}")


if __name__ == "__main__":
    main()
