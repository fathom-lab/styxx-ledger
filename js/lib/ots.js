"use strict";
/* ots.js: OpenTimestamps proofs, read natively (no opentimestamps library), plus the optional stamping helper.

   Reading a proof (pure; synchronous; no network):

     parseOts(u8)                     -> {file_hash_op, file_digest (hex), tree}; throws OtsError (.code)
     attestations(proof)              -> every leaf: {kind, height | uri | tag+payload, digest (hex), depth}
     summary(proof)                   -> {file_digest, attestations, bitcoin_heights, pending, ...}
     verifyBitcoin(digest, header)    -> {ok, time, merkle_root_expected, reason}; header {merkle_root, timestamp}
     verifyProof(u8, opts)            -> the whole proof; opts {target (bytes) | digest (hex), getHeader(height)}
     verifyProofAsync(u8, opts)       -> the same, with getHeader allowed to return a promise

   A bitcoin attestation holds when the digest at that point of the tree, byte-reversed, is the block's merkle root
   as explorers print it (display order); the header's `timestamp` is then the time the proof attests: the stamped
   bytes existed before that block. Existence before a block, not publication anywhere. Headers come from whoever
   getHeader asks; this file never fetches.

   Serialization (major version 1), limits and refusal codes are the python module's (styxx_ledger/ots.py):
     file      = MAGIC varuint(1) file_hash_op digest timestamp
     timestamp = (0xff branch)* branch;  branch = 0x00 tag(8) varbytes(payload) | op [varbytes(arg)] timestamp
     ops 0xf0 append, 0xf1 prepend, 0xf2 reverse, 0xf3 hexlify, 0x02 sha1, 0x03 ripemd160, 0x08 sha256,
         0x67 keccak256 (implemented here: node:crypto has sha3-256, which pads differently)
     tags bitcoin 0588960d73d71901, pending 83dfe30d2ef90c8e, litecoin 06869a0d73d71b45, else unknown
     codes bad_magic bad_version file_hash_op truncated varuint unknown_op op_arg msg_length result_length
           attestation_payload pending_uri too_deep too_large trailing_bytes ripemd160_unavailable
     the kit's bounds, the same in both: a varuint at most 2^53 - 1 (varuint; attestation_payload inside a payload),
     a bitcoin or litecoin height at most 2^32 - 1 (attestation_payload)

   Stamping: stamp(file) -> {ok: true, proof} | {ok: false, reason}; shells out to an `ots` client when one is on
   PATH (it talks to the public calendars). Nothing in the writer or the verifier calls it. */
const fs = require("node:fs");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

const MAGIC = Buffer.from("004f70656e54696d657374616d7073000050726f6f6600bf89e2e884e89294", "hex");
const MAJOR_VERSION = 1;
const TAG_BITCOIN = "0588960d73d71901";
const TAG_PENDING = "83dfe30d2ef90c8e";
const TAG_LITECOIN = "06869a0d73d71b45";
const MAX_MSG = 4096, MAX_RESULT = 4096, MAX_PAYLOAD = 8192, MAX_URI = 1000, MAX_DEPTH = 256, MAX_NODES = 200000;
const MAX_HEIGHT = 0xffffffff;   // the kit's bound on a bitcoin / litecoin height (python's MAX_HEIGHT); varuints stop at 2^53 - 1
const URI_RX = /^[A-Za-z0-9\-._/:]*$/;
const OP_NAMES = { 0xf0: "append", 0xf1: "prepend", 0xf2: "reverse", 0xf3: "hexlify", 0x02: "sha1", 0x03: "ripemd160", 0x08: "sha256", 0x67: "keccak256" };
const HASH_LEN = { 0x02: 20, 0x03: 20, 0x08: 32, 0x67: 32 };
const OP_BY_NAME = Object.fromEntries(Object.entries(OP_NAMES).map(([k, v]) => [v, Number(k)]));

class OtsError extends Error {
  constructor(code, message, offset) { super(message); this.name = "OtsError"; this.code = code; this.offset = offset === undefined ? null : offset; }
}

const hex = u8 => Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength).toString("hex");
const fromHex = h => new Uint8Array(Buffer.from(h, "hex"));
function toU8(b) {
  if (b instanceof Uint8Array) return b;
  if (b instanceof ArrayBuffer) return new Uint8Array(b);
  if (typeof b === "string") return new Uint8Array(Buffer.from(b, "utf8"));
  throw new TypeError("expected bytes (Uint8Array, Buffer, ArrayBuffer)");
}

