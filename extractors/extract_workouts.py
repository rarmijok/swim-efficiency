#!/usr/bin/env python3
"""
Extract workout summaries from an Apple Health export.xml into a compact CSV.

Streams the file with iterparse and clears parsed elements as it goes, so it
uses almost no memory no matter how large export.xml is (500MB+ is fine).

Usage:
    python3 extract_workouts.py /path/to/export.xml workouts.csv
    python3 extract_workouts.py /path/to/export.xml swims.csv --type Swimming

The --type filter matches a substring of the activity name (case-insensitive),
e.g. Swimming, Running, Cycling, Walking.
"""
import sys
import csv
import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_workout(elem):
    """Pull a flat summary out of one <Workout> element."""
    atype = elem.get("workoutActivityType", "")
    row = {
        "activityType": atype.replace("HKWorkoutActivityType", ""),
        "startDate": elem.get("startDate", ""),
        "endDate": elem.get("endDate", ""),
        "duration": elem.get("duration", ""),
        "durationUnit": elem.get("durationUnit", ""),
        "totalDistance": elem.get("totalDistance", ""),
        "distanceUnit": elem.get("totalDistanceUnit", ""),
        "activeEnergy": elem.get("totalEnergyBurned", ""),
        "energyUnit": elem.get("totalEnergyBurnedUnit", ""),
        "sourceName": elem.get("sourceName", ""),
        # Heart rate over the workout (from the HeartRate WorkoutStatistics child,
        # iOS 16+). Cheap: an attribute read, no scanning of the per-sample records.
        "avgHeartRate": "",
        "minHeartRate": "",
        "maxHeartRate": "",
    }

    # iOS 16+ moves distance/energy into child <WorkoutStatistics> elements
    # instead of attributes on <Workout>, so fall back to those.
    for stat in elem.findall("WorkoutStatistics"):
        stype = stat.get("type", "")
        if "Distance" in stype and not row["totalDistance"]:
            row["totalDistance"] = stat.get("sum", "")
            row["distanceUnit"] = stat.get("unit", "")
        if "ActiveEnergyBurned" in stype and not row["activeEnergy"]:
            row["activeEnergy"] = stat.get("sum", "")
            row["energyUnit"] = stat.get("unit", "")
        # Exact match so we don't pick up HeartRateVariabilitySDNN etc.
        if stype == "HKQuantityTypeIdentifierHeartRate":
            avg = stat.get("average", "")
            try:
                avg = str(round(float(avg), 1))
            except (TypeError, ValueError):
                pass
            row["avgHeartRate"] = avg
            row["minHeartRate"] = stat.get("minimum", "")
            row["maxHeartRate"] = stat.get("maximum", "")

    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("xml_path")
    p.add_argument("out_csv")
    p.add_argument("--type", default=None,
                   help="Filter by activity type substring, e.g. Swimming")
    args = p.parse_args()

    fieldnames = [
        "activityType", "startDate", "endDate", "duration", "durationUnit",
        "totalDistance", "distanceUnit", "activeEnergy", "energyUnit",
        "sourceName", "avgHeartRate", "minHeartRate", "maxHeartRate",
    ]

    rows = []
    # events=("start","end") lets us grab the root so we can free its children.
    context = ET.iterparse(args.xml_path, events=("start", "end"))
    _, root = next(context)

    for event, elem in context:
        if event != "end":
            continue

        tag = elem.tag
        if tag == "Workout":
            row = parse_workout(elem)
            if not args.type or args.type.lower() in row["activityType"].lower():
                rows.append(row)
            elem.clear()
            root.clear()        # drop the millions of already-seen siblings
        elif tag == "Record":
            # The bulk of the file. We don't need these — just free them.
            elem.clear()
            root.clear()

    with open(args.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} workouts to {args.out_csv}\n")
    counts = defaultdict(int)
    for r in rows:
        counts[r["activityType"]] += 1
    for t, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
