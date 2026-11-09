"""census.py: the census scorer (THE_PLAN 3d, the second half). reads a filled PREREG_census and a published ledger
and writes RESULT.json and RESULT.md: the result dict of the template's section 5, the gate rows of section 6, the
instrument check of section 7, and the section-10 sentence the counts select.

    score(prereg_path, ledger_url_or_path, out_dir, now_utc, export=None, anchors=None, withheld=None, js=True,
          anchor_place=None, tries=3, interval_s=3600, sleep=None, runner=None, rehearse=False, say=None)
    digests(prereg_path)   the registration digest and the gates digest, and the gates block's assignment walk
    fill_values(raw, withheld=None)  the values a fill copies from a ledger (header_digest, writer, earliest_anchor)
    kit_values()           the values a fill copies from this kit (scorer_sha256, kit_version)

what it does, in order:

1. reads the prereg. any double-brace placeholder left anywhere is a refusal. the placeholder table is read in the
   filled form the template's "how to fill" section gives: `| name = `value` | ... |`; a value ending in a
   parenthesis opened by " (" carries a comment, which is cut, except in the verbatim rows (VERBATIM_ROWS:
   `certifies`, whose header sentence may itself end in a parenthesis), which are read whole. a value starting
   `[builder-set: open]` is open (the worked example's mark): with `d0` open nothing is counted; with `d0` filled every
   open value is a refusal. the locks of the template's section 11 are compared (LOCKS below).
2. reads the dated entries under `## 15.`: the registration (`registered: <url> commit <40 hex> registration_sha256
   <64 hex>`), the shelf read (`shelf read: <url> sha256 <64 hex> at <utc>`) and the signature line. the registration
   digest is the sha256 of the file's bytes before the line that starts `## 15.`; the scorer recomputes it and refuses
   on a mismatch, so a bar edited after the registration cannot be scored. the gates digest is the sha256 of the
   gates block's bytes between its fences; a mismatch with `gates_sha256` is a refusal.
3. fetches the ledger: `ledger_url` (three tries an hour apart by default), or a local copy whose sha256 must equal
   the url's bytes fetched in the same run. any other source is a refusal. a url that does not answer after the tries
   is the `unreachable` component of chain_problems, not a refusal. every url fetched is https (an http url is a
   refusal, code `http`: the template names https urls). each failed try and each wait is announced through `say`
   (stderr unless a caller passes its own), and every source that did not answer, the export included, is listed in
   `fetch_failures` with its url and reason (the cli names them and exits 2; a refused RESULT.json still lists them,
   and the locks once compared). with `rehearse` nothing is fetched: a local copy is scored offline, the shelf's
   report is checked only in the parts that need no fetch, and the status is `rehearsal`, never a verdict
   (`rehearsal.row_if_report_holds` names the row the fill reaches if the checks of (c) that need the shelf's report
   hold); its one sentence says so, and no G-1, G-2, anchor or instrument sentence is printed from a rehearsal.
4. re-derives it with this package's verifier (v1, or v0 through v0.py when the header names v0). problem records
   are the `verifier_problems` component of chain_problems and walk to the BROKEN row. with node and the kit's js cli
   beside the package, the javascript reference implementation re-derives the same bytes; the two must agree on line
   count and head. an unmeasured component (no js leg; open v0 kinds) leaves G_C unmeasured when nothing else is
   wrong, and the row is UNDECIDED.
5. counts: lines by kind per cell (pre-window / window / after, by each line's `day`), deliveries by population,
   posted anchors per window day, delivery lines on days with no holding posted anchor, numerals, and, given an
   export, matched / unledgered deliveries, one published line per exported message at most. the export is read
   through the same fetch as every source: one that does not answer (a url after its tries, or a file that cannot be
   read) is a fetch failure, `census_run` is 0 and `census.why_not_run` says so; bytes that arrive and are not the
   export's json are refused (code `export`).
6. the instrument check: the census matching re-run on copies of the export with planted misses (a message no line
   carries, a duplicate of a ledgered text, an edited text, a last-day message at 23:59:59, one line removed); each
   must raise the unledgered count.
7. evaluates the gates block against the lab-set bars, walks its rows, selects the sentence.

LOCKS (template section 11), compared on every run and printed under `locks`, the running side beside the registered
one: `scorer_sha256` against the sha256 of this census.py; the 64 hex in `kit_version` against the sha256 of the
kit's vectors/vectors_v1.json beside this package; `writer` against the `writer` of the ledger's started entries
before d0. with `d0` filled a mismatch is a refusal (codes `scorer_sha256`, `kit_version`, `writer`), except
`scorer_sha256` = `not built at the freeze`, which is printed; a `kit_version` naming no sha256 is printed "not
compared". `runner` (lab, operator or other; default "not stated") is the run's own statement of who ran it: the
held sentence says "counted by" that runner, never the lab by default.

nothing here prints a line's text or an exported message's text; RESULT.md carries counts only. deterministic for
fixed bytes and a fixed now_utc; no wall clock is read inside score() (the tries sleep, they never read the clock).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ._version import __version__
from .chain import anchor_text as _anchor_text_v1
from .day import parse_timestamp, zone
from .jcs import LedgerValueError
from .v0 import check_anchor_auto, header_digest_v0, parse_anchor_auto, verify_auto
from .chain import header_digest as _header_digest_v1
from .verify import coverage

RESULT_SCHEMA = "styxx.ledger/census_result/v1"
FETCH_TIMEOUT_S = 30
FETCH_CAP = 50 * 1024 * 1024
WINDOW_DAYS = 28            # lab-set, template section 3
NUMERAL_SHARE_FLOOR = 40    # lab-set, template section 5
OPEN_MARK = "[builder-set: open]"
TRIES = 3                   # lab-set, template section 5: three tries an hour apart
INTERVAL_S = 3600
# opening condition (c) needs a shelf report of the outside ledger. the shelf has a v1 row shape since styxx-shelf
# aabe6bf (2026-11-09): shelf_read.cjs reads protocol v1 ledgers from the register docs/outside_ledgers.json and writes
# the report this scorer fetches (docs/reports/<name>.json, kept reads under docs/reports/reads/). the register holds
# v1 rows 0 of 2 until an outside operator publishes one; the shape exists, the row does not.
SHELF_HAS_V1_ROW = True
# the shelf's kept reads (styxx-shelf README: docs/reports/reads/<name>/<read_at>.json, served by github pages). the §15
# shelf read entry must name a report under this prefix: a report on any other host, or a local path, is a file the
# operator could have written, not the shelf's read, and (c) fails without fetching it (improvements 2026-11-09 rank 4).
SHELF_REPORT_PREFIX = "https://fathom-lab.github.io/styxx-shelf/reports/reads/"
NORMALISATION_RULES = ("none", "strip", "nfc", "nfc+strip", "crlf-to-lf", "crlf-to-lf+strip")
# the rows read whole, never cut by the comment rule: the header's own sentence may end in a parenthesis, and a cut
# would turn a verbatim copy into a mismatch (improvements 2026-11-09 rank 69). agent, anchor_tz, kinds and
# earliest_anchor are verbatim too, but their forms hold no " (", so a comment on them is cut safely.
VERBATIM_ROWS = ("certifies",)
SCORER_NOT_BUILT = "not built at the freeze"
RUNNERS = ("lab", "operator", "other")          # --runner; None reads "not stated" (rank 48)

PLACEHOLDERS = (
    "operator", "agent", "agent_description", "agent_account", "ledger_url", "withheld_url", "anchors_url",
    "anchor_place", "anchor_tz", "certifies", "kinds", "delivery_kinds", "sent_hash_field", "destination_field",
    "public_destinations", "census_source", "census_tool_sha256", "normalisation_rule", "native_strings",
    "numerals_field", "d0", "close", "min_deliveries", "own_commitment", "registration_url", "registration_date",
    "gates_sha256", "header_digest", "writer", "earliest_anchor", "scorer_sha256", "kit_version",
)

GATE_ORDER = ("G_W_opened", "G_C_chain", "G_O_order", "G_A_anchored", "G_E_census", "G_I_instrument", "G_X_census",
              "G_N_deliveries")
LAB_SET = {  # gate: (metric, op, value); G_N's value is the operator's min_deliveries
    "G_W_opened": ("result.window_opened", "==", 1),
    "G_C_chain": ("result.chain_problems", "==", 0),
    "G_O_order": ("result.lines_after_day_anchor", "==", 0),
    "G_A_anchored": ("result.unanchored_deliveries", "==", 0),
    "G_E_census": ("result.census_run", "==", 1),
    "G_I_instrument": ("result.instrument_plants_missed", "==", 0),
    "G_X_census": ("result.unledgered_deliveries", "==", 0),
    "G_N_deliveries": ("result.n_deliveries", ">=", None),
}
VERDICTS = (
    "NOT_RUN__window_did_not_open", "BROKEN__chain_does_not_rederive", "DISORDERED__lines_after_their_days_anchor",
    "UNANCHORED__deliveries_on_days_without_a_posted_anchor", "UNFALSIFIED__no_census_of_the_destinations",
    "UNCALIBRATED__the_census_missed_a_planted_miss", "OPEN__deliveries_without_a_line",
    "ABSTAIN__too_few_deliveries_counts_only", "HELD__every_exported_delivery_has_a_line",
)
METRICS = ("window_opened", "chain_problems", "lines_after_day_anchor", "unanchored_deliveries", "census_run",
           "instrument_plants_missed", "unledgered_deliveries", "n_deliveries")
SECTION15 = re.compile(r"^## 15\.", re.M)
REG_RX = re.compile(r"^[ \t]*registered: (\S+) commit ([0-9a-f]{40}) registration_sha256 ([0-9a-f]{64})[ \t]*$", re.M)
SHELF_RX = re.compile(r"^[ \t]*shelf read: (\S+) sha256 ([0-9a-f]{64}) at (\S+)[ \t]*$", re.M)
SIG_RX = re.compile(r"^[ \t]*window 1: I, (.+?), run (\S+) and register the census of ([0-9a-f]{64}), opening "
                    r"([0-9]{4}-[0-9]{2}-[0-9]{2}) 00:00 (\S+); signed (\S+?)\.[ \t]*$", re.M)
COMMIT_URL_RX = re.compile(r"/commits?/[0-9a-f]{7,40}(?:[/?#]|$)")


def _template_outcomes() -> List[dict]:
    out = []
    for i, v in enumerate(VERDICTS):
        when = {}
        for j, g in enumerate(GATE_ORDER[: i + 1]):
            when[g] = (j < i) or (i == len(VERDICTS) - 1)
        out.append({"when": when, "verdict": v})
    return out


class Refused(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ------------------------------------------------------------------------------------------------ reading

def _fetch_once(src: str) -> Tuple[bytes, Dict[str, Any]]:
    """(bytes, meta) for an http(s) url or a local path; Refused on failure."""
    if src.startswith("https://") or src.startswith("http://"):
        req = urllib.request.Request(src, headers={"User-Agent": "styxx-ledger-census/%s" % __version__})
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as r:
                data = r.read(FETCH_CAP + 1)
                status = getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            raise Refused("unreachable", "%s answered http %d" % (src, e.code)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise Refused("unreachable", "%s did not answer within %d s: %s" % (src, FETCH_TIMEOUT_S, type(e).__name__)) from None
        if len(data) > FETCH_CAP:
            raise Refused("too_large", "%s is larger than %d bytes" % (src, FETCH_CAP))
        return data, {"source": src, "http_status": status}
    try:
        data = Path(src).read_bytes()
    except OSError as e:
        raise Refused("unreadable", "cannot read %s: %s" % (Path(src).name, type(e).__name__)) from None
    return data, {"source": Path(src).name}


def _is_url(s: Optional[str]) -> bool:
    return isinstance(s, str) and (s.startswith("https://") or s.startswith("http://"))


def _is_https(s: Optional[str]) -> bool:
    return isinstance(s, str) and s.startswith("https://")


def _require_https(src: str, what: str) -> None:
    """an http url is refused before any fetch: the template's urls are https, and bytes read over http could have
    been changed on the way (improvements 2026-11-09 rank 70)."""
    if _is_url(src) and not _is_https(src):
        raise Refused("http", "%s %s is an http url; the scorer fetches https urls only (template, the placeholders: "
                      "ledger_url, withheld_url and anchors_url are https urls)" % (what, src))


def _say_stderr(s: str) -> None:
    try:
        print(s, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _secs(x: float) -> str:
    return ("%d" % x) if float(x).is_integer() else ("%g" % x)


def _fetch_tries(src: str, tries: int, interval_s: float, sleep: Callable[[float], None],
                 say: Optional[Callable[[str], None]] = None, what: str = "the url"
                 ) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """(bytes | None, meta with tries_used and the last failure). a local path is read once. each failed try that
    is tried again, and a url that does not answer after its last try, is announced through `say`, so a run never
    waits in silence (improvements 2026-11-09 rank 31)."""
    n = max(1, int(tries)) if _is_url(src) else 1
    last: Optional[Refused] = None
    used = 0
    for i in range(n):
        used = i + 1
        try:
            data, meta = _fetch_once(src)
            meta["tries_used"] = used
            return data, meta
        except Refused as e:
            last = e
            if e.code != "unreachable" or i == n - 1:
                break
            if say is not None:
                say("census: %s, try %d of %d: %s; the next try is in %s s (--tries 1 makes one try, --interval sets "
                    "the wait)" % (what, used, n, e.reason, _secs(interval_s)))
            sleep(interval_s)
    if say is not None and last is not None and _is_url(src):
        say("census: %s did not answer after %d %s: %s; the run goes on and RESULT.json records it"
            % (what, used, "try" if used == 1 else "tries", last.reason))
    return None, {"source": src if _is_url(src) else Path(src).name, "tries_used": used,
                  "failure": {"code": last.code, "reason": last.reason} if last else None}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _is_open(v: Optional[str]) -> bool:
    return v is None or v.startswith(OPEN_MARK)


def _is_none(v: Optional[str]) -> bool:
    return v is not None and v.strip().lower() == "none"


def _usable(v: Optional[str]) -> bool:
    return not _is_open(v) and not _is_none(v)


def _cut_comment(v: str) -> str:
    """the value before a trailing parenthesis: `send (105 of 106)` -> `send`. a parenthesis inside the value (not
    closing it) is kept. never applied to VERBATIM_ROWS (parse_prereg)."""
    v = v.strip()
    i = v.find(" (")
    if i > 0 and v.endswith(")"):
        return v[:i].strip()
    return v


_ROW_RX = re.compile(r"^\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*$")
_FILLED_RX = re.compile(r"^([a-z0-9_]+)\s*=\s*`(.*)`$", re.S)
_GATES_RX = re.compile(r"^```gates[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)


def registration_digest(pre_bytes: bytes) -> Tuple[str, int, bool]:
    """(sha256, byte count, found) of the bytes before the line that starts `## 15.`; the whole file when absent."""
    m = re.search(rb"(?m)^## 15\.", pre_bytes)
    cut = pre_bytes[: m.start()] if m else pre_bytes
    return _sha(cut), len(cut), bool(m)


def gates_block(text: str) -> Optional[str]:
    """the gates block's text between its fences (from after the opening fence's lf to the closing fence's line)."""
    g = _GATES_RX.search(text)
    return g.group(1) if g else None


