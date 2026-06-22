#!/usr/bin/env python3
"""Generate fully synthetic swim test data — no personal data.

Writes:
  tests/sample_export.xml      schema-accurate mini Apple Health export. Deliberately
                               stresses the in-browser parser with the quirks a real
                               ~500 MB export has (see "REAL-SCHEMA STRESSORS" below).
  tests/sample_swim_laps.csv   the expected lap CSV (for tracker smoke tests)
  tests/sample_expected.json   counts + medians for the parser test to assert against

REAL-SCHEMA STRESSORS baked into sample_export.xml:
  - A full internal DTD subset (<!ELEMENT Record ...>, <!ATTLIST Record ...>) whose
    declarations literally contain "Record"/"Workout" — the parser must not mistake
    them for real elements.
  - Self-closing heart-rate records (the bulk of a real file) AND paired HRV records
    with nested <InstantaneousBeatsPerMinute> children, as noise.
  - device="..." attributes whose values contain escaped angle brackets (&lt; &gt;).
  - Both distance encodings: older totalDistance="..." attribute on some workouts,
    newer <WorkoutStatistics ...DistanceSwimming sum="..."/> child on others — with
    multiple WorkoutStatistics per workout in varied attribute order (type before sum
    AND sum before type) so distance extraction can't rely on ordering.
  - Stroke records carrying extra MetadataEntry children besides the stroke style.
  - Multiple stroke styles across swims (freestyle/backstroke) to test passthrough.
  - A non-swim workout (running) that must be skipped.
  - An open-water swim (Swimming workout with no stroke records) that must be skipped.
  - CRLF line endings throughout.

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
rng = random.Random(42)

# device string with escaped angle brackets, exactly like a real export
DEVICE = ('&lt;&lt;HKDevice: 0x281f8c0a0&gt;, name:Apple Watch, '
          'manufacturer:Apple Inc., model:Watch, software:10.4&gt;')


def fmt(d):
    return d.strftime("%Y-%m-%d %H:%M:%S ") + OFFSET


def make_swims():
    """~30 pool swims over 6 months with a gentle, deliberate trend so the tracker
    shows something: stroke rate drifting down, distance/stroke roughly flat. Each
    swim picks a stroke style (mostly freestyle) and a distance-encoding variant."""
    swims = []
    day = dt.datetime(2025, 1, 6, 7, 30, 0)
    for k in range(30):
        n = rng.choice([32, 36, 40, 40, 44])                 # lengths
        base_spm = 23.0 - k * 0.08 + rng.uniform(-0.6, 0.6)  # drifting down
        base_dps = 1.70 + rng.uniform(-0.05, 0.05)           # roughly flat
        # Mostly freestyle (style 2); a few backstroke (style 3) to test passthrough.
        style_code = "3" if k in (5, 17) else "2"
        # Rotate through the distance encodings the parser must handle.
        dist_mode = ["stat_type_first", "stat_sum_first", "total_attr"][k % 3]
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
        hr = round(118.0 - k * 0.3 + rng.uniform(-4, 4), 1)   # gently drifting avg HR
        swims.append({"start": day, "end": clock, "laps": laps,
                      "dist": n * POOL, "dur": dur_min,
                      "style_code": style_code, "dist_mode": dist_mode,
                      "hr": hr, "hrmin": int(round(hr - 28)), "hrmax": int(round(hr + 22))})
        day += dt.timedelta(days=rng.choice([2, 2, 3, 4, 7]))
    return swims


STYLE_NAME = {"2": "freestyle", "3": "backstroke"}

DTD = "\r\n".join([
    '<!DOCTYPE HealthData [',
    '<!ENTITY foo "bar">',
    '<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout|ActivitySummary)*)>',
    '<!ATTLIST HealthData locale CDATA #REQUIRED>',
    '<!ELEMENT Record (MetadataEntry|HeartRateVariabilityMetadataList)*>',
    '<!ATTLIST Record type CDATA #REQUIRED startDate CDATA #REQUIRED '
    'endDate CDATA #REQUIRED value CDATA #IMPLIED>',
    '<!ELEMENT Workout (MetadataEntry|WorkoutEvent|WorkoutStatistics|WorkoutRoute)*>',
    '<!ATTLIST Workout workoutActivityType CDATA #REQUIRED duration CDATA #IMPLIED>',
    '<!ELEMENT WorkoutStatistics EMPTY>',
    ']>',
])


def hr_self_closing(t):
    return (f' <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" '
            f'sourceVersion="10.4" device="{DEVICE}" unit="count/min" '
            f'startDate="{fmt(t)}" endDate="{fmt(t)}" value="{rng.randint(80, 160)}"/>')


def hrv_paired(t):
    # paired Record with nested children — must be skipped but parsed past correctly
    return ("\r\n".join([
        f' <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" '
        f'sourceName="Watch" unit="ms" startDate="{fmt(t)}" endDate="{fmt(t)}" value="42">',
        '  <HeartRateVariabilityMetadataList>',
        '   <InstantaneousBeatsPerMinute bpm="71" time="7:30:01.00 AM"/>',
        '   <InstantaneousBeatsPerMinute bpm="73" time="7:30:02.00 AM"/>',
        '  </HeartRateVariabilityMetadataList>',
        ' </Record>']))


def stroke_record(st_, en_, strokes, style_code):
    # paired record with the stroke-style metadata AND an extra metadata child
    return ("\r\n".join([
        f' <Record type="HKQuantityTypeIdentifierSwimmingStrokeCount" sourceName="Watch" '
        f'device="{DEVICE}" unit="count" startDate="{fmt(st_)}" endDate="{fmt(en_)}" '
        f'value="{strokes}">',
        f'  <MetadataEntry key="HKSwimmingStrokeStyle" value="{style_code}"/>',
        '  <MetadataEntry key="HKMetadataKeyHeartRateMotionContext" value="0"/>',
        ' </Record>']))


def distance_children(dist, mode):
    """Return the WorkoutStatistics/attribute markup for a swim's distance, in one of
    several real-world encodings. Always include an energy stat as a decoy."""
    energy = ('  <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" '
              'sum="320" unit="kcal"/>')
    strokes_stat = ('  <WorkoutStatistics '
                    'type="HKQuantityTypeIdentifierSwimmingStrokeCount" sum="600" unit="count"/>')
    if mode == "stat_type_first":
        dist_stat = (f'  <WorkoutStatistics '
                     f'type="HKQuantityTypeIdentifierDistanceSwimming" sum="{dist:g}" unit="m"/>')
    elif mode == "stat_sum_first":
        # sum attribute BEFORE type — extraction must not assume ordering
        dist_stat = (f'  <WorkoutStatistics sum="{dist:g}" '
                     f'type="HKQuantityTypeIdentifierDistanceSwimming" unit="m"/>')
    else:  # total_attr -> distance only via totalDistance on the Workout element
        dist_stat = None
    parts = [energy, strokes_stat]
    if dist_stat:
        parts.insert(1, dist_stat)
    return "\r\n".join(parts)


def write_xml(swims):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           DTD,
           '<HealthData locale="en_US">',
           ' <ExportDate value="2025-07-01 10:00:00 -0400"/>',
           ' <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"/>']

    # A non-swim workout up front that must be skipped.
    run_start = dt.datetime(2025, 1, 5, 18, 0, 0)
    out.append(
        f' <Workout workoutActivityType="HKWorkoutActivityTypeRunning" '
        f'duration="30.0000" durationUnit="min" sourceName="Watch" '
        f'startDate="{fmt(run_start)}" endDate="{fmt(run_start + dt.timedelta(minutes=30))}">\r\n'
        f'  <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" '
        f'sum="5000" unit="m"/>\r\n'
        f' </Workout>')

    for sw in swims:
        # heart-rate noise (self-closing — the bulk of a real export)
        for _ in range(rng.randint(2, 5)):
            hr = sw["start"] + dt.timedelta(seconds=rng.randint(1, 30))
            out.append(hr_self_closing(hr))
        # one HRV record (paired, nested) as additional noise
        out.append(hrv_paired(sw["start"] + dt.timedelta(seconds=1)))

        for (st_, en_, strokes) in sw["laps"]:
            out.append(stroke_record(st_, en_, strokes, sw["style_code"]))

        total_attr = (f' totalDistance="{sw["dist"]:g}" totalDistanceUnit="m"'
                      if sw["dist_mode"] == "total_attr" else "")
        out.append(
            f' <Workout workoutActivityType="HKWorkoutActivityTypeSwimming" '
            f'duration="{sw["dur"]:.4f}" durationUnit="min" sourceName="Watch"{total_attr} '
            f'startDate="{fmt(sw["start"])}" endDate="{fmt(sw["end"])}">\r\n'
            f'  <MetadataEntry key="HKMetadataKeyLapLength" value="{POOL:g} m"/>\r\n'
            f'{distance_children(sw["dist"], sw["dist_mode"])}\r\n'
            f'  <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" '
            f'startDate="{fmt(sw["start"])}" endDate="{fmt(sw["end"])}" '
            f'average="{sw["hr"]:g}" minimum="{sw["hrmin"]}" maximum="{sw["hrmax"]}" unit="count/min"/>\r\n'
            f' </Workout>')

    # An open-water swim: Swimming workout but NO stroke records -> must be skipped.
    ow_start = swims[-1]["end"] + dt.timedelta(days=3)
    out.append(
        f' <Workout workoutActivityType="HKWorkoutActivityTypeSwimming" '
        f'duration="40.0000" durationUnit="min" sourceName="Watch" '
        f'startDate="{fmt(ow_start)}" endDate="{fmt(ow_start + dt.timedelta(minutes=40))}">\r\n'
        f'  <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceSwimming" '
        f'sum="1500" unit="m"/>\r\n'
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
        style = STYLE_NAME[sw["style_code"]]
        for i, (st_, en_, strokes) in enumerate(sw["laps"], 1):
            secs = round((en_ - st_).total_seconds(), 1)
            dps = round(POOL / strokes, 3)
            spm = strokes / (secs / 60.0)
            spm_all.append(spm); dps_all.append(dps)
            rows.append({"workout_start": key, "lap_index": i, "lap_count": n,
                         "pool_length_m": POOL, "seconds": secs, "strokes": strokes,
                         "dist_per_stroke_m": dps, "swolf": round(secs + strokes, 1),
                         "stroke_style": style})
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
