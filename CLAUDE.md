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
- **Associating strokes to a swim**: a stroke record belongs to a workout if its start is
  within `[workout.start, workout.end)`. Open-water swims have no stroke records (skip them).
- **Pool length** = lap-length metadata if present, else `total_distance / num_lengths`.
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
- **CSS** (Critical Swim Speed) /100m = `(400m TT time − 200m TT time) / 2`

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
   - **STILL TODO**: validate against a real ~500 MB `data/export.xml` (gitignored) once present
     — confirm the XML path reproduces the same per-year medians as `swim_laps.csv` (docs/FINDINGS.md)
     and that parse time / memory are acceptable at full scale. Only synthetic data has been used so far.

2. **Save & compare exports**. Each new drop should show what changed since last time.
   - Add a **"Save checkpoint"** button that downloads a small JSON of the per-swim aggregates
     (date, spm, dps, pace100, swolf, key). On load, accept a checkpoint JSON → use as baseline.
   - Show a **"since last check"** panel: count of new swims + deltas in spm/DPS/pace, and
     highlight swims newer than the checkpoint on the scatter and in the table.
   - **localStorage caveat**: a file:// page often has an opaque origin where `localStorage`
     throws or doesn't persist. Treat downloaded checkpoint files as the reliable mechanism;
     use `localStorage` only as a best-effort convenience wrapped in try/catch with graceful
     fallback. Do **not** depend on it.

## Conventions & guardrails

- The tracker is a **single self-contained HTML file, no external/CDN dependencies** (it must
  work offline from `file://`). Keep it that way — hand-roll any parsing/charting; no libraries.
- Charts are vanilla SVG built in JS. Two-accent color code is meaningful: **amber = stroke
  rate (raise)**, **teal = distance/stroke (hold)**. Don't break that mapping.
- Never commit the swimmer's real data. `export.xml` and the personal CSVs are gitignored.
  Use `tools/make_sample_data.py` for anything that needs sample data in the repo.
- The extractors intentionally have **zero pip dependencies** (stdlib only). Keep them portable.