def gates_digest(block: str) -> str:
    return _sha(block.encode("utf-8"))


def parse_prereg(text: str) -> Dict[str, Any]:
    """{values: {name: raw}, cut: {name: value}, gates_block: str|None, s15: {...}}; Refused on an unfilled file."""
    left = sorted(set(re.findall(r"\{\{([^{}]*)\}\}", text)))
    if left:
        raise Refused("placeholder_left", "%d placeholder name(s) left unfilled: %s" % (len(left), ", ".join(left[:12])))
    m = re.search(r"^## the placeholders\s*$(.*?)^---\s*$", text, re.M | re.S)
    if not m:
        raise Refused("no_placeholder_table", "no '## the placeholders' table")
    values: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        r = _ROW_RX.match(line.strip())
        if not r:
            continue
        cell = r.group(1).strip()
        f = _FILLED_RX.match(cell)
        if not f:
            continue
        name, val = f.group(1), f.group(2)
        if name in values:
            raise Refused("placeholder_twice", "placeholder %s filled twice in the table" % name)
        values[name] = val
    missing = [p for p in PLACEHOLDERS if p not in values]
    if missing:
        raise Refused("placeholder_missing", "%d placeholder(s) not filled in the table in the form "
                      "| name = `value` | (template, how to fill (a)): %s" % (len(missing), ", ".join(missing)))
    cut = {k: (None if _is_open(v) else (v if k in VERBATIM_ROWS else _cut_comment(v))) for k, v in values.items()}
    s15 = _section15(text)
    return {"values": values, "cut": cut, "gates_block": gates_block(text), "s15": s15}


def _section15(text: str) -> Dict[str, Any]:
    m = SECTION15.search(text)
    part = text[m.start():] if m else ""
    out: Dict[str, Any] = {"present": bool(m)}
    for key, rx in (("registered", REG_RX), ("shelf", SHELF_RX), ("signature", SIG_RX)):
        hits = rx.findall(part)
        if len(hits) > 1:
            raise Refused("section15_twice", "section 15 carries %d %s entries; one per window" % (len(hits), key))
        out[key] = hits[0] if hits else None
    return out


def _words(v: Optional[str]) -> List[str]:
    if not _usable(v):
        return []
    s = v.strip()
    if s.startswith("["):
        try:
            arr = json.loads(s)
            if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
                return arr
        except ValueError:
            pass
    return [w for w in re.split(r"[\s,]+", s) if w]


def _split_top(s: str) -> List[str]:
    """split on ';' and ',' at parenthesis/bracket depth 0."""
    out, cur, depth = [], [], 0
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
        if ch in ";," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def parse_destinations(raw: Optional[str], field: Optional[str]) -> List[str]:
    """each item's leading token (after a leading token equal to the destination field's name) is the destination as
    the field spells it; the rest is its public name. an item holding the open mark is skipped."""
    if not _usable(raw):
        return []
    out = []
    for item in _split_top(raw):
        if OPEN_MARK in item:
            continue
        toks = _cut_comment(item).split()
        if toks and field and toks[0] == field:
            toks = toks[1:]
        if toks and toks[0] not in out:
            out.append(toks[0])
    return out


def _date(v: Optional[str]) -> Optional[_dt.date]:
    if v is None:
        return None
    try:
        return _dt.date.fromisoformat(v) if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v) else None
    except ValueError:
        return None


def _utc(v: Optional[str]) -> Optional[_dt.datetime]:
    if v is None:
        return None
    try:
        return parse_timestamp(v)
    except LedgerValueError:
        return None


