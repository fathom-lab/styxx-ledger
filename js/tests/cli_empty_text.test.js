"use strict";
/* the command line on empty text (the lab's improvement sweep of 2026-11-09, rank 67): a flag given empty reaches the
   writer and is refused there, exit 1 with its code, as in the python cli; only a flag not given at all, or an empty
   <log>, is usage (exit 2). an empty --kinds item is refused, never dropped. until then this cli answered
   --certifies "" (and --agent "", --tz "", --kind "") with exit 2, "init needs --agent, --tz and --certifies" for
   flags it had been given, where python refused them with exit 1. python/tests/test_cli_parity.py runs the same
   inputs through both clis. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { BIN, tmpdir } = require("./helpers");

const run = (...args) => {
  const cp = spawnSync(process.execPath, [BIN, ...args], { encoding: "utf8", timeout: 60000 });
  return { code: cp.status, out: cp.stdout, err: cp.stderr };
};
const refused = err => { const m = /refused \(([a-z_]+)\)/.exec(err); return m ? m[1] : null; };
const INIT = ["--agent", "a", "--tz", "UTC", "--certifies", "one line per event.", "--created", "2026-11-01T00:00:00Z", "--timestamp", "2026-11-01T00:00:01Z"];
const initWith = over => { const a = INIT.slice(); for (const k of Object.keys(over)) a[a.indexOf("--" + k) + 1] = over[k]; return a; };

test("init: an empty --certifies, --agent or --tz, or an empty --kinds item, is a refusal (exit 1), and no file is made", t => {
  const d = tmpdir(t);
  const cases = [
    [initWith({ certifies: "" }), "header_form"], [initWith({ certifies: "   " }), "header_form"],
    [initWith({ agent: "" }), "header_form"], [initWith({ tz: "" }), "anchor_tz"],
    [INIT.concat(["--kinds", "note,,send"]), "header_form"], [INIT.concat(["--kinds", ""]), "header_form"],
    [INIT.concat(["--kinds", "note,"]), "header_form"],
  ];
  cases.forEach(([args, code], i) => {
    const f = path.join(d, "c" + i + ".jsonl");
    const r = run("init", f, ...args);
    assert.equal(r.code, 1, args.join(" ") + ": " + r.err);
    assert.equal(refused(r.err), code, r.err);
    assert.equal(fs.existsSync(f), false, args.join(" "));
  });
  const r = run("init", path.join(d, "k.jsonl"), ...INIT.concat(["--kinds", "note,,send"]));
  assert.ok(r.err.includes('--kinds holds an empty item ("note,,send"); give comma-separated kind names, e.g. note,send'), r.err);
});

test("append --kind '' is refused (kind_not_declared); a missing flag and an empty <log> are usage (exit 2)", t => {
  const d = tmpdir(t), f = path.join(d, "a.jsonl");
  assert.equal(run("init", f, ...INIT).code, 0);
  const r = run("append", f, "--kind", "", "--timestamp", "2026-11-01T00:00:02Z");
  assert.equal(r.code, 1, r.err);
  assert.equal(refused(r.err), "kind_not_declared");
  for (const args of [["init", path.join(d, "x.jsonl"), "--agent", "a", "--tz", "UTC"], ["append", f], ["init", "", ...INIT], ["append", "", "--kind", "note"], ["anchor-text", ""]]) {
    const u = run(...args);
    assert.equal(u.code, 2, args.join(" ") + ": " + u.err);
    assert.equal(refused(u.err), null);
  }
  assert.equal(fs.readFileSync(f, "utf8").split("\n").filter(Boolean).length, 2);
});
