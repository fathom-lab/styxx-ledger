#!/usr/bin/env python3
"""mutate_core.py: mutation calibration of vectors_v1.json.

    python -B vectors/mutate_core.py

Copy the python core to a temp folder, apply one source mutation, run run_vectors.py
against it, and record whether at least one vector fails (the mutant is KILLED) or all pass (it SURVIVES)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "python/src/styxx_ledger"

M = [
    # day.py mutants re-pointed at the fix pass's source (2026-11-08): _local() holds the astimezone call
    ("day: fixed EDT offset, zone ignored", "day.py",
     '        return d.astimezone(z)',
     '        return d.astimezone(_dt.timezone(_dt.timedelta(hours=-4)))'),
    ("day: always New York", "day.py",
     '        return d.astimezone(z)',
     '        return d.astimezone(zone("America/New_York"))'),
    ("day: UTC day, zone ignored", "day.py",
     '        return d.astimezone(z)',
     '        return d'),
    ("timestamp: offsets and fractions accepted", "day.py",
     '    m = TIMESTAMP_RX.fullmatch(ts)',
     '    m = TIMESTAMP_RX.fullmatch(ts[:19] + "Z")'),
    ("timestamp: calendar not validated (rolls over)", "day.py",
     '        return _dt.datetime(*g, tzinfo=_dt.timezone.utc)',
     '        return _dt.datetime(g[0], 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(days=sum([0,31,28,31,30,31,30,31,31,30,31,30][:g[1]]) + g[2] - 1, hours=g[3], minutes=g[4], seconds=g[5])'),
    # mutants added in the fix pass, one per review finding they pin
    ("timestamp: trailing LF tolerated (finding 1)", "day.py",
     '    m = TIMESTAMP_RX.fullmatch(ts)',
     '    m = TIMESTAMP_RX.fullmatch(ts.rstrip("\\n"))'),
    ("timestamp: unicode digits admitted (finding 1)", "day.py",
     'TIMESTAMP_RX = re.compile(r"\\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z\\Z")',
     'TIMESTAMP_RX = re.compile(r"\\A(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2}):(\\d{2})Z\\Z")'),
    ("timestamp: year range off (finding 2)", "day.py",
     '    if not YEAR_MIN <= g[0] <= YEAR_MAX:', '    if False:'),
    ("zone: listed-name check off (finding 6)", "day.py",
     '    if tz not in _available():', '    if False:'),
    ("zone: Factory admitted (finding 6)", "day.py",
     ' or ".." in tz or tz in REFUSED_ZONES:', ' or ".." in tz:'),
    ("late: cutoff ignored (finding 5)", "day.py",
     '    return day > nd or (day == nd and clock > LATE_AFTER)', '    return day > nd'),
    ("late: cutoff inclusive (finding 5)", "day.py",
     '    return day > nd or (day == nd and clock > LATE_AFTER)', '    return day > nd or (day == nd and clock >= LATE_AFTER)'),
    ("late: rule not enforced at build (finding 5)", "chain.py",
     '    if kind == "anchor" and fields["late"] != late_of(', '    if False and fields["late"] != late_of('),
    ("jcs: depth bound off (finding 3)", "jcs.py",
     '    if isinstance(v, (dict, list, tuple)) and _depth + 1 > MAX_DEPTH:', '    if False:'),
    ("jcs: depth bound off by one (finding 3)", "jcs.py",
     '    if isinstance(v, (dict, list, tuple)) and _depth + 1 > MAX_DEPTH:',
     '    if isinstance(v, (dict, list, tuple)) and _depth > MAX_DEPTH:'),
    ("read: depth scan off (finding 3)", "chain.py", '        if depth_exceeds(line):', '        if False:'),
    ("withheld: integral float ignored (finding 4)", "chain.py",
     '    if isinstance(v, float) and v.is_integer() and abs(v) <= MAX_INT:', '    if False:'),
    ("verify: no_header only with entries (finding 8)", "chain.py",
     '        bad.append({"line": 1, "seq": None, "codes": ["no_header"], "problems": ["no header"]})',
     '        bad.extend([{"line": 1, "seq": None, "codes": ["no_header"], "problems": ["no header"]}] if entries else [])'),
    ("anchor text: agent $ admits trailing LF (finding 1)", "chain.py",
     'AGENT_RX = re.compile(r"\\A[a-z0-9_-]{1,32}\\Z")', 'AGENT_RX = re.compile(r"\\A[a-z0-9_-]{1,32}$")'),
    ("anchor text: seq bound off", "chain.py",
     '            or not _is_int(seq) or seq < 0 or seq > MAX_INT:', '            or not _is_int(seq) or seq < 0:'),
    ("dump: ensure_ascii=True", "jcs.py",
     'json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))',
     'json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"))'),
    ("dump: keys unsorted", "jcs.py",
     'json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))',
     'json.dumps(obj, ensure_ascii=False, sort_keys=False, separators=(",", ":"))'),
    ("dump: DEL escaped", "jcs.py",
     '    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))',
     '    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("\\x7f", "\\\\u007f")'),
    ("jcs: float admitted", "jcs.py",
     '        raise LedgerValueError("float", "float at %s: the ledger carries integers, never floats" % path)',
     '        return'),
    ("jcs: 2^53 bound off", "jcs.py", '        if abs(v) > MAX_INT:', '        if False:'),
    ("jcs: 2^53 bound exclusive", "jcs.py", '        if abs(v) > MAX_INT:', '        if abs(v) >= MAX_INT:'),
    ("jcs: non-ASCII key admitted", "jcs.py", '            if any(ord(c) > 0x7E for c in k):', '            if False:'),
    ("jcs: DEL key admitted", "jcs.py", '            if any(ord(c) > 0x7E for c in k):', '            if any(ord(c) > 0x7F for c in k):'),
    ("jcs: lone surrogate admitted", "jcs.py", '        if _LONE_SURROGATE.search(v):', '        if False:'),
    ("header digest: no domain", "chain.py",
     '    return sha256_hex(HEADER_DOMAIN + jcs(header).encode("utf-8"))',
     '    return sha256_hex(jcs(header).encode("utf-8"))'),
    ("header digest: v0 domain", "chain.py",
     'HEADER_DOMAIN = (LOG_SCHEMA + "\\n").encode("ascii")',
     'HEADER_DOMAIN = b"darkflobi.gate/log/v0\\n"'),
    ("header digest: domain without LF", "chain.py",
     'HEADER_DOMAIN = (LOG_SCHEMA + "\\n").encode("ascii")',
     'HEADER_DOMAIN = LOG_SCHEMA.encode("ascii")'),
    ("anchor text: v0 fixed word", "chain.py",
     '    return "%s anchor %s head %s seq %d" % (agent, date, head, seq)',
     '    return "gate anchor %s head %s seq %d" % (date, head, seq)'),
    ("anchor text: agent form unchecked", "chain.py",
     '    if not isinstance(agent, str) or not AGENT_RX.match(agent) or not isinstance(date, str) \\',
     '    if not isinstance(agent, str) or not isinstance(date, str) \\'),
    ("build: kind not checked", "chain.py",
     '    if not isinstance(kind, str) or not isinstance(kinds, list) or kind not in kinds:\n        raise LedgerValueError("kind_not_declared"',
     '    if False:\n        raise LedgerValueError("kind_not_declared"'),
    ("build: reserved fields admitted", "chain.py",
     '        if not isinstance(k, str) or k in RESERVED_FIELDS or k.startswith("_"):',
     '        if not isinstance(k, str):'),
    ("build: started writer not required", "chain.py", '    if kind == "started":', '    if False:'),
    ("build: day in UTC", "chain.py",
     '    day = day_of(timestamp, header.get("anchor_tz"))', '    day = day_of(timestamp, "UTC")'),
    ("verify: kind not checked", "chain.py",
     '        if not isinstance(core.get("kind"), str) or core.get("kind") not in kinds:', '        if False:'),
    ("verify: header kinds not checked", "chain.py",
     '    if not all(r in kinds for r in REQUIRED_KINDS):\n        bad.append', '    if False:\n        bad.append'),
    ("verify: no withheld bridging", "chain.py",
     '        while want_seq in wm and e.get("seq") != want_seq:', '        while False:'),
    ("verify: CR not reported", "chain.py", '    if b"\\r" in raw:', '    if False:'),
    ("verify: canonical bytes not checked", "chain.py", '        if not canonical:', '        if False:'),
    ("verify: seq not checked", "chain.py", '        if not (_is_int(s) and s == want_seq):', '        if False:'),
    ("verify: prev not checked", "chain.py", '        if e.get("prev") != prev:', '        if False:'),
    ("verify: entry_id not checked", "chain.py", '        if want is not None and e.get("entry_id") != want:', '        if False:'),
    ("verify: day not checked", "chain.py",
     '            if day_of(core.get("timestamp"), tz) != core.get("day"):', '            if False:'),
    ("verify: day read in UTC", "chain.py",
     '            if day_of(core.get("timestamp"), tz) != core.get("day"):',
     '            if day_of(core.get("timestamp"), "UTC") != core.get("day"):'),
    ("verify: schema not checked", "chain.py", '        if core.get("schema") != ENTRY_SCHEMA:', '        if False:'),
    ("verify: v0 header accepted", "chain.py",
     '        if header is None and not entries and obj.get("schema") == LOG_SCHEMA:',
     '        if header is None and not entries and obj.get("schema") in (LOG_SCHEMA, V0_LOG_SCHEMA):'),
    ("anchor: agent not checked", "verify.py",
     '    agent_ok = True if header is None else (isinstance(header, dict) and header.get("agent") == a.get("agent"))',
     '    agent_ok = True'),
    ("anchor: later day lines ignored", "verify.py",
     '    out["ok"] = bool(agent_ok and in_chain and after == 0 and',
     '    out["ok"] = bool(agent_ok and in_chain and'),
    ("anchor: own line agreement ignored", "verify.py",
     ' and (own is None or out["ledger_anchor_line"]["agrees"]))', ')'),
    ("anchor: withheld head not honoured", "verify.py",
     '    via_withheld = by_seq is None and a["seq"] in wm', '    via_withheld = False'),
    ("coverage: anchor bound exclusive", "verify.py", '        if any(s < w <= a for w in ws):', '        if any(s < w < a for w in ws):'),
    ("coverage: withheld never severs", "verify.py", '        if any(s < w <= a for w in ws):', '        if False:'),
    ("parse anchor: trailing text tolerated", "chain.py",
     'seq (0|[1-9][0-9]*)\\n?\\Z")', 'seq (0|[1-9][0-9]*)")'),
    # added 2026-11-09 (the lab's improvement sweep), one or more per rank whose vectors they measure
    ("certifies: python's own whitespace, u+feff not blank (rank 43)", "chain.py",
     'not c.strip(CERTIFIES_BLANK)', 'not c.strip()'),
    ("certifies: only the empty string is blank (rank 43)", "chain.py", 'not c.strip(CERTIFIES_BLANK)', 'not c'),
    ("certifies: 500 bound exclusive (rank 43)", "chain.py", 'len(c) > CERTIFIES_MAX', 'len(c) >= CERTIFIES_MAX'),
    ("compose: the day of now counts as closed (rank 42)", "writer.py", '    if date >= today:', '    if date > today:'),
    ("compose: an open day composed (rank 42)", "writer.py", '    if date >= today:', '    if False:'),
    ("compose: an anchored day composed (rank 42)", "writer.py",
     '    if any(it["entry"].get("kind") == "anchor" and it["entry"].get("anchor_date") == date for it in entries):',
     '    if False:'),
    ("compose: the day's earliest line taken as its head (rank 42)", "writer.py",
     'if e.get("day") == date and (last is None or e["seq"] > last["seq"]):', 'if e.get("day") == date and last is None:'),
    ("compose: today read in utc (rank 42)", "writer.py", '    today = day_of(now, tz)', '    today = day_of(now, "UTC")'),
    ("compose: date form unchecked (rank 42)", "writer.py",
     '    if not isinstance(date, str) or not DATE_RX.match(date):', '    if not isinstance(date, str):'),
    ("dump: strings normalised to nfc (rank 68)", "jcs.py",
     '    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))',
     '    return __import__("unicodedata").normalize("NFC", json.dumps(obj, ensure_ascii=False, sort_keys=True, '
     'separators=(",", ":")))'),
]


def run(src: Path):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-B", str(REPO / "vectors/run_vectors.py"), "--src", str(src)],
                       capture_output=True, text=True, env=env, timeout=120)
    last = [ln for ln in p.stdout.splitlines() if "vectors answered" in ln]
    fails = [ln.split(None, 2)[2] if len(ln.split(None, 2)) > 2 else ln for ln in p.stdout.splitlines() if ln.startswith("FAIL")]
    return p.returncode, (last[-1] if last else p.stdout[-300:] + p.stderr[-300:]), fails


def main():
    rc, line, _ = run(PKG.parent)
    print("unmutated:", rc, line)
    rows = []
    for name, f, old, new in M:
        td = Path(tempfile.mkdtemp(prefix="mut_"))
        dst = td / "styxx_ledger"
        shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__"))
        s = (dst / f).read_text("utf-8")
        if s.count(old) != 1:
            rows.append((name, "MUTATION NOT APPLIED (%d matches)" % s.count(old), ""))
            shutil.rmtree(td)
            continue
        (dst / f).write_text(s.replace(old, new), "utf-8", newline="\n")
        rc, line, fails = run(td)
        status = "killed" if rc != 0 else "SURVIVED"
        rows.append((name, status, "%s | %s" % (line, ", ".join(fails[:4]))))
        shutil.rmtree(td)
    killed = sum(1 for r in rows if r[1] == "killed")
    applied = sum(1 for r in rows if not r[1].startswith("MUTATION NOT"))
    for r in rows:
        print("%-46s %-9s %s" % r)
    print("%d of %d applied mutants killed (%d listed)" % (killed, applied, len(rows)))


if __name__ == "__main__":
    main()
