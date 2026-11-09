"""ots.py: OpenTimestamps proofs, read natively (no opentimestamps library), plus the optional stamping helper.

Reading a proof (pure; no network):

    proof = parse_ots(data)                 # the .ots bytes -> {file_hash_op, file_digest, tree}; raises OtsError(code)
    atts  = attestations(proof)             # every leaf: {kind, height | uri | tag+payload, digest, depth}
    r     = verify_bitcoin(digest, header)  # one bitcoin attestation against {merkle_root, timestamp}
    rep   = verify_proof(data, target=..., digest=..., get_header=fn)   # the whole proof, with an injected fetch

A bitcoin attestation holds when the digest at that point of the tree, byte-reversed, is the block's merkle root as
explorers print it (display order); the block's header `timestamp` is then the time the proof attests: the stamped
bytes existed before that block. It attests existence before a block, not publication anywhere. The block header
itself comes from whoever `get_header` asks; this module never fetches.

The serialization (python-opentimestamps / javascript-opentimestamps, major version 1):

    file      = MAGIC  varuint(1)  file_hash_op(1 byte)  digest  timestamp
    timestamp = ( 0xff branch )*  branch                  -- every branch but the last is prefixed 0xff
    branch    = 0x00 tag(8) varbytes(payload)             -- an attestation
              | op [varbytes(arg) for append/prepend] timestamp   -- the op applied to this node's message

    ops: 0xf0 append, 0xf1 prepend, 0xf2 reverse, 0xf3 hexlify, 0x02 sha1, 0x03 ripemd160, 0x08 sha256, 0x67 keccak256
    attestation tags: bitcoin 0588960d73d71901 (payload varuint height), pending 83dfe30d2ef90c8e (payload varbytes
    uri), litecoin 06869a0d73d71b45 (payload varuint height), anything else unknown (kept, never verified)

Limits are the libraries': an op's message and result at most 4096 bytes, an append/prepend argument 1..4096 bytes,
hexlify's message 1..2048 bytes, an attestation payload at most 8192 bytes, a pending uri at most 1000 bytes of
[A-Za-z0-9-._/:], at most 256 ops deep. The kit's own bounds, the same in python and javascript: every varuint at most 2^53 - 1
(code varuint; inside an attestation's payload it reads attestation_payload) and a bitcoin or litecoin height at
most 2^32 - 1 (code attestation_payload); the libraries read 64-bit varints. Refusal codes (OtsError.code): bad_magic, bad_version, file_hash_op,
truncated, varuint, unknown_op, op_arg, msg_length, result_length, attestation_payload, pending_uri, too_deep,
too_large, trailing_bytes, ripemd160_unavailable.

sha256 / sha1 / ripemd160 come from hashlib (ripemd160 is OpenSSL's; `ripemd160_available()` says whether this
python has it, and a proof that needs it and cannot get it is refused with that code, never guessed). keccak256
(the original Keccak padding, not SHA3-256) is implemented here.

Stamping (optional; shells out to an `ots` client when one is on PATH, the client talks to the calendars):
stamp_file, stamp_text, ots_client.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
MAJOR_VERSION = 1
TAG_BITCOIN = bytes.fromhex("0588960d73d71901")
TAG_PENDING = bytes.fromhex("83dfe30d2ef90c8e")
TAG_LITECOIN = bytes.fromhex("06869a0d73d71b45")
MAX_MSG = 4096
MAX_RESULT = 4096
MAX_PAYLOAD = 8192
MAX_URI = 1000
MAX_DEPTH = 256
MAX_NODES = 200_000
MAX_VARUINT = (1 << 53) - 1      # the kit's bound on any varuint: javascript reads integers exactly up to 2^53 - 1
MAX_HEIGHT = (1 << 32) - 1       # the kit's bound on a bitcoin / litecoin block height (the libraries read 64 bits)
URI_CHARS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._/:")
OP_NAMES = {0xf0: "append", 0xf1: "prepend", 0xf2: "reverse", 0xf3: "hexlify",
            0x02: "sha1", 0x03: "ripemd160", 0x08: "sha256", 0x67: "keccak256"}
HASH_OPS = {0x02: 20, 0x03: 20, 0x08: 32, 0x67: 32}
BINARY_OPS = (0xf0, 0xf1)

Bytesish = Union[bytes, bytearray, memoryview]


class OtsError(ValueError):
    """A proof refused: `.code` is one of the module's refusal codes, `.offset` the byte where it was found."""

    def __init__(self, code: str, message: str, offset: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.offset = offset


class OtsUnavailable(RuntimeError):
    """no `ots` client on PATH, or the client failed (stamping helper only)."""


# ------------------------------------------------------------------------------------------------ hashing

def ripemd160_available() -> bool:
    try:
        hashlib.new("ripemd160", b"")
        return True
    except (ValueError, TypeError):
        return False


_KECCAK_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
    0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
    0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_KECCAK_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _keccak_f(a: List[List[int]]) -> None:
    for rc in _KECCAK_RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & _M64) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                r = _KECCAK_ROT[x][y]
                v = a[x][y]
                b[y][(2 * x + 3 * y) % 5] = ((v << r) | (v >> (64 - r))) & _M64 if r else v
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])
        a[0][0] ^= rc


