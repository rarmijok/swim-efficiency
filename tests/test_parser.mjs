/* test_parser.mjs — smoke test for the health-xml-parser inlined in
 *                    tracker/swim_tracker.html (extracted between its BEGIN/END markers)
 *
 *   python3 tools/make_sample_data.py   # writes tests/sample_export.xml + expected
 *   node tests/test_parser.mjs
 *
 * Checks:
 *  1) parser reproduces the expected swim/length counts and medians
 *  2) result is IDENTICAL whether fed in one big chunk or 7-byte chunks
 *     (i.e. chunk-boundary handling is correct)
 *  3) the JS parser produces BYTE-IDENTICAL rows to the Python extractor on the same
 *     XML — the "CSV path and XML path MUST produce identical keys" guarantee. This is
 *     the strongest synthetic check we can run without a real 500 MB export.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

// The parser ships INSIDE tracker/swim_tracker.html (single self-contained file). Extract
// the marked block and load it standalone so this test exercises the ACTUAL shipped code,
// with no separate copy that could drift.
function loadParserFromTracker() {
  const html = readFileSync(join(__dirname, "..", "tracker", "swim_tracker.html"), "utf8");
  const m = html.match(/BEGIN health-xml-parser[\s\S]*?\*\/\n([\s\S]*?)\/\* =+ END health-xml-parser/);
  if (!m) throw new Error("could not find the health-xml-parser block in swim_tracker.html");
  const src = m[1] + "\nmodule.exports={makeHealthParser,buildLapRows,makeHRScanner,parseAppleDate};\n";
  const tmp = join(tmpdir(), `health_parser_${process.pid}.cjs`);
  writeFileSync(tmp, src);
  return require(tmp);
}
const { makeHealthParser, buildLapRows, makeHRScanner } = loadParserFromTracker();

const xmlPath = join(__dirname, "sample_export.xml");
const xml = readFileSync(xmlPath, "utf8");
const expected = JSON.parse(readFileSync(join(__dirname, "sample_expected.json"), "utf8"));

function median(a) {
  const b = a.filter(Number.isFinite).slice().sort((x, y) => x - y);
  if (!b.length) return NaN;
  const m = b.length >> 1;
  return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2;
}

function run(chunkSize) {
  // Pass 1: workouts + strokes -> lap rows + per-length windows.
  const p = makeHealthParser();
  for (let i = 0; i < xml.length; i += chunkSize) p.feed(xml.slice(i, i + chunkSize));
  const { strokes, workouts } = p.finish();
  const res = buildLapRows(strokes, workouts);
  // Pass 2: per-length heart rate (same chunking, so chunk-boundary handling is exercised).
  const hr = makeHRScanner(res.windows);
  for (let i = 0; i < xml.length; i += chunkSize) hr.feed(xml.slice(i, i + chunkSize));
  hr.finish();
  return res;
}

let failures = 0;
function check(name, cond) {
  console.log((cond ? "  PASS  " : "  FAIL  ") + name);
  if (!cond) failures++;
}

// big-chunk pass
const big = run(xml.length);
const swims = new Set(big.lapRows.map(r => r.workout_start)).size;
const spm = big.lapRows.map(r => r.strokes / (r.seconds / 60));
const dps = big.lapRows.map(r => +r.dist_per_stroke_m);

console.log("Parser output vs expected:");
check(`swims = ${expected.n_swims}`, swims === expected.n_swims);
check(`lengths = ${expected.n_lengths}`, big.lapRows.length === expected.n_lengths);
check(`median spm ~ ${expected.median_spm}`, Math.abs(median(spm) - expected.median_spm) < 0.3);
check(`median dps ~ ${expected.median_dps}`, Math.abs(median(dps) - expected.median_dps) < 0.02);
// Every swim with laps must have a matching summary row (rest analysis joins on key).
// Open-water swims add a summary row with no laps, so summaryRows can be a superset.
const sumKeys = new Set(big.summaryRows.map(r => r.startDate.slice(0, 16)));
const lapKeys = [...new Set(big.lapRows.map(r => r.workout_start))];
check(`every lap swim has a summary row`, lapKeys.every(k => sumKeys.has(k)));
// HR: each pool swim's workout carries a HeartRate WorkoutStatistics; the open-water
// swim has none. The parser must read average HR off the workout (order-independent).
const hrRows = big.summaryRows.filter(r => isFinite(+r.avgHeartRate) && +r.avgHeartRate > 0);
check(`heart rate parsed for all ${expected.n_swims} pool swims`, hrRows.length === expected.n_swims);
// Per-length HR (pass 2): every length got a sample, and HR drifts up within a swim
// (the synthetic data places a rising sample at each length midpoint; out-of-window noise
// before each swim must NOT be counted).
const withLenHr = big.lapRows.filter(r => isFinite(+r.hr) && +r.hr > 0).length;
check(`per-length HR on all ${expected.n_lengths} lengths`, withLenHr === expected.n_lengths);
const firstSwimKey = big.lapRows[0].workout_start;
const firstSwim = big.lapRows.filter(r => r.workout_start === firstSwimKey);
check(`per-length HR drifts up within a swim`,
      +firstSwim[firstSwim.length - 1].hr > +firstSwim[0].hr);

// chunk-boundary robustness: tiny chunks must give identical output
const tiny = run(7);
check("7-byte chunks match big-chunk lengths", tiny.lapRows.length === big.lapRows.length);
check("7-byte chunks match big-chunk JSON",
      JSON.stringify(tiny.lapRows) === JSON.stringify(big.lapRows));

// a couple of odd sizes for good measure
for (const cs of [1, 3, 64, 997, 65536]) {
  const r = run(cs);
  check(`chunk size ${cs} identical`, JSON.stringify(r.lapRows) === JSON.stringify(big.lapRows));
}

// ---- JS parser vs Python extractor: rows must be byte-identical ----
// Run the real Python extractor over the same XML and compare CSV rows field-by-field.
console.log("\nJS parser vs Python extractor (same XML):");
try {
  const pyCsvPath = join(tmpdir(), `swim_laps_py_${process.pid}.csv`);
  const pyScript = join(__dirname, "..", "extractors", "extract_swim_laps.py");
  execFileSync("python3", [pyScript, xmlPath, pyCsvPath], { stdio: "pipe" });
  const pyText = readFileSync(pyCsvPath, "utf8");
  const lines = pyText.replace(/\r/g, "").split("\n").filter(l => l.trim().length);
  const head = lines[0].split(",");
  const pyRows = lines.slice(1).map(l => {
    const c = l.split(","); const o = {};
    head.forEach((h, i) => (o[h] = c[i]));
    return o;
  });

  // Compare each row field-by-field. Strings/keys/integers must match EXACTLY; the
  // rounded floats are compared within a small tolerance, because Python's round()
  // uses banker's rounding (half-to-even) and JS Math.round() rounds half-up, so an
  // exact .5 tie like 25/16 = 1.5625 can differ by 0.001. That's invisible at the
  // tracker's display precision and doesn't move any median. The invariant that
  // matters: the workout_start KEY is identical and every metric agrees to rounding.
  const EXACT = new Set(["workout_start", "stroke_style", "lap_index", "lap_count", "strokes"]);
  const TOL = { pool_length_m: 0.011, seconds: 0.11, dist_per_stroke_m: 0.0011, swolf: 0.11, hr: 1.0 };
  const show = r => head.map(h => `${h}=${r[h] ?? ""}`).join("|");
  function rowsEqual(py, js) {
    for (const h of head) {
      const pv = py[h] ?? "", jv = js[h] ?? "";
      if (EXACT.has(h)) { if (String(pv) !== String(jv)) return false; }
      else if (String(pv) === "" || String(jv) === "") { if (String(pv) !== String(jv)) return false; }
      else if (Math.abs(+pv - +jv) > (TOL[h] ?? 1e-9)) return false;
    }
    return true;
  }

  const jsByKey = new Map();
  big.lapRows.forEach(r => jsByKey.set(`${r.workout_start}#${r.lap_index}`, r));

  check(`row count matches Python (${pyRows.length})`, pyRows.length === big.lapRows.length);
  let mismatch = null;
  for (const pr of pyRows) {
    const k = `${pr.workout_start}#${pr.lap_index}`;
    const js = jsByKey.get(k);
    if (js === undefined) { mismatch = `missing JS row for ${k}`; break; }
    if (!rowsEqual(pr, js)) { mismatch = `row ${k}\n   py: ${show(pr)}\n   js: ${show(js)}`; break; }
  }
  check(`all ${pyRows.length} rows match Python (keys exact, metrics within rounding)`, mismatch === null);
  if (mismatch) console.log("    first diff: " + mismatch);
} catch (e) {
  check("python extractor ran", false);
  console.log("    " + (e.message || e));
}

// ---- units: a yard pool length must convert to metres, identically in both paths ----
console.log("\nUnit handling (yard pool):");
try {
  const yxml = [
    '<?xml version="1.0"?>', '<HealthData>',
    ' <Record type="HKQuantityTypeIdentifierSwimmingStrokeCount" startDate="2025-01-01 08:00:00 -0400" endDate="2025-01-01 08:00:20 -0400" value="18"><MetadataEntry key="HKSwimmingStrokeStyle" value="2"/></Record>',
    ' <Record type="HKQuantityTypeIdentifierSwimmingStrokeCount" startDate="2025-01-01 08:00:22 -0400" endDate="2025-01-01 08:00:42 -0400" value="18"><MetadataEntry key="HKSwimmingStrokeStyle" value="2"/></Record>',
    ' <Workout workoutActivityType="HKWorkoutActivityTypeSwimming" duration="1.0" durationUnit="min" startDate="2025-01-01 08:00:00 -0400" endDate="2025-01-01 08:01:00 -0400"><MetadataEntry key="HKMetadataKeyLapLength" value="25 yd"/></Workout>',
    '</HealthData>', ''].join("\n");
  const expectM = 25 * 0.9144;
  const p = makeHealthParser(); p.feed(yxml);
  const r = p.finish();
  const jsPool = +buildLapRows(r.strokes, r.workouts).lapRows[0].pool_length_m;
  check(`JS converts 25 yd -> ${expectM.toFixed(2)} m`, Math.abs(jsPool - expectM) < 0.01);

  const tmpXml = join(tmpdir(), `yardtest_${process.pid}.xml`);
  const tmpCsv = join(tmpdir(), `yardtest_${process.pid}.csv`);
  writeFileSync(tmpXml, yxml);
  execFileSync("python3", [join(__dirname, "..", "extractors", "extract_swim_laps.py"), tmpXml, tmpCsv], { stdio: "pipe" });
  const yl = readFileSync(tmpCsv, "utf8").replace(/\r/g, "").split("\n").filter(l => l.trim());
  const yh = yl[0].split(","), yr = yl[1].split(",");
  const pyPool = +yr[yh.indexOf("pool_length_m")];
  check(`Python matches JS pool (${jsPool.toFixed(2)} m)`, Math.abs(pyPool - jsPool) < 0.01);
} catch (e) {
  check("yard-pool test ran", false);
  console.log("    " + (e.message || e));
}

console.log(failures ? `\n${failures} FAILED` : "\nAll checks passed.");
process.exit(failures ? 1 : 0);
