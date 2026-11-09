"""a local copy of the published exhibit, served over http, with fake block explorers answering the real captured
headers (vectors/ots/block_headers.json). used by test_exhibit.py; nothing here touches the network.

layout served (from a temp dir assembled out of the repo's fixtures, byte for byte the exhibit's files):
    /ledger/ledger.jsonl, withheld.json, anchors/index.json, anchors/<date>.txt(.ots), witness/index.json,
    witness/proofs/<entry_id>.ots (the 22 of vectors/ots/witness plus the 2 of vectors/exhibit/witness/proofs)
    /xa/block-height/<h> -> hash, /xa/block/<hash> -> {id, height, merkle_root, timestamp, ...}   explorer a
    /xb/...                                                                                      explorer b
explorer b's answers can be overridden per height (server.overrides[h] = {"merkle_root": ...}; {"_absent": True}
makes b answer 404 for that height). server.limited = {"xa": "0"} makes explorer a answer HTTP 429 to everything
(the value is the Retry-After header, None for none). server.redirects[path] = location answers 302 for that path.
"""
from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from conftest import VECTORS

EXHIBIT = VECTORS / "exhibit"
OTS = VECTORS / "ots"


def assemble(dst: Path) -> Path:
    """build <dst>/ledger/ as the exhibit serves it; returns that folder."""
    root = dst / "ledger"
    (root / "anchors").mkdir(parents=True)
    (root / "witness" / "proofs").mkdir(parents=True)
    for name in ("ledger.jsonl", "withheld.json"):
        shutil.copyfile(EXHIBIT / name, root / name)
    shutil.copyfile(EXHIBIT / "anchors" / "index.json", root / "anchors" / "index.json")
    shutil.copyfile(EXHIBIT / "witness" / "index.json", root / "witness" / "index.json")
    for p in (OTS / "anchors").iterdir():
        shutil.copyfile(p, root / "anchors" / p.name)
    for d in (OTS / "witness", EXHIBIT / "witness" / "proofs"):
        for p in d.glob("*.ots"):
            shutil.copyfile(p, root / "witness" / "proofs" / p.name)
    return root


def load_headers() -> dict:
    doc = json.loads((OTS / "block_headers.json").read_text(encoding="utf-8"))
    return {int(h): b["header"] for h, b in doc["blocks"].items()}


class ExhibitServer:
    def __init__(self, root: Path):
        self.root = root.parent          # serves /ledger/... from root
        self.headers = load_headers()
        self.overrides: dict = {}
        self.limited: dict = {}
        self.redirects: dict = {}
        self.requests: list = []
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):   # quiet
                pass

            def _send(self, code, body: bytes, ctype="application/octet-stream", extra=None):
                self.send_response(code)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                srv.requests.append(self.path)
                bare = self.path.split("?")[0]
                if bare in srv.redirects:
                    return self._send(302, b"", "text/plain", {"Location": srv.redirects[bare]})
                parts = bare.strip("/").split("/")
                if parts and parts[0] in srv.limited:
                    ra = srv.limited[parts[0]]
                    return self._send(429, b"Too Many Requests", "text/plain", {"Retry-After": ra} if ra is not None else None)
                if parts and parts[0] in ("xa", "xb") and len(parts) == 3:
                    hdrs = {h: dict(v) for h, v in srv.headers.items()}
                    if parts[0] == "xb":
                        for h, o in srv.overrides.items():
                            hdrs[h].update(o)
                    if parts[1] == "block-height":
                        h = int(parts[2]) if parts[2].isdigit() else -1
                        if h in hdrs and not hdrs[h].get("_absent"):
                            return self._send(200, hdrs[h]["id"].encode(), "text/plain")
                        return self._send(404, b"Block not found", "text/plain")
                    if parts[1] == "block":
                        for h, v in hdrs.items():
                            if v["id"] == parts[2]:
                                return self._send(200, json.dumps(v).encode(), "application/json")
                        return self._send(404, b"Block not found", "text/plain")
                    return self._send(404, b"not found", "text/plain")
                p = srv.root.joinpath(*parts)
                try:
                    p.resolve().relative_to(srv.root.resolve())
                except ValueError:
                    return self._send(403, b"no")
                if p.is_file():
                    return self._send(200, p.read_bytes())
                return self._send(404, b"not found", "text/plain")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.url = self.base + "/ledger/"
        self.explorers = [self.base + "/xa", self.base + "/xb"]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def _varuint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7f, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def craft_proof(target: bytes, height=None, pending_uri: str = "https://alice.btc.calendar.opentimestamps.org") -> bytes:
    """a one-attestation .ots committing to sha256(target): a bitcoin attestation at `height` straight on the file
    digest (it cannot match a real merkle root; used where no header must match), or a pending one."""
    import hashlib
    from styxx_ledger import ots
    head = ots.MAGIC + _varuint(1) + b"\x08" + hashlib.sha256(target).digest()
    if height is not None:
        pay = _varuint(height)
        return head + b"\x00" + ots.TAG_BITCOIN + _varuint(len(pay)) + pay
    uri = pending_uri.encode()
    pay = _varuint(len(uri)) + uri
    return head + b"\x00" + ots.TAG_PENDING + _varuint(len(pay)) + pay
