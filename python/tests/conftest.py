import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
TESTS = Path(__file__).resolve().parent
PYROOT = TESTS.parent
SRC = PYROOT / "src"
REPO = PYROOT.parent
VECTORS = REPO / "vectors"
JS = REPO / "js"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))


def child_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@pytest.fixture
def cli():
    """run `python -B -m styxx_ledger <args>`; returns CompletedProcess (text, utf-8)."""
    def run(*args, stdin=None):
        return subprocess.run([sys.executable, "-B", "-m", "styxx_ledger", *map(str, args)], input=stdin,
                              capture_output=True, text=True, encoding="utf-8", env=child_env(), timeout=60)
    return run
