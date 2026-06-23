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
import argparse
import statistics as st
import xml.etree.ElementTree as ET
from datetime import datetime

STROKE = "HKQuantityTypeIdentifierSwimmingStrokeCount"
SWIM = "HKWorkoutActivityTypeSwimming"
STYLE_MAP = {"0": "unknown", "1": "mixed", "2": "freestyle",
             "3": "backstroke", "4": "breaststroke", "5": "butterfly"}


def pdate(s):
    # e.g. "2024-11-07 07:55:36 -0400"
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")


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
            rows.append({
                "workout_start": w["s"].strftime("%Y-%m-%d %H:%M"),
                "lap_index": i,
                "lap_count": n,
                "pool_length_m": round(pool, 2) if pool else "",
                "seconds": round(secs, 1),
                "strokes": int(sn) if sn == int(sn) else sn,
                "dist_per_stroke_m": round(dps, 3) if dps else "",
                "swolf": round(swolf, 1) if swolf else "",
                "stroke_style": r["style"] or "",
            })

    cols = ["workout_start", "lap_index", "lap_count", "pool_length_m", "seconds",
            "strokes", "dist_per_stroke_m", "swolf", "stroke_style"]
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
