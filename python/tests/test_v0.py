"""protocol v0 read mode (styxx_ledger.v0): the exhibit's 10 v0 vectors (vectors/v0/, byte for byte), the runner's
v0 tally, schema detection, v0's day and anchor rules, and the cli reading a v0 file by its header."""
import hashlib
import json
import re
import subprocess
import sys

import pytest

import styxx_ledger as S
from styxx_ledger import v0 as V0
from conftest import SRC, VECTORS, child_env

sys.path.insert(0, str(VECTORS))
import run_vectors as RV  # noqa: E402

DOC = json.loads((VECTORS / "v0" / "vectors.json").read_text("utf-8"))
BASE = (VECTORS / "v0" / DOC["base"]).read_bytes()
BASE_V1 = (VECTORS / "base_v1.jsonl").read_bytes()


def test_v0_files_are_the_exhibits_bytes():
    assert hashlib.sha256(BASE).hexdigest() == DOC["base_sha256"] == \
        "8029fce0bed73a52067d2e7e3552555d45c81d837187a93b6dd20d48ad8861f1"
    assert hashlib.sha256((VECTORS / "v0" / "vectors.json").read_bytes()).hexdigest() == \
        "be43667f1662e822fd31d5941e6166fdd7ce145de72b6dfea9b32bbb4ae69d4b"
    assert len(DOC["cases"]) == 10


@pytest.mark.parametrize("case", DOC["cases"], ids=[c["name"] for c in DOC["cases"]])
def test_v0_vector(case):
    ok, got = RV.check_v0(S, BASE, case)
    assert ok, got


def test_runner_answers_every_v0_vector():
    cp = subprocess.run([sys.executable, "-B", str(VECTORS / "run_vectors.py"), "--src", str(SRC), "--only", "v0"],
                        capture_output=True, text=True, encoding="utf-8", env=child_env(), timeout=120)
    last = cp.stdout.strip().splitlines()[-1]
    m = re.fullmatch(r"(\d+) of (\d+) v0 vectors answered as the file says", last)
    assert m and m.group(1) == m.group(2) == "10", cp.stdout + cp.stderr
    assert cp.returncode == 0


def test_detect_protocol():
    assert V0.detect_protocol(BASE) == "v0"
    assert V0.detect_protocol(BASE_V1) == "v1"
    assert V0.detect_protocol(b"\n\n" + BASE) == "v0"
    assert V0.detect_protocol(b"") is None
    assert V0.detect_protocol(b"not json\n") is None
    assert V0.detect_protocol(b'{"schema":"other"}\n') is None


def test_verify_auto_dispatches_and_v1_still_refuses_v0():
    r = V0.verify_auto(BASE)
    assert r["protocol"] == "v0" and r["ok"] and r["head"] == DOC["base_head"] and len(r["entries"]) == DOC["base_lines"] == 120
    assert V0.verify_auto(BASE_V1)["protocol"] == "v1" and V0.verify_auto(BASE_V1)["ok"]
    r1 = S.verify_bytes(BASE)
    assert not r1["ok"] and any("reads v1 only" in (p.get("problem") or "") for p in r1["problems"])
    forced = V0.verify_auto(BASE, protocol="v1")
    assert forced["protocol"] == "v1" and not forced["ok"]
    # a v1 file read as v0 has no v0 header: every line is an entry, line 1 named
    r0 = V0.verify_bytes_v0(BASE_V1)
    assert not r0["ok"] and "no_header" in {p.get("code") for p in r0["problems"]}


def test_an_empty_v0_reading_is_not_a_problem_in_v0():
    assert V0.verify_bytes_v0(b"")["ok"] is True
    assert V0.verify_bytes_v0(b"\n \n")["problems"] == []


def test_v0_has_no_kinds_check_and_its_own_digest():
    hdr = json.loads(BASE.split(b"\n", 1)[0])
    assert "kinds" not in hdr and "agent" not in hdr
    assert V0.header_digest_v0(hdr) == hashlib.sha256(b"darkflobi.gate/log/v0\n" + S.jcs(hdr).encode()).hexdigest()
    first = json.loads(BASE.split(b"\n")[1])
    assert first["prev"] == V0.header_digest_v0(hdr)


