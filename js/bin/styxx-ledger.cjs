#!/usr/bin/env node
"use strict";
/* styxx-ledger: the command line of the javascript package (protocol v1).

   exit 0: done / re-derives and every anchor holds; 1: refused / does not re-derive / an anchor does not hold;
   2: usage or an unreadable input. exhibit <url>: 0 every check passed, 1 any failed, 2 usage, or a file / an
   explorer did not answer. */
const fs = require("node:fs");
const L = require("../lib/index.js");

const USAGE = `styxx-ledger ${L.version} (protocol v1)

  styxx-ledger init <log> --agent <name> --tz <iana zone> --certifies <sentence> [--kinds a,b,...]
                          [--created <utc>] [--timestamp <utc>] [--no-started]
      write the header (kinds always gain anchor and started) and, unless --no-started (or --no-start),
      one started entry for this writer at --timestamp (default: now).
  styxx-ledger append <log> --kind <kind> [--fields '<json object>' | --fields-file <f>] [--field k=v ...] [--timestamp <utc>]
      append one entry under the lock; prints its line.
  styxx-ledger verify <log> [--withheld <withheld.json>] [--anchor '<text>' ...] [--anchors-file <f>] [--json]
                            [--protocol auto|v1|v0]
      re-derive the file; check each posted anchor text against it. the header's schema picks the protocol
      (a darkflobi.gate/log/v0 file is read under v0's rules); --protocol forces one.
  styxx-ledger anchor-text <log> [--date YYYY-MM-DD] [--timestamp <utc>] [--record]
      compose "<agent> anchor <date> head <hex> seq <n>" for a closed day (default: the day before
      --timestamp, or before now, in anchor_tz) and print it; with --record also write the anchor entry
      (its late flag is section 5's rule, never a flag). posting the text is yours.
  styxx-ledger head <log>
      print "<head> seq <n>" when the file re-derives.
  styxx-ledger exhibit <url> [--explorer <esplora api url> ...] [--sample <n>] [--no-ots] [--save <dir>] [--allow-redirect] [--today <YYYY-MM-DD>] [--json]
      fetch a published exhibit (ledger.jsonl, withheld.json, anchors/, witness/) and re-derive it on this machine:
      the chain, every anchor text against the chain, every anchor's opentimestamps proof against bitcoin block
      headers from each explorer (default blockstream.info and mempool.space; they must agree), and a seeded
      sample of the witness proofs (--sample, default 20, plus the earliest and latest attested lines).
      a file served from another host (a redirect off the url's host, or off https) fails unless --allow-redirect.
      --today sets the day the ages are counted against (default: today in utc).
      e.g. styxx-ledger exhibit https://fathom-lab.github.io/styxx/ledger/

  timestamps are utc YYYY-MM-DDTHH:MM:SSZ. nothing here signs; only exhibit touches the network.`;

function parseArgs(argv) {
  const out = { _: [], multi: {} };
  const MULTI = new Set(["field", "anchor", "explorer"]);
  const FLAGS = new Set(["json", "dry-run", "record", "late", "no-start", "no-started", "no-ots", "allow-redirect", "help", "version"]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h") { out.help = true; continue; }
    if (a.startsWith("--")) {
      let k = a.slice(2), v;
      const eq = k.indexOf("=");
      if (eq >= 0) { v = k.slice(eq + 1); k = k.slice(0, eq); }
      if (FLAGS.has(k) && v === undefined) { out[k] = true; continue; }
      if (v === undefined) {
        if (i + 1 >= argv.length) throw usage("--" + k + " needs a value");
        v = argv[++i];
      }
      if (MULTI.has(k)) (out.multi[k] = out.multi[k] || []).push(v); else out[k] = v;
    } else out._.push(a);
  }
  return out;
}
function usage(msg) { const e = new Error(msg); e.usage = true; return e; }
function readJson(file, what) {
  let text;
  try { text = fs.readFileSync(file, "utf8"); } catch (e) { throw usage("cannot read " + what + " " + file + ": " + e.code); }
  try { return JSON.parse(text); } catch (e) { throw usage(what + " " + file + " is not json: " + e.message); }
}
function dayBefore(ts, tz) {
  const today = L.dayOf(ts || L.nowUtc(), tz);
  return new Date(Date.parse(today + "T00:00:00Z") - 86400000).toISOString().slice(0, 10);
}

/* --kinds a,b: every comma-separated item is a kind name. An empty item (note,,send, a trailing comma, or "") is
   refused as header_form, never dropped, as the python cli refuses it (improvements 2026-11-09 rank 67). */
function kindsArg(s) {
  const items = String(s).split(",").map(x => x.trim());
  if (items.some(x => !x)) throw new L.LedgerValueError("header_form", "--kinds holds an empty item (" + JSON.stringify(String(s)) + "); give comma-separated kind names, e.g. note,send");
  return items;
}

