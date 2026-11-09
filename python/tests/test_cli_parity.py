"""the two command lines, side by side, on inputs where they used to answer differently (the lab's improvement sweep
of 2026-11-09). every case runs `python -m styxx_ledger` and `node js/bin/styxx-ledger.cjs`:

    rank 67  empty text: --certifies "", --agent "", --tz "", --kind "", --kinds with an empty item, an empty <log>:
             the same exit in both (1 a refusal, named by its code; 2 usage), and an empty --kinds item is refused,
             never dropped. javascript answered exit 2 "init needs --agent, --tz and --certifies" to a flag it was given.
    rank 43  a certifies of whitespace only is refused by both, whatever the runtime calls blank; a log either cli
             wrote takes appends from the other
    rank 42  anchor-text refuses an open day and an anchored day in both, exit 1, with the code
    rank 45  exhibit error paths: a mistyped url and an explorer that does not answer give the same report, line for
             line, and exit 2, in both

skipped, with the reason, when node is not on PATH.
"""
import os
import re
import shutil
import socket
import subprocess
import sys

import pytest

from conftest import JS, child_env

pytestmark = [pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH"),
              pytest.mark.skipif(not (JS / "bin" / "styxx-ledger.cjs").exists(), reason="js/ is not beside python/")]
CLIS = {"python": [sys.executable, "-B", "-m", "styxx_ledger"], "js": ["node", str(JS / "bin" / "styxx-ledger.cjs")]}


def run(who, *args, timeout=120):
    cp = subprocess.run(CLIS[who] + [str(a) for a in args], capture_output=True, text=True, encoding="utf-8",
                        env=child_env(), timeout=timeout)
    return cp.returncode, cp.stdout, cp.stderr


def refused(err):
    m = re.search(r"refused \(([a-z_]+)\)", err)
    return m.group(1) if m else None


INIT = ["--agent", "a", "--tz", "UTC", "--certifies", "one line per event.", "--created", "2026-11-01T00:00:00Z",
        "--timestamp", "2026-11-01T00:00:01Z"]


def init_args(**over):
    args = list(INIT)
    for k, v in over.items():
        args[args.index("--" + k) + 1] = v
    return args


@pytest.mark.parametrize("name,args,code", [
    ("certifies empty", init_args(certifies=""), "header_form"),
    ("certifies spaces", init_args(certifies="   "), "header_form"),
    ("agent empty", init_args(agent=""), "header_form"),
    ("tz empty", init_args(tz=""), "anchor_tz"),
    ("kinds with an empty item", INIT + ["--kinds", "note,,send"], "header_form"),
    ("kinds empty", INIT + ["--kinds", ""], "header_form"),
    ("kinds with a trailing comma", INIT + ["--kinds", "note,"], "header_form"),
])
def test_init_empty_text_is_one_refusal_in_both(tmp_path, name, args, code):
    for who in CLIS:
        log = tmp_path / ("%s.jsonl" % who)
        rc, out, err = run(who, "init", log, *args)
        assert (rc, refused(err)) == (1, code), (who, rc, out, err)
        assert not log.exists(), who


def test_append_empty_kind_and_empty_log_and_missing_flag(tmp_path):
    for who in CLIS:
        log = tmp_path / ("%s.jsonl" % who)
        assert run(who, "init", log, *INIT)[0] == 0
        rc, out, err = run(who, "append", log, "--kind", "", "--timestamp", "2026-11-01T00:00:02Z")
        assert (rc, refused(err)) == (1, "kind_not_declared"), (who, err)
        for args in (["init", "", *INIT], ["append", "", "--kind", "note"], ["anchor-text", ""],
                     ["init", tmp_path / "x.jsonl", "--agent", "a", "--tz", "UTC"]):
            rc, out, err = run(who, *args)
            assert rc == 2 and refused(err) is None, (who, args, rc, err)
        assert log.read_bytes().count(b"\n") == 2, who


@pytest.mark.parametrize("cp", [0x1C, 0x1F, 0x85, 0xFEFF], ids=["u+001c", "u+001f", "u+0085", "u+feff"])
def test_each_cli_refuses_the_blank_certifies_the_other_used_to_accept(tmp_path, cp):
    for who in CLIS:
        rc, out, err = run(who, "init", tmp_path / ("%s.jsonl" % who), *init_args(certifies=chr(cp)))
        assert (rc, refused(err)) == (1, "header_form"), (who, err)


def test_either_cli_appends_to_the_log_the_other_wrote(tmp_path):
    cert = "one line per event," + chr(0xA0) + "padded" + chr(0x3000)
    for maker, other in (("python", "js"), ("js", "python")):
        log = tmp_path / ("by-%s.jsonl" % maker)
        assert run(maker, "init", log, *init_args(certifies=cert))[0] == 0
        rc, out, err = run(other, "append", log, "--kind", "note", "--field", "n=1", "--timestamp", "2026-11-01T00:00:02Z")
        assert rc == 0, (maker, other, err)
        rc, out, err = run(maker, "append", log, "--kind", "note", "--field", "n=2", "--timestamp", "2026-11-01T00:00:03Z")
        assert rc == 0, (maker, other, err)
        assert run(other, "verify", log)[0] == 0 and log.read_bytes().count(b"\n") == 4


def test_anchor_text_refuses_an_open_and_an_anchored_day_in_both(tmp_path):
    for who in CLIS:
        log = tmp_path / ("%s.jsonl" % who)
        assert run(who, "init", log, *INIT)[0] == 0
        rc, out, err = run(who, "anchor-text", log, "--date", "2026-11-01", "--timestamp", "2026-11-01T12:00:00Z")
        assert (rc, refused(err), out) == (1, "day_open", ""), (who, err)
        assert "2026-11-01 has not closed in UTC (it is 2026-11-01 there)" in err, who
        rc, out, err = run(who, "anchor-text", log, "--date", "2026-11-01", "--timestamp", "2026-11-02T00:00:00Z",
                           "--record")
        assert rc == 0, (who, err)
        rc, out, err = run(who, "anchor-text", log, "--date", "2026-11-01", "--timestamp", "2026-11-02T00:01:00Z")
        assert (rc, refused(err)) == (1, "already_anchored"), (who, err)


# ------------------------------------------------------------------------------- exhibit error paths

def _dead_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def _norm(out):
    out = re.sub(r"\((python|javascript) [^)]*\)", "(implementation)", out)
    return re.sub(r"wall clock [0-9.]+ s", "wall clock", out).splitlines()


def test_exhibit_error_paths_read_the_same_in_both(tmp_path):
    from exhibit_server import ExhibitServer, assemble
    root = assemble(tmp_path)
    with ExhibitServer(root) as s:
        dead = "http://127.0.0.1:%d/api" % _dead_port()
        cases = {"a mistyped url": [s.base + "/ledgr/", "--explorer", s.explorers[0], "--explorer", s.explorers[1]],
                 "an explorer that does not answer": [s.url, "--explorer", s.explorers[0], "--explorer", dead,
                                                      "--today", "2026-11-09"]}
        for name, args in cases.items():
            got = {who: run(who, "exhibit", *args, timeout=300) for who in CLIS}
            assert got["python"][0] == got["js"][0] == 2, (name, got)
            assert _norm(got["python"][1]) == _norm(got["js"][1]), name
    py = got["python"][1]
    assert "explorer %s did not answer: the connection was refused" % dead in py
    assert py.count("did not answer") == 1
