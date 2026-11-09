"""census.py: the census scorer (THE_PLAN 3d, the second half). reads a filled PREREG_census and a published ledger
and writes RESULT.json and RESULT.md: the result dict of the template's section 5, the gate rows of section 6, the
instrument check of section 7, and the section-10 sentence the counts select.

    score(prereg_path, ledger_url_or_path, out_dir, now_utc, export=None, anchors=None, withheld=None, js=True,
          anchor_place=None, tries=3, interval_s=3600, sleep=None)
    digests(prereg_path)   the registration digest and the gates digest, and the gates block's assignment walk

what it does, in order:

1. reads the prereg. any double-brace placeholder left anywhere is a refusal. the placeholder table is read in the
   filled form the template's "how to fill" section gives: `| name = `value` | ... |`; a value ending in a
   parenthesis opened by " (" carries a comment, which is cut. a value starting `[builder-set: open]` is open (the
   worked example's mark): with `d0` open nothing is counted; with `d0` filled every open value is a refusal.
2. reads the dated entries under `## 15.`: the registration (`registered: <url> commit <40 hex> registration_sha256
   <64 hex>`), the shelf read (`shelf read: <url> sha256 <64 hex> at <utc>`) and the signature line. the registration
   digest is the sha256 of the file's bytes before the line that starts `## 15.`; the scorer recomputes it and refuses
   on a mismatch, so a bar edited after the registration cannot be scored. the gates digest is the sha256 of the
   gates block's bytes between its fences; a mismatch with `gates_sha256` is a refusal.
3. fetches the ledger: `ledger_url` (three tries an hour apart by default), or a local copy whose sha256 must equal
   the url's bytes fetched in the same run. any other source is a refusal. a url that does not answer after the tries
   is the `unreachable` component of chain_problems, not a refusal.
4. re-derives it with this package's verifier (v1, or v0 through v0.py when the header names v0). problem records
   are the `verifier_problems` component of chain_problems and walk to the BROKEN row. with node and the kit's js cli
   beside the package, the javascript reference implementation re-derives the same bytes; the two must agree on line
   count and head. an unmeasured component (no js leg; open v0 kinds) leaves G_C unmeasured when nothing else is
   wrong, and the row is UNDECIDED.
5. counts: lines by kind per cell (pre-window / window / after, by each line's `day`), deliveries by population,
   posted anchors per window day, delivery lines on days with no holding posted anchor, numerals, and, given an
   export, matched / unledgered deliveries, one published line per exported message at most.
6. the instrument check: the census matching re-run on copies of the export with planted misses (a message no line
   carries, a duplicate of a ledgered text, an edited text, a last-day message at 23:59:59, one line removed); each
   must raise the unledgered count.
7. evaluates the gates block against the lab-set bars, walks its rows, selects the sentence.

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
NORMALISATION_RULES = ("none", "strip", "nfc", "nfc+strip", "crlf-to-lf", "crlf-to-lf+strip")

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


def _fetch_tries(src: str, tries: int, interval_s: float, sleep: Callable[[float], None]
                 ) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """(bytes | None, meta with tries_used and the last failure). a local path is read once."""
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
            sleep(interval_s)
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
    closing it) is kept."""
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
    cut = {k: (None if _is_open(v) else _cut_comment(v)) for k, v in values.items()}
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


