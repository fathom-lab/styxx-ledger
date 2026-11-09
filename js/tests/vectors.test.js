"use strict";
/* the shared vectors: ../vectors/run_vectors.mjs against lib/verify.js must answer every vector as the file says. */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { VECTORS, JS_ROOT } = require("./helpers");

test("run_vectors.mjs: k of n vectors answered as the file says, k == n", () => {
  const cp = spawnSync(process.execPath, [path.join(VECTORS, "run_vectors.mjs"), "--verify", path.join(JS_ROOT, "lib", "verify.js")],
    { encoding: "utf8", timeout: 120000 });
  const m = /(\d+) of (\d+) vectors answered as the file says/.exec(cp.stdout);
  assert.ok(m, "no tally line: " + cp.stdout + cp.stderr);
  console.log("# " + m[0] + " (js/lib/verify.js, node " + process.versions.node + ", " + process.platform + ")");
  assert.equal(m[1], m[2], cp.stdout);
  assert.equal(cp.status, 0, cp.stdout);
  assert.ok(Number(m[2]) >= 80, "the vectors file shrank: " + m[2]);
});
