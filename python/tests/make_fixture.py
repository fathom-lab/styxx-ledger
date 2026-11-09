#!/usr/bin/env python3
"""make_fixture.py: the python-written ledger the javascript suite cross-verifies (tests/fixtures/py_written.*).

    python -B tests/make_fixture.py [--check]

written by styxx_ledger.Ledger with every timestamp given, so the bytes are a function of this script and the
writer. agent pybot, anchor_tz Europe/Berlin, timestamps crossing the berlin dst end (2026-10-25 01:00Z),
two anchors, kinds anchor/lock_recovered/note/send/started. py_written.json holds the head, the last seq, the
file's sha256 and the anchor texts; the javascript verifier must state the same head byte for byte.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from styxx_ledger import Ledger  # noqa: E402

FIX = HERE / "fixtures"
CREATED = "2026-10-24T20:00:00Z"
WRITER = {"name": "styxx-ledger", "version": "1.0.0a1", "language": "python"}
STEPS = [
    ("start", "2026-10-24T20:00:01Z", None),
    ("note", "2026-10-24T20:10:00Z", {"note": "22:10 CEST", "n": 1}),
    ("send", "2026-10-24T21:00:00Z", {"to_sha256": "a" * 64, "bytes": 512, "verdict": "pass", "meta": {"tries": [1, 2]}}),
    ("note", "2026-10-24T21:59:59Z", {"note": "23:59:59 CEST, the 24th's last second", "n": 3}),
    ("anchor", "2026-10-24T22:00:05Z", {"date": "2026-10-24"}),                 # 00:00:05 cest: on time
    ("note", "2026-10-25T00:30:00Z", {"note": "02:30 CEST, first pass — über", "n": 5}),
    ("note", "2026-10-25T01:00:00Z", {"note": "02:00 CET, second pass", "n": 6}),
    ("note", "2026-10-25T01:30:00Z", {"note": "02:30 CET, second pass \U0001F642", "n": 7, "tags": ["b", "a"]}),
    ("send", "2026-10-25T12:00:00Z", {"to_sha256": "b" * 64, "bytes": 0, "verdict": "held", "empty": "", "arr": []}),
    ("note", "2026-10-25T22:59:59Z", {"note": "23:59:59 CET, the 25th's last second", "n": 9, "max": 9007199254740992}),
    ("anchor", "2026-10-26T07:00:00Z", {"date": "2026-10-25"}),                 # 08:00 cet on the 26th: late by section 5
    ("note", "2026-10-26T08:00:00Z", {"note": "after the last anchor", "n": 11, "min": -9007199254740992}),
]


def build(path: Path) -> dict:
    led = Ledger.create(path, agent="pybot", anchor_tz="Europe/Berlin",
                        certifies="one line per event pybot was handed, chained; the clock is a statement, not evidence of order",
                        kinds=["lock_recovered", "note", "send"], created=CREATED)
    anchors = []
    for what, ts, f in STEPS:
        if what == "start":
            led.start(writer=WRITER, timestamp=ts)
        elif what == "anchor":
            anchors.append(led.append_anchor(f["date"], timestamp=ts)["text"])
        else:
            led.append(what, f, timestamp=ts)
    raw = path.read_bytes()
    r = led.verify()
    return {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "head": r["head"],
            "last_seq": r["entries"][-1]["entry"]["seq"], "entries": len(r["entries"]), "anchor_texts": anchors,
            "written_by": "styxx_ledger (python) tests/make_fixture.py"}


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "py_written.jsonl"
        meta = build(p)
        raw = p.read_bytes()
    mtext = (json.dumps(meta, indent=1, sort_keys=True) + "\n").encode("ascii")
    targets = [(FIX / "py_written.jsonl", raw), (FIX / "py_written.json", mtext)]
    differs = [t.name for t, b in targets if t.exists() and t.read_bytes() != b]
    if check:
        print(json.dumps({"differs": differs, "head": meta["head"]}))
        return 1 if differs else 0
    if differs:
        print("refusing: %s exist(s) with other bytes; a fixture is a receipt (delete it by hand and log why)" % differs)
        return 3
    FIX.mkdir(parents=True, exist_ok=True)
    for t, b in targets:
        t.write_bytes(b)
        if t.read_bytes() != b:
            print("write did not land: %s" % t)
            return 4
    print(json.dumps({"head": meta["head"], "sha256": meta["sha256"], "entries": meta["entries"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
