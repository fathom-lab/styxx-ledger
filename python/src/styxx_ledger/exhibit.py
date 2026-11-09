"""exhibit.py: re-derive a published ledger exhibit from its url (`styxx-ledger exhibit <url>`).

What it fetches, from the exhibit's base url: ledger.jsonl, withheld.json, anchors/index.json and every anchor text
and proof it names, witness/index.json and a sample of the witness proofs. What it asks the block explorers (each
one, default blockstream.info and mempool.space): GET <explorer>/block-height/<h> -> the block hash, then
GET <explorer>/block/<hash> -> {merkle_root, timestamp}. Every explorer must give the same hash, merkle root and
time for a height, or that height is "explorers disagree: not verified".

What it checks:
  chain       the ledger re-derives (v1 or v0 by the header's schema), withheld lines bridged on their digests
  anchors     each anchor text (the .txt the index names) equals the index's text and sha256, and holds against the
              chain (section 5: the line at seq carries that head, no line of that day after it, the ledger's own
              anchor entry agrees); its .ots commits to the .txt bytes, verifies natively against the headers, and
              its lowest verified block is the block the index names
  witness     every record in witness/index.json names the chain's entry_id at its seq; a seeded sample of the
              attested records (seed = the ledger file's sha256) plus the earliest and latest attested lines: each
              proof commits to its entry_id and verifies to the block (and block time) the index states

Transport and age: a file served from another host than the base url (a redirect off it, or from https to http)
is a failed check unless allow_redirect; an explorer's HTTP 429 is retried on its Retry-After (at most 60 s) or on
2, 4, 8, 16 s, then that explorer is left out for the run and the report says it rate-limited; an explorer's 404 on
block-height/<h> is its answer "no such block". The report gives the last holding anchor's age against the run day,
each anchor's lag from its date to its lowest block (flagged above LATE_DAYS), and an anchor the index marks pending
fails once its date is more than PENDING_MAX_DAYS before the run.

Nothing here writes outside --save, and nothing is signed. The report says what a proof attests (existence before
a block) and what it does not (publication at a url). The fetch is injectable (run_exhibit(..., get=fn)).
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import ssl
except ImportError:  # a python built without ssl fetches no https url at all; its errors read "no answer (...)"
    ssl = None  # type: ignore[assignment]

from . import ots as _ots
from ._version import __version__
from .v0 import check_anchor_auto, parse_anchor_auto, verify_auto
from .verify import coverage

DEFAULT_EXPLORERS = ("https://blockstream.info/api", "https://mempool.space/api")
TIMEOUT_S = 30.0
CAP_BYTES = 20 * 1024 * 1024
DEFAULT_SAMPLE = 20
RETRY_STATUS = (429, 500, 502, 503, 504)
TRIES = 3                     # 5xx and no answer: 3 tries, 1.5 s then 3 s apart
RATE_TRIES = 5                # HTTP 429: 5 tries, on Retry-After (capped) or 2, 4, 8, 16 s
RETRY_AFTER_CAP_S = 60.0
LATE_DAYS = 7                 # an anchor whose lowest block is more than this many days after its date is flagged
PENDING_MAX_DAYS = 7          # an anchor still pending this many days after its date fails (the calendars attest within hours)

ANCHOR_TXT_RX = re.compile(r"^anchors/[0-9]{4}-[0-9]{2}-[0-9]{2}\.txt$")
HEX64_RX = re.compile(r"^[0-9a-f]{64}$")

CAVEATS = [
    "reproducible by anyone: the same url gives the same bytes and these answers; the block headers are the "
    "explorers' word, compared with each other, not read from a bitcoin node.",
    "a proof attests that bytes existed before a bitcoin block, not that they were published at a url or posted "
    "anywhere at a time.",
    "the anchor texts come from the lab's page; the supergroup they were posted to needs an account to read.",
    "nothing is signed: the ledger, the indexes and the texts are the lab's statements; the proofs and the block "
    "headers are the outside clock.",
    "a copy that is older but consistent passes every check here: compare the head and the last anchor date with the "
    "posts, and with a run of your own on another day.",
]


# what a fetch that got no http answer says, in the same words in both packages (exhibit.js maps node's error codes to
# them): until 2026-11-09 a dns failure read "URLError: [Errno 11001] getaddrinfo failed" here and "TypeError: ENOTFOUND"
# there (improvements rank 45)
NET_DNS = "the host name did not resolve (dns)"
NET_REFUSED = "the connection was refused"
NET_RESET = "the connection was reset"
NET_TLS = "the tls handshake failed (a certificate or protocol error)"
NET_TIMEOUT = "no answer within %g s"
EXHIBIT_URL_EXAMPLE = "https://fathom-lab.github.io/styxx/ledger/"
# a proof whose every block an explorer left unanswered: one reason, so the report says it once (rank 44)
EXPLORERS_SILENT = "the explorers did not all answer for the proof's blocks"


def network_reason(e: BaseException, timeout: float = TIMEOUT_S) -> str:
    """the shared words for a fetch that got no http answer: dns, refused, reset, tls, timeout; anything else reads
    "no answer (<type>: <detail>)"."""
    r = getattr(e, "reason", None)
    r = r if isinstance(r, BaseException) else e
    if isinstance(r, socket.gaierror):
        return NET_DNS
    if isinstance(r, ConnectionRefusedError):
        return NET_REFUSED
    if isinstance(r, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return NET_RESET
    if isinstance(r, (socket.timeout, TimeoutError)):
        return NET_TIMEOUT % timeout
    if ssl is not None and isinstance(r, ssl.SSLError):
        return NET_TLS
    text = str(getattr(e, "reason", e))
    if "timed out" in text:
        return NET_TIMEOUT % timeout
    return "no answer (%s: %s)" % (type(r).__name__, text)


class FetchError(Exception):
    """kind: http (a status the server gave), network (no answer, timeout), too_large (over the cap)."""

    def __init__(self, url: str, kind: str, message: str, status: Optional[int] = None,
                 retry_after: Optional[float] = None):
        super().__init__(message)
        self.url, self.kind, self.status, self.retry_after = url, kind, status, retry_after
        self.tries = 1


def _retry_after(v: Optional[str]) -> Optional[float]:
    """Retry-After in seconds (the delta form; an http-date is not read)."""
    if isinstance(v, str) and v.strip().isdigit():
        return float(int(v.strip()))
    return None


def http_get(url: str, timeout: float = TIMEOUT_S, cap: int = CAP_BYTES) -> Tuple[int, bytes, str]:
    """GET url -> (status, body, final url after redirects). One overall deadline of `timeout` seconds; a body over
    `cap` bytes is refused."""
    req = urllib.request.Request(url, headers={"User-Agent": "styxx-ledger/%s (python)" % __version__,
                                               "Accept": "*/*"})
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.strip().isdigit() and int(cl) > cap:
                raise FetchError(url, "too_large", "%s bytes is over the %d byte cap" % (cl.strip(), cap))
            chunks, n = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise FetchError(url, "network", "no complete answer within %g s" % timeout)
                b = resp.read(65536)
                if not b:
                    break
                n += len(b)
                if n > cap:
                    raise FetchError(url, "too_large", "over the %d byte cap" % cap)
                chunks.append(b)
            return resp.status, b"".join(chunks), resp.geturl() or url
    except FetchError:
        raise
    except urllib.error.HTTPError as e:
        ra = _retry_after(e.headers.get("Retry-After") if e.headers is not None else None)
        raise FetchError(url, "http", "HTTP %d" % e.code, e.code, ra) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError,
            http.client.HTTPException) as e:
        raise FetchError(url, "network", network_reason(e, timeout)) from None


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _utc(t: Optional[int]) -> Optional[str]:
    if not isinstance(t, int) or isinstance(t, bool):
        return None
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """whole days from date a to date b (YYYY-MM-DD each); None when either is unreadable."""
    try:
        return (datetime.strptime(b[:10], "%Y-%m-%d") - datetime.strptime(a[:10], "%Y-%m-%d")).days  # type: ignore
    except (TypeError, ValueError):
        return None


def _off_host(base: str, final: Optional[str]) -> bool:
    """a file served from another host than the base url, or moved from https to http."""
    if not final:
        return False
    b, f = urllib.parse.urlsplit(base), urllib.parse.urlsplit(final)
    return f.netloc.lower() != b.netloc.lower() or (b.scheme == "https" and f.scheme != "https")


class _Fetcher:
    """Every GET goes through here: retried on 429 / 5xx / no answer (3 tries), recorded, optionally saved."""

    def __init__(self, get: Callable[[str], tuple], save_dir: Optional[Path], sleep=time.sleep):
        self.get, self.save_dir, self.sleep = get, save_dir, sleep
        self.files: List[Dict[str, Any]] = []
        self.explorer_calls = 0
        self.waited_s = 0.0

    def _get(self, url: str) -> Tuple[int, bytes, int, str]:
        """(status, body, ms, final url). 5xx / no answer: TRIES tries; 429: RATE_TRIES tries on Retry-After."""
        attempt = 0
        while True:
            t0 = time.monotonic()
            try:
                got = self.get(url)
                status, body = got[0], got[1]
                final = got[2] if len(got) > 2 and isinstance(got[2], str) and got[2] else url
                return status, body, int((time.monotonic() - t0) * 1000), final
            except FetchError as e:
                attempt += 1
                e.tries = attempt
                if e.kind == "too_large" or (e.kind == "http" and e.status not in RETRY_STATUS):
                    raise
                limited = e.kind == "http" and e.status == 429
                if attempt >= (RATE_TRIES if limited else TRIES):
                    raise
                if limited:
                    wait = (min(e.retry_after, RETRY_AFTER_CAP_S) if e.retry_after is not None
                            else min(2.0 * 2 ** (attempt - 1), 30.0))
                else:
                    wait = 1.5 * attempt
                self.waited_s += wait
                self.sleep(wait)

    def _save(self, rel: str, body: bytes) -> None:
        if self.save_dir is None:
            return
        p = self.save_dir.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)

    def file(self, base: str, rel: str) -> Tuple[Optional[bytes], Dict[str, Any]]:
        url = urllib.parse.urljoin(base, rel)
        rec: Dict[str, Any] = {"path": rel, "url": url, "final_url": None, "status": None, "bytes": None,
                               "sha256": None, "ms": None, "error": None, "error_kind": None}
        try:
            status, body, ms, final = self._get(url)
        except FetchError as e:
            rec.update(status=e.status, error=str(e), error_kind=e.kind)
            self.files.append(rec)
            return None, rec
        rec.update(status=status, final_url=final, bytes=len(body), sha256=_sha(body), ms=ms)
        self.files.append(rec)
        self._save(rel, body)
        return body, rec

    def explorer(self, base: str, path: str) -> bytes:
        self.explorer_calls += 1
        url = base.rstrip("/") + path
        _, body, _, _ = self._get(url)
        host = urllib.parse.urlsplit(base).netloc or "explorer"
        self._save("_explorers/" + re.sub(r"[^A-Za-z0-9._-]", "_", host) + path, body)
        return body


class _Explorers:
    """The block header source verify_proof asks: every explorer, compared; cached per height."""

    def __init__(self, bases: List[str], fetcher: _Fetcher):
        self.bases, self.f = bases, fetcher
        self.heights: Dict[int, Dict[str, Any]] = {}
        self.dead: Dict[str, str] = {}       # an explorer that gave no answer at all is not asked again this run
        self.limited: Dict[str, int] = {}    # an explorer still answering 429 after RATE_TRIES is not asked again

    def _ask(self, base: str, height: int) -> Dict[str, Any]:
        ans: Dict[str, Any] = {"explorer": base, "hash": None, "merkle_root": None, "timestamp": None,
                               "error": None, "error_kind": None}
        if base in self.dead:
            ans.update(error="not asked: no answer earlier in this run (%s)" % self.dead[base], error_kind="network")
            return ans
        if base in self.limited:
            ans.update(error="not asked: it rate-limited this run (HTTP 429 after %d tries)" % self.limited[base],
                       error_kind="rate_limited")
            return ans
        try:
            try:
                raw_h = self.f.explorer(base, "/block-height/%d" % height)
            except FetchError as e:
                if e.kind == "http" and e.status == 404:
                    ans.update(error="no such block (HTTP 404 on block-height/%d)" % height, error_kind="absent")
                    return ans
                raise
            h = raw_h.decode("ascii", "replace").strip()
            if not HEX64_RX.match(h):
                raise ValueError("block-height/%d did not answer a block hash" % height)
            doc = json.loads(self.f.explorer(base, "/block/" + h).decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("block/%s is not a json object" % h)
            mr, ts = doc.get("merkle_root"), doc.get("timestamp")
            if not isinstance(mr, str) or not HEX64_RX.match(mr.lower()):
                raise ValueError("block/%s carries no merkle_root" % h)
            if not isinstance(ts, int) or isinstance(ts, bool):
                raise ValueError("block/%s carries no integer timestamp" % h)
            if doc.get("id") not in (None, h) or doc.get("height") not in (None, height):
                raise ValueError("block/%s names another block (id %s, height %s)" % (h, doc.get("id"), doc.get("height")))
            ans.update(hash=h, merkle_root=mr.lower(), timestamp=ts)
        except FetchError as e:
            ans.update(error="%s (%s)" % (e, e.url), error_kind=e.kind)
            if e.kind == "network":
                self.dead[base] = str(e)
            elif e.kind == "http" and e.status == 429:
                self.limited[base] = e.tries
                ans.update(error="HTTP 429 after %d tries (%s)" % (e.tries, e.url), error_kind="rate_limited")
        except (ValueError, UnicodeDecodeError) as e:
            ans.update(error="unreadable answer: %s" % e, error_kind="answer")
        return ans

    def header(self, height: int) -> Dict[str, Any]:
        if height in self.heights:
            return self.heights[height]["result"]
        answers = [self._ask(b, height) for b in self.bases]
        good = [a for a in answers if a["error"] is None]
        absent = [a for a in answers if a["error_kind"] == "absent"]
        silent = [a for a in answers if a["error"] is not None and a["error_kind"] != "absent"]
        if silent:
            miss = ", ".join("%s: %s" % (a["explorer"], a["error"]) for a in silent)
            rec = {"verdict": "unanswered", "result": {"error": "not every explorer answered: " + miss}}
        elif absent and not good:
            rec = {"verdict": "absent", "result": {"error": "block %d does not exist at any explorer asked" % height}}
        elif absent:
            rec = {"verdict": "disagree", "result": {"error": "explorers disagree on whether block %d exists: "
                                                              "not verified" % height}}
        elif len({(a["hash"], a["merkle_root"], a["timestamp"]) for a in good}) > 1:
            rec = {"verdict": "disagree", "result": {"error": "explorers disagree: not verified"}}
        else:
            a = good[0]
            rec = {"verdict": "agree", "result": {"hash": a["hash"], "merkle_root": a["merkle_root"],
                                                  "timestamp": a["timestamp"]}}
        rec["height"], rec["answers"] = height, answers
        self.heights[height] = rec
        return rec["result"]

    def verdict(self, height: int) -> Optional[str]:
        r = self.heights.get(height)
        return r["verdict"] if r else None


# ------------------------------------------------------------------------------------------------ judging

def _judge_proof(rep: Dict[str, Any], ex: Optional[_Explorers], stated_block: Optional[int],
                 stated_time: Optional[int], index_status: Optional[str], want_time: bool = False,
                 pending_days: Optional[int] = None) -> Tuple[str, str]:
    """(verdict, why): pass | fail | pending | unchecked. One bad path fails the proof; any explorer disagreement on
    a height the proof attests means not verified; a height no explorer knows fails; the lowest verified block must be
    the block the index states, and an index that states none (or, want_time, no block time) fails. A proof the index
    marks pending stays pending until PENDING_MAX_DAYS after its date (pending_days), then fails."""
    st = rep["status"]
    if st == "refused":
        return "fail", "the proof is refused (%s): %s" % (rep["code"], rep["reason"])
    if st == "commitment_mismatch":
        return "fail", "commitment mismatch: " + rep["reason"]
    if st == "failed":
        return "fail", rep["reason"]
    if st == "no_attestation":
        return "fail", "the proof carries no attestation"
    heights = sorted({b["height"] for b in rep["bitcoin"]})
    disagree = [h for h in heights if ex is not None and ex.verdict(h) == "disagree"]
    if disagree:
        return "fail", "explorers disagree on block%s %s: not verified" % ("s" if len(disagree) > 1 else "",
                                                                           ", ".join(map(str, disagree)))
    absent = [h for h in heights if ex is not None and ex.verdict(h) == "absent"]
    if absent:
        return "fail", "block%s %s do%s not exist at any explorer asked" % (
            "s" if len(absent) > 1 else "", ", ".join(map(str, absent)), "" if len(absent) > 1 else "es")
    if st == "pending":
        if index_status == "pending":
            if pending_days is not None and pending_days > PENDING_MAX_DAYS:
                return "fail", ("pending for %d days after the anchor date (the rule here: at most %d; the calendars "
                                "attest within hours)" % (pending_days, PENDING_MAX_DAYS))
            return "pending", "calendar receipts only, as the index says; no block yet"
        return "fail", ("the index does not mark it pending (block %s); the proof carries calendar receipts only"
                        % ("none" if stated_block is None else stated_block))
    unanswered = [h for h in heights if ex is not None and ex.verdict(h) == "unanswered"]
    if st == "unverified":
        if heights and len(unanswered) == len(heights):   # one reason for every such proof, so the report collapses them
            return "unchecked", EXPLORERS_SILENT
        return "unchecked", "no block header for any of the proof's blocks (%s)" % ", ".join(map(str, heights))
    lo = rep["lowest"]
    if index_status == "pending":
        return "fail", "the index says pending; the proof verifies to block %d" % lo["height"]
    if stated_block is None:
        return "fail", "the index names no block; the proof's lowest verified block is %d" % lo["height"]
    if want_time and stated_time is None:
        return "fail", "the index names no block time; block %d's header says %s" % (lo["height"], lo["time"])
    if lo["height"] != stated_block:
        if stated_block in unanswered:
            return "unchecked", "the explorers did not all answer for block %d, the block the index states" % stated_block
        return "fail", "the index says block %s; the proof's lowest verified block is %d" % (stated_block, lo["height"])
    if stated_time is not None and lo["time"] != stated_time:
        return "fail", "the index says block time %s; block %d's header says %s" % (stated_time, lo["height"], lo["time"])
    note = "verified, block %d (%s)" % (lo["height"], _utc(lo["time"]))
    if unanswered:
        note += "; not every explorer answered for block%s %s" % ("s" if len(unanswered) > 1 else "",
                                                                  ", ".join(map(str, unanswered)))
    return "pass", note


def _ledger_missing(rec: Dict[str, Any]) -> str:
    """why the ledger did not arrive, with the url fetched and what to check. a typo in the url is not evidence
    against the publisher, so the check is unchecked (exit 2), never failed (improvements 2026-11-09 rank 45)."""
    if rec["error_kind"] == "http" and rec["status"] == 404:
        return ("%s answered HTTP 404: there is no ledger.jsonl at that url; check that the url names the exhibit's "
                "folder, the one that holds ledger.jsonl (e.g. %s)" % (rec["url"], EXHIBIT_URL_EXAMPLE))
    if rec["error_kind"] == "http":
        return "%s answered %s" % (rec["url"], rec["error"])
    if rec["error_kind"] == "network":
        return "%s did not answer: %s; check the url and this machine's network" % (rec["url"], rec["error"])
    return "%s: %s" % (rec["url"], rec["error"])


def _ranges(seqs: List[int]) -> str:
    out: List[str] = []
    for a, b in seqs:
        out.append(str(a) if a == b else "%d-%d" % (a, b))
    return ", ".join(out)


# --------------------------------------------------------------------------------------------------- run

def run_exhibit(base_url: str, explorers: Optional[List[str]] = None, sample: int = DEFAULT_SAMPLE,
                no_ots: bool = False, save_dir: Optional[str] = None,
                get: Optional[Callable[[str], tuple]] = None, sleep=time.sleep, allow_redirect: bool = False,
                today: Optional[str] = None) -> Dict[str, Any]:
    """The whole run; returns the report (render_text prints it). exit_code: 0 every check passed, 1 any failed,
    2 a check could not be made (a file or an explorer did not answer) and none failed. `today` (YYYY-MM-DD, default
    the utc day the run starts) is the run day the ages are counted against."""
    t0 = time.monotonic()
    base = base_url if base_url.endswith("/") else base_url + "/"
    exps = list(explorers) if explorers else list(DEFAULT_EXPLORERS)
    sd = Path(save_dir) if save_dir else None
    if sd is not None:
        sd.mkdir(parents=True, exist_ok=True)
    f = _Fetcher(get or http_get, sd, sleep)
    ex = None if no_ots else _Explorers(exps, f)
    checks: List[Dict[str, Any]] = []

    def check(name: str, verdict: str, detail: str) -> None:
        checks.append({"name": name, "verdict": verdict, "detail": detail})

    rep: Dict[str, Any] = {
        "tool": "styxx-ledger exhibit", "implementation": "python", "version": __version__, "base_url": base,
        "started_at": _now(), "explorers": exps if not no_ots else [], "ots": not no_ots, "sample": sample,
        "ripemd160_available": _ots.ripemd160_available(), "caveats": CAVEATS, "allow_redirect": allow_redirect,
    }
    run_day = today or rep["started_at"][:10]
    rep["run_day"] = run_day

    def finish() -> Dict[str, Any]:
        off = [{"path": x["path"], "url": x["url"], "final_url": x["final_url"]} for x in f.files
               if _off_host(base, x.get("final_url"))]
        rep["off_host"] = off
        if off:
            check("files served from the exhibit's host", "pass" if allow_redirect else "fail",
                  "%d file%s served from another host or moved off https (%s)%s"
                  % (len(off), "" if len(off) == 1 else "s", ", ".join(sorted({x["final_url"] for x in off})[:3]),
                     "; allowed by --allow-redirect" if allow_redirect else ""))
        rep["checks"] = checks
        n = {v: sum(1 for c in checks if c["verdict"] == v) for v in ("pass", "fail", "pending", "unchecked")}
        rep["counts"] = dict(n, total=len(checks))
        rep["ok"] = n["fail"] == 0 and n["unchecked"] == 0
        rep["exit_code"] = 1 if n["fail"] else (2 if n["unchecked"] else 0)
        rep["fetched"] = f.files
        rep["fetched_bytes"] = sum(x["bytes"] or 0 for x in f.files)
        rep["explorer_calls"] = f.explorer_calls
        rep["explorer_answers"] = ([ex.heights[h] for h in sorted(ex.heights)] if ex is not None else [])
        rep["explorers_rate_limited"] = ({b: n for b, n in ex.limited.items()} if ex is not None else {})
        # an explorer that gave no answer at all (dns, refused, timeout, ...): asked once, then left out for the run
        rep["explorers_unanswered"] = ({b: ex.dead[b] for b in exps if b in ex.dead} if ex is not None else {})
        rep["retry_wait_s"] = round(f.waited_s, 1)
        rep["finished_at"] = _now()
        rep["wall_clock_s"] = round(time.monotonic() - t0, 3)
        return rep

    # ---- the ledger and its withheld list
    raw, rec = f.file(base, "ledger.jsonl")
    if raw is None:   # nothing can be verified, so nothing failed: exit 2, never the exit of a failed check
        check("ledger.jsonl fetched", "unchecked", _ledger_missing(rec))
        rep["chain"] = None
        return finish()
    wraw, wrec = f.file(base, "withheld.json")
    withheld: List[dict] = []
    if wraw is None:
        if wrec["status"] == 404:
            rep["withheld_note"] = "no withheld.json at the exhibit (404): read as no withheld lines"
        else:
            check("withheld.json fetched", "unchecked", wrec["error"])
    else:
        try:
            doc = json.loads(wraw.decode("utf-8"))
            doc = doc.get("withheld", []) if isinstance(doc, dict) else doc
            if not isinstance(doc, list):
                raise ValueError("not a list")
            withheld = [w for w in doc if isinstance(w, dict)]
        except (ValueError, UnicodeDecodeError) as e:
            check("withheld.json reads", "fail", "withheld.json is not a list of {seq, entry_id}: %s" % e)
    r = verify_auto(raw, withheld=withheld)
    proto = r["protocol"]
    entries = r["entries"]
    by_seq: Dict[int, str] = {}
    for it in entries:
        e = it["entry"]
        if isinstance(e.get("seq"), int) and isinstance(e.get("entry_id"), str):
            by_seq[e["seq"]] = e["entry_id"]
    # a withheld record counts only when the chain reader bridged it: a later published line's prev names its digest
    bound = set(r["bridged"])
    wmap = {w.get("seq"): w.get("entry_id") for w in withheld if isinstance(w.get("seq"), int)
            and not isinstance(w.get("seq"), bool)}
    wbound = [w for w in withheld if w.get("seq") in bound]
    unbound = []
    for s_ in sorted(x for x in wmap if x not in bound):
        if s_ in by_seq:
            unbound.append({"seq": s_, "why": "withheld.json names seq %d, which is published" % s_})
        else:
            unbound.append({"seq": s_, "why": "withheld.json names seq %d, which no published line binds (no later "
                                              "line's prev names its digest)" % s_})
    for s_ in bound:
        by_seq.setdefault(s_, wmap[s_])
    last_seq = max(by_seq) if by_seq else 0
    nb = len(bound)
    rep["chain"] = {"protocol": proto, "rederives": r["ok"], "lines": len(entries) + nb,
                    "published": len(entries), "withheld": nb, "bridged": r["bridged"], "head": r["head"],
                    "last_seq": last_seq, "problems": len(r["problems"]), "problem_records": r["problems"][:50],
                    "withheld_records": len(wmap), "withheld_unbound": unbound,
                    "file_sha256": r["file_sha256"], "file_bytes": len(raw)}
    detail = "%d lines (%d published + %d withheld), head %s, %d problems" % (len(entries) + nb, len(entries), nb,
                                                                             r["head"], len(r["problems"]))
    if unbound:
        detail += "; " + "; ".join(u["why"] for u in unbound[:5])
    check("chain re-derives, every withheld record bound by a later line", "pass" if r["ok"] and not unbound else "fail",
          detail)

    # ---- anchors
    araw, arec = f.file(base, "anchors/index.json")
    anchors_out: List[Dict[str, Any]] = []
    holding_seqs: List[int] = []
    if araw is None:
        check("anchors/index.json fetched", "fail" if arec["error_kind"] == "http" else "unchecked", arec["error"])
    else:
        try:
            aidx = json.loads(araw.decode("utf-8"))
            alist = aidx.get("anchors") if isinstance(aidx, dict) else None
            if not isinstance(alist, list):
                raise ValueError("no anchors list")
        except (ValueError, UnicodeDecodeError) as e:
            check("anchors/index.json reads", "fail", "anchors/index.json is not {anchors: [...]}: %s" % e)
            alist = []
        for i, ai in enumerate(alist):
            ai = ai if isinstance(ai, dict) else {}
            date = ai.get("date") if isinstance(ai.get("date"), str) else "#%d" % i
            a: Dict[str, Any] = {"date": date, "index": {k: ai.get(k) for k in ("text", "text_sha256", "seq", "head",
                                                                              "block", "status", "ots_sha256", "file", "ots")}}
            anchors_out.append(a)
            rel = ai.get("file")
            if not isinstance(rel, str) or not ANCHOR_TXT_RX.match(rel):
                a["text_check"] = {"verdict": "fail", "why": "the index names no anchors/<date>.txt file (%r)" % (rel,)}
                check("anchor %s text" % date, "fail", a["text_check"]["why"])
                continue
            orel = ai.get("ots") if isinstance(ai.get("ots"), str) else rel + ".ots"
            if orel != rel + ".ots":
                orel = rel + ".ots"
                a["ots_path_note"] = "the index's ots path is not <file>.ots; read %s" % orel
            txt, trec = f.file(base, rel)
            if txt is None:
                v = "fail" if trec["error_kind"] == "http" else "unchecked"
                a["text_check"] = {"verdict": v, "why": "the text file did not arrive: %s" % trec["error"]}
                check("anchor %s text" % date, v, a["text_check"]["why"])
                continue
            text = txt.decode("utf-8", "replace")
            a["text"], a["text_sha256"] = text, _sha(txt)
            why = []
            if isinstance(ai.get("text"), str) and ai["text"] != text:
                why.append("the .txt is not the index's text")
            if isinstance(ai.get("text_sha256"), str) and ai["text_sha256"] != a["text_sha256"]:
                why.append("the .txt's sha256 is not the index's")
            a["text_check"] = {"verdict": "fail" if why else "pass",
                               "why": "; ".join(why) if why else "the .txt is the index's text and sha256"}
            check("anchor %s text matches the index" % date, a["text_check"]["verdict"], a["text_check"]["why"])
            parsed = parse_anchor_auto(text, proto)
            if parsed is None:
                form = "gate anchor <date> head <64 hex> seq <n>" if proto == "v0" else "<agent> anchor <date> head <64 hex> seq <n>"
                a["chain_check"] = {"verdict": "fail", "why": "not in the anchor form '%s'" % form}
            else:
                c = check_anchor_auto(r, parsed, wbound)
                cw = []
                if not c["agent_matches"]:
                    cw.append("the agent is not the header's")
                if not c["in_chain"]:
                    if c["seq"] in wmap and c["seq"] not in bound and c["seq"] not in by_seq:
                        cw.append("not in chain: seq %d is a withheld digest no published line binds" % c["seq"])
                    elif c["seq"] > last_seq:
                        cw.append("not in chain: seq %d is after the last line (seq %d)" % (c["seq"], last_seq))
                    else:
                        cw.append("not in chain: the line at seq %d carries another digest" % c["seq"])
                if c["day_lines_after"]:
                    cw.append("%d line%s of %s after seq %d" % (c["day_lines_after"], "" if c["day_lines_after"] == 1 else "s",
                                                               c["date"], c["seq"]))
                own = c["ledger_anchor_line"]
                if own is not None and not own["agrees"]:
                    cw.append("the ledger's own anchor entry (seq %s) disagrees" % own["seq"])
                a["seq"], a["head"] = c["seq"], c["head"]
                held = "holds"
                if c["ok"] and c.get("via_withheld"):
                    later = [x for x in by_seq if x > c["seq"] and x not in bound]
                    held = "holds on a withheld digest that seq %s binds" % (min(later) if later else "?")
                a["chain_check"] = dict(c, verdict="pass" if c["ok"] else "fail",
                                        why=held if c["ok"] else "; ".join(cw))
                if c["ok"]:
                    holding_seqs.append(c["seq"])
            check("anchor %s holds against the chain" % date, a["chain_check"]["verdict"], a["chain_check"]["why"])
            if no_ots:
                continue
            prf, prec = f.file(base, orel)
            if prf is None:
                v = "fail" if prec["error_kind"] == "http" else "unchecked"
                a["proof"] = {"verdict": v, "why": "the proof did not arrive: %s" % prec["error"]}
                check("anchor %s proof" % date, v, a["proof"]["why"])
                continue
            pr = _ots.verify_proof(prf, target=txt, get_header=ex.header)
            stated = ai.get("block") if isinstance(ai.get("block"), int) and not isinstance(ai.get("block"), bool) else None
            verdict, why = _judge_proof(pr, ex, stated, None, ai.get("status"),
                                        pending_days=_days(ai.get("date") if isinstance(ai.get("date"), str) else None,
                                                           run_day))
            if verdict == "pass" and isinstance(ai.get("ots_sha256"), str) and ai["ots_sha256"] != _sha(prf):
                verdict, why = "fail", "the .ots's sha256 is not the index's (" + why + ")"
            a["proof"] = {"verdict": verdict, "why": why, "status": pr["status"], "stated_block": stated,
                          "lowest": pr["lowest"], "ots_sha256": _sha(prf), "report": pr}
            if verdict == "pass" and pr["lowest"]:
                lag = _days(date, _utc(pr["lowest"]["time"]))
                a["proof"]["lag_days"] = lag
                a["proof"]["late"] = lag is not None and lag > LATE_DAYS
            check("anchor %s proof verifies" % date, verdict, why)
    rep["anchors"] = anchors_out
    rep["coverage"] = coverage(entries, wbound, holding_seqs)
    holding = [a for a in anchors_out if (a.get("chain_check") or {}).get("verdict") == "pass"]
    if holding:
        last = max(holding, key=lambda a: a["seq"])
        rep["last_holding_anchor"] = {"date": last["date"], "seq": last["seq"], "days_before_run": _days(last["date"], run_day),
                                      "lines_after": rep["coverage"]["after_last_anchor"]}
    else:
        rep["last_holding_anchor"] = None
    ledger_anchor_dates = sorted({it["entry"].get("anchor_date") for it in entries
                                  if it["entry"].get("kind") == "anchor" and isinstance(it["entry"].get("anchor_date"), str)})
    rep["ledger_anchor_entries"] = {"dates": ledger_anchor_dates,
                                    "not_in_index": [d for d in ledger_anchor_dates if d not in {a["date"] for a in anchors_out}]}

    # ---- witness
    wit: Dict[str, Any] = {"present": False}
    rep["witness"] = wit
    wraw2, wrec2 = f.file(base, "witness/index.json")
    if wraw2 is None:
        if wrec2["status"] == 404:
            wit["note"] = "no witness/index.json at the exhibit (404): no witness check"
        else:
            check("witness/index.json fetched", "unchecked", wrec2["error"])
        return finish()
    try:
        widx = json.loads(wraw2.decode("utf-8"))
        wents = widx.get("entries") if isinstance(widx, dict) else None
        if not isinstance(wents, dict):
            raise ValueError("no entries object")
    except (ValueError, UnicodeDecodeError) as e:
        check("witness/index.json reads", "fail", "witness/index.json is not {entries: {...}}: %s" % e)
        return finish()
    wit["present"] = True
    statuses: Dict[str, int] = {}
    matched, mismatched, outside = [], [], []
    for eid, w in wents.items():
        w = w if isinstance(w, dict) else {}
        st = w.get("status") if isinstance(w.get("status"), str) else "?"
        statuses[st] = statuses.get(st, 0) + 1
        s = w.get("seq")
        if not isinstance(s, int) or s not in by_seq:
            outside.append({"entry_id": eid, "seq": s})
        elif by_seq[s] != eid:
            mismatched.append({"entry_id": eid, "seq": s, "chain_entry_id": by_seq[s]})
        else:
            matched.append((eid, w))
    covered = {w["seq"] for _, w in matched}
    wit.update(records=len(wents), statuses=statuses, at_their_seq=len(matched), name_another_digest=len(mismatched),
               mismatches=mismatched[:50], not_in_chain=len(outside), not_in_chain_records=outside[:50],
               chain_lines=len(by_seq), chain_lines_with_record=len(covered))
    check("witness records name the chain's entry_id at their seq", "fail" if mismatched else "pass",
          "%d of %d records at their seq; %d name another digest; %d name a line not in the chain"
          % (len(matched), len(wents), len(mismatched), len(outside)))
    attested = [(eid, w) for eid, w in matched if w.get("status") == "bitcoin"]
    seed = r["file_sha256"]
    rank = lambda eid: hashlib.sha256(bytes.fromhex(seed) + bytes.fromhex(eid)).hexdigest()  # noqa: E731
    attested_ok = [(eid, w) for eid, w in attested if HEX64_RX.match(eid)]
    picked: Dict[str, Dict[str, Any]] = {}
    if sample > 0 and not no_ots and attested_ok:
        for eid, w in sorted(attested_ok, key=lambda x: rank(x[0]))[:sample]:
            picked[eid] = {"why": "seeded"}
        lo = min(attested_ok, key=lambda x: x[1]["seq"])
        hi = max(attested_ok, key=lambda x: x[1]["seq"])
        for eid, why in ((lo[0], "earliest attested line"), (hi[0], "latest attested line")):
            if eid in picked:
                picked[eid]["why"] += ", " + why
            else:
                picked[eid] = {"why": why}
    wit.update(sample_rule="attested records (status bitcoin, at their seq in the chain) ranked by "
                           "sha256(bytes(seed) + bytes(entry_id)), seed = the ledger file's sha256; the top n, "
                           "plus the earliest and latest attested lines",
               seed=seed, sample_n=sample, attested=len(attested_ok), sampled=[])
    for eid in sorted(picked, key=lambda k: wents[k]["seq"]):
        w = wents[eid]
        item: Dict[str, Any] = {"entry_id": eid, "seq": w["seq"], "picked": picked[eid]["why"],
                                "stated_block": w.get("block"), "stated_time": w.get("block_time")}
        wit["sampled"].append(item)
        prel = w.get("proof")
        if prel != "proofs/%s.ots" % eid:
            item.update(verdict="fail", why="the index names the proof %r, not proofs/<entry_id>.ots" % (prel,))
            check("witness seq %d proof" % w["seq"], "fail", item["why"])
            continue
        prf, prec = f.file(base, "witness/" + prel)
        if prf is None:
            v = "fail" if prec["error_kind"] == "http" else "unchecked"
            item.update(verdict=v, why="the proof did not arrive: %s" % prec["error"])
            check("witness seq %d proof" % w["seq"], v, item["why"])
            continue
        pr = _ots.verify_proof(prf, digest=eid, get_header=ex.header)
        sb = w.get("block") if isinstance(w.get("block"), int) and not isinstance(w.get("block"), bool) else None
        stt = (w.get("block_time") if isinstance(w.get("block_time"), int) and not isinstance(w.get("block_time"), bool)
               else None)
        verdict, why = _judge_proof(pr, ex, sb, stt, "bitcoin", want_time=True)
        item.update(verdict=verdict, why=why, status=pr["status"], lowest=pr["lowest"], ots_sha256=_sha(prf),
                    report=pr)
        check("witness seq %d proof commits and verifies" % w["seq"], verdict, why)
    return finish()


# ------------------------------------------------------------------------------------------------ report

def _short(h: Optional[str]) -> str:
    return (h[:8] + "..." + h[-6:]) if isinstance(h, str) and len(h) > 16 else str(h)


def _lag_summary(pv: List[Dict[str, Any]]) -> str:
    lags = sorted(a["proof"]["lag_days"] for a in pv if isinstance(a["proof"].get("lag_days"), int))
    if not lags:
        return "none"
    return "%d to %d days" % (lags[0], lags[-1]) if lags[0] != lags[-1] else "%d days" % lags[0]


def render_text(rep: Dict[str, Any]) -> str:
    L: List[str] = []
    say = L.append
    say("styxx-ledger exhibit (%s %s): %s" % (rep["implementation"], rep["version"], rep["base_url"]))
    nexp = len(rep["explorer_answers"])
    say("fetched %d files (%d bytes) from the exhibit; %d explorer calls for %d block%s; every sha256 and answer is in --json"
        % (len(rep["fetched"]), rep["fetched_bytes"], rep["explorer_calls"], nexp, "" if nexp == 1 else "s"))
    if not rep.get("ripemd160_available", True):
        say("note: this python's hashlib has no ripemd160; a proof that needs it is refused (ripemd160_unavailable)")
    silent = rep.get("explorers_unanswered") or {}
    for b in rep.get("explorers") or []:   # the reason, once, before the lines it explains (rank 44)
        if b in silent:
            say("explorer %s did not answer: %s; check the network, or pass --explorer <url> to ask another esplora api"
                % (b, silent[b]))
    say("")
    c = rep.get("chain")
    if c is None:
        bad = [x for x in rep["checks"] if x["verdict"] != "pass"]
        say("ledger.jsonl: %s" % (bad[0]["detail"] if bad else "not fetched"))
        say("nothing was verified: every other check needs the ledger")
    else:
        say("chain (protocol %s): %s %d lines = %d published + %d withheld, head %s (seq %d), %d problem record%s"
            % (c["protocol"], "re-derives:" if c["rederives"] else "DOES NOT re-derive:", c["lines"], c["published"],
               c["withheld"], c["head"], c["last_seq"], c["problems"], "" if c["problems"] == 1 else "s"))
        if c["bridged"]:
            say("  withheld lines bridged on their published digests (the publisher's word for what they hold back): "
                "seq %s" % ",".join(map(str, c["bridged"])))
        for u in c.get("withheld_unbound") or []:
            say("  FAIL " + u["why"])
        for p in c["problem_records"][:10]:
            text = p.get("problem") or "; ".join(p.get("problems") or [])
            say("  line %s seq %s %s: %s" % (p.get("line"), p.get("seq"), ",".join(p.get("codes") or [p.get("code") or "?"]), text))
    an = rep.get("anchors") or []
    if an:
        hold = sum(1 for a in an if (a.get("chain_check") or {}).get("verdict") == "pass")
        tm = sum(1 for a in an if (a.get("text_check") or {}).get("verdict") == "pass")
        say("anchors: %d of %d anchor texts hold against the chain (section 5 of protocol %s); %d of %d .txt files are "
            "the index's text" % (hold, len(an), (c or {}).get("protocol", "?"), tm, len(an)))
        if rep["ots"]:
            pv = [a for a in an if (a.get("proof") or {}).get("verdict") == "pass"]
            lows: Dict[int, int] = {}
            for a in pv:
                lows[a["proof"]["lowest"]["height"]] = lows.get(a["proof"]["lowest"]["height"], 0) + 1
            npend = sum(1 for a in an if (a.get("proof") or {}).get("verdict") == "pending")
            nunch = sum(1 for a in an if (a.get("proof") or {}).get("verdict") == "unchecked")
            say("anchor proofs: %d of %d verify natively against bitcoin block headers, each to the block the index "
                "names (lowest blocks: %s)%s%s" % (len(pv), len(an), ", ".join(("%d x%d" % (h, n)) if n > 1 else str(h)
                                                                              for h, n in sorted(lows.items())) or "none",
                                                   ("; %d of %d pending" % (npend, len(an))) if npend else "",
                                                   ("; %d of %d not checked" % (nunch, len(an))) if nunch else ""))
            late = [a for a in pv if a["proof"].get("late")]
            say("  lag from an anchor's date to its lowest block: %s; %d of %d over %d days (the proof pins such a text "
                "from its block, not from its date)" % (_lag_summary(pv), len(late), len(pv), LATE_DAYS))
        for a in an:
            parts = []
            tc, cc, pf = a.get("text_check") or {}, a.get("chain_check") or {}, a.get("proof")
            if tc.get("verdict") != "pass":
                parts.append("text: " + str(tc.get("why")))
            if cc:
                parts.append("chain: " + str(cc.get("why")))
            if pf:
                if pf["verdict"] == "pass":
                    parts.append("proof %s, index says block %s, %s day%s after the anchor date%s"
                                 % (pf["why"], pf.get("stated_block"), pf.get("lag_days"),
                                    "" if pf.get("lag_days") == 1 else "s", " (late)" if pf.get("late") else ""))
                else:
                    parts.append("proof %s: %s" % ("FAILS" if pf["verdict"] == "fail" else pf["verdict"], pf["why"]))
            vs = [x.get("verdict") for x in (tc, cc, pf or {"verdict": "pass"}) if x]
            label = "ok  " if all(v == "pass" for v in vs) else (
                "PEND" if all(v in ("pass", "pending") for v in vs) else (
                    "FAIL" if "fail" in vs else "----"))   # ----: nothing failed, something could not be checked
            say("  %s seq %-4s %s %s" % (a["date"], a.get("seq", "?"), label, "; ".join(parts)))
    elif c is not None:
        say("anchors: none read")
    cov = rep.get("coverage")
    if c is not None and cov is not None:
        say("coverage: %d of %d published entries pinned by holding anchors; %d unpinned by withholding [%s]; %d after "
            "the last holding anchor (seq %d); %d withheld" % (cov["pinned"], c["published"], cov["unpinned_by_withholding"],
                                                               _ranges(cov["unpinned_ranges"]), cov["after_last_anchor"],
                                                               cov["last_anchor_seq"], cov["withheld"]))
    la = rep.get("last_holding_anchor")
    if c is not None and la:
        say("age: the last holding anchor is %s (seq %d), %s day%s before this run (%s); %d line%s after it %s pinned "
            "by nothing here" % (la["date"], la["seq"], la["days_before_run"], "" if la["days_before_run"] == 1 else "s",
                                 rep["run_day"], la["lines_after"], "" if la["lines_after"] == 1 else "s",
                                 "is" if la["lines_after"] == 1 else "are"))
    w = rep.get("witness") or {}
    if w.get("present"):
        st = ", ".join("%d %s" % (n, k) for k, n in sorted(w["statuses"].items(), key=lambda kv: -kv[1]))
        say("witness index: %d records (%s); %d of %d chain lines carry one at their seq; %d name another digest; %d "
            "name a line not in the chain" % (w["records"], st, w["chain_lines_with_record"], w["chain_lines"],
                                               w["name_another_digest"], w["not_in_chain"]))
        if rep["ots"] and w["sample_n"] > 0:
            sm = w["sampled"]
            ok = [x for x in sm if x.get("verdict") == "pass"]
            blocks = sorted({x["lowest"]["height"] for x in ok})
            seeded = sum(1 for x in sm if x["picked"].startswith("seeded"))
            ends = [x["seq"] for x in sm if "attested line" in x["picked"]]
            say("witness proofs: %d sampled of %d attested (%d by the seeded rule, seed = the ledger's sha256 %s, plus the "
                "earliest and latest attested lines, seq %s): %d of %d commit to their entry_id and verify to their "
                "stated block (%s)" % (len(sm), w["attested"], seeded, _short(w["seed"]),
                                       " and ".join(map(str, ends)) or "-", len(ok), len(sm),
                                       ", ".join(map(str, blocks)) or "none"))
            unch: Dict[str, List[int]] = {}   # unchecked proofs that share a reason: said once, with their seqs (rank 44)
            for x in sm:
                if x.get("verdict") == "unchecked":
                    unch.setdefault(x.get("why"), []).append(x["seq"])
            said = set()
            for x in sm:
                v, why = x.get("verdict"), x.get("why")
                if v == "pass":
                    continue
                if v == "unchecked" and len(unch[why]) > 1:
                    if why not in said:
                        said.add(why)
                        say("  %d of %d sampled, seq %s: unchecked: %s" % (len(unch[why]), len(sm),
                                                                           ",".join(map(str, unch[why])), why))
                    continue
                say("  seq %d %s: %s: %s" % (x["seq"], _short(x["entry_id"]), "FAILS" if v == "fail" else v, why))
        elif not rep["ots"]:
            say("witness proofs: not checked (--no-ots)")
        else:
            say("witness proofs: not sampled (--sample 0)")
    elif w.get("note"):
        say("witness: " + w["note"])
    if c is None:
        pass   # no ledger: nothing was asked of an explorer, and the lines below would only count zeros
    elif rep["ots"]:
        ea = rep["explorer_answers"]
        agree = sum(1 for h in ea if h["verdict"] == "agree")
        dis = [str(h["height"]) for h in ea if h["verdict"] == "disagree"]
        un = [str(h["height"]) for h in ea if h["verdict"] == "unanswered"]
        say("explorers: %s: %d of %d blocks asked agree on hash, merkle root and time%s%s"
            % (" and ".join(rep["explorers"]), agree, len(ea),
               ("; disagree on " + ", ".join(dis)) if dis else "", ("; not every explorer answered for " + ", ".join(un)) if un else ""))
        ab = [str(h["height"]) for h in ea if h["verdict"] == "absent"]
        if ab:
            say("  no explorer asked knows block%s %s" % ("s" if len(ab) > 1 else "", ", ".join(ab)))
        for b, n in sorted(rep.get("explorers_rate_limited", {}).items()):
            host = urllib.parse.urlsplit(b).netloc or b
            say("  %s rate-limited this run (HTTP 429 after %d tries) and was not asked again; run again in a minute, "
                "or name another esplora instance with --explorer" % (host, n))
        if len(rep["explorers"]) < 2:
            say("  one explorer only: nothing to compare its headers with")
    else:
        say("proofs and explorers: not checked (--no-ots)")
    say("")
    n = rep["counts"]
    if rep["exit_code"] == 0:
        say("result: every check passed, %d of %d%s (exit 0)" % (n["pass"], n["total"],
                                                                 ("; %d pending, as the index says" % n["pending"]) if n["pending"] else ""))
    else:
        say("result: %d of %d checks passed; %d failed; %d could not be made%s (exit %d)"
            % (n["pass"], n["total"], n["fail"], n["unchecked"],
               ("; %d pending" % n["pending"]) if n["pending"] else "", rep["exit_code"]))
        same: Dict[str, List[str]] = {}   # checks not made for one reason: one line (rank 44); each failure keeps its own
        for x in rep["checks"]:
            if x["verdict"] == "unchecked":
                same.setdefault(x["detail"], []).append(x["name"])
        said = set()
        for x in rep["checks"]:
            if x["verdict"] == "fail":
                say("  FAILED: %s: %s" % (x["name"], x["detail"]))
            elif x["verdict"] == "unchecked" and len(same[x["detail"]]) == 1:
                say("  not made: %s: %s" % (x["name"], x["detail"]))
            elif x["verdict"] == "unchecked" and x["detail"] not in said:
                said.add(x["detail"])
                names = same[x["detail"]]
                say("  not made: %d checks, %s to %s: %s" % (len(names), names[0], names[-1], x["detail"]))
    for x in rep.get("off_host") or []:
        say("  served from another host: %s -> %s" % (x["path"], x["final_url"]))
    say("wall clock %.1f s" % rep["wall_clock_s"])
    say("")
    say("how to read this:")
    for cv in rep["caveats"]:
        say("  - " + cv)
    return "\n".join(L) + "\n"