// --------------------------------------------------------------------------------------------- hashing

let ripemdKnown = null;
function ripemd160Available() {
  if (ripemdKnown === null) {
    try { crypto.createHash("ripemd160").update("").digest(); ripemdKnown = true; } catch (e) { ripemdKnown = false; }
  }
  return ripemdKnown;
}

const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808An, 0x8000000080008000n, 0x000000000000808Bn,
  0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n, 0x000000000000008An, 0x0000000000000088n,
  0x0000000080008009n, 0x000000008000000An, 0x000000008000808Bn, 0x800000000000008Bn, 0x8000000000008089n,
  0x8000000000008003n, 0x8000000000008002n, 0x8000000000000080n, 0x000000000000800An, 0x800000008000000An,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n
];
const ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]];
const M64 = (1n << 64n) - 1n;
const rotl = (v, r) => (r === 0 ? v : ((v << BigInt(r)) | (v >> BigInt(64 - r))) & M64);
function keccakF(a) {
  for (const rc of RC) {
    const c = [0, 1, 2, 3, 4].map(x => a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4]);
    const d = [0, 1, 2, 3, 4].map(x => c[(x + 4) % 5] ^ rotl(c[(x + 1) % 5], 1));
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) a[x][y] ^= d[x];
    const b = [0, 1, 2, 3, 4].map(() => [0n, 0n, 0n, 0n, 0n]);
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) b[y][(2 * x + 3 * y) % 5] = rotl(a[x][y], ROT[x][y]);
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y] & M64) & b[(x + 2) % 5][y]);
    a[0][0] ^= rc;
  }
}
/* Keccak-256 as Ethereum and opentimestamps use it (padding 0x01 ... 0x80, rate 136), not SHA3-256. */
function keccak256(msg) {
  const m = toU8(msg), rate = 136;
  const len = (Math.floor((m.length + 1) / rate) + ((m.length + 1) % rate ? 1 : 0)) * rate;
  const p = new Uint8Array(len);
  p.set(m); p[m.length] ^= 0x01; p[len - 1] ^= 0x80;
  const a = [0, 1, 2, 3, 4].map(() => [0n, 0n, 0n, 0n, 0n]);
  const dv = new DataView(p.buffer);
  for (let off = 0; off < len; off += rate) {
    for (let i = 0; i < rate / 8; i++) a[i % 5][Math.floor(i / 5)] ^= dv.getBigUint64(off + 8 * i, true);
    keccakF(a);
  }
  const out = new Uint8Array(32), ov = new DataView(out.buffer);
  for (let i = 0; i < 4; i++) ov.setBigUint64(8 * i, a[i % 5][Math.floor(i / 5)], true);
  return out;
}

function hashOp(tag, msg) {
  if (tag === 0x08) return new Uint8Array(crypto.createHash("sha256").update(msg).digest());
  if (tag === 0x02) return new Uint8Array(crypto.createHash("sha1").update(msg).digest());
  if (tag === 0x03) {
    if (!ripemd160Available()) throw new OtsError("ripemd160_unavailable", "this node's crypto has no ripemd160; the proof needs it, so it is not read");
    return new Uint8Array(crypto.createHash("ripemd160").update(msg).digest());
  }
  if (tag === 0x67) return keccak256(msg);
  throw new OtsError("unknown_op", "not a hash op: 0x" + tag.toString(16));
}

function concat(a, b) { const o = new Uint8Array(a.length + b.length); o.set(a); o.set(b, a.length); return o; }

/* The op's result on msg, under the libraries' length limits. */
function applyOp(tag, arg, msg) {
  if (tag === 0xf3) {
    if (msg.length < 1 || msg.length > MAX_RESULT / 2) throw new OtsError("msg_length", "hexlify takes 1.." + (MAX_RESULT / 2) + " bytes, got " + msg.length);
    return new Uint8Array(Buffer.from(hex(msg), "ascii"));
  }
  if (msg.length > MAX_MSG) throw new OtsError("msg_length", "message of " + msg.length + " bytes exceeds " + MAX_MSG);
  let r;
  if (tag === 0xf0) r = concat(msg, arg);
  else if (tag === 0xf1) r = concat(arg, msg);
  else if (tag === 0xf2) {
    if (!msg.length) throw new OtsError("msg_length", "reverse of an empty message");
    r = Uint8Array.from(msg).reverse();
  } else r = hashOp(tag, msg);
  if (r.length > MAX_RESULT) throw new OtsError("result_length", "result of " + r.length + " bytes exceeds " + MAX_RESULT);
  return r;
}

