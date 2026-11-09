"""v0.py: read mode for protocol v0 ledgers (darkflobi.gate/log/v0), the protocol darkflobi's send ledger runs under.

The rules are the exhibit's verify.js (the reference v0 implementation; its 10 vectors are vectors/v0/):

    header        schema "darkflobi.gate/log/v0"; carries schema, created, anchor_tz, certifies (no agent, no kinds)
    entries       schema "darkflobi.gate/entry/v0"
    header_digest sha256( "darkflobi.gate/log/v0" LF JCS(header) )
    anchor text   "gate anchor <YYYY-MM-DD> head <64 hex> seq <n>"  (the fixed word "gate", not an agent)
    kinds         not declared in the header, so no kinds check applies
    day           the timestamp's calendar day in the header's anchor_tz (America/New_York when absent), read as
                  v0 reads it: fractional seconds and a +hh:mm offset accepted, a naive timestamp read as UTC; the day
                  is checked only when the entry carries a timestamp
    no_header     reported only when the file holds entries (an empty v0 file is not a problem in v0)

Everything else is v1's (JCS form, entry_id, prev, seq, bridging on withheld digests, coverage), so the reader,
check_anchor and coverage come from chain.py / verify.py. Problem records carry the v1 codes. Nothing is written.

`detect_protocol(raw)` names a file's protocol from its first object line's schema; `verify_auto` reads either.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .chain import (LOG_SCHEMA, V0_LOG_SCHEMA, _DuplicateKey, _is_int, _no_constants, _no_duplicates, core_of,
                    entry_id_of, sha256_hex, withheld_map)
from .day import zone
from .jcs import MAX_INT, LedgerValueError, depth_exceeds, dump, jcs
from .verify import check_anchor, coverage, verify_bytes

V0_ENTRY_SCHEMA = "darkflobi.gate/entry/v0"
V0_HEADER_DOMAIN = (V0_LOG_SCHEMA + "\n").encode("ascii")
V0_ANCHOR_TZ = "America/New_York"
V0_ANCHOR_WORD = "gate"
V0_ANCHOR_RX = re.compile(r"\Agate anchor ([0-9]{4}-[0-9]{2}-[0-9]{2}) head ([0-9a-f]{64}) seq ([0-9]+)\n?\Z")
V0_TS_RX = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})?\Z")

__all__ = ["V0_ENTRY_SCHEMA", "V0_HEADER_DOMAIN", "V0_ANCHOR_TZ", "header_digest_v0", "local_day_v0",
           "read_bytes_v0", "check_chain_v0", "verify_bytes_v0", "anchor_text_v0", "parse_anchor_text_v0",
           "check_anchor_v0", "detect_protocol", "verify_auto", "parse_anchor_auto", "check_anchor_auto"]


def header_digest_v0(header: Dict[str, Any]) -> str:
    return sha256_hex(V0_HEADER_DOMAIN + jcs(header).encode("utf-8"))


# the characters JavaScript's String.prototype.trim removes (WhiteSpace + LineTerminator)
_JS_WS = ("\t\n\x0b\x0c\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
          "\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")


def local_day_v0(ts: Any, tz: Optional[str] = None) -> str:
    """verify.js localDay, as node's Date.parse reads the v0 form: String(ts).trim(); fractional seconds and a
    +hh:mm offset accepted; a naive time read as UTC; day 29..31 of a shorter month rolls into the next (V8 does);
    24:00:00 is the next midnight. The calendar day in tz. Raises LedgerValueError("timestamp") when unreadable,
    ("anchor_tz") for an unknown zone. One known difference: year 0000 parses in V8 and is unreadable here."""
    if isinstance(ts, str):
        s = ts
    elif ts is None or isinstance(ts, bool):
        s = "null" if ts is None else ("true" if ts else "false")
    else:
        s = str(ts)
    s = s.strip(_JS_WS)
    m = V0_TS_RX.match(s)
    if not m:
        raise LedgerValueError("timestamp", "timestamp unreadable")
    y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
    frac, off = m.group(7), m.group(8)
    ms = int((frac[1:] + "00")[:3]) if frac else 0   # Date.parse keeps milliseconds
    bad = not (1 <= mo <= 12 and 1 <= d <= 31 and mi <= 59 and ss <= 59)
    if hh == 24:
        bad = bad or mi != 0 or ss != 0 or (frac is not None and int(frac[1:]) != 0)
    elif hh > 23:
        bad = True
    if off and off != "Z" and (int(off[1:3]) > 23 or int(off[4:6]) > 59):
        bad = True
    if bad:
        raise LedgerValueError("timestamp", "timestamp unreadable")
    try:
        base = datetime(y, mo, 1, tzinfo=timezone.utc) + timedelta(days=d - 1, hours=hh, minutes=mi, seconds=ss,
                                                                     milliseconds=ms)
        if off and off != "Z":
            sign = 1 if off[0] == "+" else -1
            base -= sign * timedelta(hours=int(off[1:3]), minutes=int(off[4:6]))
        return base.astimezone(zone(tz or V0_ANCHOR_TZ)).strftime("%Y-%m-%d")
    except (OverflowError, ValueError):
        raise LedgerValueError("timestamp", "timestamp unreadable") from None


def read_bytes_v0(raw: bytes) -> Tuple[Optional[dict], List[dict], List[dict]]:
    """(header, entries, problems) under v0's reading rules. Never raises on content."""
    header = None
    entries: List[dict] = []
    problems: List[dict] = []
    if b"\r" in raw:
        problems.append({"line": None, "seq": None, "code": "cr_byte", "problem": "the log holds a CR byte; lines are LF"})
    for i, line in enumerate(raw.split(b"\n"), start=1):
        if not line.strip():
            continue
        if depth_exceeds(line):
            problems.append({"line": i, "seq": None, "code": "unparsable",
                             "problem": "unparsable: containers nested deeper than 32"})
            continue
        try:
            obj = json.loads(line.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
        except _DuplicateKey as e:
            problems.append({"line": i, "seq": None, "code": "duplicate_key", "problem": "a key written twice: %s" % str(e)[:40]})
            continue
        except Exception as e:  # noqa: BLE001
            problems.append({"line": i, "seq": None, "code": "unparsable", "problem": "unparsable: %s" % type(e).__name__})
            continue
        if not isinstance(obj, dict):
            problems.append({"line": i, "seq": None, "code": "not_object", "problem": "not an object"})
            continue
        try:
            canonical = dump(obj).encode("utf-8") == line
        except (TypeError, ValueError, RecursionError):
            canonical = False
        if not canonical:
            problems.append({"line": i, "seq": None, "code": "not_canonical",
                             "problem": "the line's bytes are not the canonical dump of its object"})
        if header is None and not entries and obj.get("schema") == V0_LOG_SCHEMA:
            header = obj
            continue
        entries.append({"line": i, "entry": obj})
    if header is None and entries:
        problems.append({"line": 1, "seq": None, "code": "no_header", "problem": "no header on line 1"})
    return header, entries, problems


def check_chain_v0(header: Optional[dict], entries: List[dict],
                   withheld: Optional[List[dict]] = None) -> Tuple[List[dict], List[int]]:
    """(problems, bridged): verify.js checkChain, with the v1 codes."""
    bad: List[dict] = []
    bridged: List[int] = []
    if header is None:
        if entries:
            bad.append({"line": 1, "seq": None, "codes": ["no_header"], "problems": ["no header"]})
        return bad, bridged
    wm = withheld_map(withheld)
    tz = header.get("anchor_tz") if isinstance(header.get("anchor_tz"), str) else V0_ANCHOR_TZ
    try:
        prev = header_digest_v0(header)
    except LedgerValueError as err:
        prev = None
        bad.append({"line": 1, "seq": None, "codes": ["not_canonical"], "problems": ["header not canonicalisable: %s" % err]})
    want_seq = 1
    for it in entries:
        e = it["entry"]
        codes: List[str] = []
        texts: List[str] = []

        def add(code: str, text: str) -> None:
            codes.append(code)
            texts.append(text)

        while want_seq in wm and e.get("seq") != want_seq:
            prev = wm[want_seq]
            bridged.append(want_seq)
            want_seq += 1
        core = core_of(e)
        want = None
        try:
            want = entry_id_of(core)
        except LedgerValueError as err:
            add("core_not_canonical", "core not canonicalisable: %s" % err)
        if core.get("schema") != V0_ENTRY_SCHEMA:
            add("schema", "schema is not %s" % V0_ENTRY_SCHEMA)
        if want is not None and e.get("entry_id") != want:
            add("entry_id", "entry_id does not re-derive from the core")
        if e.get("prev") != prev:
            add("prev", "prev does not name the line before")
        s = e.get("seq")
        if not (_is_int(s) and s == want_seq):
            add("seq", "seq is %s, expected %d" % (json.dumps(s), want_seq))
        if "timestamp" in core:
            try:
                if local_day_v0(core.get("timestamp"), tz) != core.get("day"):
                    add("day", "day does not re-derive from timestamp")
            except LedgerValueError:
                add("day", "timestamp unreadable")
        if codes:
            bad.append({"line": it["line"], "seq": s, "codes": codes, "problems": texts})
        prev = e.get("entry_id") if isinstance(e.get("entry_id"), str) else prev
        want_seq = (s if _is_int(s) else want_seq) + 1
    return bad, bridged


def _head_v0(header: Optional[dict], entries: List[dict]) -> Optional[str]:
    if entries:
        h = entries[-1]["entry"].get("entry_id")
        return h if isinstance(h, str) else None
    if header is None:
        return None
    try:
        return header_digest_v0(header)
    except LedgerValueError:
        return None


def verify_bytes_v0(raw: bytes, withheld: Optional[List[dict]] = None) -> Dict[str, Any]:
    """{protocol: "v0", header, entries, problems, bridged, head, file_sha256, ok}."""
    header, entries, problems = read_bytes_v0(raw)
    chain, bridged = check_chain_v0(header, entries, withheld)
    allp = problems + chain
    return {"protocol": "v0", "header": header, "entries": entries, "problems": allp, "bridged": bridged,
            "head": _head_v0(header, entries), "file_sha256": hashlib.sha256(raw).hexdigest(), "ok": not allp}


def anchor_text_v0(date: str, head: str, seq: int) -> str:
    if not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date) or not isinstance(head, str) \
            or not re.fullmatch(r"[0-9a-f]{64}", head) or not _is_int(seq) or seq < 0 or seq > MAX_INT:
        raise LedgerValueError("anchor_form", "anchor fields out of form")
    return "gate anchor %s head %s seq %d" % (date, head, seq)