@pytest.mark.parametrize("ts,day", [
    ("2026-10-25T03:59:59Z", "2026-10-24"),          # new york is utc-4 before the dst end
    ("2026-10-25T04:00:00Z", "2026-10-25"),
    ("2026-11-02T04:59:59Z", "2026-11-01"),          # utc-5 after it
    ("2026-10-25T03:59:59.999999Z", "2026-10-24"),   # fractions accepted
    ("2026-10-25T00:30:00+01:00", "2026-10-24"),     # offsets accepted
    ("2026-10-25T12:00:00", "2026-10-25"),           # naive read as utc
    ("  2026-10-25T12:00:00Z\n", "2026-10-25"),      # String(ts).trim()
    ("2026-02-30T12:00:00Z", "2026-03-02"),          # V8 rolls day 30 of february over
    ("2026-01-01T24:00:00Z", "2026-01-01"),          # 24:00 is the next utc midnight, 19:00 in new york
])
def test_v0_local_day(ts, day):
    assert V0.local_day_v0(ts, "America/New_York") == day


@pytest.mark.parametrize("ts", ["2026-13-01T00:00:00Z", "2026-01-01T24:00:01Z", "2026-01-01T23:59:60Z",
                                "2026-01-01T00:00:00+24:00", "2026-01-01", 20261025, None, "2026-01-01T00:00:00z",
                                "２026-01-01T00:00:00Z"])
def test_v0_local_day_unreadable(ts):
    with pytest.raises(S.LedgerValueError) as e:
        V0.local_day_v0(ts, "America/New_York")
    assert e.value.code == "timestamp"


def test_v0_day_is_checked_only_when_a_timestamp_is_carried():
    lines = BASE.rstrip(b"\n").split(b"\n")
    o = json.loads(lines[5])
    del o["timestamp"]
    o.pop("entry_id")
    o["entry_id"] = S.entry_id_of(o)
    lines[5] = S.dump(o).encode()
    r = V0.verify_bytes_v0(b"\n".join(lines) + b"\n")
    assert {p["seq"] for p in r["problems"]} == {o["seq"] + 1}   # only the next line's prev breaks; no day problem


def test_v0_anchor_text_form():
    head = "a" * 64
    t = V0.anchor_text_v0("2026-10-25", head, 116)
    assert t == "gate anchor 2026-10-25 head %s seq 116" % head
    assert V0.parse_anchor_text_v0(t) == {"agent": "gate", "date": "2026-10-25", "head": head, "seq": 116}
    assert V0.parse_anchor_text_v0(t + "\n") is not None
    assert V0.parse_anchor_text_v0(t + "\n\n") is None
    assert V0.parse_anchor_text_v0("kitbot anchor 2026-10-25 head %s seq 116" % head) is None
    assert V0.parse_anchor_text_v0("gate anchor 2026-10-25 head %s seq 99999999999999999" % head) is None
    assert S.parse_anchor_text(t)["agent"] == "gate"   # the v1 parser reads the word as an agent
    with pytest.raises(S.LedgerValueError):
        V0.anchor_text_v0("2026-10-25", "A" * 64, 1)


def test_cli_reads_a_v0_file_by_its_header(cli, tmp_path):
    p = tmp_path / "v0.jsonl"
    p.write_bytes(BASE)
    anchors = tmp_path / "anchors.txt"
    anchors.write_text("\n".join(DOC["cases"][0]["anchors"]) + "\n", encoding="utf-8")
    cp = cli("verify", p, "--anchors-file", anchors)
    assert cp.returncode == 1, cp.stdout      # the second anchor text names the wrong seq
    assert "protocol v0" in cp.stdout and "re-derives: 120 entries" in cp.stdout
    assert cp.stdout.count(": holds") == 1 and "does not hold" in cp.stdout
    anchors.write_text(DOC["cases"][0]["anchors"][0] + "\n", encoding="utf-8")
    cp = cli("verify", p, "--anchors-file", anchors, "--json")
    out = json.loads(cp.stdout)
    assert cp.returncode == 0 and out["protocol"] == "v0" and out["head"] == DOC["base_head"]
    cp = cli("verify", p, "--protocol", "v1")
    assert cp.returncode == 1 and "reads v1 only" in cp.stdout
