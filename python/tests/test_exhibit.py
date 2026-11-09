"""styxx-ledger exhibit, end to end and offline: a local http server serving a copy of the published exhibit
(vectors/exhibit + the proofs under vectors/ots) and two fake explorers answering the real captured headers."""
import json
import socket

import pytest

from styxx_ledger import cli
from styxx_ledger.exhibit import render_text, run_exhibit
from exhibit_server import ExhibitServer, assemble, load_headers

BANNED = ("independent", "first", "no one", "provably")
FIRST = "12ba959269fdfb5431cbcd3ae542c686124519f4f65c628056bc2d6049fac32b"   # seq 1, always sampled
LAST = "0e5a698dece0bb33764c5202a03745a140a6ef66dba7bbcbc3896842795e152f"    # seq 734, always sampled


@pytest.fixture
def exhibit(tmp_path):
    root = assemble(tmp_path)
    with ExhibitServer(root) as s:
        s.dir = root
        yield s


def run_cli(capsys, s, *extra):
    rc = cli.main(["exhibit", s.url, "--explorer", s.explorers[0], "--explorer", s.explorers[1], *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err


def run_json(capsys, s, *extra):
    rc, out, err = run_cli(capsys, s, "--json", *extra)
    return rc, json.loads(out)


def anchor(rep, date):
    return next(a for a in rep["anchors"] if a["date"] == date)


# ------------------------------------------------------------------------------------------- a: clean

def test_a_clean_exit_0_text(exhibit, capsys):
    rc, out, err = run_cli(capsys, exhibit)
    assert rc == 0, out + err
    assert ("chain (protocol v0): re-derives: 743 lines = 738 published + 5 withheld, head "
            "8afd642915b2a397764041a424619b03888dd1f94532c55cf6fc9782628e2409 (seq 743), 0 problem records") in out
    assert "seq 129,131,136,138,351" in out
    assert "anchors: 14 of 14 anchor texts hold against the chain (section 5 of protocol v0)" in out
    assert "anchor proofs: 14 of 14 verify natively against bitcoin block headers" in out
    assert "(lowest blocks: 974530 x11, 974635, 974768, 975028)" in out
    assert "coverage: 692 of 738 published entries pinned" in out
    assert "witness index: 743 records (734 bitcoin, 9 pending); 743 of 743 chain lines carry one at their seq" in out
    assert "witness proofs: 22 sampled of 734 attested" in out and "seq 1 and 734): 22 of 22 commit" in out
    assert "14 of 14 blocks asked agree on hash, merkle root and time" in out
    assert "result: every check passed, 66 of 66 (exit 0)" in out
    low = out.lower()
    for w in BANNED:
        assert w not in low, w
    assert "a proof attests that bytes existed before a bitcoin block, not that they were published at a url" in out
    assert "the supergroup they were posted to needs an account" in out and "nothing is signed" in out
    assert "reproducible by anyone" in out


def test_a_clean_json_record(exhibit, capsys):
    rc, rep = run_json(capsys, exhibit)
    assert rc == 0 and rep["ok"] and rep["exit_code"] == 0
    assert rep["counts"] == {"pass": 66, "fail": 0, "pending": 0, "unchecked": 0, "total": 66}
    c = rep["chain"]
    assert (c["lines"], c["published"], c["withheld"], c["last_seq"]) == (743, 738, 5, 743)
    assert c["file_sha256"] == "b9cdb57dc29e7c0f8fe0c5bbf4dbaf58383d819a85f00e01c4e814502857f533"
    assert len(rep["fetched"]) == 54 and all(f["sha256"] and f["bytes"] for f in rep["fetched"])
    lows = sorted(a["proof"]["lowest"]["height"] for a in rep["anchors"])
    assert lows == [974530] * 11 + [974635, 974768, 975028]
    w = rep["witness"]
    assert w["seed"] == c["file_sha256"] and len(w["sampled"]) == 22
    assert all(x["verdict"] == "pass" and x["lowest"]["height"] == 975101 for x in w["sampled"])
    assert {x["seq"] for x in w["sampled"] if "attested line" in x["picked"]} == {1, 734}
    assert len(rep["explorer_answers"]) == 14 and all(h["verdict"] == "agree" for h in rep["explorer_answers"])
    assert all(len(h["answers"]) == 2 for h in rep["explorer_answers"])
    assert rep["explorer_calls"] == 56


def test_a_times_match_the_captured_headers(exhibit, capsys):
    hd = load_headers()
    rc, rep = run_json(capsys, exhibit)
    for a in rep["anchors"]:
        lo = a["proof"]["lowest"]
        assert lo["time"] == hd[lo["height"]]["timestamp"]
    assert rep["witness"]["sampled"][0]["lowest"]["time"] == 1794174086 == hd[975101]["timestamp"]


def test_a_seeded_sample_is_the_fixture_rule(exhibit, capsys):
    from conftest import VECTORS
    fx = json.loads((VECTORS / "ots" / "fixtures.json").read_text(encoding="utf-8"))
    rc, rep = run_json(capsys, exhibit)
    seeded = {x["entry_id"] for x in rep["witness"]["sampled"] if x["picked"].startswith("seeded")}
    assert seeded == {x["entry_id"] for x in fx["witness_sample"]}


# --------------------------------------------------------------------------------- b: one text altered

def test_b_altered_anchor_text_fails_that_anchor(exhibit, capsys):
    p = exhibit.dir / "anchors" / "2026-10-28.txt"
    p.write_bytes(p.read_bytes().replace(b"seq 173", b"seq 172"))
    rc, out, err = run_cli(capsys, exhibit)
    assert rc == 1
    line = next(ln for ln in out.splitlines() if ln.startswith("  2026-10-28"))
    assert "FAIL" in line and "the .txt is not the index's text" in line
    assert "commitment mismatch" in line
    assert "anchors: 13 of 14 anchor texts hold" in out and "anchor proofs: 13 of 14 verify" in out
    for ln in out.splitlines():
        if ln.startswith("  2026-") and not ln.startswith("  2026-10-28"):
            assert " ok " in ln, ln
    rc, rep = run_json(capsys, exhibit)
    a = anchor(rep, "2026-10-28")
    assert a["text_check"]["verdict"] == "fail" and a["chain_check"]["verdict"] == "fail"
    assert a["proof"]["verdict"] == "fail" and a["proof"]["status"] == "commitment_mismatch"
    assert rep["counts"]["fail"] == 3


def test_b2_proof_flipped_byte_fails(exhibit, capsys):
    p = exhibit.dir / "anchors" / "2026-11-05.txt.ots"
    b = bytearray(p.read_bytes())
    b[100] ^= 0x01                      # inside the tree, past the commitment
    p.write_bytes(bytes(b))
    rc, rep = run_json(capsys, exhibit)
    a = anchor(rep, "2026-11-05")
    assert rc == 1 and a["proof"]["verdict"] == "fail"
    assert a["text_check"]["verdict"] == "pass" and a["chain_check"]["verdict"] == "pass"


# ------------------------------------------------------------------------------- c: explorers disagree

def test_c_explorers_disagree_not_verified(exhibit, capsys):
    exhibit.overrides[974530] = {"merkle_root": "00" * 32}
    rc, out, err = run_cli(capsys, exhibit)
    assert rc == 1
    assert "anchor proofs: 3 of 14 verify" in out
    assert out.count("explorers disagree on block 974530: not verified") >= 11
    assert "13 of 14 blocks asked agree on hash, merkle root and time; disagree on 974530" in out
    rc, rep = run_json(capsys, exhibit)
    h = next(x for x in rep["explorer_answers"] if x["height"] == 974530)
    assert h["verdict"] == "disagree" and h["answers"][0]["merkle_root"] != h["answers"][1]["merkle_root"]
    assert sum(1 for a in rep["anchors"] if a["proof"]["verdict"] == "fail") == 11


def test_c2_explorers_disagree_on_time_only(exhibit, capsys):
    exhibit.overrides[975101] = {"timestamp": 1794174087}
    rc, rep = run_json(capsys, exhibit)
    assert rc == 1
    assert all(x["verdict"] == "fail" and "explorers disagree" in x["why"] for x in rep["witness"]["sampled"])
    assert all(a["proof"]["verdict"] == "pass" for a in rep["anchors"])


# ------------------------------------------------------------------------------------ d: swapped proof

def test_d_witness_proof_swapped_commitment_mismatch(exhibit, capsys):
    proofs = exhibit.dir / "witness" / "proofs"
    (proofs / (FIRST + ".ots")).write_bytes((proofs / (LAST + ".ots")).read_bytes())
    rc, out, err = run_cli(capsys, exhibit)
    assert rc == 1
    assert "21 of 22 commit to their entry_id" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("  seq 1 "))
    assert "FAILS: commitment mismatch: the proof commits to " + LAST in line
    rc, rep = run_json(capsys, exhibit)
    x = next(x for x in rep["witness"]["sampled"] if x["seq"] == 1)
    assert x["status"] == "commitment_mismatch" and x["verdict"] == "fail"


# ---------------------------------------------------------------------------------- e: ledger truncated

def test_e_truncated_ledger_anchor_not_in_chain(exhibit, capsys):
    p = exhibit.dir / "ledger.jsonl"
    lines = p.read_bytes().split(b"\n")
    p.write_bytes(b"\n".join(lines[:701]) + b"\n")          # header + 700 entries: through seq 705
    rc, out, err = run_cli(capsys, exhibit, "--sample", "0")
    assert rc == 1
    assert "re-derives: 705 lines = 700 published + 5 withheld" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("  2026-11-07"))
    assert "FAIL" in line and "not in chain: seq 729 is after the last line (seq 705)" in line
    assert "anchors: 13 of 14 anchor texts hold" in out
    assert "anchor proofs: 14 of 14 verify" in out             # the proof is about the .txt, not the chain
    assert "38 name a line not in the chain" in out
    rc, rep = run_json(capsys, exhibit, "--sample", "0")
    assert rep["witness"]["not_in_chain"] == 38 and rep["witness"]["sampled"] == []


