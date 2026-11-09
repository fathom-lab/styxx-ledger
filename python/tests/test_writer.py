"""the Ledger class: reproduction of the shared base, lock, fsync'd append, refusals."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import styxx_ledger as S
from styxx_ledger import Ledger, LedgerBroken, LedgerLocked, LedgerStateError, LedgerValueError
from conftest import REPO, SRC, VECTORS, child_env

CERT = "one line per event the test writer was handed"


def new(tmp_path, kinds=("note",), tz="America/New_York", name="log.jsonl", **kw):
    return Ledger.create(tmp_path / name, agent="testbot", anchor_tz=tz, certifies=CERT, kinds=list(kinds),
                         created="2026-10-31T12:00:00Z", **kw)


# ---------------------------------------------------------------------------------- the shared base, rewritten

def _make_vectors():
    sys.path.insert(0, str(VECTORS))
    import make_vectors  # noqa: E402  (defines the timeline; writes nothing on import)
    return make_vectors


def test_ledger_class_reproduces_base_v1_byte_for_byte(tmp_path):
    """base_v1.jsonl was composed with chain.build_entry; the Ledger class, given the same timestamps, writes
    the same 60 lines."""
    mv = _make_vectors()
    h = mv.HEADER
    p = tmp_path / "base.jsonl"
    led = Ledger.create(p, agent=h["agent"], anchor_tz=h["anchor_tz"], certifies=h["certifies"],
                        kinds=h["kinds"], created=h["created"])
    for ts, kind, spec in mv.TIMELINE:
        if kind == "started":
            led.start(writer=spec["writer"], timestamp=ts)
        elif kind == "anchor":
            e = led.append_anchor(spec["date"], timestamp=ts)["entry"]
            assert e["late"] is spec["late"], (spec, ts)   # section 5's rule reproduces the base's marks
        else:
            led.append(kind, spec, timestamp=ts)
    want = (VECTORS / "base_v1.jsonl").read_bytes()
    got = p.read_bytes()
    assert got.count(b"\n") == 60
    assert got == want
    doc = json.loads((VECTORS / "vectors_v1.json").read_text("utf-8"))
    assert led.head() == doc["base_head"]


# ------------------------------------------------------------------------------------------------- create

def test_create_writes_one_header_line_with_required_kinds(tmp_path):
    led = new(tmp_path, kinds=["note"])
    raw = led.path.read_bytes()
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    hdr = json.loads(raw)
    assert hdr["kinds"] == ["anchor", "note", "started"]
    assert hdr["schema"] == "styxx.ledger/log/v1"
    assert set(hdr) == {"schema", "created", "anchor_tz", "agent", "certifies", "kinds"}
    r = led.verify()
    assert r["ok"] and r["head"] == S.header_digest(hdr) and r["entries"] == []
    assert not led.lock_path.exists()


def test_create_refuses_an_existing_log(tmp_path):
    new(tmp_path)
    with pytest.raises(LedgerStateError):
        new(tmp_path)


@pytest.mark.parametrize("kw,code", [
    ({"agent": "Bad Agent"}, "header_form"),
    ({"agent": "x" * 33}, "header_form"),
    ({"anchor_tz": "Mars/Olympus_Mons"}, "anchor_tz"),
    ({"certifies": "two\nlines"}, "header_form"),
    ({"kinds": ["Note"]}, "header_form"),
])
def test_create_refuses_a_header_out_of_form(tmp_path, kw, code):
    args = dict(agent="testbot", anchor_tz="UTC", certifies=CERT, kinds=["note"])
    args.update(kw)
    with pytest.raises(LedgerValueError) as ei:
        Ledger.create(tmp_path / "x.jsonl", **args)
    assert ei.value.code == code
    assert not (tmp_path / "x.jsonl").exists()


# ------------------------------------------------------------------------------------------------- append

def test_append_chains_and_verifies(tmp_path):
    led = new(tmp_path)
    e1 = led.start(timestamp="2026-10-31T12:00:01Z")
    assert e1["writer"]["name"] == "styxx-ledger" and e1["writer"]["version"] == S.__version__
    e2 = led.append("note", {"note": "hi", "n": 1}, timestamp="2026-10-31T12:00:02Z")
    assert (e1["seq"], e2["seq"]) == (1, 2)
    assert e1["prev"] == S.header_digest(led.header)
    assert e2["prev"] == e1["entry_id"]
    assert e2["entry_id"] == S.entry_id_of(S.core_of(e2))
    r = led.verify()
    assert r["ok"] and r["head"] == e2["entry_id"]
    assert led.path.read_bytes().endswith(b"\n")
    assert not led.lock_path.exists()


def test_append_with_the_clock(tmp_path):
    led = new(tmp_path, tz="UTC")
    e = led.append("note", {"n": 1})
    assert S.parse_timestamp(e["timestamp"])
    assert e["day"] == e["timestamp"][:10]


def test_day_is_read_in_anchor_tz_across_the_dst_edge(tmp_path):
    led = new(tmp_path)
    days = [led.append("note", {"n": i}, timestamp=ts)["day"] for i, ts in enumerate(
        ["2026-11-01T03:59:59Z", "2026-11-01T04:00:00Z", "2026-11-02T04:59:59Z", "2026-11-02T05:00:00Z"])]
    assert days == ["2026-10-31", "2026-11-01", "2026-11-01", "2026-11-02"]


@pytest.mark.parametrize("kind,fields,code", [
    ("send", {"x": 1}, "kind_not_declared"),
    ("note", {"x": 1.5}, "float"),
    ("note", {"é": 1}, "non_ascii_key"),
    ("note", {"n": 2 ** 53 + 2}, "int_range"),
    ("note", {"seq": 9}, "reserved_field"),
    ("note", {"_private": 1}, "reserved_field"),
    ("note", {"s": "a\ud800"}, "lone_surrogate"),
    ("started", {"writer": {"name": "x"}}, "started_writer"),
    ("anchor", {"anchor_date": "2026-10-31"}, "anchor_form"),
])
def test_append_refusals_leave_the_file_unchanged(tmp_path, kind, fields, code):
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    before = led.path.read_bytes()
    with pytest.raises(LedgerValueError) as ei:
        led.append(kind, fields, timestamp="2026-10-31T12:00:02Z")
    assert ei.value.code == code
    assert led.path.read_bytes() == before
    assert not led.lock_path.exists()


@pytest.mark.parametrize("ts", ["2026-10-31T12:00:02+00:00", "2026-10-31T12:00:02.5Z", "2026-02-30T00:00:00Z",
                                "2026-10-31T24:00:00Z", "2026-10-31T23:59:60Z"])
def test_append_refuses_a_timestamp_out_of_form(tmp_path, ts):
    led = new(tmp_path)
    with pytest.raises(LedgerValueError) as ei:
        led.append("note", {}, timestamp=ts)
    assert ei.value.code == "timestamp"


def test_append_refuses_without_a_log(tmp_path):
    with pytest.raises(LedgerStateError):
        Ledger(tmp_path / "missing.jsonl").append("note", {})
    (tmp_path / "empty.jsonl").write_bytes(b"")
    with pytest.raises(LedgerStateError):
        Ledger(tmp_path / "empty.jsonl").append("note", {})


# ------------------------------------------------------------------------------------- refuse on broken chain

def _rewrite(path: Path, seq: int, field: str, value):
    lines = path.read_bytes().split(b"\n")
    for i, ln in enumerate(lines):
        if ln.strip():
            o = json.loads(ln)
            if o.get("seq") == seq:
                o[field] = value
                lines[i] = S.dump(o).encode("utf-8")
    path.write_bytes(b"\n".join(lines))


def _three(tmp_path):
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    led.append("note", {"note": "a"}, timestamp="2026-10-31T12:00:02Z")
    led.append("note", {"note": "b"}, timestamp="2026-10-31T12:00:03Z")
    return led


def test_refuses_to_append_to_a_rewritten_log(tmp_path):
    led = _three(tmp_path)
    _rewrite(led.path, 2, "note", "A")
    before = led.path.read_bytes()
    with pytest.raises(LedgerBroken) as ei:
        led.append("note", {"note": "c"}, timestamp="2026-10-31T12:00:04Z")
    assert any(p.get("seq") == 2 and "entry_id" in (p.get("codes") or []) for p in ei.value.problems)
    assert led.path.read_bytes() == before
    assert not led.lock_path.exists()


def test_refuses_to_append_after_a_dropped_line(tmp_path):
    led = _three(tmp_path)
    lines = led.path.read_bytes().split(b"\n")
    led.path.write_bytes(b"\n".join(lines[:2] + lines[3:]))
    with pytest.raises(LedgerBroken):
        led.append("note", {}, timestamp="2026-10-31T12:00:04Z")


def test_refuses_to_append_to_a_torn_tail(tmp_path):
    led = _three(tmp_path)
    raw = led.path.read_bytes()
    led.path.write_bytes(raw[:-1])                       # the LF gone: a whole line, no terminator
    with pytest.raises(LedgerBroken) as ei:
        led.append("note", {}, timestamp="2026-10-31T12:00:04Z")
    assert ei.value.problems[0]["code"] == "tail_no_lf"
    led.path.write_bytes(raw[:-20])                      # half a line
    with pytest.raises(LedgerBroken):
        led.append("note", {}, timestamp="2026-10-31T12:00:04Z")


def test_refuses_to_append_to_a_crlf_log(tmp_path):
    led = _three(tmp_path)
    led.path.write_bytes(led.path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(LedgerBroken) as ei:
        led.append("note", {}, timestamp="2026-10-31T12:00:04Z")
    assert any(p.get("code") == "cr_byte" for p in ei.value.problems)


def test_refuses_to_append_to_a_v0_log(tmp_path):
    p = tmp_path / "v0.jsonl"
    p.write_bytes(b'{"anchor_tz":"America/New_York","certifies":"x","created":"2026-10-24T00:00:00Z","schema":"darkflobi.gate/log/v0"}\n')
    with pytest.raises((LedgerBroken, LedgerStateError)):
        Ledger(p).append("note", {})


# ------------------------------------------------------------------------------------------------- anchor

def test_anchor_composes_text_and_records_entry(tmp_path):
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    last = led.append("note", {"n": 1}, timestamp="2026-11-01T03:59:59Z")      # 23:59:59 EDT on the 31st
    c = led.compose_anchor(now="2026-11-01T04:00:05Z")
    assert c["date"] == "2026-10-31" and c["seq"] == last["seq"] and c["head"] == last["entry_id"]
    assert c["text"] == "testbot anchor 2026-10-31 head %s seq %d" % (last["entry_id"], last["seq"])
    before = led.path.read_bytes()
    assert led.path.read_bytes() == before                                     # compose wrote nothing
    out = led.append_anchor(timestamp="2026-11-01T04:00:05Z")
    assert out["text"] == c["text"]
    e = out["entry"]
    assert e["kind"] == "anchor" and e["anchor_date"] == "2026-10-31" and e["late"] is False
    import hashlib
    assert e["anchor_text_sha256"] == hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
    r = led.verify()
    a = S.check_anchor(r["entries"], S.parse_anchor_text(out["text"]), [], r["header"])
    assert r["ok"] and a["ok"] and a["ledger_anchor_line"]["agrees"]


def test_anchor_refuses_an_open_day_a_repeat_and_an_empty_day(tmp_path):
    led = new(tmp_path)
    led.start(timestamp="2026-10-31T12:00:01Z")
    with pytest.raises(LedgerStateError):                                        # the 31st is still open
        led.append_anchor("2026-10-31", timestamp="2026-10-31T23:00:00Z")
    with pytest.raises(LedgerStateError):                                        # nothing on the 30th
        led.append_anchor("2026-10-30", timestamp="2026-11-01T05:00:00Z")
    led.append_anchor("2026-10-31", timestamp="2026-11-01T05:00:00Z")
    with pytest.raises(LedgerStateError):                                        # already anchored
        led.append_anchor("2026-10-31", timestamp="2026-11-01T05:00:01Z")
    with pytest.raises(LedgerStateError):                                        # a backdated line after it
        led.append("note", {}, timestamp="2026-10-31T23:00:00Z")
    assert led.verify()["ok"]


def test_anchor_late_is_the_rule_not_the_caller(tmp_path):
    """review finding 5: late = the entry's local day is after date+1, or is date+1 after 00:10:00 local."""
    led = new(tmp_path, tz="UTC")
    led.start(timestamp="2026-10-31T12:00:01Z")
    led.append("note", {}, timestamp="2026-11-01T00:05:00Z")
    led.append("note", {}, timestamp="2026-11-02T00:05:00Z")
    led.append("note", {}, timestamp="2026-11-03T00:05:00Z")
    assert led.append_anchor("2026-10-31", timestamp="2026-11-01T00:10:00Z")["entry"]["late"] is False
    assert led.append_anchor("2026-11-01", timestamp="2026-11-02T00:10:01Z")["entry"]["late"] is True
    assert led.append_anchor("2026-11-02", timestamp="2026-11-04T00:00:00Z")["entry"]["late"] is True
    with pytest.raises(TypeError):
        led.append_anchor("2026-11-03", late=False, timestamp="2026-11-04T00:00:01Z")
    with pytest.raises(S.LedgerValueError) as ei:      # a caller composing a wrong mark by hand is refused
        S.build_entry(led.header, 99, "a" * 64, "anchor", "2026-11-01T00:10:00Z",
                      {"anchor_date": "2026-10-31", "anchor_head": "a" * 64, "anchor_head_seq": 1,
                       "anchor_text_sha256": "b" * 64, "late": True})
    assert ei.value.code == "anchor_form"