def score(prereg_path, ledger_url_or_path: Optional[str], out_dir, now_utc: str, export: Optional[str] = None,
          anchors: Optional[str] = None, withheld: Optional[str] = None, js: bool = True,
          anchor_place: Optional[str] = None, tries: int = TRIES, interval_s: float = INTERVAL_S,
          sleep: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
    """score one census; writes RESULT.json and RESULT.md under out_dir and returns the dict written.
    anchor_place: None (not judged in this run), "holds", or "fails: <why>" (every day prints unanchored)."""
    out = Path(out_dir)
    pre_bytes = Path(prereg_path).read_bytes()
    res: Dict[str, Any] = {
        "schema": RESULT_SCHEMA, "now_utc": now_utc,
        "prereg": {"file": Path(prereg_path).name, "sha256": _sha(pre_bytes), "bytes": len(pre_bytes)},
        "scorer": {"module": "styxx_ledger.census", "sha256": _sha(Path(__file__).read_bytes()), "kit_version": __version__},
    }
    try:
        body = _score(pre_bytes, ledger_url_or_path, now_utc, export, anchors, withheld, js, anchor_place,
                      tries, interval_s, sleep or time.sleep)
        res.update(body)
    except Refused as e:
        res.update({"status": "refused", "refusal": {"code": e.code, "reason": e.reason}, "verdict": None,
                    "sentences": ["refused: %s" % e.reason]})
        if getattr(e, "partial", None):
            res.update(e.partial)
    _write(out, res)
    return res


def _score(pre_bytes: bytes, src: Optional[str], now_s: str, export: Optional[str], anchors_src: Optional[str],
           withheld_src: Optional[str], js: bool, anchor_place: Optional[str], tries: int, interval_s: float,
           sleep: Callable[[float], None]) -> Dict[str, Any]:
    now = _utc(now_s)
    if now is None:
        raise Refused("now", "now_utc is not YYYY-MM-DDTHH:MM:SSZ: %r" % now_s)
    if anchor_place is not None and anchor_place != "holds" and not anchor_place.startswith("fails: "):
        raise Refused("anchor_place", "anchor_place is None, 'holds' or 'fails: <why>'")
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
        if not _is_url(v["ledger_url"]):
            raise Refused("ledger_url", "ledger_url is not an https url: %r" % v["ledger_url"])
        if s15["registered"] is not None:
            url, commit, sha = s15["registered"]
            registration["entry"] = {"url": url, "commit": commit, "registration_sha256": sha}
            if sha != reg_read:
                raise Refused("registration_mismatch", "the bytes before section 15 hash to %s; the registration entry "
                              "names %s. a bar, value or rule edited after the registration is not scored%s"
                              % (reg_read, sha, " (the file carries crlf line ends; the digest is over the committed lf bytes)"
                                 if b"\r\n" in pre_bytes else ""))
    norm, norm_name = _normaliser(v["normalisation_rule"])
    natives = _native_list(None if _is_open(pr["values"]["native_strings"]) else pr["values"]["native_strings"])
    gates_doc, gates_src, gates_sha = _gates(pr["gates_block"], min_del)
    if d0 is not None and gates_sha != v["gates_sha256"]:
        raise Refused("gates_sha256", "the gates block's bytes between the fences hash to %s; gates_sha256 is %s"
                      % (gates_sha, v["gates_sha256"]))

    # ---- the ledger, bound to ledger_url
    reg_url = v["ledger_url"] if _is_url(v["ledger_url"]) else None
    if src is None:
        if reg_url is None:
            raise Refused("ledger_url", "no --ledger given and ledger_url is not an https url")
        src = reg_url
    if _is_url(src) and src != reg_url:
        raise Refused("ledger_not_registered", "--ledger %s is not the registered ledger_url %s" % (src, reg_url))
    unreachable = 0
    raw: Optional[bytes]
    if _is_url(src):
        raw, meta = _fetch_tries(src, tries, interval_s, sleep)
        bound = "the bytes at ledger_url, fetched in this run"
        url_meta = meta
    else:
        raw, meta = _fetch_tries(src, 1, 0, sleep)
        if raw is None:
            raise Refused("unreadable", meta["failure"]["reason"])
        if reg_url is None:
            bound = "not bound: ledger_url is open (an illustration)"
            url_meta = None
        else:
            ub, url_meta = _fetch_tries(reg_url, tries, interval_s, sleep)
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
        wb, wm = _fetch_tries(wsrc, tries, interval_s, sleep)
        if wb is None:
            ledger["withheld"] = {"source": wm["source"], "failure": wm["failure"],
                                  "read": "the withheld list did not answer; the chain is verified without it"}
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
        ab, am = _fetch_tries(posted_src, tries, interval_s, sleep)
        if ab is None:
            anchors_info.update({"source": "posted texts from %s: did not answer; every day reads unanchored" % am["source"],
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
    if export and hfield is not None and close is not None:
        eb, em = _fetch_once(export)
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
        census["why_not_run"] = "no export committed with the result"
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
        opening["c"] = _shelf(s15["shelf"], v, r, wh, tz, d0_at, tries, interval_s, sleep, proto)
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

    body = {
        "status": status, "verdict": verdict,
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
    body["now_utc"] = now_s
    body["sentences"] = _sentences(body, v)
    return body


def _shelf(entry, v, r, wh, tz, d0_at, tries, interval_s, sleep, proto) -> Dict[str, Any]:
    """opening condition (c): the shelf's report of the outside ledger."""
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
    checks: Dict[str, bool] = {}
    rb, rm = _fetch_tries(url, tries, interval_s, sleep)
    checks["report_answers"] = rb is not None
    checks["report_sha256"] = rb is not None and _sha(rb) == sha
    body = rb.decode("utf-8", "replace") if rb is not None else ""
    ea = v["earliest_anchor"] or ""
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
    return {"held": held, "verified": True,
            "evidence": stated + "; " + ", ".join("%s %s" % (k, "ok" if x else "FAILS") for k, x in checks.items())}


# --------------------------------------------------------------------------------------------- sentences

def _s(v: Dict[str, Optional[str]], k: str) -> str:
    return v[k] if v[k] is not None else "[open]"


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
        s += (" this is one operator's ledger counted by the lab under a frozen rule: custody of what was delivered, not "
              "that any message is true, and nothing in it is signed.")
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
        why = ("the lines carry no hash of the delivered text" if v["sent_hash_field"] in (None, "none")
               else "no export of %s for the window was committed" % _s(v, "public_destinations"))
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


def render_md(res: Dict[str, Any]) -> str:
    L: List[str] = ["# census result", ""]
    L.append("status: %s" % res.get("status"))
    L.append("verdict: %s" % (res.get("verdict") or "none"))
    L.append("now_utc: %s" % res.get("now_utc"))
    L.append("prereg: %s sha256 %s" % (res["prereg"]["file"], res["prereg"]["sha256"]))
    L.append("scorer: %s sha256 %s (styxx-ledger %s)" % (res["scorer"]["module"], res["scorer"]["sha256"],
                                                        res["scorer"]["kit_version"]))
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