// --------------------------------------------------------------------------------------------- reading

class Reader {
  constructor(b, i) { this.b = b; this.i = i || 0; }
  byte() { if (this.i >= this.b.length) throw new OtsError("truncated", "the proof ends early", this.i); return this.b[this.i++]; }
  take(n) {
    if (this.i + n > this.b.length) throw new OtsError("truncated", "the proof ends early (wanted " + n + " bytes)", this.i);
    const v = this.b.subarray(this.i, this.i + n); this.i += n; return v;
  }
  varuint() {
    const start = this.i;
    let value = 0n, shift = 0n;
    for (;;) {
      const c = this.byte();
      value |= BigInt(c & 0x7f) << shift;
      if (!(c & 0x80)) break;
      shift += 7n;
      if (shift > 63n) throw new OtsError("varuint", "a varuint longer than 9 bytes", start);
    }
    if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new OtsError("varuint", "a varuint above 2^53", start);
    return Number(value);
  }
  varbytes(maxLen, minLen, code) {
    const at = this.i, n = this.varuint();
    if (n > maxLen || n < (minLen || 0)) throw new OtsError(code || "truncated", "varbytes of " + n + " bytes outside " + (minLen || 0) + ".." + maxLen, at);
    return this.take(n);
  }
  eof() { return this.i >= this.b.length; }
}

function readAttestation(r) {
  const at = r.i;
  const tag = hex(r.take(8));
  const payload = r.varbytes(MAX_PAYLOAD, 0, "attestation_payload");
  const p = new Reader(payload);
  let out;
  try {
    if (tag === TAG_BITCOIN || tag === TAG_LITECOIN) {
      out = { kind: tag === TAG_BITCOIN ? "bitcoin" : "litecoin", height: p.varuint() };
      if (out.height > MAX_HEIGHT) throw new OtsError("attestation_payload", "a block height above 2^32 - 1 (" + out.height + ")", at);
    }
    else if (tag === TAG_PENDING) {
      const uri = p.varbytes(MAX_URI, 0, "pending_uri");
      const s = Buffer.from(uri).toString("latin1");
      if (!URI_RX.test(s)) throw new OtsError("pending_uri", "a pending uri with a character outside [A-Za-z0-9-._/:]", at);
      out = { kind: "pending", uri: s };
    } else return { kind: "unknown", tag, payload: hex(payload) };
  } catch (e) {
    if (e instanceof OtsError && (e.code === "truncated" || e.code === "varuint")) throw new OtsError("attestation_payload", "attestation payload unreadable: " + e.message, at);
    throw e;
  }
  if (!p.eof()) throw new OtsError("attestation_payload", "bytes left over in a " + out.kind + " attestation's payload", at);
  return out;
}

function node(msg, depth) { return { msg, depth, attestations: [], ops: [] }; }

/* Iterative: a node stays on the stack until its last (un-prefixed) branch begins. */
function parseTimestamp(r, msg) {
  const root = node(msg, 0), stack = [root];
  let nodes = 1;
  while (stack.length) {
    const n = stack[stack.length - 1];
    const tag = r.byte();
    let cur;
    if (tag === 0xff) cur = r.byte(); else { cur = tag; stack.pop(); }
    if (cur === 0x00) { n.attestations.push(readAttestation(r)); continue; }
    const at = r.i - 1;
    if (!(cur in OP_NAMES)) throw new OtsError("unknown_op", "unknown op tag 0x" + cur.toString(16).padStart(2, "0"), at);
    let arg = null;
    if (cur === 0xf0 || cur === 0xf1) arg = r.varbytes(MAX_RESULT, 1, "op_arg");
    if (n.depth + 1 > MAX_DEPTH) throw new OtsError("too_deep", "ops nested deeper than " + MAX_DEPTH, at);
    let res;
    try { res = applyOp(cur, arg, n.msg); } catch (e) { if (e instanceof OtsError && e.offset === null) e.offset = at; throw e; }
    if (++nodes > MAX_NODES) throw new OtsError("too_large", "more than " + MAX_NODES + " nodes", at);
    const child = node(res, n.depth + 1);
    n.ops.push([{ op: OP_NAMES[cur], tag: cur, arg }, child]);
    stack.push(child);
  }
  return root;
}

