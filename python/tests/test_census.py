"""the census scorer (styxx_ledger.census, THE_PLAN 3d second half) against tests/fixtures/census/.

hand counts for the fixture ledger (11 lines: header + 10 entries, 3 anchor lines; tests/make_census_fixture.py):
pre-window 2 (started, the anchor line of 2026-09-29); window 8 (send 5, anchor 2, note 1); deliveries 5, population
(chan-1) 4, outside (dm-9) 1; days with lines 3. without posted texts no day is anchored (the ledger's own anchor
lines are the writer's statement): unanchored deliveries 4 -> UNANCHORED, 10 entries after the last holding anchor.
with anchors.json (4 posted texts, 2026-10-02 marked late): 3 of 3 days anchored, late 1, 0 after the last anchor.
numerals over the population Nn 3, Nb 2, Nu 1, carried on 3 of 4 lines. the held export -> E 5 (exact 3, normalised
1 under strip, native 1), 5 of 5 plants read -> HELD; the open export -> 1 of 6 unmatched -> OPEN.

the seams (make_census_fixture.install_seams): example.invalid urls answer from the fixture files, the shelf row is
switched on, and the js leg is answered by the python verifier, except where a test says otherwise.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import TESTS, VECTORS
import make_census_fixture as M
from styxx_ledger import census
from styxx_ledger.census import score

FIX = TESTS / "fixtures" / "census"
PREREG = FIX / "PREREG_filled.md"
LEDGER = FIX / "ledger.jsonl"
ANCHORS = str(FIX / "anchors.json")
HELD = str(FIX / "export_held.json")
OPEN = str(FIX / "export_open.json")
NOW = M.NOW


@pytest.fixture
def seams(monkeypatch):
    M.install_seams(census, monkeypatch.setattr)
    return monkeypatch


def _run(tmp_path, name, **kw):
    out = tmp_path / name
    prereg = kw.pop("prereg", PREREG)
    ledger = kw.pop("ledger", M.LEDGER_URL)
    now = kw.pop("now", NOW)
    kw.setdefault("js", True)
    kw.setdefault("sleep", lambda s: None)   # no test waits an hour: a guard that regresses into a fetch fails fast
    res = score(prereg, ledger, out, now, **kw)
    return res, out


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return p


def _reseal(text):
    return M.seal(M.regate(text), M.hashlib.sha256((FIX / "shelf_report.json").read_bytes()).hexdigest())


def _strip(d):
    d = json.loads(json.dumps(d))
    d["scorer"].pop("sha256", None)
    d["scorer"].pop("vectors_sha256", None)  # the kit's vectors file moves with the kit, as census.py does
    d["scorer"].pop("kit_version", None)  # the version is recorded, not tested: a pin is not a test
    return d


def test_expected_result(seams, tmp_path):
    res, out = _run(tmp_path, "a")
    want = json.loads((FIX / "expected_RESULT.json").read_text(encoding="utf-8"))
    got = json.loads((out / "RESULT.json").read_text(encoding="utf-8"))
    assert _strip(got) == _strip(want)
    assert got == res


def test_counts(seams, tmp_path):
    res, _ = _run(tmp_path, "a")
    assert res["status"] == "scored"
    assert res["verdict"] == "UNANCHORED__deliveries_on_days_without_a_posted_anchor"
    assert res["ledger"]["protocol"] == "v1" and res["ledger"]["entries"] == 10
    c = res["lines"]["cells"]
    assert c["pre_window"] == {"lines": 2, "by_kind": {"anchor": 1, "started": 1}, "delivery_lines": 0}
    assert c["window"] == {"lines": 8, "by_kind": {"anchor": 2, "note": 1, "send": 5}, "delivery_lines": 5}
    assert c["after"]["lines"] == 0
    s = res["sends"]
    assert (s["delivery_lines_in_window"], s["in_population"], s["outside_destination"]) == (5, 4, 1)
    assert s["outside_by_destination"] == {"dm-9": 1}
    aw = res["anchors"]["window"]
    assert (aw["days_with_lines"], aw["anchored_days_with_lines"], len(aw["missing_days"])) == (3, 0, 3)
    assert res["anchors"]["ledger_own_anchor_lines"] == 3 and res["anchors"]["texts"] == 0
    n = res["numerals"]
    assert (n["Nn"], n["Nb"], n["Nu"], n["lines_carrying"], n["of_population"], n["bound_share"]) == (3, 2, 1, 3, 4, None)
    r = res["result"]
    assert (r["window_opened"], r["chain_problems"], r["lines_after_day_anchor"], r["unanchored_deliveries"],
            r["census_run"], r["n_deliveries"]) == (1, 0, 0, 4, 0, 4)
    assert all(res["window"]["opening_condition"][k]["held"] for k in "abcd")
    assert res["gates"]["block_sha256"] == res["gates"]["gates_sha256_registered"]
    assert res["registration"]["entry"]["registration_sha256"] == res["registration"]["digest_read"]


def test_held_and_open_with_export(seams, tmp_path):
    res, _ = _run(tmp_path, "h", export=HELD, anchors=ANCHORS)
    assert res["verdict"] == "HELD__every_exported_delivery_has_a_line"
    c = res["census"]
    assert (c["E"], c["exact"], c["normalised"], c["native"], c["unmatched"], c["missing_from_export"]) == (5, 3, 1, 1, 0, 0)
    assert (c["instrument"]["built"], c["instrument"]["read"]) == (5, 5)
    aw = res["anchors"]["window"]
    assert (aw["days_with_lines"], aw["anchored_days_with_lines"], aw["late"]) == (3, 3, 1)
    assert res["anchors"]["lines_after_last_anchor"] == 0
    assert res["sentences"][0].startswith("between 2026-10-01 and 2026-10-29")
    assert "the census read 5 of 5 planted misses" in res["sentences"][0]
    res, _ = _run(tmp_path, "o", export=OPEN, anchors=ANCHORS)
    assert res["verdict"] == "OPEN__deliveries_without_a_line"
    assert (res["census"]["E"], res["result"]["unledgered_deliveries"]) == (6, 1)


# ---- M1: the registration digest binds every byte above section 15

def test_m1_bar_moved_after_registration_is_refused(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    moved = t.replace("| min_deliveries = `3` |", "| min_deliveries = `1` |").replace('"op": ">=", "value": 3,', '"op": ">=", "value": 1,')
    assert moved != t
    res, _ = _run(tmp_path, "m1", prereg=_write(tmp_path, "p1.md", M.regate(moved)), export=HELD, anchors=ANCHORS)
    assert res["status"] == "refused" and res["refusal"]["code"] == "registration_mismatch"
    rule = t.replace("| normalisation_rule = `strip` |", "| normalisation_rule = `nfc+strip` |")
    res, _ = _run(tmp_path, "m1b", prereg=_write(tmp_path, "p2.md", rule), export=HELD, anchors=ANCHORS)
    assert res["status"] == "refused" and res["refusal"]["code"] == "registration_mismatch"


def test_m1_commit_url_refused(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8").replace(M.REG_URL, "https://example.invalid/opfixture/census/commit/" + M.REG_COMMIT)
    res, _ = _run(tmp_path, "cu", prereg=_write(tmp_path, "cu.md", _reseal(t)))
    assert res["status"] == "refused" and res["refusal"]["code"] == "registration_url"


def test_digests_cli(cli):
    r = cli("census-digests", "--prereg", PREREG)
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["gates"]["reached_by_row"] == [128, 64, 32, 16, 8, 4, 2, 1, 1] and d["gates"]["unreached"] == 0
    assert d["registration_sha256"] in PREREG.read_text(encoding="utf-8")


# ---- M2: no posted anchor, no held

def test_m2_empty_anchors_is_not_held(seams, tmp_path):
    empty = _write(tmp_path, "anchors_empty.json", '{"anchors": []}\n')
    res, _ = _run(tmp_path, "m2", export=HELD, anchors=str(empty))
    assert res["verdict"] == "UNANCHORED__deliveries_on_days_without_a_posted_anchor"
    assert res["result"]["unanchored_deliveries"] == 4 and res["result"]["lines_after_day_anchor"] == 0


def test_m2_anchor_place_fails(seams, tmp_path):
    res, _ = _run(tmp_path, "pf", export=HELD, anchors=ANCHORS, anchor_place="fails: the operator hosts the index")
    assert res["verdict"] == "UNANCHORED__deliveries_on_days_without_a_posted_anchor"
    assert res["anchors"]["place_fails"] == "the operator hosts the index"


# ---- M3: one line per message

def test_m3_duplicate_delivery_is_unledgered(seams, tmp_path):
    doc = json.loads((FIX / "export_held.json").read_text(encoding="utf-8"))
    doc["messages"].append(dict(doc["messages"][0]))
    p = _write(tmp_path, "export_dup.json", json.dumps(doc))
    res, _ = _run(tmp_path, "m3", export=str(p), anchors=ANCHORS)
    c = res["census"]
    assert (c["E"], c["exact"], c["unmatched"]) == (6, 3, 1)
    assert res["verdict"] == "OPEN__deliveries_without_a_line"


# ---- M4: the scored bytes are the bytes at ledger_url

def test_m4_ledger_bound_to_url(seams, tmp_path):
    res, _ = _run(tmp_path, "u", ledger=None)
    assert res["ledger"]["source"] == M.LEDGER_URL and res["ledger"]["bound"].startswith("the bytes at ledger_url")
    res, _ = _run(tmp_path, "l", ledger=str(LEDGER))
    assert res["status"] == "scored" and res["ledger"]["bound"].startswith("a local copy whose sha256 equals")
    other = _write(tmp_path, "ledger.jsonl", LEDGER.read_text(encoding="utf-8").rsplit("\n", 2)[0] + "\n")
    res, _ = _run(tmp_path, "x", ledger=str(other))
    assert res["status"] == "refused" and res["refusal"]["code"] == "ledger_not_registered"
    res, _ = _run(tmp_path, "y", ledger="https://example.invalid/somewhere/else.jsonl")
    assert res["status"] == "refused" and res["refusal"]["code"] == "ledger_not_registered"


# ---- M5: the forms of "how to fill"

def test_m5_forms_refused(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    bad = _reseal(t.replace("| normalisation_rule = `strip` |", "| normalisation_rule = `lowercase` |"))
    res, _ = _run(tmp_path, "n", prereg=_write(tmp_path, "n.md", bad))
    assert res["status"] == "refused" and res["refusal"]["code"] == "normalisation_rule"
    bad = _reseal(t.replace('| native_strings = `["censusbot pinned a message"]` |', "| native_strings = `censusbot pinned a message` |"))
    res, _ = _run(tmp_path, "s", prereg=_write(tmp_path, "s.md", bad))
    assert res["status"] == "refused" and res["refusal"]["code"] == "native_strings"


# ---- M6: (c) is the shelf's report, verified, and no window opens without a v1 row

def test_m6_no_shelf_row_no_window(tmp_path, monkeypatch):
    M.install_seams(census, monkeypatch.setattr)
    monkeypatch.setattr(census, "SHELF_HAS_V1_ROW", False)
    res, _ = _run(tmp_path, "c0", export=HELD, anchors=ANCHORS)
    assert res["verdict"] == "NOT_RUN__window_did_not_open"
    assert res["window"]["opening_condition"]["c"]["evidence"].startswith("stated, unverified")


def test_m6_shelf_read_before_anchor_day_fails(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8").replace("at 2026-09-30T12:00:00Z", "at 2026-09-01T00:00:00Z")
    res, _ = _run(tmp_path, "c1", prereg=_write(tmp_path, "c1.md", t), export=HELD, anchors=ANCHORS)
    assert res["verdict"] == "NOT_RUN__window_did_not_open"
    assert "read_after_the_anchors_day_ended FAILS" in res["window"]["opening_condition"]["c"]["evidence"]


# ---- rank 4 (improvements 2026-11-09): the shelf report must be on the shelf, never on a host the operator holds

OPERATOR_SHELF = "https://kestrel-ops.github.io/shelf/censusbot.json"


def test_rank4_operator_hosted_report_is_refused(tmp_path, monkeypatch):
    """the same report bytes, served from the operator's own host: (c) fails, the window does not open, and the
    scorer never fetches the operator's url."""
    mp = M.fetch_map()
    mp[OPERATOR_SHELF] = FIX / "shelf_report.json"
    monkeypatch.setattr(M, "fetch_map", lambda: mp)
    M.install_seams(census, monkeypatch.setattr)
    fetched = []
    inner = census._fetch_once
    monkeypatch.setattr(census, "_fetch_once", lambda src: (fetched.append(src), inner(src))[1])
    t = PREREG.read_text(encoding="utf-8").replace(M.SHELF_URL, OPERATOR_SHELF)
    assert OPERATOR_SHELF in t
    res, _ = _run(tmp_path, "r4", prereg=_write(tmp_path, "r4.md", t), export=HELD, anchors=ANCHORS)
    c = res["window"]["opening_condition"]["c"]
    assert c["held"] is False and c["verified"] is True
    assert "report_on_the_shelf FAILS" in c["evidence"] and census.SHELF_REPORT_PREFIX in c["evidence"]
    assert res["verdict"] == "NOT_RUN__window_did_not_open"
    assert OPERATOR_SHELF not in fetched


