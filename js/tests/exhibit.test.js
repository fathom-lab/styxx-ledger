"use strict";
/* styxx-ledger exhibit, end to end and offline: a local http server serving a copy of the published exhibit
   (vectors/exhibit + the proofs under vectors/ots) and two fake explorers answering the real captured headers
   (vectors/ots/block_headers.json). The command runs as a child process (async, so the server keeps answering). */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const crypto = require("node:crypto");
const http = require("node:http");
const { execFile } = require("node:child_process");
const { BIN, VECTORS, tmpdir } = require("./helpers");
const { runExhibit, renderText, httpGet, FetchError } = require("../lib/exhibit");

const EXHIBIT = path.join(VECTORS, "exhibit");
const OTS = path.join(VECTORS, "ots");
const FIRST = "12ba959269fdfb5431cbcd3ae542c686124519f4f65c628056bc2d6049fac32b";   // seq 1, always sampled
const LAST = "0e5a698dece0bb33764c5202a03745a140a6ef66dba7bbcbc3896842795e152f";    // seq 734, always sampled
const BANNED = ["independent", "first", "no one", "provably"];

function assemble(dst) {
  const root = path.join(dst, "ledger");
  fs.mkdirSync(path.join(root, "anchors"), { recursive: true });
  fs.mkdirSync(path.join(root, "witness", "proofs"), { recursive: true });
  for (const n of ["ledger.jsonl", "withheld.json"]) fs.copyFileSync(path.join(EXHIBIT, n), path.join(root, n));
  fs.copyFileSync(path.join(EXHIBIT, "anchors", "index.json"), path.join(root, "anchors", "index.json"));
  fs.copyFileSync(path.join(EXHIBIT, "witness", "index.json"), path.join(root, "witness", "index.json"));
  for (const n of fs.readdirSync(path.join(OTS, "anchors"))) fs.copyFileSync(path.join(OTS, "anchors", n), path.join(root, "anchors", n));
  for (const d of [path.join(OTS, "witness"), path.join(EXHIBIT, "witness", "proofs")]) {
    for (const n of fs.readdirSync(d).filter(n => n.endsWith(".ots"))) fs.copyFileSync(path.join(d, n), path.join(root, "witness", "proofs", n));
  }
  return root;
}

function loadHeaders() {
  const doc = JSON.parse(fs.readFileSync(path.join(OTS, "block_headers.json"), "utf8"));
  const out = new Map();
  for (const [h, b] of Object.entries(doc.blocks)) out.set(Number(h), b.header);
  return out;
}

async function serve(t) {
  const dir = tmpdir(t);
  const root = assemble(dir);
  const headers = loadHeaders();
  // s.overrides.set(h, {...}) changes explorer b's answer ({_absent: true}: b answers 404 for h); s.limited.set("xa",
  // "0") makes explorer a answer 429 to everything (the value is Retry-After, null for none); s.redirects.set(path, loc)
  const s = { dir: root, overrides: new Map(), limited: new Map(), redirects: new Map(), requests: [] };
  const server = http.createServer((req, res) => {
    s.requests.push(req.url);
    const send = (code, body, type, extra) => { res.writeHead(code, Object.assign({}, extra || {}, { "Content-Type": type || "application/octet-stream", "Content-Length": Buffer.byteLength(body) })); res.end(body); };
    const bare = req.url.split("?")[0];
    if (s.redirects.has(bare)) return send(302, "", "text/plain", { Location: s.redirects.get(bare) });
    const parts = bare.replace(/^\/+|\/+$/g, "").split("/");
    if (s.limited.has(parts[0])) { const ra = s.limited.get(parts[0]); return send(429, "Too Many Requests", "text/plain", ra === null ? {} : { "Retry-After": ra }); }
    if ((parts[0] === "xa" || parts[0] === "xb") && parts.length === 3) {
      const hd = new Map();
      for (const [h, v] of headers) hd.set(h, Object.assign({}, v, parts[0] === "xb" && s.overrides.has(h) ? s.overrides.get(h) : {}));
      if (parts[1] === "block-height") {
        const h = /^[0-9]+$/.test(parts[2]) ? Number(parts[2]) : -1;
        return hd.has(h) && !hd.get(h)._absent ? send(200, hd.get(h).id, "text/plain") : send(404, "Block not found", "text/plain");
      }
      if (parts[1] === "block") {
        for (const v of hd.values()) if (v.id === parts[2]) return send(200, JSON.stringify(v), "application/json");
        return send(404, "Block not found", "text/plain");
      }
      return send(404, "not found", "text/plain");
    }
    const p = path.join(dir, ...parts);
    if (!path.resolve(p).startsWith(path.resolve(dir))) return send(403, "no");
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return send(200, fs.readFileSync(p));
    return send(404, "not found", "text/plain");
  });
  await new Promise(r => server.listen(0, "127.0.0.1", r));
  t.after(() => new Promise(r => server.close(r)));
  const base = "http://127.0.0.1:" + server.address().port;
  Object.assign(s, { url: base + "/ledger/", explorers: [base + "/xa", base + "/xb"] });
  return s;
}

