"use strict";
/* ots.js: an optional OpenTimestamps helper. It shells out to an `ots` client when one is on PATH (for example
   the python opentimestamps-client); this package does not depend on it and never installs it. Nothing in the
   writer or the verifier calls this file.

     stamp(file)  -> {ok: true, proof: "<file>.ots"} | {ok: false, reason}

   `ots stamp` sends the file's sha256 to the public calendars, so it needs the network; the core packages do
   not. A proof made on a later day for an earlier post shows only that the post existed by the stamping day. */
const fs = require("node:fs");
const { spawnSync } = require("node:child_process");

function stamp(file, opts) {
  const bin = (opts && opts.bin) || "ots";
  if (!fs.existsSync(file)) return { ok: false, reason: "no such file: " + file };
  const r = spawnSync(bin, ["stamp", file], { encoding: "utf8", timeout: 30000, shell: false });
  if (r.error && r.error.code === "ENOENT") return { ok: false, reason: "no `" + bin + "` client on PATH (optional; see README)" };
  if (r.error) return { ok: false, reason: String(r.error.message || r.error) };
  if (r.status !== 0) return { ok: false, reason: "`" + bin + " stamp` exited " + r.status + ": " + String(r.stderr || "").trim().slice(0, 300) };
  const proof = file + ".ots";
  return fs.existsSync(proof) ? { ok: true, proof } : { ok: false, reason: "the client ran but wrote no " + proof };
}

module.exports = { stamp };
