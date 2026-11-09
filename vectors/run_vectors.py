#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_vectors.py: answer the shared v1 vectors with the python package (styxx_ledger).

    python -B vectors/run_vectors.py [--vectors vectors/vectors_v1.json] [--src python/src] [-v]

Read-side cases: apply the transform to base_v1.jsonl (the input's sha256 must match), verify it with the withheld
list and anchor texts given, and compare the answer with `expect` (only the keys in `compare` when a case names
them). Write-side cases: call the named function on the given arguments and compare the value, or the refusal's
`.code`. Prints "k of n vectors answered as the file says"; exit 0 only when k == n. run_vectors.mjs does the same
with the javascript package.

Protocol v0 (vectors/v0/, the exhibit's 10 cases over its base.jsonl, copied byte for byte): the same, with the
package's v0 read mode (styxx_ledger.v0) and the exhibit runner's transforms; printed first, as
"k of n v0 vectors answered as the file says". `--only v1` or `--only v0` runs one set; the default runs both, the
v1 tally stays the last line, and the exit is 0 only when both sets are answered in full.

A python with no zone database (python.org windows without the `tzdata` package) cannot read a day: the runner
says "this python has no zone database: pip install tzdata" and ends exit 2 before any case, never a miss count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def load_pkg(src: Path):
    sys.path.insert(0, str(src))
    import styxx_ledger  # noqa: E402
    return styxx_ledger


# ------------------------------------------------------------------------------------------- transforms

def _canon(S, obj) -> bytes:
    return S.dump(obj).encode("utf-8")


def _rechain(S, lines, from_seq: int):
    """Re-derive prev and entry_id for every entry with seq >= from_seq; line 1 (first non-blank) is the header."""
    out, prev, seen_header = [], None, False
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            continue
        o = json.loads(ln)
        if not seen_header:
            seen_header = True
            prev = S.header_digest(o)
            out.append(ln)
            continue
        if o["seq"] >= from_seq:
            o["prev"] = prev
            o.pop("entry_id", None)
            o["entry_id"] = S.entry_id_of(o)
            out.append(_canon(S, o))
        else:
            out.append(ln)
        prev = o["entry_id"]
    return out


def apply(S, base: bytes, t: dict) -> bytes:
    op = t["op"]
    if op == "identity":
        return base
    if op == "crlf_first_line":
        return base.replace(b"\n", b"\r\n", 1)
    if op == "truncate_last":
        kept = base.rstrip(b"\n").split(b"\n")[:-1]
        return b"\n".join(kept) + b"\n"
    if op == "replace_all":
        return t["text"].encode("utf-8")
    if op == "append_nested":
        n = t["depth"] - 1
        return base + b'{"deep":' + b"[" * n + b"1" + b"]" * n + b"}\n"
    lines = base.split(b"\n")
    out, header_done = [], False
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            continue
        o = json.loads(ln)
        if not header_done:
            header_done = True
            if op in ("set_header", "set_header_rechain"):
                o[t["field"]] = t["value"]
                out.append(_canon(S, o))
            else:
                out.append(ln)
            continue
        s = o.get("seq")
        if op in ("set_field", "set_field_rechain") and s == t["seq"]:
            o[t["field"]] = t["value"]
            out.append(_canon(S, o))
        elif op == "drop_seq" and s == t["seq"]:
            continue
        elif op == "replace_in_line" and s == t["seq"]:
            old, new = t["old"].encode("utf-8"), t["new"].encode("utf-8")
            if old not in ln:
                raise ValueError("replace_in_line: %r not in the line of seq %s" % (t["old"], s))
            out.append(ln.replace(old, new, 1))
        elif op == "dup_key" and s == t["seq"]:
            out.append(ln[:-1] + b',"' + t["key"].encode("utf-8") + b'":' + json.dumps(t["value"]).encode("utf-8") + b"}")
        else:
            out.append(ln)
    if op == "set_field_rechain":
        out = _rechain(S, out, t["seq"])
    elif op == "set_header_rechain":
        out = _rechain(S, out, 1)
    elif op not in ("set_field", "drop_seq", "dup_key", "set_header", "replace_in_line"):
        raise ValueError("unknown transform op %r" % op)
    return b"\n".join(out)


# --------------------------------------------------------------------------------------------- answers

def _codes(p):
    return list(p.get("codes") or ([p["code"]] if p.get("code") else []))


def answer_read(S, text: bytes, case: dict) -> dict:
    r = S.verify_bytes(text, withheld=case.get("withheld") or [])
    probs = r["problems"]
    out = {
        "ok": r["ok"],
        "problem_seqs": sorted({p["seq"] for p in probs if p.get("seq") is not None}),
        "problems_without_seq": sum(1 for p in probs if p.get("seq") is None),
        "problem_codes": sorted({c for p in probs for c in _codes(p)}),
        "head": r["head"],
        "bridged": r["bridged"],
    }
    if case.get("anchors") is not None:
        res = []
        for t in case["anchors"]:
            a = S.parse_anchor_text(t)
            res.append(bool(a) and S.check_anchor(r["entries"], a, case.get("withheld") or [], r["header"])["ok"])
        out["anchors_ok"] = res
    if case.get("coverage_anchor_seqs") is not None:
        out["coverage"] = S.coverage(r["entries"], case.get("withheld") or [], case["coverage_anchor_seqs"])
    return out


def call_write(S, c: dict):
    """(value, error_code). value is a string for every function (a line for build_entry)."""
    fn = c["fn"]
    try:
        if fn == "jcs":
            v = S.jcs(c["input"])
        elif fn == "day_of":
            v = S.day_of(c["timestamp"], c["tz"])
        elif fn == "header_digest":
            v = S.header_digest(c["header"])
        elif fn == "entry_id":
            v = S.entry_id_of(c["core"])
        elif fn == "anchor_text":
            v = S.anchor_text(c["agent"], c["date"], c["head"], c["seq"])
        elif fn == "late_of":
            v = S.late_of(c["anchor_date"], c["timestamp"], c["tz"])
        elif fn == "build_entry":
            v = S.dump(S.build_entry(c["header"], c["seq"], c["prev"], c["kind"], c["timestamp"], c["fields"]))
        else:
            raise KeyError("unknown write fn %r" % fn)
    except S.LedgerValueError as e:
        return None, e.code
    return v, None


def check_write(S, c: dict):
    v, err = call_write(S, c)
    if "expect_error" in c:
        return err == c["expect_error"], {"value": v, "error": err}
    ok = err is None and v == c["expect"]
    if ok and "expect_sha256" in c:
        ok = hashlib.sha256(v.encode("utf-8")).hexdigest() == c["expect_sha256"]
    return ok, {"value": v, "error": err}


# ------------------------------------------------------------------------------------------- protocol v0

def apply_v0(S, base: bytes, t: dict) -> bytes:
    """The exhibit's run_vectors.cjs transforms, byte for byte; the header is the line whose schema is v0's."""
    V0 = S.v0
    op = t["op"]
    if op == "identity":
        return base
    if op == "crlf_first_line":
        return base.replace(b"\n", b"\r\n", 1)
    if op == "truncate_last":
        kept = base.rstrip(b"\n").split(b"\n")[:-1]
        return b"\n".join(kept) + b"\n"
    out = []
    for ln in base.split(b"\n"):
        if not ln.strip():
            out.append(ln)
            continue
        o = json.loads(ln)
        s = o.get("seq")
        if op == "set_field" and s == t["seq"]:
            o[t["field"]] = t["value"]
            out.append(_canon(S, o))
        elif op == "drop_seq" and s == t["seq"]:
            continue
        elif op == "dup_key" and s == t["seq"]:
            out.append(ln[:-1] + b',"' + t["key"].encode("utf-8") + b'":' + json.dumps(t["value"]).encode("utf-8") + b"}")
        else:
            out.append(ln)
    if op == "set_field_rechain":
        res, prev = [], None
        for ln in out:
            if not ln.strip():
                res.append(ln)
                continue
            o = json.loads(ln)
            if o.get("schema") == S.chain.V0_LOG_SCHEMA:
                prev = V0.header_digest_v0(o)
                res.append(ln)
                continue
            if o["seq"] == t["seq"]:
                o[t["field"]] = t["value"]
            if o["seq"] >= t["seq"]:
                o["prev"] = prev
                o.pop("entry_id", None)
                o["entry_id"] = S.entry_id_of(o)
                res.append(_canon(S, o))
            else:
                res.append(ln)
            prev = o["entry_id"]
        out = res
    elif op not in ("set_field", "drop_seq", "dup_key"):
        raise ValueError("unknown v0 transform op %r" % op)
    return b"\n".join(out)


def answer_v0(S, text: bytes, case: dict) -> dict:
    V0 = S.v0
    w = case.get("withheld") or []
    r = V0.verify_bytes_v0(text, withheld=w)
    probs = r["problems"]
    out = {"ok": r["ok"],
           "problem_seqs": sorted({p["seq"] for p in probs if p.get("seq") is not None}),
           "problems_without_seq": sum(1 for p in probs if p.get("seq") is None),
           "head": r["head"], "bridged": r["bridged"]}
    if case.get("anchors") is not None:
        res = []
        for t in case["anchors"]:
            a = V0.parse_anchor_text_v0(t)
            res.append(bool(a) and V0.check_anchor_v0(r["entries"], a, w)["ok"])
        out["anchors_ok"] = res
    return out


def check_v0(S, base: bytes, c: dict):
    text = apply_v0(S, base, c["transform"])
    if hashlib.sha256(text).hexdigest() != c["input_sha256"]:
        return False, {"input_sha256": hashlib.sha256(text).hexdigest()}
    got = answer_v0(S, text, c)
    if c["transform"]["op"] == "dup_key":   # the exhibit runner compares ok only for this case
        return got["ok"] == c["expect"]["ok"], got
    return all(got.get(k) == c["expect"].get(k) for k in c["expect"]), got


def run_v0(S, vpath: Path, verbose: bool):
    """(answered, total), or None when the base file is not the one the vectors name."""
    doc = json.loads(vpath.read_text("utf-8"))
    base = (vpath.parent / doc["base"]).read_bytes()
    if hashlib.sha256(base).hexdigest() != doc["base_sha256"]:
        print("the v0 base file is not the one the v0 vectors were made over")
        return None
    good = 0
    for c in doc["cases"]:
        try:
            ok, got = check_v0(S, base, c)
        except S.ZoneDatabaseMissing:
            raise
        except Exception as e:  # noqa: BLE001
            ok, got = False, {"raised": "%s: %s" % (type(e).__name__, str(e)[:200])}
        good += 1 if ok else 0
        if verbose or not ok:
            print("%s v0    %s" % ("ok  " if ok else "FAIL", c["name"]))
        if not ok:
            print("   expected %s" % json.dumps(c["expect"], sort_keys=True))
            print("   got      %s" % json.dumps(got, sort_keys=True))
    print("  %-22s %d of %d" % ("v0:read", good, len(doc["cases"])))
    print("%d of %d v0 vectors answered as the file says" % (good, len(doc["cases"])))
    return good, len(doc["cases"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", default=str(HERE / "vectors_v1.json"))
    ap.add_argument("--v0-vectors", default=str(HERE / "v0" / "vectors.json"))
    ap.add_argument("--only", choices=("v1", "v0", "both"), default="both")
    ap.add_argument("--src", default=str(HERE.parent / "python" / "src"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    S = load_pkg(Path(a.src))
    try:
        return _main(S, a)
    except S.ZoneDatabaseMissing as e:
        print("%s; no vector was answered (exit 2)" % e)
        return 2


def _main(S, a) -> int:
    S.require_zone_database()
    v0_failed = False
    if a.only in ("v0", "both"):
        res = run_v0(S, Path(a.v0_vectors), a.verbose)
        if res is None:
            return 2
        v0_failed = res[0] != res[1]
        if a.only == "v0":
            return 1 if v0_failed else 0
    vpath = Path(a.vectors)
    doc = json.loads(vpath.read_text("utf-8"))
    base = (vpath.parent / doc["base"]).read_bytes()
    if hashlib.sha256(base).hexdigest() != doc["base_sha256"]:
        print("the base file is not the one the vectors were made over (a checkout that converted LF to CRLF does this)")
        return 2
    total = len(doc["read"]) + len(doc["write"])
    failed = 0
    by_group = {}
    for c in doc["read"]:
        try:
            text = apply(S, base, c["transform"])
            if hashlib.sha256(text).hexdigest() != c["input_sha256"]:
                ok, got = False, {"input_sha256": hashlib.sha256(text).hexdigest()}
            else:
                got = answer_read(S, text, c)
                keys = c.get("compare") or list(c["expect"])
                ok = all(got.get(k) == c["expect"].get(k) for k in keys)
        except S.ZoneDatabaseMissing:
            raise
        except Exception as e:  # noqa: BLE001 - an implementation that throws on a case misses that case
            ok, got = False, {"raised": "%s: %s" % (type(e).__name__, str(e)[:200])}
        g = "read"
        by_group.setdefault(g, [0, 0])[1] += 1
        if ok:
            by_group[g][0] += 1
        else:
            failed += 1
        if a.verbose or not ok:
            print("%s read  %s" % ("ok  " if ok else "FAIL", c["name"]))
        if not ok:
            print("   expected %s" % json.dumps(c["expect"], sort_keys=True))
            print("   got      %s" % json.dumps(got, sort_keys=True))
    for c in doc["write"]:
        try:
            ok, got = check_write(S, c)
        except S.ZoneDatabaseMissing:
            raise
        except Exception as e:  # noqa: BLE001 - an uncoded exception is a miss, not a refusal
            ok, got = False, {"raised": "%s: %s" % (type(e).__name__, str(e)[:200])}
        g = "write:" + c["fn"]
        by_group.setdefault(g, [0, 0])[1] += 1
        if ok:
            by_group[g][0] += 1
        else:
            failed += 1
        if a.verbose or not ok:
            print("%s write %s" % ("ok  " if ok else "FAIL", c["name"]))
        if not ok:
            want = {"error": c["expect_error"]} if "expect_error" in c else {"value": c["expect"]}
            print("   expected %s" % json.dumps(want, ensure_ascii=True))
            print("   got      %s" % json.dumps(got, ensure_ascii=True))
    for g in sorted(by_group):
        print("  %-22s %d of %d" % (g, by_group[g][0], by_group[g][1]))
    print("implementation: styxx_ledger (python %s, %s)" % (sys.version.split()[0], sys.platform))
    print("%d of %d vectors answered as the file says" % (total - failed, total))
    return 1 if (failed or v0_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