# ------------------------------------------------------------------------------------ flags and edges

def test_no_ots_skips_proofs_and_explorers(exhibit, capsys):
    rc, out, err = run_cli(capsys, exhibit, "--no-ots")
    assert rc == 0
    assert "proofs and explorers: not checked (--no-ots)" in out and "witness proofs: not checked (--no-ots)" in out
    assert not any(r.startswith(("/xa", "/xb")) for r in exhibit.requests)
    assert "result: every check passed, 30 of 30 (exit 0)" in out


def test_save_keeps_the_fetched_bytes(exhibit, capsys, tmp_path):
    out_dir = tmp_path / "kept"
    rc, rep = run_json(capsys, exhibit, "--save", str(out_dir))
    assert rc == 0
    assert (out_dir / "ledger.jsonl").read_bytes() == (exhibit.dir / "ledger.jsonl").read_bytes()
    assert (out_dir / "anchors" / "2026-10-24.txt.ots").is_file()
    assert len(list((out_dir / "witness" / "proofs").iterdir())) == 22
    assert (out_dir / "_explorers").is_dir()


def test_sample_counts(exhibit, capsys):
    rc, rep = run_json(capsys, exhibit, "--sample", "3")
    assert rc == 0 and len(rep["witness"]["sampled"]) == 5


