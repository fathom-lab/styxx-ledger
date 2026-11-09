"""make_crafted.py: hand-built .ots files that pin where the kit's two OpenTimestamps readers must agree (review 3e).

Writes vectors/ots/crafted/<name>.ots and crafted.json ({name: {why, sha256, expect}}), where expect is
{"status": "refused", "code": ...} or {"status": "parsed", "attestations": [[kind, height-or-uri], ...]} in walk
order (depth first; a node's own attestations before those of the ops under it). The expectations are written by hand here, not read back from either reader. `--check` rebuilds in memory and
reports any file whose bytes differ. Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "crafted"
MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
TAG_BITCOIN = bytes.fromhex("0588960d73d71901")
TAG_PENDING = bytes.fromhex("83dfe30d2ef90c8e")


def varuint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def varbytes(b):
    return varuint(len(b)) + b


def btc(height):
    return b"\x00" + TAG_BITCOIN + varbytes(varuint(height))


def pending(uri):
    return b"\x00" + TAG_PENDING + varbytes(varbytes(uri))


DIGEST = hashlib.sha256(b"review 3e").digest()
HEAD = MAGIC + varuint(1) + b"\x08" + DIGEST
ALICE = b"https://alice.btc.calendar.opentimestamps.org"

REFUSED = lambda code: {"status": "refused", "code": code}  # noqa: E731
CASES = {
    "height_max": ("a bitcoin height of 2^32 - 1, the kit's bound: read", HEAD + b"\x08" + btc((1 << 32) - 1),
                   {"status": "parsed", "attestations": [["bitcoin", (1 << 32) - 1]]}),
    "height_2p32": ("a bitcoin height of 2^32, one past the kit's bound", HEAD + b"\x08" + btc(1 << 32),
                    REFUSED("attestation_payload")),
    "height_2p53": ("a bitcoin height of 2^53 (python once read it and asked the explorers; javascript refused)",
                    HEAD + b"\x08" + btc(1 << 53), REFUSED("attestation_payload")),
    "height_2p60": ("a bitcoin height of 2^60", HEAD + b"\x08" + btc(1 << 60), REFUSED("attestation_payload")),
    "height_2p63": ("a bitcoin height of 2^63 in a 10-byte varuint", HEAD + b"\x08" + btc(1 << 63),
                    REFUSED("attestation_payload")),
    "arg_len_2p60": ("an append whose argument length is the varuint 2^60", HEAD + b"\xf0" + varuint(1 << 60) + b"a",
                     REFUSED("varuint")),
    "nested_forks": ("root -> [append 'a' -> [sha256 -> btc 974530 | pending alice]] | [sha256 -> btc 974635]",
                     HEAD + b"\xff" + b"\xf0" + varbytes(b"a") + b"\xff" + b"\x08" + btc(974530) + pending(ALICE)
                     + b"\x08" + btc(974635),
                     {"status": "parsed", "attestations": [["pending", ALICE.decode()], ["bitcoin", 974530],
                                                           ["bitcoin", 974635]]}),
    "fork_attestations_first": ("a three-way fork whose first two branches are attestations (the library keeps two)",
                                HEAD + b"\xff" + btc(974530) + b"\xff" + pending(b"https://x") + b"\x08" + btc(974635),
                                {"status": "parsed", "attestations": [["bitcoin", 974530], ["pending", "https://x"],
                                                                      ["bitcoin", 974635]]}),
    "pending_bad_uri": ("a pending uri with the bytes ff fe", HEAD + pending(b"https://\xff\xfe.example"),
                        REFUSED("pending_uri")),
    "btc_trailing": ("a bitcoin payload with a byte after the height (the library accepts it)",
                     HEAD + b"\x08" + b"\x00" + TAG_BITCOIN + varbytes(varuint(974530) + b"\x00"),
                     REFUSED("attestation_payload")),
}


def build():
    files, doc = {}, {}
    for name, (why, data, expect) in CASES.items():
        files[name + ".ots"] = data
        doc[name] = {"why": why, "file": name + ".ots", "sha256": hashlib.sha256(data).hexdigest(), "expect": expect}
    return files, doc


def main(argv):
    files, doc = build()
    blob = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()
    if "--check" in argv:
        differs = [n for n, b in files.items() if not (HERE / n).is_file() or (HERE / n).read_bytes() != b]
        if (HERE / "crafted.json").read_bytes() != blob:
            differs.append("crafted.json")
        print(json.dumps({"differs": differs, "files": len(files)}))
        return 1 if differs else 0
    HERE.mkdir(exist_ok=True)
    for n, b in files.items():
        (HERE / n).write_bytes(b)
    (HERE / "crafted.json").write_bytes(blob)
    print("%d crafted proofs written to %s" % (len(files), HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
