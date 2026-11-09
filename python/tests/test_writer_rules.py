"""writer rules settled in the lab's improvement sweep of 2026-11-09, python side (js/tests/writer_rules.test.js is
the javascript side; the shared vectors pin both):

    rank 42  compose_anchor refuses a day that has not closed in anchor_tz (day_open), a day the ledger already
             anchors (already_anchored) and a day with no line (nothing_to_anchor). until then the python writer
             composed a postable text for an open or an anchored day, which section 5's check then failed.
    rank 43  a certifies made only of whitespace is refused (header_form), whitespace being the 30 code points spelled
             out in PROTOCOL_v1 section 1: the union of python's str.isspace and javascript's String.prototype.trim.
    rank 68  strings are never normalised: an nfc and an nfd spelling give two lines with two entry_ids.

every non-ascii character here is written with chr(), so this file's bytes say which code point is meant.
"""
import json

import pytest

import styxx_ledger as S
from styxx_ledger import Ledger, LedgerStateError, LedgerValueError
from styxx_ledger.chain import CERTIFIES_BLANK

CERT = "one line per event the rules test was handed"
BLANK30 = [0x9, 0xA, 0xB, 0xC, 0xD, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x85, 0xA0, 0x1680] + list(range(0x2000, 0x200B)) \
    + [0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]


def new(tmp_path, certifies=CERT, tz="America/New_York", name="log.jsonl"):
    return Ledger.create(tmp_path / name, agent="rulebot", anchor_tz=tz, certifies=certifies, kinds=["note"],
                         created="2026-10-31T12:00:00Z")


def state_code(fn):
    with pytest.raises(LedgerStateError) as ei:
        fn()
    return ei.value.code


# ------------------------------------------------------------------------------------------ rank 42: compose

def test_compose_refuses_a_day_that_has_not_closed(tmp_path):
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    led.append("note", {"n": 1}, timestamp="2026-10-31T20:00:00Z")
    before = led.path.read_bytes()
    with pytest.raises(LedgerStateError) as ei:                               # 19:00 edt on the 31st
        led.compose_anchor("2026-10-31", now="2026-10-31T23:00:00Z")
    assert ei.value.code == "day_open"
    assert str(ei.value) == "2026-10-31 has not closed in America/New_York (it is 2026-10-31 there)"
    assert state_code(lambda: led.compose_anchor("2026-10-31", now="2026-11-01T03:59:59Z")) == "day_open"   # 23:59:59 edt
    assert state_code(lambda: led.compose_anchor("2026-11-02", now="2026-11-01T12:00:00Z")) == "day_open"   # a later day
    c = led.compose_anchor("2026-10-31", now="2026-11-01T04:00:00Z")          # 00:00:00 edt on the 1st: closed
    assert c["seq"] == 2 and c["text"] == "rulebot anchor 2026-10-31 head %s seq 2" % c["head"]
    assert led.path.read_bytes() == before                                    # composing writes nothing


def test_compose_refuses_an_anchored_day_and_a_day_with_no_line(tmp_path):
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    led.append_anchor("2026-10-31", timestamp="2026-11-01T04:00:05Z")
    assert state_code(lambda: led.compose_anchor("2026-10-31", now="2026-11-02T12:00:00Z")) == "already_anchored"
    assert state_code(lambda: led.compose_anchor("2026-10-30", now="2026-11-02T12:00:00Z")) == "nothing_to_anchor"
    with pytest.raises(LedgerValueError) as ei:
        led.compose_anchor("2026-10-3", now="2026-11-02T12:00:00Z")
    assert ei.value.code == "anchor_form"


def test_compose_and_append_anchor_refuse_alike_and_in_one_order(tmp_path):
    """the module function, Ledger.compose_anchor and Ledger.append_anchor answer alike; when a day is both open and
    anchored (a clock that stepped back), day_open is named before already_anchored, as in javascript."""
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    led.append_anchor("2026-10-31", timestamp="2026-11-01T04:00:05Z")
    r = led.verify()
    assert state_code(lambda: S.compose_anchor(r["header"], r["entries"], "2026-10-31", "2026-10-31T23:00:00Z")) == "day_open"
    assert state_code(lambda: led.append_anchor("2026-10-31", timestamp="2026-11-02T12:00:00Z")) == "already_anchored"
    led.append("note", {"n": 2}, timestamp="2026-11-01T15:00:00Z")
    assert state_code(lambda: led.append_anchor("2026-11-01", timestamp="2026-11-01T23:00:00Z")) == "day_open"
    a = S.compose_anchor(r["header"], led.verify()["entries"], "2026-11-01", "2026-11-02T05:00:00Z")
    assert a == dict(led.compose_anchor("2026-11-01", now="2026-11-02T05:00:00Z"))
    assert a["agent"] == "rulebot" and a["date"] == "2026-11-01" and a["seq"] == 3   # the anchor entry, then the note


