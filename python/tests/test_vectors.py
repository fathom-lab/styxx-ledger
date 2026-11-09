"""the shared vectors, one pytest case per vector (through run_vectors.py's own transforms and answers), and the
runner itself as a subprocess: it must print 'k of n vectors answered as the file says' with k == n."""
import hashlib
import json
import re
import subprocess
import sys

import pytest

import styxx_ledger as S
from conftest import SRC, VECTORS, child_env

sys.path.insert(0, str(VECTORS))
import run_vectors as RV  # noqa: E402

DOC = json.loads((VECTORS / "vectors_v1.json").read_text("utf-8"))
BASE = (VECTORS / DOC["base"]).read_bytes()


def test_base_is_the_one_the_vectors_were_made_over():
    assert hashlib.sha256(BASE).hexdigest() == DOC["base_sha256"], \
        "base_v1.jsonl changed bytes (a checkout that turned lf into crlf does this; keep vectors/.gitattributes)"


@pytest.mark.parametrize("case", DOC["read"], ids=[c["name"] for c in DOC["read"]])
def test_read_vector(case):
    text = RV.apply(S, BASE, case["transform"])
    assert hashlib.sha256(text).hexdigest() == case["input_sha256"]
    got = RV.answer_read(S, text, case)
    for k in case.get("compare") or list(case["expect"]):
        assert got.get(k) == case["expect"].get(k), k


@pytest.mark.parametrize("case", DOC["write"], ids=[c["name"] for c in DOC["write"]])
def test_write_vector(case):
    ok, got = RV.check_write(S, case)
    assert ok, got


def test_runner_answers_every_vector():
    cp = subprocess.run([sys.executable, "-B", str(VECTORS / "run_vectors.py"), "--src", str(SRC)],
                        capture_output=True, text=True, encoding="utf-8", env=child_env(), timeout=120)
    last = cp.stdout.strip().splitlines()[-1]
    m = re.fullmatch(r"(\d+) of (\d+) vectors answered as the file says", last)
    assert m, cp.stdout + cp.stderr
    n = len(DOC["read"]) + len(DOC["write"])
    assert (int(m.group(1)), int(m.group(2))) == (n, n), cp.stdout
    assert cp.returncode == 0
