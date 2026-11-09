"""styxx_ledger: a reference writer and verifier for the styxx ledger protocol v1 (PROTOCOL_v1.md).

The core (jcs, day, chain, verify) is what the shared vectors exercise; the writer (Ledger) and the CLI sit on it.
v0 reads protocol v0 ledgers (darkflobi.gate/*/v0); ots reads OpenTimestamps proofs natively (no dependency);
exhibit re-derives a published exhibit by url (the `exhibit` command).
"""
from ._version import __version__  # noqa: F401
from .jcs import LedgerValueError, MAX_DEPTH, check_value, depth_exceeds, dump, jcs, canonical_line  # noqa: F401
from .day import day_of, late_of, next_day, parse_timestamp, now_utc  # noqa: F401
from .chain import (  # noqa: F401
    LOG_SCHEMA, ENTRY_SCHEMA, HEADER_DOMAIN, core_of, entry_id_of, header_digest, check_header, make_header,
    build_entry, anchor_text, parse_anchor_text, read_bytes, read_log, check_chain, head_of,
)
from .verify import verify_bytes, check_anchor, coverage  # noqa: F401
from . import chain, exhibit, ots, v0  # noqa: F401
from .v0 import (  # noqa: F401
    V0_ENTRY_SCHEMA, header_digest_v0, verify_bytes_v0, parse_anchor_text_v0, check_anchor_v0, anchor_text_v0,
    detect_protocol, verify_auto,
)
from .writer import (  # noqa: F401
    Ledger, LedgerError, LedgerLocked, LedgerBroken, LedgerStateError, DEFAULT_WRITER, LOCK_STALE_S, pid_alive,
)
