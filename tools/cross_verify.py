#!/usr/bin/env python3
"""cross_verify.py: the two command lines against each other's bytes.

    python -B tools/cross_verify.py

1. replay: the 41 calls behind python/tests/fixtures/py_cli_written.jsonl (`init --no-started`, one
   `append --kind K --fields <json> --timestamp T` per entry, `anchor-text --date D --record --timestamp T` per
   anchor entry) go through the python cli and through the javascript cli, each into its own new file; the two
   files must be byte-identical.
2. each cli verifies the file the other wrote (exit 0, same head).
3. every committed ledger fixture is verified by the cli of the language that did not write it (python fixtures
   under node, javascript fixtures under python, the shared base under both); the head must be the one its
   sidecar (or vectors_v1.json) names.

prints one line per check and "k of n cross checks hold"; exit 0 only when k == n. needs python (with tzdata on
windows) and node on PATH; writes only under a temp directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent
RESERVED = {"schema", "seq", "prev", "kind", "timestamp", "day", "entry_id"}
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(REPO / "python" / "src"), PYTHONIOENCODING="utf-8")
CLI = {"python": [sys.executable, "-B", "-m", "styxx_ledger"], "js": ["node", str(REPO / "js" / "bin" / "styxx-ledger.cjs")]}
results = []


def run(which, args):
    return subprocess.run(CLI[which] + args, capture_output=True, text=True, encoding="utf-8", env=ENV, timeout=120)


def check(name, ok, detail=""):
    results.append(ok)
    print("%s %s%s" % ("ok  " if ok else "FAIL", name, (": " + detail) if detail else ""))


def replay(src: Path, out: Path, which: str) -> bool:
    lines = src.read_bytes().decode("utf-8").split("\n")
    hdr = json.loads(lines[0])
    kinds = ",".join(k for k in hdr["kinds"] if k not in ("anchor", "started"))
    calls = [["init", str(out), "--agent", hdr["agent"], "--tz", hdr["anchor_tz"], "--certifies", hdr["certifies"],
              "--kinds", kinds, "--created", hdr["created"], "--no-started"]]
    for ln in lines[1:]:
        if not ln.strip():
            continue
        e = json.loads(ln)
        if e["kind"] == "anchor":
            calls.append(["anchor-text", str(out), "--date", e["anchor_date"], "--record", "--timestamp", e["timestamp"]])
        else:
            f = {k: v for k, v in e.items() if k not in RESERVED}
            calls.append(["append", str(out), "--kind", e["kind"], "--fields", json.dumps(f, ensure_ascii=False),
                          "--timestamp", e["timestamp"]])
    for c in calls:
        cp = run(which, c)
        if cp.returncode != 0:
            print("   %s cli refused %s: %s%s" % (which, c[0], cp.stdout[-300:], cp.stderr[-300:]))
            return False
    return True


def head_by(which, path: Path):
    cp = run(which, ["verify", str(path), "--json"])
    try:
        j = json.loads(cp.stdout)
    except ValueError:
        return cp.returncode, None
    return cp.returncode, j.get("head")


def main() -> int:
    src = REPO / "python" / "tests" / "fixtures" / "py_cli_written.jsonl"
    with tempfile.TemporaryDirectory(prefix="styxx-cross-") as d:
        a, b = Path(d) / "by_python.jsonl", Path(d) / "by_js.jsonl"
        okp, okj = replay(src, a, "python"), replay(src, b, "js")
        check("replay through the python cli", okp)
        check("replay through the javascript cli", okj)
        if okp and okj:
            ra, rb = a.read_bytes(), b.read_bytes()
            check("the two clis wrote the same bytes", ra == rb,
                  "sha256 %s / %s, %d lines" % (hashlib.sha256(ra).hexdigest()[:12], hashlib.sha256(rb).hexdigest()[:12], ra.count(b"\n")))
            ca, ha = head_by("js", a)
            cb, hb = head_by("python", b)
            check("javascript verifies the python-written file", ca == 0 and ha is not None, "head %s" % (ha or "")[:16])
            check("python verifies the javascript-written file", cb == 0 and hb is not None, "head %s" % (hb or "")[:16])
            check("same head both ways", ha == hb and ha is not None)
    doc = json.loads((REPO / "vectors" / "vectors_v1.json").read_text("utf-8"))
    fixtures = [(REPO / "vectors" / "base_v1.jsonl", doc["base_head"], ["python", "js"])]
    for p in sorted((REPO / "python" / "tests" / "fixtures").glob("*.jsonl")):
        fixtures.append((p, json.loads(p.with_suffix(".json").read_text("utf-8"))["head"], ["js"]))
    for p in sorted((REPO / "js" / "tests" / "fixtures").glob("*.jsonl")):
        fixtures.append((p, json.loads(p.with_suffix(".json").read_text("utf-8"))["head"], ["python"]))
    for p, want, whos in fixtures:
        for who in whos:
            rc, h = head_by(who, p)
            check("%s cli verifies %s" % ("javascript" if who == "js" else "python", p.relative_to(REPO).as_posix()),
                  rc == 0 and h == want, "head %s" % (h or "")[:16])
    print("%d of %d cross checks hold" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
