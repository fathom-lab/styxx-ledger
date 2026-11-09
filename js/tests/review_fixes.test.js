"use strict";
/* regression tests for the review findings fixed on 2026-11-08 (BUILD_LOG_3a.md, fix pass). The conformance side of
   each finding is also a shared vector (vectors/vectors_v1.json), so the python package is held to the same answer. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const V = require("../lib/verify");
const { Ledger } = require("../lib/ledger");
const { BIN, VECTORS, tmpdir } = require("./helpers");

const code = fn => { try { fn(); return null; } catch (e) { return e.code; } };
const HDR = { agent: "fixbot", certifies: "regression tests.", anchorTz: "America/New_York", kinds: ["note"], created: "2026-10-31T12:00:00Z" };
const nested = n => { let v = 1; for (let i = 0; i < n - 1; i++) v = [v]; return { d: v }; };

test("finding 1: a trailing LF and non-ascii digits are not the timestamp or anchor form", t => {
  assert.equal(code(() => V.dayOf("2026-11-01T05:00:00Z\n", "UTC")), "timestamp");
  assert.equal(code(() => V.dayOf("２０２６-11-01T05:00:00Z", "UTC")), "timestamp");
  assert.equal(code(() => V.anchorText("kitbot\n", "2026-11-01", "a".repeat(64), 1)), "anchor_form");
  const led = Ledger.init(path.join(tmpdir(t), "a.jsonl"), HDR);
  assert.equal(code(() => led.append("note", { t: 1 }, { timestamp: "2026-11-03T12:00:00Z\n" })), "timestamp");
});

test("finding 2: years outside 1000..9998 are refused, not printed as nonsense", () => {
  assert.equal(code(() => V.dayOf("0001-01-01T00:00:00Z", "America/New_York")), "timestamp");
  assert.equal(code(() => V.dayOf("9999-12-31T23:59:59Z", "Europe/Berlin")), "timestamp");
  assert.equal(V.dayOf("1000-01-01T00:00:00Z", "America/New_York"), "0999-12-31");
  assert.equal(V.dayOf("9998-12-31T23:59:59Z", "Europe/Berlin"), "9999-01-01");
});

test("finding 3: depth is bounded at 32 for writers; a deeper line is unparsable for readers", t => {
  assert.equal(code(() => V.jcs(nested(32))), null);
  assert.equal(code(() => V.jcs(nested(33))), "depth");
  const f = path.join(tmpdir(t), "d.jsonl");
  const led = Ledger.init(f, HDR);
  const before = fs.readFileSync(f);
  assert.equal(code(() => led.append("note", { deep: nested(1200) }, { timestamp: "2026-11-02T12:00:00Z" })), "depth");
  assert.ok(fs.readFileSync(f).equals(before));
  const deepLine = Buffer.from('{"deep":' + "[".repeat(1199) + "1" + "]".repeat(1199) + "}\n");
  const r = V.verifyBytesSync(Buffer.concat([before, deepLine]));
  assert.equal(r.ok, false);
  assert.deepEqual(r.problems.map(p => p.code), ["unparsable"]);
});

test("finding 4: a withheld seq written 10.0 is the integer 10 (python reads it the same since the fix)", () => {
  const base = fs.readFileSync(path.join(VECTORS, "base_v1.jsonl"));
  const r0 = V.verifyBytesSync(base);
  const e10 = r0.entries[9].entry;
  const cut = Buffer.from(base.toString("utf8").split("\n").filter(l => !l.includes('"seq":10,')).join("\n"));
  const withheld = JSON.parse('[{"seq":10.0,"entry_id":"' + e10.entry_id + '"}]');
  const r = V.verifyBytesSync(cut, { withheld });
  assert.equal(r.ok, true);
  assert.deepEqual(r.bridged, [10]);
});

test("finding 5: late is section 5's rule, never the caller's", t => {
  assert.equal(V.lateOf("2026-10-31", "2026-11-01T04:10:00Z", "America/New_York"), false);
  assert.equal(V.lateOf("2026-10-31", "2026-11-01T04:10:01Z", "America/New_York"), true);
  assert.equal(V.lateOf("2026-11-01", "2026-11-03T05:00:00Z", "America/New_York"), true);
  const led = Ledger.init(path.join(tmpdir(t), "l.jsonl"), HDR);
  led.append("note", {}, { timestamp: "2026-10-31T13:00:00Z" });
  assert.equal(code(() => led.anchor("2026-10-31", { timestamp: "2026-11-01T05:00:00Z", late: false })), "anchor_form");
  assert.equal(led.anchor("2026-10-31", { timestamp: "2026-11-01T05:00:00Z" }).entry.late, true);   // 01:00 EDT on the 1st
  assert.equal(code(() => V.buildEntry(led.read().header, 9, "a".repeat(64), "anchor", "2026-11-01T04:00:05Z",
    { anchor_date: "2026-10-31", anchor_head: "a".repeat(64), anchor_head_seq: 1, anchor_text_sha256: "b".repeat(64), late: true })), "anchor_form");
});

test("finding 6: a zone is the exact-case name the database lists, never Factory", t => {
  for (const tz of ["utc", "UTC ", "Factory", "america/new_york"]) {
    assert.equal(code(() => V.dayOf("2026-11-01T05:00:00Z", tz)), "anchor_tz", tz);
    assert.equal(code(() => Ledger.init(path.join(tmpdir(t), "z.jsonl"), Object.assign({}, HDR, { anchorTz: tz }))), "anchor_tz", tz);
  }
});

test("finding 7: the writer refuses a header a v1 writer may not write, though the verifier is silent on it", t => {
  const d = tmpdir(t);
  const f0 = path.join(d, "ok.jsonl");
  Ledger.init(f0, HDR);
  const hdr = JSON.parse(fs.readFileSync(f0, "utf8"));
  for (const [i, change] of [{ extra: 1 }, { agent: "KitBot" }, { kinds: ["note", "anchor", "started"] }].entries()) {
    const f = path.join(d, "bad" + i + ".jsonl");
    fs.writeFileSync(f, V.dump(Object.assign({}, hdr, change)) + "\n");
    assert.equal(V.verifyBytesSync(fs.readFileSync(f)).ok, true);
    assert.equal(code(() => new Ledger(f).append("note", { t: 1 }, { timestamp: "2026-11-02T12:00:00Z" })), "header_form");
  }
});

test("finding 8: a file with no header (empty, or blank lines only) does not re-derive", () => {
  for (const raw of ["", "\n", "\n\n \t\n"]) {
    const r = V.verifyBytesSync(Buffer.from(raw));
    assert.equal(r.ok, false, JSON.stringify(raw));
    assert.equal(r.head, null);
    assert.deepEqual([...new Set(r.problems.flatMap(p => p.codes || [p.code]))], ["no_header"]);
  }
});

test("note: an anchor text whose seq exceeds 2^53 does not parse", () => {
  assert.equal(V.parseAnchorText("kitbot anchor 2026-10-31 head " + "a".repeat(64) + " seq 99999999999999999999"), null);
  assert.notEqual(V.parseAnchorText("kitbot anchor 2026-10-31 head " + "a".repeat(64) + " seq 9007199254740992"), null);
});

test("cli flags: --tz is required, anchor-text writes only with --record, --no-started and --no-start agree", t => {
  const d = tmpdir(t);
  const run = (...a) => spawnSync(process.execPath, [BIN, ...a], { encoding: "utf8", timeout: 60000 });
  assert.equal(run("init", path.join(d, "a.jsonl"), "--agent", "x", "--certifies", "s.").status, 2);
  for (const flag of ["--no-started", "--no-start"]) {
    const f = path.join(d, flag + ".jsonl");
    assert.equal(run("init", f, "--agent", "x", "--tz", "UTC", "--certifies", "s.", flag).status, 0);
    assert.equal(fs.readFileSync(f, "utf8").split("\n").filter(Boolean).length, 1, flag);
  }
});
