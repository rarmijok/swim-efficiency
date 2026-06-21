/* parser_wip.js — DRAFT in-browser Apple Health export.xml parser.
 *
 * STATUS: works against synthetic data (tests/test_parser.mjs); NOT yet validated
 *         against a real ~500 MB export. See CLAUDE.md -> UNFINISHED WORK.
 *
 * Goal: let the tracker ingest export.xml directly instead of running the Python
 * extractors. Streams the file in chunks (flat memory), pulls out swimming workouts
 * and per-length SwimmingStrokeCount records, and emits the SAME lap rows the Python
 * extractor produces, plus summary rows for rest analysis. Feed the lapRows into the
 * tracker's existing aggregate().
 *
 * Integration note: the tracker is a single dependency-free HTML file, so the final
 * step is to INLINE these functions into swim_tracker.html (don't ship a separate JS
 * file / no <script src> over file:// if it can be avoided). This file is structured
 * to also load as a CommonJS module for node testing.
 *
 * Apple schema reminders (see CLAUDE.md for detail):
 *  - <Record type="...SwimmingStrokeCount" startDate endDate value> usually has a
 *    <MetadataEntry key="HKSwimmingStrokeStyle" value="N"/> child (paired tag).
 *  - Heart-rate records are self-closing <Record .../> and are the bulk of the file.
 *  - <Workout ...> distance is a totalDistance attr OR a <WorkoutStatistics ...Distance
 *    sum="..."/> child; pool length may be <MetadataEntry key="HKMetadataKeyLapLength"
 *    value="25 m"/>.
 *  - Associate a stroke record to a workout when start in [workout.start, workout.end).
 */

function makeHealthParser() {
  let buf = "";
  const strokes = [];
  const workouts = [];
  const STROKE_TYPE = "HKQuantityTypeIdentifierSwimmingStrokeCount";

  function attrs(openTag) {
    const o = {};
    let m;
    const re = /([\w:]+)="([^"]*)"/g;
    while ((m = re.exec(openTag))) o[m[1]] = m[2];
    return o;
  }

  // Consume every COMPLETE element currently in buf; leave any trailing partial
  // element in buf for the next feed(). Keeps memory flat.
  function drain() {
    let i = 0;
    for (;;) {
      const lt = buf.indexOf("<", i);
      if (lt < 0) { buf = ""; return; }

      // Any element we process needs its opening '>' present. If it isn't here yet,
      // this is a partial tag split across the chunk boundary — wait for more.
      const gt = buf.indexOf(">", lt);
      if (gt < 0) { buf = buf.slice(lt); return; }

      if (buf.startsWith("<Record", lt)) {
        const selfClose = buf[gt - 1] === "/";
        const openTag = buf.slice(lt, gt + 1);
        let endIdx;
        if (selfClose) {
          endIdx = gt + 1;
        } else {
          const close = buf.indexOf("</Record>", gt);
          if (close < 0) { buf = buf.slice(lt); return; } // body split across chunks
          endIdx = close + 9; // "</Record>".length
        }
        if (openTag.indexOf(STROKE_TYPE) >= 0) {
          const a = attrs(openTag);
          let style = null;
          if (!selfClose) {
            const inner = buf.slice(gt + 1, endIdx);
            const sm = inner.match(/HKSwimmingStrokeStyle"\s+value="([^"]*)"/);
            if (sm) style = sm[1];
          }
          strokes.push({ start: a.startDate, end: a.endDate, value: +a.value || 0, style });
        }
        i = endIdx;

      } else if (buf.startsWith("<Workout ", lt)) {
        const selfClose = buf[gt - 1] === "/";
        let endIdx, block;
        if (selfClose) {
          endIdx = gt + 1;
          block = buf.slice(lt, endIdx);
        } else {
          const close = buf.indexOf("</Workout>", lt);
          if (close < 0) { buf = buf.slice(lt); return; } // workout body split
          endIdx = close + 10; // "</Workout>".length
          block = buf.slice(lt, endIdx);
        }
        const ogt = block.indexOf(">");
        const a = attrs(block.slice(0, ogt + 1));
        if ((a.workoutActivityType || "").indexOf("Swimming") >= 0) {
          let dist = a.totalDistance ? +a.totalDistance : null;
          if (dist == null) {
            const dm = block.match(/<WorkoutStatistics[^>]*Distance[^>]*\bsum="([^"]*)"/);
            if (dm) dist = +dm[1];
          }
          let lapLen = null;
          const lm = block.match(/LapLength"\s+value="([\d.]+)/);
          if (lm) lapLen = +lm[1];
          workouts.push({
            start: a.startDate, end: a.endDate, dist, lapLen,
            dur: a.duration ? +a.duration : null, source: a.sourceName || ""
          });
        }
        i = endIdx;

      } else {
        // ExportDate, Me, HealthData, DOCTYPE, ActivitySummary, Correlation, etc.
        // Skip the opening tag; any children get handled on subsequent iterations.
        i = gt + 1;
      }

      // Compact so the buffer doesn't grow unbounded within one big chunk.
      if (i > (1 << 20)) { buf = buf.slice(i); i = 0; }
    }
  }

  return {
    feed(chunk) { buf += chunk; drain(); },
    finish() { drain(); return { strokes, workouts }; }
  };
}