def test_rank4_the_kit_constant_is_the_shelfs_kept_reads(tmp_path, monkeypatch):
    """without the seams' stand-in prefix, the fixture's own example.invalid report is not the shelf's either."""
    real = census.SHELF_REPORT_PREFIX
    assert real == "https://fathom-lab.github.io/styxx-shelf/reports/reads/"
    M.install_seams(census, monkeypatch.setattr)
    monkeypatch.setattr(census, "SHELF_REPORT_PREFIX", real)
    res, _ = _run(tmp_path, "r4k", export=HELD, anchors=ANCHORS)
    assert "report_on_the_shelf FAILS" in res["window"]["opening_condition"]["c"]["evidence"]
    assert res["verdict"] == "NOT_RUN__window_did_not_open"


def test_rank4_the_same_report_on_the_shelf_holds(seams, tmp_path):
    res, _ = _run(tmp_path, "r4h", export=HELD, anchors=ANCHORS)
    c = res["window"]["opening_condition"]["c"]
    assert c["held"] is True and "report_on_the_shelf" not in c["evidence"]
    assert res["verdict"] == "HELD__every_exported_delivery_has_a_line"


@pytest.mark.parametrize("url,ok", [
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/kestrel/2026-11-09T06-00-35Z.json", True),
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/", False),
    ("http://fathom-lab.github.io/styxx-shelf/reports/reads/kestrel/a.json", False),
    ("https://fathom-lab.github.io/styxx-shelf/reports/kestrel.json", False),
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/../../../evil/a.json", False),
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/%2e%2e/a.json", False),
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/a.json?x=1", False),
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/a.json#x", False),
    ("https://fathom-lab.github.io/styxx-shelf/reports/reads/a\\..\\b.json", False),
    ("https://fathom-lab.github.io.evil.example/styxx-shelf/reports/reads/a.json", False),
    ("https://kestrel-ops.github.io/styxx-shelf/reports/reads/a.json", False),
    ("C:/shelf/reports/reads/a.json", False),
])
def test_rank4_on_the_shelf_rule(url, ok):
    assert census._on_the_shelf(url) is ok