def test_writer_refuses_a_header_a_v1_writer_may_not_write(tmp_path):
    """review finding 7: the verifier is silent on header form beyond kinds; the writer refuses it."""
    led = new(tmp_path, tz="UTC")
    raw = led.path.read_bytes()
    hdr = json.loads(raw)
    for change in ({"extra": 1}, {"agent": "KitBot"}, {"kinds": ["note", "anchor", "started"]}):
        h = dict(hdr, **change)
        p = tmp_path / ("bad-%d.jsonl" % len(str(change)))
        p.write_bytes((S.dump(h) + "\n").encode("utf-8"))
        assert S.verify_bytes(p.read_bytes())["ok"]
        with pytest.raises(S.LedgerValueError) as ei:
            Ledger(p).append("note", {"t": 1}, timestamp="2026-11-02T12:00:00Z")
        assert ei.value.code == "header_form"
        assert p.read_bytes().count(b"\n") == 1


def test_writer_refuses_forms_python_regex_used_to_admit(tmp_path):
    """review finding 1: a trailing LF and non-ascii digits are refused."""
    led = new(tmp_path, tz="UTC")
    for ts in ("2026-11-03T12:00:00Z\n", "\uff12\uff10\uff12\uff16-11-02T12:00:00Z"):
        with pytest.raises(S.LedgerValueError) as ei:
            led.append("note", {"t": 1}, timestamp=ts)
        assert ei.value.code == "timestamp"
    with pytest.raises(S.LedgerValueError):
        S.anchor_text("kitbot\n", "2026-11-01", "a" * 64, 1)
    with pytest.raises(S.LedgerValueError):
        S.make_header("2026-11-01T00:00:00Z\n", "UTC", "kitbot", "x", ["anchor", "started"])
    with pytest.raises(S.LedgerValueError):
        S.make_header("2026-11-01T00:00:00Z", "UTC", "kitbot\n", "x", ["anchor", "started"])


