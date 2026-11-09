"""day.py: a timestamp's calendar day in the header's anchor_tz (protocol v1, section 1), and the anchor's `late`
rule (section 5).

v1 timestamps are exactly `YYYY-MM-DDTHH:MM:SSZ` (UTC, no fraction, no offset, ascii digits only, years 1000 to
9998 so the day exists as a four-digit year in every zone). The day is read with the platform's zone database
(zoneinfo; on Windows that is the `tzdata` package, which the package declares). A zone name is admitted only when
it is, exactly and case for case, a name the database lists (zoneinfo.available_timezones()), and never "Factory".
There is no written fallback rule: a zone the database does not hold is refused (code anchor_tz), never
approximated. Codes: timestamp, anchor_tz, anchor_form.
"""
from __future__ import annotations

import datetime as _dt
import re
from functools import lru_cache

from .jcs import LedgerValueError

TIMESTAMP_RX = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z\Z")
DATE_RX = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
YEAR_MIN, YEAR_MAX = 1000, 9998
REFUSED_ZONES = ("Factory",)
LATE_AFTER = "00:10:00"   # an anchor written later than this, local, on the day after its date is late


def parse_timestamp(ts: object) -> _dt.datetime:
    """A v1 timestamp as an aware UTC datetime; LedgerValueError(code=timestamp) otherwise."""
    if not isinstance(ts, str):
        raise LedgerValueError("timestamp", "timestamp is not a string")
    m = TIMESTAMP_RX.fullmatch(ts)
    if not m:
        raise LedgerValueError("timestamp", "timestamp is not YYYY-MM-DDTHH:MM:SSZ: %r" % ts[:40])
    g = [int(x) for x in m.groups()]
    if not YEAR_MIN <= g[0] <= YEAR_MAX:
        raise LedgerValueError("timestamp", "timestamp year outside %d..%d: %r" % (YEAR_MIN, YEAR_MAX, ts))
    try:
        return _dt.datetime(*g, tzinfo=_dt.timezone.utc)
    except ValueError:
        raise LedgerValueError("timestamp", "timestamp names no calendar instant: %r" % ts) from None


@lru_cache(maxsize=1)
def _available() -> frozenset:
    import zoneinfo
    try:
        return frozenset(zoneinfo.available_timezones())
    except Exception:  # noqa: BLE001 - no database at all: every name is refused below
        return frozenset()


@lru_cache(maxsize=64)
def _zone(tz: str):
    import zoneinfo
    return zoneinfo.ZoneInfo(tz)


def zone(tz: object):
    """The ZoneInfo for an IANA name the database lists exactly; LedgerValueError(code=anchor_tz) otherwise."""
    if not isinstance(tz, str) or not tz or tz.startswith("/") or ".." in tz or tz in REFUSED_ZONES:
        raise LedgerValueError("anchor_tz", "anchor_tz is not an IANA zone name: %r" % (tz,))
    if tz not in _available():
        raise LedgerValueError("anchor_tz", "zone %r is not, case for case, a name in this platform's zone database" % (tz,))
    try:
        return _zone(tz)
    except Exception as e:  # noqa: BLE001 - ZoneInfoNotFoundError, ValueError, OSError
        raise LedgerValueError("anchor_tz", "zone %r not in this platform's zone database (%s)" % (tz, type(e).__name__)) from None


def _local(ts: str, tz: str) -> _dt.datetime:
    d = parse_timestamp(ts)
    z = zone(tz)
    try:
        return d.astimezone(z)
    except (OverflowError, ValueError):
        raise LedgerValueError("timestamp", "timestamp %r has no day in %s" % (ts, tz)) from None


def day_of(ts: str, tz: str) -> str:
    """The calendar day, YYYY-MM-DD, of a v1 timestamp in zone `tz`."""
    d = _local(ts, tz)
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def next_day(date: str) -> str:
    """The day after a YYYY-MM-DD date; LedgerValueError(anchor_form) when it is not a date."""
    m = DATE_RX.fullmatch(date) if isinstance(date, str) else None
    try:
        if not m:
            raise ValueError
        return (_dt.date(*(int(x) for x in m.groups())) + _dt.timedelta(days=1)).isoformat()
    except (ValueError, OverflowError):
        raise LedgerValueError("anchor_form", "not a YYYY-MM-DD date: %r" % (date,)) from None


def late_of(anchor_date: str, ts: str, tz: str) -> bool:
    """Section 5's rule for an anchor entry's `late`: the entry's own local day (in tz) is after the day following
    anchor_date, or is that following day with a local clock later than 00:10:00. The writer sets it; a caller
    does not. (darkflobi's v0 gate uses the same cutoff.)"""
    nd = next_day(anchor_date)
    d = _local(ts, tz)
    day = "%04d-%02d-%02d" % (d.year, d.month, d.day)
    clock = "%02d:%02d:%02d" % (d.hour, d.minute, d.second)
    return day > nd or (day == nd and clock > LATE_AFTER)


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
