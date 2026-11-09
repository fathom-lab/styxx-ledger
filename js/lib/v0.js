"use strict";
/* v0.js: read mode for protocol v0 ledgers (darkflobi.gate/log/v0), the protocol darkflobi's send ledger runs under.

   The rules are the exhibit's verify.js (the reference v0 implementation; its 10 vectors are vectors/v0/):

     header         schema "darkflobi.gate/log/v0"; schema, created, anchor_tz, certifies (no agent, no kinds)
     entries        schema "darkflobi.gate/entry/v0"
     header digest  sha256("darkflobi.gate/log/v0" LF JCS(header))
     anchor text    "gate anchor <YYYY-MM-DD> head <64 hex> seq <n>" (the fixed word "gate")
     kinds          not declared in the header: no kinds check
     day            the timestamp's day in the header's anchor_tz (America/New_York when absent), read as verify.js
                    reads it (Date.parse: fractions, +hh:mm offsets, a naive time as UTC); checked only when the
                    entry carries a timestamp
     no_header      reported only when the file holds entries

   Everything else is v1's (JCS, entry_id, prev, seq, bridging on withheld digests, coverage); problem records carry
   the v1 codes. detectProtocol(raw) names a file's protocol from its first line's schema; verifyAuto reads either.
   The python package's styxx_ledger/v0.py is the same module. */
const jcsm = require("./jcs");
const chain = require("./chain");
const verify = require("./verify");

const V0_LOG_SCHEMA = chain.V0_LOG_SCHEMA;
const V0_ENTRY_SCHEMA = "darkflobi.gate/entry/v0";
const V0_HEADER_DOMAIN = V0_LOG_SCHEMA + "\n";
const V0_ANCHOR_TZ = "America/New_York";
const V0_ANCHOR_RX = /^gate anchor ([0-9]{4}-[0-9]{2}-[0-9]{2}) head ([0-9a-f]{64}) seq ([0-9]+)\n?$/;
const { own, dump, jcs, LedgerValueError } = jcsm;
const { isInt } = chain;

const enc = new TextEncoder();
const dec = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

function headerDigestV0(header) { return chain.sha256Hex(V0_HEADER_DOMAIN + jcs(header)); }

const fmts = new Map();
/* verify.js localDay, with the zone as an argument: throws LedgerValueError("timestamp") when unreadable. */
function localDayV0(ts, tz) {
  let s = String(ts).trim();
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.test(s)) throw new LedgerValueError("timestamp", "timestamp unreadable");
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(s)) s += "Z";
  const ms = Date.parse(s);
  if (isNaN(ms)) throw new LedgerValueError("timestamp", "timestamp unreadable");
  const zone = tz || V0_ANCHOR_TZ;
  let f = fmts.get(zone);
  if (!f) {
    try { f = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }); }
    catch (e) { throw new LedgerValueError("anchor_tz", "anchor_tz is not a zone this node knows: " + JSON.stringify(zone)); }
    fmts.set(zone, f);
  }
  const m = {};
  for (const p of f.formatToParts(new Date(ms))) m[p.type] = p.value;
  return m.year + "-" + m.month + "-" + m.day;
}

function splitLines(u8) {
  const out = [];
  let start = 0, hasCR = false;
  for (let i = 0; i <= u8.length; i++) {
    if (i === u8.length || u8[i] === 0x0a) { out.push({ line: out.length + 1, bytes: u8.subarray(start, i) }); start = i + 1; }
    else if (u8[i] === 0x0d) hasCR = true;
  }
  return { lines: out, hasCR };
}
function isBlank(b) {
  for (let i = 0; i < b.length; i++) { const c = b[i]; if (c !== 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d && c !== 0x0b && c !== 0x0c) return false; }
  return true;
}
function bytesEqual(a, b) { if (a.length !== b.length) return false; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false; return true; }

