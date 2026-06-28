# CLAUDE.md — project context for Claude Code

This file orients you (Claude) when working in this repo. Read it first.

## What this project is

A personal, local-first **swim efficiency analysis toolkit** built from one swimmer's
Apple Health data. It turns an Apple Health export into lap-level metrics and a browser
dashboard, plus a training plan. Everything runs locally; the swimmer's health data never
leaves their machine. The owner (referred to as "the swimmer" below) is technical, works on
Ubuntu and macOS, and is comfortable in the terminal and with Python/JS.

The toolkit exists to answer one coaching question: **is the swimmer's speed improving, and
through which lever — stroke efficiency or effort?** The analysis below already answered it;
the tooling now tracks it ongoing.

## The data pipeline

```
Apple Health "Export All Health Data" -> export.zip -> (unzip) -> export.xml  (~500 MB)
        |
        |  extractors/extract_workouts.py     -> workouts.csv   (per-swim summary)
        |  extractors/extract_swim_laps.py    -> swim_laps.csv  (per-length detail)
        v
   tracker/swim_tracker.html  (drop the CSV in -> dashboard)
```

`export.xml` is enormous and is **mostly `<Record type="HKQuantityTypeIdentifierHeartRate">`
samples**. The swim data is a tiny fraction. Both extractors stream the file with
`xml.etree.ElementTree.iterparse` and clear elements as they go, so memory stays flat. Never
load the whole file into memory.

### Apple Health XML schema quirks (important for the in-browser parser)

- **Per-length strokes** live in top-level records:
  `<Record type="HKQuantityTypeIdentifierSwimmingStrokeCount" startDate="..." endDate="..." value="N"> <MetadataEntry key="HKSwimmingStrokeStyle" value="2"/> </Record>`
  The record's start→end span is the **time for that length**; `value` is the stroke count.
  These are usually **paired tags** (they have a metadata child). Heart-rate records are
  **self-closing** `<Record .../>`. The parser must handle both forms.
- **Stroke style** values: 0 unknown, 1 mixed, 2 freestyle, 3 backstroke, 4 breaststroke, 5 butterfly.
- **Workouts**: `<Workout workoutActivityType="HKWorkoutActivityTypeSwimming" duration="36.5" durationUnit="min" startDate="..." endDate="..."> ...children... </Workout>`.
  Distance is either a `totalDistance` attribute (older exports) or a child
  `<WorkoutStatistics type="HKQuantityTypeIdentifierDistanceSwimming" sum="1000" unit="m"/>` (iOS 16+).
  Pool length may appear as `<MetadataEntry key="HKMetadataKeyLapLength" value="25 m"/>`.
- **Per-workout heart rate** is a child `<WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate"
  average="113.6" minimum="62" maximum="136" unit="count/min"/>` — read avg/min/max off that
  attribute (exact type match, so HRV doesn't sneak in). This is the cheap per-swim HR source.
  `extract_workouts.py` writes `avgHeartRate`/`minHeartRate`/`maxHeartRate` into `swims.csv`; the
  in-browser parser puts the same on its summary rows, so HR flows through the existing summary merge.
- **Per-length heart rate** comes from the **per-sample** `<Record type="HKQuantityTypeIdentifierHeartRate"
  startDate="…" value="N"/>` rows (the millions that pass 1 skips). The `hr` column on `swim_laps.csv`
  is the average of the samples whose `startDate` lands in a length's `[stroke.start, stroke.end)`
  window — computed in a **second streaming pass** since the windows aren't known until all workouts
  are read. Match the type **exactly** (`"…HeartRate"`) so HeartRateVariability… doesn't get counted.
- **Associating strokes to a swim**: a stroke record belongs to a workout if its start is
  within `[workout.start, workout.end)`. Open-water swims have no stroke records (skip them).
- **Pool length** = lap-length metadata if present, else `total_distance / num_lengths`. The
  `HKMetadataKeyLapLength` value carries a unit (`"25 m"`, `"25 yd"`); **yards are converted to
  metres** (×0.9144) in both the Python extractor and the in-browser parser, so every metric stays
  metric. `pool_length_m` is therefore always metres. The footer surfaces the pool length(s).
- **Dates** look like `2024-11-07 07:55:36 -0400` (note the timezone offset).
- **`workout_start` key**: the first 16 chars of the start date, `YYYY-MM-DD HH:MM`, kept in
  the **original offset (not converted to another timezone)**. The CSV path and the XML path
  MUST produce identical keys, or the optional `swims.csv` rest-merge breaks.

## Metric definitions (used everywhere — keep consistent)

- `spm` (strokes/min) = `strokes / (seconds/60)` — **turnover / cadence**
- `dist_per_stroke` (DPS, m) = `pool_length / strokes` — **stroke length / efficiency**
- `SWOLF` = `seconds + strokes` per length (lower = better)
- **pure-swim pace** /100m = `sum(length seconds) / distance * 100` (rest excluded)
- **session pace** /100m = `workout duration / distance * 100` (rest included)
- **speed** = `(spm/60) * DPS`  — the identity the whole tool is built around
- **cardiac cost** (beats/100m) = `avg_HR/60 * pure-swim pace/100m` — **HR-economy: heartbeats spent
  per 100 m. Lower = fitter/more efficient (faster and/or lower HR), not just "tried harder".** Needs
  `swims.csv` (or the XML path) for HR; gated by the `HASHR` flag like rest% is by `SUMMARY`.
- **CSS** (Critical Swim Speed) /100m = `(400m TT time − 200m TT time) / 2`
- **tempo set** = a contiguous run (≥2 lengths) within one swim where stroke rate is lifted
  ≥ `max(1.5, 8%)` spm over the swim's **cruise cadence** (median spm of the calmer half of
  lengths). For each set the tracker checks the plan's golden rule — did stroke length **hold**?
  `held` = set-median DPS ≥ cruise DPS − 0.10 m (≈ one extra stroke). Surfaced in "Inside one
  swim": shaded bands (green outline = held, red = count ballooned) + a one-line verdict.
  `detectTempoSets()` is pure (off `swim.laps`); on the current data most swims show none — the
  honest signal that the prescribed rate-up work isn't happening yet.