def test_one_explorer_says_nothing_to_compare(exhibit, capsys):
    rc = cli.main(["exhibit", exhibit.url, "--explorer", exhibit.explorers[0]])
    out = capsys.readouterr().out
    assert rc == 0 and "one explorer only: nothing to compare its headers with" in out


def test_missing_proof_404_fails(exhibit, capsys):
    (exhibit.dir / "anchors" / "2026-11-01.txt.ots").unlink()
    rc, rep = run_json(capsys, exhibit)
    a = anchor(rep, "2026-11-01")
    assert rc == 1 and a["proof"]["verdict"] == "fail" and "HTTP 404" in a["proof"]["why"]


def _dead_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def test_explorer_down_is_exit_2(exhibit):
    dead = "http://127.0.0.1:%d/api" % _dead_port()
    rep = run_exhibit(exhibit.url, explorers=[exhibit.explorers[0], dead], sleep=lambda s: None)
    assert rep["exit_code"] == 2 and rep["counts"]["fail"] == 0
    assert "could not be made" in render_text(rep)


def test_exhibit_down_is_exit_2():
    dead = "http://127.0.0.1:%d/ledger/" % _dead_port()
    rep = run_exhibit(dead, sleep=lambda s: None)
    assert rep["exit_code"] == 2 and rep["chain"] is None
    assert "ledger.jsonl:" in render_text(rep)


