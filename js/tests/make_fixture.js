#!/usr/bin/env node
"use strict";
/* make_fixture.js: write tests/fixtures/js_written.jsonl (30 lines: header + 29 entries) with the javascript
   Ledger, for the python suite's cross test, and js_written.json beside it (python's sidecar shape: anchor_texts,
   entries, file, head, last_seq, sha256, written_by).

     node tests/make_fixture.js            write when absent; refuse when the bytes on disk differ
     node tests/make_fixture.js --check    rebuild into a temp dir and compare only (exit 1 on a difference)
     node tests/make_fixture.js --force    overwrite (a receipt is history: say so in BUILD_LOG_3a.md)

   Every timestamp is given, so the bytes are a pure function of this file and the package. They cross the
   America/New_York DST end (2026-11-01 06:00Z), the 2026-12-31/2027-01-01 boundary, and hold one late anchor. */
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { Ledger } = require("../lib/ledger");
const { verifyBytesSync } = require("../lib/verify");

const FIX = path.join(__dirname, "fixtures");
const OUT = path.join(FIX, "js_written.jsonl");
const OUT_ANCHORS = path.join(FIX, "js_written.json");

const HEADER = {
  schema: "styxx.ledger/log/v1",
  created: "2026-10-31T20:00:00Z",
  anchor_tz: "America/New_York",
  agent: "kitbot-js",
  certifies: "one line per event kitbot-js was handed, chained; the writer's clock is a statement, not evidence of order",
  kinds: ["anchor", "lock_recovered", "note", "started"]
};
const WRITER = { language: "javascript", name: "styxx-ledger", version: "1.0.0-alpha.1" };

function build(file) {
  const led = Ledger.init(file, HEADER);
  const anchors = [];
  const note = (ts, fields) => led.append("note", fields, { timestamp: ts });
  const anchor = (date, ts) => { const r = led.anchor(date, { timestamp: ts }); anchors.push(r.text); return r; };
  led.append("started", { writer: WRITER, run: "fixture" }, { timestamp: "2026-10-31T20:00:01Z" });          // 1
  note("2026-10-31T20:05:00Z", { n: 1, note: "first note from javascript" });                                // 2
  note("2026-10-31T21:00:00Z", { n: 2, note: "café ☕ — 🙂 ünïcödé" });                                       // 3
  note("2026-10-31T22:00:00Z", { n: 3, note: "line1\nline2\t\"quoted\" back\\slash \u0001 \u001f \u007f  " }); // 4
  note("2026-10-31T23:00:00Z", { n: 4, edges: { max: 9007199254740992, min: -9007199254740992, zero: 0 } });    // 5
  note("2026-11-01T01:00:00Z", { n: 5, empty_obj: {}, empty_arr: [], nested: { b: [1, { a: null, c: true }], a: false } }); // 6
  note("2026-11-01T03:59:59Z", { n: 6, note: "23:59:59 EDT, still 2026-10-31" });                           // 7
  note("2026-11-01T04:00:00Z", { n: 7, note: "00:00:00 EDT, 2026-11-01" });                                 // 8
  anchor("2026-10-31", "2026-11-01T04:05:00Z");                                                             // 9 (00:05 edt: on time by section 5)
  note("2026-11-01T05:59:59Z", { n: 8, note: "01:59:59 EDT" });                                             // 10
  note("2026-11-01T06:00:00Z", { n: 9, note: "01:00:00 EST, the hour repeats" });                           // 11
  note("2026-11-01T06:30:00Z", { n: 10, note: "01:30:00 EST" });                                            // 12
  led.append("started", { writer: WRITER, run: "fixture, second process" }, { timestamp: "2026-11-01T12:00:00Z" }); // 13
  note("2026-11-02T04:59:59Z", { n: 11, note: "23:59:59 EST, still 2026-11-01" });                          // 14
  note("2026-11-02T05:00:00Z", { n: 12, note: "00:00:00 EST, 2026-11-02" });                                // 15
  anchor("2026-11-01", "2026-11-02T05:00:10Z");                                                             // 16
  note("2026-11-02T18:00:00Z", { n: 13, keys: { "": "empty key", "A": 1, "_x": 2, "a": 3, "~": 4 } });       // 17
  note("2026-11-03T15:00:00Z", { n: 14, note: "the anchor for 2026-11-02 comes late" });                    // 18
  anchor("2026-11-02", "2026-11-05T14:00:00Z");                                                             // 19 (late)
  note("2026-12-31T12:00:00Z", { n: 15, note: "last day of 2026" });                                        // 20
  note("2026-12-31T23:59:59Z", { n: 16, note: "18:59:59 EST, utc already sees 2026 end" });                 // 21
  note("2027-01-01T00:00:00Z", { n: 17, note: "utc new year, still 2026-12-31 in new york" });              // 22
  note("2027-01-01T04:59:59Z", { n: 18, note: "23:59:59 EST 2026-12-31" });                                 // 23
  note("2027-01-01T05:00:00Z", { n: 19, note: "00:00:00 EST 2027-01-01" });                                 // 24
  anchor("2026-12-31", "2027-01-01T05:00:30Z");                                                             // 25
  note("2027-01-01T12:00:00Z", { n: 20, list: ["a", 1, null, true, [], {}] });                              // 26
  note("2027-01-01T23:00:00Z", { n: 21, note: "the last note of 2027-01-01" });                             // 27
  anchor("2027-01-01", "2027-01-02T05:00:00Z");                                                             // 28
  note("2027-01-02T06:00:00Z", { n: 22, note: "after the last anchor: not yet pinned" });                   // 29
  return anchors;
}

