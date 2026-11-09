"""a python with no zone database (python.org windows without tzdata) is the machine's fault, never the ledger's.

simulated two ways, as zoneinfo fails on such a box: available_timezones() empty, and a listed key whose
ZoneInfo(key) raises ZoneInfoNotFoundError ("No time zone found with key ..."). the verifier must raise
ZoneDatabaseMissing (not a problem record), the cli and the vectors runner must end exit 2 with
"pip install tzdata", and nothing may print a chain verdict."""
import subprocess
import sys
import zoneinfo

import pytest

import styxx_ledger as S
from styxx_ledger import day as D
from conftest import TESTS, VECTORS, child_env

FIXTURE = TESTS / "fixtures" / "py_written.jsonl"

# run in a child: break zoneinfo the way a tzdata-less windows python is broken, then run the target as __main__
_BOOT = r"""
import runpy, sys, zoneinfo
mode = sys.argv[1]
if mode == "empty":
    zoneinfo.available_timezones = lambda: set()
def _missing(key):
    raise zoneinfo.ZoneInfoNotFoundError("No time zone found with key %s" % key)
zoneinfo.ZoneInfo = _missing
target = sys.argv[2]
sys.argv = sys.argv[2:]
if target.endswith(".py"):
    runpy.run_path(target, run_name="__main__")
else:
    sys.argv[0] = target
    runpy.run_module(target, run_name="__main__", alter_sys=True)
"""


def _child(mode, *args):
    return subprocess.run([sys.executable, "-B", "-c", _BOOT, mode, *map(str, args)], capture_output=True,
                          text=True, encoding="utf-8", env=child_env(), timeout=120)


@pytest.fixture
def no_zone_key(monkeypatch):
    """in process: every listed key raises ZoneInfoNotFoundError (the 'missing zoneinfo key')."""
    def _missing(key):
        raise zoneinfo.ZoneInfoNotFoundError("No time zone found with key %s" % key)
    monkeypatch.setattr(zoneinfo, "ZoneInfo", _missing)
    D._zone.cache_clear()
    yield
    D._zone.cache_clear()


@pytest.fixture
def no_zone_list(monkeypatch):
    """in process: the database lists nothing."""
    monkeypatch.setattr(D, "_available", lambda: frozenset())
    yield


def test_sound_ledger_reads_ok_with_the_database():
    assert S.verify_bytes(FIXTURE.read_bytes())["ok"]


def test_missing_key_for_a_listed_zone_is_the_database(no_zone_key):
    with pytest.raises(S.ZoneDatabaseMissing, match="pip install tzdata"):
        D.zone("America/New_York")
    with pytest.raises(S.ZoneDatabaseMissing):
        S.day_of("2026-11-09T05:00:00Z", "UTC")


def test_empty_database_is_the_database(no_zone_list):
    with pytest.raises(S.ZoneDatabaseMissing, match="pip install tzdata"):
        S.require_zone_database()
    with pytest.raises(S.ZoneDatabaseMissing):
        D.zone("UTC")


def test_names_that_are_not_zones_are_still_refused_as_anchor_tz(no_zone_list):
    for bad in ("Factory", "", "../etc", "/UTC"):
        with pytest.raises(S.LedgerValueError) as e:
            D.zone(bad)
        assert e.value.code == "anchor_tz"


@pytest.mark.parametrize("fx", ["no_zone_key", "no_zone_list"])
def test_verifier_never_turns_it_into_a_problem_record(fx, request):
    request.getfixturevalue(fx)
    with pytest.raises(S.ZoneDatabaseMissing):
        S.verify_bytes(FIXTURE.read_bytes())
    v0_line = (b'{"schema":"darkflobi.gate/log/v0"}\n'
               b'{"seq":1,"timestamp":"2026-11-09T05:00:00Z","day":"2026-11-09"}\n')
    with pytest.raises(S.ZoneDatabaseMissing):
        S.v0.verify_bytes_v0(v0_line)


@pytest.mark.parametrize("mode", ["empty", "key"])
def test_cli_verify_exits_2_with_the_hint(mode):
    r = _child(mode, "styxx_ledger", "verify", FIXTURE)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "pip install tzdata" in r.stderr
    assert "does not re-derive" not in r.stdout + r.stderr


@pytest.mark.parametrize("mode", ["empty", "key"])
def test_cli_exhibit_exits_2_before_any_fetch(mode):
    # port 9 on loopback: if the preflight did not stop it, the run would report a fetch failure instead
    r = _child(mode, "styxx_ledger", "exhibit", "http://127.0.0.1:9/ledger/", "--no-ots")
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "pip install tzdata" in r.stderr
    assert "ledger.jsonl" not in r.stdout
    assert "DOES NOT" not in r.stdout


@pytest.mark.parametrize("mode", ["empty", "key"])
def test_vectors_runner_exits_2_with_the_hint(mode):
    r = _child(mode, VECTORS / "run_vectors.py")
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "pip install tzdata" in r.stdout
    assert "vectors answered as the file says" not in r.stdout