function cli(s, ...extra) {
  return new Promise(resolve => {
    execFile(process.execPath, [BIN, "exhibit", s.url, "--explorer", s.explorers[0], "--explorer", s.explorers[1], ...extra],
      { encoding: "utf8", timeout: 120000, maxBuffer: 64 * 1024 * 1024 },
      (err, out, errOut) => resolve({ code: err ? (typeof err.code === "number" ? err.code : -1) : 0, out, err: errOut }));
  });
}
async function cliJson(s, ...extra) { const r = await cli(s, "--json", ...extra); return { code: r.code, rep: JSON.parse(r.out) }; }
const anchor = (rep, date) => rep.anchors.find(a => a.date === date);
const lineOf = (out, prefix) => out.split("\n").find(l => l.startsWith(prefix));

async function deadPort() {
  const srv = net.createServer();
  await new Promise(r => srv.listen(0, "127.0.0.1", r));
  const port = srv.address().port;
  await new Promise(r => srv.close(r));
  return port;
}

test("a: clean exhibit -> exit 0, the counts with their denominators", async t => {
  const s = await serve(t);
  const r = await cli(s);
  assert.equal(r.code, 0, r.out + r.err);
  assert.ok(r.out.includes("chain (protocol v0): re-derives: 743 lines = 738 published + 5 withheld, head 8afd642915b2a397764041a424619b03888dd1f94532c55cf6fc9782628e2409 (seq 743), 0 problem records"));
  assert.ok(r.out.includes("seq 129,131,136,138,351"));
  assert.ok(r.out.includes("anchors: 14 of 14 anchor texts hold against the chain (section 5 of protocol v0)"));
  assert.ok(r.out.includes("anchor proofs: 14 of 14 verify natively against bitcoin block headers"));
  assert.ok(r.out.includes("(lowest blocks: 974530 x11, 974635, 974768, 975028)"));
  assert.ok(r.out.includes("coverage: 692 of 738 published entries pinned"));
  assert.ok(r.out.includes("witness index: 743 records (734 bitcoin, 9 pending); 743 of 743 chain lines carry one at their seq"));
  assert.ok(r.out.includes("witness proofs: 22 sampled of 734 attested") && r.out.includes("seq 1 and 734): 22 of 22 commit"));
  assert.ok(r.out.includes("14 of 14 blocks asked agree on hash, merkle root and time"));
  assert.ok(r.out.includes("result: every check passed, 66 of 66 (exit 0)"));
  const low = r.out.toLowerCase();
  for (const w of BANNED) assert.ok(!low.includes(w), w);
  assert.ok(r.out.includes("reproducible by anyone") && r.out.includes("nothing is signed"));
  assert.ok(r.out.includes("a proof attests that bytes existed before a bitcoin block, not that they were published at a url"));
});