function main() {
  const args = process.argv.slice(2);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "styxx-ledger-fixture-"));
  try {
    const file = path.join(tmp, "js_written.jsonl");
    const anchors = build(file);
    const bytes = fs.readFileSync(file);
    const r = verifyBytesSync(bytes);
    if (!r.ok) throw new Error("the built fixture does not re-derive");
    const meta = {
      anchor_texts: anchors, entries: r.entries.length, file: "js_written.jsonl", head: r.head,
      last_seq: r.entries[r.entries.length - 1].entry.seq,
      sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
      written_by: "styxx-ledger (javascript) tests/make_fixture.js"
    };
    const anchorBytes = Buffer.from(JSON.stringify(meta, null, 1) + "\n", "utf8");
    const lines = bytes.toString("utf8").split("\n").filter(Boolean).length;
    if (lines !== 30) throw new Error("expected 30 lines, built " + lines);
    const same = fs.existsSync(OUT) && fs.readFileSync(OUT).equals(bytes)
      && fs.existsSync(OUT_ANCHORS) && fs.readFileSync(OUT_ANCHORS).equals(anchorBytes);
    if (args.includes("--check")) {
      console.log(same ? "fixture rebuilds byte for byte (" + lines + " lines)" : "fixture differs from a rebuild");
      return same ? 0 : 1;
    }
    if (same) { console.log("fixture unchanged (" + lines + " lines)"); return 0; }
    if (fs.existsSync(OUT) && !args.includes("--force")) {
      console.log("refusing to overwrite " + OUT + " with other bytes (pass --force and log it)");
      return 1;
    }
    fs.mkdirSync(FIX, { recursive: true });
    fs.writeFileSync(OUT, bytes);
    fs.writeFileSync(OUT_ANCHORS, anchorBytes);
    if (!fs.readFileSync(OUT).equals(bytes)) throw new Error("write did not land");
    console.log("wrote " + OUT + " (" + lines + " lines, " + bytes.length + " bytes) and " + anchors.length + " anchor texts");
    return 0;
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

if (require.main === module) process.exitCode = main();
module.exports = { build, HEADER, OUT, OUT_ANCHORS };
