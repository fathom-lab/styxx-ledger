#!/usr/bin/env node
/* run_vectors.mjs: answer the shared v1 vectors with the javascript package (js/lib/verify.js, CommonJS).

     node vectors/run_vectors.mjs [--vectors vectors/vectors_v1.json] [--verify js/lib/verify.js] [-v]

   The module's expected exports are listed in vectors/README.md. Every call is awaited, so a module may answer
   synchronously or with promises. Read-side cases: apply the transform to base_v1.jsonl (the input's sha256 must
   match), verify with the withheld list and anchor texts given, compare with `expect` (only the keys in `compare`
   when a case names them). Write-side cases: call the named function, compare the value or the thrown error's
   `.code`. Prints "k of n vectors answered as the file says"; exit 0 only when k == n. run_vectors.py does the same
   with the python package. */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
let vectorsPath = path.join(HERE, "vectors_v1.json");
let verifyPath = path.join(HERE, "..", "js", "lib", "verify.js");
let verbose = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--vectors") vectorsPath = args[++i];
  else if (args[i] === "--verify") verifyPath = args[++i];
  else if (args[i] === "-v" || args[i] === "--verbose") verbose = true;
}

let V;
try { V = require(path.resolve(verifyPath)); }
catch (e) { console.log("cannot load the verifier module " + verifyPath + ": " + (e && e.message ? e.message : e)); process.exit(2); }

const doc = JSON.parse(fs.readFileSync(vectorsPath, "utf8"));
const base = fs.readFileSync(path.join(path.dirname(vectorsPath), doc.base));
const sha = b => crypto.createHash("sha256").update(b).digest("hex");

// a key-sorted stringify for comparing answers (the module's own dump is what is under test, so it is not used here)
function stable(v) {
  if (v === undefined) return "undefined";
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(stable).join(",") + "]";
  return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + stable(v[k])).join(",") + "}";
}

// ---------------------------------------------------------------------------------------------- transforms
function splitLines(buf) {          // Buffer -> Buffers split on 0x0a, terminators dropped (python's bytes.split)
  const out = []; let start = 0;
  for (let i = 0; i < buf.length; i++) if (buf[i] === 0x0a) { out.push(buf.subarray(start, i)); start = i + 1; }
  out.push(buf.subarray(start));
  return out;
}
const isBlank = b => b.toString("utf8").trim() === "";
const joinLF = parts => { const nl = Buffer.from("\n"); const out = []; parts.forEach((p, i) => { if (i) out.push(nl); out.push(p); }); return Buffer.concat(out); };
const canon = async o => Buffer.from(await V.dump(o), "utf8");

async function rechain(lines, fromSeq) {
  const out = []; let prev = null, seenHeader = false;
  for (const ln of lines) {
    if (isBlank(ln)) { out.push(ln); continue; }
    const o = JSON.parse(ln.toString("utf8"));
    if (!seenHeader) { seenHeader = true; prev = await V.headerDigest(o); out.push(ln); continue; }
    if (o.seq >= fromSeq) {
      o.prev = prev; delete o.entry_id;
      o.entry_id = await V.entryId(o);
      out.push(await canon(o));
    } else out.push(ln);
    prev = o.entry_id;
  }
  return out;
}

async function apply(baseBuf, t) {
  const op = t.op;
  if (op === "identity") return baseBuf;
  if (op === "crlf_first_line") { const i = baseBuf.indexOf(0x0a); return Buffer.concat([baseBuf.subarray(0, i), Buffer.from("\r\n"), baseBuf.subarray(i + 1)]); }
  if (op === "truncate_last") {
    let s = baseBuf; while (s.length && s[s.length - 1] === 0x0a) s = s.subarray(0, s.length - 1);
    const parts = splitLines(s); parts.pop();
    return Buffer.concat([joinLF(parts), Buffer.from("\n")]);
  }
  if (op === "replace_all") return Buffer.from(t.text, "utf8");
  if (op === "append_nested") {
    const n = t.depth - 1;
    return Buffer.concat([baseBuf, Buffer.from('{"deep":' + "[".repeat(n) + "1" + "]".repeat(n) + "}\n", "utf8")]);
  }
  let out = []; let headerDone = false;
  for (const ln of splitLines(baseBuf)) {
    if (isBlank(ln)) { out.push(ln); continue; }
    const o = JSON.parse(ln.toString("utf8"));
    if (!headerDone) {
      headerDone = true;
      if (op === "set_header" || op === "set_header_rechain") { o[t.field] = t.value; out.push(await canon(o)); }
      else out.push(ln);
      continue;
    }
    const s = o.seq;
    if ((op === "set_field" || op === "set_field_rechain") && s === t.seq) { o[t.field] = t.value; out.push(await canon(o)); }
    else if (op === "drop_seq" && s === t.seq) continue;
    else if (op === "replace_in_line" && s === t.seq) {
      const oldB = Buffer.from(t.old, "utf8"), i = ln.indexOf(oldB);
      if (i < 0) throw new Error("replace_in_line: " + JSON.stringify(t.old) + " not in the line of seq " + s);
      out.push(Buffer.concat([ln.subarray(0, i), Buffer.from(t.new, "utf8"), ln.subarray(i + oldB.length)]));
    }
    else if (op === "dup_key" && s === t.seq) out.push(Buffer.concat([ln.subarray(0, ln.length - 1), Buffer.from(',"' + t.key + '":' + JSON.stringify(t.value) + "}", "utf8")]));
    else out.push(ln);
  }
  if (op === "set_field_rechain") out = await rechain(out, t.seq);
  else if (op === "set_header_rechain") out = await rechain(out, 1);
  else if (!["set_field", "drop_seq", "dup_key", "set_header", "replace_in_line"].includes(op)) throw new Error("unknown transform op " + op);
  return joinLF(out);
}