def test_usage_is_exit_2(capsys):
    assert cli.main(["exhibit", "ftp://example.org/ledger/"]) == 2
    assert cli.main(["exhibit", "https://example.org/ledger/", "--explorer", "nope"]) == 2
    assert cli.main(["exhibit", "https://example.org/ledger/", "--sample", "-1"]) == 2
    capsys.readouterr()


def test_cap_refuses_a_large_file(exhibit):
    from styxx_ledger import exhibit as E
    with pytest.raises(E.FetchError) as ei:
        E.http_get(exhibit.url + "ledger.jsonl", cap=1000)
    assert ei.value.kind == "too_large"


# ----------------------------------------------------------------------- review 3e regressions (f and on)

from exhibit_server import craft_proof  # noqa: E402

PHANTOM = "ab" * 32


def _edit_json(p, fn):
    doc = json.loads(p.read_text(encoding="utf-8"))
    fn(doc)
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def test_a_clean_says_age_lag_and_the_rollback_caveat(exhibit):
    rep = run_exhibit(exhibit.url, explorers=exhibit.explorers, today="2026-11-09")
    out = render_text(rep)
    assert ("age: the last holding anchor is 2026-11-07 (seq 729), 2 days before this run (2026-11-09); 14 lines "
            "after it are pinned by nothing here") in out
    assert "lag from an anchor's date to its lowest block: 1 to 11 days; 4 of 14 over 7 days" in out
    assert "11 days after the anchor date (late)" in out
    assert "a copy that is older but consistent passes every check here" in out
    assert rep["exit_code"] == 0 and rep["off_host"] == [] and rep["explorers_rate_limited"] == {}


def test_f_withheld_seq_after_the_last_line_is_not_in_chain(exhibit, capsys):
    _edit_json(exhibit.dir / "withheld.json", lambda d: d.append({"seq": 744, "entry_id": PHANTOM}))
    text = "gate anchor 2026-11-08 head %s seq 744" % PHANTOM
    (exhibit.dir / "anchors" / "2026-11-08.txt").write_text(text, encoding="utf-8")
    _edit_json(exhibit.dir / "anchors" / "index.json", lambda d: d["anchors"].append(
        {"date": "2026-11-08", "file": "anchors/2026-11-08.txt", "text": text, "seq": 744, "head": PHANTOM}))
    rc, out, err = run_cli(capsys, exhibit, "--no-ots")
    assert rc == 1
    assert "re-derives: 743 lines = 738 published + 5 withheld, head 8afd6429" in out and "(seq 743)" in out
    assert "  FAIL withheld.json names seq 744, which no published line binds" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("  2026-11-08"))
    assert "FAIL" in line and "not in chain: seq 744 is a withheld digest no published line binds" in line
    assert "anchors: 14 of 15 anchor texts hold" in out


def test_g_withheld_naming_a_published_line_fails(exhibit, capsys):
    rec = json.loads((exhibit.dir / "ledger.jsonl").read_bytes().split(b"\n")[500 - 5])   # seq 500 (5 withheld before it)
    assert rec["seq"] == 500
    _edit_json(exhibit.dir / "withheld.json", lambda d: d.append({"seq": 500, "entry_id": rec["entry_id"]}))
    rc, rep = run_json(capsys, exhibit, "--no-ots")
    assert rc == 1
    c = rep["chain"]
    assert (c["lines"], c["withheld"], c["withheld_records"]) == (743, 5, 6)
    assert c["withheld_unbound"] == [{"seq": 500, "why": "withheld.json names seq 500, which is published"}]


def test_h_index_without_block_or_block_time_fails(exhibit, capsys):
    def strip(d):
        for a in d["anchors"]:
            a.pop("block", None)
    _edit_json(exhibit.dir / "anchors" / "index.json", strip)
    _edit_json(exhibit.dir / "witness" / "index.json", lambda d: d["entries"][FIRST].pop("block_time"))
    rc, out, err = run_cli(capsys, exhibit)
    assert rc == 1
    assert "None" not in out and "null" not in out
    assert sum(1 for ln in out.splitlines() if ln.startswith("  2026-")
               and "FAILS: the index names no block; the proof's lowest verified block is" in ln) == 14
    assert "anchor proofs: 0 of 14 verify" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("  seq 1 "))
    assert "the index names no block time; block 975101's header says 1794174086" in line