# ---- rank 21 (improvements 2026-11-09): a crlf copy is refused as crlf, never as "no gates block"

def test_rank21_crlf_prereg_is_refused_as_crlf(seams, tmp_path):
    crlf = tmp_path / "crlf.md"
    crlf.write_bytes(PREREG.read_bytes().replace(b"\n", b"\r\n"))
    res, _ = _run(tmp_path, "crlf", prereg=crlf, export=HELD, anchors=ANCHORS)
    assert res["status"] == "refused" and res["refusal"]["code"] == "crlf", res.get("refusal")
    assert "lf bytes" in res["refusal"]["reason"] and "dos2unix" in res["refusal"]["reason"]


def test_rank21_one_crlf_is_enough(seams, tmp_path):
    one = tmp_path / "one.md"
    one.write_bytes(PREREG.read_bytes().replace(b"\n", b"\r\n", 1))
    res, _ = _run(tmp_path, "one", prereg=one)
    assert res["refusal"]["code"] == "crlf"


def test_rank21_digests_refuse_crlf(cli, tmp_path):
    crlf = tmp_path / "crlf.md"
    crlf.write_bytes(PREREG.read_bytes().replace(b"\n", b"\r\n"))
    r = cli("census-digests", "--prereg", crlf)
    assert r.returncode == 1, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["refused"]["code"] == "crlf" and d["gates"] is None


# ---- M7: a chain that does not re-derive is scored to BROKEN; unreachable is a component

def test_m7_broken_chain_is_broken(seams, tmp_path, monkeypatch):
    raw = LEDGER.read_bytes()
    lines = raw.split(b"\n")
    lines[4] = lines[4].replace(b'"dest":"chan-1"', b'"dest":"chan-2"')
    assert lines[4] != raw.split(b"\n")[4]
    bad = tmp_path / "ledger_bad.jsonl"
    bad.write_bytes(b"\n".join(lines))
    mp = M.fetch_map()
    mp[M.LEDGER_URL] = bad
    monkeypatch.setattr(M, "fetch_map", lambda: mp)
    M.install_seams(census, monkeypatch.setattr)
    res, _ = _run(tmp_path, "b", export=HELD, anchors=ANCHORS)
    assert res["status"] == "scored" and res["verdict"] == "BROKEN__chain_does_not_rederive"
    assert res["chain_problem_components"]["verifier_problems"] >= 1
    assert "entry_id" in res["problem_codes"] and res["problem_seqs"]
    assert "problem records" in res["sentences"][0] and "at seqs" in res["sentences"][0]


def test_m7_unreachable_after_three_tries(seams, tmp_path, monkeypatch):
    def down(src):
        raise census.Refused("unreachable", "%s did not answer within 30 s: URLError" % src)
    monkeypatch.setattr(census, "_fetch_once", down)
    slept = []
    res, _ = _run(tmp_path, "un", ledger=None, tries=3, interval_s=3600, sleep=slept.append)
    assert res["chain_problem_components"]["unreachable"] == 1
    assert res["ledger"]["tries"]["used"] == 3 and slept[:2] == [3600, 3600]
    assert res["status"] != "refused"


# ---- S1: an unmeasured js leg is not agreement

def test_s1_unmeasured_js_is_undecided(seams, tmp_path):
    res, _ = _run(tmp_path, "nj", export=HELD, anchors=ANCHORS, js=False)
    assert res["verdict"] == "UNDECIDED__a_gate_the_row_needs_is_unmeasured"
    assert res["result"]["chain_problems_unmeasured"] == ["implementations_disagree"]


# ---- S2: open values refused once d0 is filled

