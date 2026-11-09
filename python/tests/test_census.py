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
import json
import shutil

import pytest

from conftest import TESTS
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
    """the cli in a subprocess (no seams): example.invalid does not answer, so the window cannot open; exit 0."""
    out = tmp_path / "c"
    r = cli("census", "--prereg", PREREG, "--ledger", LEDGER, "--out", out, "--now", NOW, "--no-js", "--tries", "1")
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads((out / "RESULT.json").read_text(encoding="utf-8"))
    assert doc["verdict"] == "NOT_RUN__window_did_not_open"
    assert doc["chain_problem_components"]["unreachable"] == 1
    assert doc["window"]["opening_condition"]["c"]["evidence"].startswith("stated, unverified")
    bad = tmp_path / "half.md"
    bad.write_text("{{d0}}\n", encoding="utf-8")
    r = cli("census", "--prereg", bad, "--ledger", LEDGER, "--out", tmp_path / "c2", "--now", NOW, "--no-js")
    assert r.returncode == 1
