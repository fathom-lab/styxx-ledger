"""the native OpenTimestamps reader (styxx_ledger.ots) against the 14 anchor proofs and a sampled 22 witness proofs
of darkflobi's exhibit (vectors/ots/), offline, with the block headers captured from two explorers; every height,
attested time and digest must equal what javascript-opentimestamps 0.4.9 said of the same files (expect.json)."""
import hashlib
import json

import pytest

from styxx_ledger import ots
from conftest import VECTORS

OTSDIR = VECTORS / "ots"
EXPECT = json.loads((OTSDIR / "expect.json").read_text("utf-8"))
HEADERS = json.loads((OTSDIR / "block_headers.json").read_text("utf-8"))["blocks"]
FILES = sorted(EXPECT["files"])
ANCHORS = [f for f in FILES if f.startswith("anchors/")]
WITNESS = [f for f in FILES if f.startswith("witness/")]


def get_header(h):
    b = HEADERS.get(str(h))
    return None if b is None else {"merkle_root": b["header"]["merkle_root"], "timestamp": b["header"]["timestamp"]}


def norm(atts):
    keys = ("kind", "digest", "height", "uri")
    return sorted(json.dumps({k: a[k] for k in keys if k in a}, sort_keys=True) for a in atts)


def check_against(f, rep):
    exp = EXPECT["files"][f]
    assert rep["file_digest"] == exp["file_digest"]
    assert rep["status"] == exp["status"], rep["reason"]
    assert norm(rep["attestations"]) == norm(exp["attestations"])
    got_btc = sorted((b["height"], b["time"], b["digest"]) for b in rep["bitcoin"])
    exp_btc = sorted((a["height"], a["time"], a["digest"]) for a in exp["attestations"] if a["kind"] == "bitcoin")
    assert got_btc == exp_btc
    assert rep["lowest"] == exp["lowest"]


def test_fixture_counts():
    assert len(ANCHORS) == 14 and len(WITNESS) == 22
    assert len(HEADERS) == 14
    assert all(b["mempool_space_agrees"] for b in HEADERS.values())


@pytest.mark.parametrize("f", ANCHORS)
def test_anchor_proof_matches_the_library(f):
    data = (OTSDIR / f).read_bytes()
    target = (OTSDIR / EXPECT["files"][f]["target"]).read_bytes()
    rep = ots.verify_proof(data, target=target, get_header=get_header)
    assert rep["ok"] and rep["commits"] is True
    check_against(f, rep)
    assert len([a for a in rep["attestations"] if a["kind"] == "bitcoin"]) == 4
    assert len(rep["pending"]) == 4


def test_anchor_heights_are_the_shelfs():
    lows = {f.split("/")[1][:10]: ots.verify_proof((OTSDIR / f).read_bytes(), get_header=get_header)["lowest"]["height"]
            for f in ANCHORS}
    assert sorted(set(lows.values())) == [974530, 974635, 974768, 975028]
    assert sum(1 for h in lows.values() if h == 974530) == 11
    assert lows["2026-11-07"] == 975028


@pytest.mark.parametrize("f", WITNESS)
def test_witness_proof_matches_the_library(f):
    entry_id = f.split("/")[1][:-4]
    rep = ots.verify_proof((OTSDIR / f).read_bytes(), digest=entry_id, get_header=get_header)
    assert rep["commits"] is True
    check_against(f, rep)


def test_pending_only_witness_reports_pending():
    pend = [f for f in WITNESS if EXPECT["files"][f]["status"] == "pending"]
    assert len(pend) == 2
    for f in pend:
        rep = ots.verify_proof((OTSDIR / f).read_bytes(), digest=f.split("/")[1][:-4], get_header=get_header)
        assert rep["status"] == "pending" and not rep["ok"] and rep["bitcoin"] == [] and len(rep["pending"]) == 4


