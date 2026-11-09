"use strict";
/* packaging (improvements 2026-11-09, ranks 46 and 65): the npm tarball carries the MIT text and nothing from tests/,
   and package.json carries the registry fields. what the tarball holds is npm's answer, not ours: `npm pack
   --dry-run --json` (it writes nothing) in js/; that test skips when npm does not run here. */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const JS_ROOT = path.join(__dirname, "..");
const REPO = path.join(JS_ROOT, "..");
const REPO_URL = "https://github.com/fathom-lab/styxx-ledger";
const pkg = JSON.parse(fs.readFileSync(path.join(JS_ROOT, "package.json"), "utf8"));

function walk(dir, rel) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const r = rel + "/" + e.name;
    if (e.isDirectory()) out.push(...walk(path.join(dir, e.name), r));
    else out.push(r);
  }
  return out;
}

test("js/LICENSE is the MIT text, a byte copy of the repository's LICENSE, and package.json lists it", () => {
  const mine = fs.readFileSync(path.join(JS_ROOT, "LICENSE"));
  assert.ok(mine.toString("latin1").startsWith("MIT License\n"));
  const root = path.join(REPO, "LICENSE");
  if (fs.existsSync(root)) assert.ok(mine.equals(fs.readFileSync(root)), "js/LICENSE differs from the repository's LICENSE");
  assert.ok(pkg.files.includes("LICENSE"), "files does not list LICENSE");
  assert.equal(pkg.license, "MIT");
});

test("package.json carries the registry fields: repository, homepage, bugs, author, engines, keywords", () => {
  assert.equal(pkg.repository.url, REPO_URL + ".git");
  assert.equal(pkg.repository.directory, "js");
  assert.ok(pkg.homepage.startsWith(REPO_URL + "/"), pkg.homepage);
  assert.equal(pkg.bugs.url, REPO_URL + "/issues");
  assert.equal(typeof pkg.author, "string");
  assert.ok(pkg.author.length > 0, "no author");
  assert.equal(pkg.engines.node, ">=20");
  for (const k of ["hash-chain", "append-only", "tamper-evident", "opentimestamps"]) assert.ok(pkg.keywords.includes(k), k);
});

test("npm pack carries LICENSE, README.md, package.json, lib/ and bin/, and nothing else", t => {
  const r = spawnSync("npm pack --dry-run --json", { cwd: JS_ROOT, shell: true, encoding: "utf8", timeout: 120000 });
  if (r.error || r.status !== 0) {
    t.skip("npm pack did not run here (" + (r.error ? r.error.message : "exit " + r.status) + ")");
    return;
  }
  const got = JSON.parse(r.stdout)[0].files.map(f => f.path.replace(/\\/g, "/")).sort();
  const want = ["LICENSE", "README.md", "package.json", ...walk(path.join(JS_ROOT, "lib"), "lib"),
    ...walk(path.join(JS_ROOT, "bin"), "bin")].sort();
  assert.deepEqual(got, want);
  assert.ok(!got.some(f => f.startsWith("tests/")), "the tarball carries tests/");
});
