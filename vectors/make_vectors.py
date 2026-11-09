#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_vectors.py: write base_v1.jsonl and vectors_v1.json ONCE, with the python package's answers as `expect`.

    python -B vectors/make_vectors.py [--check] [--force]

The base is a fixed 60-line ledger (header + 59 entries) for agent "kitbot", kinds anchor/note/started, its
timestamps crossing the America/New_York DST end (2026-11-01 06:00Z) and the 2026-12-31/2027-01-01 boundary; every
timestamp is given, so the bytes are a function of this script. Each expectation is what styxx_ledger answers;
run_vectors.py re-asks python and run_vectors.mjs asks javascript.

A receipt is history: when base_v1.jsonl or vectors_v1.json already exists and the newly computed bytes differ, the
script prints the difference and writes nothing, unless --force is given (and the change is then logged by hand in
BUILD_LOG_3a.md). --check only compares.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import run_vectors as RV  # noqa: E402

S = RV.load_pkg(HERE.parent / "python" / "src")

AGENT = "kitbot"
TZ = "America/New_York"
HEADER = {"schema": S.LOG_SCHEMA, "created": "2026-10-31T13:00:00Z", "anchor_tz": TZ, "agent": AGENT,
          "certifies": "one line per event kitbot was handed, chained; the writer's clock is a statement, not evidence of order",
          "kinds": ["anchor", "note", "started"]}
WRITER = {"name": "styxx-ledger", "version": "1.0.0a1", "language": "python"}

# (timestamp, kind, fields-or-anchor-spec). An anchor spec is {"date": D, "late": bool}: its head is the last entry
# whose day is D, composed when the timeline is played.
TIMELINE = [
    ("2026-10-31T13:00:01Z", "started", {"writer": WRITER}),
    ("2026-10-31T13:05:00Z", "note", {"note": "first note", "n": 1}),
    ("2026-10-31T14:00:00Z", "note", {"note": "café ☕ — \U0001F642", "n": 2, "tags": ["unicode"]}),
    ("2026-10-31T15:30:00Z", "note", {"note": "line1\nline2\t\"quoted\" back\\slash", "n": 3}),
    ("2026-10-31T18:00:00Z", "note", {"note": "edges", "max": 9007199254740992, "min": -9007199254740992, "zero": 0}),
    ("2026-10-31T20:00:00Z", "note", {"note": "nested", "meta": {"ok": True, "none": None, "list": [1, [2, [3]], {}]}}),
    ("2026-11-01T00:00:00Z", "note", {"note": "20:00 EDT on the 31st", "n": 6}),
    ("2026-11-01T02:00:00Z", "note", {"note": "22:00 EDT on the 31st", "n": 7}),
    ("2026-11-01T03:59:59Z", "note", {"note": "23:59:59 EDT, the 31st's last second", "n": 8}),
    ("2026-11-01T04:00:05Z", "anchor", {"date": "2026-10-31", "late": False}),
    ("2026-11-01T04:30:00Z", "note", {"note": "00:30 EDT on the 1st", "n": 10}),
    ("2026-11-01T05:00:00Z", "note", {"note": "01:00 EDT, first pass", "n": 11}),
    ("2026-11-01T05:30:00Z", "note", {"note": "01:30 EDT, first pass", "n": 12}),
    ("2026-11-01T05:59:59Z", "note", {"note": "01:59:59 EDT", "n": 13}),
    ("2026-11-01T06:00:00Z", "note", {"note": "01:00 EST, second pass", "n": 14}),
    ("2026-11-01T06:30:00Z", "note", {"note": "01:30 EST, second pass", "n": 15}),
    ("2026-11-01T07:00:00Z", "note", {"note": "02:00 EST", "n": 16}),
    ("2026-11-01T12:00:00Z", "note", {"note": "07:00 EST", "n": 17, "flag": False}),
    ("2026-11-01T18:00:00Z", "note", {"note": "13:00 EST", "n": 18, "tags": ["b", "a", "ä"]}),
    ("2026-11-02T00:00:00Z", "note", {"note": "19:00 EST on the 1st", "n": 19}),
    ("2026-11-02T04:00:00Z", "note", {"note": "23:00 EST on the 1st (EDT would say 00:00 on the 2nd)", "n": 20}),
    ("2026-11-02T04:30:00Z", "note", {"note": "23:30 EST on the 1st (EDT would say 00:30 on the 2nd)", "n": 21}),
    ("2026-11-02T04:59:59Z", "note", {"note": "23:59:59 EST, the 1st's last second", "n": 22}),
    ("2026-11-02T05:00:07Z", "anchor", {"date": "2026-11-01", "late": False}),
    ("2026-11-02T05:01:00Z", "note", {"note": "00:01 EST on the 2nd", "n": 24}),
    ("2026-11-02T13:00:00Z", "note", {"note": "08:00 EST", "n": 25}),
    ("2026-11-02T17:00:00Z", "note", {"note": "12:00 EST", "n": 26, "empty": "", "arr": []}),
    ("2026-11-02T21:00:00Z", "note", {"note": "16:00 EST", "n": 27}),
    ("2026-11-03T02:00:00Z", "note", {"note": "21:00 EST on the 2nd", "n": 28}),
    ("2026-11-03T09:00:00Z", "anchor", {"date": "2026-11-02", "late": True}),
    ("2026-11-03T09:00:30Z", "note", {"note": "the anchor above was late: posted 04:00 EST on the 3rd", "n": 30}),
    ("2026-11-03T15:00:00Z", "note", {"note": "10:00 EST on the 3rd", "n": 31}),
    ("2026-12-31T15:00:00Z", "note", {"note": "the writer slept; 10:00 EST on dec 31", "n": 32}),
    ("2026-12-31T20:00:00Z", "note", {"note": "15:00 EST", "n": 33}),
    ("2026-12-31T23:00:00Z", "note", {"note": "18:00 EST; 2027 already in UTC in an hour", "n": 34}),
    ("2027-01-01T00:00:00Z", "note", {"note": "UTC new year, 19:00 EST on dec 31", "n": 35}),
    ("2027-01-01T02:30:00Z", "note", {"note": "21:30 EST", "n": 36}),
    ("2027-01-01T04:00:00Z", "note", {"note": "23:00 EST", "n": 37}),
    ("2027-01-01T04:59:59Z", "note", {"note": "23:59:59 EST, the year's last second in New York", "n": 38}),
    ("2027-01-01T05:00:03Z", "anchor", {"date": "2026-12-31", "late": False}),
    ("2027-01-01T05:00:04Z", "note", {"note": "new year in New York", "n": 40}),
    ("2027-01-01T06:00:00Z", "note", {"note": "01:00 EST", "n": 41}),
    ("2027-01-01T09:00:00Z", "note", {"note": "04:00 EST", "n": 42}),
    ("2027-01-01T12:00:00Z", "note", {"note": "07:00 EST", "n": 43}),
    ("2027-01-01T14:00:00Z", "note", {"note": "09:00 EST", "n": 44}),
    ("2027-01-01T15:00:00Z", "note", {"note": "10:00 EST", "n": 45}),
    ("2027-01-01T16:00:00Z", "note", {"note": "11:00 EST", "n": 46}),
    ("2027-01-01T17:00:00Z", "note", {"note": "12:00 EST", "n": 47}),
    ("2027-01-01T18:00:00Z", "note", {"note": "13:00 EST", "n": 48}),
    ("2027-01-01T19:00:00Z", "note", {"note": "14:00 EST", "n": 49}),
    ("2027-01-01T20:00:00Z", "note", {"note": "15:00 EST", "n": 50}),
    ("2027-01-01T21:00:00Z", "note", {"note": "16:00 EST", "n": 51}),
    ("2027-01-01T22:00:00Z", "note", {"note": "17:00 EST", "n": 52}),
    ("2027-01-01T23:00:00Z", "note", {"note": "18:00 EST", "n": 53}),
    ("2027-01-02T01:00:00Z", "note", {"note": "20:00 EST on jan 1", "n": 54}),
    ("2027-01-02T03:00:00Z", "note", {"note": "22:00 EST on jan 1", "n": 55}),
    ("2027-01-02T04:59:00Z", "note", {"note": "23:59 EST on jan 1", "n": 56}),
    ("2027-01-02T05:00:02Z", "anchor", {"date": "2027-01-01", "late": False}),
    ("2027-01-02T05:10:00Z", "note", {"note": "after the last anchor: not yet pinned", "n": 58}),
]


