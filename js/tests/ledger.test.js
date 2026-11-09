"use strict";
/* unit: the writer (section 3b): init, append, start, anchor, refusals, the lock and its recovery, fsync'd
   appends from several processes at once. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { Ledger, LedgerLocked, LedgerTamper } = require("../lib/ledger");
const V = require("../lib/verify");
const { tmpdir } = require("./helpers");

const HDR = { agent: "unit", certifies: "a unit-test ledger.", anchorTz: "America/New_York", kinds: ["note"], created: "2026-10-31T12:00:00Z" };
const code = fn => { try { fn(); return null; } catch (e) { return e.code || "uncoded:" + e.message; } };

function deadPid() {
  const r = spawnSync(process.execPath, ["-e", "process.stdout.write(String(process.pid))"], { encoding: "utf8" });
  return Number(r.stdout);
}
function ageFile(p, seconds) {
  const t = new Date(Date.now() - seconds * 1000);
  fs.utimesSync(p, t, t);
}

test("init writes one canonical header line; a second init refuses", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  const led = Ledger.init(f, HDR);
  const raw = fs.readFileSync(f, "utf8");
  assert.equal(raw.split("\n").length, 2);
  assert.ok(raw.endsWith("\n"));
  const r = V.verifyBytesSync(raw);
  assert.equal(r.ok, true);
  assert.deepEqual(r.header.kinds, ["anchor", "note", "started"]);
  assert.deepEqual(led.head(), { head: V.headerDigestSync(r.header), seq: 0 });
  assert.equal(code(() => Ledger.init(f, HDR)), "exists");
  assert.equal(fs.existsSync(f + ".lock"), false, "the lock is released");
});

test("append and start chain from the tail; every line re-derives", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  const led = Ledger.init(f, HDR);
  const s = led.start({ framework: "node:test" }, { timestamp: "2026-10-31T12:00:01Z" });
  assert.equal(s.seq, 1);
  assert.equal(s.writer.name, "styxx-ledger");
  assert.equal(s.writer.language, "javascript");
  const e = led.append("note", { note: "x" }, { timestamp: "2026-11-01T05:30:00Z" });
  assert.equal(e.seq, 2);
  assert.equal(e.prev, s.entry_id);
  assert.equal(e.day, "2026-11-01");
  const now = led.append("note", { note: "clock" });
  assert.match(now.timestamp, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  const r = led.read();
  assert.equal(r.ok, true);
  assert.equal(r.head, now.entry_id);
  assert.deepEqual(led.head(), { head: now.entry_id, seq: 3 });
});

test("refusals leave the file byte for byte as it was", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  const led = Ledger.init(f, HDR);
  led.append("note", { n: 1 }, { timestamp: "2026-10-31T13:00:00Z" });
  const before = fs.readFileSync(f);
  assert.equal(code(() => led.append("send", {})), "kind_not_declared");
  assert.equal(code(() => led.append("note", { seq: 5 })), "reserved_field");
  assert.equal(code(() => led.append("note", { x: 0.5 })), "float");
  assert.equal(code(() => led.append("note", { "ü": 1 })), "non_ascii_key");
  assert.equal(code(() => led.append("note", {}, { timestamp: "2026-11-01T01:00:00-04:00" })), "timestamp");
  assert.equal(code(() => led.append("started", {})), "started_writer");
  assert.ok(fs.readFileSync(f).equals(before));
  assert.equal(fs.existsSync(f + ".lock"), false);
});

test("a file that does not re-derive, or lacks its final LF, is refused (LedgerTamper)", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  const led = Ledger.init(f, HDR);
  led.append("note", { note: "a" }, { timestamp: "2026-10-31T13:00:00Z" });
  led.append("note", { note: "b" }, { timestamp: "2026-10-31T14:00:00Z" });
  const good = fs.readFileSync(f, "utf8");
  fs.writeFileSync(f, good.replace('"note":"a"', '"note":"A"'));
  const tampered = fs.readFileSync(f);
  assert.throws(() => led.append("note", {}), e => e instanceof LedgerTamper && e.problems.some(p => (p.codes || []).includes("entry_id")));
  assert.ok(fs.readFileSync(f).equals(tampered), "nothing appended");
  fs.writeFileSync(f, good.slice(0, -1));
  assert.throws(() => led.append("note", {}), e => e instanceof LedgerTamper && e.problems.some(p => p.code === "tail"));
  fs.writeFileSync(f, good);
  assert.equal(led.append("note", {}, { timestamp: "2026-10-31T15:00:00Z" }).seq, 3);
});

test("a lock held by a live writer is waited on, then LedgerLocked", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  Ledger.init(f, HDR);
  fs.writeFileSync(f + ".lock", String(process.pid));
  ageFile(f + ".lock", 120);
  const led = new Ledger(f, { lockTimeoutMs: 300 });
  const t0 = Date.now();
  assert.throws(() => led.append("note", {}), e => e instanceof LedgerLocked && e.code === "locked");
  assert.ok(Date.now() - t0 >= 250);
  assert.equal(fs.readFileSync(f + ".lock", "utf8"), String(process.pid), "a live writer's lock is never broken");
});

test("a fresh lock whose pid is dead is not broken before 30 s", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  Ledger.init(f, HDR);
  const pid = deadPid();
  fs.writeFileSync(f + ".lock", String(pid));
  assert.throws(() => new Ledger(f, { lockTimeoutMs: 200 }).append("note", {}), LedgerLocked);
});

test("a stale lock (older than 30 s, pid dead) is broken; lock_recovered is written only when declared", t => {
  const d = tmpdir(t);
  const f1 = path.join(d, "declared.jsonl"), f2 = path.join(d, "undeclared.jsonl");
  Ledger.init(f1, Object.assign({}, HDR, { kinds: ["note", "lock_recovered"] }));
  Ledger.init(f2, HDR);
  const pid = deadPid();
  for (const f of [f1, f2]) { fs.writeFileSync(f + ".lock", String(pid)); ageFile(f + ".lock", 45); }
  const e1 = new Ledger(f1, { lockTimeoutMs: 2000 }).append("note", { n: 1 }, { timestamp: "2026-10-31T13:00:00Z" });
  const r1 = V.verifyBytesSync(fs.readFileSync(f1));
  assert.equal(r1.ok, true);
  assert.deepEqual(r1.entries.map(x => x.entry.kind), ["lock_recovered", "note"]);
  const rec = r1.entries[0].entry;
  assert.equal(rec.stale_pid, pid);
  assert.deepEqual(Object.keys(rec).filter(k => !["schema", "seq", "prev", "kind", "timestamp", "day", "entry_id"].includes(k)).sort(), ["stale_age_s", "stale_pid"], "the python writer's fields");
  assert.ok(rec.stale_age_s >= 30);
  assert.equal(e1.seq, 2);
  new Ledger(f2, { lockTimeoutMs: 2000 }).append("note", { n: 1 }, { timestamp: "2026-10-31T13:00:00Z" });
  assert.deepEqual(V.verifyBytesSync(fs.readFileSync(f2)).entries.map(x => x.entry.kind), ["note"]);
  for (const f of [f1, f2]) { assert.equal(fs.existsSync(f + ".lock"), false); assert.equal(fs.existsSync(f + ".lock.break"), false); }
});

test("a stale lock naming no pid is broken after 30 s", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  Ledger.init(f, Object.assign({}, HDR, { kinds: ["note", "lock_recovered"] }));
  fs.writeFileSync(f + ".lock", "");
  ageFile(f + ".lock", 31);
  new Ledger(f, { lockTimeoutMs: 2000 }).append("note", {}, { timestamp: "2026-10-31T13:00:00Z" });
  const r = V.verifyBytesSync(fs.readFileSync(f));
  assert.equal(r.entries[0].entry.kind, "lock_recovered");
  assert.equal(r.entries[0].entry.stale_pid, null);
});

test("anchor: composes the closing head of a closed day, writes its entry, refuses an open day and a repeat", t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  const led = Ledger.init(f, HDR);
  led.append("note", { n: 1 }, { timestamp: "2026-10-31T13:00:00Z" });
  const last = led.append("note", { n: 2 }, { timestamp: "2026-11-01T03:59:59Z" });   // 23:59:59 EDT
  led.append("note", { n: 3 }, { timestamp: "2026-11-01T04:00:00Z" });               // the next day
  assert.equal(code(() => led.anchor("2026-11-01", { timestamp: "2026-11-01T12:00:00Z" })), "day_open");
  const dry = led.composeAnchor("2026-10-31", { timestamp: "2026-11-01T04:05:00Z" });
  assert.equal(dry.text, "unit anchor 2026-10-31 head " + last.entry_id + " seq 2");
  const before = fs.readFileSync(f);
  const { text, entry } = led.anchor("2026-10-31", { timestamp: "2026-11-01T04:05:00Z" });   // 00:05 EDT: on time
  assert.equal(text, dry.text);
  assert.ok(fs.readFileSync(f).length > before.length);
  assert.equal(entry.kind, "anchor");
  assert.equal(entry.late, false);
  assert.equal(entry.anchor_text_sha256, require("node:crypto").createHash("sha256").update(text).digest("hex"));
  const r = led.read();
  assert.equal(V.checkAnchor(r.entries, V.parseAnchorText(text), [], r.header).ok, true);
  assert.equal(code(() => led.anchor("2026-10-31", { timestamp: "2026-11-01T05:00:00Z" })), "already_anchored");
  assert.equal(code(() => led.append("note", {}, { timestamp: "2026-11-01T03:00:00Z" })), "anchored_day", "an entry of an anchored day");
  const late = led.anchor("2026-11-01", { timestamp: "2026-11-04T12:00:00Z" });
  assert.equal(late.entry.late, true);
  assert.equal(code(() => led.anchor("2026-11-03", { timestamp: "2026-11-05T12:00:00Z" })), "nothing_to_anchor", "no entry has that day");
  const empty = Ledger.init(path.join(d, "e.jsonl"), HDR);
  assert.equal(code(() => empty.anchor("2026-10-30", { timestamp: "2026-11-01T12:00:00Z" })), "nothing_to_anchor");
});

test("four processes appending at once: every line lands once, in one chain", async t => {
  const d = tmpdir(t), f = path.join(d, "l.jsonl");
  Ledger.init(f, Object.assign({}, HDR, { kinds: ["note", "lock_recovered"] }));
  const worker = path.join(__dirname, "append_worker.js");
  const N = 4, M = 12;
  const codes = await Promise.all(Array.from({ length: N }, (_, i) => new Promise((resolve, reject) => {
    const c = spawn(process.execPath, [worker, f, String(M), "w" + i], { stdio: ["ignore", "ignore", "pipe"] });
    let err = "";
    c.stderr.on("data", b => { err += b; });
    c.on("error", reject);
    c.on("exit", code => resolve({ code, err }));
  })));
  for (const c of codes) assert.equal(c.code, 0, c.err);
  const r = V.verifyBytesSync(fs.readFileSync(f));
  assert.equal(r.ok, true, JSON.stringify(r.problems.slice(0, 3)));
  const notes = r.entries.filter(x => x.entry.kind === "note");
  assert.equal(notes.length, N * M);
  assert.deepEqual(r.entries.map(x => x.entry.seq), r.entries.map((_, i) => i + 1));
  for (let i = 0; i < N; i++) {
    assert.deepEqual(notes.filter(x => x.entry.worker === "w" + i).map(x => x.entry.i), Array.from({ length: M }, (_, k) => k));
  }
  assert.equal(fs.existsSync(f + ".lock"), false);
});
