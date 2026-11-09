"use strict";
/* the native OpenTimestamps reader (lib/ots.js) against the 14 anchor proofs and 22 sampled witness proofs of
   darkflobi's exhibit (vectors/ots/), offline, with the block headers captured from two explorers; every height,
   attested time and digest must equal what javascript-opentimestamps 0.4.9 said of the same files (expect.json). */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const O = require("../lib/ots.js");
const { VECTORS } = require("./helpers");

const DIR = path.join(VECTORS, "ots");
const EXPECT = JSON.parse(fs.readFileSync(path.join(DIR, "expect.json"), "utf8"));
const HEADERS = JSON.parse(fs.readFileSync(path.join(DIR, "block_headers.json"), "utf8")).blocks;
const FILES = Object.keys(EXPECT.files).sort();
const ANCHORS = FILES.filter(f => f.startsWith("anchors/"));
const WITNESS = FILES.filter(f => f.startsWith("witness/"));
const read = f => fs.readFileSync(path.join(DIR, f));
const getHeader = h => (HEADERS[String(h)] ? { merkle_root: HEADERS[String(h)].header.merkle_root, timestamp: HEADERS[String(h)].header.timestamp } : null);
const norm = atts => atts.map(a => JSON.stringify(Object.fromEntries(["digest", "height", "kind", "uri"].filter(k => k in a).map(k => [k, a[k]])))).sort();
const entryOf = f => f.split("/")[1].slice(0, -4);

function checkAgainst(f, rep) {
  const exp = EXPECT.files[f];
  assert.equal(rep.file_digest, exp.file_digest);
  assert.equal(rep.status, exp.status, rep.reason);
  assert.deepEqual(norm(rep.attestations), norm(exp.attestations));
  const got = rep.bitcoin.map(b => [b.height, b.time, b.digest].join(" ")).sort();
  const want = exp.attestations.filter(a => a.kind === "bitcoin").map(a => [a.height, a.time, a.digest].join(" ")).sort();
  assert.deepEqual(got, want);
  assert.deepEqual(rep.lowest, exp.lowest);
}

test("fixture counts: 14 anchors, 22 witness proofs, 14 headers both explorers agreed on", () => {
  assert.equal(ANCHORS.length, 14);
  assert.equal(WITNESS.length, 22);
  assert.equal(Object.keys(HEADERS).length, 14);
  assert.ok(Object.values(HEADERS).every(b => b.mempool_space_agrees === true));
});

test("the 14 anchor proofs verify offline exactly as the library said", () => {
  for (const f of ANCHORS) {
    const rep = O.verifyProof(read(f), { target: read(EXPECT.files[f].target), getHeader });
    assert.ok(rep.ok && rep.commits === true, f + " " + rep.status);
    checkAgainst(f, rep);
    assert.equal(rep.attestations.filter(a => a.kind === "bitcoin").length, 4, f);
    assert.equal(rep.pending.length, 4, f);
  }
});

test("anchor lowest heights are the shelf's: 974530 x11, 974635, 974768, 975028", () => {
  const lows = ANCHORS.map(f => O.verifyProof(read(f), { getHeader }).lowest.height);
  assert.deepEqual(Array.from(new Set(lows)).sort(), [974530, 974635, 974768, 975028]);
  assert.equal(lows.filter(h => h === 974530).length, 11);
});

test("the 22 witness proofs commit to their entry_id and verify as the library said", () => {
  for (const f of WITNESS) {
    const rep = O.verifyProof(read(f), { digest: entryOf(f), getHeader });
    assert.equal(rep.commits, true, f);
    checkAgainst(f, rep);
  }
});

test("a pending-only witness proof reports pending", () => {
  const pend = WITNESS.filter(f => EXPECT.files[f].status === "pending");
  assert.equal(pend.length, 2);
  for (const f of pend) {
    const rep = O.verifyProof(read(f), { digest: entryOf(f), getHeader });
    assert.equal(rep.status, "pending"); assert.equal(rep.ok, false); assert.equal(rep.bitcoin.length, 0); assert.equal(rep.pending.length, 4);
  }
});

test("verifyProofAsync agrees with verifyProof, with a promise-returning header source", async () => {
  for (const f of [ANCHORS[0], ANCHORS[13], WITNESS[0]]) {
    const opts = f.startsWith("anchors/") ? { target: read(EXPECT.files[f].target) } : { digest: entryOf(f) };
    const a = O.verifyProof(read(f), Object.assign({ getHeader }, opts));
    const b = await O.verifyProofAsync(read(f), Object.assign({ getHeader: async h => getHeader(h) }, opts));
    assert.deepEqual(b, a);
  }
  assert.throws(() => O.verifyProof(read(ANCHORS[0]), { getHeader: async h => getHeader(h) }), /verifyProofAsync/);
});

