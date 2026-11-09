"""jcs.py: the one byte form of a ledger object (protocol v1, section 2).

For the value types the ledger admits (null, booleans, integers with |n| <= 2^53, strings without lone
surrogates, arrays, objects whose keys are U+0000..U+007E, nested at most MAX_DEPTH = 32 containers deep), the compact key-sorted dump below IS RFC 8785 (JCS):
strings escape only `"`, `\\` and U+0000-U+001F (short forms for \\b \\f \\n \\r \\t, \\u00xx with lowercase hex
for the rest), every other character is raw UTF-8, keys sort by code point (equal to UTF-16 order for ASCII).
Anything else is refused at write time with a LedgerValueError carrying a stable `.code`, so two implementations
never disagree on a number's or a string's bytes.

Codes: float, int_range, non_ascii_key, lone_surrogate, depth, type.
Carried from the gate's ledger.py (jcs / canonical_line); the canonicaliser is the same json.dumps call.
"""
from __future__ import annotations

import json
import re
from typing import Any

MAX_INT = 2 ** 53
MAX_DEPTH = 32  # containers, the outermost counted as 1 (section 2)
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


class LedgerValueError(ValueError):
    """A value the ledger refuses to canonicalise. `.code` is one of the protocol's refusal codes."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def check_value(v: Any, path: str = "$", _depth: int = 0) -> None:
    """Raise LedgerValueError when `v` holds a value outside the admitted types."""
    if isinstance(v, (dict, list, tuple)) and _depth + 1 > MAX_DEPTH:
        raise LedgerValueError("depth", "containers nested deeper than %d at %s" % (MAX_DEPTH, path))
    if v is None or isinstance(v, bool):
        return
    if isinstance(v, str):
        if _LONE_SURROGATE.search(v):
            raise LedgerValueError("lone_surrogate", "lone surrogate in a string at %s" % path)
        return
    if isinstance(v, int):
        if abs(v) > MAX_INT:
            raise LedgerValueError("int_range", "integer at %s exceeds 2^53; JCS numbers are IEEE doubles" % path)
        return
    if isinstance(v, float):
        raise LedgerValueError("float", "float at %s: the ledger carries integers, never floats" % path)
    if isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                raise LedgerValueError("type", "non-string key at %s" % path)
            if any(ord(c) > 0x7E for c in k):
                raise LedgerValueError("non_ascii_key", "non-ASCII key at %s" % path)
            check_value(x, path + "/" + k, _depth + 1)
        return
    if isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            check_value(x, "%s[%d]" % (path, i), _depth + 1)
        return
    raise LedgerValueError("type", "unserialisable value at %s: %s" % (path, type(v).__name__))


def depth_exceeds(line: bytes, limit: int = MAX_DEPTH) -> bool:
    """Whether a line's json nests more than `limit` containers deep, read from its bytes (brackets outside
    strings), before any parser recurses into it. A reader reports such a line as unparsable (section 4)."""
    if line.count(b"[") + line.count(b"{") <= limit:
        return False
    depth = 0
    in_str = esc = False
    for c in line:
        if in_str:
            if esc:
                esc = False
            elif c == 0x5C:
                esc = True
            elif c == 0x22:
                in_str = False
        elif c == 0x22:
            in_str = True
        elif c == 0x5B or c == 0x7B:
            depth += 1
            if depth > limit:
                return True
        elif c == 0x5D or c == 0x7D:
            depth -= 1
    return False


def dump(obj: Any) -> str:
    """The compact, key-sorted dump, unchecked (what a reader compares a line's bytes against)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def jcs(obj: Any) -> str:
    """Checked canonical form: refuses what the ledger does not admit, then dumps."""
    check_value(obj, "$")
    return dump(obj)


def canonical_line(obj: Any) -> str:
    """The bytes (as text) of one ledger line: the dump of its object, no LF."""
    return dump(obj)
