"""verify.py: what a stranger checks of a v1 ledger (sections 4, 5, 6). Port of the exhibit's verify.js API:
verify_bytes, check_anchor, coverage. No network; nothing here writes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .chain import _is_int, as_seq, check_chain, head_of, read_bytes, sha256_hex, withheld_map


def verify_bytes(raw: bytes, withheld: Optional[List[dict]] = None) -> Dict[str, Any]:
    """{header, entries, problems, bridged, head, file_sha256, ok}. A log with no problem re-derives."""
    header, entries, problems = read_bytes(raw)
    chain, bridged = check_chain(header, entries, withheld)
    allp = problems + chain
    return {"header": header, "entries": entries, "problems": allp, "bridged": bridged,
            "head": head_of(header, entries), "file_sha256": sha256_hex(raw), "ok": not allp}


def check_anchor(entries: List[dict], a: Dict[str, Any], withheld: Optional[List[dict]] = None,
                 header: Optional[dict] = None) -> Dict[str, Any]:
    """A posted anchor ({agent, date, head, seq}, as parse_anchor_text gives it) against the entries: the entry
    at seq carries that head (or the withheld list names it); no entry of that day sits after seq; the ledger's
    own anchor entry for that date, if any, agrees; and, given the header, the text's agent is the header's."""
    wm = withheld_map(withheld)
    by_seq = None
    after = 0
    own = None
    for it in entries:
        e = it["entry"]
        if e.get("seq") == a["seq"] and _is_int(e.get("seq")):
            by_seq = e
        if e.get("day") == a["date"] and _is_int(e.get("seq")) and e["seq"] > a["seq"]:
            after += 1
        if e.get("kind") == "anchor" and e.get("anchor_date") == a["date"]:
            own = e
    via_withheld = by_seq is None and a["seq"] in wm
    in_chain = (wm[a["seq"]] == a["head"]) if via_withheld else (by_seq is not None and by_seq.get("entry_id") == a["head"])
    agent_ok = True if header is None else (isinstance(header, dict) and header.get("agent") == a.get("agent"))
    out = {
        "agent": a.get("agent"), "date": a["date"], "seq": a["seq"], "head": a["head"],
        "agent_matches": agent_ok, "in_chain": in_chain, "via_withheld": via_withheld,
        "line_at_seq": ({"kind": by_seq.get("kind"), "day": by_seq.get("day"), "timestamp": by_seq.get("timestamp")}
                        if by_seq is not None else ({"withheld": True} if via_withheld else None)),
        "day_lines_after": after,
        "ledger_anchor_line": ({"seq": own.get("seq"),
                                "agrees": own.get("anchor_head") == a["head"] and own.get("anchor_head_seq") == a["seq"],
                                "late": own.get("late") is True} if own is not None else None),
    }
    out["ok"] = bool(agent_ok and in_chain and after == 0 and (own is None or out["ledger_anchor_line"]["agrees"]))
    return out


def coverage(entries: List[dict], withheld: Optional[List[dict]], anchor_seqs: Optional[List[int]]) -> Dict[str, Any]:
    """What the posted heads pin for the reader: a published entry is pinned when no withheld seq sits after it
    and at or before the first anchor head at or after it (section 6)."""
    ws = [as_seq(w.get("seq")) for w in (withheld or []) if isinstance(w, dict)]
    ws = [w for w in ws if w is not None]
    as_ = sorted(s for s in (anchor_seqs or []) if _is_int(s))
    last_anchor = as_[-1] if as_ else 0
    pinned = after = 0
    unpinned: List[int] = []
    for it in entries:
        s = it["entry"].get("seq")
        if not _is_int(s):
            continue
        if s > last_anchor:
            after += 1
            continue
        a = next((x for x in as_ if x >= s), None)
        if any(s < w <= a for w in ws):
            unpinned.append(s)
        else:
            pinned += 1
    unpinned.sort()
    ranges: List[List[int]] = []
    for s in unpinned:
        if ranges and ranges[-1][1] == s - 1:
            ranges[-1][1] = s
        else:
            ranges.append([s, s])
    return {"pinned": pinned, "unpinned_by_withholding": len(unpinned), "unpinned_ranges": ranges,
            "after_last_anchor": after, "withheld": len(ws), "last_anchor_seq": last_anchor}