test("a flipped byte in the path fails every bitcoin attestation", () => {
  const f = ANCHORS[0];
  const data = Buffer.from(read(f));
  const firstOp = O.MAGIC.length + 1 + 1 + 32;
  assert.equal(data[firstOp], 0xf0); assert.equal(data[firstOp + 1], 16);
  data[firstOp + 2] ^= 0x01;
  const rep = O.verifyProof(data, { target: read(EXPECT.files[f].target), getHeader });
  assert.equal(rep.status, "failed"); assert.equal(rep.ok, false);
  assert.equal(rep.bitcoin.length, 4); assert.ok(rep.bitcoin.every(b => b.verified === false));
});

test("a flipped text byte, or another entry's digest, is a commitment mismatch", () => {
  const f = ANCHORS[0];
  const t = Buffer.from(read(EXPECT.files[f].target)); t[0] ^= 0x20;
  const r1 = O.verifyProof(read(f), { target: t, getHeader });
  assert.equal(r1.status, "commitment_mismatch"); assert.equal(r1.commits, false);
  const r2 = O.verifyProof(read(WITNESS[0]), { digest: entryOf(WITNESS[1]), getHeader });
  assert.equal(r2.status, "commitment_mismatch");
});

test("no header source is unverified; a throwing source records its error; a wrong header fails", () => {
  assert.equal(O.verifyProof(read(ANCHORS[0])).status, "unverified");
  const r = O.verifyProof(read(ANCHORS[0]), { getHeader: () => { throw new Error("net down"); } });
  assert.equal(r.status, "unverified"); assert.match(r.bitcoin[0].reason, /net down/);
  assert.equal(O.verifyProof(read(ANCHORS[0]), { getHeader: () => ({ merkle_root: "00".repeat(32), timestamp: 1 }) }).status, "failed");
});

// ---------------------------------------------------------------------------------------- synthetic proofs
function vu(n) { const o = []; for (;;) { const b = n & 0x7f; n = Math.floor(n / 128); if (n) o.push(b | 0x80); else { o.push(b); return Buffer.from(o); } } }
const vb = b => Buffer.concat([vu(b.length), Buffer.from(b)]);
const btc = h => Buffer.concat([Buffer.from([0]), Buffer.from(O.TAG_BITCOIN, "hex"), vb(vu(h))]);
const pending = uri => Buffer.concat([Buffer.from([0]), Buffer.from(O.TAG_PENDING, "hex"), vb(vb(Buffer.from(uri, "ascii")))]);
const proof = (body, digest, op) => Buffer.concat([O.MAGIC, Buffer.from([1, op || 0x08]), digest || Buffer.alloc(32, 0x11), body]);
const H = (alg, b) => crypto.createHash(alg).update(b).digest();