// ------------------------------------------------------------------------------------------------- answers
const codesOf = p => Array.isArray(p.codes) ? p.codes : (p.code ? [p.code] : []);
const noSeq = p => p.seq === undefined || p.seq === null;

async function answerRead(input, c) {
  const withheld = c.withheld || [];
  const r = await V.verifyBytes(new Uint8Array(input), { withheld });
  const got = {
    ok: r.ok,
    problem_seqs: [...new Set(r.problems.filter(p => !noSeq(p)).map(p => p.seq))].sort((a, b) => a - b),
    problems_without_seq: r.problems.filter(noSeq).length,
    problem_codes: [...new Set(r.problems.flatMap(codesOf))].sort(),
    head: r.head,
    bridged: r.bridged
  };
  if (c.anchors) {
    got.anchors_ok = [];
    for (const t of c.anchors) {
      const a = await V.parseAnchorText(t);
      got.anchors_ok.push(a ? !!(await V.checkAnchor(r.entries, a, withheld, r.header)).ok : false);
    }
  }
  if (c.coverage_anchor_seqs) got.coverage = await V.coverage(r.entries, withheld, c.coverage_anchor_seqs);
  return got;
}

async function callWrite(c) {           // -> {value, error}
  try {
    let v;
    switch (c.fn) {
      case "jcs": v = await V.jcs(c.input); break;
      case "day_of": v = await V.dayOf(c.timestamp, c.tz); break;
      case "header_digest": v = await V.headerDigest(c.header); break;
      case "entry_id": v = await V.entryId(c.core); break;
      case "anchor_text": v = await V.anchorText(c.agent, c.date, c.head, c.seq); break;
      case "late_of": v = await V.lateOf(c.anchor_date, c.timestamp, c.tz); break;
      case "build_entry": v = await V.dump(await V.buildEntry(c.header, c.seq, c.prev, c.kind, c.timestamp, c.fields)); break;
      default: throw Object.assign(new Error("unknown write fn " + c.fn), { code: "runner_unknown_fn" });
    }
    return { value: v, error: null };
  } catch (e) {
    return { value: null, error: e && e.code !== undefined ? e.code : "uncoded: " + (e && e.message ? e.message : String(e)) };
  }
}

(async () => {
  if (sha(base) !== doc.base_sha256) { console.log("the base file is not the one the vectors were made over (a checkout that converted LF to CRLF does this)"); process.exit(2); }
  const total = doc.read.length + doc.write.length;
  let failed = 0; const groups = {};
  const tally = (g, ok) => { groups[g] = groups[g] || [0, 0]; groups[g][1]++; if (ok) groups[g][0]++; else failed++; };
  for (const c of doc.read) {
    let ok, got;
    try {
      const input = await apply(base, c.transform);
      if (sha(input) !== c.input_sha256) { ok = false; got = { input_sha256: sha(input) }; }
      else {
        got = await answerRead(input, c);
        const keys = c.compare || Object.keys(c.expect);
        ok = keys.every(k => stable(got[k]) === stable(c.expect[k]));
      }
    } catch (e) { ok = false; got = { thrown: e && e.message ? e.message : String(e) }; }
    tally("read", ok);
    if (verbose || !ok) console.log((ok ? "ok   " : "FAIL ") + "read  " + c.name);
    if (!ok) { console.log("   expected " + stable(c.expect)); console.log("   got      " + stable(got)); }
  }
  for (const c of doc.write) {
    const got = await callWrite(c);
    let ok;
    if ("expect_error" in c) ok = got.error === c.expect_error;
    else {
      ok = got.error === null && got.value === c.expect;
      if (ok && c.expect_sha256) ok = sha(Buffer.from(got.value, "utf8")) === c.expect_sha256;
    }
    tally("write:" + c.fn, ok);
    if (verbose || !ok) console.log((ok ? "ok   " : "FAIL ") + "write " + c.name);
    if (!ok) { console.log("   expected " + JSON.stringify("expect_error" in c ? { error: c.expect_error } : { value: c.expect })); console.log("   got      " + JSON.stringify(got)); }
  }
  for (const g of Object.keys(groups).sort()) console.log("  " + g.padEnd(22) + " " + groups[g][0] + " of " + groups[g][1]);
  console.log("implementation: " + path.relative(process.cwd(), path.resolve(verifyPath)) + " (node " + process.versions.node + ", " + process.platform + ")");
  console.log(`${total - failed} of ${total} vectors answered as the file says`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error("error: " + (e && e.message ? e.message : e)); process.exit(2); });
