"""the verifier API (verify_bytes, check_anchor, coverage), withheld bridging, and the core's edges."""
import json

import pytest

import styxx_ledger as S
from styxx_ledger import Ledger, LedgerValueError
from conftest import VECTORS

BASE = (VECTORS / "base_v1.jsonl").read_bytes()
DOC = json.loads((VECTORS / "vectors_v1.json").read_text("utf-8"))


def lines_of(raw):
    return [ln for ln in raw.split(b"\n") if ln.strip()]


def drop(raw, seq):
    out = [ln for ln in lines_of(raw) if json.loads(ln).get("seq") != seq]
    return b"\n".join(out) + b"\n"


def entry(raw, seq):
    return next(json.loads(ln) for ln in lines_of(raw) if json.loads(ln).get("seq") == seq)


def test_base_rederives_and_states_its_head():
    r = S.verify_bytes(BASE)
    assert r["ok"] and r["problems"] == [] and r["bridged"] == []
    assert len(r["entries"]) == 59 and r["head"] == DOC["base_head"]
    assert r["header"]["agent"] == "kitbot"
    assert r["file_sha256"] == DOC["base_sha256"]


def test_every_posted_base_anchor_holds():
    r = S.verify_bytes(BASE)
    for t in DOC["base_anchor_texts"]:
        a = S.check_anchor(r["entries"], S.parse_anchor_text(t), [], r["header"])
        assert a["ok"], (t, a)


def test_empty_and_header_only():
    for raw in (b"", b"\n", b"\n\n \t\n"):            # review finding 8: no header is a problem, entries or not
        r = S.verify_bytes(raw)
        assert not r["ok"] and r["head"] is None
        assert {c for p in r["problems"] for c in (p.get("codes") or [p.get("code")])} == {"no_header"}
    hdr = BASE.split(b"\n")[0] + b"\n"
    r = S.verify_bytes(hdr)
    assert r["ok"] and r["head"] == S.header_digest(json.loads(hdr))


def test_withheld_integral_float_seq_bridges():
    """review finding 4: a withheld seq of 20.0 is the integer 20, as javascript reads it."""
    e = entry(BASE, 20)
    cut = drop(BASE, 20)
    r = S.verify_bytes(cut, withheld=[{"seq": 20.0, "entry_id": e["entry_id"], "reason": "test"}])
    assert r["ok"] and r["bridged"] == [20]
    assert S.coverage(r["entries"], [{"seq": 20.0, "entry_id": e["entry_id"]}], [])["withheld"] == 1
    assert not S.verify_bytes(cut, withheld=[{"seq": 20.5, "entry_id": e["entry_id"]}])["ok"]


def test_deep_line_is_unparsable_not_a_crash():
    """review finding 3: a line nested 1200 deep is reported, not a RecursionError."""
    line = b'{"deep":' + b"[" * 1199 + b"1" + b"]" * 1199 + b"}"
    r = S.verify_bytes(BASE + line + b"\n")
    assert not r["ok"]
    assert [p["code"] for p in r["problems"]] == ["unparsable"]


def test_year_edges_are_a_day_problem_not_a_crash():
    """review finding 2: a year-0001 timestamp in a non-utc zone is a `day` problem, not an OverflowError."""
    hdr = json.loads(BASE.split(b"\n")[0])
    e = S.build_entry(hdr, 1, S.header_digest(hdr), "note", "2026-11-01T00:00:00Z", {})
    e["timestamp"], e["day"] = "0001-01-01T00:00:00Z", "0001-01-01"
    e.pop("entry_id"); e["entry_id"] = S.entry_id_of(e)
    r = S.verify_bytes((S.dump(hdr) + "\n" + S.dump(e) + "\n").encode("utf-8"))
    assert not r["ok"] and r["problems"][0]["codes"] == ["day"]


