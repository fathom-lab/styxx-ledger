"""chain.py: the chain of protocol v1 (sections 1, 3, 4, 5): header, entry composition, reading, checking, anchor text.

    core(entry)    = every key of the entry except entry_id
    entry_id       = sha256( JCS(core) )                         64 lowercase hex
    header_digest  = sha256( "styxx.ledger/log/v1" LF JCS(header) )
    entry_1.prev   = header_digest; entry_k.prev = entry_{k-1}.entry_id
    entry_k.seq    = entry_{k-1}.seq + 1; entry_1.seq = 1
    head           = the last entry's entry_id, or header_digest when there is no entry

Problem records (what a verifier reports, section 4) carry `line`, `seq` (an int, or None for a reading problem
or a header problem), and either `code` + `problem` (one problem) or `codes` + `problems` (one entry's list). The
codes are the protocol's: cr_byte, unparsable, not_object, not_canonical, no_header, duplicate_key (python reader
only, see section 4), header_kinds; per entry: core_not_canonical, schema, kind_not_declared, entry_id, prev, seq,
day. Write-time refusals raise LedgerValueError with codes: float, int_range, non_ascii_key, lone_surrogate, type,
reserved_field, kind_not_declared, started_writer, anchor_form, header_form, timestamp, anchor_tz.

The math is the gate's ledger.py (W:gate, v0) with the schema strings renamed, the anchor text's fixed word
replaced by the header's agent, and the day read in the header's anchor_tz. Nothing is signed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .day import TIMESTAMP_RX, day_of, late_of, next_day, parse_timestamp, zone
from .jcs import MAX_INT, LedgerValueError, check_value, depth_exceeds, dump, jcs

LOG_SCHEMA = "styxx.ledger/log/v1"
ENTRY_SCHEMA = "styxx.ledger/entry/v1"
V0_LOG_SCHEMA = "darkflobi.gate/log/v0"
HEADER_DOMAIN = (LOG_SCHEMA + "\n").encode("ascii")
HEADER_KEYS = ("agent", "anchor_tz", "certifies", "created", "kinds", "schema")
REQUIRED_KINDS = ("anchor", "started")
RESERVED_FIELDS = ("schema", "seq", "prev", "kind", "timestamp", "day", "entry_id")
ANCHOR_FIELDS = ("anchor_date", "anchor_head", "anchor_head_seq", "anchor_text_sha256", "late")
# every form regex is anchored \A...\Z and spells its digits [0-9]: `$` also matches before a trailing LF, and `\d`
# matches non-ascii digits (review finding 1); with \A...\Z, `.match` is a full match
AGENT_RX = re.compile(r"\A[a-z0-9_-]{1,32}\Z")
KIND_RX = re.compile(r"\A[a-z][a-z0-9_]{0,31}\Z")
DATE_RX = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
HEX64_RX = re.compile(r"\A[0-9a-f]{64}\Z")
ANCHOR_RX = re.compile(r"\A([a-z0-9_-]{1,32}) anchor ([0-9]{4}-[0-9]{2}-[0-9]{2}) head ([0-9a-f]{64}) seq (0|[1-9][0-9]*)\n?\Z")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def as_seq(v: Any) -> Optional[int]:
    """A withheld list's seq as an integer: an int, or an integral json number (10.0 reads as 10, as it does in
    javascript), with |n| <= 2^53; anything else is None (section 6)."""
    if _is_int(v):
        return v if abs(v) <= MAX_INT else None
    if isinstance(v, float) and v.is_integer() and abs(v) <= MAX_INT:
        return int(v)
    return None


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def core_of(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "entry_id"}


def entry_id_of(core: Dict[str, Any]) -> str:
    return sha256_hex(jcs(core).encode("utf-8"))


def header_digest(header: Dict[str, Any]) -> str:
    """Domain-separated, so a header never passes as an entry."""
    return sha256_hex(HEADER_DOMAIN + jcs(header).encode("utf-8"))


# ------------------------------------------------------------------------------------------ writing side

def check_header(header: Any) -> None:
    """Refuse (code header_form, or anchor_tz) a header a v1 writer may not write."""
    def bad(msg: str) -> None:
        raise LedgerValueError("header_form", msg)
    if not isinstance(header, dict):
        bad("header is not an object")
    extra = sorted(set(header) - set(HEADER_KEYS))
    missing = sorted(set(HEADER_KEYS) - set(header))
    if extra or missing:
        bad("header keys: missing %s, not allowed %s" % (missing, extra))
    if header["schema"] != LOG_SCHEMA:
        bad("header schema is not %s" % LOG_SCHEMA)
    if not isinstance(header["created"], str) or not TIMESTAMP_RX.match(header["created"]):
        bad("created is not YYYY-MM-DDTHH:MM:SSZ")
    parse_timestamp(header["created"])
    zone(header["anchor_tz"])
    if not isinstance(header["agent"], str) or not AGENT_RX.match(header["agent"]):
        bad("agent is not 1-32 chars of [a-z0-9_-]")
    c = header["certifies"]
    if not isinstance(c, str) or not c.strip() or "\n" in c or len(c) > 500:
        bad("certifies is not one sentence (a non-empty line of at most 500 chars)")
    k = header["kinds"]
    if not isinstance(k, list) or not all(isinstance(x, str) and KIND_RX.match(x) for x in k):
        bad("kinds is not a list of kind names ([a-z][a-z0-9_]{0,31})")
    if k != sorted(set(k)):
        bad("kinds is not sorted and unique")
    if not all(r in k for r in REQUIRED_KINDS):
        bad("kinds must contain anchor and started")
    check_value(header)


def make_header(created: str, anchor_tz: str, agent: str, certifies: str, kinds: List[str]) -> Dict[str, Any]:
    header = {"schema": LOG_SCHEMA, "created": created, "anchor_tz": anchor_tz, "agent": agent,
              "certifies": certifies, "kinds": sorted(set(kinds))}
    check_header(header)
    return header


def build_entry(header: Dict[str, Any], seq: int, prev: str, kind: str, timestamp: str,
                fields: Dict[str, Any]) -> Dict[str, Any]:
    """The entry a writer appends: chain keys, day from the header's anchor_tz, the kind's fields, entry_id.
    Pure: no file is touched. Refusal order: fields shape, reserved field, kind, started/anchor shape, seq/prev
    form, timestamp, zone, an anchor's `late` against section 5's rule, value types."""
    if not isinstance(fields, dict):
        raise LedgerValueError("type", "fields must be an object")
    for k in fields:
        if not isinstance(k, str) or k in RESERVED_FIELDS or k.startswith("_"):
            raise LedgerValueError("reserved_field", "field %r is the ledger's to set" % (k,))
    kinds = header.get("kinds") if isinstance(header, dict) else None
    if not isinstance(kind, str) or not isinstance(kinds, list) or kind not in kinds:
        raise LedgerValueError("kind_not_declared", "kind %r is not in header.kinds" % (kind,))
    if kind == "started":
        w = fields.get("writer")
        if not (isinstance(w, dict) and isinstance(w.get("name"), str) and w.get("name")
                and isinstance(w.get("version"), str) and w.get("version")):
            raise LedgerValueError("started_writer", "a started entry carries writer {name, version}")
    if kind == "anchor":
        missing = [f for f in ANCHOR_FIELDS if f not in fields]
        if missing or not DATE_RX.match(str(fields.get("anchor_date"))) \
                or not HEX64_RX.match(str(fields.get("anchor_head"))) \
                or not _is_int(fields.get("anchor_head_seq")) \
                or not HEX64_RX.match(str(fields.get("anchor_text_sha256"))) \
                or not isinstance(fields.get("late"), bool):
            raise LedgerValueError("anchor_form", "an anchor entry carries %s in form" % ", ".join(ANCHOR_FIELDS))
    if not _is_int(seq) or seq < 1:
        raise LedgerValueError("type", "seq must be an integer >= 1")
    if not isinstance(prev, str) or not HEX64_RX.match(prev):
        raise LedgerValueError("type", "prev must be 64 lowercase hex")
    day = day_of(timestamp, header.get("anchor_tz"))
    if kind == "anchor" and fields["late"] != late_of(fields["anchor_date"], timestamp, header.get("anchor_tz")):
        raise LedgerValueError("anchor_form", "late is %s by section 5's rule for an anchor of %s written at %s"
                               % (str(not fields["late"]).lower(), fields["anchor_date"], timestamp))
    core: Dict[str, Any] = {"schema": ENTRY_SCHEMA, "seq": seq, "prev": prev, "kind": kind,
                            "timestamp": timestamp, "day": day}
    core.update(fields)
    entry = dict(core)
    entry["entry_id"] = entry_id_of(core)
    return entry


# ----------------------------------------------------------------------------------------------- anchor

def anchor_text(agent: str, date: str, head: str, seq: int) -> str:
    """`<agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>`, byte for byte (section 5)."""
    if not isinstance(agent, str) or not AGENT_RX.match(agent) or not isinstance(date, str) \
            or not DATE_RX.match(date) or not isinstance(head, str) or not HEX64_RX.match(head) \
            or not _is_int(seq) or seq < 0 or seq > MAX_INT:
        raise LedgerValueError("anchor_form", "anchor fields out of form")
    return "%s anchor %s head %s seq %d" % (agent, date, head, seq)


def parse_anchor_text(text: Any) -> Optional[Dict[str, Any]]:
    """The fields of a text that IS the anchor form (one trailing LF tolerated; seq at most 2^53), else None."""
    if not isinstance(text, str):
        return None
    m = ANCHOR_RX.match(text)
    if not m or len(m.group(4)) > 16 or int(m.group(4)) > MAX_INT:
        return None
    return {"agent": m.group(1), "date": m.group(2), "head": m.group(3), "seq": int(m.group(4))}


# ---------------------------------------------------------------------------------------------- reading

class _DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs):
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise _DuplicateKey(k)
        out[k] = v
    return out


def _no_constants(name: str):
    raise ValueError("JSON has no %s" % name)


def read_bytes(raw: bytes) -> Tuple[Optional[dict], List[dict], List[dict]]:
    """(header, entries, problems). entries are [{"line": n, "entry": obj}]. Never raises on content."""
    header = None
    entries: List[dict] = []
    problems: List[dict] = []
    if b"\r" in raw:
        problems.append({"line": None, "seq": None, "code": "cr_byte", "problem": "the log holds a CR byte; lines are LF"})
    first_obj_schema = None
    for i, line in enumerate(raw.split(b"\n"), start=1):
        if not line.strip():
            continue
        if depth_exceeds(line):
            problems.append({"line": i, "seq": None, "code": "unparsable",
                             "problem": "unparsable: containers nested deeper than 32 (section 2)"})
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
        if first_obj_schema is None:
            first_obj_schema = obj.get("schema")
        if header is None and not entries and obj.get("schema") == LOG_SCHEMA:
            header = obj
            continue
        entries.append({"line": i, "entry": obj})
    if header is None:
        why = "no header on line 1" if entries else "no header: the file holds no v1 header line"
        if first_obj_schema == V0_LOG_SCHEMA:
            why += " (line 1 is a protocol v0 header; this verifier reads v1 only)"
        problems.append({"line": 1, "seq": None, "code": "no_header", "problem": why})
    return header, entries, problems


def read_log(path) -> Tuple[Optional[dict], List[dict], List[dict]]:
    p = Path(path)
    if not p.exists():
        return None, [], []
    return read_bytes(p.read_bytes())


def withheld_map(withheld: Optional[List[dict]]) -> Dict[int, str]:
    m: Dict[int, str] = {}
    for w in withheld or []:
        s = as_seq(w.get("seq")) if isinstance(w, dict) else None
        if s is not None and isinstance(w.get("entry_id"), str):
            m[s] = w["entry_id"]
    return m


def declared_kinds(header: Optional[dict]) -> List[str]:
    k = header.get("kinds") if isinstance(header, dict) else None
    return [x for x in k if isinstance(x, str)] if isinstance(k, list) else []


def check_chain(header: Optional[dict], entries: List[dict],
                withheld: Optional[List[dict]] = None) -> Tuple[List[dict], List[int]]:
    """(problems, bridged). A withheld seq is bridged on its published digest (section 6): when the next entry
    present is not that seq, `prev` advances to the withheld digest and the expected seq moves past it."""
    bad: List[dict] = []
    bridged: List[int] = []
    if header is None:
        bad.append({"line": 1, "seq": None, "codes": ["no_header"], "problems": ["no header"]})
        return bad, bridged
    kinds = declared_kinds(header)
    if not all(r in kinds for r in REQUIRED_KINDS):
        bad.append({"line": 1, "seq": None, "codes": ["header_kinds"],
                    "problems": ["header.kinds missing anchor or started"]})
    wm = withheld_map(withheld)
    tz = header.get("anchor_tz")
    try:
        prev = header_digest(header)
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
        if core.get("schema") != ENTRY_SCHEMA:
            add("schema", "schema is not %s" % ENTRY_SCHEMA)
        if not isinstance(core.get("kind"), str) or core.get("kind") not in kinds:
            add("kind_not_declared", "kind %r not in header.kinds" % (core.get("kind"),))
        if want is not None and e.get("entry_id") != want:
            add("entry_id", "entry_id does not re-derive from the core")
        if e.get("prev") != prev:
            add("prev", "prev does not name the line before")
        s = e.get("seq")
        if not (_is_int(s) and s == want_seq):
            add("seq", "seq is %r, expected %d" % (s, want_seq))
        try:
            if day_of(core.get("timestamp"), tz) != core.get("day"):
                add("day", "day does not re-derive from timestamp")
        except LedgerValueError as err:
            add("day", "day does not re-derive: %s" % err)
        if codes:
            bad.append({"line": it["line"], "seq": s, "codes": codes, "problems": texts})
        prev = e.get("entry_id") if isinstance(e.get("entry_id"), str) else prev
        want_seq = (s if _is_int(s) else want_seq) + 1
    return bad, bridged


def head_of(header: Optional[dict], entries: List[dict]) -> Optional[str]:
    if entries:
        h = entries[-1]["entry"].get("entry_id")
        return h if isinstance(h, str) else None
    if header is None:
        return None
    try:
        return header_digest(header)
    except LedgerValueError:
        return None