def _pending_anchor(exhibit):
    p = exhibit.dir / "anchors" / "2026-11-07.txt"
    (exhibit.dir / "anchors" / "2026-11-07.txt.ots").write_bytes(craft_proof(p.read_bytes()))

    def mark(d):
        a = next(x for x in d["anchors"] if x["date"] == "2026-11-07")
        a["status"] = "pending"
        a.pop("block", None)
        a.pop("ots_sha256", None)
    _edit_json(exhibit.dir / "anchors" / "index.json", mark)


def test_i_pending_anchor_is_pend_then_fails_after_7_days(exhibit):
    _pending_anchor(exhibit)
    rep = run_exhibit(exhibit.url, explorers=exhibit.explorers, today="2026-11-09")
    out = render_text(rep)
    line = next(ln for ln in out.splitlines() if ln.startswith("  2026-11-07"))
    assert " PEND " in line and "calendar receipts only, as the index says" in line
    assert "anchor proofs: 13 of 14 verify" in out and "; 1 of 14 pending" in out
    assert rep["exit_code"] == 0 and rep["counts"]["pending"] == 1
    rep = run_exhibit(exhibit.url, explorers=exhibit.explorers, today="2026-11-20")
    a = anchor(rep, "2026-11-07")
    assert rep["exit_code"] == 1 and a["proof"]["verdict"] == "fail"
    assert "pending for 13 days after the anchor date (the rule here: at most 7" in a["proof"]["why"]


def test_j_redirect_off_the_host_fails_unless_allowed(exhibit, capsys, tmp_path):
    other_root = assemble(tmp_path / "other")
    with ExhibitServer(other_root) as other:
        exhibit.redirects["/ledger/anchors/2026-10-24.txt"] = other.url + "anchors/2026-10-24.txt"
        rc, rep = run_json(capsys, exhibit, "--sample", "0")
        assert rc == 1
        f = next(x for x in rep["fetched"] if x["path"] == "anchors/2026-10-24.txt")
        assert f["url"] == exhibit.url + "anchors/2026-10-24.txt" and f["final_url"] == other.url + "anchors/2026-10-24.txt"
        assert rep["off_host"] == [{"path": "anchors/2026-10-24.txt", "url": f["url"], "final_url": f["final_url"]}]
        bad = [c for c in rep["checks"] if c["verdict"] == "fail"]
        assert [c["name"] for c in bad] == ["files served from the exhibit's host"]
        rc, out, err = run_cli(capsys, exhibit, "--sample", "0", "--allow-redirect")
        assert rc == 0 and "served from another host: anchors/2026-10-24.txt -> " + other.url in out
        rc, rep = run_json(capsys, exhibit, "--sample", "0", "--allow-redirect")
        assert rc == 0 and "allowed by --allow-redirect" in json.dumps(rep["checks"])


def test_k_a_block_no_explorer_knows_fails_and_one_404_is_disagreement(exhibit, capsys):
    p = exhibit.dir / "anchors" / "2026-10-24.txt"
    (exhibit.dir / "anchors" / "2026-10-24.txt.ots").write_bytes(craft_proof(p.read_bytes(), height=99999999))
    exhibit.overrides[974635] = {"_absent": True}
    rc, out, err = run_cli(capsys, exhibit, "--sample", "0")
    assert rc == 1
    line = next(ln for ln in out.splitlines() if ln.startswith("  2026-10-24"))
    assert "FAILS: block 99999999 does not exist at any explorer asked" in line
    assert "  no explorer asked knows block 99999999" in out
    assert "disagree on 974635" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("  2026-11-04"))
    assert "FAILS: explorers disagree on block 974635: not verified" in line
    assert "; 0 could not be made" in out