def test_cli_anchor_text_refuses_an_open_day_with_its_code(cli, tmp_path):
    log = tmp_path / "a.jsonl"
    cp = cli("init", log, "--agent", "clibot", "--tz", "UTC", "--certifies", CERT, "--created", "2026-11-09T01:00:00Z",
             "--timestamp", "2026-11-09T01:00:01Z")
    assert cp.returncode == 0, cp.stderr
    before = log.read_bytes()
    for extra in ((), ("--record",)):
        cp = cli("anchor-text", log, "--date", "2026-11-09", "--timestamp", "2026-11-09T01:30:00Z", *extra)
        assert cp.returncode == 1 and cp.stdout == ""
        assert "styxx-ledger: refused (day_open): 2026-11-09 has not closed in UTC (it is 2026-11-09 there)" in cp.stderr
    assert log.read_bytes() == before
    cp = cli("anchor-text", log, "--date", "2026-11-09", "--timestamp", "2026-11-10T00:00:00Z", "--record")
    assert cp.returncode == 0, cp.stderr
    cp = cli("anchor-text", log, "--date", "2026-11-09", "--timestamp", "2026-11-10T00:05:00Z")
    assert cp.returncode == 1 and "refused (already_anchored)" in cp.stderr


# -------------------------------------------------------------------------------- rank 43: the blank set

def test_the_blank_set_is_the_union_of_both_runtimes():
    assert sorted(ord(ch) for ch in CERTIFIES_BLANK) == sorted(BLANK30) and len(set(CERTIFIES_BLANK)) == 30
    isspace = {chr(cp) for cp in range(0x110000) if chr(cp).isspace()}
    assert set(CERTIFIES_BLANK) == isspace | {chr(0xFEFF)}                   # javascript's trim adds u+feff alone


@pytest.mark.parametrize("cp", BLANK30, ids=["u+%04x" % cp for cp in BLANK30])
def test_a_certifies_of_one_blank_is_refused_and_a_blank_inside_a_sentence_is_not(tmp_path, cp):
    with pytest.raises(LedgerValueError) as ei:
        new(tmp_path, certifies=chr(cp) * 3)
    assert ei.value.code == "header_form" and not (tmp_path / "log.jsonl").exists()
    if cp != 0xA:                                                             # an lf is refused anywhere (one line)
        led = new(tmp_path, certifies="one" + chr(cp) + "sentence", name="ok.jsonl")
        assert json.loads(led.path.read_bytes())["certifies"] == "one" + chr(cp) + "sentence"


@pytest.mark.parametrize("cert", [chr(0x200B), chr(0x180E), chr(0x2060), "x" * 500, chr(0x1F642) * 500],
                         ids=["u+200b", "u+180e", "u+2060", "500-chars", "500-astral-chars"])
def test_outside_the_set_and_within_500_code_points_is_accepted(tmp_path, cert):
    assert json.loads(new(tmp_path, certifies=cert).path.read_bytes())["certifies"] == cert


def test_a_log_whose_certifies_is_blank_is_refused_by_the_writer(tmp_path):
    """the python writer accepted a certifies of u+feff alone until 2026-11-09 (javascript refused it); such a file
    still re-derives (the verifier does not judge header form), and now neither writer appends to it."""
    hdr = {"schema": S.LOG_SCHEMA, "created": "2026-10-31T12:00:00Z", "anchor_tz": "UTC", "agent": "rulebot",
           "certifies": chr(0xFEFF), "kinds": ["anchor", "note", "started"]}
    p = tmp_path / "old.jsonl"
    p.write_bytes((S.dump(hdr) + "\n").encode("utf-8"))
    assert S.verify_bytes(p.read_bytes())["ok"]
    with pytest.raises(LedgerValueError) as ei:
        Ledger(p).append("note", {"n": 1}, timestamp="2026-11-01T00:00:00Z")
    assert ei.value.code == "header_form" and p.read_bytes().count(b"\n") == 1


# ---------------------------------------------------------------------------- rank 68: never normalised

def test_strings_are_never_normalised(tmp_path):
    nfc, nfd = chr(0xE9), "e" + chr(0x301)
    a, b = new(tmp_path, name="nfc.jsonl"), new(tmp_path, name="nfd.jsonl")
    ea = a.append("note", {"s": nfc}, timestamp="2026-11-01T00:00:00Z")
    eb = b.append("note", {"s": nfd}, timestamp="2026-11-01T00:00:00Z")
    assert ea["entry_id"] != eb["entry_id"]
    la, lb = a.path.read_bytes().split(b"\n")[1], b.path.read_bytes().split(b"\n")[1]
    assert b'"s":"\xc3\xa9"' in la and b'"s":"e\xcc\x81"' in lb               # the code points as given, raw utf-8
    assert S.verify_bytes(a.path.read_bytes())["ok"] and S.verify_bytes(b.path.read_bytes())["ok"]
