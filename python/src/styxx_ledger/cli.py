"""cli.py: styxx-ledger init | append | verify | anchor-text | head | exhibit.

exit codes: 0 done / re-derives; 1 refused, or the log does not re-derive, or an anchor does not hold;
2 usage or i/o error, or this python has no zone database ("pip install tzdata"). machine output with --json; the anchor text alone on stdout for anchor-text.

verify reads the header's schema: a v1 log is read as v1, a v0 log (darkflobi.gate/log/v0) under v0's rules (v0.py);
--protocol v1|v0 forces one. head is v1 only, as before.

exhibit <url> re-derives a published exhibit over the network (exhibit.py): exit 0 every check passed, 1 any
failed, 2 usage, or a file / an explorer did not answer.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional

from ._version import __version__
from .day import ZoneDatabaseMissing, require_zone_database
from .jcs import LedgerValueError
from .v0 import check_anchor_auto, parse_anchor_auto, verify_auto
from .verify import coverage
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
    r = verify_auto(raw, withheld=withheld, protocol=a.protocol)
    proto = r["protocol"]
    anchors = []
    for t in texts:
        p = parse_anchor_auto(t, proto)
        if p is None:
            anchors.append({"text": t, "ok": False, "parsed": False})
        else:
            c = check_anchor_auto(r, p, withheld)
            c["text"], c["parsed"] = t, True
            anchors.append(c)
    cov = None
    if texts or withheld:
        seqs = [x["seq"] for x in anchors if x.get("parsed") and x.get("ok")]
        cov = coverage(r["entries"], withheld, seqs)
    ok = r["ok"] and all(x["ok"] for x in anchors)
    if a.json:
        print(json.dumps({"ok": ok, "protocol": proto, "rederives": r["ok"], "entries": len(r["entries"]), "head": r["head"],
                          "file_sha256": r["file_sha256"], "bridged": r["bridged"], "problems": r["problems"],
                          "anchors": anchors, "coverage": cov}, ensure_ascii=True, sort_keys=True))
        return 0 if ok else 1
    n = len(r["entries"])
    if proto == "v0":
        _say("protocol v0 (darkflobi.gate/log/v0): read under v0's rules")
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
            form = "gate anchor <YYYY-MM-DD> head <64 hex> seq <n>" if proto == "v0" else \
                "<agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>"
            _say("anchor not in the form '%s': %r" % (form, x["text"][:120]))
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
        r = verify_auto(Path(a.log).read_bytes(), protocol="v1")
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


def cmd_exhibit(a) -> int:
    from .exhibit import DEFAULT_EXPLORERS, render_text, run_exhibit
    u = a.url
    if not (u.startswith("https://") or u.startswith("http://")):
        raise _Usage("exhibit wants an http(s) url, e.g. https://fathom-lab.github.io/styxx/ledger/")
    exps = a.explorer or list(DEFAULT_EXPLORERS)
    for e in exps:
        if not (e.startswith("https://") or e.startswith("http://")):
            raise _Usage("--explorer wants an http(s) url (an esplora api base such as https://blockstream.info/api)")
    if a.sample < 0:
        raise _Usage("--sample wants a count of 0 or more")
    if a.today is not None and not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", a.today):
        raise _Usage("--today wants a date YYYY-MM-DD")
    require_zone_database()   # no zone database: exit 2 before anything is fetched, never a chain verdict
    rep = run_exhibit(u, explorers=exps, sample=a.sample, no_ots=a.no_ots, save_dir=a.save,
                      allow_redirect=a.allow_redirect, today=a.today)
    if a.json:
        print(json.dumps(rep, ensure_ascii=True, sort_keys=True, indent=1))
    else:
        sys.stdout.write(render_text(rep))
    return rep["exit_code"]


def cmd_census(a) -> int:
    from .census import score
    from .day import now_utc
    if a.anchor_place_holds and a.anchor_place_fails:
        _say("census: --anchor-place-holds and --anchor-place-fails exclude each other")
        return 2
    place = "holds" if a.anchor_place_holds else ("fails: " + a.anchor_place_fails if a.anchor_place_fails else None)
    res = score(a.prereg, a.ledger, a.out, a.now or now_utc(), export=a.export, anchors=a.anchors,
                withheld=a.withheld, js=not a.no_js, anchor_place=place, tries=a.tries, interval_s=a.interval)
    _say("%s: verdict %s; wrote %s" % (res["status"], res.get("verdict") or "none", Path(a.out) / "RESULT.json"))
    return 1 if res["status"] == "refused" else 0


def cmd_census_digests(a) -> int:
    from .census import digests
    try:
        d = digests(a.prereg)
    except (OSError, UnicodeDecodeError) as e:
        _say("census-digests: cannot read %s: %s" % (a.prereg, type(e).__name__))
        return 2
    _say(json.dumps(d, indent=1, sort_keys=True))
    g = d.get("gates")
    bad = g is None or "error" in g or g["unreached"] or g["vacuous_gates"] or g["without_power_basis"]
    return 1 if bad else 0


# -------------------------------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="styxx-ledger", description="a writer and verifier for styxx ledger protocol v1 (and a reader of v0)")
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
    p.add_argument("--protocol", choices=("auto", "v1", "v0"), default="auto",
                   help="auto (default): by the header's schema; v1 or v0 forces one")
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

    p = sub.add_parser("exhibit", help="fetch a published exhibit by url and re-derive it: chain, anchors, proofs, witness")
    p.add_argument("url", help="the exhibit's base url, e.g. https://fathom-lab.github.io/styxx/ledger/")
    p.add_argument("--explorer", action="append",
                   help="an esplora api base asked for block headers (repeatable; default blockstream.info and mempool.space)")
    p.add_argument("--sample", type=int, default=20, help="witness proofs picked by the seeded rule (default 20; 0: none)")
    p.add_argument("--no-ots", action="store_true", help="skip every proof and explorer call")
    p.add_argument("--save", help="keep the fetched bytes (and the explorers' answers) under this directory")
    p.add_argument("--allow-redirect", action="store_true",
                   help="accept exhibit files served from another host (a redirect off the base url's host or off https)")
    p.add_argument("--today", help="the day (YYYY-MM-DD) the ages are counted against (default: today in utc)")
    p.add_argument("--json", action="store_true", help="the full record: every fetched file's sha256 and length, every answer")
    p.set_defaults(fn=cmd_exhibit)

    p = sub.add_parser("census", help="score a filled PREREG_census against a published ledger; writes RESULT.json / RESULT.md")
    p.add_argument("--prereg", required=True, help="the filled PREREG_census markdown file")
    p.add_argument("--ledger", help="the ledger: default the prereg's ledger_url; a url must be ledger_url, and a local "
                   "copy must hash to the bytes at ledger_url fetched in the same run")
    p.add_argument("--out", required=True, help="the directory RESULT.json and RESULT.md are written to")
    p.add_argument("--now", help="utc YYYY-MM-DDTHH:MM:SSZ the census is scored at (default: now)")
    p.add_argument("--export", help="the census export (json {destinations, made_at, messages}), a path or url")
    p.add_argument("--anchors", help="posted anchor texts (an index json or one text per line), overriding anchors_url")
    p.add_argument("--withheld", help="withheld.json, overriding withheld_url")
    p.add_argument("--no-js", action="store_true", help="skip the javascript reference implementation's re-derivation "
                   "(G_C then reads unmeasured)")
    p.add_argument("--tries", type=int, default=3, help="fetch tries for each url (default 3, the template's rule)")
    p.add_argument("--interval", type=float, default=3600, help="seconds between tries (default 3600)")
    p.add_argument("--anchor-place-holds", action="store_true", help="the lab's judgement: the anchor place is one where "
                   "the operator cannot edit or delete a post")
    p.add_argument("--anchor-place-fails", metavar="WHY", help="the lab's judgement that the place fails, and why; "
                   "every day prints unanchored")
    p.set_defaults(fn=cmd_census)

    p = sub.add_parser("census-digests", help="print a prereg's registration digest (bytes before '## 15.') and gates "
                       "digest, and walk the gates block's assignments")
    p.add_argument("--prereg", required=True)
    p.set_defaults(fn=cmd_census_digests)
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
    except ZoneDatabaseMissing as e:
        print("styxx-ledger: %s; nothing was verified (exit 2)" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("styxx-ledger: i/o error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