def parse_anchor_text_v0(text: Any) -> Optional[Dict[str, Any]]:
    """{agent: "gate", date, head, seq} for a text that IS the v0 form (one trailing LF tolerated), else None."""
    if not isinstance(text, str):
        return None
    m = V0_ANCHOR_RX.match(text)
    if not m or len(m.group(3)) > 16 or int(m.group(3)) > MAX_INT:
        return None
    return {"agent": V0_ANCHOR_WORD, "date": m.group(1), "head": m.group(2), "seq": int(m.group(3))}


def check_anchor_v0(entries: List[dict], a: Dict[str, Any], withheld: Optional[List[dict]] = None) -> Dict[str, Any]:
    """verify.js checkAnchor: no agent check (the word is fixed), everything else as v1."""
    return check_anchor(entries, a, withheld, None)


# ----------------------------------------------------------------------------------------------- dispatch

def detect_protocol(raw: bytes) -> Optional[str]:
    """"v1" or "v0" from the first non-blank line's schema, or None when it names neither (or does not parse)."""
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        if depth_exceeds(line):
            return None
        try:
            obj = json.loads(line.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        s = obj.get("schema") if isinstance(obj, dict) else None
        return "v1" if s == LOG_SCHEMA else ("v0" if s == V0_LOG_SCHEMA else None)
    return None


def verify_auto(raw: bytes, withheld: Optional[List[dict]] = None, protocol: str = "auto") -> Dict[str, Any]:
    """verify_bytes or verify_bytes_v0 by the header's schema (protocol "auto"), or the one named; the result
    carries `protocol`. A file naming neither schema is read as v1 (which reports no_header)."""
    p = detect_protocol(raw) if protocol == "auto" else protocol
    if p == "v0":
        return verify_bytes_v0(raw, withheld)
    r = verify_bytes(raw, withheld)
    r["protocol"] = "v1"
    return r


def parse_anchor_auto(text: Any, protocol: str) -> Optional[Dict[str, Any]]:
    from .chain import parse_anchor_text
    return parse_anchor_text_v0(text) if protocol == "v0" else parse_anchor_text(text)


def check_anchor_auto(r: Dict[str, Any], a: Dict[str, Any], withheld: Optional[List[dict]] = None) -> Dict[str, Any]:
    if r.get("protocol") == "v0":
        return check_anchor_v0(r["entries"], a, withheld)
    return check_anchor(r["entries"], a, withheld, r["header"])
