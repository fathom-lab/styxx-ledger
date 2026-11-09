"""ots.py: an optional opentimestamps helper (protocol v1, section 5). not required, not a dependency.

it shells out to an `ots` client (the opentimestamps-client package's command) when one is on PATH; the client,
not this package, talks to the public calendars. a proof shows the stamped bytes existed before the bitcoin block
it lands in; a proof made on a later day for an earlier post shows only that the post existed by the stamping day.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


class OtsUnavailable(RuntimeError):
    """no `ots` client on PATH, or the client failed."""


def ots_client() -> Optional[str]:
    return shutil.which("ots")


def stamp_file(path, timeout_s: float = 30.0, client: Optional[str] = None) -> Path:
    """run `ots stamp <path>`; returns the .ots proof path. raises OtsUnavailable when there is no client, the
    client fails, or it does not finish within timeout_s."""
    exe = client or ots_client()
    if not exe:
        raise OtsUnavailable("no `ots` client on PATH (pip install opentimestamps-client); nothing stamped")
    p = Path(path)
    try:
        cp = subprocess.run([exe, "stamp", str(p)], capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise OtsUnavailable("ots stamp did not finish in %.0f s" % timeout_s) from None
    except OSError as e:
        raise OtsUnavailable("ots client could not run: %s" % e) from None
    proof = p.with_name(p.name + ".ots")
    if cp.returncode != 0 or not proof.exists():
        raise OtsUnavailable("ots stamp exit %d: %s" % (cp.returncode, (cp.stderr or cp.stdout).strip()[:300]))
    return proof


def stamp_text(text: str, out_path, timeout_s: float = 30.0, client: Optional[str] = None) -> Path:
    """write the exact anchor text (utf-8, no added LF) to out_path and stamp it; returns the .ots path."""
    p = Path(out_path)
    p.write_bytes(text.encode("utf-8"))
    if p.read_bytes() != text.encode("utf-8"):
        raise OSError("write did not land: %s" % p)
    return stamp_file(p, timeout_s=timeout_s, client=client)