test("a: the --json record; heights and times are the captured headers'; the seeded sample is the fixture rule", async t => {
  const s = await serve(t);
  const { code, rep } = await cliJson(s);
  assert.equal(code, 0);
  assert.deepEqual(rep.counts, { pass: 66, fail: 0, pending: 0, unchecked: 0, total: 66 });
  assert.equal(rep.chain.file_sha256, "b9cdb57dc29e7c0f8fe0c5bbf4dbaf58383d819a85f00e01c4e814502857f533");
  assert.deepEqual([rep.chain.lines, rep.chain.published, rep.chain.withheld, rep.chain.last_seq], [743, 738, 5, 743]);
  assert.equal(rep.fetched.length, 54);
  assert.ok(rep.fetched.every(f => f.sha256 && f.bytes));
  const hd = loadHeaders();
  const lows = rep.anchors.map(a => a.proof.lowest.height).sort((a, b) => a - b);
  assert.deepEqual(lows, [...Array(11).fill(974530), 974635, 974768, 975028]);
  for (const a of rep.anchors) assert.equal(a.proof.lowest.time, hd.get(a.proof.lowest.height).timestamp);
  assert.equal(rep.witness.sampled.length, 22);
  assert.ok(rep.witness.sampled.every(x => x.verdict === "pass" && x.lowest.height === 975101 && x.lowest.time === 1794174086));
  assert.deepEqual(rep.witness.sampled.filter(x => x.picked.includes("attested line")).map(x => x.seq).sort((a, b) => a - b), [1, 734]);
  const fx = JSON.parse(fs.readFileSync(path.join(OTS, "fixtures.json"), "utf8"));
  assert.deepEqual(new Set(rep.witness.sampled.filter(x => x.picked.startsWith("seeded")).map(x => x.entry_id)), new Set(fx.witness_sample.map(x => x.entry_id)));
  assert.equal(rep.explorer_answers.length, 14);
  assert.ok(rep.explorer_answers.every(h => h.verdict === "agree" && h.answers.length === 2));
  assert.equal(rep.explorer_calls, 56);
});

test("b: one anchor .txt altered -> that anchor FAILs, exit 1", async t => {
  const s = await serve(t);
  const p = path.join(s.dir, "anchors", "2026-10-28.txt");
  fs.writeFileSync(p, fs.readFileSync(p, "utf8").replace("seq 173", "seq 172"));
  const r = await cli(s);
  assert.equal(r.code, 1);
  const line = lineOf(r.out, "  2026-10-28");
  assert.ok(line.includes("FAIL") && line.includes("the .txt is not the index's text") && line.includes("commitment mismatch"), line);
  assert.ok(r.out.includes("anchors: 13 of 14 anchor texts hold") && r.out.includes("anchor proofs: 13 of 14 verify"));
  for (const l of r.out.split("\n")) if (l.startsWith("  2026-") && !l.startsWith("  2026-10-28")) assert.ok(l.includes(" ok "), l);
  const { rep } = await cliJson(s);
  const a = anchor(rep, "2026-10-28");
  assert.equal(a.text_check.verdict, "fail"); assert.equal(a.chain_check.verdict, "fail");
  assert.equal(a.proof.status, "commitment_mismatch");
  assert.equal(rep.counts.fail, 3);
});

test("b2: a flipped byte inside an anchor proof fails that proof only", async t => {
  const s = await serve(t);
  const p = path.join(s.dir, "anchors", "2026-11-05.txt.ots");
  const b = fs.readFileSync(p); b[100] ^= 0x01; fs.writeFileSync(p, b);
  const { code, rep } = await cliJson(s);
  const a = anchor(rep, "2026-11-05");
  assert.equal(code, 1);
  assert.equal(a.proof.verdict, "fail");
  assert.equal(a.text_check.verdict, "pass"); assert.equal(a.chain_check.verdict, "pass");
});

test("c: explorers disagree -> not verified", async t => {
  const s = await serve(t);
  s.overrides.set(974530, { merkle_root: "00".repeat(32) });
  const r = await cli(s);
  assert.equal(r.code, 1);
  assert.ok(r.out.includes("anchor proofs: 3 of 14 verify"));
  assert.ok(r.out.split("explorers disagree on block 974530: not verified").length - 1 >= 11);
  assert.ok(r.out.includes("13 of 14 blocks asked agree on hash, merkle root and time; disagree on 974530"));
  const { rep } = await cliJson(s);
  const h = rep.explorer_answers.find(x => x.height === 974530);
  assert.equal(h.verdict, "disagree");
  assert.notEqual(h.answers[0].merkle_root, h.answers[1].merkle_root);
  assert.equal(rep.anchors.filter(a => a.proof.verdict === "fail").length, 11);
});

test("c2: explorers disagree on the time only -> the witness proofs are not verified", async t => {
  const s = await serve(t);
  s.overrides.set(975101, { timestamp: 1794174087 });
  const { code, rep } = await cliJson(s);
  assert.equal(code, 1);
  assert.ok(rep.witness.sampled.every(x => x.verdict === "fail" && x.why.includes("explorers disagree")));
  assert.ok(rep.anchors.every(a => a.proof.verdict === "pass"));
});

