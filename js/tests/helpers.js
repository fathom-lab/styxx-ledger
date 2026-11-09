"use strict";
/* helpers.js: shared by the node:test files (not itself a test file). */
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Ledger } = require("../lib/ledger");
const { RESERVED_FIELDS } = require("../lib/chain");
const { verifyBytesSync } = require("../lib/verify");

const JS_ROOT = path.join(__dirname, "..");
const REPO = path.join(JS_ROOT, "..");
const VECTORS = path.join(REPO, "vectors");
const PY_FIXTURES = path.join(REPO, "python", "tests", "fixtures");
const JS_FIXTURES = path.join(__dirname, "fixtures");
const BIN = path.join(JS_ROOT, "bin", "styxx-ledger.cjs");

function tmpdir(t) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "styxx-ledger-test-"));
  if (t && t.after) t.after(() => fs.rmSync(d, { recursive: true, force: true }));
  return d;
}

/* Re-write a ledger with the javascript Ledger from its header and each entry's kind, fields and timestamp. A
   writer that agrees with the one that wrote `bytes` produces the same bytes. -> Buffer */
function rewriteWithJs(bytes, dir) {
  const r = verifyBytesSync(bytes);
  if (!r.ok) throw new Error("the source ledger does not re-derive");
  const file = path.join(dir, "rewrite-" + process.pid + "-" + Date.now() + "-" + Math.random().toString(16).slice(2) + ".jsonl");
  const led = Ledger.init(file, r.header);
  for (const { entry } of r.entries) {
    const fields = {};
    for (const k of Object.keys(entry)) if (!RESERVED_FIELDS.includes(k)) fields[k] = entry[k];
    led.append(entry.kind, fields, { timestamp: entry.timestamp });
  }
  return fs.readFileSync(file);
}

module.exports = { JS_ROOT, REPO, VECTORS, PY_FIXTURES, JS_FIXTURES, BIN, tmpdir, rewriteWithJs };