## What the analysis found (the "why" behind the tracker)

Dataset: 227 swims, Nov 2024 → Jun 2026, all freestyle in a 25 m pool, single source (Apple Watch).

- **DPS rose then stalled**: 1.56 m (2024) → 1.79 m (2025) → 1.79 m (2026). Efficiency improved, then plateaued.
- **Stroke rate has steadily fallen**: 22.9 → 21.1 → 19.6 spm across 2024/25/26.
- **Pure-swim pace got SLOWER in the last year**: 2:44 → 2:39 → 2:50 /100m.
- The **session pace looked flat (~3:40)** only because rest dropped from **34% → 24%** of each
  session. Less rest masked an in-water slowdown.
- Across swims, length speed correlates with **stroke rate (−0.72)** and **not with DPS (+0.02)**.
  The swimmer over-optimized stroke length and let turnover drift down — a net brake.
- **Targets**: raise spm to **22–24** while holding **DPS ≥ 1.79**. By the swimmer's own numbers
  that projects to ~**2:21–2:32 /100m** (from ~2:50 now).
- Within-swim fade is minor (lengths slow ~2s, rate drops ~2 spm in the final quarter).

The training plan (`plan/`) and the tracker's "target zone" both encode these targets.

## How to run things

```bash
# extract (on the machine with export.xml; Python 3, no deps for the extractors)
python3 extractors/extract_swim_laps.py path/to/export.xml data/swim_laps.csv
python3 extractors/extract_workouts.py  path/to/export.xml data/workouts.csv

# tracker: open tracker/swim_tracker.html in a browser, then EITHER
#   - drop the raw Apple Health export.xml on it (parsed in-browser, no Python step), OR
#   - drop data/swim_laps.csv (optionally also data/workouts.csv -> adds rest analysis)

# plan PDF (needs weasyprint)
pip install -r requirements.txt
python3 plan/generate_plan.py        # plan/plan.html -> plan/swim_plan_8week.pdf

# generate synthetic test data (no personal data) for parser testing
python3 tools/make_sample_data.py    # writes tests/sample_export.xml + tests/sample_swim_laps.csv
node tests/test_parser.mjs           # extracts the parser from swim_tracker.html and checks it
                                     # reproduces extract_swim_laps.py row-for-row (needs node)
```

## UNFINISHED WORK — pick up here

1. **Ingest `export.xml` directly in the tracker** — ✅ **DONE**. The streaming parser now
   lives inline in `swim_tracker.html` between the `BEGIN/END health-xml-parser` markers
   (no separate file — the old `tracker/parser_wip.js` was removed). `ingest()` detects XML
   (by `.xml` extension or by sniffing for `<?xml` / `<HealthData`) and streams it in ~8 MB
   chunks with a progress bar; the CSV path still works unchanged. `tests/test_parser.mjs`
   extracts that exact block and asserts it reproduces `extract_swim_laps.py` row-for-row on
   a quirky synthetic export, across every chunk-boundary.
   - **Validated against the real export** (809 MB, HealthKit Export Version 14): the XML path
     reproduces `data/swim_laps.csv` exactly — **8680 lengths across 228 swims, every row matching**
     (keys exact, metrics within rounding, incl. per-length `hr`) and identical per-year SPM/DPS
     medians. Two streaming passes (workouts/strokes, then per-length HR) in ~2 s with flat memory
     (peak RSS ~480 MB in node). Re-run any time with
     `node tools/validate_xml_parser.mjs <export.xml> <swim_laps.csv>`.