def test_s2_open_value_with_d0_refused(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    t = t.replace("| census_source = `the fixture's", "| census_source = `[builder-set: open] the fixture's")
    res, _ = _run(tmp_path, "o2", prereg=_write(tmp_path, "o2.md", _reseal(t)))
    assert res["status"] == "refused" and res["refusal"]["code"] == "open_value"


# ---- S5: the gates digest is the kit's, and a mismatch is refused

def test_s5_gates_digest_mismatch_refused(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    t = M.re.sub(r"^\| gates_sha256 = `[0-9a-f]{64}` \|", "| gates_sha256 = `%s` |" % ("0" * 64), t, count=1, flags=M.re.M)
    t = M.seal(t, M.hashlib.sha256((FIX / "shelf_report.json").read_bytes()).hexdigest())
    res, _ = _run(tmp_path, "g", prereg=_write(tmp_path, "g.md", t))
    assert res["status"] == "refused" and res["refusal"]["code"] == "gates_sha256"


def test_refuse_moved_lab_set_bar(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    old = '"metric": "result.chain_problems", "op": "==", "value": 0'
    assert old in t
    res, _ = _run(tmp_path, "m", prereg=_write(tmp_path, "m.md", _reseal(t.replace(old, old[:-1] + "1"))))
    assert res["status"] == "refused" and res["refusal"]["code"] == "gates_block"


# ---- S7: the instrument check

def test_s7_uncalibrated_instrument(seams, tmp_path, monkeypatch):
    real = census._match

    def many_to_one(msgs, pool, norm, natives):
        fat = {h: s * 10 for h, s in pool.items()}   # an instrument that lets one line cover repeats
        return real(msgs, fat, norm, natives)
    monkeypatch.setattr(census, "_match", many_to_one)
    res, _ = _run(tmp_path, "s7", export=HELD, anchors=ANCHORS)
    assert res["verdict"] == "UNCALIBRATED__the_census_missed_a_planted_miss"
    missed = [p["plant"] for p in res["census"]["instrument"]["plants"] if p["built"] and not p["read"]]
    assert "a duplicate of a ledgered text" in missed


def test_window_edge_message_reads_unledgered(seams, tmp_path):
    doc = json.loads((FIX / "export_held.json").read_text(encoding="utf-8"))
    doc["messages"].append({"account": "censusbot#0001", "destination": "chan-1", "timestamp": "2026-10-29T03:59:00Z",
                            "text": "a message at 23:59 on the last day"})
    p = _write(tmp_path, "export_edge.json", json.dumps(doc))
    res, _ = _run(tmp_path, "edge", export=str(p), anchors=ANCHORS)
    assert res["result"]["unledgered_deliveries"] == 1


# ---- refusals, timing, determinism, privacy

def test_refuse_unfilled_placeholder(seams, tmp_path):
    p = _write(tmp_path, "PREREG_half.md", PREREG.read_text(encoding="utf-8").replace("2026-09-30", "{{registration_date}}", 1))
    res, out = _run(tmp_path, "r", prereg=p)
    assert res["status"] == "refused" and res["refusal"]["code"] == "placeholder_left"
    assert json.loads((out / "RESULT.json").read_text(encoding="utf-8"))["status"] == "refused"
    assert (out / "RESULT.md").exists()


def test_refuse_template_itself(seams, tmp_path):
    p = _write(tmp_path, "PREREG_census_TEMPLATE.md", "# t\n\n## the placeholders\n\n| `{{operator}}` | x |\n\n---\n")
    res, _ = _run(tmp_path, "t", prereg=p)
    assert res["status"] == "refused" and res["refusal"]["code"] == "placeholder_left"


def test_nothing_counted_before_window(seams, tmp_path):
    res, _ = _run(tmp_path, "p", now="2026-09-30T20:00:00Z")
    assert res["status"] == "nothing_counted" and res["verdict"] == "NOT_RUN__window_did_not_open"
    assert res["result"]["window_opened"] == 0
    assert res["sentences"][0].startswith("nothing counted:")
    assert "is before 00:00 2026-10-01" in res["sentences"][0]


def test_in_progress_scores_nothing(seams, tmp_path):
    res, _ = _run(tmp_path, "i", now="2026-10-05T12:00:00Z")
    assert res["status"] == "in_progress" and res["verdict"] is None
    assert "nothing is scored before 2026-10-30T04:00:00Z" in res["sentences"][0]


def test_open_d0_counts_nothing(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    t = t.replace("| d0 = `2026-10-01` |", "| d0 = `[builder-set: open]` |")
    t = t.replace("| close = `2026-10-29` |", "| close = `[builder-set: open]` |")
    res, _ = _run(tmp_path, "d", prereg=_write(tmp_path, "PREREG_open.md", t))
    assert res["status"] == "nothing_counted"
    assert res["lines"]["cells"]["pre_window"]["lines"] == 10


def test_deterministic(seams, tmp_path):
    _, a = _run(tmp_path, "one", export=HELD, anchors=ANCHORS)
    _, b = _run(tmp_path, "two", export=HELD, anchors=ANCHORS)
    for name in ("RESULT.json", "RESULT.md"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_no_line_text_in_result(seams, tmp_path):
    _, out = _run(tmp_path, "x", export=OPEN, anchors=ANCHORS)
    blob = (out / "RESULT.json").read_text(encoding="utf-8") + (out / "RESULT.md").read_text(encoding="utf-8")
    for t in ("census fixture message", "a message the writer never saw", "a reader's reply", "styxx census plant"):
        assert t not in blob


def test_js_leg_agrees_when_node_is_here(tmp_path, monkeypatch):
    if shutil.which("node") is None:
        pytest.skip("no node on PATH")
    real_js = census._js_verify
    M.install_seams(census, monkeypatch.setattr)
    monkeypatch.setattr(census, "_js_verify", real_js)
    res, _ = _run(tmp_path, "j", export=HELD, anchors=ANCHORS)
    if res["js_leg"]["status"] != "measured":
        pytest.skip("js leg unmeasured: %s" % res["js_leg"].get("why"))
    assert res["chain_problem_components"]["implementations_disagree"] == 0
    assert res["verdict"] == "HELD__every_exported_delivery_has_a_line"


def test_cli_census(cli, tmp_path):
    """the cli in a subprocess (no seams): example.invalid does not answer, so the window cannot open. since rank 31
    (2026-11-09) that is exit 2 with the url named on the summary line, not exit 0; RESULT.json is still written."""
    out = tmp_path / "c"
    r = cli("census", "--prereg", PREREG, "--ledger", LEDGER, "--out", out, "--now", NOW, "--no-js", "--tries", "1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "did not answer: ledger_url after 1 try: %s" % M.LEDGER_URL in r.stdout, r.stdout
    assert "verdict NOT_RUN__window_did_not_open" in r.stdout
    doc = json.loads((out / "RESULT.json").read_text(encoding="utf-8"))
    assert doc["fetch_failures"][0]["what"] == "ledger_url" and doc["fetch_failures"][0]["source"] == M.LEDGER_URL
    assert doc["verdict"] == "NOT_RUN__window_did_not_open"
    assert doc["chain_problem_components"]["unreachable"] == 1
    c = doc["window"]["opening_condition"]["c"]
    # the scorer checks (c) itself against the shelf report the prereg names; example.invalid is not the shelf's
    # kept reads (census.SHELF_REPORT_PREFIX), so the check ran (verified) and did not hold
    assert c["held"] is False and c["verified"] is True, c
    bad = tmp_path / "half.md"
    bad.write_text("{{d0}}\n", encoding="utf-8")
    r = cli("census", "--prereg", bad, "--ledger", LEDGER, "--out", tmp_path / "c2", "--now", NOW, "--no-js")
    assert r.returncode == 1


# ---- improvements 2026-11-09, the census group (ranks 31, 48, 49, 50, 51, 69, 70)

def _row(text, name, value):
    """the table row of `name` set to `value` (the left cell only; the right cell is kept)."""
    out, n = re.subn(r"^\| %s = `[^`]*` \|" % re.escape(name), lambda m: "| %s = `%s` |" % (name, value), text,
                     count=1, flags=re.M)
    assert n == 1, name
    return out


def _down(src):
    raise census.Refused("unreachable", "%s did not answer within 30 s: URLError" % src)


# rank 31: each failed try and each wait is announced; the url that did not answer is named; RESULT.md says so

def test_rank31_each_try_and_wait_is_announced(seams, tmp_path, monkeypatch):
    monkeypatch.setattr(census, "_fetch_once", _down)
    said, slept = [], []
    res, out = _run(tmp_path, "r31", ledger=None, tries=3, interval_s=3600, sleep=slept.append, say=said.append)
    assert slept == [3600] * 4   # two waits for ledger_url, two for the shelf report (nothing answers here)
    tries = [s for s in said if s.startswith("census: ledger_url, try ")]
    assert len(tries) == 2 and "try 1 of 3" in tries[0] and "try 2 of 3" in tries[1]
    assert all(M.LEDGER_URL in s and "the next try is in 3600 s" in s for s in tries)
    assert any(s.startswith("census: ledger_url did not answer after 3 tries: " + M.LEDGER_URL) for s in said)
    assert len(said) == 6
    f = res["fetch_failures"]
    assert [(x["what"], x["source"], x["tries_used"]) for x in f] == [("ledger_url", M.LEDGER_URL, 3),
                                                                      ("the shelf report", M.SHELF_URL, 3)]
    assert res["ledger"]["bound"].startswith("ledger_url did not answer in this run (after 3 tries)")
    md = (out / "RESULT.md").read_text(encoding="utf-8")
    assert "did not answer: ledger_url, after 3 tries: %s did not answer" % M.LEDGER_URL in md
    assert "fetched in this run" not in md


def test_rank31_a_run_that_answers_announces_nothing(seams, tmp_path):
    said = []
    res, _ = _run(tmp_path, "r31ok", say=said.append)
    assert said == [] and res["fetch_failures"] == []


def test_rank31_cli_names_the_url_and_exits_2(cli, tmp_path):
    r = cli("census", "--prereg", PREREG, "--out", tmp_path / "c31", "--now", NOW, "--no-js", "--tries", "2",
            "--interval", "0")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "census: ledger_url, try 1 of 2: %s did not answer" % M.LEDGER_URL in r.stderr, r.stderr
    assert "did not answer: ledger_url after 2 tries: %s" % M.LEDGER_URL in r.stdout, r.stdout
    assert (tmp_path / "c31" / "RESULT.json").exists()


# rank 48: "counted by" names the run's own runner, never the lab by default

def test_rank48_counted_by_names_the_runner(seams, tmp_path):
    for runner, words in (("operator", "counted by its operator"), ("lab", "counted by the lab"),
                          ("other", "counted by a runner other than the lab and the operator"),
                          (None, "counted by a runner this run does not name")):
        res, out = _run(tmp_path, "r48%s" % runner, export=HELD, anchors=ANCHORS, runner=runner)
        assert res["verdict"] == "HELD__every_exported_delivery_has_a_line"
        assert res["runner"] == (runner or "not stated")
        assert words in res["sentences"][0], res["sentences"][0][-200:]
        assert ("counted by: %s" % (runner or "not stated")) in (out / "RESULT.md").read_text(encoding="utf-8")
        if runner != "lab":
            assert "counted by the lab" not in res["sentences"][0]
    res, _ = _run(tmp_path, "r48bad", runner="me")
    assert res["status"] == "refused" and res["refusal"]["code"] == "runner"


def test_rank48_cli_takes_runner(cli, tmp_path):
    r = cli("census", "--prereg", PREREG, "--ledger", LEDGER, "--out", tmp_path / "c48", "--now", NOW, "--no-js",
            "--tries", "1", "--runner", "operator")
    doc = json.loads((tmp_path / "c48" / "RESULT.json").read_text(encoding="utf-8"))
    assert doc["runner"] == "operator", r.stdout + r.stderr
    assert cli("census", "--prereg", PREREG, "--out", tmp_path / "c48b", "--runner", "lab-ish").returncode == 2


# rank 49: the registered scorer, kit and writer are compared with the running ones; both are printed

def _running_census_sha():
    return hashlib.sha256(Path(census.__file__).read_bytes()).hexdigest()


def test_rank49_scorer_hash_is_compared(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    res, out = _run(tmp_path, "z", prereg=_write(tmp_path, "z.md", _reseal(_row(t, "scorer_sha256", "0" * 64))),
                    export=HELD, anchors=ANCHORS)
    assert res["status"] == "refused" and res["refusal"]["code"] == "scorer_sha256"
    assert res["locks"]["scorer"] == {"registered": "0" * 64, "reads": "differs"}
    assert res["scorer"]["sha256"] == _running_census_sha() and res["scorer"]["sha256"] in res["refusal"]["reason"]
    md = (out / "RESULT.md").read_text(encoding="utf-8")
    assert "registered %s; running census.py sha256 %s" % ("0" * 64, _running_census_sha()) in md
    same = _reseal(_row(t, "scorer_sha256", _running_census_sha()))
    res, _ = _run(tmp_path, "s", prereg=_write(tmp_path, "s.md", same), export=HELD, anchors=ANCHORS)
    assert res["locks"]["scorer"]["reads"] == "same" and res["verdict"] == "HELD__every_exported_delivery_has_a_line"
    res, _ = _run(tmp_path, "w", prereg=_write(tmp_path, "w.md", _reseal(_row(t, "scorer_sha256", "census.py"))))
    assert res["status"] == "refused" and res["refusal"]["code"] == "scorer_sha256"
    res, _ = _run(tmp_path, "n", export=HELD, anchors=ANCHORS)   # the fixture: not built at the freeze, printed
    assert res["locks"]["scorer"]["reads"].startswith("not built at the freeze") and res["status"] == "scored"


def test_rank49_kit_vectors_hash_is_compared(seams, tmp_path, monkeypatch):
    t = PREREG.read_text(encoding="utf-8")
    vec = hashlib.sha256((TESTS.parent.parent / "vectors" / "vectors_v1.json").read_bytes()).hexdigest()
    assert census.kit_values()["kit_version"] == "styxx-ledger %s vectors_v1.json sha256 %s" % (census.__version__, vec)
    good = _reseal(_row(t, "kit_version", "styxx-ledger %s vectors_v1.json sha256 %s" % (census.__version__, vec)))
    res, _ = _run(tmp_path, "k1", prereg=_write(tmp_path, "k1.md", good), export=HELD, anchors=ANCHORS)
    assert res["locks"]["kit"]["reads"] == "same" and res["scorer"]["vectors_sha256"] == vec
    assert res["verdict"] == "HELD__every_exported_delivery_has_a_line"
    bad = _reseal(_row(t, "kit_version", "styxx-ledger 1.0.0a2 vectors_v1.json sha256 " + "ab" * 32))
    res, _ = _run(tmp_path, "k2", prereg=_write(tmp_path, "k2.md", bad))
    assert res["status"] == "refused" and res["refusal"]["code"] == "kit_version"
    assert res["locks"]["kit"]["vectors_sha256_registered"] == "ab" * 32
    monkeypatch.setattr(census, "_running_vectors", lambda: (None, "not beside this package (test)"))
    res, _ = _run(tmp_path, "k3", prereg=_write(tmp_path, "k3.md", bad), export=HELD, anchors=ANCHORS)
    assert res["locks"]["kit"]["reads"].startswith("unmeasured") and res["status"] == "scored"


def test_rank49_writer_is_compared(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    bad = _reseal(_row(t, "writer", "styxx-ledger 9.9.9 python"))
    res, _ = _run(tmp_path, "wr1", prereg=_write(tmp_path, "wr1.md", bad))
    assert res["status"] == "refused" and res["refusal"]["code"] == "writer"
    assert "seq 1 styxx-ledger 1.0.0a1 python" in res["refusal"]["reason"]
    obj = _reseal(_row(t, "writer", '{"name":"styxx-ledger","version":"1.0.0a1"}'))
    res, _ = _run(tmp_path, "wr2", prereg=_write(tmp_path, "wr2.md", obj), export=HELD, anchors=ANCHORS)
    assert res["locks"]["writer"]["reads"] == "same" and res["verdict"] == "HELD__every_exported_delivery_has_a_line"


def test_rank49_open_d0_prints_and_does_not_refuse(seams, tmp_path):
    t = PREREG.read_text(encoding="utf-8")
    t = _row(_row(t, "d0", "[builder-set: open]"), "close", "[builder-set: open]")
    t = _row(_row(t, "scorer_sha256", "0" * 64), "writer", "someone else 1")
    res, _ = _run(tmp_path, "od", prereg=_write(tmp_path, "od.md", t))
    assert res["status"] == "nothing_counted"
    assert res["locks"]["scorer"]["reads"] == "differs" and res["locks"]["writer"]["reads"] == "differs"


# rank 50: --rehearse scores a local copy offline and never prints a verdict

def test_rank50_rehearsal_is_offline_and_never_a_verdict(seams, tmp_path, monkeypatch):
    fetched = []
    inner = census._fetch_once
    monkeypatch.setattr(census, "_fetch_once", lambda src: (fetched.append(src), inner(src))[1])
    res, out = _run(tmp_path, "rh", ledger=str(LEDGER), export=HELD, anchors=ANCHORS, rehearse=True)
    assert [s for s in fetched if census._is_url(s)] == []
    assert res["status"] == "rehearsal" and res["verdict"] is None
    rh = res["rehearsal"]
    assert (rh["status_if_report_holds"], rh["row_if_report_holds"]) == ("scored",
                                                                         "HELD__every_exported_delivery_has_a_line")
    c = res["window"]["opening_condition"]["c"]
    assert c["held"] is False and c["offline_held"] is True and "not fetched in a rehearsal" in c["evidence"]
    assert res["result"]["window_opened"] == 0 and res["ledger"]["bound"].startswith("rehearsal: a local copy")
    assert res["sentences"][0].startswith("rehearsal, not a result") and "no verdict is printed" in res["sentences"][0]
    md = (out / "RESULT.md").read_text(encoding="utf-8")
    assert "status: rehearsal" in md and "verdict: none" in md


def test_rank50_rehearsal_needs_a_local_copy_and_names_what_it_skipped(seams, tmp_path):
    res, _ = _run(tmp_path, "rh2", rehearse=True)
    assert res["status"] == "refused" and res["refusal"]["code"] == "rehearse"
    url = "https://example.invalid/censusbot/anchors.json"
    res, _ = _run(tmp_path, "rh3", ledger=str(LEDGER), anchors=url, rehearse=True, now="2026-10-05T12:00:00Z")
    assert res["rehearsal"]["not_fetched"] == [{"what": "the posted anchor texts", "url": url}]
    assert res["rehearsal"]["status_if_report_holds"] == "in_progress" and res["fetch_failures"] == []
    t = PREREG.read_text(encoding="utf-8")
    zeros = _reseal(_row(t, "scorer_sha256", "0" * 64))
    res, _ = _run(tmp_path, "rh4", prereg=_write(tmp_path, "rh4.md", zeros), ledger=str(LEDGER), rehearse=True)
    assert res["status"] == "refused" and res["refusal"]["code"] == "scorer_sha256"   # a fill mistake, caught offline


def test_rank50_cli_rehearsal(cli, tmp_path):
    r = cli("census", "--prereg", PREREG, "--rehearse", "--ledger", LEDGER, "--anchors", ANCHORS, "--export", HELD,
            "--now", NOW, "--out", tmp_path / "rh", "--no-js")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("rehearsal: no verdict") and "did not answer" not in r.stdout + r.stderr
    doc = json.loads((tmp_path / "rh" / "RESULT.json").read_text(encoding="utf-8"))
    assert doc["status"] == "rehearsal" and doc["verdict"] is None and doc["fetch_failures"] == []


# rank 51: census-digests prints the values a fill copies, from the ledger and from the kit

def test_rank51_digests_print_the_values_a_fill_copies(cli):
    r = cli("census-digests", "--ledger", LEDGER)
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    fl, t = d["from_the_ledger"], PREREG.read_text(encoding="utf-8")
    for name in ("header_digest", "writer", "earliest_anchor", "kinds", "certifies", "anchor_tz", "agent"):
        assert "| %s = `%s` |" % (name, fl[name]) in t, (name, fl[name])
    assert d["from_this_kit"]["scorer_sha256"] == _running_census_sha()
    assert d["from_this_kit"]["kit_version"] == census.kit_values()["kit_version"]
    r = cli("census-digests", "--prereg", PREREG, "--ledger", LEDGER)
    d = json.loads(r.stdout)
    assert r.returncode == 0 and "registration_sha256" in d and "from_the_ledger" in d
    assert cli("census-digests").returncode == 2
    ex = VECTORS / "exhibit"   # a v0 chain with withheld lines: the earliest anchor is the one the exhibit posted
    r = cli("census-digests", "--ledger", ex / "ledger.jsonl", "--withheld", ex / "withheld.json")
    fl = json.loads(r.stdout)["from_the_ledger"]
    posted = json.loads((ex / "anchors" / "index.json").read_text(encoding="utf-8"))["anchors"][0]["text"]
    assert r.returncode == 0 and fl["rederives"] is True and fl["earliest_anchor"] == posted
    assert cli("census-digests", "--ledger", ex / "ledger.jsonl").returncode == 1   # without the list it does not re-derive


# rank 69: the verbatim rows keep a trailing parenthesis

def test_rank69_certifies_keeps_its_parenthesis():
    t = _row(PREREG.read_text(encoding="utf-8"), "certifies", "one line per message (hashes only)")
    t = _row(t, "delivery_kinds", "send (the only delivery kind)")
    cut = census.parse_prereg(t)["cut"]
    assert cut["certifies"] == "one line per message (hashes only)"
    assert cut["delivery_kinds"] == "send"


def test_rank69_a_header_ending_in_a_parenthesis_matches(tmp_path, monkeypatch):
    cert = "one line per message censusbot delivered (hashes only)"
    assert census._cut_comment(cert) != cert   # the rule that used to cut it
    monkeypatch.setattr(M, "CERTIFIES", cert)
    led = tmp_path / "ledger69.jsonl"
    meta = M.build_ledger(led)
    shelf = tmp_path / "shelf69.json"
    shelf.write_bytes(M.shelf_report(meta))
    mp = M.fetch_map()
    mp[M.LEDGER_URL], mp[M.SHELF_URL] = led, shelf
    monkeypatch.setattr(M, "fetch_map", lambda: mp)
    M.install_seams(census, monkeypatch.setattr)
    t = _row(PREREG.read_text(encoding="utf-8"), "certifies", cert)
    t = _row(_row(t, "header_digest", meta["header_digest"]), "earliest_anchor", meta["anchors"][0])
    p = _write(tmp_path, "p69.md", M.seal(M.regate(t), hashlib.sha256(shelf.read_bytes()).hexdigest()))
    res, _ = _run(tmp_path, "r69", prereg=p)
    assert res["status"] == "scored", res.get("refusal")
    assert res["header"]["certifies"] == cert and res["header"]["mismatch_with_registration"] == []
    assert res["window"]["opening_condition"]["c"]["held"] is True


# rank 70: every url the scorer fetches is https; an http url is refused before any fetch

def test_rank70_http_is_refused(seams, tmp_path, monkeypatch):
    fetched = []
    inner = census._fetch_once
    monkeypatch.setattr(census, "_fetch_once", lambda src: (fetched.append(src), inner(src))[1])
    t = PREREG.read_text(encoding="utf-8")
    http_ledger = M.LEDGER_URL.replace("https://", "http://")
    h1 = _reseal(_row(t, "ledger_url", http_ledger))
    res, _ = _run(tmp_path, "h1", prereg=_write(tmp_path, "h1.md", h1), ledger=None)
    assert res["status"] == "refused" and res["refusal"]["code"] == "ledger_url"
    h2 = _reseal(_row(t, "anchors_url", "http://example.invalid/a.json"))
    res, _ = _run(tmp_path, "h2", prereg=_write(tmp_path, "h2.md", h2))
    assert res["status"] == "refused" and res["refusal"]["code"] == "anchors_url"
    res, _ = _run(tmp_path, "h3", anchors="http://example.invalid/a.json")
    assert res["status"] == "refused" and res["refusal"]["code"] == "http"
    res, _ = _run(tmp_path, "h4", export="http://example.invalid/export.json", anchors=ANCHORS)
    assert res["status"] == "refused" and res["refusal"]["code"] == "http"
    o = _row(_row(t, "d0", "[builder-set: open]"), "close", "[builder-set: open]")
    res, _ = _run(tmp_path, "h5", prereg=_write(tmp_path, "h5.md", _row(o, "ledger_url", http_ledger)), ledger=None)
    assert res["status"] == "refused" and res["refusal"]["code"] == "http"
    assert [s for s in fetched if s.startswith("http://")] == []


# ---- the review of 2026-11-09 (census group): the export goes through the one fetch helper; a refusal keeps what did
# not answer and the locks; a rehearsal prints its own sentence and nothing after it

EXPORT_URL = "https://example.invalid/censusbot/export.json"   # not in the seams' fetch map: it does not answer
COVERAGE_LINE = re.compile(r"^(> )?(G-1|G-2|the anchor check|the instrument check)", re.M)


def test_review_export_url_that_does_not_answer_is_a_fetch_failure(seams, tmp_path):
    """an https export that does not answer is tried and waited for as any url, named in fetch_failures, and leaves
    census_run 0: the row is UNFALSIFIED, and its sentence says the export did not answer. it is never a refusal."""
    said, slept = [], []
    res, out = _run(tmp_path, "ex", export=EXPORT_URL, anchors=ANCHORS, tries=2, interval_s=60, sleep=slept.append,
                    say=said.append)
    assert res["status"] == "scored", res.get("refusal")
    assert res["verdict"] == "UNFALSIFIED__no_census_of_the_destinations"
    assert [(f["what"], f["source"], f["tries_used"]) for f in res["fetch_failures"]] == [("the export", EXPORT_URL, 2)]
    assert slept == [60]
    assert any(s.startswith("census: the export, try 1 of 2: %s did not answer" % EXPORT_URL) for s in said), said
    assert any(s.startswith("census: the export did not answer after 2 tries: " + EXPORT_URL) for s in said), said
    c = res["census"]
    why = "the export did not answer in this run, after 2 tries; no message was read"
    assert res["result"]["census_run"] == 0 and c["why_not_run"] == why
    assert c["export"] == {"source": EXPORT_URL, "tries_used": 2,
                           "failure": {"code": "unreachable", "reason": "%s did not answer within 30 s: URLError"
                                                                        % EXPORT_URL}}
    s0 = res["sentences"][0]
    assert "but the export of chan-1 https://example.invalid/chan-1 for the window named for this run did not " \
           "answer;" in s0 and "was committed" not in s0, s0
    assert "G-1: unmeasured (%s)." % why in res["sentences"]
    md = (out / "RESULT.md").read_text(encoding="utf-8")
    assert "did not answer: the export, after 2 tries: %s did not answer" % EXPORT_URL in md
    assert "census: not run (%s)" % why in md


def test_review_export_file_that_cannot_be_read_is_a_fetch_failure(seams, tmp_path):
    res, _ = _run(tmp_path, "exf", export=str(tmp_path / "no_such_export.json"), anchors=ANCHORS)
    assert res["status"] == "scored" and res["verdict"] == "UNFALSIFIED__no_census_of_the_destinations"
    assert [(f["what"], f["source"], f["tries_used"], f["failure"]["code"]) for f in res["fetch_failures"]] == [
        ("the export", "no_such_export.json", 1, "unreadable")]
    assert res["census"]["why_not_run"] == "the export did not answer in this run, after 1 try; no message was read"


def test_review_export_that_is_not_json_is_refused_and_keeps_what_did_not_answer(seams, tmp_path):
    """bytes that arrive and are not the export's json are still a refusal; the refused RESULT.json keeps every source
    that did not answer before it, and the locks."""
    bad = _write(tmp_path, "export_bad.json", "not json")
    gone = "https://example.invalid/censusbot/anchors_gone.json"
    res, out = _run(tmp_path, "exj", export=str(bad), anchors=gone, tries=1)
    assert res["status"] == "refused" and res["refusal"]["code"] == "export"
    assert [(f["what"], f["source"]) for f in res["fetch_failures"]] == [("the posted anchor texts", gone)]
    assert sorted(res["locks"]) == ["kit", "scorer", "writer"]
    md = (out / "RESULT.md").read_text(encoding="utf-8")
    assert "did not answer: the posted anchor texts, after 1 try: %s did not answer" % gone in md
    assert "lock scorer_sha256: registered" in md and "refused (export): the export is not json" in md
    res, _ = _run(tmp_path, "exr", runner="me")   # refused before anything is read: an empty list, no locks
    assert res["status"] == "refused" and res["fetch_failures"] == [] and "locks" not in res


def test_review_cli_export_url_that_does_not_answer_exits_2(cli, tmp_path):
    """the review's run, in a subprocess (no seams): the ledger url and the export url do not answer; exit 2, both
    named, and RESULT.json is not a refusal. an export that is not json is refused (exit 1) and still names them."""
    out = tmp_path / "cx"
    r = cli("census", "--prereg", PREREG, "--ledger", LEDGER, "--export", EXPORT_URL, "--out", out, "--now", NOW,
            "--no-js", "--tries", "1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "; the export after 1 try: %s did not answer" % EXPORT_URL in r.stdout, r.stdout
    doc = json.loads((out / "RESULT.json").read_text(encoding="utf-8"))
    assert doc["status"] != "refused" and doc["verdict"] == "NOT_RUN__window_did_not_open"
    assert [(f["what"], f["source"]) for f in doc["fetch_failures"]] == [("ledger_url", M.LEDGER_URL),
                                                                         ("the export", EXPORT_URL)]
    bad = _write(tmp_path, "export_bad.json", "not json")
    r = cli("census", "--prereg", PREREG, "--ledger", LEDGER, "--export", bad, "--out", tmp_path / "cx2", "--now", NOW,
            "--no-js", "--tries", "1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.startswith("refused (export): the export is not json; did not answer: ledger_url after 1 try: "
                               + M.LEDGER_URL), r.stdout
    doc = json.loads((tmp_path / "cx2" / "RESULT.json").read_text(encoding="utf-8"))
    assert [f["what"] for f in doc["fetch_failures"]] == ["ledger_url"] and "scorer" in doc["locks"]


def test_review_rehearsal_prints_one_sentence(tmp_path, monkeypatch):
    """a rehearsal's sentences are its own sentence only: no G-1, G-2, anchor or instrument line, neither when the
    fill would not open (the kit's own shelf prefix: the README's command) nor when it would be scored (the seams)."""
    res, out = _run(tmp_path, "rn", ledger=str(LEDGER), export=HELD, anchors=ANCHORS, rehearse=True, js=False)
    assert res["status"] == "rehearsal" and res["rehearsal"]["status_if_report_holds"] == "nothing_counted"
    M.install_seams(census, monkeypatch.setattr)
    held, out2 = _run(tmp_path, "rs", ledger=str(LEDGER), export=HELD, anchors=ANCHORS, rehearse=True)
    assert held["rehearsal"]["row_if_report_holds"] == "HELD__every_exported_delivery_has_a_line"
    for r, o in ((res, out), (held, out2)):
        assert len(r["sentences"]) == 1 and r["sentences"][0].startswith("rehearsal, not a result"), r["sentences"]
        md = (o / "RESULT.md").read_text(encoding="utf-8")
        assert not COVERAGE_LINE.search(md), md
        assert [x for x in md.splitlines() if x.startswith("> ")] == ["> " + r["sentences"][0]]