def test_a_flipped_byte_in_the_path_fails_every_bitcoin_attestation():
    f = ANCHORS[0]
    data = bytearray((OTSDIR / f).read_bytes())
    first_op = len(ots.MAGIC) + 1 + 1 + 32
    assert data[first_op] == 0xf0 and data[first_op + 1] == 16   # append, 16 bytes (the calendar nonce)
    data[first_op + 2] ^= 0x01
    target = (OTSDIR / EXPECT["files"][f]["target"]).read_bytes()
    rep = ots.verify_proof(bytes(data), target=target, get_header=get_header)
    assert rep["status"] == "failed" and not rep["ok"]
    assert len(rep["bitcoin"]) == 4 and all(b["verified"] is False for b in rep["bitcoin"])


def test_a_flipped_text_byte_is_a_commitment_mismatch():
    f = ANCHORS[0]
    target = bytearray((OTSDIR / EXPECT["files"][f]["target"]).read_bytes())
    target[0] ^= 0x20
    rep = ots.verify_proof((OTSDIR / f).read_bytes(), target=bytes(target), get_header=get_header)
    assert rep["status"] == "commitment_mismatch" and rep["commits"] is False and not rep["ok"]


def test_a_witness_proof_for_another_entry_is_a_commitment_mismatch():
    a, b = WITNESS[0], WITNESS[1]
    rep = ots.verify_proof((OTSDIR / a).read_bytes(), digest=b.split("/")[1][:-4], get_header=get_header)
    assert rep["status"] == "commitment_mismatch"


def test_no_header_source_is_unverified_not_verified():
    rep = ots.verify_proof((OTSDIR / ANCHORS[0]).read_bytes())
    assert rep["status"] == "unverified" and not rep["ok"]
    rep = ots.verify_proof((OTSDIR / ANCHORS[0]).read_bytes(), get_header=lambda h: (_ for _ in ()).throw(OSError("net down")))
    assert rep["status"] == "unverified" and "net down" in rep["bitcoin"][0]["reason"]


def test_a_wrong_header_fails():
    def wrong(h):
        return {"merkle_root": "00" * 32, "timestamp": 1}
    rep = ots.verify_proof((OTSDIR / ANCHORS[0]).read_bytes(), get_header=wrong)
    assert rep["status"] == "failed"


# ------------------------------------------------------------------------------------- synthetic proofs