test("d: a witness proof swapped for another entry's -> commitment mismatch", async t => {
  const s = await serve(t);
  const proofs = path.join(s.dir, "witness", "proofs");
  fs.copyFileSync(path.join(proofs, LAST + ".ots"), path.join(proofs, FIRST + ".ots"));
  const r = await cli(s);
  assert.equal(r.code, 1);
  assert.ok(r.out.includes("21 of 22 commit to their entry_id"));
  assert.ok(lineOf(r.out, "  seq 1 ").includes("FAILS: commitment mismatch: the proof commits to " + LAST));
  const { rep } = await cliJson(s);
  const x = rep.witness.sampled.find(y => y.seq === 1);
  assert.equal(x.status, "commitment_mismatch"); assert.equal(x.verdict, "fail");
});

test("e: ledger truncated -> the anchor after the last line is not in chain", async t => {
  const s = await serve(t);
  const p = path.join(s.dir, "ledger.jsonl");
  const lines = fs.readFileSync(p).toString("utf8").split("\n");
  fs.writeFileSync(p, lines.slice(0, 701).join("\n") + "\n");     // header + 700 entries: through seq 705
  const r = await cli(s, "--sample", "0");
  assert.equal(r.code, 1);
  assert.ok(r.out.includes("re-derives: 705 lines = 700 published + 5 withheld"));
  const line = lineOf(r.out, "  2026-11-07");
  assert.ok(line.includes("FAIL") && line.includes("not in chain: seq 729 is after the last line (seq 705)"), line);
  assert.ok(r.out.includes("anchors: 13 of 14 anchor texts hold"));
  assert.ok(r.out.includes("anchor proofs: 14 of 14 verify"));
  assert.ok(r.out.includes("38 name a line not in the chain"));
});

test("flags: --no-ots asks no explorer; --sample n; --save keeps the bytes; one explorer", async t => {
  const s = await serve(t);
  let r = await cli(s, "--no-ots");
  assert.equal(r.code, 0);
  assert.ok(r.out.includes("proofs and explorers: not checked (--no-ots)") && r.out.includes("result: every check passed, 30 of 30 (exit 0)"));
  assert.ok(!s.requests.some(u => u.startsWith("/xa") || u.startsWith("/xb")));
  const { rep } = await cliJson(s, "--sample", "3");
  assert.equal(rep.witness.sampled.length, 5);
  const kept = path.join(tmpdir(t), "kept");
  r = await cli(s, "--save", kept);
  assert.equal(r.code, 0);
  assert.deepEqual(fs.readFileSync(path.join(kept, "ledger.jsonl")), fs.readFileSync(path.join(s.dir, "ledger.jsonl")));
  assert.equal(fs.readdirSync(path.join(kept, "witness", "proofs")).length, 22);
  assert.ok(fs.existsSync(path.join(kept, "_explorers")));
  const one = await new Promise(resolve => execFile(process.execPath, [BIN, "exhibit", s.url, "--explorer", s.explorers[0]], { encoding: "utf8" }, (e, out) => resolve({ code: e ? e.code : 0, out })));
  assert.equal(one.code, 0);
  assert.ok(one.out.includes("one explorer only: nothing to compare its headers with"));
});

test("a missing proof (404) fails; an explorer or exhibit that does not answer is exit 2; usage is exit 2", async t => {
  const s = await serve(t);
  fs.unlinkSync(path.join(s.dir, "anchors", "2026-11-01.txt.ots"));
  const { code, rep } = await cliJson(s);
  assert.equal(code, 1);
  assert.ok(anchor(rep, "2026-11-01").proof.why.includes("HTTP 404"));
  fs.copyFileSync(path.join(OTS, "anchors", "2026-11-01.txt.ots"), path.join(s.dir, "anchors", "2026-11-01.txt.ots"));
  const dead = "http://127.0.0.1:" + (await deadPort());
  const noSleep = async () => {};
  let r2 = await runExhibit(s.url, { explorers: [s.explorers[0], dead + "/api"], sleep: noSleep });
  assert.equal(r2.exit_code, 2); assert.equal(r2.counts.fail, 0);
  assert.ok(renderText(r2).includes("could not be made"));
  r2 = await runExhibit(dead + "/ledger/", { sleep: noSleep });
  assert.equal(r2.exit_code, 2); assert.equal(r2.chain, null);
  for (const args of [["exhibit", "ftp://example.org/ledger/"], ["exhibit", "https://example.org/ledger/", "--explorer", "nope"], ["exhibit", "https://example.org/ledger/", "--sample", "-1"], ["exhibit"]]) {
    const u = await new Promise(resolve => execFile(process.execPath, [BIN, ...args], { encoding: "utf8" }, e => resolve(e ? e.code : 0)));
    assert.equal(u, 2, args.join(" "));
  }
});