def test_l_a_huge_height_is_refused_and_never_asked(exhibit, capsys):
    p = exhibit.dir / "anchors" / "2026-10-24.txt"
    (exhibit.dir / "anchors" / "2026-10-24.txt.ots").write_bytes(craft_proof(p.read_bytes(), height=1 << 60))
    rc, rep = run_json(capsys, exhibit, "--sample", "0")
    a = anchor(rep, "2026-10-24")
    assert rc == 1 and a["proof"]["status"] == "refused" and "(attestation_payload)" in a["proof"]["why"]
    assert not any(str(1 << 60) in r for r in exhibit.requests)


def test_m_rate_limited_explorer_is_named_and_left_out(exhibit):
    exhibit.limited["xa"] = "0"
    sleeps = []
    rep = run_exhibit(exhibit.url, explorers=exhibit.explorers, sample=0, sleep=sleeps.append)
    out = render_text(rep)
    assert rep["exit_code"] == 2 and rep["counts"]["fail"] == 0
    assert rep["explorers_rate_limited"] == {exhibit.explorers[0]: 5}
    assert sum(1 for r in exhibit.requests if r.startswith("/xa")) == 5 and sleeps == [0.0, 0.0, 0.0, 0.0]
    assert ("127.0.0.1:%d rate-limited this run (HTTP 429 after 5 tries) and was not asked again; run again in a "
            "minute, or name another esplora instance with --explorer" % exhibit.port) in out
    assert all(a["proof"]["verdict"] == "unchecked" for a in rep["anchors"])


def test_m2_rate_limit_without_retry_after_backs_off_2_4_8_16(exhibit):
    exhibit.limited["xa"] = None
    sleeps = []
    run_exhibit(exhibit.url, explorers=exhibit.explorers, sample=0, sleep=sleeps.append)
    assert sleeps == [2.0, 4.0, 8.0, 16.0]


def test_m3_retry_after_is_capped_at_60(exhibit):
    exhibit.limited["xa"] = "3600"
    sleeps = []
    run_exhibit(exhibit.url, explorers=exhibit.explorers, sample=0, sleep=sleeps.append)
    assert sleeps == [60.0] * 4


def test_today_usage(capsys):
    assert cli.main(["exhibit", "https://example.org/ledger/", "--today", "11/09/2026"]) == 2
    capsys.readouterr()


# ------------------------------------------------- the lab's improvement sweep of 2026-11-09: ranks 44 and 45

import http.client  # noqa: E402
import ssl  # noqa: E402
import urllib.error  # noqa: E402

from styxx_ledger import exhibit as E  # noqa: E402


def test_n_an_explorer_that_does_not_answer_says_why_once(exhibit):
    """rank 44: the reason is one line, before the lines it explains; no anchor line reads FAIL for a proof that was
    not checked; the 22 witness lines and the 36 'not made' lines that repeated it are one line each (the report on
    this copy went from 95 lines to 41 with both explorers down)."""
    dead = "http://127.0.0.1:%d/api" % _dead_port()
    rep = run_exhibit(exhibit.url, explorers=[exhibit.explorers[0], dead], sleep=lambda s: None, today="2026-11-09")
    lines = render_text(rep).splitlines()
    assert rep["exit_code"] == 2
    assert rep["counts"] == {"pass": 30, "fail": 0, "pending": 0, "unchecked": 36, "total": 66}
    assert rep["explorers_unanswered"] == {dead: "the connection was refused"}
    assert lines[2] == ("explorer %s did not answer: the connection was refused; check the network, or pass "
                        "--explorer <url> to ask another esplora api" % dead)
    assert sum(1 for ln in lines if "did not answer" in ln) == 1
    anchor_lines = [ln for ln in lines if ln.startswith("  2026-")]
    assert len(anchor_lines) == 14 and all(" ---- chain: holds; proof unchecked: " + E.EXPLORERS_SILENT in ln
                                           for ln in anchor_lines)
    assert "; 14 of 14 not checked" in lines[[i for i, ln in enumerate(lines) if ln.startswith("anchor proofs:")][0]]
    assert sum(1 for ln in lines if ln.startswith("  seq ") or " sampled, seq " in ln) == 1
    assert ("  22 of 22 sampled, seq 1,21,32,47,122,137,149,346,361,386,419,446,543,564,601,608,612,614,622,632,701,"
            "734: unchecked: " + E.EXPLORERS_SILENT) in lines
    assert [ln for ln in lines if ln.startswith("  not made")] == [
        "  not made: 36 checks, anchor 2026-10-24 proof verifies to witness seq 734 proof commits and verifies: "
        + E.EXPLORERS_SILENT]
    assert len(lines) == 40


