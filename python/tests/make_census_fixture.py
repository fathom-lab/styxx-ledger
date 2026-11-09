#!/usr/bin/env python3
"""make_census_fixture.py: the census scorer's fixtures (tests/fixtures/census/).

    python -I -B tests/make_census_fixture.py [--check] [--template PATH] [--expected]

ledger.jsonl      a synthetic v1 ledger written by styxx_ledger.Ledger with every timestamp given: 11 lines (the
                  header and 10 entries), 3 anchor lines, agent censusbot, anchor_tz America/New_York, window opening
                  2026-10-01. pre-window: the started line (2026-09-29) and the anchor of 2026-09-29 (posted 00:05 edt
                  on the 30th), which the shelf reads. window: five sends (four to chan-1, one to dm-9), one note, two
                  anchors (2026-10-01 on time, 2026-10-02 late), one send after the last anchor line.
anchors.json      the posted anchor texts (how to fill (e)): the three anchor lines' texts and a posted text for
                  2026-10-03 the ledger carries no anchor line for (heads may be posted without a line, P1 section 5).
shelf_report.json a synthetic shelf report naming the ledger url, the earliest anchor and its head.
export_held.json  an export of chan-1 holding the four chan-1 texts (one padded with spaces, matched under the
                  `strip` rule), one enumerated native string, and one dm-9 message outside the population.
export_open.json  the same plus one chan-1 message no line carries.
PREREG_filled.md  the census template (PREREG_census_TEMPLATE.md, THE_PLAN 3d) filled in its "how to fill" form, with
                  the three section-15 entries sealed over the bytes above section 15. built only when --template
                  names the template (it lives outside the kit); otherwise left as committed.
expected_RESULT.json  with --expected: the scorer's output at now 2026-11-01T00:00:00Z without the export and without
                  posted anchors, under the test seams below (fetch map, shelf row on, the js leg answered by the
                  python verifier); its counts are the ones listed in test_census.py's docstring, checked by hand.
a fixture is a receipt: an existing file with other bytes is refused, never overwritten.

the test seams (used by tests/test_census.py and --expected): census._fetch_once answers the fixture's example.invalid
urls from the files here; census.SHELF_HAS_V1_ROW is set True so (c) can hold; census._js_verify is answered by the
python verifier (the real js leg is exercised by test_js_leg_agrees_when_node_is_here).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from styxx_ledger import Ledger, header_digest  # noqa: E402
from styxx_ledger.chain import anchor_text  # noqa: E402
from styxx_ledger.verify import verify_bytes  # noqa: E402

FIX = HERE / "fixtures" / "census"
TZ = "America/New_York"
CREATED = "2026-09-29T15:59:00Z"
WRITER = {"name": "styxx-ledger", "version": "1.0.0a1", "language": "python"}
CERTIFIES = "one line per message censusbot delivered, chained; the sha256 of the delivered text, never the text"
LEDGER_URL = "https://example.invalid/censusbot/ledger.jsonl"
SHELF_URL = "https://example.invalid/shelf/censusbot.json"
REG_URL = "https://example.invalid/opfixture/census/pull/1"
REG_COMMIT = hashlib.sha1(b"census fixture registration commit").hexdigest()
SHELF_AT = "2026-09-30T12:00:00Z"
SIGNED_AT = "2026-09-30T18:00:00Z"
NOW = "2026-11-01T00:00:00Z"
TEXTS = {
    "t1": "census fixture message one: 2 numerals, 1 bound",
    "t2": "census fixture message two",
    "t3": "census fixture message three, sent to a private place",
    "t4": "census fixture message four",
    "t5": "census fixture message five, after the last anchor",
}


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


STEPS = [
    ("start", "2026-09-29T16:00:00Z", None),
    ("anchor", "2026-09-30T04:05:00Z", {"date": "2026-09-29"}),     # 00:05 edt on the 30th: pre-window, on time
    ("send", "2026-10-01T14:00:00Z", {"dest": "chan-1", "sent_sha256": h(TEXTS["t1"]), "numerals": {"total": 2, "bound": 1, "unbound": 1}}),
    ("send", "2026-10-01T15:00:00Z", {"dest": "chan-1", "sent_sha256": h(TEXTS["t2"]), "numerals": {"total": 1, "bound": 1, "unbound": 0}}),
    ("send", "2026-10-01T16:00:00Z", {"dest": "dm-9", "sent_sha256": h(TEXTS["t3"]), "numerals": {"total": 5, "bound": 0, "unbound": 5}}),
    ("anchor", "2026-10-02T04:05:00Z", {"date": "2026-10-01"}),     # 00:05 edt on the 2nd: on time
    ("send", "2026-10-02T14:00:00Z", {"dest": "chan-1", "sent_sha256": h(TEXTS["t4"]), "numerals": {"total": 0, "bound": 0, "unbound": 0}}),
    ("note", "2026-10-02T15:00:00Z", {"note": "a line of a kind that is not a delivery"}),
    ("anchor", "2026-10-03T05:00:00Z", {"date": "2026-10-02"}),     # 01:00 edt on the 3rd: late by section 5
    ("send", "2026-10-03T14:00:00Z", {"dest": "chan-1", "sent_sha256": h(TEXTS["t5"])}),
]


def build_ledger(path: Path) -> dict:
    led = Ledger.create(path, agent="censusbot", anchor_tz=TZ, certifies=CERTIFIES, kinds=["note", "send"],
                        created=CREATED)
    anchors = []
    for what, ts, f in STEPS:
        if what == "start":
            led.start(writer=WRITER, timestamp=ts)
        elif what == "anchor":
            anchors.append(led.append_anchor(f["date"], timestamp=ts)["text"])
        else:
            led.append(what, f, timestamp=ts)
    r = verify_bytes(path.read_bytes())
    last = r["entries"][-1]["entry"]
    posted_last = anchor_text("censusbot", "2026-10-03", last["entry_id"], last["seq"])
    return {"anchors": anchors, "posted_last": posted_last, "header_digest": header_digest(led.header)}


def anchors_index(meta: dict) -> bytes:
    a = meta["anchors"]
    doc = {"anchors": [{"text": a[0], "late": False}, {"text": a[1], "late": False}, {"text": a[2], "late": True},
                       {"text": meta["posted_last"], "late": False}],
           "note": "synthetic posted texts for the census fixture; no place posted them"}
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")


def shelf_report(meta: dict) -> bytes:
    doc = {"shelf": "census fixture (synthetic; no shelf ran)", "ledger_url": LEDGER_URL, "read_at": SHELF_AT,
           "rederives": True, "earliest_anchor": meta["anchors"][0]}
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")


def export(extra: bool) -> bytes:
    msgs = [
        {"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-01T14:00:02Z", "text": TEXTS["t1"]},
        {"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-01T15:00:02Z", "text": "  " + TEXTS["t2"] + " "},
        {"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-02T14:00:02Z", "text": TEXTS["t4"]},
        {"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-03T14:00:02Z", "text": TEXTS["t5"]},
        {"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-03T20:00:00Z", "text": "censusbot pinned a message"},
        {"account": "censusbot#0001", "destination": "dm-9", "timestamp": "2026-10-01T16:00:02Z", "text": TEXTS["t3"]},
        {"account": "someone-else", "destination": "chan-1", "timestamp": "2026-10-01T14:30:00Z", "text": "a reader's reply"},
    ]
    if extra:
        msgs.append({"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-04T12:00:00Z",
                     "text": "a message the writer never saw"})
    doc = {"destinations": ["chan-1"], "made_at": "2026-10-29T12:00:00Z", "messages": msgs,
           "tool": "tests/make_census_fixture.py (synthetic; no platform)"}
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")


def values(meta: dict) -> dict:
    return {
        "operator": "opfixture",
        "agent": "censusbot",
        "agent_description": "a synthetic test agent written by the kit's own writer, posting nowhere",
        "agent_account": "censusbot#0001",
        "ledger_url": LEDGER_URL,
        "withheld_url": "none",
        "anchors_url": "none",
        "anchor_place": "https://example.invalid/censusbot/anchors (fixture: tests pass anchors.json as the posted texts)",
        "anchor_tz": TZ,
        "certifies": CERTIFIES,
        "kinds": "anchor,note,send,started",
        "delivery_kinds": "send",
        "sent_hash_field": "sent_sha256",
        "destination_field": "dest",
        "public_destinations": "chan-1 https://example.invalid/chan-1",
        "census_source": "the fixture's synthetic json export (tests/make_census_fixture.py)",
        "census_tool_sha256": "none",
        "normalisation_rule": "strip",
        "native_strings": "[\"censusbot pinned a message\"]",
        "numerals_field": "numerals",
        "d0": "2026-10-01",
        "close": "2026-10-29",
        "min_deliveries": "3",
        "own_commitment": "none",
        "registration_url": REG_URL,
        "registration_date": "2026-09-30",
        "gates_sha256": "GATES_SHA",
        "header_digest": meta["header_digest"],
        "writer": "styxx-ledger 1.0.0a1 python",
        "earliest_anchor": meta["anchors"][0],
        "scorer_sha256": "not built at the freeze",
        "kit_version": "styxx-ledger 1.0.0a1",
    }


ENTRIES_MARK = "\n### 15.1 — "


def seal(text: str, shelf_sha: str, operator: str = "opfixture", agent: str = "censusbot", d0: str = "2026-10-01",
         tz: str = TZ) -> str:
    """append (or re-append) the three section-15 entries, sealed over the bytes above section 15 as they stand."""
    i = text.find(ENTRIES_MARK)
    if i >= 0:
        text = text[: i + 1]
    m = re.search(r"(?m)^## 15\.", text)
    digest = hashlib.sha256(text[: m.start()].encode("utf-8")).hexdigest()
    if not text.endswith("\n"):
        text += "\n"
    return text + (
        "\n### 15.1 — 2026-09-30: the registration\n\n"
        "    registered: %s commit %s registration_sha256 %s\n\n"
        "### 15.2 — 2026-09-30: the shelf read\n\n"
        "    shelf read: %s sha256 %s at %s\n\n"
        "### 15.3 — 2026-09-30: the signature line for window 1\n\n"
        "    window 1: I, %s, run %s and register the census of %s, opening %s 00:00 %s; signed %s.\n"
        % (REG_URL, REG_COMMIT, digest, SHELF_URL, shelf_sha, SHELF_AT, operator, agent, digest, d0, tz, SIGNED_AT))


def regate(text: str) -> str:
    """rewrite the table's gates_sha256 to the block's digest as it stands (an operator re-hashing an edited block)."""
    g = re.search(r"^```gates[ \t]*\n(.*?)^```[ \t]*$", text, re.M | re.S)
    d = hashlib.sha256(g.group(1).encode("utf-8")).hexdigest()
    return re.sub(r"^\| gates_sha256 = `[^`]*` \|", "| gates_sha256 = `%s` |" % d, text, count=1, flags=re.M)


def fill(template: str, vals: dict, shelf_sha: str) -> str:
    def row(m):
        return "| %s = `%s` |" % (m.group(1), vals[m.group(1)])
    out = re.sub(r"^\| `\{\{([a-z0-9_]+)\}\}` \|", row, template, flags=re.M)

    def cut(v: str) -> str:
        i = v.find(" (")
        return v[:i] if i > 0 and v.endswith(")") else v
    out = re.sub(r"\{\{([a-z0-9_]+)\}\}", lambda m: cut(vals[m.group(1)]), out)
    g = re.search(r"^```gates[ \t]*\n(.*?)^```[ \t]*$", out, re.M | re.S)
    out = out.replace("GATES_SHA", hashlib.sha256(g.group(1).encode("utf-8")).hexdigest())
    return seal(out, shelf_sha)


# ---------------------------------------------------------------------------------------------- test seams

def fetch_map() -> dict:
    return {LEDGER_URL: FIX / "ledger.jsonl", SHELF_URL: FIX / "shelf_report.json"}


def install_seams(census, setattr_):
    """the seams of the module docstring; setattr_ is monkeypatch.setattr or builtins.setattr."""
    from styxx_ledger.v0 import verify_auto
    real = census._fetch_once
    mp = fetch_map()

    def fake_fetch(src):
        if src in mp:
            return mp[src].read_bytes(), {"source": src, "http_status": 200}
        if src.startswith("https://example.invalid/"):
            raise census.Refused("unreachable", "%s did not answer within 30 s: URLError" % src)
        return real(src)

    def fake_js(raw, wh):
        r = verify_auto(raw, withheld=wh)
        return {"status": "measured", "ok": r["ok"], "head": r["head"], "entries": len(r["entries"]),
                "protocol": r["protocol"]}
    setattr_(census, "_fetch_once", fake_fetch)
    setattr_(census, "SHELF_HAS_V1_ROW", True)
    setattr_(census, "_js_verify", fake_js)


def expected_bytes() -> bytes:
    from styxx_ledger import census
    saved = (census._fetch_once, census.SHELF_HAS_V1_ROW, census._js_verify)
    try:
        install_seams(census, setattr)
        with tempfile.TemporaryDirectory() as d:
            census.score(FIX / "PREREG_filled.md", LEDGER_URL, Path(d), NOW, js=True)
            return (Path(d) / "RESULT.json").read_bytes()
    finally:
        census._fetch_once, census.SHELF_HAS_V1_ROW, census._js_verify = saved


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    check = "--check" in argv
    template = argv[argv.index("--template") + 1] if "--template" in argv else None
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ledger.jsonl"
        meta = build_ledger(p)
        raw = p.read_bytes()
    shelf = shelf_report(meta)
    targets = [(FIX / "ledger.jsonl", raw), (FIX / "anchors.json", anchors_index(meta)),
               (FIX / "shelf_report.json", shelf), (FIX / "export_held.json", export(False)),
               (FIX / "export_open.json", export(True))]
    if template:
        filled = fill(Path(template).read_text(encoding="utf-8"), values(meta), hashlib.sha256(shelf).hexdigest())
        if "{{" in filled:
            print("refusing: the filled prereg still holds a placeholder")
            return 5
        targets.append((FIX / "PREREG_filled.md", filled.encode("utf-8")))
    differs = [t.name for t, b in targets if t.exists() and t.read_bytes() != b]
    if check:
        if "--expected" in argv:
            e = FIX / "expected_RESULT.json"
            got = json.loads(expected_bytes())
            want = json.loads(e.read_bytes()) if e.exists() else None
            if want is not None:
                got["scorer"].pop("sha256", None)
                want["scorer"].pop("sha256", None)
            if got != want:
                differs.append(e.name)
        print(json.dumps({"differs": differs, "anchors": meta["anchors"]}))
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
    written = [t.name for t, _ in targets]
    if "--expected" in argv:
        e = FIX / "expected_RESULT.json"
        b = expected_bytes()

        def core(x: bytes) -> dict:
            d = json.loads(x)
            d["scorer"].pop("sha256", None)
            return d
        if e.exists() and core(e.read_bytes()) != core(b):
            print("refusing: expected_RESULT.json exists with other bytes (delete it by hand and log why)")
            return 3
        if not e.exists():
            e.write_bytes(b)
            written.append(e.name)
    print(json.dumps({"written": written, "anchors": meta["anchors"], "header_digest": meta["header_digest"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
