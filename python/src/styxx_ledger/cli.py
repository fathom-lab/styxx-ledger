"""cli.py: styxx-ledger init | append | verify | anchor-text | head.

exit codes: 0 done / re-derives; 1 refused, or the log does not re-derive, or an anchor does not hold;
2 usage or i/o error. machine output with --json; the anchor text alone on stdout for anchor-text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from ._version import __version__
from .chain import parse_anchor_text
from .jcs import LedgerValueError
from .verify import check_anchor, coverage, verify_bytes
from .writer import Ledger, LedgerBroken, LedgerError


class _Usage(Exception):
    pass


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise _Usage("a key written twice in the fields: %r" % k)
        out[k] = v
    return out


def _load_json(text: str, what: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_no_dupes)
    except _Usage:
        raise
    except RecursionError:
        raise LedgerValueError("depth", "%s nests containers deeper than this python can read (the limit is 32)" % what) from None
    except ValueError as e:
        raise _Usage("%s is not json: %s" % (what, e)) from None


def _read_text(p: str, what: str) -> str:
    try:
        return sys.stdin.read() if p == "-" else Path(p).read_text(encoding="utf-8")
    except OSError as e:
        raise _Usage("cannot read %s %s: %s" % (what, p, e)) from None


def _load_withheld(p: Optional[str]) -> List[dict]:
    if not p:
        return []
    doc = _load_json(_read_text(p, "withheld file"), "the withheld file")
    if isinstance(doc, dict):
        doc = doc.get("withheld", [])
    if not isinstance(doc, list):
        raise _Usage("the withheld file is a list of {seq, entry_id, reason} (or {\"withheld\": [...]})")
    return doc


def _codes(p: dict) -> str:
    return ",".join(p.get("codes") or [p.get("code") or "?"])


def _say(s: str = "") -> None:
    print(s)


# ------------------------------------------------------------------------------------------------ commands

def cmd_init(a) -> int:
    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()] if a.kinds else []
    led = Ledger.create(a.log, agent=a.agent, anchor_tz=a.tz, certifies=a.certifies, kinds=kinds, created=a.created)
    hdr = led.header
    if a.no_started:
        _say("created %s: header only, kinds %s" % (a.log, ",".join(hdr["kinds"])))
        return 0
    e = led.start(timestamp=a.timestamp)
    _say("created %s: header + started (seq 1), kinds %s" % (a.log, ",".join(hdr["kinds"])))
    _say("head %s" % e["entry_id"])
    return 0


def cmd_append(a) -> int:
    if a.fields is not None and a.fields_file is not None:
        raise _Usage("give --fields or --fields-file, not both")
    if a.fields_file is not None:
        fields = _load_json(_read_text(a.fields_file, "fields file"), "the fields file")
    elif a.fields == "-":
        fields = _load_json(_read_text("-", "fields"), "the fields on stdin")
    elif a.fields is not None:
        fields = _load_json(a.fields, "--fields")
    else:
        fields = {}
    if not isinstance(fields, dict):
        raise _Usage("fields are a json object")
    e = Ledger(a.log).append(a.kind, fields, timestamp=a.timestamp)
    if a.json:
        print(json.dumps({"seq": e["seq"], "entry_id": e["entry_id"], "day": e["day"]}))
    else:
        _say("appended seq %d kind %s day %s" % (e["seq"], e["kind"], e["day"]))
        _say("head %s" % e["entry_id"])
    return 0


def cmd_verify(a) -> int:
    try:
        raw = Path(a.log).read_bytes()
    except OSError as e:
        raise _Usage("cannot read %s: %s" % (a.log, e)) from None
    withheld = _load_withheld(a.withheld)
    texts = list(a.anchor or [])
    if a.anchors_file:
        texts += [ln for ln in _read_text(a.anchors_file, "anchors file").split("\n") if ln.strip()]
    r = verify_bytes(raw, withheld=withheld)
    anchors = []
    for t in texts:
        p = parse_anchor_text(t)
        if p is None:
            anchors.append({"text": t, "ok": False, "parsed": False})
        else:
            c = check_anchor(r["entries"], p, withheld, r["header"])
            c["text"], c["parsed"] = t, True
            anchors.append(c)
    cov = None
    if texts or withheld:
        seqs = [x["seq"] for x in anchors if x.get("parsed") and x.get("ok")]
        cov = coverage(r["entries"], withheld, seqs)
    ok = r["ok"] and all(x["ok"] for x in anchors)
    if a.json:
        print(json.dumps({"ok": ok, "rederives": r["ok"], "entries": len(r["entries"]), "head": r["head"],
                          "file_sha256": r["file_sha256"], "bridged": r["bridged"], "problems": r["problems"],
                          "anchors": anchors, "coverage": cov}, ensure_ascii=True, sort_keys=True))
        return 0 if ok else 1
    n = len(r["entries"])
    if r["ok"]:
        _say("re-derives: %d entr%s, head %s" % (n, "y" if n == 1 else "ies", r["head"]))
        if r["bridged"]:
            _say("bridged on withheld digests (the publisher's word): seq %s" % ",".join(str(s) for s in r["bridged"]))
    else:
        _say("does not re-derive: %d problem record(s) over %d entr%s" % (len(r["problems"]), n, "y" if n == 1 else "ies"))
        for p in r["problems"][: a.max_problems]:
            text = p.get("problem") or "; ".join(p.get("problems") or [])
            _say("  line %s seq %s %s: %s" % (p.get("line"), p.get("seq"), _codes(p), text))
        if len(r["problems"]) > a.max_problems:
            _say("  ... %d more (--max-problems, or --json)" % (len(r["problems"]) - a.max_problems))
    for x in anchors:
        if not x.get("parsed"):
            _say("anchor not in the form '<agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>': %r" % x["text"][:120])
            continue
        why = []
        if not x["agent_matches"]:
            why.append("agent is not the header's")
        if not x["in_chain"]:
            why.append("the entry at seq %d does not carry that head" % x["seq"])
        if x["day_lines_after"]:
            why.append("%d entr%s of that day after seq %d" % (x["day_lines_after"], "y" if x["day_lines_after"] == 1 else "ies", x["seq"]))
        own = x["ledger_anchor_line"]
        if own is not None and not own["agrees"]:
            why.append("the ledger's own anchor entry (seq %s) disagrees" % own["seq"])
        _say("anchor %s seq %d: %s" % (x["date"], x["seq"], "holds" if x["ok"] else "does not hold (" + "; ".join(why) + ")"))
    if cov is not None:
        _say("coverage: %d of %d entries pinned by holding anchors; %d unpinned by withholding %s; %d after the last "
             "anchor; %d withheld" % (cov["pinned"], n, cov["unpinned_by_withholding"], cov["unpinned_ranges"],
                                      cov["after_last_anchor"], cov["withheld"]))
    return 0 if ok else 1


def cmd_anchor_text(a) -> int:
    led = Ledger(a.log)
    if a.record:
        out = led.append_anchor(a.date, timestamp=a.timestamp)
        e = out["entry"]
        print(out["text"])
        print("recorded anchor entry seq %d for %s (late %s); head %s" % (e["seq"], e["anchor_date"],
                                                                          str(e["late"]).lower(), e["entry_id"]),
              file=sys.stderr)
        return 0
    c = led.compose_anchor(a.date, now=a.timestamp)
    print(c["text"])
    print("composed only; post it, then record it: styxx-ledger anchor-text %s --date %s --record" % (a.log, c["date"]),
          file=sys.stderr)
    return 0


def cmd_head(a) -> int:
    try:
        r = verify_bytes(Path(a.log).read_bytes())
    except OSError as e:
        raise _Usage("cannot read %s: %s" % (a.log, e)) from None
    last = r["entries"][-1]["entry"].get("seq") if r["entries"] else 0
    if a.json:
        print(json.dumps({"head": r["head"], "seq": last, "rederives": r["ok"]}))
    else:
        print(r["head"])
        if not r["ok"]:
            print("the log does not re-derive; this head is the last line's claim, not a derivation", file=sys.stderr)
    return 0 if r["ok"] else 1


# -------------------------------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="styxx-ledger", description="a writer and verifier for styxx ledger protocol v1")
    ap.add_argument("--version", action="version", version="styxx-ledger %s (python)" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a new log: the header line, then a started entry")
    p.add_argument("log")
    p.add_argument("--agent", required=True, help="1-32 chars of [a-z0-9_-]; the anchor text's first word")
    p.add_argument("--tz", required=True, help="anchor_tz: an iana zone (America/New_York, Europe/Berlin, UTC)")
    p.add_argument("--certifies", required=True, help="one sentence: what a line records and what it never carries")
    p.add_argument("--kinds", default="note", help="comma list of kinds; anchor and started are always added")
    p.add_argument("--created", help="header created, utc YYYY-MM-DDTHH:MM:SSZ (default: now)")
    p.add_argument("--timestamp", help="the started entry's timestamp (default: now)")
    p.add_argument("--no-started", "--no-start", dest="no_started", action="store_true", help="write the header only")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("append", help="append one entry")
    p.add_argument("log")
    p.add_argument("--kind", required=True)
    p.add_argument("--fields", help="a json object (integers only, no floats; ascii keys), or - for stdin")
    p.add_argument("--fields-file", help="a file holding the json object, or - for stdin")
    p.add_argument("--timestamp", help="utc YYYY-MM-DDTHH:MM:SSZ (default: now)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_append)

    p = sub.add_parser("verify", help="re-derive a log; check posted anchor texts; report coverage")
    p.add_argument("log")
    p.add_argument("--withheld", help="withheld.json: [{seq, entry_id, reason}, ...]")
    p.add_argument("--anchor", action="append", help="a posted anchor text (repeatable)")
    p.add_argument("--anchors-file", help="a file of posted anchor texts, one per line")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-problems", type=int, default=20)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("anchor-text", help="compose a day's anchor text (prints it); --record writes the anchor entry")
    p.add_argument("log")
    p.add_argument("--date", help="the day to anchor, YYYY-MM-DD (default: yesterday in anchor_tz)")
    p.add_argument("--record", action="store_true", help="also append the anchor entry")
    p.add_argument("--timestamp", help="'now' for the composition / the anchor entry's timestamp (default: now)")
    p.set_defaults(fn=cmd_anchor_text)

    p = sub.add_parser("head", help="print the head digest")
    p.add_argument("log")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_head)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except _Usage as e:
        print("styxx-ledger: %s" % e, file=sys.stderr)
        return 2
    except LedgerValueError as e:
        print("styxx-ledger: refused (%s): %s" % (e.code, e), file=sys.stderr)
        return 1
    except LedgerBroken as e:
        print("styxx-ledger: %s" % e, file=sys.stderr)
        for p in e.problems[:10]:
            print("  line %s seq %s %s" % (p.get("line"), p.get("seq"), _codes(p)), file=sys.stderr)
        return 1
    except LedgerError as e:
        print("styxx-ledger: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("styxx-ledger: i/o error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
