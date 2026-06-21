#!/usr/bin/env python3
"""Generate fully synthetic swim test data — no personal data.

Writes:
  tests/sample_export.xml      schema-accurate mini Apple Health export (with HR noise,
                               paired SwimmingStrokeCount records, CRLF line endings)
  tests/sample_swim_laps.csv   the expected lap CSV (for tracker smoke tests)
  tests/sample_expected.json   counts + medians for the parser test to assert against

Run:  python3 tools/make_sample_data.py
Then: node tests/test_parser.mjs
"""
import os
import csv
import json
import random
import datetime as dt
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(os.path.dirname(HERE), "tests")
os.makedirs(TESTS, exist_ok=True)

POOL = 25.0
OFFSET = "-0400"
STYLE_CODE = "2"  # freestyle
rng = random.Random(42)


def fmt(d):
    return d.strftime("%Y-%m-%d %H:%M:%S ") + OFFSET


def make_swims():
    """~30 swims over 6 months with a gentle, deliberate trend so the tracker shows
    something: stroke rate drifting down, distance/stroke roughly flat."""
    swims = []
    day = dt.datetime(2025, 1, 6, 7, 30, 0)
    for k in range(30):
        n = rng.choice([32, 36, 40, 40, 44])           # lengths
        base_spm = 23.0 - k * 0.08 + rng.uniform(-0.6, 0.6)  # drifting down
        base_dps = 1.70 + rng.uniform(-0.05, 0.05)     # roughly flat
        laps = []
        clock = day
        for _ in range(n):
            spm = max(14.0, base_spm + rng.uniform(-1.2, 1.2))
            dps = max(1.2, base_dps + rng.uniform(-0.08, 0.08))
            strokes = max(8, round(POOL / dps))
            secs = round(strokes / (spm / 60.0), 1)
            st_ = clock
            en_ = clock + dt.timedelta(seconds=secs)
            laps.append((st_, en_, strokes))
            clock = en_ + dt.timedelta(seconds=rng.uniform(0.5, 3.0))
        dur_min = (clock - day).total_seconds() / 60.0
        swims.append({"start": day, "end": clock, "laps": laps,
                      "dist": n * POOL, "dur": dur_min})
        day += dt.timedelta(days=rng.choice([2, 2, 3, 4, 7]))
    return swims


def write_xml(swims):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE HealthData [ <!ENTITY foo "bar"> ]>',
           '<HealthData locale="en_US">',
           ' <ExportDate value="2025-07-01 10:00:00 -0400"/>',
           ' <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>']
    for sw in swims:
        # heart-rate noise (self-closing records — the bulk of a real export)
        for _ in range(rng.randint(2, 5)):
            hr = sw["start"] + dt.timedelta(seconds=rng.randint(1, 30))
            out.append(f' <Record type="HKQuantityTypeIdentifierHeartRate" '
                       f'sourceName="Watch" unit="count/min" startDate="{fmt(hr)}" '
                       f'endDate="{fmt(hr)}" value="{rng.randint(80, 160)}"/>')
        for (st_, en_, strokes) in sw["laps"]:
            out.append(
                f' <Record type="HKQuantityTypeIdentifierSwimmingStrokeCount" '
                f'sourceName="Watch" unit="count" startDate="{fmt(st_)}" '
                f'endDate="{fmt(en_)}" value="{strokes}">\n'
                f'  <MetadataEntry key="HKSwimmingStrokeStyle" value="{STYLE_CODE}"/>\n'
                f' </Record>')
        out.append(
            f' <Workout workoutActivityType="HKWorkoutActivityTypeSwimming" '
            f'duration="{sw["dur"]:.4f}" durationUnit="min" sourceName="Watch" '
            f'startDate="{fmt(sw["start"])}" endDate="{fmt(sw["end"])}">\n'
            f'  <MetadataEntry key="HKMetadataKeyLapLength" value="{POOL:g} m"/>\n'
            f'  <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceSwimming" '
            f'sum="{sw["dist"]:g}" unit="m"/>\n'
            f' </Workout>')
    out.append('</HealthData>')
    xml = "\r\n".join(out) + "\r\n"  # CRLF to stress the parser
    with open(os.path.join(TESTS, "sample_export.xml"), "w", encoding="utf-8") as f:
        f.write(xml)


def write_csv_and_expected(swims):
    cols = ["workout_start", "lap_index", "lap_count", "pool_length_m", "seconds",
            "strokes", "dist_per_stroke_m", "swolf", "stroke_style"]
    rows = []
    spm_all, dps_all = [], []
    for sw in swims:
        key = sw["start"].strftime("%Y-%m-%d %H:%M")
        n = len(sw["laps"])
        for i, (st_, en_, strokes) in enumerate(sw["laps"], 1):
            secs = round((en_ - st_).total_seconds(), 1)
            dps = round(POOL / strokes, 3)
            spm = strokes / (secs / 60.0)
            spm_all.append(spm); dps_all.append(dps)
            rows.append({"workout_start": key, "lap_index": i, "lap_count": n,
                         "pool_length_m": POOL, "seconds": secs, "strokes": strokes,
                         "dist_per_stroke_m": dps, "swolf": round(secs + strokes, 1),
                         "stroke_style": "freestyle"})
    with open(os.path.join(TESTS, "sample_swim_laps.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    expected = {"n_swims": len(swims), "n_lengths": len(rows),
                "median_spm": round(st.median(spm_all), 2),
                "median_dps": round(st.median(dps_all), 3)}
    with open(os.path.join(TESTS, "sample_expected.json"), "w") as f:
        json.dump(expected, f, indent=2)
    return expected


if __name__ == "__main__":
    swims = make_swims()
    write_xml(swims)
    exp = write_csv_and_expected(swims)
    print("wrote tests/sample_export.xml, tests/sample_swim_laps.csv, tests/sample_expected.json")
    print("expected:", exp)