def test_writer_refuses_depth_and_year_and_zone(tmp_path):
    """review findings 2, 3, 6."""
    led = new(tmp_path, tz="America/New_York")
    deep = 1
    for _ in range(32):
        deep = [deep]
    for fields, ts, code in (({"deep": deep}, "2026-11-02T12:00:00Z", "depth"),
                             ({}, "0001-01-01T00:00:00Z", "timestamp"),
                             ({}, "9999-12-31T23:59:59Z", "timestamp")):
        with pytest.raises(S.LedgerValueError) as ei:
            led.append("note", fields, timestamp=ts)
        assert ei.value.code == code
    for tz in ("utc", "UTC ", "Factory", "america/new_york"):
        with pytest.raises(S.LedgerValueError) as ei:
            Ledger.create(tmp_path / ("z%d.jsonl" % len(tz)), agent="kitbot", anchor_tz=tz, certifies="x", kinds=[])
        assert ei.value.code == "anchor_tz"


# --------------------------------------------------------------------------------------------------- lock

def _dead_pid():
    p = subprocess.Popen([sys.executable, "-B", "-c", "pass"])
    p.wait()
    return p.pid


def _age(path: Path, seconds: float):
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_lock_held_by_a_live_writer_times_out(tmp_path):
    led = new(tmp_path)
    led.lock_path.write_text(str(os.getpid()))
    _age(led.lock_path, 120)
    fast = Ledger(led.path, lock_timeout_s=0.3)
    before = led.path.read_bytes()
    with pytest.raises(LedgerLocked):
        fast.append("note", {}, timestamp="2026-10-31T12:00:01Z")
    assert led.path.read_bytes() == before
    assert led.lock_path.exists()                                                # not ours to remove


