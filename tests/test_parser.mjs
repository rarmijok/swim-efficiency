/* test_parser.mjs — smoke test for tracker/parser_wip.js
 *
 *   python3 tools/make_sample_data.py   # writes tests/sample_export.xml + expected
 *   node tests/test_parser.mjs
 *
 * Checks:
 *  1) parser reproduces the expected swim/length counts and medians
 *  2) result is IDENTICAL whether fed in one big chunk or 7-byte chunks
 *     (i.e. chunk-boundary handling is correct)
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeHealthParser, buildLapRows } = require(join(__dirname, "..", "tracker", "parser_wip.js"));

const xml = readFileSync(join(__dirname, "sample_export.xml"), "utf8");
const expected = JSON.parse(readFileSync(join(__dirname, "sample_expected.json"), "utf8"));

function median(a) {
  const b = a.filter(Number.isFinite).slice().sort((x, y) => x - y);
  if (!b.length) return NaN;
  const m = b.length >> 1;
  return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2;
}

function run(chunkSize) {
  const p = makeHealthParser();
  for (let i = 0; i < xml.length; i += chunkSize) p.feed(xml.slice(i, i + chunkSize));
  const { strokes, workouts } = p.finish();
  return buildLapRows(strokes, workouts);
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
check(`summary rows = swims`, big.summaryRows.length === expected.n_swims);

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

console.log(failures ? `\n${failures} FAILED` : "\nAll checks passed.");
process.exit(failures ? 1 : 0);