test("the 20 MB cap (here 1000 bytes) refuses a larger file", async t => {
  const s = await serve(t);
  await assert.rejects(httpGet(s.url + "ledger.jsonl", { cap: 1000 }), e => e instanceof FetchError && e.kind === "too_large");
});

/* ------------------------------------------------------------------ review 3e regressions (f and on) */
const O = require("../lib/ots");
const PHANTOM = "ab".repeat(32);
const editJson = (p, fn) => { const d = JSON.parse(fs.readFileSync(p, "utf8")); fn(d); fs.writeFileSync(p, JSON.stringify(d, null, 1)); };
function varuint(n) {
  const out = [];
  let v = BigInt(n);
  for (;;) { const b = Number(v & 0x7fn); v >>= 7n; if (v) out.push(b | 0x80); else { out.push(b); return Buffer.from(out); } }
}
/* a one-attestation .ots committing to sha256(target): bitcoin at `height` on the file digest, or a pending one */
function craftProof(target, height, uri) {
  const head = Buffer.concat([O.MAGIC, varuint(1), Buffer.from([0x08]), crypto.createHash("sha256").update(target).digest()]);
  if (height !== undefined && height !== null) {
    const pay = varuint(height);
    return Buffer.concat([head, Buffer.from([0]), Buffer.from(O.TAG_BITCOIN, "hex"), varuint(pay.length), pay]);
  }
  const u = Buffer.from(uri || "https://alice.btc.calendar.opentimestamps.org");
  const pay = Buffer.concat([varuint(u.length), u]);
  return Buffer.concat([head, Buffer.from([0]), Buffer.from(O.TAG_PENDING, "hex"), varuint(pay.length), pay]);
}
const noSleep = async () => {};

test("a: the clean report gives the age, the lag and the rollback caveat", async t => {
  const s = await serve(t);
  const rep = await runExhibit(s.url, { explorers: s.explorers, today: "2026-11-09" });
  const out = renderText(rep);
  assert.ok(out.includes("age: the last holding anchor is 2026-11-07 (seq 729), 2 days before this run (2026-11-09); 14 lines after it are pinned by nothing here"));
  assert.ok(out.includes("lag from an anchor's date to its lowest block: 1 to 11 days; 4 of 14 over 7 days"));
  assert.ok(out.includes("11 days after the anchor date (late)"));
  assert.ok(out.includes("a copy that is older but consistent passes every check here"));
  assert.equal(rep.exit_code, 0); assert.deepEqual(rep.off_host, []); assert.deepEqual(rep.explorers_rate_limited, {});
});

test("f: a withheld seq after the last line binds nothing -> not in chain", async t => {
  const s = await serve(t);
  editJson(path.join(s.dir, "withheld.json"), d => d.push({ seq: 744, entry_id: PHANTOM }));
  const text = "gate anchor 2026-11-08 head " + PHANTOM + " seq 744";
  fs.writeFileSync(path.join(s.dir, "anchors", "2026-11-08.txt"), text);
  editJson(path.join(s.dir, "anchors", "index.json"), d => d.anchors.push({ date: "2026-11-08", file: "anchors/2026-11-08.txt", text, seq: 744, head: PHANTOM }));
  const r = await cli(s, "--no-ots");
  assert.equal(r.code, 1);
  assert.ok(r.out.includes("re-derives: 743 lines = 738 published + 5 withheld, head 8afd6429") && r.out.includes("(seq 743)"));
  assert.ok(r.out.includes("  FAIL withheld.json names seq 744, which no published line binds"));
  const line = lineOf(r.out, "  2026-11-08");
  assert.ok(line.includes("FAIL") && line.includes("not in chain: seq 744 is a withheld digest no published line binds"), line);
  assert.ok(r.out.includes("anchors: 14 of 15 anchor texts hold"));
});