def test_anchor_seq_over_2_53_does_not_parse():
    assert S.parse_anchor_text("kitbot anchor 2026-10-31 head " + "a" * 64 + " seq 99999999999999999999") is None
    assert S.parse_anchor_text("kitbot anchor 2026-10-31 head " + "a" * 64 + " seq 9007199254740992") is not None


def test_withheld_bridging():
    e = entry(BASE, 20)
    cut = drop(BASE, 20)
    assert not S.verify_bytes(cut)["ok"]
    r = S.verify_bytes(cut, withheld=[{"seq": 20, "entry_id": e["entry_id"], "reason": "test"}])
    assert r["ok"] and r["bridged"] == [20]
    bad = S.verify_bytes(cut, withheld=[{"seq": 20, "entry_id": "f" * 64}])
    assert not bad["ok"] and {p["seq"] for p in bad["problems"]} == {21}


def test_withheld_run_of_two_and_the_tail():
    e20, e21 = entry(BASE, 20), entry(BASE, 21)
    cut = drop(drop(BASE, 20), 21)
    r = S.verify_bytes(cut, withheld=[{"seq": 20, "entry_id": e20["entry_id"]}, {"seq": 21, "entry_id": e21["entry_id"]}])
    assert r["ok"] and r["bridged"] == [20, 21]


def test_coverage_counts_what_withholding_unpins():
    seqs = [S.parse_anchor_text(t)["seq"] for t in DOC["base_anchor_texts"]]
    e = entry(BASE, 33)
    cut = drop(BASE, 33)
    r = S.verify_bytes(cut, withheld=[{"seq": 33, "entry_id": e["entry_id"]}])
    cov = S.coverage(r["entries"], [{"seq": 33, "entry_id": e["entry_id"]}], seqs)
    assert cov["withheld"] == 1 and cov["last_anchor_seq"] == max(seqs)
    assert cov["unpinned_by_withholding"] > 0
    assert cov["pinned"] + cov["unpinned_by_withholding"] + cov["after_last_anchor"] == len(r["entries"])
    full = S.coverage(S.verify_bytes(BASE)["entries"], [], seqs)
    assert full["unpinned_by_withholding"] == 0 and full["after_last_anchor"] == 59 - max(seqs)


def test_anchor_from_another_agent_does_not_hold():
    r = S.verify_bytes(BASE)
    a = S.parse_anchor_text(DOC["base_anchor_texts"][0])
    a["agent"] = "gate"
    out = S.check_anchor(r["entries"], a, [], r["header"])
    assert not out["ok"] and not out["agent_matches"] and out["in_chain"]


@pytest.mark.parametrize("text", [
    "kitbot anchor 2026-10-31 head " + "a" * 64 + " seq 01",
    "kitbot anchor 2026-10-31 head " + "A" * 64 + " seq 1",
    " kitbot anchor 2026-10-31 head " + "a" * 64 + " seq 1",
    "kitbot anchor 2026-10-31 head " + "a" * 64 + " seq 1\n\n",
    "kitbot  anchor 2026-10-31 head " + "a" * 64 + " seq 1",
    "gate anchor 2026-10-31 head " + "a" * 63 + " seq 1",
])
def test_parse_anchor_text_is_strict(text):
    assert S.parse_anchor_text(text) is None


def test_parse_anchor_text_tolerates_one_lf():
    t = "kitbot anchor 2026-10-31 head " + "a" * 64 + " seq 0"
    assert S.parse_anchor_text(t + "\n") == S.parse_anchor_text(t) == {"agent": "kitbot", "date": "2026-10-31",
                                                                        "head": "a" * 64, "seq": 0}


def test_v0_log_is_named_not_read():
    v0 = b'{"anchor_tz":"America/New_York","certifies":"x","created":"2026-10-24T00:00:00Z","schema":"darkflobi.gate/log/v0"}\n' \
         b'{"schema":"darkflobi.gate/entry/v0","seq":1}\n'
    r = S.verify_bytes(v0)
    assert not r["ok"] and r["header"] is None
    msgs = [p.get("problem") or "" for p in r["problems"]]
    assert any("reads v1 only" in m for m in msgs)


