# styxx-ledger (python)

a reference writer and verifier for the styxx ledger protocol v1 (`../PROTOCOL_v1.md`): one json line per event an
agent's writer is handed, each line chained to the one before by sha256, a header naming the agent and the kinds it
may write, and once a day an anchor text (`<agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>`) for the caller to post
somewhere public. a stranger holding the file and the posts recomputes everything; nothing is signed.

this is the python half. the javascript half is `../js/`; both are held to `../vectors/vectors_v1.json`.

## what it is not

- not a coverage claim: the writer records what it is handed. an event the caller never hands it leaves no trace.
- not a truth claim: no field is checked for what it says. the writer does not read content.
- not a signature: the chain and the posted heads are the whole of what fixes the bytes.
- not a reader of protocol v0 (darkflobi's own ledger, `darkflobi.gate/log/v0`): v0 remains v0. given a v0 file the
  verifier reports `no_header` with the words "this verifier reads v1 only".

## install

    pip install styxx-ledger            # not published yet; from a checkout: pip install ./python

runtime requirements: python >= 3.10 and, on windows only, the `tzdata` package (declared in pyproject, installed with
the package). windows python has no iana zone database of its own; without `tzdata` every named zone is refused
(code `anchor_tz`) and 60 of the 118 vectors miss (read on this box with python 3.14.2, which has no tzdata).

## quickstart (cli)

    styxx-ledger init agent.jsonl --agent mybot --tz America/New_York \
        --certifies "one line per message mybot sent, chained; hashes, never message text" --kinds note,send
    styxx-ledger append agent.jsonl --kind send --fields '{"to_sha256":"<64 hex>","bytes":512}'
    styxx-ledger anchor-text agent.jsonl                 # yesterday's text on stdout; nothing written
    styxx-ledger anchor-text agent.jsonl --date 2026-11-08 --record     # after posting it: the anchor entry
    styxx-ledger verify agent.jsonl --anchor "mybot anchor 2026-11-08 head <64 hex> seq 41"
    styxx-ledger head agent.jsonl

`python -m styxx_ledger` is the same command. `init` writes the header and a `started` entry (`--no-started` for the
header alone; `--no-start` is the same flag); `--tz` is required; `anchor` and `started` are always added to
`--kinds`. `--fields -` reads the object from stdin. `anchor-text` writes nothing unless `--record` is given, and the
anchor entry's `late` is section 5's rule (written after 00:10:00 local on the day after its date, or on a later
day), never a flag.
`verify` takes `--withheld withheld.json` (`[{seq, entry_id, reason}]`) and bridges the chain through those seqs on
their published digests, `--anchor` (repeatable) or `--anchors-file`, and `--json`; with anchors or a withheld list it
prints the coverage line (how many published entries the holding anchors pin, how many withholding leaves unpinned,
how many sit after the last anchor).

exit codes: 0 done / re-derives / every anchor holds; 1 refused, does not re-derive, or an anchor does not hold;
2 usage or i/o error.

## quickstart (python)

```python
from styxx_ledger import Ledger, verify_bytes, parse_anchor_text, check_anchor

led = Ledger.create("agent.jsonl", agent="mybot", anchor_tz="UTC",
                    certifies="one line per tool call mybot made, chained; arguments hashed", kinds=["tool_call"])
led.start()                                             # {"writer": {"name", "version", "language"}}
led.append("tool_call", {"tool": "search", "args_sha256": "<64 hex>"})
a = led.compose_anchor()                                # {"agent","date","head","seq","text"}; post a["text"]
led.append_anchor(a["date"])                            # then record it

r = verify_bytes(open("agent.jsonl", "rb").read())
r["ok"], r["head"], r["problems"]
check_anchor(r["entries"], parse_anchor_text(a["text"]), [], r["header"])["ok"]
```

## the writer (protocol section 3b)

an append takes `<log>.lock` beside the log (create-exclusive, holding the pid), re-reads the whole file and
re-derives it, takes seq and prev from the tail, writes the canonical line and one lf, fsyncs, checks the file grew by
exactly those bytes, and releases the lock. it refuses, appending nothing:

- a file that does not re-derive (`LedgerBroken`, carrying the verifier's problem records), or whose last byte is not
  lf (a torn write: `tail_no_lf`);
- a value the canonical form does not admit, and the composition refusals (`LedgerValueError`, `.code` one of
  `float`, `int_range`, `non_ascii_key`, `lone_surrogate`, `type`, `reserved_field`, `kind_not_declared`,
  `started_writer`, `anchor_form`, `timestamp`, `anchor_tz`, `header_form`);
- an anchor for a day not yet closed in `anchor_tz`, a day already anchored, a day with no entry, and an entry whose
  day is a day already anchored (a backdated timestamp would sit after that day's posted head): `LedgerStateError`.

a lock older than 30 s whose pid is not a live process is broken once, under a breaker file; the append then writes a
`lock_recovered` entry before its own only when the header lists `lock_recovered`. a lock held by a live writer is
waited on for `lock_timeout_s` (10 s) and then `LedgerLocked`. on windows a lock file that another process has open
for a moment cannot be unlinked or re-created; the writer reads that as contention and retries (the suite's
concurrent-writer test, 6 processes and 120 appends, found it: the first version crashed on release).

`timestamp=` on the writing calls is for reproducible logs; without it the utc clock is used, which is the writer's
statement, not evidence of order. `day` is read with `zoneinfo`.

## opentimestamps (optional)

`styxx_ledger.ots.stamp_text(text, path)` writes the exact anchor text to a file and runs `ots stamp` on it when an
`ots` client is on PATH (`pip install opentimestamps-client`); the client talks to the calendars, this package does
no network. not a dependency, not required, not exercised by the suite.

## tests and counts

    cd python
    python -B -m pytest -q
    python -B ../vectors/run_vectors.py

as read on this box (windows 11, python 3.12.10, tzdata 2025.3, 2026-11-08):

    vectors (run_vectors.py)          118 of 118 vectors answered as the file says
    vectors, python 3.14.2, no tzdata 58 of 118 (the windows zone database is the tzdata package)
    pytest                            212 passed of 212 collected
    of those, cross tests             5 of 5: the python fixture re-written byte for byte; each of the 3
                                      js/tests/fixtures/*.jsonl (js_written, js_cli_written, mixed_written)
                                      re-derives here with the head and sha256 its sidecar names, and its anchors
                                      hold; py_written.jsonl and a fresh log verify under node's js/lib/verify.js
                                      with the same head

the pytest count includes the 118 vectors once more, one case each. without js/ present the two js cross tests skip
and say why. ubuntu counts come from ci, not from this box.

the cross tests: `tests/fixtures/py_written.jsonl` (12 entries, agent pybot, Europe/Berlin across the 2026-10-25 dst
end, 2 anchors, 1 of them late) is what `tests/make_fixture.py` writes with the Ledger class; the javascript suite verifies it and must
state the head in `py_written.json`. every `js/tests/fixtures/*.jsonl` is verified here the same way, and when node
and `js/lib/verify.js` are present, a log python writes during the run is verified by the javascript verifier.

## forbidden claims

these sentences are not made about this package, here or anywhere it is described: "stdlib-only", "dependency-free",
"gate your agent in a day", any zero-to-anchored time, "first", "no one", "provably", "independent".