def test_n2_one_failure_reason_per_check_still(exhibit):
    """failures are never collapsed: each FAILED check keeps its own line; only checks not made share one."""
    for d in ("2026-10-28", "2026-10-29"):
        p = exhibit.dir / "anchors" / ("%s.txt" % d)
        p.write_bytes(p.read_bytes() + b" ")
    rep = run_exhibit(exhibit.url, explorers=exhibit.explorers, sleep=lambda s: None, today="2026-11-09")
    failed = [ln for ln in render_text(rep).splitlines() if ln.startswith("  FAILED: ")]
    assert rep["exit_code"] == 1 and len(failed) == rep["counts"]["fail"] >= 4


def test_o_a_mistyped_url_is_exit_2_with_the_url_and_what_to_check(exhibit, capsys):
    """rank 45: a 404 on ledger.jsonl is not evidence against the publisher: exit 2 (it was 1, a failed check's
    exit), the url that was fetched, and what to check; nothing else is counted or listed."""
    url = exhibit.base + "/ledgr/"
    rc = cli.main(["exhibit", url, "--explorer", exhibit.explorers[0], "--explorer", exhibit.explorers[1]])
    out = capsys.readouterr().out
    detail = ("%sledger.jsonl answered HTTP 404: there is no ledger.jsonl at that url; check that the url names the "
              "exhibit's folder, the one that holds ledger.jsonl (e.g. https://fathom-lab.github.io/styxx/ledger/)" % url)
    assert rc == 2
    assert "\nledger.jsonl: %s\nnothing was verified: every other check needs the ledger\n" % detail in out
    assert "result: 0 of 1 checks passed; 0 failed; 1 could not be made (exit 2)" in out
    assert "  not made: ledger.jsonl fetched: " + detail in out
    for gone in ("FAILED", "anchors: none read", "explorers:", "0 of 0 blocks"):
        assert gone not in out, gone


def test_o2_an_exhibit_that_does_not_answer_names_the_url_and_the_reason():
    dead = "http://127.0.0.1:%d/ledger/" % _dead_port()
    rep = run_exhibit(dead, sleep=lambda s: None)
    assert rep["exit_code"] == 2 and rep["counts"]["fail"] == 0
    assert rep["checks"][0]["detail"] == ("%sledger.jsonl did not answer: the connection was refused; check the url "
                                          "and this machine's network" % dead)


@pytest.mark.parametrize("exc,words", [
    (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), E.NET_DNS),           # windows
    (urllib.error.URLError(socket.gaierror(-2, "Name or service not known")), E.NET_DNS),       # linux
    (urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution")), E.NET_DNS),
    (urllib.error.URLError(ConnectionRefusedError(10061, "actively refused")), E.NET_REFUSED),
    (ConnectionResetError(104, "Connection reset by peer"), E.NET_RESET),
    (http.client.RemoteDisconnected("Remote end closed connection without response"), E.NET_RESET),
    (urllib.error.URLError(socket.timeout("timed out")), "no answer within 30 s"),
    (TimeoutError("The read operation timed out"), "no answer within 30 s"),
    (urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")), E.NET_TLS),
    (urllib.error.URLError("unknown url type: xyz"), "no answer (URLError: unknown url type: xyz)"),
], ids=["dns-windows", "dns-linux", "dns-again", "refused", "reset", "remote-disconnected", "timeout", "read-timeout",
        "tls", "other"])
def test_o3_network_errors_read_in_the_shared_words(exc, words):
    """rank 45: one wording for both packages; js/tests/exhibit.test.js holds node's error codes to the same words
    (python said 'URLError: [Errno 11001] getaddrinfo failed' where javascript said 'TypeError: ENOTFOUND')."""
    assert E.network_reason(exc) == words
    assert E.NET_DNS == "the host name did not resolve (dns)" and E.NET_REFUSED == "the connection was refused"