def vu(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def vb(b):
    return vu(len(b)) + b


def btc(height):
    return b"\x00" + ots.TAG_BITCOIN + vb(vu(height))


def pending(uri):
    return b"\x00" + ots.TAG_PENDING + vb(vb(uri.encode("ascii")))


def proof(body, digest=b"\x11" * 32, op=0x08):
    return ots.MAGIC + b"\x01" + bytes([op]) + digest + body


def test_every_op_and_keccak():
    assert ots.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert ots.keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"
    assert ots.keccak256(b"a" * 200).hex() == "96ea54061def936c4be90b518992fdc6f12f535068a256229aca54267b4d084d"
    d = b"\x11" * 32
    m = d + b"\xaa"                       # append aa
    m = b"\xbb\xcc" + m                   # prepend bbcc
    m = m[::-1]                           # reverse
    m = m.hex().encode()                  # hexlify
    m = hashlib.sha1(m).digest()          # sha1
    m = hashlib.new("ripemd160", m).digest()
    m = ots.keccak256(m)                  # keccak256
    m = hashlib.sha256(m).digest()
    body = (b"\xf0" + vb(b"\xaa") + b"\xf1" + vb(b"\xbb\xcc") + b"\xf2" + b"\xf3" + b"\x02" + b"\x03" + b"\x67"
            + b"\x08" + btc(800000))
    hdr = {"merkle_root": m[::-1].hex(), "timestamp": 1700000000}
    rep = ots.verify_proof(proof(body), digest=d.hex(), get_header=lambda h: hdr if h == 800000 else None)
    assert rep["status"] == "verified" and rep["lowest"] == {"height": 800000, "time": 1700000000}
    assert rep["attestations"][0]["depth"] == 8


def test_forks_and_pending_only():
    body = b"\xff" + pending("https://a.example.org") + b"\x08" + pending("https://b.example.org")
    rep = ots.verify_proof(proof(body))
    assert rep["status"] == "pending" and rep["pending"] == ["https://a.example.org", "https://b.example.org"]
    s = ots.summary(ots.parse_ots(proof(body)))
    assert s["attestations"] == 2 and s["bitcoin_heights"] == []


def test_unknown_and_litecoin_attestations_are_kept_not_verified():
    body = b"\xff\x00" + bytes.fromhex("0102030405060708") + vb(b"xyz") + b"\x00" + ots.TAG_LITECOIN + vb(vu(5))
    rep = ots.verify_proof(proof(body))
    kinds = sorted(a["kind"] for a in rep["attestations"])
    assert kinds == ["litecoin", "unknown"] and rep["status"] == "no_attestation"


@pytest.mark.parametrize("data,code", [
    (b"not a proof", "bad_magic"),
    (ots.MAGIC + b"\x02\x08" + b"\x11" * 32 + b"\x00", "bad_version"),
    (ots.MAGIC + b"\x01\xf0" + b"\x11" * 32, "file_hash_op"),
    (ots.MAGIC + b"\x01\x08" + b"\x11" * 10, "truncated"),
    (proof(b"\x99" + btc(1)), "unknown_op"),
    (proof(b"\xf0\x00" + btc(1)), "op_arg"),
    (proof(btc(1) + b"\x00"), "trailing_bytes"),
    (proof(b"\x00" + ots.TAG_BITCOIN + vb(vu(1) + b"\x00")), "attestation_payload"),
    (proof(b"\x00" + ots.TAG_PENDING + vb(vb(b"https://a b"))), "pending_uri"),
    (proof(b"\x08" * 257 + btc(1)), "too_deep"),
    (proof(b"\xf0" + vb(b"\x00" * 4096) + btc(1)), "result_length"),
    (proof(b"\x00" + ots.TAG_BITCOIN + vb(b"\xff" * 10)), "attestation_payload"),
])
def test_refusals_carry_a_code(data, code):
    with pytest.raises(ots.OtsError) as e:
        ots.parse_ots(data)
    assert e.value.code == code
    rep = ots.verify_proof(data)
    assert rep["status"] == "refused" and rep["code"] == code and not rep["ok"]


def test_depth_256_is_read():
    assert ots.verify_proof(proof(b"\x08" * 256 + btc(1)))["status"] == "unverified"


def test_verify_bitcoin_edges():
    d = bytes(range(32))
    ok = ots.verify_bitcoin(d, {"merkle_root": d[::-1].hex().upper(), "timestamp": 5})
    assert ok["ok"] and ok["time"] == 5
    assert ots.expected_merkle_root(d) == d[::-1].hex()
    assert not ots.verify_bitcoin(d, None)["ok"]
    assert not ots.verify_bitcoin(d[:20], {"merkle_root": d[:20][::-1].hex(), "timestamp": 5})["ok"]
    assert not ots.verify_bitcoin(d, {"merkle_root": d[::-1].hex(), "timestamp": "5"})["ok"]


def test_ripemd160_is_available_here():
    # recorded, not assumed: OpenSSL 3 builds without the legacy provider lack it, and the reader then refuses
    assert ots.ripemd160_available() is True


# ------------------------------------------------------------------- crafted proofs (review 3e): py == js == file

CRAFTED = json.loads((OTSDIR / "crafted" / "crafted.json").read_text("utf-8"))


@pytest.mark.parametrize("name", sorted(CRAFTED))
def test_crafted_proof_answers_as_the_file_says(name):
    c = CRAFTED[name]
    data = (OTSDIR / "crafted" / c["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == c["sha256"]
    exp = c["expect"]
    if exp["status"] == "refused":
        with pytest.raises(ots.OtsError) as ei:
            ots.parse_ots(data)
        assert ei.value.code == exp["code"], (name, str(ei.value))
    else:
        got = [[a["kind"], a.get("height", a.get("uri"))] for a in ots.attestations(ots.parse_ots(data))]
        assert got == exp["attestations"]


def test_a_huge_height_is_refused_before_any_header_is_asked():
    asked = []
    data = (OTSDIR / "crafted" / "height_2p60.ots").read_bytes()
    rep = ots.verify_proof(data, get_header=lambda h: asked.append(h))
    assert rep["status"] == "refused" and rep["code"] == "attestation_payload" and asked == []