test("every op, keccak256 included (the original padding, not sha3-256)", () => {
  const hx = u => Buffer.from(u).toString("hex");
  assert.equal(hx(O.keccak256(new Uint8Array(0))), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470");
  assert.equal(hx(O.keccak256(Buffer.from("abc"))), "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45");
  assert.equal(hx(O.keccak256(Buffer.from("a".repeat(200)))), "96ea54061def936c4be90b518992fdc6f12f535068a256229aca54267b4d084d");
  // the rate edge (135 and 136 bytes); the values were checked against pycryptodome's keccak
  assert.equal(hx(O.keccak256(Buffer.alloc(135, 1))), "3c172af358851e71c45d39b53a91bb503e72de2548ea55caedbb5202f6d34bdb");
  assert.equal(hx(O.keccak256(Buffer.alloc(136, 1))), "782165b181823a770bd1c5d6c0b5e7c5f1b53e91da289c27b3622c49fcb91402");
  const d = Buffer.alloc(32, 0x11);
  let m = Buffer.concat([d, Buffer.from([0xaa])]);
  m = Buffer.concat([Buffer.from([0xbb, 0xcc]), m]);
  m = Buffer.from(m).reverse();
  m = Buffer.from(m.toString("hex"), "ascii");
  m = H("sha1", m); m = H("ripemd160", m); m = Buffer.from(O.keccak256(m)); m = H("sha256", m);
  const body = Buffer.concat([Buffer.from([0xf0]), vb([0xaa]), Buffer.from([0xf1]), vb([0xbb, 0xcc]), Buffer.from([0xf2, 0xf3, 0x02, 0x03, 0x67, 0x08]), btc(800000)]);
  const hdr = { merkle_root: Buffer.from(m).reverse().toString("hex"), timestamp: 1700000000 };
  const rep = O.verifyProof(proof(body), { digest: d.toString("hex"), getHeader: h => (h === 800000 ? hdr : null) });
  assert.equal(rep.status, "verified"); assert.deepEqual(rep.lowest, { height: 800000, time: 1700000000 });
  assert.equal(rep.attestations[0].depth, 8);
});

test("forks, pending-only, unknown and litecoin attestations", () => {
  const body = Buffer.concat([Buffer.from([0xff]), pending("https://a.example.org"), Buffer.from([0x08]), pending("https://b.example.org")]);
  const rep = O.verifyProof(proof(body));
  assert.equal(rep.status, "pending"); assert.deepEqual(rep.pending, ["https://a.example.org", "https://b.example.org"]);
  assert.equal(O.summary(O.parseOts(proof(body))).attestations, 2);
  const body2 = Buffer.concat([Buffer.from([0xff, 0x00]), Buffer.from("0102030405060708", "hex"), vb(Buffer.from("xyz")), Buffer.from([0]), Buffer.from(O.TAG_LITECOIN, "hex"), vb(vu(5))]);
  const r2 = O.verifyProof(proof(body2));
  assert.deepEqual(r2.attestations.map(a => a.kind).sort(), ["litecoin", "unknown"]);
  assert.equal(r2.status, "no_attestation");
});

test("refusals carry a code", () => {
  const cases = [
    [Buffer.from("not a proof"), "bad_magic"],
    [Buffer.concat([O.MAGIC, Buffer.from([2, 8]), Buffer.alloc(32, 0x11), Buffer.from([0])]), "bad_version"],
    [Buffer.concat([O.MAGIC, Buffer.from([1, 0xf0]), Buffer.alloc(32, 0x11)]), "file_hash_op"],
    [Buffer.concat([O.MAGIC, Buffer.from([1, 8]), Buffer.alloc(10, 0x11)]), "truncated"],
    [proof(Buffer.concat([Buffer.from([0x99]), btc(1)])), "unknown_op"],
    [proof(Buffer.concat([Buffer.from([0xf0, 0x00]), btc(1)])), "op_arg"],
    [proof(Buffer.concat([btc(1), Buffer.from([0])])), "trailing_bytes"],
    [proof(Buffer.concat([Buffer.from([0]), Buffer.from(O.TAG_BITCOIN, "hex"), vb(Buffer.concat([vu(1), Buffer.from([0])]))])), "attestation_payload"],
    [proof(Buffer.concat([Buffer.from([0]), Buffer.from(O.TAG_PENDING, "hex"), vb(vb(Buffer.from("https://a b")))])), "pending_uri"],
    [proof(Buffer.concat([Buffer.alloc(257, 0x08), btc(1)])), "too_deep"],
    [proof(Buffer.concat([Buffer.from([0xf0]), vb(Buffer.alloc(4096)), btc(1)])), "result_length"],
    [proof(Buffer.concat([Buffer.from([0]), Buffer.from(O.TAG_BITCOIN, "hex"), vb(Buffer.alloc(10, 0xff))])), "attestation_payload"]
  ];
  for (const [data, code] of cases) {
    assert.throws(() => O.parseOts(data), e => e instanceof O.OtsError && e.code === code, code);
    const rep = O.verifyProof(data);
    assert.equal(rep.status, "refused", code); assert.equal(rep.code, code); assert.equal(rep.ok, false);
  }
  assert.equal(O.verifyProof(proof(Buffer.concat([Buffer.alloc(256, 0x08), btc(1)]))).status, "unverified", "depth 256 is read");
});

test("verifyBitcoin edges", () => {
  const d = Buffer.from(Array.from({ length: 32 }, (_, i) => i));
  const rev = Buffer.from(d).reverse().toString("hex");
  const ok = O.verifyBitcoin(d, { merkle_root: rev.toUpperCase(), timestamp: 5 });
  assert.equal(ok.ok, true); assert.equal(ok.time, 5);
  assert.equal(O.expectedMerkleRoot(d), rev);
  assert.equal(O.verifyBitcoin(d, null).ok, false);
  assert.equal(O.verifyBitcoin(d.subarray(0, 20), { merkle_root: Buffer.from(d.subarray(0, 20)).reverse().toString("hex"), timestamp: 5 }).ok, false);
  assert.equal(O.verifyBitcoin(d, { merkle_root: rev, timestamp: "5" }).ok, false);
});

test("ripemd160 is available in this node (recorded, not assumed)", () => {
  assert.equal(O.ripemd160Available(), true);
});

/* crafted proofs (review 3e): the javascript reader answers what crafted.json says, as the python reader must */
const CRAFTED = JSON.parse(fs.readFileSync(path.join(DIR, "crafted", "crafted.json"), "utf8"));

test("crafted proofs answer as crafted.json says (the same file the python suite reads)", () => {
  for (const name of Object.keys(CRAFTED).sort()) {
    const c = CRAFTED[name];
    const data = fs.readFileSync(path.join(DIR, "crafted", c.file));
    assert.equal(crypto.createHash("sha256").update(data).digest("hex"), c.sha256, name);
    if (c.expect.status === "refused") {
      assert.throws(() => O.parseOts(data), e => e instanceof O.OtsError && e.code === c.expect.code, name);
    } else {
      const got = O.attestations(O.parseOts(data)).map(a => [a.kind, a.height !== undefined ? a.height : a.uri]);
      assert.deepEqual(got, c.expect.attestations, name);
    }
  }
});

test("a huge height is refused before any header is asked", () => {
  const asked = [];
  const rep = O.verifyProof(fs.readFileSync(path.join(DIR, "crafted", "height_2p60.ots")), { getHeader: h => { asked.push(h); return null; } });
  assert.equal(rep.status, "refused"); assert.equal(rep.code, "attestation_payload"); assert.deepEqual(asked, []);
});
