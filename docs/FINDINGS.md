# Findings

Analysis of 227 swims, Nov 2024 → Jun 2026, all freestyle in a 25 m pool, single source
(Apple Watch). These are the conclusions the tracker and plan are built around, and the
**validation targets** for any reimplementation of the data pipeline (the XML parser should
reproduce these per-year medians).

## Per-year medians (controlled: freestyle, 800–1200 m swims)

| Year | n  | spm  | DPS (m) | SWOLF | pure pace /100m |
|------|----|------|---------|-------|-----------------|
| 2024 | 21 | 22.9 | 1.56    | 56    | 2:44            |
| 2025 | 85 | 21.1 | 1.79    | 54    | 2:39            |
| 2026 | 38 | 19.6 | 1.79    | 57    | 2:52            |

Overall median DPS ≈ 1.79 m. Best continuous efforts: 100 m ≈ 1:27, 200 m ≈ 1:37, 400 m ≈ 1:59
per 100 m (pure-swim pace); rough CSS estimate ≈ 2:21–2:25 /100m (confirm with a real TT).

## The core story

1. **Stroke length improved then plateaued.** DPS rose 1.56 → 1.79 (2024→2025), then flat.
2. **Stroke rate has fallen steadily.** 22.9 → 21.1 → 19.6 spm. The swimmer drifted toward a
   slower, glide-heavy stroke.
3. **In-water speed got slower in 2026.** Pure-swim pace 2:44 → 2:39 → 2:52 /100m.
4. **The slowdown was masked by less rest.** Session pace (incl. rest) stayed ~3:40 because
   rest fell from ~34% to ~24% of each session. The summary numbers alone were misleading.
5. **Speed is driven by turnover, not stroke length, for this swimmer.** Length speed
   correlates −0.72 with spm and +0.02 with DPS. Lowering the stroke rate while DPS was already
   maxed was a net brake.

## Implications (encoded in the tools)

- **Target zone**: spm 22–24 while holding DPS ≥ 1.79. Projects to ~2:21–2:32 /100m.
- The tracker's hero "balance" chart plots spm vs DPS with this zone and equal-pace contours.
- The 8-week plan's whole thesis is "raise turnover, hold length" (tempo work + dryland power
  + the rule: don't let strokes-per-length climb when adding tempo).
- Within-swim fade is minor (≈2 s/length and ≈2 spm slower in the final quarter) — endurance is
  fine; the ceiling is turnover.

## Caveats

- Energy/calorie figures are Apple Watch estimates — treat as ballpark.
- A few months have gaps (Feb 2025, Jul 2025, Feb 2026) — breaks or uncaptured.
- CSS estimate from best efforts is not a clean test; a dedicated 400 m + 200 m TT is better.
