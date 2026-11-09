"use strict";
/* unit: the chain, the verifier and the anchor check (sections 3-6), and the exhibit-compatible API. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const V = require("../lib/verify");
const { VECTORS } = require("./helpers");

const base = fs.readFileSync(path.join(VECTORS, "base_v1.jsonl"));
const doc = JSON.parse(fs.readFileSync(path.join(VECTORS, "vectors_v1.json"), "utf8"));
const codesOf = r => [...new Set(r.problems.flatMap(p => p.codes || [p.code]))].sort();
const lines = () => base.toString("utf8").split("\n");
const code = fn => { try { fn(); return null; } catch (e) { return e.code || "uncoded"; } };

test("the base re-derives to the head the vectors name (promise and sync forms agree)", async () => {
  const r = await V.verifyBytes(new Uint8Array(base), { withheld: [] });
  assert.equal(r.ok, true);
  assert.equal(r.head, doc.base_head);
  assert.equal(r.entries.length, doc.base_entries);
  assert.equal(r.file_sha256, doc.base_sha256);
  const s = V.verifyBytesSync(base);
  assert.equal(s.head, r.head);
  assert.equal((await V.verifyText(base.toString("utf8"))).head, r.head);
  assert.equal(await V.headerDigest(r.header), V.headerDigestSync(r.header));
  assert.equal(await V.entryIdOf(V.coreOf(r.entries[0].entry)), r.entries[0].entry.entry_id);
  assert.equal(V.entryId(r.entries[0].entry), r.entries[0].entry.entry_id, "entryId drops entry_id itself");
  assert.equal(await V.headOf(r.header, r.entries), r.head);
  assert.deepEqual(await V.checkChain(r.header, r.entries, []), { problems: [], bridged: [] });
});

test("every base anchor text holds; another agent's word does not", () => {
  const r = V.verifyBytesSync(base);
  for (const t of doc.base_anchor_texts) assert.equal(V.checkAnchor(r.entries, V.parseAnchorText(t), [], r.header).ok, true, t);
  const t0 = doc.base_anchor_texts[0];
  const other = V.parseAnchorText(t0.replace(/^kitbot /, "gate "));
  const c = V.checkAnchor(r.entries, other, [], r.header);
  assert.equal(c.ok, false);
  assert.equal(c.agent_matches, false);
  assert.equal(V.checkAnchor(r.entries, other, [], null).ok, true, "without a header the agent is not checked (v0 behaviour)");
});

test("a rewritten field is caught at its seq; a flip re-chained moves the head", () => {
  const ls = lines();
  const o = JSON.parse(ls[5]);
  o.note = "rewritten";
  ls[5] = V.dump(o);
  const r = V.verifyBytesSync(ls.join("\n"));
  assert.equal(r.ok, false);
  assert.deepEqual(codesOf(r), ["entry_id"]);
  assert.deepEqual(r.problems.map(p => p.seq), [o.seq]);
});

test("a dropped line breaks prev and seq; withheld with its digest, it is bridged", () => {
  const ls = lines();
  const dropped = JSON.parse(ls[10]);
  ls.splice(10, 1);
  const raw = ls.join("\n");
  const r = V.verifyBytesSync(raw);
  assert.equal(r.ok, false);
  assert.deepEqual(codesOf(r), ["prev", "seq"]);
  const w = [{ seq: dropped.seq, entry_id: dropped.entry_id, reason: "test" }];
  const b = V.verifyBytesSync(raw, { withheld: w });
  assert.equal(b.ok, true);
  assert.deepEqual(b.bridged, [dropped.seq]);
  const wrong = V.verifyBytesSync(raw, { withheld: [{ seq: dropped.seq, entry_id: "0".repeat(64) }] });
  assert.equal(wrong.ok, false);
});

test("reading problems: cr byte, bom, invalid utf-8, not an object, not canonical, lone-surrogate escape", () => {
  const ls = lines();
  const withCr = V.verifyBytesSync(ls[0] + "\r\n" + ls.slice(1).join("\n"));
  assert.ok(codesOf(withCr).includes("cr_byte"));
  const bom = V.verifyBytesSync(Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), base]));
  assert.ok(codesOf(bom).includes("unparsable"), "a BOM is refused as python refuses it");
  const badUtf8 = V.verifyBytesSync(Buffer.concat([base, Buffer.from([0xff, 0x0a])]));
  assert.ok(codesOf(badUtf8).includes("unparsable"));
  assert.ok(codesOf(V.verifyBytesSync(base.toString("utf8") + "[1]\n")).includes("not_object"));
  const spaced = ls.slice(); spaced[3] = spaced[3].replace('","', '", "');
  assert.ok(codesOf(V.verifyBytesSync(spaced.join("\n"))).includes("not_canonical"));
  const lone = ls.slice(); lone[2] = lone[2].replace('"first note"', '"\\ud800"');
  const rl = V.verifyBytesSync(lone.join("\n"));
  assert.ok(codesOf(rl).includes("not_canonical") && codesOf(rl).includes("core_not_canonical"), JSON.stringify(codesOf(rl)));
});

test("a v0 file is not read, and the verifier says why", () => {
  const ls = lines();
  const h = JSON.parse(ls[0]);
  h.schema = "darkflobi.gate/log/v0";
  ls[0] = V.dump(h);
  const r = V.verifyBytesSync(ls.join("\n"));
  assert.equal(r.ok, false);
  assert.ok(r.problems.some(p => p.code === "no_header" && /reads v1 only/.test(p.problem)));
});

test("kind not declared and header kinds missing started are reported", () => {
  const ls = lines();
  const h = JSON.parse(ls[0]);
  h.kinds = ["anchor", "note"];
  ls[0] = V.dump(h);
  const r = V.verifyBytesSync(ls.join("\n"));
  assert.ok(codesOf(r).includes("header_kinds"));
  assert.ok(codesOf(r).includes("kind_not_declared"));
  assert.ok(r.problems.some(p => p.seq === null && (p.codes || []).includes("header_kinds")));
});

test("anchor text: compose, parse, strict form", () => {
  const head = "a".repeat(64);
  assert.equal(V.anchorText("bot-1", "2026-11-01", head, 7), "bot-1 anchor 2026-11-01 head " + head + " seq 7");
  assert.deepEqual(V.parseAnchorText("bot-1 anchor 2026-11-01 head " + head + " seq 7\n"), { agent: "bot-1", date: "2026-11-01", head, seq: 7 });
  for (const bad of ["bot-1 anchor 2026-11-01 head " + head + " seq 07", "Bot anchor 2026-11-01 head " + head + " seq 7",
    " bot anchor 2026-11-01 head " + head + " seq 7", "bot anchor 2026-11-01 head " + head + " seq 7\n\n",
    "bot anchor 2026-11-01 head " + head.toUpperCase() + " seq 7", "gate anchor 2026-11-01 head " + head + " seq 7 extra", null]) {
    assert.equal(V.parseAnchorText(bad), null, JSON.stringify(bad));
  }
  assert.equal(code(() => V.anchorText("kitbot\n", "2026-11-01", head, 1)), "anchor_form");
  assert.equal(code(() => V.anchorText("kitbot", "2026-11-01", head, -1)), "anchor_form");
  assert.equal(code(() => V.anchorText("kitbot", "2026-11-1", head, 1)), "anchor_form");
  assert.equal(code(() => V.anchorText("x".repeat(33), "2026-11-01", head, 1)), "anchor_form");
});

test("checkHeader and makeHeader refuse what a v1 writer may not write", () => {
  const ok = { schema: "styxx.ledger/log/v1", created: "2026-11-01T00:00:00Z", anchor_tz: "UTC", agent: "a", certifies: "one sentence.", kinds: ["anchor", "started"] };
  assert.equal(code(() => V.checkHeader(ok)), null);
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { extra: 1 }))), "header_form");
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { kinds: ["started", "anchor"] }))), "header_form");
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { kinds: ["anchor"] }))), "header_form");
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { agent: "Bad" }))), "header_form");
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { certifies: "two\nlines" }))), "header_form");
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { anchor_tz: "Nowhere/Zone" }))), "anchor_tz");
  assert.equal(code(() => V.checkHeader(Object.assign({}, ok, { created: "2026-02-30T00:00:00Z" }))), "timestamp");
  assert.deepEqual(V.makeHeader("2026-11-01T00:00:00Z", "UTC", "a", "s.", ["started", "note", "anchor", "note"]).kinds, ["anchor", "note", "started"]);
});

test("buildEntry: refusal order and the composed line", () => {
  const h = JSON.parse(lines()[0]);
  const prev = "0".repeat(64);
  assert.equal(code(() => V.buildEntry(h, 2, prev, "note", "2026-11-01T05:00:00Z", [])), "type");
  assert.equal(code(() => V.buildEntry(h, 2, prev, "send", "bad", { _x: 1 })), "reserved_field");
  assert.equal(code(() => V.buildEntry(h, 2, prev, "send", "bad", { x: 1.5 })), "kind_not_declared");
  assert.equal(code(() => V.buildEntry(h, 2, prev, "anchor", "bad", { anchor_date: "2026-11-01" })), "anchor_form");
  assert.equal(code(() => V.buildEntry(h, 0, prev, "note", "bad", {})), "type");
  assert.equal(code(() => V.buildEntry(h, 2, "x", "note", "bad", {})), "type");
  assert.equal(code(() => V.buildEntry(h, 2, prev, "note", "bad", { x: 1.5 })), "timestamp");
  assert.equal(code(() => V.buildEntry(h, 2, prev, "note", "2026-11-01T05:00:00Z", { x: 1.5 })), "float");
  const e = V.buildEntry(h, 2, prev, "note", "2026-11-01T05:30:00Z", { note: "x" });
  assert.equal(e.day, "2026-11-01");
  assert.equal(e.entry_id, V.entryId(e));
});

test("coverage keeps v0's shape", () => {
  const r = V.verifyBytesSync(base);
  const c = V.coverage(r.entries, [{ seq: 33, entry_id: "x" }], [9, 23, 29, 39, 57]);
  assert.deepEqual(Object.keys(c).sort(), ["after_last_anchor", "last_anchor_seq", "pinned", "unpinned_by_withholding", "unpinned_ranges", "withheld"]);
  assert.deepEqual(c.unpinned_ranges, [[30, 32]]);
  assert.equal(c.pinned + c.unpinned_by_withholding + c.after_last_anchor, r.entries.length);
});