test("g: withheld.json naming a published line fails", async t => {
  const s = await serve(t);
  const rec = JSON.parse(fs.readFileSync(path.join(s.dir, "ledger.jsonl"), "utf8").split("\n")[495]);
  assert.equal(rec.seq, 500);
  editJson(path.join(s.dir, "withheld.json"), d => d.push({ seq: 500, entry_id: rec.entry_id }));
  const { code, rep } = await cliJson(s, "--no-ots");
  assert.equal(code, 1);
  assert.deepEqual([rep.chain.lines, rep.chain.withheld, rep.chain.withheld_records], [743, 5, 6]);
  assert.deepEqual(rep.chain.withheld_unbound, [{ seq: 500, why: "withheld.json names seq 500, which is published" }]);
});

test("h: an index without block (or block_time) fails, printed the same as python", async t => {
  const s = await serve(t);
  editJson(path.join(s.dir, "anchors", "index.json"), d => { for (const a of d.anchors) delete a.block; });
  editJson(path.join(s.dir, "witness", "index.json"), d => { delete d.entries[FIRST].block_time; });
  const r = await cli(s);
  assert.equal(r.code, 1);
  assert.ok(!r.out.includes("None") && !r.out.includes("null"));
  assert.equal(r.out.split("\n").filter(l => l.startsWith("  2026-") && l.includes("FAILS: the index names no block; the proof's lowest verified block is")).length, 14);
  assert.ok(r.out.includes("anchor proofs: 0 of 14 verify"));
  assert.ok(lineOf(r.out, "  seq 1 ").includes("the index names no block time; block 975101's header says 1794174086"));
});

test("i: an anchor the index marks pending is PEND, then fails after 7 days", async t => {
  const s = await serve(t);
  const p = path.join(s.dir, "anchors", "2026-11-07.txt");
  fs.writeFileSync(p + ".ots", craftProof(fs.readFileSync(p)));
  editJson(path.join(s.dir, "anchors", "index.json"), d => { const a = d.anchors.find(x => x.date === "2026-11-07"); a.status = "pending"; delete a.block; delete a.ots_sha256; });
  let rep = await runExhibit(s.url, { explorers: s.explorers, today: "2026-11-09" });
  const out = renderText(rep);
  const line = lineOf(out, "  2026-11-07");
  assert.ok(line.includes(" PEND ") && line.includes("calendar receipts only, as the index says"), line);
  assert.ok(out.includes("anchor proofs: 13 of 14 verify") && out.includes("; 1 of 14 pending"));
  assert.equal(rep.exit_code, 0); assert.equal(rep.counts.pending, 1);
  rep = await runExhibit(s.url, { explorers: s.explorers, today: "2026-11-20" });
  const a = anchor(rep, "2026-11-07");
  assert.equal(rep.exit_code, 1); assert.equal(a.proof.verdict, "fail");
  assert.ok(a.proof.why.includes("pending for 13 days after the anchor date (the rule here: at most 7"));
});

test("j: a redirect off the exhibit's host fails unless --allow-redirect", async t => {
  const s = await serve(t);
  const other = await serve(t);
  s.redirects.set("/ledger/anchors/2026-10-24.txt", other.url + "anchors/2026-10-24.txt");
  let { code, rep } = await cliJson(s, "--sample", "0");
  assert.equal(code, 1);
  const f = rep.fetched.find(x => x.path === "anchors/2026-10-24.txt");
  assert.equal(f.url, s.url + "anchors/2026-10-24.txt"); assert.equal(f.final_url, other.url + "anchors/2026-10-24.txt");
  assert.deepEqual(rep.off_host, [{ path: "anchors/2026-10-24.txt", url: f.url, final_url: f.final_url }]);
  assert.deepEqual(rep.checks.filter(c => c.verdict === "fail").map(c => c.name), ["files served from the exhibit's host"]);
  const r = await cli(s, "--sample", "0", "--allow-redirect");
  assert.equal(r.code, 0);
  assert.ok(r.out.includes("served from another host: anchors/2026-10-24.txt -> " + other.url));
  ({ code, rep } = await cliJson(s, "--sample", "0", "--allow-redirect"));
  assert.equal(code, 0); assert.ok(JSON.stringify(rep.checks).includes("allowed by --allow-redirect"));
});

