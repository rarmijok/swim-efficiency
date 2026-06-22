/* validate_xml_parser.mjs — validate the in-browser parser against a REAL export.
 *
 *   node tools/validate_xml_parser.mjs <export.xml> <swim_laps.csv>
 *
 * Streams a real Apple Health export.xml through the exact parser shipped in
 * tracker/swim_tracker.html (extracted between its BEGIN/END markers), then checks
 * that it reproduces the Python extractor's swim_laps.csv row-for-row — the
 * "CSV path and XML path MUST produce identical keys" guarantee, at full scale.
 * Reports parse time, peak RSS, row/swim counts, and per-year medians.
 *
 * Reads only the paths you pass (data/ is gitignored). Prints no personal data
 * beyond aggregate medians.
 */
import { readFileSync, writeFileSync, createReadStream } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const xmlPath = process.argv[2] || join(__dirname, "..", "data", "apple_health_export", "export.xml");
const csvPath = process.argv[3] || join(__dirname, "..", "data", "swim_laps.csv");

function loadParserFromTracker() {
  const html = readFileSync(join(__dirname, "..", "tracker", "swim_tracker.html"), "utf8");
  const m = html.match(/BEGIN health-xml-parser[\s\S]*?\*\/\n([\s\S]*?)\/\* =+ END health-xml-parser/);
  if (!m) throw new Error("could not find the health-xml-parser block in swim_tracker.html");
  const src = m[1] + "\nmodule.exports={makeHealthParser,buildLapRows};\n";
  const tmp = join(tmpdir(), `health_parser_validate_${process.pid}.cjs`);
  writeFileSync(tmp, src);
  return require(tmp);
}
const { makeHealthParser, buildLapRows } = loadParserFromTracker();

function median(a) {
  const b = a.filter(Number.isFinite).slice().sort((x, y) => x - y);
  if (!b.length) return NaN;
  const m = b.length >> 1;
  return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2;
}
function parseCSV(text) {
  const lines = text.replace(/﻿/, "").split(/\r?\n/).filter(l => l.trim().length);
  const head = lines[0].split(",").map(h => h.trim());
  return lines.slice(1).map(l => {
    const c = l.split(","); const o = {};
    head.forEach((h, i) => (o[h] = (c[i] ?? "").trim()));
    return o;
  });
}

async function streamParse(path) {
  const parser = makeHealthParser();
  const dec = new TextDecoder("utf-8");
  const stream = createReadStream(path, { highWaterMark: 8 * 1024 * 1024 });
  let bytes = 0, lastLog = 0;
  const total = require("node:fs").statSync(path).size;
  for await (const chunk of stream) {
    parser.feed(dec.decode(chunk, { stream: true }));
    bytes += chunk.length;
    if (bytes - lastLog > 100 * 1024 * 1024) {
      lastLog = bytes;
      const rss = (process.memoryUsage().rss / 1048576).toFixed(0);
      process.stdout.write(`  …${(bytes / 1048576).toFixed(0)}/${(total / 1048576).toFixed(0)} MB  (RSS ${rss} MB)\n`);
    }
  }
  parser.feed(dec.decode());
  const { strokes, workouts } = parser.finish();
  return buildLapRows(strokes, workouts);
}

function yearMedians(rows) {
  const byYear = {};
  for (const r of rows) {
    const y = String(r.workout_start).slice(0, 4);
    (byYear[y] = byYear[y] || []).push(r);
  }
  const out = {};
  for (const y of Object.keys(byYear).sort()) {
    const rs = byYear[y];
    const spm = rs.map(r => (+r.seconds > 0 ? +r.strokes / (+r.seconds / 60) : NaN));
    const dps = rs.map(r => +r.dist_per_stroke_m);
    out[y] = { n_lengths: rs.length, spm: +median(spm).toFixed(1), dps: +median(dps).toFixed(2) };
  }
  return out;
}

const EXACT = new Set(["workout_start", "stroke_style", "lap_index", "lap_count", "strokes"]);
const TOL = { pool_length_m: 0.011, seconds: 0.11, dist_per_stroke_m: 0.0011, swolf: 0.11 };
function rowsEqual(py, js, cols) {
  for (const h of cols) {
    const pv = py[h] ?? "", jv = js[h] ?? "";
    if (EXACT.has(h)) { if (String(pv) !== String(jv)) return false; }
    else if (String(pv) === "" || String(jv) === "") { if (String(pv) !== String(jv)) return false; }
    else if (Math.abs(+pv - +jv) > (TOL[h] ?? 1e-9)) return false;
  }
  return true;
}

(async () => {
  console.log(`Streaming ${xmlPath}`);
  const t0 = Date.now();
  const { lapRows } = await streamParse(xmlPath);
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  const peak = (process.memoryUsage().rss / 1048576).toFixed(0);

  const py = parseCSV(readFileSync(csvPath, "utf8"));
  const cols = Object.keys(py[0] || {});
  const jsSwims = new Set(lapRows.map(r => r.workout_start)).size;
  const pySwims = new Set(py.map(r => r.workout_start)).size;

  console.log(`\nParsed in ${secs}s, peak RSS ${peak} MB`);
  console.log(`JS parser : ${lapRows.length} lengths across ${jsSwims} swims`);
  console.log(`Python CSV: ${py.length} lengths across ${pySwims} swims`);

  let pass = true;
  const ok = (name, cond) => { console.log((cond ? "  PASS  " : "  FAIL  ") + name); if (!cond) pass = false; };

  ok(`length count matches (${py.length})`, lapRows.length === py.length);
  ok(`swim count matches (${pySwims})`, jsSwims === pySwims);

  const jsByKey = new Map();
  lapRows.forEach(r => jsByKey.set(`${r.workout_start}#${r.lap_index}`, r));
  let mismatch = null, missing = 0;
  for (const pr of py) {
    const k = `${pr.workout_start}#${pr.lap_index}`;
    const js = jsByKey.get(k);
    if (!js) { missing++; if (!mismatch) mismatch = `missing JS row for ${k}`; continue; }
    if (!rowsEqual(pr, js, cols)) {
      mismatch = `row ${k}\n   py: ${cols.map(h => h + "=" + pr[h]).join("|")}\n   js: ${cols.map(h => h + "=" + (js[h] ?? "")).join("|")}`;
      break;
    }
  }
  ok(`every Python row reproduced (missing: ${missing})`, missing === 0 && !mismatch);
  if (mismatch) console.log("    first diff: " + mismatch);

  console.log("\nPer-year medians (XML parser) — compare to docs/FINDINGS.md:");
  const jm = yearMedians(lapRows), pm = yearMedians(py);
  for (const y of Object.keys(jm)) {
    const j = jm[y], p = pm[y] || {};
    console.log(`  ${y}: n=${j.n_lengths}  spm=${j.spm} (csv ${p.spm})  dps=${j.dps} (csv ${p.dps})`);
  }

  console.log(pass ? "\n✅ Validation passed." : "\n❌ Validation FAILED.");
  process.exit(pass ? 0 : 1);
})();
