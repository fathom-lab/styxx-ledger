"""the CLI: styxx-ledger init | append | verify | anchor-text | head, through `python -m styxx_ledger`."""
import json

import styxx_ledger as S
from conftest import VECTORS


def init(cli, log, *extra):
    return cli("init", log, "--agent", "clibot", "--tz", "America/New_York", "--certifies", "one line per event",
               "--kinds", "note,send", "--created", "2026-10-31T12:00:00Z", "--timestamp", "2026-10-31T12:00:01Z", *extra)


def test_quickstart_flow(cli, tmp_path):
    log = tmp_path / "agent.jsonl"
    cp = init(cli, log)
    assert cp.returncode == 0, cp.stderr
    hdr = json.loads(log.read_bytes().split(b"\n")[0])
    assert hdr["kinds"] == ["anchor", "note", "send", "started"]
    cp = cli("append", log, "--kind", "note", "--fields", '{"note":"hello","n":1}', "--timestamp", "2026-11-01T03:00:00Z")
    assert cp.returncode == 0, cp.stderr
    assert "appended seq 2 kind note day 2026-10-31" in cp.stdout
    cp = cli("append", log, "--kind", "send", "--fields", "-", "--timestamp", "2026-11-01T03:30:00Z", "--json",
             stdin='{"to_sha256":"' + "a" * 64 + '"}')
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout)["seq"] == 3
    cp = cli("anchor-text", log, "--timestamp", "2026-11-01T04:00:05Z")
    assert cp.returncode == 0, cp.stderr
    text = cp.stdout.strip()
    assert S.parse_anchor_text(text)["date"] == "2026-10-31" and S.parse_anchor_text(text)["seq"] == 3
    assert log.read_bytes().count(b"\n") == 4                       # compose wrote nothing
    cp = cli("anchor-text", log, "--date", "2026-10-31", "--record", "--timestamp", "2026-11-01T04:00:05Z")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == text and "recorded anchor entry seq 4" in cp.stderr
    cp = cli("verify", log, "--anchor", text)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "re-derives: 4 entries" in cp.stdout and "anchor 2026-10-31 seq 3: holds" in cp.stdout
    assert "coverage: 3 of 4 entries pinned" in cp.stdout
    cp = cli("head", log)
    assert cp.returncode == 0 and cp.stdout.strip() == S.verify_bytes(log.read_bytes())["head"]


def test_verify_json_and_failure_exit(cli, tmp_path):
    log = tmp_path / "a.jsonl"
    init(cli, log)
    cli("append", log, "--kind", "note", "--fields", '{"n":1}', "--timestamp", "2026-10-31T13:00:00Z")
    raw = log.read_bytes()
    log.write_bytes(raw.replace(b'"n":1', b'"n":2'))
    cp = cli("verify", log, "--json")
    assert cp.returncode == 1
    out = json.loads(cp.stdout)
    assert out["ok"] is False and out["problems"][0]["seq"] == 2
    cp = cli("verify", log)
    assert cp.returncode == 1 and "does not re-derive" in cp.stdout
    cp = cli("append", log, "--kind", "note", "--fields", "{}")
    assert cp.returncode == 1 and "does not re-derive" in cp.stderr
    assert log.read_bytes() == raw.replace(b'"n":1', b'"n":2')
    cp = cli("head", log)
    assert cp.returncode == 1


def test_refusals_exit_1(cli, tmp_path):
    log = tmp_path / "a.jsonl"
    init(cli, log)
    for fields, code in [('{"x":1.5}', "float"), ('{"seq":1}', "reserved_field")]:
        cp = cli("append", log, "--kind", "note", "--fields", fields)
        assert cp.returncode == 1 and "refused (%s)" % code in cp.stderr
    cp = cli("append", log, "--kind", "tool_call", "--fields", "{}")
    assert cp.returncode == 1 and "kind_not_declared" in cp.stderr
    cp = init(cli, log)
    assert cp.returncode == 1 and "already" in cp.stderr


def test_usage_errors_exit_2(cli, tmp_path):
    log = tmp_path / "a.jsonl"
    init(cli, log)
    assert cli("append", log, "--kind", "note", "--fields", "{nope").returncode == 2
    assert cli("append", log, "--kind", "note", "--fields", '{"a":1,"a":2}').returncode == 2
    assert cli("append", log, "--kind", "note", "--fields", "[1]").returncode == 2
    assert cli("verify", tmp_path / "missing.jsonl").returncode == 2
    assert cli("init", tmp_path / "b.jsonl").returncode == 2        # argparse: required flags missing


def test_verify_shared_base_with_withheld_and_anchors(cli, tmp_path):
    doc = json.loads((VECTORS / "vectors_v1.json").read_text("utf-8"))
    base = (VECTORS / "base_v1.jsonl").read_bytes()
    lines = base.split(b"\n")
    e33 = json.loads(lines[33])
    assert e33["seq"] == 33
    cut = tmp_path / "published.jsonl"
    cut.write_bytes(b"\n".join(lines[:33] + lines[34:]))
    wh = tmp_path / "withheld.json"
    wh.write_text(json.dumps([{"seq": 33, "entry_id": e33["entry_id"], "reason": "test"}]), encoding="utf-8")
    anchors = tmp_path / "anchors.txt"
    anchors.write_text("\n".join(doc["base_anchor_texts"]) + "\n", encoding="utf-8")
    cp = cli("verify", cut, "--withheld", wh, "--anchors-file", anchors)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "bridged on withheld digests (the publisher's word): seq 33" in cp.stdout
    assert cp.stdout.count(": holds") == len(doc["base_anchor_texts"])
    assert "unpinned by withholding" in cp.stdout


def test_verify_names_a_v0_log(cli, tmp_path):
    p = tmp_path / "v0.jsonl"
    p.write_bytes(b'{"anchor_tz":"America/New_York","certifies":"x","created":"2026-10-24T00:00:00Z","schema":"darkflobi.gate/log/v0"}\n'
                  b'{"schema":"darkflobi.gate/entry/v0","seq":1}\n')
    cp = cli("verify", p)
    assert cp.returncode == 1 and "reads v1 only" in cp.stdout


def test_bad_anchor_text_fails(cli, tmp_path):
    log = tmp_path / "a.jsonl"
    init(cli, log)
    cp = cli("verify", log, "--anchor", "gate anchor 2026-10-31 head %s seq 1" % ("0" * 64))
    assert cp.returncode == 1 and "does not hold" in cp.stdout
    cp = cli("verify", log, "--anchor", "not an anchor")
    assert cp.returncode == 1 and "not in the form" in cp.stdout


def test_version(cli):
    cp = cli("--version")
    assert cp.returncode == 0 and S.__version__ in cp.stdout