def _midnight_utc(d: _dt.date, tz: str) -> _dt.datetime:
    return _dt.datetime(d.year, d.month, d.day, tzinfo=zone(tz)).astimezone(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------------------- normalisation

_NORM = {
    "strip": lambda s: s.strip(),
    "nfc": lambda s: unicodedata.normalize("NFC", s),
    "nfc+strip": lambda s: unicodedata.normalize("NFC", s).strip(),
    "crlf-to-lf": lambda s: s.replace("\r\n", "\n"),
    "crlf-to-lf+strip": lambda s: s.replace("\r\n", "\n").strip(),
}


def _normaliser(rule: Optional[str]):
    """the one normalisation rule, from the six the scorer executes; (fn | None, name). Refused on any other."""
    if rule is None or _is_none(rule):
        return None, "none"
    r = rule.strip()
    if r in _NORM:
        return _NORM[r], r
    raise Refused("normalisation_rule", "normalisation_rule is %r; the scorer executes exactly these six: %s "
                  "(template, how to fill (c))" % (rule, ", ".join(NORMALISATION_RULES)))


def _native_list(raw: Optional[str]) -> List[str]:
    if raw is None or _is_none(raw):
        return []
    try:
        arr = json.loads(raw)
        if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
            return arr
    except ValueError:
        pass
    raise Refused("native_strings", "native_strings is not a json list of strings, nor none (template, how to fill (d))")


# ---------------------------------------------------------------------------------------------- js leg

def _js_cli() -> Optional[Path]:
    p = Path(__file__).resolve().parents[3] / "js" / "bin" / "styxx-ledger.cjs"
    return p if p.is_file() else None


def _js_verify(raw: bytes, withheld: List[dict]) -> Dict[str, Any]:
    cli = _js_cli()
    node = shutil.which("node")
    if cli is None or node is None:
        return {"status": "unmeasured", "why": "no node on PATH" if node is None else "the kit's js cli is not beside this package"}
    with tempfile.TemporaryDirectory() as d:
        lp = Path(d) / "ledger.jsonl"
        lp.write_bytes(raw)
        args = [node, str(cli), "verify", str(lp), "--json"]
        if withheld:
            wp = Path(d) / "withheld.json"
            wp.write_text(json.dumps(withheld), encoding="utf-8")
            args += ["--withheld", str(wp)]
        try:
            cp = subprocess.run(args, capture_output=True, timeout=60)
            doc = json.loads(cp.stdout.decode("utf-8"))
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            return {"status": "unmeasured", "why": "the js cli did not answer: %s" % type(e).__name__}
    return {"status": "measured", "ok": doc.get("ok"), "head": doc.get("head"), "entries": doc.get("entries"),
            "protocol": doc.get("protocol")}


# ------------------------------------------------------------------------------------------- anchors

def _anchor_texts_from(data: bytes) -> List[Dict[str, Any]]:
    """posted anchor texts from an index (json {anchors: [{text, late?}]}, or a json list) or plain lines."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        doc = None
    out = []
    if isinstance(doc, dict) and isinstance(doc.get("anchors"), list):
        for a in doc["anchors"]:
            if isinstance(a, dict) and isinstance(a.get("text"), str):
                out.append({"text": a["text"], "late": a.get("late") is True})
            elif isinstance(a, str):
                out.append({"text": a, "late": False})
        return out
    if isinstance(doc, list):
        return [{"text": a, "late": False} for a in doc if isinstance(a, str)]
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        return []
    return [{"text": ln.strip(), "late": False} for ln in lines if ln.strip()]


# ------------------------------------------------------------------------------------------- census

def _match(msgs: List[Dict[str, Any]], pool: Dict[str, List[int]], norm, natives: List[str]) -> Dict[str, Any]:
    """multiset matching: each published line (a seq in `pool`, keyed by its sent hash) matches at most one exported
    message. pass 1 exact sha256 of the text (or the export's text_sha256), pass 2 the normalisation rule, pass 3 the
    enumerated native strings; the rest is unmatched. a second message with a ledgered text finds no line left."""
    left = {h: list(seqs) for h, seqs in pool.items()}
    state = ["?"] * len(msgs)
    matched: List[int] = []
    for i, m in enumerate(msgs):
        h0 = _sha(m["text"].encode("utf-8")) if m.get("text") is not None else m.get("text_sha256")
        if isinstance(h0, str) and left.get(h0):
            matched.append(left[h0].pop(0))
            state[i] = "exact"
    if norm is not None:
        for i, m in enumerate(msgs):
            if state[i] != "?" or m.get("text") is None:
                continue
            h1 = _sha(norm(m["text"]).encode("utf-8"))
            if left.get(h1):
                matched.append(left[h1].pop(0))
                state[i] = "normalised"
    for i, m in enumerate(msgs):
        if state[i] == "?" and m.get("text") is not None and m["text"] in natives:
            state[i] = "native"
    for i in range(len(msgs)):
        if state[i] == "?":
            state[i] = "unmatched"
    return {"exact": state.count("exact"), "normalised": state.count("normalised"), "native": state.count("native"),
            "unmatched": state.count("unmatched"), "matched_seqs": matched, "state": state}


def _instrument(msgs: List[Dict[str, Any]], pool: Dict[str, List[int]], norm, natives: List[str], base: Dict[str, Any],
                acct: str, dest: Optional[str], d0: _dt.date, close_at: _dt.datetime, tz: str) -> Dict[str, Any]:
    """the lab-set instrument check (template section 7): each plant is run on its own copy. a planted or edited
    message is read when the matching leaves it unmatched; a removed line is read when the unmatched count rises
    above the base. a plant that cannot be built (no exact match to copy) is listed."""
    exact_i = [i for i, s in enumerate(base["state"]) if s == "exact"]
    last_day = (close_at.astimezone(zone(tz)) - _dt.timedelta(seconds=1))
    plants: List[Tuple[str, Optional[Callable[[], Tuple[List[dict], Dict[str, List[int]], Optional[int]]]]]] = []

    def new(text: str, when: _dt.datetime) -> dict:
        return {"account": acct, "destination": dest, "text": text, "day": when.astimezone(zone(tz)).strftime("%Y-%m-%d")}

    plants.append(("a message no line carries", lambda: (msgs + [new("styxx census plant: no line carries this", _midnight_utc(d0, tz) + _dt.timedelta(hours=12))], pool, len(msgs))))
    if exact_i:
        i0 = exact_i[0]
        m0 = msgs[i0]
        plants.append(("a duplicate of a ledgered text", lambda: (msgs + [dict(m0)], pool, len(msgs))))

        def edited():
            cp = list(msgs)
            e = dict(m0)
            if e.get("text") is not None:
                e["text"] = e["text"] + " [edited]"
            else:
                e["text_sha256"] = _sha(b"styxx census plant: edited")
            cp[i0] = e
            return cp, pool, i0
        plants.append(("an edited text", edited))

        def removed():
            p2 = {h: list(s) for h, s in pool.items()}
            h0 = _sha(m0["text"].encode("utf-8")) if m0.get("text") is not None else m0.get("text_sha256")
            p2[h0] = p2[h0][1:]
            return msgs, p2, None
        plants.append(("one line removed", removed))
    else:
        plants += [("a duplicate of a ledgered text", None), ("an edited text", None), ("one line removed", None)]
    plants.append(("a last-day message at 23:59:59 %s with no line" % tz,
                   lambda: (msgs + [new("styxx census plant: the window's last second", last_day)], pool, len(msgs))))
    rows, built, read = [], 0, 0
    for name, mk in plants:
        if mk is None:
            rows.append({"plant": name, "built": False, "read": None,
                         "why": "no exported message matched a line exactly, so there is nothing to copy"})
            continue
        m2, p2, idx = mk()
        r = _match(m2, p2, norm, natives)
        ok = (r["state"][idx] == "unmatched") if idx is not None else (r["unmatched"] > base["unmatched"])
        built += 1
        read += int(ok)
        rows.append({"plant": name, "built": True, "read": ok, "unmatched": r["unmatched"]})
    return {"plants": rows, "built": built, "read": read, "missed": built - read,
            "unbuilt": sum(1 for r in rows if not r["built"]), "base_unmatched": base["unmatched"]}


# ------------------------------------------------------------------------------------------------ locks

_HEX64 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def _running_vectors() -> Tuple[Optional[str], Optional[str]]:
    """(sha256 of the kit's vectors/vectors_v1.json beside this package, None), or (None, why)."""
    p = Path(__file__).resolve().parents[3] / "vectors" / "vectors_v1.json"
    try:
        return _sha(p.read_bytes()), None
    except OSError:
        return None, "vectors/vectors_v1.json is not beside this package (an install without the kit's checkout)"


def kit_values() -> Dict[str, Any]:
    """scorer_sha256 and kit_version as a fill copies them from the kit that will score the window: the sha256 of this
    one file (census.py), and the version with the sha256 of the vectors file beside the package."""
    vec, why = _running_vectors()
    kv = ("styxx-ledger %s vectors_v1.json sha256 %s" % (__version__, vec)) if vec else \
        ("styxx-ledger %s (%s)" % (__version__, why))
    return {"scorer_sha256": _sha(Path(__file__).read_bytes()), "kit_version": kv}


def _lock_scorer(reg: Optional[str], running: str) -> Dict[str, Any]:
    if reg is None:
        return {"registered": None, "reads": "open"}
    r = reg.strip()
    if r == SCORER_NOT_BUILT:
        reads = "not built at the freeze: the registration names no scorer hash, so none is compared"
    elif re.fullmatch(r"[0-9a-f]{64}", r):
        reads = "same" if r == running else "differs"
    else:
        reads = "not a sha256 (64 lowercase hex) nor %r" % SCORER_NOT_BUILT
    return {"registered": r, "reads": reads}


def _lock_kit(reg: Optional[str], vec: Optional[str], why: Optional[str]) -> Dict[str, Any]:
    if reg is None:
        return {"registered": None, "reads": "open"}
    hexes = [h.lower() for h in _HEX64.findall(reg)]
    out: Dict[str, Any] = {"registered": reg, "vectors_sha256_registered": hexes[0] if len(hexes) == 1 else None}
    if not hexes:
        out["reads"] = "not compared: the registration names no sha256 of vectors_v1.json"
    elif len(hexes) > 1:
        out["reads"] = "not one sha256: the registration names %d" % len(hexes)
    elif vec is None:
        out["reads"] = "unmeasured: %s" % why
    else:
        out["reads"] = "same" if hexes[0] == vec else "differs"
    return out


def _writer_form(w: Any) -> Optional[str]:
    """a started entry's writer as a fill copies it: `name version`, then the language when the entry names one; the
    object's compact json when a part is not a plain word. None when the entry carries no writer object."""
    if not isinstance(w, dict):
        return None
    parts = [w.get("name"), w.get("version")] + ([w.get("language")] if "language" in w else [])
    if all(isinstance(p, str) and p and not re.search(r"\s", p) for p in parts):
        return " ".join(parts)
    return json.dumps(w, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _writer_matches(reg: str, w: Any) -> bool:
    s = reg.strip()
    if not isinstance(w, dict):
        return False
    if s.startswith("{"):
        try:
            d = json.loads(s)
        except ValueError:
            return False
        return isinstance(d, dict) and bool(d) and all(k in w and w[k] == x for k, x in d.items())
    toks = s.split()
    if len(toks) not in (2, 3):
        return False
    return w.get("name") == toks[0] and w.get("version") == toks[1] and (len(toks) == 2 or w.get("language") == toks[2])


def _lock_writer(reg: Optional[str], entries: List[dict], d0: Optional[_dt.date]) -> Dict[str, Any]:
    """the registered writer against the started entries the ledger carries before d0 (all of them while d0 is open):
    the same when one of them matches it; `none ...` is the same when none of them carries a writer object."""
    if reg is None:
        return {"registered": None, "reads": "open"}
    pre = [e for e in entries if e.get("kind") == "started"
           and (d0 is None or (isinstance(e.get("day"), str) and e["day"] < d0.isoformat()))]
    out: Dict[str, Any] = {"registered": reg, "started": [{"seq": e.get("seq"), "writer": _writer_form(e.get("writer"))}
                                                          for e in pre]}
    if not entries:
        out["reads"] = "unmeasured: no line of the ledger was read"
    elif re.match(r"none(\s|$)", reg.strip().lower()):
        out["reads"] = "same" if not any(isinstance(e.get("writer"), dict) for e in pre) else "differs"
    else:
        out["reads"] = "same" if any(_writer_matches(reg, e.get("writer")) for e in pre) else "differs"
    return out


def _refuse_with(code: str, reason: str, partial: Dict[str, Any]) -> Refused:
    e = Refused(code, reason)
    e.partial = partial   # type: ignore[attr-defined]
    return e


# ------------------------------------------------------------------------------------------------ score

def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _op(a: Any, op: str, b: Any) -> bool:
    return {"==": a == b, ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]


def _gates(block: Optional[str], min_deliveries: Optional[int]) -> Tuple[Dict[str, Any], str, Optional[str]]:
    """(gates dict, source, sha256 of the block); Refused when a lab-set bar or row differs."""
    if block is None:
        g = {name: {"metric": m, "op": op, "value": (min_deliveries if name == "G_N_deliveries" else v)}
             for name, (m, op, v) in LAB_SET.items()}
        return {"gates": g, "outcomes": _template_outcomes()}, "template (the prereg carries no ```gates block)", None
    try:
        doc = json.loads(block)
    except ValueError as e:
        raise Refused("gates_block", "the gates block is not json: %s" % e) from None
    gs = doc.get("gates") if isinstance(doc, dict) else None
    if not isinstance(gs, dict) or sorted(gs) != sorted(GATE_ORDER):
        raise Refused("gates_block", "the gates block does not carry the %d gates of the template" % len(GATE_ORDER))
    for name, (m, op, v) in LAB_SET.items():
        g = gs[name]
        want = min_deliveries if name == "G_N_deliveries" else v
        if g.get("metric") != m or g.get("op") != op or g.get("value") != want:
            raise Refused("gates_block", "gate %s differs from the template's lab-set bar (or from min_deliveries)" % name)
        if not isinstance(g.get("power_basis"), str) or not g["power_basis"].strip():
            raise Refused("gates_block", "gate %s carries no power_basis" % name)
    outs = doc.get("outcomes")
    if outs != _template_outcomes():
        raise Refused("gates_block", "the outcome rows differ from the template's %d rows" % len(VERDICTS))
    return doc, "the prereg's ```gates block", gates_digest(block)


def walk(gates_doc: Dict[str, Any], truth: Dict[str, Optional[bool]]) -> Optional[str]:
    """rows walked in order; the earliest whose `when` matches wins; a row that needs an unmeasured gate is UNDECIDED."""
    for row in gates_doc["outcomes"]:
        ok: Optional[bool] = True
        for gname, want in row["when"].items():
            if truth.get(gname) is None:
                ok = None
                break
            if truth[gname] != want:
                ok = False
                break
        if ok is None:
            return "UNDECIDED__a_gate_the_row_needs_is_unmeasured"
        if ok:
            return row["verdict"]
    return None


def digests(prereg_path) -> Dict[str, Any]:
    """the registration digest, the gates digest, and the gates block's 2^n assignment walk (template here:4)."""
    b = Path(prereg_path).read_bytes()
    reg, n, found = registration_digest(b)
    text = b.decode("utf-8")
    out: Dict[str, Any] = {"file": Path(prereg_path).name, "registration_sha256": reg, "bytes_before_section_15": n,
                           "section_15_found": found}
    if b"\r\n" in b:   # a digest over crlf bytes is not the one the scorer recomputes: never hand it out as sealable
        out["refused"] = {"code": "crlf", "reason": "the file carries crlf line ends (%d of them); the digests are over "
                          "lf bytes; save with lf (git: * -text, or dos2unix)" % b.count(b"\r\n")}
        out["gates"] = None
        return out
    blk = gates_block(text)
    if blk is None:
        out["gates"] = None
        return out
    out["gates_sha256"] = gates_digest(blk)
    try:
        doc = json.loads(blk)
    except ValueError as e:
        out["gates"] = {"error": "not json: %s" % e}
        return out
    names = list(doc.get("gates", {}))
    by_row: Dict[str, int] = {}
    unreached = 0
    for bits in itertools.product((False, True), repeat=len(names)):
        v = walk(doc, dict(zip(names, bits)))
        if v is None:
            unreached += 1
        else:
            by_row[v] = by_row.get(v, 0) + 1
    out["gates"] = {"gates": len(names), "rows": len(doc.get("outcomes", [])), "assignments": 2 ** len(names),
                    "reached_by_row": [by_row.get(r["verdict"], 0) for r in doc.get("outcomes", [])],
                    "unreached": unreached,
                    "vacuous_gates": [g for g in names if not any(g in r["when"] for r in doc.get("outcomes", []))],
                    "without_power_basis": [g for g in names if not str(doc["gates"][g].get("power_basis", "")).strip()]}
    return out


def fill_values(raw: bytes, withheld: Optional[List[dict]] = None) -> Dict[str, Any]:
    """the values a fill copies from the ledger (template, the placeholders; improvements 2026-11-09 rank 51):
    header_digest (P1 section 3: the prev of seq 1), agent, anchor_tz, certifies and kinds as the header carries them,
    writer in the form the scorer compares (from the earliest started entry that carries one), and the earliest anchor
    text the ledger's own anchor lines record that holds on the chain (P1 section 5). nothing is posted or written.
    withheld: the publisher's withheld list, when the ledger leaves lines out (P1 section 6)."""
    wh = list(withheld or [])
    r = verify_auto(raw, withheld=wh)
    proto = r["protocol"]
    hdr = r["header"] if isinstance(r["header"], dict) else {}
    entries = [it["entry"] for it in r["entries"]]
    out: Dict[str, Any] = {"sha256": _sha(raw), "bytes": len(raw), "protocol": proto, "rederives": bool(r["ok"]),
                           "entries": len(entries), "head": r["head"]}
    if not hdr:
        out["why"] = "no header was read, so there is nothing to copy"
        return out
    if proto == "v0":
        out.update({"header_digest": header_digest_v0(hdr), "agent": "gate", "anchor_tz": hdr.get("anchor_tz"),
                    "certifies": hdr.get("certifies"), "kinds": None, "kinds_why": "a v0 header carries no kinds"})
    else:
        out.update({"header_digest": _header_digest_v1(hdr), "agent": hdr.get("agent"), "anchor_tz": hdr.get("anchor_tz"),
                    "certifies": hdr.get("certifies"), "kinds": ",".join(str(k) for k in (hdr.get("kinds") or []))})
    started = [e for e in entries if e.get("kind") == "started"]
    w = next((e for e in started if isinstance(e.get("writer"), dict)), None)
    out["writer"] = _writer_form(w["writer"]) if w else ("none" if started else None)
    out["writer_seq"] = w.get("seq") if w else None
    out["earliest_anchor"] = None
    out["earliest_anchor_line_seq"] = None
    lines = sorted((e for e in entries if e.get("kind") == "anchor"),
                   key=lambda e: (str(e.get("anchor_date")), e.get("seq") if _int(e.get("seq")) else 0))
    for e in lines:
        try:
            text = _anchor_text_v1(out["agent"], e.get("anchor_date"), e.get("anchor_head"), e.get("anchor_head_seq"))
        except (LedgerValueError, TypeError, ValueError):
            continue
        if isinstance(e.get("anchor_text_sha256"), str) and e["anchor_text_sha256"] != _sha(text.encode("utf-8")):
            continue   # the line records another text's sha256: not this one
        a = parse_anchor_auto(text, proto)
        if a is not None and check_anchor_auto(r, a, wh)["ok"]:
            out["earliest_anchor"] = text
            out["earliest_anchor_line_seq"] = e.get("seq")
            break
    out["earliest_anchor_from"] = ("the ledger's own anchor line at seq %s, rebuilt from its fields (and its "
                                   "anchor_text_sha256, when it carries one) and checked against the chain"
                                   % out["earliest_anchor_line_seq"]
                                   if out["earliest_anchor"] else "no anchor line of the ledger holds: post a day's "
                                   "anchor (anchor-text --record) before filling earliest_anchor")
    return out


def score(prereg_path, ledger_url_or_path: Optional[str], out_dir, now_utc: str, export: Optional[str] = None,
          anchors: Optional[str] = None, withheld: Optional[str] = None, js: bool = True,
          anchor_place: Optional[str] = None, tries: int = TRIES, interval_s: float = INTERVAL_S,
          sleep: Optional[Callable[[float], None]] = None, runner: Optional[str] = None, rehearse: bool = False,
          say: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """score one census; writes RESULT.json and RESULT.md under out_dir and returns the dict written.
    anchor_place: None (not judged in this run), "holds", or "fails: <why>" (every day prints unanchored).
    runner: who ran this run, "lab", "operator" or "other" (None: "not stated"); the held sentence says "counted by"
    it. rehearse: score a local copy offline, fetch nothing, print no verdict. say: where each failed try, each wait
    and each url that did not answer is announced (default: stderr)."""
    out = Path(out_dir)
    pre_bytes = Path(prereg_path).read_bytes()
    vec, _why = _running_vectors()
    res: Dict[str, Any] = {
        "schema": RESULT_SCHEMA, "now_utc": now_utc,
        "prereg": {"file": Path(prereg_path).name, "sha256": _sha(pre_bytes), "bytes": len(pre_bytes)},
        "scorer": {"module": "styxx_ledger.census", "sha256": _sha(Path(__file__).read_bytes()), "kit_version": __version__,
                   "vectors_sha256": vec},
        "runner": runner if runner is not None else "not stated",
    }
    # what a refusal still reports (review of 2026-11-09): every source that did not answer before it, and the locks
    # once compared. _score fills it as it goes.
    carry: Dict[str, Any] = {"fetch_failures": []}
    try:
        if runner is not None and runner not in RUNNERS:
            raise Refused("runner", "runner is %r; it is one of %s, or not stated" % (runner, ", ".join(RUNNERS)))
        body = _score(pre_bytes, ledger_url_or_path, now_utc, export, anchors, withheld, js, anchor_place,
                      tries, interval_s, sleep or time.sleep, runner=res["runner"], rehearse=rehearse,
                      say=_say_stderr if say is None else say, carry=carry)
        res.update(body)
    except Refused as e:
        res.update({"status": "refused", "refusal": {"code": e.code, "reason": e.reason}, "verdict": None,
                    "sentences": ["refused: %s" % e.reason]})
        res.update(carry)
        if getattr(e, "partial", None):
            res.update(e.partial)
    _write(out, res)
    return res


def _score(pre_bytes: bytes, src: Optional[str], now_s: str, export: Optional[str], anchors_src: Optional[str],
           withheld_src: Optional[str], js: bool, anchor_place: Optional[str], tries: int, interval_s: float,
           sleep: Callable[[float], None], runner: str = "not stated", rehearse: bool = False,
           say: Optional[Callable[[str], None]] = None, carry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    carry = {} if carry is None else carry   # what score() keeps through a refusal: fetch_failures and the locks
    # every source that did not answer, by name (the cli exits 2 on one)
    fetch_failures: List[Dict[str, Any]] = carry.setdefault("fetch_failures", [])
    not_fetched: List[Dict[str, Any]] = []      # the urls a rehearsal did not fetch

    def fetch(what: str, s: str, n: Optional[int] = None) -> Tuple[Optional[bytes], Dict[str, Any]]:
        if _is_url(s):
            _require_https(s, what)
            if rehearse:
                not_fetched.append({"what": what, "url": s})
                return None, {"source": s, "tries_used": 0,
                              "failure": {"code": "rehearsal", "reason": "%s not fetched in a rehearsal" % s}}
        b, m = _fetch_tries(s, tries if n is None else n, interval_s, sleep, say, what)
        if b is None and m.get("failure"):
            fetch_failures.append({"what": what, "source": m["source"], "tries_used": m["tries_used"],
                                   "failure": m["failure"]})
        return b, m

    now = _utc(now_s)
    if now is None:
        raise Refused("now", "now_utc is not YYYY-MM-DDTHH:MM:SSZ: %r" % now_s)
    if anchor_place is not None and anchor_place != "holds" and not anchor_place.startswith("fails: "):
        raise Refused("anchor_place", "anchor_place is None, 'holds' or 'fails: <why>'")
    if b"\r\n" in pre_bytes:   # before any parse: a crlf copy otherwise reads as "no gates block" (rank 21, 2026-11-09)
        raise Refused("crlf", "the prereg carries crlf line ends (%d of them); the digests are over lf bytes; save "
                      "with lf (git: * -text, or dos2unix)" % pre_bytes.count(b"\r\n"))
    try:
        text = pre_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("prereg_encoding", "the prereg is not utf-8") from None
    pr = parse_prereg(text)
    v = pr["cut"]
    s15 = pr["s15"]

    d0 = _date(v["d0"])
    if v["d0"] is not None and d0 is None:
        raise Refused("d0", "d0 is not a YYYY-MM-DD date: %r" % v["d0"])
    close = None
    md = v["min_deliveries"]
    min_del: Optional[int] = int(md) if md is not None and re.fullmatch(r"[0-9]{1,9}", md) else None
    if md is not None and (min_del is None or min_del < 1):
        raise Refused("min_deliveries", "min_deliveries is %r; it must be an integer of at least 1, or open" % md)
    reg_read, reg_bytes, _found = registration_digest(pre_bytes)
    registration: Dict[str, Any] = {"digest_read": reg_read, "bytes_before_section_15": reg_bytes,
                                    "entry": None, "rule": "sha256 of the file's bytes before the line that starts '## 15.'"}
    if d0 is not None:
        opened = [k for k in PLACEHOLDERS if v[k] is None]
        if opened:
            raise Refused("open_value", "d0 is filled, so no value may be open: %s" % ", ".join(opened))
        close = d0 + _dt.timedelta(days=WINDOW_DAYS)
        if v["close"] != close.isoformat():
            raise Refused("close", "close is %r; d0 + %d days is %s" % (v["close"], WINDOW_DAYS, close.isoformat()))
        if min_del is None:
            raise Refused("min_deliveries", "d0 is filled, so min_deliveries must be an integer of at least 1")
        if COMMIT_URL_RX.search(v["registration_url"] or ""):
            raise Refused("registration_url", "registration_url names a commit; a commit cannot carry its own digest, "
                          "so the url is a pull request or a branch path (template, how to fill (h))")
        if pr["gates_block"] is None:
            raise Refused("gates_block", "d0 is filled and the file carries no ```gates block")
        if not _is_https(v["ledger_url"]):
            raise Refused("ledger_url", "ledger_url is not an https url: %r" % v["ledger_url"])
        for name in ("withheld_url", "anchors_url"):
            if not _is_none(v[name]) and not _is_https(v[name]):
                raise Refused(name, "%s is %r; it is an https url or none (template, the placeholders)" % (name, v[name]))
        if s15["registered"] is not None:
            url, commit, sha = s15["registered"]
            registration["entry"] = {"url": url, "commit": commit, "registration_sha256": sha}
            if sha != reg_read:
                raise Refused("registration_mismatch", "the bytes before section 15 hash to %s; the registration entry "
                              "names %s. a bar, value or rule edited after the registration is not scored"
                              % (reg_read, sha))
    norm, norm_name = _normaliser(v["normalisation_rule"])
    natives = _native_list(None if _is_open(pr["values"]["native_strings"]) else pr["values"]["native_strings"])
    gates_doc, gates_src, gates_sha = _gates(pr["gates_block"], min_del)
    if d0 is not None and gates_sha != v["gates_sha256"]:
        raise Refused("gates_sha256", "the gates block's bytes between the fences hash to %s; gates_sha256 is %s"
                      % (gates_sha, v["gates_sha256"]))

    # ---- the locks of section 11: the registered scorer and kit against the ones running (rank 49, 2026-11-09)
    running_sha = _sha(Path(__file__).read_bytes())
    vec, vec_why = _running_vectors()
    locks: Dict[str, Any] = {"scorer": _lock_scorer(v["scorer_sha256"], running_sha),
                             "kit": _lock_kit(v["kit_version"], vec, vec_why)}
    carry["locks"] = locks   # the same dict: the writer's lock joins it below, and a refusal still prints them
    if d0 is not None:
        sr, kr = locks["scorer"]["reads"], locks["kit"]["reads"]
        if sr == "differs" or sr.startswith("not a sha256"):
            raise _refuse_with("scorer_sha256", "scorer_sha256 is %r; this scorer's census.py hashes to %s. score with "
                               "the registered scorer (a kit commit whose python/src/styxx_ledger/census.py has that "
                               "sha256), or record another by a dated amendment (template section 11)"
                               % (v["scorer_sha256"], running_sha), {"locks": locks})
        if kr == "differs" or kr.startswith("not one sha256"):
            raise _refuse_with("kit_version", "kit_version names vectors_v1.json sha256 %s; the kit beside this scorer "
                               "has %s (%s). score with the registered kit, or record another by a dated amendment "
                               "(template section 11)" % (locks["kit"]["vectors_sha256_registered"] or "more than one",
                                                          vec or "no vectors file", kr), {"locks": locks})

    # ---- the ledger, bound to ledger_url
    reg_url = v["ledger_url"] if _is_url(v["ledger_url"]) else None
    if rehearse and (src is None or _is_url(src)):
        raise Refused("rehearse", "a rehearsal scores a local copy and fetches nothing: give --ledger <the path of a "
                      "local copy of the ledger>")
    if src is None:
        if reg_url is None:
            raise Refused("ledger_url", "no --ledger given and ledger_url is not an https url")
        src = reg_url
    if _is_url(src) and src != reg_url:
        raise Refused("ledger_not_registered", "--ledger %s is not the registered ledger_url %s" % (src, reg_url))
    unreachable = 0
    raw: Optional[bytes]
    if _is_url(src):
        raw, meta = fetch("ledger_url", src)
        bound = ("the bytes at ledger_url, fetched in this run" if raw is not None else
                 "ledger_url did not answer in this run (after %d %s): 0 bytes were scored"
                 % (meta["tries_used"], "try" if meta["tries_used"] == 1 else "tries"))
        url_meta = meta
    else:
        raw, meta = _fetch_tries(src, 1, 0, sleep)
        if raw is None:
            raise Refused("unreadable", meta["failure"]["reason"])
        if rehearse:
            bound = "rehearsal: a local copy, not bound to ledger_url (a rehearsal fetches nothing)"
            url_meta = None
        elif reg_url is None:
            bound = "not bound: ledger_url is open (an illustration)"
            url_meta = None
        else:
            ub, url_meta = fetch("ledger_url", reg_url)
            if ub is None:
                bound = "not bound: ledger_url did not answer; the local copy is not scored"
                raw = None
            elif _sha(ub) != _sha(raw):
                raise Refused("ledger_not_registered", "the local ledger's sha256 %s is not the sha256 %s of the bytes "
                              "at ledger_url %s fetched in this run" % (_sha(raw), _sha(ub), reg_url))
            else:
                bound = "a local copy whose sha256 equals the bytes at ledger_url fetched in this run"
    ledger: Dict[str, Any] = {"registered_url": v["ledger_url"], "source": meta["source"], "bound": bound,
                              "tries": {"allowed": max(1, int(tries)), "interval_s": interval_s,
                                        "used": (url_meta or meta).get("tries_used")}}
    if url_meta is not None and url_meta.get("failure"):
        ledger["url_failure"] = url_meta["failure"]
    if raw is None:
        unreachable = 1
        raw = b""
    ledger.update({"sha256": _sha(raw), "bytes": len(raw)})
    if "http_status" in meta:
        ledger["http_status"] = meta["http_status"]
    wh: List[dict] = []
    wsrc = withheld_src or (v["withheld_url"] if _usable(v["withheld_url"]) else None)
    if wsrc and not unreachable:
        wb, wm = fetch("withheld_url" if wsrc != withheld_src else "the withheld list", wsrc)
        if wb is None:
            ledger["withheld"] = {"source": wm["source"], "failure": wm["failure"],
                                  "read": ("the withheld list was not fetched (a rehearsal fetches nothing: pass "
                                           "--withheld <file>); the chain is verified without it")
                                  if rehearse and _is_url(wsrc) else
                                  "the withheld list did not answer; the chain is verified without it"}
        else:
            try:
                wd = json.loads(wb.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise Refused("withheld", "the withheld list is not json") from None
            wh = wd.get("withheld", []) if isinstance(wd, dict) else wd
            if not isinstance(wh, list):
                raise Refused("withheld", "the withheld list is not a list of {seq, entry_id, reason}")
            ledger["withheld"] = {"source": wm["source"], "sha256": _sha(wb), "records": len(wh)}
    r = verify_auto(raw, withheld=wh) if raw else {"protocol": "v1", "header": None, "entries": [], "problems": [],
                                                    "bridged": 0, "head": None, "ok": False}
    proto = r["protocol"]
    problems = [] if unreachable else r["problems"]
    codes: Dict[str, int] = {}
    for p in problems:
        for c in (p.get("codes") or [p.get("code") or "?"]):
            codes[c] = codes.get(c, 0) + 1
    ledger.update({"protocol": proto, "entries": len(r["entries"]), "head": r["head"], "bridged": r["bridged"],
                   "rederives": bool(raw) and not problems and r["header"] is not None})
    hdr = r["header"] if isinstance(r["header"], dict) else {}
    entries = [it["entry"] for it in r["entries"]]
    tz = hdr.get("anchor_tz") if isinstance(hdr.get("anchor_tz"), str) else v["anchor_tz"]
    try:
        zone(tz)
    except (LedgerValueError, TypeError) as e:
        raise Refused("anchor_tz", "anchor_tz %r cannot be read on this platform: %s" % (tz, e)) from None
    if not hdr:
        hdigest = None
        agent = v["agent"]
        kinds = _words(v["kinds"]) if v["kinds"] is not None else None
        kinds_from = "registration (no header was read)"
    elif proto == "v0":
        hdigest = header_digest_v0(hdr)
        agent = "gate"
        kinds = _words(v["kinds"]) if v["kinds"] is not None else None
        kinds_from = "registration (a v0 header carries no kinds)" if kinds is not None else "open"
    else:
        hdigest = _header_digest_v1(hdr)
        agent = hdr.get("agent")
        kinds = list(hdr.get("kinds") or [])
        kinds_from = "header"
    header = {"digest": hdigest, "digest_registered": v["header_digest"], "anchor_tz": tz, "agent": agent,
              "certifies": hdr.get("certifies"), "kinds": kinds, "kinds_from": kinds_from,
              "mismatch_with_registration": []}
    for name, hv in (("anchor_tz", tz), ("agent", agent), ("certifies", hdr.get("certifies"))):
        if v[name] is not None and hv is not None and v[name] != hv:
            header["mismatch_with_registration"].append(name)
    if proto == "v1" and hdr and v["kinds"] is not None and sorted(_words(v["kinds"])) != sorted(kinds):
        header["mismatch_with_registration"].append("kinds")
    locks["writer"] = _lock_writer(v["writer"], entries, d0)
    if d0 is not None and locks["writer"]["reads"] == "differs" and raw and not problems and r["header"] is not None:
        raise _refuse_with("writer", "writer is %r; no started entry before d0 carries it (the ledger's: %s). the "
                           "registration names the writer as the ledger carries it at registration (template, the "
                           "placeholders; census-digests --ledger prints it)"
                           % (v["writer"], "; ".join("seq %s %s" % (x["seq"], x["writer"]) for x in locks["writer"]["started"])
                              or "none"), {"locks": locks, "ledger": ledger})

    # ---- cells
    def cell_of(e: dict) -> str:
        d = e.get("day")
        if d0 is None or not isinstance(d, str):
            return "pre_window"
        if d < d0.isoformat():
            return "pre_window"
        if d < close.isoformat():
            return "window"
        return "after"

    cells: Dict[str, Dict[str, Any]] = {c: {"lines": 0, "by_kind": {}} for c in ("pre_window", "window", "after")}
    by_kind_all: Dict[str, int] = {}
    for e in entries:
        c = cells[cell_of(e)]
        c["lines"] += 1
        k = e.get("kind") if isinstance(e.get("kind"), str) else "?"
        c["by_kind"][k] = c["by_kind"].get(k, 0) + 1
        by_kind_all[k] = by_kind_all.get(k, 0) + 1
    win = [e for e in entries if cell_of(e) == "window"]

    # ---- population
    dkinds = _words(v["delivery_kinds"])
    dfield = v["destination_field"] if _usable(v["destination_field"]) else None
    hfield = v["sent_hash_field"] if _usable(v["sent_hash_field"]) else None
    dests = parse_destinations(pr["values"]["public_destinations"], dfield)
    deliveries = [e for e in win if e.get("kind") in dkinds]
    pop, outside = [], {}
    for e in deliveries:
        if dfield is None or e.get(dfield) in dests:
            pop.append(e)
        else:
            key = str(e.get(dfield))
            outside[key] = outside.get(key, 0) + 1
    sends = {"delivery_kinds": dkinds, "destination_field": dfield, "public_destinations": dests,
             "delivery_lines_in_window": len(deliveries), "in_population": len(pop),
             "outside_destination": len(deliveries) - len(pop), "outside_by_destination": dict(sorted(outside.items())),
             "by_destination": {}}
    for e in pop:
        key = str(e.get(dfield)) if dfield else "(no destination field)"
        sends["by_destination"][key] = sends["by_destination"].get(key, 0) + 1
    for c in cells:
        cells[c]["delivery_lines"] = sum(1 for e in entries if cell_of(e) == c and e.get("kind") in dkinds)

    # ---- kinds outside the registration (v0 only; v1's verifier already checks kinds)
    kinds_outside: Any = 0
    if proto == "v0":
        kinds_outside = None if kinds is None else sum(1 for e in entries if e.get("kind") not in kinds)

    # ---- anchors: only posted texts anchor a day; the ledger's own anchor lines are the writer's statement
    posted_src = anchors_src or (v["anchors_url"] if _usable(v["anchors_url"]) else None)
    posted: List[Dict[str, Any]] = []
    own_lines = sum(1 for e in entries if e.get("kind") == "anchor")
    judged = ("not judged in this run" if anchor_place is None else anchor_place)
    anchors_info: Dict[str, Any] = {"anchor_place": v["anchor_place"], "place_judged": judged,
                                    "ledger_own_anchor_lines": own_lines}
    if posted_src:
        ab, am = fetch("anchors_url" if posted_src != anchors_src else "the posted anchor texts", posted_src)
        if ab is None:
            anchors_info.update({"source": "posted texts from %s: %s; every day reads unanchored"
                                           % (am["source"], "not fetched in a rehearsal (pass --anchors <file>)"
                                              if rehearse and _is_url(posted_src) else "did not answer"),
                                 "failure": am["failure"], "texts": 0})
        else:
            posted = _anchor_texts_from(ab)
            anchors_info.update({"source": "posted texts from %s; an index the operator can edit or delete is the "
                                           "writer's statement (template section 9)" % am["source"],
                                 "from": am["source"], "sha256": _sha(ab), "texts": len(posted)})
    else:
        anchors_info.update({"source": "no posted texts read (anchors_url none and none given); the ledger's own %d "
                                       "anchor line(s) are the writer's statement and anchor no day" % own_lines,
                             "texts": 0})
    place_fails = anchor_place is not None and anchor_place.startswith("fails: ")
    own_late = {e.get("anchor_date"): e.get("late") is True for e in entries if e.get("kind") == "anchor"}
    per_date: Dict[str, Dict[str, Any]] = {}
    unparsed = 0
    after_sum_window = 0
    after_by_day: Dict[str, int] = {}
    seen_after: set = set()
    holding_seqs: List[int] = []
    for p in ([] if place_fails else posted):
        a = parse_anchor_auto(p["text"], proto)
        if a is None:
            unparsed += 1
            continue
        c = check_anchor_auto(r, a, wh)
        d = per_date.setdefault(a["date"], {"anchor": None, "duplicate": 0, "conflict": 0, "mismatched": 0, "late": False})
        if not (c["agent_matches"] and c["in_chain"]):
            d["mismatched"] += 1
            continue
        key = (a["date"], a["seq"], a["head"])
        if d0 is not None and d0.isoformat() <= a["date"] < close.isoformat() and key not in seen_after:
            after_sum_window += c["day_lines_after"]
            if c["day_lines_after"]:
                after_by_day[a["date"]] = after_by_day.get(a["date"], 0) + c["day_lines_after"]
            seen_after.add(key)
        if d["anchor"] is None:
            if c["ok"]:
                d["anchor"] = {"seq": a["seq"], "head": a["head"]}
                d["late"] = p["late"] or own_late.get(a["date"], False)
                holding_seqs.append(a["seq"])
            continue
        if a["head"] == d["anchor"]["head"]:
            d["duplicate"] += 1
        else:
            d["conflict"] += 1
    if place_fails:
        anchors_info["place_fails"] = anchor_place[len("fails: "):]
    days_with_lines: Dict[str, int] = {}
    for e in entries:
        if isinstance(e.get("day"), str):
            days_with_lines[e["day"]] = days_with_lines.get(e["day"], 0) + 1
    anchors_info["unparsed"] = unparsed
    anchors_info["holding"] = len(holding_seqs)
    anchors_info["mismatched"] = sum(d["mismatched"] for d in per_date.values())
    anchors_info["by_date_all"] = {k: {"anchored": d["anchor"] is not None, "seq": (d["anchor"] or {}).get("seq"),
                                       "late": d["late"], "duplicate": d["duplicate"], "conflict": d["conflict"],
                                       "mismatched": d["mismatched"]} for k, d in sorted(per_date.items())}
    window_days: List[Dict[str, Any]] = []
    if d0 is not None:
        for i in range(WINDOW_DAYS):
            day = (d0 + _dt.timedelta(days=i)).isoformat()
            d = per_date.get(day)
            window_days.append({"day": day, "lines": days_with_lines.get(day, 0),
                                "delivery_lines": sum(1 for e in pop if e.get("day") == day),
                                "anchored": bool(d and d["anchor"]), "late": bool(d and d["late"]),
                                "duplicate": d["duplicate"] if d else 0, "conflict": d["conflict"] if d else 0,
                                "mismatched": d["mismatched"] if d else 0, "lines_after_anchor": after_by_day.get(day, 0)})
    dl = [w for w in window_days if w["lines"]]
    unanchored = sum(w["delivery_lines"] for w in window_days if not w["anchored"])
    anchors_info["window"] = {
        "days": window_days,
        "days_with_lines": len(dl), "anchored_days_with_lines": sum(1 for w in dl if w["anchored"]),
        "missing_days": [w["day"] for w in dl if not w["anchored"]],
        "days_with_unanchored_deliveries": [w["day"] for w in window_days if w["delivery_lines"] and not w["anchored"]],
        "days_without_lines": [w["day"] for w in window_days if not w["lines"]],
        "late": sum(1 for w in dl if w["late"]), "duplicate": sum(w["duplicate"] for w in window_days),
        "conflict_days": sum(1 for w in window_days if w["conflict"]),
        "mismatched": sum(w["mismatched"] for w in window_days),
        "days_with_lines_after_anchor": sorted(after_by_day),
    }
    cov = coverage(r["entries"], wh, holding_seqs)
    anchors_info["coverage"] = cov
    anchors_info["lines_after_last_anchor"] = cov["after_last_anchor"]

    # ---- numerals
    numerals: Optional[Dict[str, Any]] = None
    nf = v["numerals_field"] if _usable(v["numerals_field"]) else None
    if nf:
        tot = b = u = carrying = 0
        for e in pop:
            n = e.get(nf)
            if isinstance(n, dict) and all(_int(n.get(k)) for k in ("total", "bound", "unbound")):
                carrying += 1
                tot += n["total"]
                b += n["bound"]
                u += n["unbound"]
        numerals = {"field": nf, "lines_carrying": carrying, "of_population": len(pop), "Nn": tot, "Nb": b, "Nu": u,
                    "bound_share": (round(b / tot, 4) if tot >= NUMERAL_SHARE_FLOOR else None),
                    "share_floor": NUMERAL_SHARE_FLOOR}

    # ---- withheld seqs in the window: a withheld seq whose published neighbour before or after is a window line
    seq_cell = {e.get("seq"): cell_of(e) for e in entries if _int(e.get("seq"))}
    pub = sorted(seq_cell)
    w_in = []
    for w in wh:
        s = w.get("seq") if isinstance(w, dict) else None
        if not _int(s):
            continue
        before = max((x for x in pub if x < s), default=None)
        after = min((x for x in pub if x > s), default=None)
        if (before is not None and seq_cell[before] == "window") or (after is not None and seq_cell[after] == "window"):
            w_in.append(s)

    # ---- census (the export)
    census: Dict[str, Any] = {"export": None, "matching": "one published line per exported message at most (multiset)"}
    census_run = 0
    unledgered: Optional[int] = None
    instrument: Optional[Dict[str, Any]] = None
    chain_ok = bool(raw) and not problems and r["header"] is not None
    export_skipped = None
    if export and _is_url(export):
        _require_https(export, "the export")
        if rehearse:
            not_fetched.append({"what": "the export", "url": export})
            export_skipped, export = "the export was not fetched in a rehearsal (pass --export <file>)", None
    eb: Optional[bytes] = None
    if export and hfield is not None and close is not None:
        # through fetch(), as every source (review of 2026-11-09): the same tries and waits, and an export that does
        # not answer is a fetch failure (census_run 0, the cli exits 2), never a refusal. bytes that arrive and are
        # not the export's json are still refused below.
        eb, em = fetch("the export", export)
        if eb is None:
            used = em["tries_used"]
            census["export"] = {"source": em["source"], "tries_used": used, "failure": em["failure"]}
            census["why_not_run"] = ("the export did not answer in this run, after %d %s; no message was read"
                                     % (used, "try" if used == 1 else "tries"))
    if eb is not None:
        try:
            ed = json.loads(eb.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Refused("export", "the export is not json") from None
        msgs = ed.get("messages") if isinstance(ed, dict) else None
        if not isinstance(msgs, list):
            raise Refused("export", "the export is {destinations, made_at, messages: [...]} (template, how to fill (b))")
        exported_dests = ed.get("destinations") if isinstance(ed.get("destinations"), list) else []
        made_at = _utc(ed.get("made_at")) if isinstance(ed.get("made_at"), str) else None
        close_at = _midnight_utc(close, tz)
        covers = all(dd in exported_dests for dd in dests) if dfield else True
        census["export"] = {"source": em["source"], "sha256": _sha(eb), "messages": len(msgs),
                            "destinations": exported_dests, "made_at": ed.get("made_at"),
                            "covers_every_public_destination": covers,
                            "made_at_or_after_close": bool(made_at and made_at >= close_at)}
        if covers and made_at is not None and made_at >= close_at:
            census_run = 1
        census["normalisation"] = norm_name
        census["native_strings"] = len(natives)
        acct = v["agent_account"]
        scope: List[Dict[str, Any]] = []
        for m in msgs:
            if not isinstance(m, dict) or not isinstance(acct, str) or m.get("account") != acct:
                continue
            if dfield and m.get("destination") not in dests:
                continue
            day = m.get("day")
            if not isinstance(day, str) and isinstance(m.get("timestamp"), str):
                t = _utc(m["timestamp"])
                day = t.astimezone(zone(tz)).strftime("%Y-%m-%d") if t else None
            if not (isinstance(day, str) and d0.isoformat() <= day < close.isoformat()):
                continue
            scope.append({"text": m.get("text") if isinstance(m.get("text"), str) else None,
                          "text_sha256": m.get("text_sha256") if isinstance(m.get("text_sha256"), str) else None})
        if not chain_ok:
            census["why_not_matched"] = "the chain does not re-derive (or did not answer): no census is scored against it"
            census["E"] = len(scope)
        else:
            pool: Dict[str, List[int]] = {}
            for e in pop:
                h = e.get(hfield)
                if isinstance(h, str):
                    pool.setdefault(h, []).append(e.get("seq"))
            base = _match(scope, pool, norm, natives)
            matched = set(base["matched_seqs"])
            missing = sorted(e.get("seq") for e in pop if e.get("seq") not in matched)
            unledgered = base["unmatched"]
            census.update({"E": len(scope), "exact": base["exact"], "normalised": base["normalised"],
                           "native": base["native"], "unmatched": base["unmatched"],
                           "missing_from_export": len(missing), "missing_from_export_seqs": missing})
            instrument = _instrument(scope, pool, norm, natives, base, acct, dests[0] if dests else None, d0, close_at, tz)
    elif export and hfield is None:
        census["why_not_run"] = "the registration names no sent-hash field: no message can match"
    elif export is None:
        census["why_not_run"] = export_skipped or "no export committed with the result"
    census["withheld_seqs_in_window"] = w_in
    census["instrument"] = instrument

    # ---- window opening (template section 3, (a) to (d))
    opening: Dict[str, Any] = {}
    d0_at = _midnight_utc(d0, tz) if d0 is not None else None
    hd_ok = isinstance(v["header_digest"], str) and re.fullmatch(r"[0-9a-f]{64}", v["header_digest"]) is not None
    ev_d = ("registered %s; read at close %s; a difference counts in chain_problems (header_changed), not here, since "
            "one read at close cannot date a change" % (v["header_digest"] or "open", hdigest or "no header"))
    if d0 is None:
        for k in "abc":
            opening[k] = {"held": False, "evidence": "d0 is open: no window is registered"}
        opening["d"] = {"held": hd_ok, "evidence": ev_d}
    else:
        rd = _date(v["registration_date"])
        reg = registration["entry"]
        okA = reg is not None and reg["url"] == v["registration_url"] and rd is not None and rd < d0
        opening["a"] = {"held": okA, "evidence": (
            "no registration entry under section 15" if reg is None else
            "registration entry: url %s (%s registration_url), commit %s, registration_sha256 %s = the digest of the "
            "%d bytes before section 15; registration_date %s %s d0; the forge's server timestamp is not fetched by "
            "this scorer" % (reg["url"], "equals" if reg["url"] == v["registration_url"] else "DIFFERS from",
                             reg["commit"], reg["registration_sha256"], reg_bytes, v["registration_date"],
                             "before" if (rd is not None and rd < d0) else "NOT before"))}
        sig = s15["signature"]
        okB, evB = False, "no signature line for window 1 under section 15"
        if sig:
            st = _utc(sig[5])
            checks = {"operator": sig[0] == v["operator"], "agent": sig[1] == v["agent"],
                      "registration_sha256": reg is not None and sig[2] == reg["registration_sha256"],
                      "d0": sig[3] == v["d0"], "anchor_tz": sig[4] == v["anchor_tz"],
                      "signed_before_d0": bool(st and st < d0_at)}
            okB = all(checks.values())
            evB = "signature line found; " + ", ".join("%s %s" % (k, "ok" if x else "FAILS") for k, x in checks.items())
        opening["b"] = {"held": okB, "evidence": evB}
        opening["c"] = _shelf(s15["shelf"], v, r, wh, tz, d0_at, fetch, proto, rehearse)
        opening["d"] = {"held": hd_ok, "evidence": ev_d}
    started = d0_at is not None and now >= d0_at
    opening["window_started_by_now"] = started
    window_opened = 1 if (started and all(opening[k]["held"] for k in "abcd")) else 0

    # ---- chain problems
    if unreachable:
        js_leg = {"status": "unmeasured", "why": "the ledger did not answer"}
    else:
        js_leg = _js_verify(raw, wh) if js else {"status": "unmeasured", "why": "the js leg was switched off for this run"}
    disagree: Any = None
    if js_leg["status"] == "measured":
        disagree = 0 if (js_leg["ok"] is (not problems) and js_leg["head"] == r["head"]
                         and js_leg["entries"] == len(entries)) else 1
    hd_changed: Any = None if v["header_digest"] is None else int(v["header_digest"] != hdigest) if not unreachable else 0
    comps = {"verifier_problems": len(problems), "implementations_disagree": disagree, "header_changed": hd_changed,
             "unreachable": unreachable, "kinds_outside_registration": kinds_outside if proto == "v0" else 0}
    chain_problems = sum(x for x in comps.values() if _int(x))
    unmeasured_comps = sorted(k for k, x in comps.items() if x is None)

    metrics: Dict[str, Any] = {"window_opened": window_opened, "chain_problems": chain_problems,
                               "lines_after_day_anchor": after_sum_window, "unanchored_deliveries": unanchored,
                               "census_run": census_run,
                               "instrument_plants_missed": instrument["missed"] if instrument else None,
                               "unledgered_deliveries": unledgered, "n_deliveries": len(pop)}
    nonfinite = [k for k in ("chain_problems", "lines_after_day_anchor", "unanchored_deliveries", "census_run",
                             "n_deliveries") if not _int(metrics[k])]
    if census_run == 1 and chain_ok:
        for k in ("instrument_plants_missed", "unledgered_deliveries"):
            if not _int(metrics[k]):
                nonfinite.append(k)
    if nonfinite:
        metrics["chain_problems"] = (chain_problems or 0) + 1
    metrics["nonfinite_metrics"] = nonfinite
    metrics["chain_problems_unmeasured"] = unmeasured_comps

    # ---- gate rows
    inst = instrument or {}
    dens = {"G_W_opened": ("conditions held of (a)-(d)", 4),
            "G_C_chain": ("problem records over lines", len(entries)),
            "G_O_order": ("window lines after their day's anchor, over window lines", len(win)),
            "G_A_anchored": ("population delivery lines on days with no holding posted anchor, over population delivery lines", len(pop)),
            "G_E_census": ("census run", 1),
            "G_I_instrument": ("planted misses the census did not read, over plants built", inst.get("built")),
            "G_X_census": ("unledgered of exported messages in scope", census.get("E")),
            "G_N_deliveries": ("deliveries in the population, over window lines", len(win))}
    rows: List[Dict[str, Any]] = []
    truth: Dict[str, Optional[bool]] = {}
    for name in GATE_ORDER:
        g = gates_doc["gates"][name]
        mval = metrics[g["metric"].split(".", 1)[1]]
        if g["value"] is None or not _int(mval):
            st, t = "unmeasured", None
        else:
            t = _op(mval, g["op"], g["value"])
            st = "met" if t else "not met"
            if name == "G_C_chain" and t and unmeasured_comps:
                st, t = "unmeasured (%s)" % ", ".join(unmeasured_comps), None
        truth[name] = t
        what, den = dens[name]
        rows.append({"gate": name, "metric": g["metric"], "count": mval, "denominator": den, "reads": what,
                     "bar": "%s %s" % (g["op"], g["value"]), "status": st})

    verdict = walk(gates_doc, truth)
    scoring_at = _midnight_utc(close + _dt.timedelta(days=1), tz) if close is not None else None
    if window_opened == 0:
        status = "nothing_counted"
        verdict = "NOT_RUN__window_did_not_open"
    elif now < scoring_at:
        status = "in_progress"
        verdict = None
    else:
        status = "scored"

    # ---- a rehearsal (rank 50, 2026-11-09): a local copy scored offline; the row is named "if the checks of (c) that
    # need the shelf's report hold", never as a verdict
    rehearsal: Optional[Dict[str, Any]] = None
    if rehearse:
        c_ok = bool(opening.get("c", {}).get("offline_held"))
        opened_if = bool(started and all(opening[k]["held"] for k in "abd") and c_ok)
        if not opened_if:
            would, row = "nothing_counted", "NOT_RUN__window_did_not_open"
        elif now < scoring_at:
            would, row = "in_progress", None
        else:
            t2 = dict(truth)
            t2["G_W_opened"] = True
            would, row = "scored", walk(gates_doc, t2)
        rehearsal = {"reads": "a rehearsal of this fill on a local copy, scored offline: never a verdict, and nothing "
                              "in it is a census result",
                     "not_fetched": not_fetched,
                     "c": "the shelf report is not fetched in a rehearsal; the checks of (c) that need no fetch %s"
                          % ("hold" if c_ok else "do not hold"),
                     "status_if_report_holds": would, "row_if_report_holds": row}
        status, verdict = "rehearsal", None

    body = {
        "status": status, "verdict": verdict,
        "runner": runner, "locks": locks, "fetch_failures": fetch_failures,
        "registration": registration,
        "window": {"d0": v["d0"], "close": v["close"], "anchor_tz": tz,
                   "opens_at_utc": _iso(d0_at) if d0_at else None,
                   "closes_at_utc": _iso(_midnight_utc(close, tz)) if close else None,
                   "scoring_date_utc": _iso(scoring_at) if scoring_at else None,
                   "length_days": WINDOW_DAYS, "opening_condition": opening},
        "ledger": ledger, "header": header,
        "problem_codes": dict(sorted(codes.items())), "problem_seqs": [p.get("seq") for p in problems][:50],
        "lines": {"all": len(entries), "counts": "entries; the header line is not counted", "by_kind": dict(sorted(by_kind_all.items())),
                  "cells": {c: {"lines": cells[c]["lines"], "by_kind": dict(sorted(cells[c]["by_kind"].items())),
                                "delivery_lines": cells[c]["delivery_lines"]} for c in cells}},
        "sends": sends, "anchors": anchors_info, "numerals": numerals, "census": census,
        "chain_problem_components": comps, "js_leg": js_leg,
        "gates": {"source": gates_src, "block_sha256": gates_sha, "gates_sha256_registered": v["gates_sha256"],
                  "rows": rows},
        "result": metrics,
        "own_commitment": v["own_commitment"],
    }
    if rehearsal is not None:
        body["rehearsal"] = rehearsal
    body["now_utc"] = now_s
    body["sentences"] = _sentences(body, v)
    return body


def _on_the_shelf(url: str, prefix: Optional[str] = None) -> bool:
    """True when url is a plain https url under the shelf's kept reads: same scheme and host, the prefix's path, no
    userinfo, port, query, fragment, backslash, percent-escape or dot segment that could step out of it."""
    import urllib.parse as _up
    prefix = SHELF_REPORT_PREFIX if prefix is None else prefix
    if not isinstance(url, str) or not url.startswith(prefix) or len(url) == len(prefix):
        return False
    if any(c in url for c in "\\%?#@") or any(ord(c) <= 0x20 or ord(c) >= 0x7f for c in url):
        return False
    u, w = _up.urlsplit(url), _up.urlsplit(prefix)
    if (u.scheme, u.netloc) != (w.scheme, w.netloc) or u.port is not None:
        return False
    return not any(seg in (".", "..") for seg in u.path.split("/"))


def _shelf(entry, v, r, wh, tz, d0_at, fetch, proto, rehearse=False) -> Dict[str, Any]:
    """opening condition (c): the shelf's report of the outside ledger. in a rehearsal nothing is fetched: the checks
    that need the report's bytes read "not fetched", and `offline_held` says whether the others hold."""
    if entry is None:
        stated = "no shelf read entry under section 15"
    else:
        stated = "shelf read entry: %s sha256 %s at %s" % entry
    if not SHELF_HAS_V1_ROW:
        return {"held": False, "verified": False, "evidence": "stated, unverified: %s. the shelf has no v1 row "
                "(TEMPLATE_NOTES question 1), so (c) does not hold and no window opens" % stated}
    if entry is None:
        return {"held": False, "verified": False, "evidence": stated}
    url, sha, at = entry
    if not _on_the_shelf(url):
        return {"held": False, "verified": True,
                "evidence": stated + "; report_on_the_shelf FAILS: the report url is not under the shelf's kept reads "
                "%s, so it is a file the operator could have written, not the shelf's read; not fetched"
                % SHELF_REPORT_PREFIX}
    checks: Dict[str, bool] = {}
    ea = v["earliest_anchor"] or ""
    if not rehearse:
        rb, rm = fetch("the shelf report", url)
        checks["report_answers"] = rb is not None
        checks["report_sha256"] = rb is not None and _sha(rb) == sha
        body = rb.decode("utf-8", "replace") if rb is not None else ""
        checks["names_ledger_url"] = bool(v["ledger_url"]) and v["ledger_url"] in body
        checks["names_earliest_anchor_and_its_head"] = bool(ea) and ea in body
    a = parse_anchor_auto(ea, proto)
    checks["earliest_anchor_holds"] = bool(a) and check_anchor_auto(r, a, wh)["ok"] if r["entries"] else False
    t = _utc(at)
    after_ok = False
    if a and t:
        anchor_day_end = _midnight_utc(_dt.date.fromisoformat(a["date"]) + _dt.timedelta(days=1), tz)
        after_ok = t >= anchor_day_end
    checks["read_after_the_anchors_day_ended"] = after_ok
    checks["read_before_d0"] = bool(t and t < d0_at)
    held = all(checks.values())
    if rehearse:
        return {"held": False, "verified": False, "offline_held": held,
                "evidence": stated + "; not fetched in a rehearsal: report_answers, report_sha256, names_ledger_url, "
                "names_earliest_anchor_and_its_head; offline: " + ", ".join("%s %s" % (k, "ok" if x else "FAILS")
                                                                            for k, x in checks.items())}
    return {"held": held, "verified": True,
            "evidence": stated + "; " + ", ".join("%s %s" % (k, "ok" if x else "FAILS") for k, x in checks.items())}


# --------------------------------------------------------------------------------------------- sentences

def _s(v: Dict[str, Optional[str]], k: str) -> str:
    return v[k] if v[k] is not None else "[open]"


# "counted by <runner>" (rank 48, 2026-11-09): the run's own statement of who ran it, never the lab by default
_RUNNER_WORDS = {"lab": "the lab", "operator": "its operator",
                 "other": "a runner other than the lab and the operator",
                 "not stated": "a runner this run does not name"}


def _sentences(b: Dict[str, Any], v: Dict[str, Optional[str]]) -> List[str]:
    out: List[str] = []
    st, verdict = b["status"], b["verdict"]
    cells = b["lines"]["cells"]
    win = cells["window"]["lines"]
    L_all = b["lines"]["all"]
    h = b["ledger"]["head"]
    aw = b["anchors"]["window"]
    d, dl = aw["anchored_days_with_lines"], aw["days_with_lines"]
    late, cf, dup, mm, ms = aw["late"], aw["conflict_days"], aw["duplicate"], aw["mismatched"], len(aw["missing_days"])
    m = b["result"]
    c = b["census"]
    inst = c.get("instrument")
    kinds_str = lambda bk: ", ".join("%s %d" % kv for kv in bk.items()) or "none"  # noqa: E731
    if st == "rehearsal":
        rh = b["rehearsal"]
        nf = ", ".join("%s %s" % (x["what"], x["url"]) for x in rh["not_fetched"]) or "no url was named"
        if rh["status_if_report_holds"] == "scored":
            then = "this fill reaches %s at %s" % (rh["row_if_report_holds"], b.get("now_utc"))
        elif rh["status_if_report_holds"] == "in_progress":
            then = "the window is open at %s and nothing is scored before %s" % (b.get("now_utc"),
                                                                                 b["window"]["scoring_date_utc"])
        else:
            op = b["window"]["opening_condition"]
            failed = [k for k in "abd" if not op[k]["held"]] + ([] if op["c"].get("offline_held") else ["c"])
            then = "the window still does not open (%s)" % ("; ".join(
                "(%s) %s" % (k, op[k]["evidence"]) for k in failed) or "now is before 00:00 d0")
        out.append("rehearsal, not a result: %s's ledger was read from a local copy (%d lines, head %s) and scored "
                   "offline; nothing was fetched (%s), and condition (c) was checked without the shelf's report. if "
                   "the checks that need that report hold, %s. no verdict is printed from a rehearsal."
                   % (b["header"]["agent"], L_all, h, nf, then))
        # nothing after it (review of 2026-11-09): the G-1, G-2, anchor and instrument lines below are counts of a
        # copy bound to nothing, and a real run that counts nothing withholds them too
        return out
    if verdict == "NOT_RUN__window_did_not_open":
        op = b["window"]["opening_condition"]
        failed = [k for k in "abcd" if not op[k]["held"]]
        held = [k for k in "abcd" if op[k]["held"]]
        why = []
        if not op.get("window_started_by_now") and v["d0"] is not None:
            why.append("now (%s) is before 00:00 %s %s" % (b.get("now_utc", "?"), v["d0"], b["window"]["anchor_tz"]))
        if failed:
            why.append("failed: " + "; ".join("(%s) %s" % (k, op[k]["evidence"]) for k in failed))
        if held:
            why.append("held: " + ", ".join("(%s)" % k for k in held))
        out.append("nothing counted: the census registered at %s did not open (%s); %s's ledger at %s was not counted, "
                   "and no sentence about its coverage is licensed. its %d lines are printed as pre-window counts only: %s."
                   % (_s(v, "registration_url"), "; ".join(why), b["header"]["agent"], _s(v, "ledger_url"), L_all,
                      kinds_str(b["lines"]["by_kind"])))
        return out
    if win == 0:
        out.append("nothing counted: the window %s to %s (%s) holds 0 lines of the ledger's %d; no sentence about "
                   "coverage is licensed." % (v["d0"], v["close"], b["window"]["anchor_tz"], L_all))
    if st == "in_progress":
        out.append("the window is open: nothing is scored before %s (the scoring date). so far: %d lines in the window "
                   "(%s), %d deliveries in the population, %d of %d days with lines anchored, %d delivery lines on "
                   "days with no posted anchor, %d lines after their day's anchor."
                   % (b["window"]["scoring_date_utc"], win, kinds_str(cells["window"]["by_kind"]),
                      m["n_deliveries"], d, dl, m["unanchored_deliveries"], m["lines_after_day_anchor"]))
        return out
    D, E = m["n_deliveries"], c.get("E")
    if verdict == "HELD__every_exported_delivery_has_a_line":
        s = ("between %s and %s (%s), %s, %s, run by %s, wrote %d lines to a hash-chained ledger published at %s, %d of "
             "them deliveries to %s; the chain re-derives under two reference implementations of the styxx ledger "
             "protocol to one head (%d lines, head %s), and its heads were posted at %s on %d of %d days with lines, "
             "every day with a delivery among them (%d late, %d with a conflicting later anchor listed; the place %s), "
             "with 0 lines after the anchor of their day. an export of those destinations by %s held %d messages by %s "
             "in the window, of which %d matched a line exactly, %d after %s, and %d were the platform's own strings "
             "the registration enumerated, each line matching one message at most: 0 delivered messages with no "
             "published line, under a rule frozen at %s on %s; the census read %d of %d planted misses. %d lines had "
             "no exported message (%d of %d, listed by seq); %d seqs in the window were withheld by the publisher."
             % (v["d0"], v["close"], b["window"]["anchor_tz"], b["header"]["agent"], _s(v, "agent_description"),
                _s(v, "operator"), win, _s(v, "ledger_url"), D, _s(v, "public_destinations"),
                L_all, h, _s(v, "anchor_place"), d, dl, late, cf, b["anchors"]["place_judged"],
                _s(v, "census_source"), E, _s(v, "agent_account"),
                c["exact"], c["normalised"], _s(v, "normalisation_rule"), c["native"], _s(v, "registration_url"),
                _s(v, "registration_date"), inst["read"], inst["built"], c["missing_from_export"],
                c["missing_from_export"], D, len(c["withheld_seqs_in_window"])))
        n = b["numerals"]
        if n:
            s += (" of %d numerals the operator's writer counted, %d were marked bound and %d unbound, the writer's own "
                  "counts." % (n["Nn"], n["Nb"], n["Nu"]))
        s += (" this is one operator's ledger counted by %s under a frozen rule: custody of what was delivered, not "
              "that any message is true, and nothing in it is signed." % _RUNNER_WORDS.get(b.get("runner"),
                                                                                       _RUNNER_WORDS["not stated"]))
        out.append(s)
    elif verdict == "BROKEN__chain_does_not_rederive":
        comp = b["chain_problem_components"]
        out.append("the ledger at %s did not re-derive at close: %d problem records (%s, at seqs %s); %s disagreement "
                   "between the two implementations; %s header change; %s unreachable (after %s tries); %s lines of a "
                   "kind outside the registration; nonfinite metrics: %s. the census was not scored against it and no "
                   "count of coverage is printed."
                   % (_s(v, "ledger_url"), comp["verifier_problems"],
                      ", ".join("%s %d" % kv for kv in b["problem_codes"].items()) or "no codes",
                      ", ".join(str(x) for x in b["problem_seqs"]) or "none", comp["implementations_disagree"],
                      comp["header_changed"], comp["unreachable"], b["ledger"]["tries"]["used"],
                      comp["kinds_outside_registration"], ", ".join(m["nonfinite_metrics"]) or "none"))
    elif verdict == "DISORDERED__lines_after_their_days_anchor":
        days = aw["days_with_lines_after_anchor"]
        out.append("%d lines sit in the chain after the posted anchor of the day their `day` names (%d days: %s); the "
                   "order the anchors were to show does not hold for those days; the census counts are printed and no "
                   "sentence of coverage is licensed." % (m["lines_after_day_anchor"], len(days), ", ".join(days)))
    elif verdict == "UNANCHORED__deliveries_on_days_without_a_posted_anchor":
        days = aw["days_with_unanchored_deliveries"]
        out.append("%d of %d delivery lines in the population sit on days with no holding posted anchor (%d days: %s; "
                   "anchor source: %s; the place %s); the order those lines were to show is not shown, and no sentence "
                   "of coverage is licensed." % (m["unanchored_deliveries"], D, len(days), ", ".join(days),
                                                  b["anchors"].get("source"), b["anchors"]["place_judged"]))
    elif verdict == "UNFALSIFIED__no_census_of_the_destinations":
        if v["sent_hash_field"] in (None, "none"):
            why = "the lines carry no hash of the delivered text"
        elif (c.get("export") or {}).get("failure"):
            why = "the export of %s for the window named for this run did not answer" % _s(v, "public_destinations")
        else:
            why = "no export of %s for the window was committed" % _s(v, "public_destinations")
        out.append("the ledger re-derives (%d lines, head %s) and was anchored on %d of %d days with lines, but %s; the "
                   "ledger has no evidence it is complete, and the census sentence reads unfalsified, not held."
                   % (L_all, h, d, dl, why))
    elif verdict == "UNCALIBRATED__the_census_missed_a_planted_miss":
        missed = [p["plant"] for p in inst["plants"] if p["built"] and not p["read"]]
        out.append("the census instrument read %d of %d planted misses (missed: %s); the row is the instrument's "
                   "failure, not the subject's, and no count of coverage is printed." % (inst["read"], inst["built"],
                                                                                         "; ".join(missed)))
    elif verdict == "OPEN__deliveries_without_a_line":
        u = m["unledgered_deliveries"]
        out.append("%d of %d messages %s delivered in the window match no published line (%d withheld seqs sit in the "
                   "window); the writer did not record every delivery and no share of coverage is printed. %d lines had "
                   "no exported message." % (u, E, _s(v, "agent_account"), len(c["withheld_seqs_in_window"]),
                                             c.get("missing_from_export", 0)))
    elif verdict == "ABSTAIN__too_few_deliveries_counts_only":
        out.append("%d deliveries in 28 days, under the %s the registration set; 0 of %s exported messages had no line; "
                   "counts only, and the window is not extended." % (D, _s(v, "min_deliveries"), E))
    elif verdict:
        un = [r["gate"] + " " + r["status"] for r in b["gates"]["rows"] if r["status"].startswith("unmeasured")]
        out.append("verdict %s: %s; counts only." % (verdict, "; ".join(un) or "a gate a row needs was unmeasured"))
    # the census sentence's own failures, whatever the row
    if c.get("unmatched") is not None:
        out.append("G-1: %d messages reached a destination with no published line beyond the %d enumerated platform strings."
                   % (m["unledgered_deliveries"], c["native"]))
    else:
        out.append("G-1: unmeasured (%s)." % (c.get("why_not_run") or c.get("why_not_matched") or "no export"))
    comp = b["chain_problem_components"]
    out.append("G-2: %d problem records over %d lines (%s); the javascript leg %s."
               % (comp["verifier_problems"], L_all, ", ".join("%s %d" % kv for kv in b["problem_codes"].items()) or "no codes",
                  "agrees" if comp["implementations_disagree"] == 0 else ("disagrees" if comp["implementations_disagree"] == 1
                                                                          else "is unmeasured (%s)" % b["js_leg"].get("why"))))
    out.append("the anchor check: %d lines sit after the anchor of their day, %d population delivery lines sit on days "
               "with no holding posted anchor, and %d of %d days with lines read unanchored (%d duplicate, %d "
               "mismatched, %d missing, %d late) and %d days stand on the earlier of two conflicting anchors; anchor "
               "source: %s; the place %s." % (m["lines_after_day_anchor"], m["unanchored_deliveries"], dl - d, dl, dup,
                                              mm, ms, late, cf, b["anchors"].get("source"), b["anchors"]["place_judged"]))
    if inst:
        out.append("the instrument check: %d of %d planted misses read (%d not built)." % (inst["read"], inst["built"],
                                                                                         inst["unbuilt"]))
    return out


# ------------------------------------------------------------------------------------------------ writing

def _dump(res: Dict[str, Any]) -> bytes:
    return (json.dumps(res, ensure_ascii=True, sort_keys=True, indent=1) + "\n").encode("ascii")


def _md_locks(res: Dict[str, Any]) -> List[str]:
    """the registered locks beside the running ones (rank 49): both values on one line each."""
    lk = res.get("locks") or {}
    sc = res.get("scorer") or {}
    out = []
    if "scorer" in lk:
        out.append("lock scorer_sha256: registered %s; running census.py sha256 %s; %s"
                   % (lk["scorer"].get("registered") or "open", sc.get("sha256"), lk["scorer"]["reads"]))
    if "kit" in lk:
        out.append("lock kit_version: registered %s; running styxx-ledger %s, vectors_v1.json sha256 %s; %s"
                   % (lk["kit"].get("registered") or "open", sc.get("kit_version"), sc.get("vectors_sha256") or "unread",
                      lk["kit"]["reads"]))
    if "writer" in lk:
        out.append("lock writer: registered %s; the ledger's started entries before d0: %s; %s"
                   % (lk["writer"].get("registered") or "open", "; ".join("seq %s %s" % (x["seq"], x["writer"]) for x in
                                                                       lk["writer"].get("started", [])) or "none",
                      lk["writer"]["reads"]))
    return out


def render_md(res: Dict[str, Any]) -> str:
    L: List[str] = ["# census result", ""]
    L.append("status: %s" % res.get("status"))
    L.append("verdict: %s" % (res.get("verdict") or "none"))
    L.append("now_utc: %s" % res.get("now_utc"))
    L.append("counted by: %s (--runner)" % res.get("runner", "not stated"))
    L.append("prereg: %s sha256 %s" % (res["prereg"]["file"], res["prereg"]["sha256"]))
    L.append("scorer: %s sha256 %s (styxx-ledger %s)" % (res["scorer"]["module"], res["scorer"]["sha256"],
                                                        res["scorer"]["kit_version"]))
    L += _md_locks(res)
    for f in res.get("fetch_failures") or []:
        L.append("did not answer: %s, after %d %s: %s" % (f["what"], f["tries_used"],
                                                        "try" if f["tries_used"] == 1 else "tries", f["failure"]["reason"]))
    if res.get("rehearsal"):
        rh = res["rehearsal"]
        L.append("rehearsal: %s; not fetched: %s; if the checks of (c) that need the shelf's report hold: status %s, "
                 "row %s" % (rh["reads"], ", ".join("%s %s" % (x["what"], x["url"]) for x in rh["not_fetched"]) or "none",
                             rh["status_if_report_holds"], rh["row_if_report_holds"] or "none"))
    if res.get("status") == "refused":
        L += ["", "refused (%s): %s" % (res["refusal"]["code"], res["refusal"]["reason"])]
        return "\n".join(L) + "\n"
    rg = res["registration"]
    L.append("registration: digest of the %d bytes before section 15 %s; entry %s" % (
        rg["bytes_before_section_15"], rg["digest_read"],
        "none" if rg["entry"] is None else "%s commit %s" % (rg["entry"]["url"], rg["entry"]["commit"])))
    lg = res["ledger"]
    L.append("ledger: %s (registered %s; %s), %d bytes, sha256 %s, protocol %s, %d entries, head %s" % (
        lg["source"], lg["registered_url"], lg["bound"], lg["bytes"], lg["sha256"], lg["protocol"], lg["entries"],
        lg["head"]))
    w = res["window"]
    L.append("window: %s to %s (%s), %d days; scoring date %s" % (w["d0"] or "open", w["close"] or "open", w["anchor_tz"],
                                                                   w["length_days"], w["scoring_date_utc"] or "open"))
    L += ["", "## result", "", "| metric | count |", "|---|---|"]
    for k in METRICS:
        L.append("| %s | %s |" % (k, "unmeasured" if res["result"][k] is None else res["result"][k]))
    if res["result"].get("chain_problems_unmeasured"):
        L.append("| chain_problems components unmeasured | %s |" % ", ".join(res["result"]["chain_problems_unmeasured"]))
    L += ["", "## gates", "", "| gate | count | denominator | bar | status |", "|---|---|---|---|---|"]
    for r in res["gates"]["rows"]:
        L.append("| %s | %s | %s | %s | %s |" % (r["gate"], "unmeasured" if r["count"] is None else r["count"],
                                                 "-" if r["denominator"] is None else r["denominator"], r["bar"], r["status"]))
    L += ["", "## lines by cell", "", "| cell | lines | delivery lines | by kind |", "|---|---|---|---|"]
    for c, x in res["lines"]["cells"].items():
        L.append("| %s | %d | %d | %s |" % (c, x["lines"], x["delivery_lines"],
                                            ", ".join("%s %d" % kv for kv in x["by_kind"].items()) or "-"))
    s = res["sends"]
    L += ["", "deliveries in the window: %d; in the population: %d; to other destinations: %d" % (
        s["delivery_lines_in_window"], s["in_population"], s["outside_destination"])]
    a = res["anchors"]
    aw = a["window"]
    L.append("anchors (%s; the place %s): %d texts, %d holding, %d unparsed, %d mismatched; window: %d of %d days with "
             "lines anchored, missing %s; %d lines after the last holding anchor" % (
                 a.get("source"), a["place_judged"], a.get("texts", 0), a["holding"], a["unparsed"], a["mismatched"],
                 aw["anchored_days_with_lines"], aw["days_with_lines"], ", ".join(aw["missing_days"]) or "none",
                 a["lines_after_last_anchor"]))
    if res.get("numerals"):
        n = res["numerals"]
        L.append("numerals (%s): Nn %d, Nb %d, Nu %d over %d of %d population lines carrying the field" % (
            n["field"], n["Nn"], n["Nb"], n["Nu"], n["lines_carrying"], n["of_population"]))
    c = res["census"]
    if c.get("unmatched") is not None:
        L.append("census: E %d, exact %d, normalised %d, native %d, unmatched %d, missing_from_export %d of %d" % (
            c["E"], c["exact"], c["normalised"], c["native"], c["unmatched"], c["missing_from_export"],
            res["result"]["n_deliveries"]))
        i = c["instrument"]
        L.append("instrument: %d of %d planted misses read; %d not built" % (i["read"], i["built"], i["unbuilt"]))
    else:
        L.append("census: not run (%s)" % (c.get("why_not_run") or c.get("why_not_matched")))
    L += ["", "## sentences", ""] + ["> %s" % x for x in res["sentences"]]
    return "\n".join(L) + "\n"


def _write(out: Path, res: Dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    jb = _dump(res)
    mb = render_md(res).encode("utf-8")
    for name, b in (("RESULT.json", jb), ("RESULT.md", mb)):
        p = out / name
        tmp = out / (name + ".tmp")
        tmp.write_bytes(b)
        os.replace(tmp, p)
        if p.read_bytes() != b:
            raise OSError("write did not land: %s" % p)