/* {file_hash_op, file_digest (hex), tree}. Throws OtsError on anything the libraries would not read. */
function parseOts(data) {
  const b = toU8(data);
  if (b.length < MAGIC.length || !Buffer.from(b.buffer, b.byteOffset, MAGIC.length).equals(MAGIC)) {
    throw new OtsError("bad_magic", "not an OpenTimestamps proof (magic header missing)", 0);
  }
  const r = new Reader(b, MAGIC.length);
  const ver = r.varuint();
  if (ver !== MAJOR_VERSION) throw new OtsError("bad_version", "proof major version " + ver + "; this reader knows " + MAJOR_VERSION, MAGIC.length);
  const at = r.i, op = r.byte();
  if (!(op in HASH_LEN)) throw new OtsError("file_hash_op", "file hash op 0x" + op.toString(16) + " is not a hash op", at);
  const digest = r.take(HASH_LEN[op]);
  const tree = parseTimestamp(r, Uint8Array.from(digest));
  if (!r.eof()) throw new OtsError("trailing_bytes", (b.length - r.i) + " bytes after the proof", r.i);
  return { file_hash_op: OP_NAMES[op], file_digest: hex(digest), tree };
}

/* Every node in serialization order (depth first). */
function walk(proof) {
  const out = [], stack = [proof.tree];
  while (stack.length) {
    const n = stack.pop();
    out.push(n);
    for (let i = n.ops.length - 1; i >= 0; i--) stack.push(n.ops[i][1]);
  }
  return out;
}

function attestations(proof) {
  const out = [];
  for (const n of walk(proof)) for (const a of n.attestations) out.push(Object.assign({}, a, { digest: hex(n.msg), depth: n.depth }));
  return out;
}

function summary(proof) {
  const atts = attestations(proof);
  const uniqSort = xs => Array.from(new Set(xs)).sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));
  return {
    file_hash_op: proof.file_hash_op, file_digest: proof.file_digest, attestations: atts.length,
    bitcoin_heights: uniqSort(atts.filter(a => a.kind === "bitcoin").map(a => a.height)),
    pending: uniqSort(atts.filter(a => a.kind === "pending").map(a => a.uri)),
    litecoin_heights: uniqSort(atts.filter(a => a.kind === "litecoin").map(a => a.height)),
    unknown: atts.filter(a => a.kind === "unknown").length
  };
}

// ------------------------------------------------------------------------------------------- verifying

const asBytes = d => (typeof d === "string" ? fromHex(d) : toU8(d));
/* The merkle root (display-order hex, as explorers print it) a bitcoin attestation on `digest` claims. */
function expectedMerkleRoot(digest) { return hex(Uint8Array.from(asBytes(digest)).reverse()); }

/* {ok, time, merkle_root_expected, reason}. header: {merkle_root (display hex), timestamp (unix s)}. */
function verifyBitcoin(digest, header) {
  const d = asBytes(digest), want = expectedMerkleRoot(d);
  if (d.length !== 32) return { ok: false, time: null, merkle_root_expected: want, reason: "the attested digest is " + d.length + " bytes, not 32" };
  if (!header || typeof header !== "object" || typeof header.merkle_root !== "string") return { ok: false, time: null, merkle_root_expected: want, reason: "no block header with a merkle_root" };
  if (header.merkle_root.toLowerCase() !== want) return { ok: false, time: null, merkle_root_expected: want, reason: "the digest does not match the block's merkle root" };
  const t = header.timestamp !== undefined ? header.timestamp : header.time;
  if (!Number.isInteger(t)) return { ok: false, time: null, merkle_root_expected: want, reason: "the block header has no integer timestamp" };
  return { ok: true, time: t, merkle_root_expected: want, reason: null };
}

function startReport(data, opts) {
  const out = { ok: false, status: null, code: null, reason: null, file_hash_op: null, file_digest: null, commits: null, attestations: [], bitcoin: [], pending: [], lowest: null };
  let proof;
  try { proof = parseOts(data); } catch (e) {
    if (!(e instanceof OtsError)) throw e;
    Object.assign(out, { status: "refused", code: e.code, reason: e.message });
    return { out, done: true };
  }
  out.file_hash_op = proof.file_hash_op; out.file_digest = proof.file_digest;
  const atts = attestations(proof);
  out.attestations = atts;
  out.pending = Array.from(new Set(atts.filter(a => a.kind === "pending").map(a => a.uri))).sort();
  let want = null;
  if (opts.target !== undefined && opts.target !== null) {
    try { want = hex(hashOp(OP_BY_NAME[proof.file_hash_op], toU8(opts.target))); } catch (e) {
      if (!(e instanceof OtsError)) throw e;
      Object.assign(out, { status: "refused", code: e.code, reason: e.message });
      return { out, done: true };
    }
  } else if (typeof opts.digest === "string") want = opts.digest.toLowerCase();
  if (want !== null) {
    out.commits = want === proof.file_digest;
    if (!out.commits) { Object.assign(out, { status: "commitment_mismatch", reason: "the proof commits to " + proof.file_digest + ", not " + want }); return { out, done: true }; }
  }
  return { out, done: false, atts };
}

