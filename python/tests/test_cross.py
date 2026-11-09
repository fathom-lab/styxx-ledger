"""cross tests: a ledger written by javascript verifies under python, and one written by python verifies under
javascript, byte for byte, same head.

    js -> python   every js/tests/fixtures/*.jsonl (the js suite writes them) re-derives here; when a sibling .json
                   names a head or a sha256, they must match. skipped, with the reason, while no js fixture exists.
    python -> js   tests/fixtures/py_written.jsonl (and a fresh log written now) under js/lib/verify.js's verifyBytes,
                   run with node: same ok, same head. skipped while node or the js module is absent.
"""
import hashlib
import json
import shutil
import subprocess
import sys

import pytest

import styxx_ledger as S
from styxx_ledger import Ledger
from conftest import JS, TESTS, child_env

FIX = TESTS / "fixtures"
JS_FIX = JS / "tests" / "fixtures"
JS_VERIFY = JS / "lib" / "verify.js"
JS_FILES = sorted(JS_FIX.glob("*.jsonl")) if JS_FIX.is_dir() else []


def test_python_fixture_is_what_the_writer_writes_now():
    import make_fixture
    cp = subprocess.run([sys.executable, "-B", str(TESTS / "make_fixture.py"), "--check"], capture_output=True,
                        text=True, env=child_env(), timeout=60)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    meta = json.loads((FIX / "py_written.json").read_text("utf-8"))
    raw = (FIX / "py_written.jsonl").read_bytes()
    r = S.verify_bytes(raw)
    assert r["ok"] and r["head"] == meta["head"] and hashlib.sha256(raw).hexdigest() == meta["sha256"]
    for t in meta["anchor_texts"]:
        assert S.check_anchor(r["entries"], S.parse_anchor_text(t), [], r["header"])["ok"]
    assert make_fixture.STEPS  # the module imports without writing


@pytest.mark.skipif(not JS_FILES, reason="no javascript-written ledger yet: js/tests/fixtures/*.jsonl is absent")
@pytest.mark.parametrize("path", JS_FILES, ids=[p.name for p in JS_FILES])
def test_js_written_ledger_verifies_under_python(path):
    raw = path.read_bytes()
    r = S.verify_bytes(raw)
    assert r["ok"], r["problems"][:5]
    assert r["header"]["schema"] == "styxx.ledger/log/v1"
    side = path.with_suffix(".json")
    if side.exists():
        meta = json.loads(side.read_text("utf-8"))
        if "head" in meta:
            assert r["head"] == meta["head"]
        if "sha256" in meta:
            assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
        for t in meta.get("anchor_texts", []):
            assert S.check_anchor(r["entries"], S.parse_anchor_text(t), [], r["header"])["ok"], t


NODE_VERIFY = r"""
const fs = require('fs');
const V = require(process.argv[2]);
(async () => {
  const out = [];
  for (const p of process.argv.slice(3)) {
    const r = await V.verifyBytes(new Uint8Array(fs.readFileSync(p)), {withheld: []});
    out.push({path: p, ok: r.ok, head: r.head, n: r.entries.length});
  }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(3); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
@pytest.mark.skipif(not JS_VERIFY.exists(), reason="js/lib/verify.js is absent (the javascript package is not built yet)")
def test_python_written_ledger_verifies_under_js(tmp_path):
    fresh = tmp_path / "fresh.jsonl"
    led = Ledger.create(fresh, agent="crossbot", anchor_tz="America/New_York", certifies="cross test",
                        kinds=["note", "lock_recovered"])
    led.start()
    led.append("note", {"note": "now, with the clock — ü \U0001F642", "n": -(2 ** 53), "deep": {"a": [[], {}]}})
    paths = [FIX / "py_written.jsonl", fresh]
    script = tmp_path / "v.cjs"
    script.write_text(NODE_VERIFY, encoding="utf-8")
    cp = subprocess.run(["node", str(script), str(JS_VERIFY), *map(str, paths)], capture_output=True, text=True,
                        timeout=60)
    assert cp.returncode == 0, cp.stderr
    got = json.loads(cp.stdout)
    for g, p in zip(got, paths):
        r = S.verify_bytes(p.read_bytes())
        assert r["ok"] and g["ok"] is True, g
        assert g["head"] == r["head"] and g["n"] == len(r["entries"])
