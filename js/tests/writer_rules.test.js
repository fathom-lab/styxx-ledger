"use strict";
/* writer rules settled in the lab's improvement sweep of 2026-11-09, javascript side (python/tests/test_writer_rules.py
   is the python side; the shared vectors pin both):

     rank 42  composeAnchor refuses a day that has not closed in anchor_tz (day_open), a day the ledger already
              anchors (already_anchored) and a day with no line (nothing_to_anchor); the python writer composed for
              an open or an anchored day until then, and now refuses the same, with the same codes
     rank 43  a certifies made only of whitespace is refused (header_form), whitespace being the 30 code points
              spelled out in PROTOCOL_v1 section 1, not String.prototype.trim's 25
     rank 68  strings are never normalised: an nfc and an nfd spelling give two lines with two entry_ids
     rank 67  Ledger.init with anchorTz "" refuses the zone; it used to write a UTC log

   every non-ascii character here is written with String.fromCodePoint, so this file's bytes say which is meant. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { Ledger } = require("../lib/ledger");
const V = require("../lib/verify");
const chain = require("../lib/chain");
const { tmpdir } = require("./helpers");

const ch = cp => String.fromCodePoint(cp);
const BLANK30 = [0x9, 0xa, 0xb, 0xc, 0xd, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680];
for (let cp = 0x2000; cp <= 0x200a; cp++) BLANK30.push(cp);
BLANK30.push(0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff);
const HDR = { agent: "rulebot", certifies: "one line per event the rules test was handed", anchorTz: "America/New_York", kinds: ["note"], created: "2026-10-31T12:00:00Z" };
const code = fn => { try { fn(); return null; } catch (e) { return e.code || "uncoded:" + e.message; } };

// ------------------------------------------------------------------------------------------ rank 42: compose
test("composeAnchor refuses an open day at its last second, composes it at local midnight, and writes nothing", t => {
  const f = path.join(tmpdir(t), "l.jsonl");
  const led = Ledger.init(f, HDR);
  led.start({}, { timestamp: "2026-10-31T12:00:01Z" });
  led.append("note", { n: 1 }, { timestamp: "2026-10-31T20:00:00Z" });
  const before = fs.readFileSync(f);
  let e = null;
  try { led.composeAnchor("2026-10-31", { timestamp: "2026-10-31T23:00:00Z" }); } catch (x) { e = x; }
  assert.equal(e.code, "day_open");
  assert.equal(e.message, "2026-10-31 has not closed in America/New_York (it is 2026-10-31 there)");
  assert.equal(code(() => led.composeAnchor("2026-10-31", { timestamp: "2026-11-01T03:59:59Z" })), "day_open");   // 23:59:59 edt
  assert.equal(code(() => led.composeAnchor("2026-11-02", { timestamp: "2026-11-01T12:00:00Z" })), "day_open");   // a later day
  const c = led.composeAnchor("2026-10-31", { timestamp: "2026-11-01T04:00:00Z" });                               // 00:00:00 edt
  assert.equal(c.seq, 2);
  assert.equal(c.text, "rulebot anchor 2026-10-31 head " + c.head + " seq 2");
  assert.deepEqual(fs.readFileSync(f), before);
});

test("composeAnchor refuses an anchored day, a day with no line and a date out of form; day_open is named before already_anchored", t => {
  const f = path.join(tmpdir(t), "l.jsonl");
  const led = Ledger.init(f, HDR);
  led.start({}, { timestamp: "2026-10-31T12:00:01Z" });
  led.anchor("2026-10-31", { timestamp: "2026-11-01T04:00:05Z" });
  assert.equal(code(() => led.composeAnchor("2026-10-31", { timestamp: "2026-11-02T12:00:00Z" })), "already_anchored");
  assert.equal(code(() => led.composeAnchor("2026-10-30", { timestamp: "2026-11-02T12:00:00Z" })), "nothing_to_anchor");
  assert.equal(code(() => led.composeAnchor("2026-10-3", { timestamp: "2026-11-02T12:00:00Z" })), "anchor_form");
  const r = V.verifyBytesSync(fs.readFileSync(f));
  assert.equal(code(() => V.composeAnchor(r.header, r.entries, "2026-10-31", "2026-10-31T23:00:00Z")), "day_open");
  led.append("note", { n: 2 }, { timestamp: "2026-11-01T15:00:00Z" });
  const r2 = V.verifyBytesSync(fs.readFileSync(f));
  const a = V.composeAnchor(r2.header, r2.entries, "2026-11-01", "2026-11-02T05:00:00Z");
  const b = led.composeAnchor("2026-11-01", { timestamp: "2026-11-02T05:00:00Z" });
  assert.deepEqual({ agent: a.agent, date: a.date, seq: a.seq }, { agent: "rulebot", date: "2026-11-01", seq: 3 });
  assert.deepEqual({ text: b.text, head: b.head, seq: b.seq, date: b.date }, { text: a.text, head: a.head, seq: a.seq, date: a.date });
});

// ------------------------------------------------------------------------------- rank 43: the blank set
test("the blank set is 30 code points: trim's 25 and the 5 python's isspace adds", () => {
  assert.deepEqual(Array.from(chain.CERTIFIES_BLANK).map(c => c.codePointAt(0)).sort((x, y) => x - y), BLANK30.slice().sort((x, y) => x - y));
  const set = new Set(BLANK30);
  let trimmed = 0, mismatch = 0;
  for (let cp = 0; cp < 0x110000; cp++) {
    if (cp >= 0xd800 && cp <= 0xdfff) continue;
    if (ch(cp).trim() === "") { trimmed++; if (!set.has(cp)) mismatch++; }
    if (chain.CERTIFIES_BLANK_RX.test(ch(cp)) !== set.has(cp)) mismatch++;
  }
  assert.equal(trimmed, 25);
  assert.equal(mismatch, 0);
  for (const cp of [0x1c, 0x1d, 0x1e, 0x1f, 0x85]) assert.notEqual(ch(cp).trim(), "", "trim keeps u+" + cp.toString(16));
});

test("a certifies of blanks only is refused; a blank inside a sentence is not; length is in code points", t => {
  const d = tmpdir(t);
  const header = cert => Object.assign({}, HDR, { certifies: cert });
  for (const cp of BLANK30) {
    const f = path.join(d, "b" + cp.toString(16) + ".jsonl");
    assert.equal(code(() => Ledger.init(f, header(ch(cp).repeat(3)))), "header_form", "u+" + cp.toString(16));
    assert.equal(fs.existsSync(f), false);
    if (cp !== 0xa) {
      const g = path.join(d, "ok" + cp.toString(16) + ".jsonl");
      Ledger.init(g, header("one" + ch(cp) + "sentence"));
      assert.equal(JSON.parse(fs.readFileSync(g, "utf8")).certifies, "one" + ch(cp) + "sentence");
    }
  }
  for (const cert of [ch(0x200b), ch(0x180e), ch(0x2060), "x".repeat(500), ch(0x1f642).repeat(500)]) {
    assert.equal(code(() => chain.checkHeader(chain.makeHeader("2026-10-31T12:00:00Z", "UTC", "a", cert, ["anchor", "started"]))), null);
  }
  assert.equal(code(() => chain.makeHeader("2026-10-31T12:00:00Z", "UTC", "a", "x".repeat(501), ["anchor", "started"])), "header_form");
});

test("a log whose certifies is blank by python's isspace (u+001f) re-derives, and the writer refuses to append", t => {
  const f = path.join(tmpdir(t), "old.jsonl");
  const hdr = { schema: V.LOG_SCHEMA, created: "2026-10-31T12:00:00Z", anchor_tz: "UTC", agent: "rulebot", certifies: ch(0x1f), kinds: ["anchor", "note", "started"] };
  fs.writeFileSync(f, V.dump(hdr) + "\n");
  assert.equal(V.verifyBytesSync(fs.readFileSync(f)).ok, true);
  assert.equal(code(() => new Ledger(f).append("note", { n: 1 }, { timestamp: "2026-11-01T00:00:00Z" })), "header_form");
  assert.equal(fs.readFileSync(f, "utf8").split("\n").length, 2);
});

// ------------------------------------------------------------------------- rank 68: never normalised
test("strings are never normalised: nfc and nfd give two lines and two entry_ids", t => {
  const d = tmpdir(t);
  const a = Ledger.init(path.join(d, "nfc.jsonl"), HDR), b = Ledger.init(path.join(d, "nfd.jsonl"), HDR);
  const ea = a.append("note", { s: ch(0xe9) }, { timestamp: "2026-11-01T00:00:00Z" });
  const eb = b.append("note", { s: "e" + ch(0x301) }, { timestamp: "2026-11-01T00:00:00Z" });
  assert.notEqual(ea.entry_id, eb.entry_id);
  const la = fs.readFileSync(a.path).toString("latin1").split("\n")[1], lb = fs.readFileSync(b.path).toString("latin1").split("\n")[1];
  assert.ok(la.includes('"s":"\xc3\xa9"'), la);
  assert.ok(lb.includes('"s":"e\xcc\x81"'), lb);
});

// ------------------------------------------------------------------------------- rank 67: an empty zone
test("Ledger.init with anchorTz '' refuses the zone instead of writing a UTC log; undefined still means UTC", t => {
  const d = tmpdir(t);
  assert.equal(code(() => Ledger.init(path.join(d, "e.jsonl"), Object.assign({}, HDR, { anchorTz: "" }))), "anchor_tz");
  assert.equal(fs.existsSync(path.join(d, "e.jsonl")), false);
  const led = Ledger.init(path.join(d, "u.jsonl"), { agent: "a", certifies: "s." });
  assert.equal(led.read().header.anchor_tz, "UTC");
});
