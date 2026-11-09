#!/usr/bin/env python3
"""census_check_readme.py: fail when a census RESULT.json is refused, or when a README sentence that quotes a
RESULT number does not match RESULT.json.

    python -I -B census_check_readme.py RESULT.json README.md [--require N]

a quoted number carries its receipt as a marker in the same sentence, in either form:

    the census counted 0 unledgered deliveries (census: result.unledgered_deliveries = 0).
    4 deliveries reached the public channel <!-- census: result.n_deliveries = 4 -->.

the path is dotted into RESULT.json (integers index lists: anchors.window.missing_days.0); the value is json (0,
null, "HELD__...") or a bare word compared with the string at that path. three checks per marker:

1. the path exists in RESULT.json;
2. RESULT.json's value at the path equals the marker's value;
3. when the value is a number, the sentence the marker sits in (from the previous . ! ? or line start, up to the
   marker) says that number as a standalone numeral, so the prose cannot drift from its marker.

and two per file: RESULT.json's status is not "refused" nor "rehearsal" (a census --rehearse run is a local copy
scored offline, never a verdict, so a readme never quotes one), and at least --require markers (default 1) exist,
so a readme with no marker does not pass by saying nothing. exit 0 every check passed; 1 any failed; 2 usage or i/o.
nothing is written. standard library only.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, List, Tuple

MARKER_RX = re.compile(r"\(census:\s*([A-Za-z0-9_.\-]+)\s*=\s*(.+?)\)"
                       r"|<!--\s*census:\s*([A-Za-z0-9_.\-]+)\s*=\s*(.+?)\s*-->")
MISSING = object()


def resolve(doc: Any, path: str) -> Any:
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and re.fullmatch(r"[0-9]+", part) and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return MISSING
    return cur


def parse_value(s: str) -> Any:
    s = s.strip()
    try:
        return json.loads(s)
    except ValueError:
        return s


def _same(want: Any, got: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return want == got
    return type(want) is type(got) and want == got


def _sentence_before(line: str, start: int) -> str:
    head = line[:start]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[cut + 1:] if cut >= 0 else head


def check(result: dict, readme: str, require: int = 1) -> Tuple[List[str], int]:
    """(failures, markers seen)."""
    fails: List[str] = []
    if result.get("status") == "refused":
        r = result.get("refusal") or {}
        fails.append("RESULT.json says refused (%s): %s" % (r.get("code"), r.get("reason")))
    if result.get("status") == "rehearsal":
        fails.append("RESULT.json is a rehearsal (census --rehearse: a local copy scored offline, never a verdict); "
                     "a readme quotes a run that read ledger_url")
    seen = 0
    for n, line in enumerate(readme.splitlines(), start=1):
        for m in MARKER_RX.finditer(line):
            seen += 1
            path = m.group(1) or m.group(3)
            want = parse_value(m.group(2) if m.group(1) else m.group(4))
            got = resolve(result, path)
            if got is MISSING:
                fails.append("line %d: %s is not in RESULT.json" % (n, path))
                continue
            if not _same(want, got):
                fails.append("line %d: the readme says %s = %s; RESULT.json says %s"
                             % (n, path, json.dumps(want), json.dumps(got)))
                continue
            if isinstance(want, (int, float)) and not isinstance(want, bool):
                num = re.escape(json.dumps(want))
                if not re.search(r"(?<![0-9.])%s(?![0-9])" % num, _sentence_before(line, m.start())):
                    fails.append("line %d: the sentence before the marker for %s does not say %s"
                                 % (n, path, json.dumps(want)))
    if seen < require:
        fails.append("%d census marker(s) in the readme; at least %d required" % (seen, require))
    return fails, seen


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    require = 1
    if "--require" in argv:
        i = argv.index("--require")
        try:
            require = int(argv[i + 1])
        except (IndexError, ValueError):
            print("census_check_readme: --require wants an integer", file=sys.stderr)
            return 2
        del argv[i:i + 2]
    if len(argv) != 2:
        print("usage: census_check_readme.py RESULT.json README.md [--require N]", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as f:
            result = json.load(f)
        with open(argv[1], encoding="utf-8") as f:
            readme = f.read()
    except (OSError, ValueError) as e:
        print("census_check_readme: cannot read: %s" % e, file=sys.stderr)
        return 2
    if not isinstance(result, dict):
        print("census_check_readme: RESULT.json is not an object", file=sys.stderr)
        return 2
    fails, seen = check(result, readme, require)
    for f in fails:
        print("FAIL %s" % f)
    print("%d marker(s) checked, %d failure(s); RESULT status %s, verdict %s"
          % (seen, len(fails), result.get("status"), result.get("verdict")))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