/* {header, entries: [{line, entry}], problems} under v0's reading rules. Never throws on content. */
function readBytesV0(raw) {
  const u8 = chain.toU8(raw);
  let header = null;
  const entries = [], problems = [];
  const sp = splitLines(u8);
  if (sp.hasCR) problems.push({ line: null, seq: null, code: "cr_byte", problem: "the log holds a CR byte; lines are LF" });
  for (const ln of sp.lines) {
    const n = ln.line;
    if (isBlank(ln.bytes)) continue;
    if (jcsm.depthExceeds(ln.bytes)) { problems.push({ line: n, seq: null, code: "unparsable", problem: "unparsable: containers nested deeper than 32" }); continue; }
    let obj;
    try { obj = JSON.parse(dec.decode(ln.bytes)); }
    catch (e) { problems.push({ line: n, seq: null, code: "unparsable", problem: "unparsable: " + (e && e.name ? e.name : "error") }); continue; }
    if (obj === null || typeof obj !== "object" || Array.isArray(obj)) { problems.push({ line: n, seq: null, code: "not_object", problem: "not an object" }); continue; }
    let canonical = false;
    try { canonical = !jcsm.hasLoneSurrogate(obj) && bytesEqual(enc.encode(dump(obj)), ln.bytes); } catch (e2) { canonical = false; }
    if (!canonical) problems.push({ line: n, seq: null, code: "not_canonical", problem: "the line's bytes are not the canonical dump of its object" });
    if (header === null && entries.length === 0 && own(obj, "schema") === V0_LOG_SCHEMA) { header = obj; continue; }
    entries.push({ line: n, entry: obj });
  }
  if (header === null && entries.length) problems.push({ line: 1, seq: null, code: "no_header", problem: "no header on line 1" });
  return { header, entries, problems };
}

const nul = v => (v === undefined ? null : v);

/* {problems, bridged}: verify.js checkChain, with the v1 codes. */
function checkChainV0(header, entries, withheld) {
  const bad = [], bridged = [];
  if (header === null || header === undefined) {
    if (entries.length) bad.push({ line: 1, seq: null, codes: ["no_header"], problems: ["no header"] });
    return { problems: bad, bridged };
  }
  const wm = chain.withheldMap(withheld);
  const tz = typeof own(header, "anchor_tz") === "string" ? own(header, "anchor_tz") : V0_ANCHOR_TZ;
  let prev;
  try { prev = headerDigestV0(header); }
  catch (err) { prev = null; bad.push({ line: 1, seq: null, codes: ["not_canonical"], problems: ["header not canonicalisable: " + err.message] }); }
  let wantSeq = 1;
  for (const it of entries) {
    const e = it.entry, codes = [], texts = [];
    const add = (c, t) => { codes.push(c); texts.push(t); };
    const s = own(e, "seq");
    while (wm.has(wantSeq) && s !== wantSeq) { prev = wm.get(wantSeq); bridged.push(wantSeq); wantSeq++; }
    const core = chain.coreOf(e);
    let want = null;
    try { want = chain.entryId(core); } catch (err) { add("core_not_canonical", "core not canonicalisable: " + err.message); }
    if (own(core, "schema") !== V0_ENTRY_SCHEMA) add("schema", "schema is not " + V0_ENTRY_SCHEMA);
    if (want !== null && own(e, "entry_id") !== want) add("entry_id", "entry_id does not re-derive from the core");
    if (nul(own(e, "prev")) !== prev) add("prev", "prev does not name the line before");
    if (!(isInt(s) && s === wantSeq)) add("seq", "seq is " + JSON.stringify(nul(s)) + ", expected " + wantSeq);
    if (Object.prototype.hasOwnProperty.call(core, "timestamp")) {
      try { if (localDayV0(own(core, "timestamp"), tz) !== own(core, "day")) add("day", "day does not re-derive from timestamp"); }
      catch (err) { add("day", "timestamp unreadable"); }
    }
    if (codes.length) bad.push({ line: it.line, seq: nul(s), codes, problems: texts });
    const eid = own(e, "entry_id");
    prev = typeof eid === "string" ? eid : prev;
    wantSeq = (isInt(s) ? s : wantSeq) + 1;
  }
  return { problems: bad, bridged };
}

