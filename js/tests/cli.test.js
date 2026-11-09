"use strict";
/* the command line: init | append | verify | anchor-text | head, and its exit codes (0 ok, 1 refused or not
   re-deriving, 2 usage). */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { BIN, tmpdir } = require("./helpers");

const run = (...args) => {
  const cp = spawnSync(process.execPath, [BIN, ...args], { encoding: "utf8", timeout: 60000 });
  return { code: cp.status, out: cp.stdout, err: cp.stderr };
};

test("init, append, anchor-text, verify, head", t => {
  const d = tmpdir(t), f = path.join(d, "a.jsonl");
  let r = run("init", f, "--agent", "clibot", "--certifies", "one line per event clibot was handed.", "--tz", "America/New_York", "--created", "2026-10-31T12:00:00Z");
  assert.equal(r.code, 0, r.err);
  assert.match(r.out, /agent clibot, anchor_tz America\/New_York, kinds anchor,note,started; head [0-9a-f]{64} seq 1/);
  r = run("append", f, "--kind", "note", "--fields", '{"note":"hi","n":1}', "--timestamp", "2026-10-31T13:00:00Z");
  assert.equal(r.code, 0, r.err);
  const line = JSON.parse(r.out);
  assert.equal(line.seq, 2);
  r = run("append", f, "--kind", "note", "--field", "note=two", "--timestamp", "2026-11-01T05:30:00Z");
  assert.equal(r.code, 0, r.err);
  r = run("anchor-text", f, "--date", "2026-10-31", "--timestamp", "2026-11-01T06:00:00Z", "--dry-run");
  assert.equal(r.code, 0, r.err);
  const text = r.out.trim();
  assert.equal(text, "clibot anchor 2026-10-31 head " + line.entry_id + " seq 2");
  assert.equal(fs.readFileSync(f, "utf8").split("\n").filter(Boolean).length, 4, "anchor-text without --record writes nothing");
  assert.equal(run("anchor-text", f, "--date", "2026-10-31", "--timestamp", "2026-11-01T06:00:00Z", "--late").code, 2, "--late is gone");
  r = run("anchor-text", f, "--date", "2026-10-31", "--timestamp", "2026-11-01T06:00:00Z", "--record");
  assert.equal(r.code, 0, r.err);
  assert.equal(r.out.trim(), text);
  assert.match(r.err, /anchor entry seq 4 written/);
  r = run("verify", f, "--anchor", text);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /^re-derives: 4 entries, head [0-9a-f]{64} seq 4/);
  assert.match(r.out, /1 of 1 anchors hold/);
  r = run("verify", f, "--json");
  assert.equal(JSON.parse(r.out).ok, true);
  r = run("head", f);
  assert.equal(r.code, 0);
  assert.match(r.out, /^[0-9a-f]{64} seq 4\n$/);
});

test("refusals exit 1 and append nothing; usage errors exit 2", t => {
  const d = tmpdir(t), f = path.join(d, "a.jsonl");
  assert.equal(run("init", f, "--agent", "clibot", "--tz", "UTC", "--certifies", "s.").code, 0);
  const before = fs.readFileSync(f);
  let r = run("append", f, "--kind", "send");
  assert.equal(r.code, 1);
  assert.match(r.err, /refused \(kind_not_declared\)/);
  r = run("append", f, "--kind", "note", "--fields", '{"x":1.5}');
  assert.equal(r.code, 1);
  assert.match(r.err, /refused \(float\)/);
  assert.ok(fs.readFileSync(f).equals(before));
  assert.equal(run("init", f, "--agent", "clibot", "--tz", "UTC", "--certifies", "s.").code, 1, "exists");
  assert.equal(run("append", f).code, 2);
  assert.equal(run("frobnicate", f).code, 2);
  assert.equal(run("verify", path.join(d, "missing.jsonl")).code, 2);
  assert.equal(run("init", path.join(d, "b.jsonl"), "--agent", "Bad Name", "--tz", "UTC", "--certifies", "s.").code, 1);
  fs.writeFileSync(f, before.toString("utf8").replace("clibot", "clibox"));
  r = run("verify", f);
  assert.equal(r.code, 1);
  assert.match(r.out, /does not re-derive/);
  assert.equal(run("append", f, "--kind", "note").code, 1);
  assert.equal(run("--version").code, 0);
  assert.equal(run("init", path.join(d, "c.jsonl"), "--agent", "clibot", "--certifies", "s.").code, 2, "--tz is required");
});

test("verify bridges a withheld line given --withheld", t => {
  const d = tmpdir(t), f = path.join(d, "a.jsonl");
  assert.equal(run("init", f, "--agent", "clibot", "--tz", "UTC", "--certifies", "s.", "--created", "2026-10-31T12:00:00Z").code, 0);
  const lines = [];
  for (let i = 0; i < 3; i++) lines.push(JSON.parse(run("append", f, "--kind", "note", "--field", "n=" + i, "--timestamp", "2026-10-31T13:0" + i + ":00Z").out));
  const raw = fs.readFileSync(f, "utf8").split("\n");
  const dropped = lines[1];
  const pub = path.join(d, "pub.jsonl"), wf = path.join(d, "withheld.json");
  fs.writeFileSync(pub, raw.filter(l => !l.includes(dropped.entry_id + '","kind"')).join("\n"));
  fs.writeFileSync(wf, JSON.stringify([{ seq: dropped.seq, entry_id: dropped.entry_id, reason: "test" }]));
  assert.equal(run("verify", pub).code, 1);
  const r = run("verify", pub, "--withheld", wf);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, new RegExp("bridged over withheld seqs " + dropped.seq));
});

test("the package entry exports the verifier, the writer and the version", () => {
  const S = require("../lib/index.js");
  const pkg = require("../package.json");
  assert.equal(S.version, pkg.version);
  for (const k of ["verifyBytes", "verifyText", "checkAnchor", "coverage", "dump", "jcs", "dayOf", "headerDigest", "entryId",
    "entryIdOf", "anchorText", "parseAnchorText", "buildEntry", "sha256Hex", "coreOf", "Ledger", "LedgerTamper", "LedgerLocked"]) {
    assert.ok(S[k] !== undefined, k);
  }
  assert.deepEqual(Object.keys(pkg.dependencies || {}), [], "no runtime dependencies");
});

test("the optional opentimestamps helper says so when no client is installed", t => {
  const { stamp } = require("../lib/ots.js");
  const d = tmpdir(t), f = path.join(d, "post.txt");
  fs.writeFileSync(f, "kitbot anchor 2026-10-31 head " + "a".repeat(64) + " seq 1");
  const r = stamp(f, { bin: "styxx-ledger-no-such-ots-client" });
  assert.equal(r.ok, false);
  assert.match(r.reason, /no `styxx-ledger-no-such-ots-client` client on PATH/);
  assert.equal(stamp(path.join(d, "missing.txt")).ok, false);
});