2. **Compare two periods** — ✅ **DONE** (section 06 "Compare two periods" in the tracker).
   The swimmer chose this over the original "since last check" checkpoint idea: instead of a
   saved baseline, pick **two arbitrary date ranges (A and B)** and see how the stroke moved.
   - **Presets + custom**: a preset dropdown of rolling windows anchored at the latest swim —
     last 7 days vs previous 30, last 30 vs previous 30, last 90 vs previous 90 (default), last 180
     vs previous 180, last year vs previous year — fills four `<input type=date>` fields; editing any
     field switches the preset to "Custom". (B = the recent window, A = the window immediately before.)
   - **Comparison strip** (A · B · Δ) for swims, distance, SPM, DPS, pure pace, SWOLF, and —
     when `swims.csv`/summary is present — session pace + rest%. Δ is colored by *meaning*
     (`.up`/`.down`/`.flat`): SPM up = good, pace/SWOLF down = good, DPS/volume neutral.
   - **Two-color scatter** reusing the hero balance geometry: period-A dots (`--pace` blue),
     period-B dots (`--rate` amber), a median ring per period, and a **white arrow A→B** that
     visualizes the drift. Plus a one-line plain-English verdict naming the dominant lever.
   - All in-memory off the loaded dataset (no files/localStorage). Renders via `buildCompare()`
     in `build()`; key fns: `computePresets`, `renderCompare`, `renderCompareScatter`.
   - Verified on the real data: the default "2025 vs 2026" reproduces FINDINGS exactly
     (SPM 21.1→19.6, DPS held 1.79, pure pace 2:39→2:50) with the verdict pinning the cause to
     falling turnover.

3. **Heart rate / effort & economy** — ✅ **DONE** (section 04 "Effort & economy" + HR everywhere).
   Per-swim avg/max HR comes from the workout's HeartRate `WorkoutStatistics` (cheap; no per-sample
   scan), flows through the summary merge (`HASHR` flag), and surfaces as: KPI tiles (avg HR,
   beats/100m), a table column, an A/B comparison row, and the **economy trend** (beats/100m =
   cardiac cost, lower=better). `extract_workouts.py` writes the HR columns so the CSV path has
   parity with the XML path. Verified on real data: avg HR ~flat 2025→2026 (112→111) while
   beats/100m **rose 298→316** — i.e. the slowdown is paid effort, not reduced effort.
   - **Per-length HR / within-swim cardiac drift** — ✅ **DONE**. A `hr` column on each length
     (avg of the per-sample `<Record type="…HeartRate"/>` records whose timestamp falls in that
     length's window). It needs a **second streaming pass** (the length windows aren't known until
     all workouts are read): the in-browser `parseHealthExport` runs pass 1 (workouts+strokes →
     `buildLapRows` + per-length `windows`) then pass 2 (`makeHRScanner` averages HR into the
     windows, flat memory); `extract_swim_laps.py` mirrors this with a second `iterparse` (fast
     hand-parsed dates + a swim-day prefix filter so it skips the all-day HR firehose; ~16 s on the
     809 MB export). "Inside one swim" overlays the HR line (red, right axis). Verified: JS == Python
     per-length HR row-for-row on synthetic + the real export (8680 lengths / 228 swims).

Beyond that there is **no remaining planned work**. Future ideas live in the swimmer's head; ask
before inventing scope.

## Conventions & guardrails

- The tracker is a **single self-contained HTML file, no external/CDN dependencies** (it must
  work offline from `file://`). Keep it that way — hand-roll any parsing/charting; no libraries.
- Charts are vanilla SVG built in JS. Two-accent color code is meaningful: **amber = stroke
  rate (raise)**, **teal = distance/stroke (hold)**. Don't break that mapping.
- Never commit the swimmer's real data. `export.xml` and the personal CSVs are gitignored.
  Use `tools/make_sample_data.py` for anything that needs sample data in the repo.
- The extractors intentionally have **zero pip dependencies** (stdlib only). Keep them portable.