def keccak256(msg: bytes) -> bytes:
    """Keccak-256 as Ethereum and opentimestamps use it (padding 0x01 ... 0x80, rate 136), not SHA3-256."""
    rate = 136
    p = bytearray(msg)
    p.append(0x01)
    while len(p) % rate:
        p.append(0)
    p[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(p), rate):
        block = p[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        _keccak_f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


def _hash(tag: int, msg: bytes) -> bytes:
    if tag == 0x08:
        return hashlib.sha256(msg).digest()
    if tag == 0x02:
        return hashlib.sha1(msg).digest()
    if tag == 0x03:
        try:
            return hashlib.new("ripemd160", msg).digest()
        except (ValueError, TypeError):
            raise OtsError("ripemd160_unavailable",
                           "this python's hashlib has no ripemd160 (OpenSSL without the legacy provider); "
                           "the proof needs it, so it is not read") from None
    if tag == 0x67:
        return keccak256(msg)
    raise OtsError("unknown_op", "not a hash op: 0x%02x" % tag)


def apply_op(tag: int, arg: Optional[bytes], msg: bytes) -> bytes:
    """The op's result on msg, under the libraries' length limits."""
    if tag == 0xf3:
        if not 1 <= len(msg) <= MAX_RESULT // 2:
            raise OtsError("msg_length", "hexlify takes 1..%d bytes, got %d" % (MAX_RESULT // 2, len(msg)))
        return msg.hex().encode("ascii")
    if len(msg) > MAX_MSG:
        raise OtsError("msg_length", "message of %d bytes exceeds %d" % (len(msg), MAX_MSG))
    if tag == 0xf0:
        r = msg + (arg or b"")
    elif tag == 0xf1:
        r = (arg or b"") + msg
    elif tag == 0xf2:
        if not msg:
            raise OtsError("msg_length", "reverse of an empty message")
        r = msg[::-1]
    else:
        r = _hash(tag, msg)
    if len(r) > MAX_RESULT:
        raise OtsError("result_length", "result of %d bytes exceeds %d" % (len(r), MAX_RESULT))
    return r


# ------------------------------------------------------------------------------------------------ reading

class _Reader:
    __slots__ = ("b", "i")

    def __init__(self, b: bytes, i: int = 0):
        self.b = b
        self.i = i

    def byte(self) -> int:
        if self.i >= len(self.b):
            raise OtsError("truncated", "the proof ends early", self.i)
        v = self.b[self.i]
        self.i += 1
        return v

    def take(self, n: int) -> bytes:
        if self.i + n > len(self.b):
            raise OtsError("truncated", "the proof ends early (wanted %d bytes)" % n, self.i)
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def varuint(self) -> int:
        start, value, shift = self.i, 0, 0
        while True:
            c = self.byte()
            value |= (c & 0x7f) << shift
            if not c & 0x80:
                break
            shift += 7
            if shift > 63:
                raise OtsError("varuint", "a varuint longer than 9 bytes", start)
        if value > MAX_VARUINT:
            raise OtsError("varuint", "a varuint above 2^53", start)
        return value

    def varbytes(self, max_len: int, min_len: int = 0, code: str = "truncated") -> bytes:
        at = self.i
        n = self.varuint()
        if n > max_len or n < min_len:
            raise OtsError(code, "varbytes of %d bytes outside %d..%d" % (n, min_len, max_len), at)
        return self.take(n)

    def eof(self) -> bool:
        return self.i >= len(self.b)


def _attestation(r: _Reader) -> Dict[str, Any]:
    at = r.i
    tag = r.take(8)
    payload = r.varbytes(MAX_PAYLOAD, code="attestation_payload")
    p = _Reader(payload)
    try:
        if tag == TAG_BITCOIN or tag == TAG_LITECOIN:
            out: Dict[str, Any] = {"kind": "bitcoin" if tag == TAG_BITCOIN else "litecoin", "height": p.varuint()}
            if out["height"] > MAX_HEIGHT:
                raise OtsError("attestation_payload", "a block height above 2^32 - 1 (%d)" % out["height"], at)
        elif tag == TAG_PENDING:
            uri = p.varbytes(MAX_URI, code="pending_uri")
            if not all(c in URI_CHARS for c in uri):
                raise OtsError("pending_uri", "a pending uri with a character outside [A-Za-z0-9-._/:]", at)
            out = {"kind": "pending", "uri": uri.decode("ascii")}
        else:
            return {"kind": "unknown", "tag": tag.hex(), "payload": payload.hex()}
    except OtsError as e:
        if e.code in ("truncated", "varuint"):
            raise OtsError("attestation_payload", "attestation payload unreadable: %s" % e, at) from None
        raise
    if not p.eof():
        raise OtsError("attestation_payload", "bytes left over in a %s attestation's payload" % out["kind"], at)
    return out


def _node(msg: bytes, depth: int) -> Dict[str, Any]:
    return {"msg": msg, "depth": depth, "attestations": [], "ops": []}


def _parse_timestamp(r: _Reader, msg: bytes) -> Dict[str, Any]:
    """Iterative: a node stays on the stack until its last (un-prefixed) branch begins."""
    root = _node(msg, 0)
    stack = [root]
    nodes = 1
    while stack:
        node = stack[-1]
        tag = r.byte()
        if tag == 0xff:
            cur = r.byte()
        else:
            cur = tag
            stack.pop()
        if cur == 0x00:
            node["attestations"].append(_attestation(r))
            continue
        at = r.i - 1
        if cur not in OP_NAMES:
            raise OtsError("unknown_op", "unknown op tag 0x%02x" % cur, at)
        arg = None
        if cur in BINARY_OPS:
            arg = r.varbytes(MAX_RESULT, 1, code="op_arg")
        if node["depth"] + 1 > MAX_DEPTH:
            raise OtsError("too_deep", "ops nested deeper than %d" % MAX_DEPTH, at)
        try:
            res = apply_op(cur, arg, node["msg"])
        except OtsError as e:
            e.offset = at if e.offset is None else e.offset
            raise
        nodes += 1
        if nodes > MAX_NODES:
            raise OtsError("too_large", "more than %d nodes" % MAX_NODES, at)
        child = _node(res, node["depth"] + 1)
        node["ops"].append(({"op": OP_NAMES[cur], "tag": cur, "arg": arg}, child))
        stack.append(child)
    return root


def parse_ots(data: Bytesish) -> Dict[str, Any]:
    """{file_hash_op, file_digest (hex), tree}. Raises OtsError on anything the libraries would not read."""
    b = bytes(data)
    r = _Reader(b)
    if len(b) < len(MAGIC) or b[:len(MAGIC)] != MAGIC:
        raise OtsError("bad_magic", "not an OpenTimestamps proof (magic header missing)", 0)
    r.i = len(MAGIC)
    ver = r.varuint()
    if ver != MAJOR_VERSION:
        raise OtsError("bad_version", "proof major version %d; this reader knows %d" % (ver, MAJOR_VERSION), len(MAGIC))
    at = r.i
    op = r.byte()
    if op not in HASH_OPS:
        raise OtsError("file_hash_op", "file hash op 0x%02x is not a hash op" % op, at)
    digest = r.take(HASH_OPS[op])
    tree = _parse_timestamp(r, digest)
    if not r.eof():
        raise OtsError("trailing_bytes", "%d bytes after the proof" % (len(b) - r.i), r.i)
    return {"file_hash_op": OP_NAMES[op], "file_digest": digest.hex(), "tree": tree}


def walk(proof: Dict[str, Any]):
    """Yield every node of the tree in serialization order (depth first)."""
    stack = [proof["tree"]]
    while stack:
        n = stack.pop()
        yield n
        for _op, child in reversed(n["ops"]):
            stack.append(child)


def attestations(proof: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every attestation, in serialization order, with the hex digest of the message it attests and its depth."""
    out = []
    for n in walk(proof):
        for a in n["attestations"]:
            d = dict(a)
            d["digest"] = n["msg"].hex()
            d["depth"] = n["depth"]
            out.append(d)
    return out


def summary(proof: Dict[str, Any]) -> Dict[str, Any]:
    atts = attestations(proof)
    btc = sorted({a["height"] for a in atts if a["kind"] == "bitcoin"})
    return {"file_hash_op": proof["file_hash_op"], "file_digest": proof["file_digest"],
            "attestations": len(atts), "bitcoin_heights": btc,
            "pending": sorted({a["uri"] for a in atts if a["kind"] == "pending"}),
            "litecoin_heights": sorted({a["height"] for a in atts if a["kind"] == "litecoin"}),
            "unknown": sum(1 for a in atts if a["kind"] == "unknown")}


# ---------------------------------------------------------------------------------------------- verifying

def expected_merkle_root(digest: Union[str, Bytesish]) -> str:
    """The merkle root (display-order hex, as explorers print it) a bitcoin attestation on `digest` claims."""
    d = bytes.fromhex(digest) if isinstance(digest, str) else bytes(digest)
    return d[::-1].hex()


def verify_bitcoin(digest: Union[str, Bytesish], header: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{ok, time, merkle_root_expected, reason}. header: {merkle_root (display hex), timestamp (unix s)}."""
    d = bytes.fromhex(digest) if isinstance(digest, str) else bytes(digest)
    want = d[::-1].hex()
    if len(d) != 32:
        return {"ok": False, "time": None, "merkle_root_expected": want,
                "reason": "the attested digest is %d bytes, not 32" % len(d)}
    if not isinstance(header, dict) or not isinstance(header.get("merkle_root"), str):
        return {"ok": False, "time": None, "merkle_root_expected": want, "reason": "no block header with a merkle_root"}
    if header["merkle_root"].lower() != want:
        return {"ok": False, "time": None, "merkle_root_expected": want,
                "reason": "the digest does not match the block's merkle root"}
    t = header.get("timestamp", header.get("time"))
    if not isinstance(t, int) or isinstance(t, bool):
        return {"ok": False, "time": None, "merkle_root_expected": want, "reason": "the block header has no integer timestamp"}
    return {"ok": True, "time": t, "merkle_root_expected": want, "reason": None}


def verify_proof(data: Bytesish, target: Optional[Bytesish] = None, digest: Optional[str] = None,
                 get_header: Optional[Callable[[int], Optional[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """Read a proof and check what it says.

    target: the stamped bytes (the proof must commit to their sha256 under its file hash op); digest: the hex
    digest the proof must commit to (a witness proof commits to an entry_id this way). get_header(height) returns
    {merkle_root, timestamp} for a bitcoin block, or None / {"error": why} when it cannot (it is called once per
    distinct height; exceptions it raises are recorded as that height's error).

    status: refused (unreadable; `code`), commitment_mismatch, failed (a header was had and a bitcoin attestation
    did not match it), verified (at least one bitcoin attestation matched, none failed), unverified (bitcoin
    attestations, no header for any), pending (calendar receipts only), no_attestation. ok is status == verified.
    """
    out: Dict[str, Any] = {"ok": False, "status": None, "code": None, "reason": None, "file_hash_op": None,
                           "file_digest": None, "commits": None, "attestations": [], "bitcoin": [],
                           "pending": [], "lowest": None}
    try:
        proof = parse_ots(data)
    except OtsError as e:
        out.update(status="refused", code=e.code, reason=str(e))
        return out
    out["file_hash_op"], out["file_digest"] = proof["file_hash_op"], proof["file_digest"]
    atts = attestations(proof)
    out["attestations"] = atts
    out["pending"] = sorted({a["uri"] for a in atts if a["kind"] == "pending"})
    want = None
    if target is not None:
        tag = {v: k for k, v in OP_NAMES.items()}[proof["file_hash_op"]]
        try:
            want = _hash(tag, bytes(target)).hex()
        except OtsError as e:
            out.update(status="refused", code=e.code, reason=str(e))
            return out
    elif digest is not None:
        want = digest.lower()
    if want is not None:
        out["commits"] = want == proof["file_digest"]
        if not out["commits"]:
            out.update(status="commitment_mismatch",
                       reason="the proof commits to %s, not %s" % (proof["file_digest"], want))
            return out
    headers: Dict[int, Any] = {}
    for a in atts:
        if a["kind"] != "bitcoin":
            continue
        h = a["height"]
        if h not in headers:
            if get_header is None:
                headers[h] = {"error": "no header source given"}
            else:
                try:
                    headers[h] = get_header(h) or {"error": "no header for block %d" % h}
                except Exception as e:  # noqa: BLE001 - an injected fetch's failure is that height's answer
                    headers[h] = {"error": "%s: %s" % (type(e).__name__, e)}
        hd = headers[h]
        if isinstance(hd, dict) and isinstance(hd.get("merkle_root"), str):
            v = verify_bitcoin(a["digest"], hd)
            rec = {"height": h, "digest": a["digest"], "merkle_root_expected": v["merkle_root_expected"],
                   "merkle_root": hd["merkle_root"], "verified": v["ok"], "time": v["time"], "reason": v["reason"]}
        else:
            rec = {"height": h, "digest": a["digest"], "merkle_root_expected": expected_merkle_root(a["digest"]),
                   "merkle_root": None, "verified": None, "time": None,
                   "reason": (hd or {}).get("error") if isinstance(hd, dict) else "no header"}
        out["bitcoin"].append(rec)
    good = [b for b in out["bitcoin"] if b["verified"] is True]
    bad = [b for b in out["bitcoin"] if b["verified"] is False]
    if good:
        lo = min(good, key=lambda b: (b["height"], b["time"]))
        out["lowest"] = {"height": lo["height"], "time": lo["time"]}
    if bad:
        out.update(status="failed", reason="%d of %d bitcoin attestations do not match their block header"
                   % (len(bad), len(out["bitcoin"])))
    elif good:
        out.update(status="verified", ok=True)
    elif out["bitcoin"]:
        out.update(status="unverified", reason="no block header for any of %d bitcoin attestations" % len(out["bitcoin"]))
    elif out["pending"]:
        out.update(status="pending", reason="calendar receipts only; no bitcoin attestation yet")
    else:
        out.update(status="no_attestation", reason="no bitcoin or pending attestation")
    return out


# ------------------------------------------------------------------------------------------------ stamping

def ots_client() -> Optional[str]:
    return shutil.which("ots")


def stamp_file(path, timeout_s: float = 30.0, client: Optional[str] = None) -> Path:
    """run `ots stamp <path>`; returns the .ots proof path. raises OtsUnavailable when there is no client, the
    client fails, or it does not finish within timeout_s."""
    exe = client or ots_client()
    if not exe:
        raise OtsUnavailable("no `ots` client on PATH (pip install opentimestamps-client); nothing stamped")
    p = Path(path)
    try:
        cp = subprocess.run([exe, "stamp", str(p)], capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise OtsUnavailable("ots stamp did not finish in %.0f s" % timeout_s) from None
    except OSError as e:
        raise OtsUnavailable("ots client could not run: %s" % e) from None
    proof = p.with_name(p.name + ".ots")
    if cp.returncode != 0 or not proof.exists():
        raise OtsUnavailable("ots stamp exit %d: %s" % (cp.returncode, (cp.stderr or cp.stdout).strip()[:300]))
    return proof


def stamp_text(text: str, out_path, timeout_s: float = 30.0, client: Optional[str] = None) -> Path:
    """write the exact anchor text (utf-8, no added LF) to out_path and stamp it; returns the .ots path."""
    p = Path(out_path)
    p.write_bytes(text.encode("utf-8"))
    if p.read_bytes() != text.encode("utf-8"):
        raise OSError("write did not land: %s" % p)
    return stamp_file(p, timeout_s=timeout_s, client=client)
