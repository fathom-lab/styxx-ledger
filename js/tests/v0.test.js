"use strict";
/* protocol v0 read mode (lib/v0.js): the exhibit's 10 v0 vectors through the runner, schema detection, v0's day and
   anchor rules, and the cli reading a v0 file by its header. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const V0 = require("../lib/v0.js");
const V = require("../lib/verify.js");
const { VECTORS, JS_ROOT, BIN, tmpdir } = require("./helpers");

const DOC = JSON.parse(fs.readFileSync(path.join(VECTORS, "v0", "vectors.json"), "utf8"));
const BASE = fs.readFileSync(path.join(VECTORS, "v0", DOC.base));
const BASE_V1 = fs.readFileSync(path.join(VECTORS, "base_v1.jsonl"));
const sha = b => crypto.createHash("sha256").update(b).digest("hex");

test("vectors/v0 are the exhibit's bytes", () => {
  assert.equal(sha(BASE), DOC.base_sha256);
  assert.equal(sha(BASE), "8029fce0bed73a52067d2e7e3552555d45c81d837187a93b6dd20d48ad8861f1");
  assert.equal(sha(fs.readFileSync(path.join(VECTORS, "v0", "vectors.json"))), "be43667f1662e822fd31d5941e6166fdd7ce145de72b6dfea9b32bbb4ae69d4b");
  assert.equal(DOC.cases.length, 10);
});

test("run_vectors.mjs --only v0: 10 of 10 v0 vectors answered as the file says", () => {
  const cp = spawnSync(process.execPath, [path.join(VECTORS, "run_vectors.mjs"), "--verify", path.join(JS_ROOT, "lib", "verify.js"), "--only", "v0"],
    { encoding: "utf8", timeout: 120000 });
  const m = /(\d+) of (\d+) v0 vectors answered as the file says/.exec(cp.stdout);
  assert.ok(m, cp.stdout + cp.stderr);
  console.log("# " + m[0] + " (js/lib/v0.js, node " + process.versions.node + ", " + process.platform + ")");
  assert.equal(m[1], "10"); assert.equal(m[2], "10"); assert.equal(cp.status, 0, cp.stdout);
});

test("detectProtocol", () => {
  assert.equal(V0.detectProtocol(BASE), "v0");
  assert.equal(V0.detectProtocol(BASE_V1), "v1");
  assert.equal(V0.detectProtocol(Buffer.concat([Buffer.from("\n\n"), BASE])), "v0");
  assert.equal(V0.detectProtocol(Buffer.alloc(0)), null);
  assert.equal(V0.detectProtocol(Buffer.from("not json\n")), null);
  assert.equal(V0.detectProtocol(Buffer.from('{"schema":"other"}\n')), null);
});

test("verifyAuto dispatches; the v1 verifier still refuses v0", () => {
  const r = V0.verifyAuto(BASE);
  assert.equal(r.protocol, "v0"); assert.equal(r.ok, true); assert.equal(r.head, DOC.base_head); assert.equal(r.entries.length, DOC.base_lines);
  const r1v = V0.verifyAuto(BASE_V1);
  assert.equal(r1v.protocol, "v1"); assert.equal(r1v.ok, true);
  const r1 = V.verifyBytesSync(BASE);
  assert.equal(r1.ok, false); assert.ok(r1.problems.some(p => /reads v1 only/.test(p.problem || "")));
  assert.equal(V0.verifyAuto(BASE, {}, "v1").ok, false);
  const r0 = V0.verifyBytesV0(BASE_V1);
  assert.equal(r0.ok, false); assert.ok(r0.problems.some(p => p.code === "no_header"));
  assert.equal(V0.verifyBytesV0(Buffer.alloc(0)).ok, true, "an empty file is not a problem in v0");
});

test("v0's header digest, no kinds check", () => {
  const hdr = JSON.parse(BASE.toString("utf8").split("\n")[0]);
  assert.ok(!("kinds" in hdr) && !("agent" in hdr));
  assert.equal(V0.headerDigestV0(hdr), sha(Buffer.from("darkflobi.gate/log/v0\n" + V.jcs(hdr), "utf8")));
  assert.equal(JSON.parse(BASE.toString("utf8").split("\n")[1]).prev, V0.headerDigestV0(hdr));
});

test("v0 local day: the verify.js reading", () => {
  const ny = "America/New_York";
  const cases = [
    ["2026-10-25T03:59:59Z", "2026-10-24"], ["2026-10-25T04:00:00Z", "2026-10-25"], ["2026-11-02T04:59:59Z", "2026-11-01"],
    ["2026-10-25T03:59:59.999999Z", "2026-10-24"], ["2026-10-25T00:30:00+01:00", "2026-10-24"], ["2026-10-25T12:00:00", "2026-10-25"],
    ["  2026-10-25T12:00:00Z\n", "2026-10-25"], ["2026-02-30T12:00:00Z", "2026-03-02"], ["2026-01-01T24:00:00Z", "2026-01-01"]
  ];
  for (const [ts, day] of cases) assert.equal(V0.localDayV0(ts, ny), day, ts);
  for (const ts of ["2026-13-01T00:00:00Z", "2026-01-01T24:00:01Z", "2026-01-01T23:59:60Z", "2026-01-01T00:00:00+24:00", "2026-01-01", 20261025, null, "2026-01-01T00:00:00z", "２026-01-01T00:00:00Z"]) {
    assert.throws(() => V0.localDayV0(ts, ny), e => e.code === "timestamp", String(ts));
  }
});

test("v0 checks the day only when a timestamp is carried", () => {
  const lines = BASE.toString("utf8").replace(/\n+$/, "").split("\n");
  const o = JSON.parse(lines[5]);
  delete o.timestamp; delete o.entry_id;
  o.entry_id = V.entryId(o);
  lines[5] = V.dump(o);
  const r = V0.verifyBytesV0(Buffer.from(lines.join("\n") + "\n"));
  assert.deepEqual([...new Set(r.problems.map(p => p.seq))], [o.seq + 1]);
});

test("v0 anchor text form", () => {
  const head = "a".repeat(64);
  const t = V0.anchorTextV0("2026-10-25", head, 116);
  assert.equal(t, "gate anchor 2026-10-25 head " + head + " seq 116");
  assert.deepEqual(V0.parseAnchorTextV0(t), { agent: "gate", date: "2026-10-25", head, seq: 116 });
  assert.ok(V0.parseAnchorTextV0(t + "\n"));
  assert.equal(V0.parseAnchorTextV0(t + "\n\n"), null);
  assert.equal(V0.parseAnchorTextV0("kitbot anchor 2026-10-25 head " + head + " seq 116"), null);
  assert.equal(V0.parseAnchorTextV0("gate anchor 2026-10-25 head " + head + " seq 99999999999999999"), null);
  assert.throws(() => V0.anchorTextV0("2026-10-25", "A".repeat(64), 1), e => e.code === "anchor_form");
});

test("the cli reads a v0 file by its header", t => {
  const d = tmpdir(t);
  const p = path.join(d, "v0.jsonl"), anchors = path.join(d, "anchors.txt");
  fs.writeFileSync(p, BASE);
  fs.writeFileSync(anchors, DOC.cases[0].anchors.join("\n") + "\n");
  let cp = spawnSync(process.execPath, [BIN, "verify", p, "--anchors-file", anchors], { encoding: "utf8" });
  assert.equal(cp.status, 1, cp.stdout);
  assert.match(cp.stdout, /protocol v0/); assert.match(cp.stdout, /re-derives: 120 entries/); assert.match(cp.stdout, /1 of 2 anchors hold/);
  fs.writeFileSync(anchors, DOC.cases[0].anchors[0] + "\n");
  cp = spawnSync(process.execPath, [BIN, "verify", p, "--anchors-file", anchors, "--json"], { encoding: "utf8" });
  const out = JSON.parse(cp.stdout);
  assert.equal(cp.status, 0); assert.equal(out.protocol, "v0"); assert.equal(out.head, DOC.base_head);
  cp = spawnSync(process.execPath, [BIN, "verify", p, "--protocol", "v1"], { encoding: "utf8" });
  assert.equal(cp.status, 1); assert.match(cp.stdout, /reads v1 only/);
});
