"""tests for census_check_readme.py.

    python -I -B -m pytest -q -p no:cacheprovider census/test_census_check_readme.py

RESULT is the census scorer's own expected fixture (python/tests/fixtures/census/expected_RESULT.json):
n_deliveries 4, anchored 0 of 3 days with lines (no posted texts), missing 2026-10-01 at index 0, unledgered null (no
export), verdict UNANCHORED (fixture rebuilt in the review round; the readme check itself is unchanged).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from census_check_readme import check  # noqa: E402

RESULT = json.loads((HERE.parent / "python" / "tests" / "fixtures" / "census" / "expected_RESULT.json")
                    .read_text(encoding="utf-8"))


def test_matching_readme_passes():
    md = ("the census counted 4 deliveries to chan-1 (census: result.n_deliveries = 4). it reads "
          "UNANCHORED <!-- census: verdict = UNANCHORED__deliveries_on_days_without_a_posted_anchor -->.\n"
          "0 of 3 days with lines were anchored (census: anchors.window.anchored_days_with_lines = 0); "
          "the earliest missing day was 2026-10-01 (census: anchors.window.missing_days.0 = \"2026-10-01\").\n")
    fails, seen = check(RESULT, md)
    assert fails == [] and seen == 4


def test_wrong_number_fails():
    fails, _ = check(RESULT, "the census counted 5 deliveries (census: result.n_deliveries = 5).\n")
    assert len(fails) == 1 and "RESULT.json says 4" in fails[0]


def test_prose_drift_fails():
    fails, _ = check(RESULT, "the census counted 5 deliveries (census: result.n_deliveries = 4).\n")
    assert len(fails) == 1 and "does not say 4" in fails[0]


def test_numeral_inside_another_number_does_not_count():
    fails, _ = check(RESULT, "the census counted 14 deliveries (census: result.n_deliveries = 4).\n")
    assert len(fails) == 1


def test_unknown_path_fails():
    fails, _ = check(RESULT, "0 of them (census: result.no_such_metric = 0).\n")
    assert len(fails) == 1 and "not in RESULT.json" in fails[0]


def test_refused_fails_and_no_marker_fails():
    fails, seen = check({"status": "refused", "refusal": {"code": "placeholder_left", "reason": "x"}}, "nothing here\n")
    assert seen == 0 and len(fails) == 2


def test_rehearsal_fails():
    """a census --rehearse RESULT is never a verdict, so no readme may quote it (improvements 2026-11-09 rank 50)."""
    reh = dict(RESULT, status="rehearsal", verdict=None)
    fails, seen = check(reh, "the census counted 4 deliveries (census: result.n_deliveries = 4).\n")
    assert seen == 1 and len(fails) == 1 and "rehearsal" in fails[0]


def test_null_and_string_values():
    fails, _ = check(RESULT, "no export, so unledgered is unmeasured (census: result.unledgered_deliveries = null).\n")
    assert fails == []
    fails, _ = check(RESULT, "x (census: result.n_deliveries = \"4\").\n")
    assert len(fails) == 1


def test_cli_exit_codes(tmp_path):
    r = tmp_path / "RESULT.json"
    r.write_text(json.dumps(RESULT), encoding="utf-8")
    ok = tmp_path / "ok.md"
    ok.write_text("4 deliveries (census: result.n_deliveries = 4).\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("3 deliveries (census: result.n_deliveries = 3).\n", encoding="utf-8")

    def run(*a):
        return subprocess.run([sys.executable, "-I", "-B", str(HERE / "census_check_readme.py"), *map(str, a)],
                              capture_output=True, text=True, timeout=60)
    assert run(r, ok).returncode == 0
    assert run(r, bad).returncode == 1
    assert run(r).returncode == 2