test("k: a block no explorer knows fails; one explorer's 404 is disagreement", async t => {
  const s = await serve(t);
  const p = path.join(s.dir, "anchors", "2026-10-24.txt");
  fs.writeFileSync(p + ".ots", craftProof(fs.readFileSync(p), 99999999));
  s.overrides.set(974635, { _absent: true });
  const r = await cli(s, "--sample", "0");
  assert.equal(r.code, 1);
  assert.ok(lineOf(r.out, "  2026-10-24").includes("FAILS: block 99999999 does not exist at any explorer asked"));
  assert.ok(r.out.includes("  no explorer asked knows block 99999999"));
  assert.ok(r.out.includes("disagree on 974635"));
  assert.ok(lineOf(r.out, "  2026-11-04").includes("FAILS: explorers disagree on block 974635: not verified"));
  assert.ok(r.out.includes("; 0 could not be made"));
});

test("l: a huge height is refused and never asked", async t => {
  const s = await serve(t);
  const p = path.join(s.dir, "anchors", "2026-10-24.txt");
  fs.writeFileSync(p + ".ots", craftProof(fs.readFileSync(p), 2n ** 60n));
  const { code, rep } = await cliJson(s, "--sample", "0");
  const a = anchor(rep, "2026-10-24");
  assert.equal(code, 1); assert.equal(a.proof.status, "refused"); assert.ok(a.proof.why.includes("(attestation_payload)"));
  assert.ok(!s.requests.some(u => u.includes(String(2n ** 60n))));
});

test("m: a rate-limited explorer is named and left out; Retry-After honoured, else 2 4 8 16, capped at 60", async t => {
  const s = await serve(t);
  s.limited.set("xa", "0");
  let sleeps = [];
  const rep = await runExhibit(s.url, { explorers: s.explorers, sample: 0, sleep: async ms => { sleeps.push(ms); } });
  const out = renderText(rep);
  assert.equal(rep.exit_code, 2); assert.equal(rep.counts.fail, 0);
  assert.deepEqual(rep.explorers_rate_limited, { [s.explorers[0]]: 5 });
  assert.equal(s.requests.filter(u => u.startsWith("/xa")).length, 5);
  assert.deepEqual(sleeps, [0, 0, 0, 0]);
  const port = new URL(s.url).port;
  assert.ok(out.includes("127.0.0.1:" + port + " rate-limited this run (HTTP 429 after 5 tries) and was not asked again; run again in a minute, or name another esplora instance with --explorer"));
  assert.ok(rep.anchors.every(a => a.proof.verdict === "unchecked"));
  s.limited.set("xa", null); sleeps = [];
  await runExhibit(s.url, { explorers: s.explorers, sample: 0, sleep: async ms => { sleeps.push(ms); } });
  assert.deepEqual(sleeps, [2000, 4000, 8000, 16000]);
  s.limited.set("xa", "3600"); sleeps = [];
  await runExhibit(s.url, { explorers: s.explorers, sample: 0, sleep: async ms => { sleeps.push(ms); } });
  assert.deepEqual(sleeps, [60000, 60000, 60000, 60000]);
  const u = await new Promise(resolve => execFile(process.execPath, [BIN, "exhibit", "https://example.org/ledger/", "--today", "11/09/2026"], { encoding: "utf8" }, e => resolve(e ? e.code : 0)));
  assert.equal(u, 2);
  void noSleep;
});

// ------------------------------------------------- the lab's improvement sweep of 2026-11-09: ranks 44 and 45
const { networkReason, EXPLORERS_SILENT } = require("../lib/exhibit");