def test_duplicate_key_is_dropped_by_the_python_reader():
    ls = lines_of(BASE)
    ls[5] = ls[5][:-1] + b',"kind":"note"}'
    r = S.verify_bytes(b"\n".join(ls) + b"\n")
    assert not r["ok"] and "duplicate_key" in {p.get("code") for p in r["problems"]}


@pytest.mark.parametrize("bad", [b'{"a":1.0}', b'{"a":NaN}', b"[1,2]", b"\xff\xfe"])
def test_reader_never_raises_on_content(bad):
    r = S.verify_bytes(BASE + bad + b"\n")
    assert not r["ok"]


def test_problem_records_carry_seq_and_codes():
    ls = lines_of(BASE)
    o = json.loads(ls[3])
    o["day"] = "1999-01-01"
    ls[3] = S.dump(o).encode("utf-8")
    r = S.verify_bytes(b"\n".join(ls) + b"\n")
    recs = [p for p in r["problems"] if p.get("seq") is not None]
    assert recs and recs[0]["seq"] == o["seq"]
    assert {"day", "entry_id"} <= set(recs[0]["codes"])


# ----------------------------------------------------------------------------------------------- core edges

def test_jcs_matches_the_byte_rules():
    assert S.jcs({"b": 1, "a": [True, None, "é\n"]}) == '{"a":[true,null,"é\\n"],"b":1}'
    assert S.jcs({"x": 2 ** 53, "y": -(2 ** 53)}) == '{"x":9007199254740992,"y":-9007199254740992}'
    for v, code in [(1.0, "float"), ({"k": 2 ** 53 + 1}, "int_range"), ({"\x7f": 1}, "non_ascii_key"),
                    (object(), "type"), ({1: 2}, "type")]:
        with pytest.raises(LedgerValueError) as ei:
            S.jcs(v)
        assert ei.value.code == code


@pytest.mark.parametrize("ts,tz,day", [
    ("2026-11-01T05:59:59Z", "America/New_York", "2026-11-01"),
    ("2026-11-02T04:59:59Z", "America/New_York", "2026-11-01"),
    ("2026-03-08T04:59:59Z", "America/New_York", "2026-03-07"),
    ("2026-10-24T21:59:59Z", "Europe/Berlin", "2026-10-24"),
    ("2026-10-25T22:59:59Z", "Europe/Berlin", "2026-10-25"),
    ("2026-12-31T23:59:59Z", "UTC", "2026-12-31"),
    ("2026-06-30T14:00:00Z", "Asia/Kolkata", "2026-06-30"),
    ("2026-06-30T18:30:00Z", "Asia/Kolkata", "2026-07-01"),
])
def test_day_of(ts, tz, day):
    assert S.day_of(ts, tz) == day


def test_day_of_refuses_an_unknown_zone():
    with pytest.raises(LedgerValueError) as ei:
        S.day_of("2026-11-01T00:00:00Z", "Nowhere/Atlantis")
    assert ei.value.code == "anchor_tz"


def test_verify_on_a_written_log_with_kinds_out_of_header(tmp_path):
    led = Ledger.create(tmp_path / "l.jsonl", agent="t", anchor_tz="UTC", certifies="c", kinds=["note"],
                        created="2026-10-31T00:00:00Z")
    led.append("note", {}, timestamp="2026-10-31T00:00:01Z")
    ls = lines_of(led.path.read_bytes())
    o = json.loads(ls[1])
    o["kind"] = "send"
    o.pop("entry_id")
    o["entry_id"] = S.entry_id_of(o)
    led.path.write_bytes(ls[0] + b"\n" + S.dump(o).encode("utf-8") + b"\n")
    r = led.verify()
    assert not r["ok"] and r["problems"][0]["codes"] == ["kind_not_declared"]
