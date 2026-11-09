"""the census scorer on the red ledger by url, under the 3d worked example (a v0 chain, d0 open).

a network test, kept out of the python suite's testpaths (REVIEW_3d note N4: a live, growing url does not belong in
the unit suite). run it from the kit root:

    PYTHONDONTWRITEBYTECODE=1 python -I -B -m pytest -q -p no:cacheprovider census/test_census_red_smoke.py

it skips, never fails, when the url does not answer; a skip here is a fact about the network, not about the scorer.
"""
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python" / "src"))
from styxx_ledger.census import score  # noqa: E402

RED_PREREG = REPO / "python" / "tests" / "fixtures" / "census" / "PREREG_census_EXAMPLE_red.md"  # a byte copy of the example
RED_LEDGER = "https://fathom-lab.github.io/styxx/ledger/red/ledger.jsonl"


def test_red_smoke(tmp_path):
    try:
        urllib.request.urlopen(RED_LEDGER, timeout=10).close()
    except (urllib.error.URLError, OSError):
        pytest.skip("red ledger url unreachable from here")
    res = score(RED_PREREG, None, tmp_path / "red", "2026-11-09T05:00:00Z", tries=1)
    if res["status"] == "refused" and res["refusal"]["code"] == "unreachable":
        pytest.skip("red ledger url unreachable from here")
    assert res["status"] == "nothing_counted" and res["verdict"] == "NOT_RUN__window_did_not_open"
    assert res["ledger"]["protocol"] == "v0" and res["ledger"]["source"] == RED_LEDGER
    assert res["ledger"]["entries"] >= 106
    assert res["lines"]["cells"]["pre_window"]["lines"] == res["ledger"]["entries"]
    assert res["window"]["opening_condition"]["d"]["held"] is True
    assert res["chain_problem_components"]["unreachable"] == 0
