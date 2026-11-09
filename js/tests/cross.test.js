"use strict";
/* cross tests: a ledger written by python verifies here, byte for byte, same head, and the javascript writer,
   handed the same header, kinds, fields and timestamps, writes the same bytes; the javascript-written fixture
   (tests/fixtures/js_written.jsonl, read by the python suite) is what this writer writes now.

     python -> js   vectors/base_v1.jsonl (written by the python core) and every python/tests/fixtures/*.jsonl,
                    skipped with the reason while the python fixtures are absent.
     js -> python   python/tests/test_cross.py reads tests/fixtures/js_written.jsonl and its .json sidecar. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const V = require("../lib/verify");
const { VECTORS, PY_FIXTURES, JS_FIXTURES, tmpdir, rewriteWithJs } = require("./helpers");

const sha = b => crypto.createHash("sha256").update(b).digest("hex");
const pyFiles = fs.existsSync(PY_FIXTURES) ? fs.readdirSync(PY_FIXTURES).filter(f => f.endsWith(".jsonl")).sort() : [];

test("python-written base_v1.jsonl: verifies here and the js writer rewrites it byte for byte", t => {
  const doc = JSON.parse(fs.readFileSync(path.join(VECTORS, "vectors_v1.json"), "utf8"));
  const base = fs.readFileSync(path.join(VECTORS, "base_v1.jsonl"));
  const r = V.verifyBytesSync(base);
  assert.equal(r.ok, true);
  assert.equal(r.head, doc.base_head);
  const again = rewriteWithJs(base, tmpdir(t));
  assert.equal(sha(again), doc.base_sha256, "same bytes");
  assert.equal(V.verifyBytesSync(again).head, doc.base_head, "same head");
});

if (!pyFiles.length) {
  test("python/tests/fixtures/*.jsonl verify here", { skip: "no python-written fixture yet: " + PY_FIXTURES + " holds no .jsonl" }, () => {});
}
for (const name of pyFiles) {
  test("python-written " + name + ": verifies here, same head; the js writer rewrites it byte for byte", t => {
    const raw = fs.readFileSync(path.join(PY_FIXTURES, name));
    const r = V.verifyBytesSync(raw);
    assert.equal(r.ok, true, JSON.stringify(r.problems.slice(0, 5)));
    const side = path.join(PY_FIXTURES, name.replace(/\.jsonl$/, ".json"));
    if (fs.existsSync(side)) {
      const meta = JSON.parse(fs.readFileSync(side, "utf8"));
      if (meta.head) assert.equal(r.head, meta.head);
      if (meta.sha256) assert.equal(sha(raw), meta.sha256);
      for (const tx of meta.anchor_texts || []) assert.equal(V.checkAnchor(r.entries, V.parseAnchorText(tx), [], r.header).ok, true, tx);
    }
    const again = rewriteWithJs(raw, tmpdir(t));
    assert.equal(sha(again), sha(raw), "same bytes");
    assert.equal(V.verifyBytesSync(again).head, r.head, "same head");
  });
}

// the python package, when this box can run it: python/src on sys.path, a zone database (on windows the tzdata
// package; a python without it refuses every named zone), no bytecode written
const PY_SRC = path.join(PY_FIXTURES, "..", "..", "src");
const PY_ENV = Object.assign({}, process.env, { PYTHONDONTWRITEBYTECODE: "1" });
const python = ["python", "python3"].find(bin => {
  const probe = "import sys, zoneinfo; sys.path.insert(0, sys.argv[1]); import styxx_ledger.writer; zoneinfo.ZoneInfo('America/New_York'); zoneinfo.ZoneInfo('UTC')";
  const cp = spawnSync(bin, ["-B", "-c", probe, PY_SRC], { env: PY_ENV, encoding: "utf8" });
  return cp.status === 0;
});
const PY_WORKER = [
  "import sys",
  "sys.path.insert(0, sys.argv[4])",
  "from styxx_ledger import Ledger",
  "led = Ledger(sys.argv[1], lock_timeout_s=60)",
  "for i in range(int(sys.argv[2])):",
  "    led.append('note', {'worker': sys.argv[3], 'i': i})",
  ""
].join("\n");

test("python and javascript writers appending to one file at once: one chain, both verifiers agree",
  { skip: python ? false : "no python on this box with python/src/styxx_ledger importable and a zone database" }, async t => {
    const { Ledger } = require("../lib/ledger");
    const d = tmpdir(t), f = path.join(d, "mixed.jsonl"), w = path.join(d, "pyw.py");
    fs.writeFileSync(w, PY_WORKER);
    Ledger.init(f, { agent: "mixed", certifies: "two writers, one file.", kinds: ["note", "lock_recovered"], created: "2026-11-08T00:00:00Z" });
    const M = 15;
    const runs = [
      [process.execPath, [path.join(__dirname, "append_worker.js"), f, String(M), "js0"]],
      [process.execPath, [path.join(__dirname, "append_worker.js"), f, String(M), "js1"]],
      [python, ["-B", w, f, String(M), "py0", PY_SRC]],
      [python, ["-B", w, f, String(M), "py1", PY_SRC]]
    ];
    const { spawn } = require("node:child_process");
    const res = await Promise.all(runs.map(([bin, args]) => new Promise((resolve, reject) => {
      const c = spawn(bin, args, { env: PY_ENV, stdio: ["ignore", "ignore", "pipe"] });
      let err = "";
      c.stderr.on("data", b => { err += b; });
      c.on("error", reject);
      c.on("exit", code => resolve({ code, err }));
    })));
    for (const r of res) assert.equal(r.code, 0, r.err);
    const raw = fs.readFileSync(f);
    const r = V.verifyBytesSync(raw);
    assert.equal(r.ok, true, JSON.stringify(r.problems.slice(0, 3)));
    const notes = r.entries.filter(x => x.entry.kind === "note");
    assert.equal(notes.length, 4 * M);
    for (const tag of ["js0", "js1", "py0", "py1"]) assert.equal(notes.filter(x => x.entry.worker === tag).length, M, tag);
    const py = spawnSync(python, ["-B", "-c",
      "import sys, json; sys.path.insert(0, sys.argv[1]); from styxx_ledger import verify_bytes; r = verify_bytes(open(sys.argv[2], 'rb').read()); print(json.dumps({'ok': r['ok'], 'head': r['head']}))",
      PY_SRC, f], { env: PY_ENV, encoding: "utf8" });
    assert.equal(py.status, 0, py.stderr);
    assert.deepEqual(JSON.parse(py.stdout), { ok: true, head: r.head });
  });

test("js_written.jsonl is what the js writer writes now, re-derives, and its anchors hold", () => {
  const cp = spawnSync(process.execPath, [path.join(__dirname, "make_fixture.js"), "--check"], { encoding: "utf8" });
  assert.equal(cp.status, 0, cp.stdout + cp.stderr);
  const raw = fs.readFileSync(path.join(JS_FIXTURES, "js_written.jsonl"));
  const meta = JSON.parse(fs.readFileSync(path.join(JS_FIXTURES, "js_written.json"), "utf8"));
  const r = V.verifyBytesSync(raw);
  assert.equal(r.ok, true);
  assert.equal(raw.toString("utf8").split("\n").filter(Boolean).length, 30);
  assert.equal(r.head, meta.head);
  assert.equal(sha(raw), meta.sha256);
  assert.equal(meta.anchor_texts.length, 5);
  for (const tx of meta.anchor_texts) assert.equal(V.checkAnchor(r.entries, V.parseAnchorText(tx), [], r.header).ok, true, tx);
  assert.equal(r.entries.filter(x => x.entry.kind === "anchor" && x.entry.late).length, 1, "one late anchor");
});