test("n: an explorer that does not answer says why, once; nothing unchecked reads FAIL; the repeats collapse (rank 44)", async t => {
  const s = await serve(t);
  const dead = "http://127.0.0.1:" + (await deadPort()) + "/api";
  const rep = await runExhibit(s.url, { explorers: [s.explorers[0], dead], sleep: async () => {}, today: "2026-11-09" });
  const lines = renderText(rep).split("\n").slice(0, -1);
  assert.equal(rep.exit_code, 2);
  assert.deepEqual(rep.counts, { pass: 30, fail: 0, pending: 0, unchecked: 36, total: 66 });
  assert.deepEqual(rep.explorers_unanswered, { [dead]: "the connection was refused" });
  assert.equal(lines[2], "explorer " + dead + " did not answer: the connection was refused; check the network, or pass --explorer <url> to ask another esplora api");
  assert.equal(lines.filter(l => l.includes("did not answer")).length, 1);
  const anchorLines = lines.filter(l => l.startsWith("  2026-"));
  assert.equal(anchorLines.length, 14);
  assert.ok(anchorLines.every(l => l.includes(" ---- chain: holds; proof unchecked: " + EXPLORERS_SILENT)), anchorLines[0]);
  assert.ok(lines.find(l => l.startsWith("anchor proofs:")).endsWith("; 14 of 14 not checked"));
  assert.ok(lines.includes("  22 of 22 sampled, seq 1,21,32,47,122,137,149,346,361,386,419,446,543,564,601,608,612,614,622,632,701,734: unchecked: " + EXPLORERS_SILENT));
  assert.deepEqual(lines.filter(l => l.startsWith("  not made")), ["  not made: 36 checks, anchor 2026-10-24 proof verifies to witness seq 734 proof commits and verifies: " + EXPLORERS_SILENT]);
  assert.equal(lines.length, 40);
});

test("o: a mistyped url is exit 2 with the url fetched and what to check; a dead exhibit names its reason (rank 45)", async t => {
  const s = await serve(t);
  const url = s.url.replace(/\/ledger\/$/, "/ledgr/");
  const r = await new Promise(resolve => execFile(process.execPath, [BIN, "exhibit", url, "--explorer", s.explorers[0], "--explorer", s.explorers[1]],
    { encoding: "utf8", timeout: 120000 }, (err, out) => resolve({ code: err ? err.code : 0, out })));
  const detail = url + "ledger.jsonl answered HTTP 404: there is no ledger.jsonl at that url; check that the url names the exhibit's folder, the one that holds ledger.jsonl (e.g. https://fathom-lab.github.io/styxx/ledger/)";
  assert.equal(r.code, 2);
  assert.ok(r.out.includes("\nledger.jsonl: " + detail + "\nnothing was verified: every other check needs the ledger\n"), r.out);
  assert.ok(r.out.includes("result: 0 of 1 checks passed; 0 failed; 1 could not be made (exit 2)"));
  assert.ok(r.out.includes("  not made: ledger.jsonl fetched: " + detail));
  for (const gone of ["FAILED", "anchors: none read", "explorers:", "0 of 0 blocks"]) assert.ok(!r.out.includes(gone), gone);
  const dead = "http://127.0.0.1:" + (await deadPort()) + "/ledger/";
  const rep = await runExhibit(dead, { sleep: async () => {} });
  assert.equal(rep.exit_code, 2); assert.equal(rep.counts.fail, 0);
  assert.equal(rep.checks[0].detail, dead + "ledger.jsonl did not answer: the connection was refused; check the url and this machine's network");
});

test("p: node's network errors read in the words the python package uses (rank 45)", () => {
  const f = (code, extra) => Object.assign(new TypeError("fetch failed"), { cause: Object.assign(new Error("x"), { code }, extra || {}) });
  const cases = [
    [f("ENOTFOUND"), "the host name did not resolve (dns)"],
    [f("EAI_AGAIN"), "the host name did not resolve (dns)"],
    [f("ECONNREFUSED"), "the connection was refused"],
    [Object.assign(new TypeError("fetch failed"), { cause: Object.assign(new AggregateError([Object.assign(new Error("a"), { code: "ECONNREFUSED" })], ""), {}) }), "the connection was refused"],
    [f("ECONNRESET"), "the connection was reset"],
    [f("UND_ERR_SOCKET"), "the connection was reset"],
    [f("UND_ERR_CONNECT_TIMEOUT"), "no answer within 30 s"],
    [f("CERT_HAS_EXPIRED"), "the tls handshake failed (a certificate or protocol error)"],
    [f("DEPTH_ZERO_SELF_SIGNED_CERT"), "the tls handshake failed (a certificate or protocol error)"],
    [f("ERR_SOMETHING_ELSE"), "no answer (TypeError: ERR_SOMETHING_ELSE)"],
  ];
  for (const [e, words] of cases) assert.equal(networkReason(e, 30000), words, words);
});