function cmdInit(log, o) {
  // a flag given empty (--certifies "") reaches the header check and is refused there (exit 1), as in python;
  // only a flag not given at all is usage (exit 2)
  if (o.agent === undefined || o.certifies === undefined || o.tz === undefined) throw usage("init needs --agent, --tz and --certifies");
  const kinds = new Set(["anchor", "started"]);
  for (const k of kindsArg(o.kinds === undefined ? "note" : o.kinds)) kinds.add(k);
  const led = L.Ledger.init(log, { agent: o.agent, certifies: o.certifies, anchorTz: o.tz, kinds: [...kinds], created: o.created });
  if (!o["no-start"] && !o["no-started"]) led.start({}, o.timestamp ? { timestamp: o.timestamp } : undefined);
  const h = led.head();
  console.log("initialised " + log + ": agent " + o.agent + ", anchor_tz " + o.tz + ", kinds " + [...kinds].sort().join(",") + "; head " + h.head + " seq " + h.seq);
  return 0;
}

function cmdAppend(log, o) {
  if (o.kind === undefined) throw usage("append needs --kind");   // --kind "" is refused by the writer (kind_not_declared), as in python
  let fields = {};
  if (o.fields !== undefined) { try { fields = JSON.parse(o.fields); } catch (e) { throw usage("--fields is not json: " + e.message); } }
  else if (o["fields-file"]) fields = readJson(o["fields-file"], "--fields-file");
  if (fields === null || typeof fields !== "object" || Array.isArray(fields)) throw usage("the fields must be a json object");
  for (const kv of o.multi.field || []) {
    const i = kv.indexOf("=");
    if (i <= 0) throw usage("--field wants k=v, got " + JSON.stringify(kv));
    fields[kv.slice(0, i)] = kv.slice(i + 1);
  }
  const e = new L.Ledger(log).append(o.kind, fields, o.timestamp ? { timestamp: o.timestamp } : undefined);
  console.log(L.dump(e));
  return 0;
}

function loadWithheld(file) {
  if (!file) return [];
  const w = readJson(file, "--withheld");
  const list = Array.isArray(w) ? w : (w && Array.isArray(w.withheld) ? w.withheld : null);
  if (!list) throw usage("--withheld wants a json array of {seq, entry_id}, or an object with a withheld array");
  return list;
}
function loadAnchors(o) {
  const texts = (o.multi.anchor || []).slice();
  if (o["anchors-file"]) {
    const raw = fs.readFileSync(o["anchors-file"], "utf8");
    let arr = null;
    try { const j = JSON.parse(raw); if (Array.isArray(j)) arr = j; } catch (e) { /* not json: one text per line */ }
    for (const t of arr || raw.split("\n").filter(s => s.trim())) texts.push(String(t));
  }
  return texts;
}

function cmdVerify(log, o) {
  let raw;
  try { raw = fs.readFileSync(log); } catch (e) { throw usage("cannot read " + log + ": " + e.code); }
  const withheld = loadWithheld(o.withheld);
  const proto = o.protocol || "auto";
  if (!["auto", "v1", "v0"].includes(proto)) throw usage("--protocol takes auto, v1 or v0");
  const r = L.verifyAuto(raw, { withheld }, proto);
  const anchors = loadAnchors(o).map(t => {
    const a = L.v0.parseAnchorAuto(t, r.protocol);
    if (!a) return { text: t, ok: false, why: "not the anchor form" };
    const c = L.v0.checkAnchorAuto(r, a, withheld);
    return Object.assign({ text: t }, c);
  });
  const allOk = r.ok && anchors.every(a => a.ok);
  if (o.json) {
    console.log(JSON.stringify({ ok: r.ok, protocol: r.protocol, head: r.head, entries: r.entries.length, bridged: r.bridged, problems: r.problems, file_sha256: r.file_sha256, anchors }, null, 1));
    return allOk ? 0 : 1;
  }
  if (r.protocol === "v0") console.log("protocol v0 (darkflobi.gate/log/v0): read under v0's rules");
  if (r.ok) {
    const last = r.entries.length ? r.entries[r.entries.length - 1].entry.seq : 0;
    console.log("re-derives: " + r.entries.length + " entries, head " + r.head + " seq " + last + (r.bridged.length ? ", bridged over withheld seqs " + r.bridged.join(",") : ""));
  } else {
    console.log("does not re-derive: " + r.problems.length + " problem record(s)");
    for (const p of r.problems.slice(0, 50)) {
      const codes = p.codes || [p.code];
      const texts = p.problems || [p.problem];
      console.log("  line " + (p.line === null ? "-" : p.line) + " seq " + (p.seq === null ? "-" : p.seq) + ": " + codes.map((c, i) => c + " (" + texts[i] + ")").join("; "));
    }
    if (r.problems.length > 50) console.log("  ... " + (r.problems.length - 50) + " more");
  }
  anchors.forEach(a => {
    if (a.why) console.log("anchor " + JSON.stringify(a.text.slice(0, 60)) + ": does not hold (" + a.why + ")");
    else {
      const why = [];
      if (!a.agent_matches) why.push("agent is not the header's");
      if (!a.in_chain) why.push("no entry at seq " + a.seq + " carries that head");
      if (a.day_lines_after) why.push(a.day_lines_after + " entr" + (a.day_lines_after === 1 ? "y" : "ies") + " of " + a.date + " after seq " + a.seq);
      if (a.ledger_anchor_line && !a.ledger_anchor_line.agrees) why.push("the ledger's own anchor entry for " + a.date + " disagrees");
      console.log("anchor " + a.date + " seq " + a.seq + ": " + (a.ok ? "holds" + (a.via_withheld ? " (on a withheld digest)" : "") : "does not hold (" + why.join("; ") + ")"));
    }
  });
  if (anchors.length) console.log(anchors.filter(a => a.ok).length + " of " + anchors.length + " anchors hold");
  return allOk ? 0 : 1;
}