function parseAppleDate(s) {
  // "2024-11-07 07:55:36 -0400" -> epoch ms (UTC)
  const m = s && s.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})\s*([+-])(\d{2})(\d{2})/);
  if (!m) return NaN;
  const sign = m[7] === "-" ? -1 : 1;
  const offMin = sign * (parseInt(m[8], 10) * 60 + parseInt(m[9], 10));
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) - offMin * 60000;
}

const STYLE_NAME = { "0": "unknown", "1": "mixed", "2": "freestyle",
                     "3": "backstroke", "4": "breaststroke", "5": "butterfly" };

function buildLapRows(strokes, workouts) {
  const W = workouts.map(w => ({ ...w, s: parseAppleDate(w.start), e: parseAppleDate(w.end) }))
                    .filter(w => isFinite(w.s) && isFinite(w.e))
                    .sort((a, b) => a.s - b.s);
  const S = strokes.map(r => ({ ...r, s: parseAppleDate(r.start), e: parseAppleDate(r.end) }))
                   .filter(r => isFinite(r.s))
                   .sort((a, b) => a.s - b.s);
  const lapRows = [];
  for (const w of W) {
    // O(W*S); fine at these sizes. Optimize with a pointer sweep if needed.
    const laps = S.filter(r => r.s >= w.s && r.s < w.e);
    if (!laps.length) continue;             // open-water / phone-logged swims: no lengths
    const n = laps.length;
    const pool = w.lapLen != null ? w.lapLen : (w.dist != null ? w.dist / n : null);
    const key = w.start.slice(0, 16);        // "YYYY-MM-DD HH:MM", original offset
    laps.forEach((r, idx) => {
      const secs = (r.e - r.s) / 1000;
      const strk = r.value;
      const dps = (pool && strk) ? pool / strk : null;
      const swolf = strk ? secs + strk : null;
      lapRows.push({
        workout_start: key,
        lap_index: idx + 1,
        lap_count: n,
        pool_length_m: pool != null ? Math.round(pool * 100) / 100 : "",
        seconds: Math.round(secs * 10) / 10,
        strokes: strk,
        dist_per_stroke_m: dps != null ? Math.round(dps * 1000) / 1000 : "",
        swolf: swolf != null ? Math.round(swolf * 10) / 10 : "",
        stroke_style: STYLE_NAME[r.style] || r.style || ""
      });
    });
  }
  const summaryRows = W.filter(w => w.dur != null).map(w => ({
    startDate: w.start, duration: w.dur, totalDistance: w.dist
  }));
  return { lapRows, summaryRows };
}

/* Browser entry point. Streams a File in chunks with flat memory.
 * onProgress(bytesDone, bytesTotal) drives a progress bar.
 * Returns { lapRows, summaryRows }. */
async function parseHealthExport(file, onProgress) {
  const parser = makeHealthParser();
  const CHUNK = 8 * 1024 * 1024;
  const dec = new TextDecoder("utf-8");
  let offset = 0;
  while (offset < file.size) {
    const slice = file.slice(offset, Math.min(offset + CHUNK, file.size));
    const bytes = await slice.arrayBuffer();
    parser.feed(dec.decode(bytes, { stream: true })); // stream:true handles UTF-8 split across chunks
    offset += CHUNK;
    if (onProgress) onProgress(Math.min(offset, file.size), file.size);
  }
  parser.feed(dec.decode()); // flush any trailing bytes
  const { strokes, workouts } = parser.finish();
  return buildLapRows(strokes, workouts);
}

// CommonJS export for node testing; harmless in the browser.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { makeHealthParser, buildLapRows, parseAppleDate, parseHealthExport };
}