function bitcoinRecord(a, hd) {
  if (hd && typeof hd === "object" && typeof hd.merkle_root === "string") {
    const v = verifyBitcoin(a.digest, hd);
    return { height: a.height, digest: a.digest, merkle_root_expected: v.merkle_root_expected, merkle_root: hd.merkle_root, verified: v.ok, time: v.time, reason: v.reason };
  }
  return { height: a.height, digest: a.digest, merkle_root_expected: expectedMerkleRoot(a.digest), merkle_root: null, verified: null, time: null, reason: hd && hd.error ? hd.error : "no header" };
}

function finish(out) {
  const good = out.bitcoin.filter(b => b.verified === true), bad = out.bitcoin.filter(b => b.verified === false);
  if (good.length) {
    const lo = good.slice().sort((x, y) => x.height - y.height || x.time - y.time)[0];
    out.lowest = { height: lo.height, time: lo.time };
  }
  if (bad.length) Object.assign(out, { status: "failed", reason: bad.length + " of " + out.bitcoin.length + " bitcoin attestations do not match their block header" });
  else if (good.length) Object.assign(out, { status: "verified", ok: true });
  else if (out.bitcoin.length) Object.assign(out, { status: "unverified", reason: "no block header for any of " + out.bitcoin.length + " bitcoin attestations" });
  else if (out.pending.length) Object.assign(out, { status: "pending", reason: "calendar receipts only; no bitcoin attestation yet" });
  else Object.assign(out, { status: "no_attestation", reason: "no bitcoin or pending attestation" });
  return out;
}

/* Read a proof and check what it says. opts: target (the stamped bytes; the proof must commit to their hash under
   its file hash op) or digest (hex; a witness proof commits to an entry_id this way); getHeader(height) ->
   {merkle_root, timestamp} | null | {error}, called once per distinct height (a throw is that height's error).
   status: refused (`code`), commitment_mismatch, failed, verified, unverified, pending, no_attestation; ok is
   status === "verified". Same rules as styxx_ledger.ots.verify_proof. */
function verifyProof(data, opts) {
  const o = opts || {};
  const s = startReport(data, o);
  if (s.done) return s.out;
  const headers = new Map();
  for (const a of s.atts) {
    if (a.kind !== "bitcoin") continue;
    if (!headers.has(a.height)) {
      let hd;
      if (typeof o.getHeader !== "function") hd = { error: "no header source given" };
      else {
        try { hd = o.getHeader(a.height) || { error: "no header for block " + a.height }; } catch (e) { hd = { error: (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e) }; }
        if (hd && typeof hd.then === "function") throw new TypeError("getHeader returned a promise: use verifyProofAsync");
      }
      headers.set(a.height, hd);
    }
    s.out.bitcoin.push(bitcoinRecord(a, headers.get(a.height)));
  }
  return finish(s.out);
}

async function verifyProofAsync(data, opts) {
  const o = opts || {};
  const s = startReport(data, o);
  if (s.done) return s.out;
  const headers = new Map();
  for (const a of s.atts) {
    if (a.kind !== "bitcoin") continue;
    if (!headers.has(a.height)) {
      let hd;
      if (typeof o.getHeader !== "function") hd = { error: "no header source given" };
      else {
        try { hd = (await o.getHeader(a.height)) || { error: "no header for block " + a.height }; } catch (e) { hd = { error: (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e) }; }
      }
      headers.set(a.height, hd);
    }
    s.out.bitcoin.push(bitcoinRecord(a, headers.get(a.height)));
  }
  return finish(s.out);
}

// -------------------------------------------------------------------------------------------- stamping

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

module.exports = {
  MAGIC, MAJOR_VERSION, TAG_BITCOIN, TAG_PENDING, TAG_LITECOIN, MAX_DEPTH, OP_NAMES, OtsError,
  ripemd160Available, keccak256, applyOp, parseOts, walk, attestations, summary, expectedMerkleRoot, verifyBitcoin,
  verifyProof, verifyProofAsync, stamp
};