function cmdAnchorText(log, o) {
  const led = new L.Ledger(log);
  if (o.late) throw usage("--late is gone: an anchor entry's late is section 5's rule, set by the writer");
  const tz = led.head() && led.read().header.anchor_tz;   // head() refuses a file that does not re-derive
  const date = o.date || dayBefore(o.timestamp, tz);
  const opts = { timestamp: o.timestamp };
  if (!o.record) {   // --dry-run is accepted and means the default: compose only
    const c = led.composeAnchor(date, opts);
    console.log(c.text);
    console.error("composed only; post it, then record it: styxx-ledger anchor-text " + log + " --date " + c.date + " --record");
    return 0;
  }
  const r = led.anchor(date, opts);
  console.log(r.text);
  console.error("anchor entry seq " + r.entry.seq + " written for " + date + (r.entry.late ? " (late)" : "") + "; post the text above in a public place");
  return 0;
}

function cmdHead(log) {
  const h = new L.Ledger(log).head();
  console.log(h.head + " seq " + h.seq);
  return 0;
}

async function cmdExhibit(url, o) {
  const E = require("../lib/exhibit.js");
  if (!/^https?:\/\//.test(url)) throw usage("exhibit wants an http(s) url, e.g. https://fathom-lab.github.io/styxx/ledger/");
  const exps = o.multi.explorer && o.multi.explorer.length ? o.multi.explorer : E.DEFAULT_EXPLORERS;
  for (const e of exps) if (!/^https?:\/\//.test(e)) throw usage("--explorer wants an http(s) url (an esplora api base such as https://blockstream.info/api)");
  let sample = E.DEFAULT_SAMPLE;
  if (o.sample !== undefined) {
    if (!/^[0-9]+$/.test(o.sample)) throw usage("--sample wants a count of 0 or more");
    sample = Number(o.sample);
  }
  if (o.today !== undefined && !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(o.today)) throw usage("--today wants a date YYYY-MM-DD");
  const rep = await E.runExhibit(url, { explorers: exps, sample, noOts: !!o["no-ots"], saveDir: o.save, allowRedirect: !!o["allow-redirect"], today: o.today });
  process.stdout.write(o.json ? JSON.stringify(rep, null, 1) + "\n" : E.renderText(rep));
  return rep.exit_code;
}

function main(argv) {
  let o;
  try { o = parseArgs(argv); } catch (e) { console.error("styxx-ledger: " + e.message); return 2; }
  if (o.version) { console.log(L.version); return 0; }
  const [cmd, log] = o._;
  if (o.help || !cmd) { console.log(USAGE); return cmd || o.help ? 0 : 2; }
  const table = { init: cmdInit, append: cmdAppend, verify: cmdVerify, "anchor-text": cmdAnchorText, head: cmdHead, exhibit: cmdExhibit };
  if (!table[cmd]) { console.error("styxx-ledger: unknown command " + JSON.stringify(cmd) + "\n\n" + USAGE); return 2; }
  if (!log) { console.error("styxx-ledger " + cmd + ": needs " + (cmd === "exhibit" ? "<url>" : "<log>")); return 2; }
  const fail = e => {
    if (e && e.usage) { console.error("styxx-ledger " + cmd + ": " + e.message); return 2; }
    if (e && e.code && (e.name === "LedgerValueError" || e.name === "LedgerError" || e.name === "LedgerLocked" || e.name === "LedgerTamper")) {
      console.error("styxx-ledger " + cmd + ": refused (" + e.code + "): " + e.message);
      if (e.problems) for (const p of e.problems.slice(0, 20)) console.error("  line " + (p.line === null ? "-" : p.line) + " seq " + (p.seq === null ? "-" : p.seq) + ": " + (p.codes || [p.code]).join(","));
      return 1;
    }
    console.error("styxx-ledger " + cmd + ": " + (e && e.message ? e.message : e));
    return 2;
  };
  let rc;
  try { rc = table[cmd](log, o); } catch (e) { return fail(e); }
  return rc && typeof rc.then === "function" ? rc.catch(fail) : rc;
}

const rc = main(process.argv.slice(2));
if (rc && typeof rc.then === "function") rc.then(c => { process.exitCode = c; });
else process.exitCode = rc;