function headOfV0(header, entries) {
  if (entries.length) { const h = own(entries[entries.length - 1].entry, "entry_id"); return typeof h === "string" ? h : null; }
  if (header === null || header === undefined) return null;
  try { return headerDigestV0(header); } catch (e) { return null; }
}

/* {protocol: "v0", header, entries, problems, bridged, head, file_sha256, ok}, synchronously. */
function verifyBytesV0(raw, opts) {
  const u8 = chain.toU8(raw);
  const r = readBytesV0(u8);
  const c = checkChainV0(r.header, r.entries, opts && opts.withheld);
  const problems = r.problems.concat(c.problems);
  return { protocol: "v0", header: r.header, entries: r.entries, problems, bridged: c.bridged, head: headOfV0(r.header, r.entries), file_sha256: chain.sha256Hex(u8), ok: problems.length === 0 };
}

function anchorTextV0(date, head, seq) {
  if (typeof date !== "string" || !chain.DATE_RX.test(date) || typeof head !== "string" || !chain.HEX64_RX.test(head)
      || !isInt(seq) || seq < 0 || seq > jcsm.MAX_INT) throw new LedgerValueError("anchor_form", "anchor fields out of form");
  return "gate anchor " + date + " head " + head + " seq " + BigInt(seq).toString();
}
/* {agent: "gate", date, head, seq} for a text that IS the v0 form (one trailing LF tolerated), else null. */
function parseAnchorTextV0(text) {
  if (typeof text !== "string") return null;
  const m = V0_ANCHOR_RX.exec(text);
  if (!m || m[3].length > 16 || BigInt(m[3]) > BigInt(jcsm.MAX_INT)) return null;
  return { agent: "gate", date: m[1], head: m[2], seq: parseInt(m[3], 10) };
}
/* verify.js checkAnchor: no agent check (the word is fixed), everything else as v1. */
function checkAnchorV0(entries, a, withheld) { return verify.checkAnchor(entries, a, withheld, null); }

// ------------------------------------------------------------------------------------------------ dispatch

/* "v1" | "v0" from the first non-blank line's schema, or null when it names neither (or does not parse). */
function detectProtocol(raw) {
  const u8 = chain.toU8(raw);
  for (const ln of splitLines(u8).lines) {
    if (isBlank(ln.bytes)) continue;
    if (jcsm.depthExceeds(ln.bytes)) return null;
    let obj;
    try { obj = JSON.parse(dec.decode(ln.bytes)); } catch (e) { return null; }
    const s = obj && typeof obj === "object" && !Array.isArray(obj) ? own(obj, "schema") : undefined;
    return s === chain.LOG_SCHEMA ? "v1" : (s === V0_LOG_SCHEMA ? "v0" : null);
  }
  return null;
}

/* verifyBytesSync or verifyBytesV0 by the header's schema (protocol "auto"), or the one named; the result carries
   `protocol`. A file naming neither schema is read as v1 (which reports no_header). */
function verifyAuto(raw, opts, protocol) {
  const p = !protocol || protocol === "auto" ? detectProtocol(raw) : protocol;
  if (p === "v0") return verifyBytesV0(raw, opts);
  return Object.assign(verify.verifyBytesSync(raw, opts), { protocol: "v1" });
}
function parseAnchorAuto(text, protocol) { return protocol === "v0" ? parseAnchorTextV0(text) : chain.parseAnchorText(text); }
function checkAnchorAuto(r, a, withheld) { return r.protocol === "v0" ? checkAnchorV0(r.entries, a, withheld) : verify.checkAnchor(r.entries, a, withheld, r.header); }

module.exports = {
  V0_LOG_SCHEMA, V0_ENTRY_SCHEMA, V0_HEADER_DOMAIN, V0_ANCHOR_TZ,
  headerDigestV0, localDayV0, readBytesV0, checkChainV0, verifyBytesV0, anchorTextV0, parseAnchorTextV0, checkAnchorV0,
  detectProtocol, verifyAuto, parseAnchorAuto, checkAnchorAuto
};