def test_fresh_lock_of_a_dead_pid_is_not_broken(tmp_path):
    led = new(tmp_path)
    led.lock_path.write_text(str(_dead_pid()))
    with pytest.raises(LedgerLocked):
        Ledger(led.path, lock_timeout_s=0.3).append("note", {}, timestamp="2026-10-31T12:00:01Z")


def test_stale_lock_is_broken_and_recorded_when_kinds_lists_lock_recovered(tmp_path):
    led = new(tmp_path, kinds=["lock_recovered", "note"])
    led.start(timestamp="2026-10-31T12:00:01Z")
    dead = _dead_pid()
    led.lock_path.write_text(str(dead))
    _age(led.lock_path, 60)
    e = Ledger(led.path, lock_timeout_s=2).append("note", {"n": 1}, timestamp="2026-10-31T12:00:02Z")
    r = led.verify()
    kinds = [it["entry"]["kind"] for it in r["entries"]]
    assert kinds == ["started", "lock_recovered", "note"]
    lr = r["entries"][1]["entry"]
    assert lr["stale_pid"] == dead and lr["stale_age_s"] >= 59
    assert e["seq"] == 3 and r["ok"] and not led.lock_path.exists()


def test_stale_lock_is_broken_silently_when_kinds_omits_lock_recovered(tmp_path):
    led = new(tmp_path, kinds=["note"])
    led.lock_path.write_text("")                                                 # died between create and write
    _age(led.lock_path, 60)
    led.append("note", {"n": 1}, timestamp="2026-10-31T12:00:02Z")
    assert [it["entry"]["kind"] for it in led.verify()["entries"]] == ["note"]


def test_pid_alive():
    assert S.pid_alive(os.getpid())
    assert not S.pid_alive(_dead_pid())
    assert not S.pid_alive(0) and not S.pid_alive(-1)


WORKER = r"""
import sys
sys.dont_write_bytecode = True
from styxx_ledger import Ledger
led = Ledger(sys.argv[1], lock_timeout_s=60)
for i in range(int(sys.argv[3])):
    led.append("note", {"worker": int(sys.argv[2]), "i": i})
"""


def test_concurrent_writers_keep_one_chain(tmp_path):
    led = new(tmp_path, tz="UTC")
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    workers, each = 6, 20
    procs = [subprocess.Popen([sys.executable, "-B", str(script), str(led.path), str(w), str(each)], env=child_env())
             for w in range(workers)]
    for p in procs:
        assert p.wait(timeout=120) == 0
    r = led.verify()
    assert r["ok"], r["problems"][:3]
    assert len(r["entries"]) == workers * each
    assert [it["entry"]["seq"] for it in r["entries"]] == list(range(1, workers * each + 1))
    got = sorted((it["entry"]["worker"], it["entry"]["i"]) for it in r["entries"])
    assert got == sorted((w, i) for w in range(workers) for i in range(each))
    assert not led.lock_path.exists()