def play():
    """The base ledger's lines (header first), each entry composed by build_entry, the anchor texts posted."""
    S.check_header(HEADER)
    lines = [S.dump(HEADER)]
    entries, anchors = [], []
    prev = S.header_digest(HEADER)
    for i, (ts, kind, spec) in enumerate(TIMELINE, start=1):
        if kind == "anchor":
            day_entries = [e for e in entries if e["day"] == spec["date"]]
            head = day_entries[-1]
            text = S.anchor_text(AGENT, spec["date"], head["entry_id"], head["seq"])
            fields = {"anchor_date": spec["date"], "anchor_head": head["entry_id"], "anchor_head_seq": head["seq"],
                      "anchor_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "late": spec["late"]}
            anchors.append({"text": text, "head_seq": head["seq"], "date": spec["date"]})
        else:
            fields = spec
        e = S.build_entry(HEADER, i, prev, kind, ts, fields)
        entries.append(e)
        lines.append(S.dump(e))
        prev = e["entry_id"]
    return (("\n".join(lines) + "\n").encode("utf-8")), entries, anchors


# --------------------------------------------------------------------------------------- write-side cases

H2 = {"schema": S.LOG_SCHEMA, "created": "2027-03-01T00:00:00Z", "anchor_tz": "Europe/Berlin", "agent": "bot-2_b",
      "certifies": "a header with a non-ASCII sentence: über alles nichts — 日本", "kinds": ["anchor", "edit", "note", "send", "started"]}
P0 = "0" * 64


def nested(depth: int):
    """`depth` containers: an object holding arrays, the innermost holding 1."""
    v = 1
    for _ in range(depth - 1):
        v = [v]
    return {"d": v}


def sweep_cases(entries, base):
    """write-side cases added 2026-11-09 (the lab's improvement sweep), appended after the earlier cases so those keep
    their places. every non-ascii string is spelled with chr(), so the bytes of this source say which code point is
    meant. ranks 68, 43 and 42 of the sweep's list."""
    c = []
    # rank 68, section 2: strings are never normalised. nfc and nfd, a compatibility ligature, a fullwidth letter,
    # conjoining jamo and the angstrom sign keep their own code points and bytes
    s = {"nfc": chr(0xE9), "nfd": "e" + chr(0x301), "nfkc_ligature": chr(0xFB01), "fullwidth_a": chr(0xFF21),
         "jamo": chr(0x1100) + chr(0x1161), "angstrom_sign": chr(0x212B)}
    v = S.jcs(s)
    c.append({"name": "dump-strings-never-normalised", "fn": "jcs", "input": s, "expect": v,
              "expect_sha256": hashlib.sha256(v.encode("utf-8")).hexdigest()})
    nfc = {"schema": S.ENTRY_SCHEMA, "seq": 1, "prev": P0, "kind": "note", "timestamp": "2027-03-01T00:00:00Z",
           "day": "2027-03-01", "x": chr(0xFC)}
    nfd = dict(nfc, x="u" + chr(0x308))
    assert S.entry_id_of(nfc) != S.entry_id_of(nfd)     # the core of entry-id-minimal, its string in nfd
    c.append({"name": "entry-id-minimal-in-nfd", "fn": "entry_id", "core": nfd, "expect": S.entry_id_of(nfd)})
    # rank 43, section 1: a certifies of whitespace only is refused (header_form), whitespace being exactly these 30
    # code points, the union of python's str.isspace and javascript's String.prototype.trim
    blank30 = [0x9, 0xA, 0xB, 0xC, 0xD, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x85, 0xA0, 0x1680] + list(range(0x2000, 0x200B)) \
        + [0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]
    assert len(set(blank30)) == 30
    headers = [
        ("header-certifies-base", HEADER["certifies"], None),
        ("header-refuse-certifies-empty", "", "header_form"),
        ("header-refuse-certifies-space", " ", "header_form"),
        ("header-refuse-certifies-u+feff", chr(0xFEFF), "header_form"),   # blank to javascript's trim, not to python's strip
        ("header-refuse-certifies-u+001c", chr(0x1C), "header_form"),     # blank to python's strip, not to javascript's trim
        ("header-refuse-certifies-u+001f", chr(0x1F), "header_form"),
        ("header-refuse-certifies-u+0085", chr(0x85), "header_form"),
        ("header-refuse-certifies-the-30-but-lf", "".join(chr(x) for x in blank30 if x != 0xA), "header_form"),
        ("header-refuse-certifies-lf", "one line" + chr(0xA) + "and another", "header_form"),
        ("header-refuse-certifies-501-chars", "x" * 501, "header_form"),
        ("header-certifies-u+200b-is-not-blank", chr(0x200B), None),      # zero width space: outside the 30
        ("header-certifies-u+180e-is-not-blank", chr(0x180E), None),      # mongolian vowel separator: outside the 30
        ("header-certifies-padded", " certifies, with blanks around it ", None),
        ("header-certifies-500-chars", "x" * 500, None),
        ("header-certifies-500-astral-chars", chr(0x1F642) * 500, None),  # characters are code points, not utf-16 units
    ]
    for name, cert, code in headers:
        h = dict(HEADER, certifies=cert)
        x = {"name": name, "fn": "check_header", "header": h}
        if code:
            x["expect_error"] = code
        else:
            x["expect"] = S.header_digest(h)
        c.append(x)
    # rank 42, section 5: the anchor text is composed for a day that has closed in anchor_tz, that the ledger has not
    # anchored, and that has a line; over the base's header and entries (america/new_york)
    composes = [
        ("compose-anchor-closed-at-local-midnight", "2027-01-02", "2027-01-03T05:00:00Z", None),   # 00:00:00 est, the 3rd
        ("compose-anchor-a-skipped-day-weeks-later", "2026-11-03", "2027-01-03T12:00:00Z", None),
        ("compose-anchor-refuse-open-last-second", "2027-01-02", "2027-01-03T04:59:59Z", "day_open"),  # 23:59:59 est
        ("compose-anchor-refuse-open-same-day", "2027-01-02", "2027-01-02T12:00:00Z", "day_open"),
        ("compose-anchor-refuse-open-at-dst-end", "2026-11-01", "2026-11-02T04:30:00Z", "day_open"),   # 23:30 est, the 1st
        ("compose-anchor-refuse-a-future-day", "2027-01-05", "2027-01-03T12:00:00Z", "day_open"),
        ("compose-anchor-refuse-already-anchored", "2027-01-01", "2027-01-03T12:00:00Z", "already_anchored"),
        ("compose-anchor-refuse-open-before-anchored", "2027-01-01", "2027-01-01T12:00:00Z", "day_open"),  # before already_anchored
        ("compose-anchor-refuse-a-day-with-no-line", "2026-12-01", "2027-01-03T12:00:00Z", "nothing_to_anchor"),
        ("compose-anchor-refuse-date-out-of-form", "2027-1-2", "2027-01-03T12:00:00Z", "anchor_form"),
    ]
    for name, d, now, code in composes:
        x = {"name": name, "fn": "compose_anchor", "date": d, "now": now}
        v, err = RV.call_write(S, x, base)
        if code:
            x["expect_error"] = code
        else:
            x["expect"] = v
            x["expect_sha256"] = hashlib.sha256(v.encode("utf-8")).hexdigest()
        c.append(x)
    return c


def write_cases(entries, base):
    c = []
    dumps = [
        ("dump-nested", {"z": {"b": [1, {"d": None, "c": True}], "a": False}, "a": []}),
        ("dump-unicode-strings", {"s": "héllo wörld — 日本語 \U0001F642", "t": "äöüß"}),
        ("dump-escapes", {"e": "quote\" backslash\\ slash/ \b\f\n\r\t \u0000 \u001f \u007f \u0080     ﻿"}),
        ("dump-int-plus-2^53", {"max": 9007199254740992}),
        ("dump-int-minus-2^53", {"min": -9007199254740992}),
        ("dump-empty-object", {}),
        ("dump-empty-array-and-object-values", {"a": [], "o": {}}),
        ("dump-key-order-by-code-point", {"b": 1, "B": 2, "_": 3, "a": 4, "A": 5, "aa": 6, "a_": 7, "~": 8, "0": 9, " ": 10, "": 11, "a ": 12}),
        ("dump-top-level-array", [3, "x", None, [], {}, [[]]]),
        ("dump-control-and-quote-keys", {"\u0001": 1, "\t": 2, "a\"b": 3, "\\": 4, "~": 5}),
        ("dump-integers", {"zero": 0, "neg": -1, "big": 123456789012345, "small": -123456789012345}),
        ("dump-mixed-entry-like", {"tags": ["ä", "a", "Z"], "meta": {"n": 1, "ok": True, "none": None}, "s": ""}),
        ("dump-depth-32", nested(32)),                                                  # review finding 3: the bound itself
    ]
    for name, obj in dumps:
        v = S.jcs(obj)
        c.append({"name": name, "fn": "jcs", "input": obj, "expect": v,
                  "expect_sha256": hashlib.sha256(v.encode("utf-8")).hexdigest()})
    refusals = [
        ("refuse-float", {"a": [1, {"b": 1.5}]}, "float"),
        ("refuse-non-ascii-key", {"é": 1}, "non_ascii_key"),
        ("refuse-key-U+007F", {"\u007f": 1}, "non_ascii_key"),
        ("refuse-int-over-2^53", {"n": 9007199254740994}, "int_range"),
        ("refuse-int-under-minus-2^53", {"n": [-9007199254740994]}, "int_range"),
        ("refuse-lone-surrogate", {"s": "a\ud800b"}, "lone_surrogate"),
        ("refuse-depth-33", nested(33), "depth"),                                       # review finding 3
    ]
    for name, obj, code in refusals:
        c.append({"name": name, "fn": "jcs", "input": obj, "expect_error": code})
    days = [
        ("2026-11-01T03:59:59Z", TZ), ("2026-11-01T04:00:00Z", TZ), ("2026-11-01T05:00:00Z", TZ),
        ("2026-11-01T05:59:59Z", TZ), ("2026-11-01T06:00:00Z", TZ), ("2026-11-01T07:00:00Z", TZ),
        ("2026-11-02T04:59:59Z", TZ), ("2026-11-02T05:00:00Z", TZ),
        ("2026-10-24T21:59:59Z", "Europe/Berlin"), ("2026-10-24T22:00:00Z", "Europe/Berlin"),
        ("2026-10-25T22:59:59Z", "Europe/Berlin"), ("2026-12-31T23:00:00Z", "Europe/Berlin"),
        ("2026-12-31T23:59:59Z", "UTC"), ("2027-01-01T00:00:00Z", "UTC"), ("2026-11-01T05:30:00Z", "UTC"),
        ("1000-01-01T00:00:00Z", TZ), ("9998-12-31T23:59:59Z", "Europe/Berlin"),     # review finding 2: the year edges
    ]
    for ts, tz in days:
        c.append({"name": "day %s %s" % (ts, tz), "fn": "day_of", "timestamp": ts, "tz": tz, "expect": S.day_of(ts, tz)})
    day_refusals = [
        ("day-refuse-offset", "2026-11-01T05:00:00+00:00", TZ, "timestamp"),
        ("day-refuse-fraction", "2026-11-01T05:00:00.000Z", TZ, "timestamp"),
        ("day-refuse-feb-30", "2026-02-30T00:00:00Z", TZ, "timestamp"),
        ("day-refuse-hour-24", "2026-11-01T24:00:00Z", TZ, "timestamp"),
        ("day-refuse-leap-second", "2026-12-31T23:59:60Z", "UTC", "timestamp"),
        ("day-refuse-unknown-zone", "2026-11-01T05:00:00Z", "Mars/Olympus_Mons", "anchor_tz"),
        # review finding 1: a trailing LF and non-ascii digits are not the form
        ("day-refuse-trailing-lf", "2026-11-01T05:00:00Z\n", "UTC", "timestamp"),
        ("day-refuse-fullwidth-digits", "\uff12\uff10\uff12\uff16-11-01T05:00:00Z", "UTC", "timestamp"),
        # review finding 2: years outside 1000..9998
        ("day-refuse-year-0001-new-york", "0001-01-01T00:00:00Z", TZ, "timestamp"),
        ("day-refuse-year-9999-berlin", "9999-12-31T23:59:59Z", "Europe/Berlin", "timestamp"),
        ("day-refuse-year-0999-utc", "0999-12-31T23:59:59Z", "UTC", "timestamp"),
        # review finding 6: a zone is the exact-case name the database lists, never Factory
        ("day-refuse-zone-lowercase-utc", "2026-11-01T05:00:00Z", "utc", "anchor_tz"),
        ("day-refuse-zone-trailing-space", "2026-11-01T05:00:00Z", "UTC ", "anchor_tz"),
        ("day-refuse-zone-factory", "2026-11-01T05:00:00Z", "Factory", "anchor_tz"),
        ("day-refuse-zone-lowercase-new-york", "2026-11-01T05:00:00Z", "america/new_york", "anchor_tz"),
    ]
    for name, ts, tz, code in day_refusals:
        c.append({"name": name, "fn": "day_of", "timestamp": ts, "tz": tz, "expect_error": code})
    for name, h in (("header-digest-base", HEADER), ("header-digest-berlin-unicode", H2)):
        c.append({"name": name, "fn": "header_digest", "header": h, "expect": S.header_digest(h)})
    a_ok = [("anchor-text-base", AGENT, entries[22]["day"], entries[22]["entry_id"], entries[22]["seq"]),
            ("anchor-text-seq-0", "bot-2_b", "2027-03-01", "a" * 64, 0)]
    for name, ag, d, h, s in a_ok:
        v = S.anchor_text(ag, d, h, s)
        c.append({"name": name, "fn": "anchor_text", "agent": ag, "date": d, "head": h, "seq": s, "expect": v,
                  "expect_sha256": hashlib.sha256(v.encode("utf-8")).hexdigest()})
    a_bad = [("anchor-refuse-agent-space", "Kit Bot", "2026-11-01", "a" * 64, 1),
             ("anchor-refuse-agent-33-chars", "k" * 33, "2026-11-01", "a" * 64, 1),
             ("anchor-refuse-uppercase-head", AGENT, "2026-11-01", "A" * 64, 1),
             ("anchor-refuse-negative-seq", AGENT, "2026-11-01", "a" * 64, -1),
             ("anchor-refuse-agent-trailing-lf", AGENT + "\n", "2026-11-01", "a" * 64, 1),    # review finding 1
             ("anchor-refuse-seq-over-2^53", AGENT, "2026-11-01", "a" * 64, 9007199254740994)]
    for name, ag, d, h, s in a_bad:
        c.append({"name": name, "fn": "anchor_text", "agent": ag, "date": d, "head": h, "seq": s, "expect_error": "anchor_form"})
    cores = [("entry-id-base-seq-3", S.core_of(entries[2])),
             ("entry-id-minimal", {"schema": S.ENTRY_SCHEMA, "seq": 1, "prev": P0, "kind": "note",
                                   "timestamp": "2027-03-01T00:00:00Z", "day": "2027-03-01", "x": "ü"})]
    for name, core in cores:
        c.append({"name": name, "fn": "entry_id", "core": core, "expect": S.entry_id_of(core)})
    lates = [   # review finding 5: section 5's rule, (anchor_date, timestamp, tz)
        ("late-on-time-at-cutoff-edt", "2026-10-31", "2026-11-01T04:10:00Z", TZ),
        ("late-one-second-after-cutoff-edt", "2026-10-31", "2026-11-01T04:10:01Z", TZ),
        ("late-on-time-at-cutoff-est", "2026-11-01", "2026-11-02T05:10:00Z", TZ),
        ("late-one-second-after-cutoff-est", "2026-11-01", "2026-11-02T05:10:01Z", TZ),
        ("late-next-day-at-23:59:59-local", "2026-11-01", "2026-11-03T04:59:59Z", TZ),
        ("late-two-days-after", "2026-11-01", "2026-11-03T05:00:00Z", TZ),
        ("late-utc-cutoff", "2026-12-31", "2027-01-01T00:10:01Z", "UTC"),
        ("late-same-day-is-not-late", "2026-12-31", "2026-12-31T23:00:00Z", "UTC"),
        ("late-berlin-after-dst-end", "2026-10-25", "2026-10-25T23:10:00Z", "Europe/Berlin"),
    ]
    for name, d, ts, tz in lates:
        c.append({"name": name, "fn": "late_of", "anchor_date": d, "timestamp": ts, "tz": tz,
                  "expect": S.late_of(d, ts, tz)})
    c.append({"name": "late-refuse-not-a-date", "fn": "late_of", "anchor_date": "2026-02-30",
              "timestamp": "2026-03-02T00:00:00Z", "tz": "UTC", "expect_error": "anchor_form"})
    hd = S.header_digest(HEADER)
    builds = [
        ("build-started", HEADER, 1, hd, "started", "2026-10-31T13:00:01Z", {"writer": {"name": "styxx-ledger", "version": "1.0.0a1"}}),
        ("build-note-dst-edge", HEADER, 21, entries[19]["entry_id"], "note", "2026-11-02T04:30:00Z", {"note": "23:30 EST", "deep": {"b": [1], "a": None}}),
        ("build-anchor", HEADER, 9, entries[7]["entry_id"], "anchor", "2026-11-01T04:00:05Z",
         {"anchor_date": "2026-10-31", "anchor_head": entries[7]["entry_id"], "anchor_head_seq": 8, "anchor_text_sha256": "b" * 64, "late": False}),
        ("build-berlin-new-year", H2, 4, P0, "send", "2026-12-31T23:30:00Z", {"sent_sha256": "c" * 64}),
        ("build-anchor-late-by-rule", HEADER, 30, entries[28]["entry_id"], "anchor", "2026-11-03T09:00:00Z",
         {"anchor_date": "2026-11-02", "anchor_head": entries[28]["entry_id"], "anchor_head_seq": 29, "anchor_text_sha256": "d" * 64, "late": True}),
    ]
    for name, h, s, p, k, ts, f in builds:
        c.append({"name": name, "fn": "build_entry", "header": h, "seq": s, "prev": p, "kind": k, "timestamp": ts,
                  "fields": f, "expect": S.dump(S.build_entry(h, s, p, k, ts, f))})
    build_bad = [
        ("build-refuse-kind-not-declared", HEADER, 2, P0, "send", "2026-11-01T05:00:00Z", {"x": 1}, "kind_not_declared"),
        ("build-refuse-reserved-field", HEADER, 2, P0, "note", "2026-11-01T05:00:00Z", {"day": "2026-11-02"}, "reserved_field"),
        ("build-refuse-started-without-writer", HEADER, 1, P0, "started", "2026-11-01T05:00:00Z", {"note": "no writer"}, "started_writer"),
        ("build-refuse-float-field", HEADER, 2, P0, "note", "2026-11-01T05:00:00Z", {"score": 0.5}, "float"),
        ("build-refuse-offset-timestamp", HEADER, 2, P0, "note", "2026-11-01T01:00:00-04:00", {"x": 1}, "timestamp"),
        ("build-refuse-anchor-late-mark-against-rule", HEADER, 9, P0, "anchor", "2026-11-01T04:00:05Z",
         {"anchor_date": "2026-10-31", "anchor_head": P0, "anchor_head_seq": 8, "anchor_text_sha256": "b" * 64, "late": True}, "anchor_form"),
        ("build-refuse-depth-33-field", HEADER, 2, P0, "note", "2026-11-01T05:00:00Z", {"deep": nested(32)}, "depth"),
    ]
    for name, h, s, p, k, ts, f, code in build_bad:
        c.append({"name": name, "fn": "build_entry", "header": h, "seq": s, "prev": p, "kind": k, "timestamp": ts,
                  "fields": f, "expect_error": code})
    c.extend(sweep_cases(entries, base))
    for x in c:
        v, err = RV.call_write(S, x, base)
        if "expect_error" in x:
            assert err == x["expect_error"], (x["name"], err, v)
        else:
            assert err is None and v == x["expect"], (x["name"], err)
    return c


# ---------------------------------------------------------------------------------------- read-side cases

def read_cases(base, entries, anchors):
    by_seq = {e["seq"]: e for e in entries}
    last_seq = entries[-1]["seq"]
    true_last = anchors[-1]["text"]
    bad_last = true_last[:-1] + ("0" if true_last[-1] != "0" else "1")
    anchor_seqs = [a["head_seq"] for a in anchors]
    mid = 33  # between the anchor heads 29 and 39, so withholding it leaves 30-32 unpinned
    note_seq = 20
    a1101 = next(a for a in anchors if a["date"] == "2026-11-01")
    early = a1101["head_seq"] - 1
    after_text = S.anchor_text(AGENT, "2026-11-01", by_seq[early]["entry_id"], early)
    gate_text = "gate" + true_last[len(AGENT):]
    dst_seq = next(e["seq"] for e in entries if e["timestamp"] == "2026-11-02T04:30:00Z")
    rechain_seq = next(e["seq"] for e in entries if e["kind"] == "note" and e["seq"] > 40)
    assert rechain_seq < anchors[-1]["head_seq"]
    # an anchor naming a seq whose day has a later line, with no anchor entry for that date (only the later line fails it)
    last_day = entries[-1]["day"]
    lone = [e for e in entries if e["day"] == last_day]
    assert len(lone) >= 2 and not any(e.get("anchor_date") == last_day for e in entries)
    lone_text = S.anchor_text(AGENT, last_day, lone[-2]["entry_id"], lone[-2]["seq"])
    # an anchor the chain carries, with no later line of its date, that the ledger's own anchor entry disagrees with
    own_line = next(e for e in entries if e.get("anchor_date") == "2026-11-01")
    own_text = S.anchor_text(AGENT, "2026-11-01", own_line["entry_id"], own_line["seq"])
    assert own_line["day"] != "2026-11-01"
    # an anchor whose head line is withheld: in_chain through the withheld digest, and the withheld seq equal to a head
    a1231 = next(a for a in anchors if a["date"] == "2026-12-31")
    cases = [
        {"name": "identity", "transform": {"op": "identity"}, "anchors": [true_last, bad_last],
         "coverage_anchor_seqs": anchor_seqs},
        {"name": "anchor-present", "transform": {"op": "identity"}, "anchors": [a["text"] for a in anchors]},
        {"name": "anchor-after-a-later-line", "transform": {"op": "identity"}, "anchors": [after_text]},
        {"name": "anchor-v0-word-or-other-agent", "transform": {"op": "identity"}, "anchors": [gate_text]},
        {"name": "rewrite-one-field", "transform": {"op": "set_field", "seq": note_seq, "field": "note", "value": "rewritten"}},
        {"name": "rewrite-prev", "transform": {"op": "set_field", "seq": mid, "field": "prev", "value": "0" * 64}},
        {"name": "drop-a-line", "transform": {"op": "drop_seq", "seq": mid}},
        {"name": "drop-a-line-withheld", "transform": {"op": "drop_seq", "seq": mid},
         "withheld": [{"seq": mid, "entry_id": by_seq[mid]["entry_id"]}], "anchors": [true_last],
         "coverage_anchor_seqs": anchor_seqs},
        {"name": "drop-a-line-withheld-wrong-digest", "transform": {"op": "drop_seq", "seq": mid},
         "withheld": [{"seq": mid, "entry_id": "f" * 64}]},
        {"name": "cr-byte", "transform": {"op": "crlf_first_line"}},
        {"name": "duplicate-key", "transform": {"op": "dup_key", "seq": 10, "key": "late", "value": True},
         "compare": ["ok"],
         "note": "section 4's one documented difference: the python reader drops the line (the chain breaks after it), a JSON.parse reader keeps it with its bytes flagged; both answer ok=false"},
        {"name": "truncate-last-line", "transform": {"op": "truncate_last"}, "anchors": [true_last]},
        {"name": "flip-and-rechain", "transform": {"op": "set_field_rechain", "seq": rechain_seq, "field": "note", "value": "flipped"},
         "anchors": [true_last]},
        {"name": "kind-not-declared", "transform": {"op": "set_field_rechain", "seq": note_seq, "field": "kind", "value": "send"}},
        {"name": "header-kinds-missing-started", "transform": {"op": "set_header_rechain", "field": "kinds", "value": ["anchor", "note"]}},
        {"name": "header-v0-schema", "transform": {"op": "set_header", "field": "schema", "value": S.V0_LOG_SCHEMA}
         if hasattr(S, "V0_LOG_SCHEMA") else {"op": "set_header", "field": "schema", "value": "darkflobi.gate/log/v0"}},
        {"name": "day-rewritten-at-dst-edge", "transform": {"op": "set_field_rechain", "seq": dst_seq, "field": "day", "value": "2026-11-02"}},
        {"name": "entry-schema-v0", "transform": {"op": "set_field_rechain", "seq": note_seq, "field": "schema", "value": "darkflobi.gate/entry/v0"}},
        {"name": "anchor-later-line-no-own-entry", "transform": {"op": "identity"}, "anchors": [lone_text]},
        {"name": "anchor-own-entry-disagrees", "transform": {"op": "identity"}, "anchors": [own_text]},
        {"name": "anchor-head-withheld", "transform": {"op": "drop_seq", "seq": a1231["head_seq"]},
         "withheld": [{"seq": a1231["head_seq"], "entry_id": by_seq[a1231["head_seq"]]["entry_id"]}],
         "anchors": [a1231["text"]], "coverage_anchor_seqs": anchor_seqs},
        {"name": "anchor-text-strict-form", "transform": {"op": "identity"},
         "anchors": [true_last + "\n", true_last + " ", " " + true_last, true_last + "\n\n", true_last.replace(" seq ", " seq 0"),
                     true_last.replace(" anchor ", "  anchor "), true_last.upper()]},
        # ---- added in the fix pass of 2026-11-08 (review findings 1, 3, 4, 8, 9, 10)
        {"name": "timestamp-trailing-lf-rechained",
         "transform": {"op": "set_field_rechain", "seq": rechain_seq, "field": "timestamp",
                       "value": by_seq[rechain_seq]["timestamp"] + "\n"}},
        {"name": "timestamp-fullwidth-digits-rechained",
         "transform": {"op": "set_field_rechain", "seq": rechain_seq, "field": "timestamp",
                       "value": "\uff12\uff10\uff12\uff17" + by_seq[rechain_seq]["timestamp"][4:]}},
        {"name": "drop-a-line-withheld-integral-float-seq", "transform": {"op": "drop_seq", "seq": mid},
         "withheld": [{"seq": float(mid), "entry_id": by_seq[mid]["entry_id"]}], "coverage_anchor_seqs": anchor_seqs},
        {"name": "line-nested-33-deep", "transform": {"op": "append_nested", "depth": 33}},
        {"name": "line-nested-1200-deep", "transform": {"op": "append_nested", "depth": 1200}},
        {"name": "empty-file", "transform": {"op": "replace_all", "text": ""}},
        {"name": "blank-lines-only", "transform": {"op": "replace_all", "text": "\n\n \t\n"}},
        {"name": "header-extra-key-is-not-a-verifier-problem",
         "transform": {"op": "set_header_rechain", "field": "extra", "value": 1},
         "note": "section 4: header form beyond kinds is a writer-side refusal (header_form) that the verifier does not report"},
        {"name": "seq-written-as-5.0", "transform": {"op": "replace_in_line", "seq": 5, "old": '"seq":5,', "new": '"seq":5.0,'},
         "compare": ["ok"],
         "note": "section 4: a number a javascript reader re-prints (5.0 as 5) gives different codes in the two readers; both answer ok=false"},
        {"name": "non-ascii-keys-in-code-point-order",
         "transform": {"op": "replace_in_line", "seq": note_seq, "old": '"timestamp":"%s"}' % by_seq[note_seq]["timestamp"],
                       "new": '"timestamp":"%s","\uff5e":1,"\U0001F600":2}' % by_seq[note_seq]["timestamp"]},
         "compare": ["ok"],
         "note": "section 4: dump order is defined for admitted keys only; a python reader orders u+ff5e first, a utf-16 reader u+1f600 first; both answer ok=false"},
    ]
    for cs in cases:
        text = RV.apply(S, base, cs["transform"])
        cs["input_sha256"] = hashlib.sha256(text).hexdigest()
        cs["expect"] = RV.answer_read(S, text, cs)
    return cases


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    base, entries, anchors = play()
    r = S.verify_bytes(base)
    assert r["ok"], r["problems"]
    assert len(base.split(b"\n")) - 1 == 60, "the base is 60 lines"
    doc = {
        "schema": "styxx.ledger/vectors/v1",
        "protocol": "PROTOCOL_v1.md",
        "base": "base_v1.jsonl",
        "base_sha256": hashlib.sha256(base).hexdigest(),
        "base_lines": 60,
        "base_entries": len(entries),
        "base_head": r["head"],
        "base_anchor_texts": [x["text"] for x in anchors],
        "made_by": "vectors/make_vectors.py with styxx_ledger (python); every expect is the python answer, re-asked by both runners",
        "note": ("read: apply `transform` to the base (the result must hash to input_sha256), verify it with `withheld` and the "
                 "`anchors` texts, and answer as `expect` says (only the keys in `compare` when a case names them). problem_seqs: "
                 "the seqs carrying a problem; problems_without_seq: the count of problem records naming no seq (reading and "
                 "header problems); problem_codes: the sorted set of codes; anchors_ok: check_anchor(...).ok per text, with the "
                 "header; coverage: coverage(entries, withheld, coverage_anchor_seqs). write: call `fn` on the given arguments "
                 "and compare the string value (build_entry: the canonical line of the entry; check_header: the header's "
                 "digest, when the header is one a writer may write; compose_anchor: the anchor text of `date` at `now`, "
                 "composed over the base's header and entries), or the refusal's code."),
        "read": read_cases(base, entries, anchors),
        "write": write_cases(entries, base),
    }
    vtext = (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    targets = [(HERE / "base_v1.jsonl", base), (HERE / "vectors_v1.json", vtext)]
    differs = []
    for p, b in targets:
        if p.exists() and p.read_bytes() != b:
            differs.append(p.name)
    if a.check:
        print(json.dumps({"differs": differs, "read": len(doc["read"]), "write": len(doc["write"])}))
        return 1 if differs else 0
    if differs and not a.force:
        print("refusing: %s already exist(s) with other bytes; a receipt is history (use --force and log it)" % differs)
        return 3
    for p, b in targets:
        p.write_bytes(b)
        if p.read_bytes() != b:
            print("write did not land: %s" % p)
            return 4
    print(json.dumps({"base_sha256": doc["base_sha256"], "base_head": doc["base_head"], "read": len(doc["read"]),
                      "write": len(doc["write"]), "total": len(doc["read"]) + len(doc["write"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
