# styxx-ledger (python)

a reference writer and verifier for the styxx ledger protocol v1
([PROTOCOL_v1.md](https://github.com/fathom-lab/styxx-ledger/blob/main/PROTOCOL_v1.md)): one json line per event an
agent's writer is handed, each line chained to the one before by sha256, a header naming the agent and the kinds it
may write, and once a day an anchor text (`<agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>`) for the caller to post
somewhere public. a stranger holding the file and the posts recomputes everything; nothing is signed.

this is the python half. the javascript half is [js/](https://github.com/fathom-lab/styxx-ledger/tree/main/js); both
are held to [vectors/vectors_v1.json](https://github.com/fathom-lab/styxx-ledger/blob/main/vectors/vectors_v1.json).
the package carries the code, this readme and the license; the protocol, the vectors, the tests and the fixtures
this page names are in the repository (https://github.com/fathom-lab/styxx-ledger), which its links point at.

## what it is not

- not a coverage claim: the writer records what it is handed. an event the caller never hands it leaves no trace.
- not a truth claim: no field is checked for what it says. the writer does not read content.
- not a signature: the chain and the posted heads are the whole of what fixes the bytes.
- not a writer of protocol v0 (darkflobi's own ledger, `darkflobi.gate/log/v0`): v0 remains v0. `verify_bytes` reads
  v1 only (`no_header`, "this verifier reads v1 only"); the v0 read mode is separate (below).

## install

from the root of a checkout (`git clone https://github.com/fathom-lab/styxx-ledger`, then `cd styxx-ledger`), into
a venv:

    python3 -m venv .venv
    .venv/bin/python -m pip install ./python

on windows the two lines read `python -m venv .venv` and `.venv\Scripts\python -m pip install ./python`. on ubuntu,
run `sudo apt install python3-venv` before them: there python3 has no pip, `python3 -m venv` fails without that
package ("ensurepip is not available"), and a `pip install` outside a venv is refused (pep 668; read on ubuntu 24.04
under WSL, 2026-11-09). the cli is then `.venv/bin/styxx-ledger` (`.venv\Scripts\styxx-ledger`), or `styxx-ledger`
once the venv is activated. after publication only (the name is not on pypi: 404 as of 2026-11-09):
`pip install styxx-ledger`.

runtime requirements: python >= 3.10 and, on windows only, the `tzdata` package (declared in pyproject, installed with
the package). windows python has no iana zone database of its own. without `tzdata` no day can be read: the verifier
raises `ZoneDatabaseMissing` (never a problem record), and the cli and the vectors runner end exit 2 with "this python
has no zone database: pip install tzdata" (read on this box with python 3.14.2, which has no tzdata, 2026-11-09;
before that fix every named zone was refused as `anchor_tz` and 60 of the 118 vectors missed).

## quickstart (cli)

    styxx-ledger init agent.jsonl --agent mybot --tz America/New_York --certifies "one line per message mybot sent, chained; hashes, never message text" --kinds note,send
    styxx-ledger append agent.jsonl --kind send --field to_sha256=c307eaf7779f92fcaed883b323596060d8cd0fd88d4688b95689d51a854ccb66 --field channel=general
    styxx-ledger anchor-text agent.jsonl                 # yesterday's text on stdout; nothing written
    styxx-ledger anchor-text agent.jsonl --date 2026-11-08 --record     # after posting it: the anchor entry
    styxx-ledger verify agent.jsonl --anchor "mybot anchor 2026-11-08 head <64 hex> seq 41"
    styxx-ledger head agent.jsonl

`python -m styxx_ledger` is the same command. `init` writes the header and a `started` entry (`--no-started` for the
header alone; `--no-start` is the same flag); `--tz` is required; `anchor` and `started` are always added to
`--kinds`. each quickstart line is one command with no json in it, so it reads the same in bash and in windows
powershell 5.1. `--field k=v` (repeatable) sets one string field, after `--fields`, as in the javascript cli; a
field that is not a string needs json: `--fields '{"bytes":512}'` in bash, `--fields-file <f>` in powershell 5.1,
which strips the double quotes inside an argument (write the file with `Set-Content -Encoding ascii`: its utf8 adds
a byte order mark, refused as not json). `--fields -` reads the object from stdin. `anchor-text` writes nothing
unless `--record` is given, and the anchor entry's `late` is section 5's rule (written after 00:10:00 local on the
day after its date, or on a later day), never a flag. with or without `--record` it refuses, exit 1, a day that
has not closed in anchor_tz (`refused (day_open)`), a day already anchored (`already_anchored`) and a day with no
entry (`nothing_to_anchor`), as the javascript cli does; until 2026-11-09 it composed a postable text for an open
day or an anchored one, which the day's next line then broke. `--certifies` is refused when it is whitespace only,
whitespace being the 30 code points PROTOCOL_v1.md section 1 lists, and an empty `--kinds` item is refused, never
dropped.
`verify` takes `--withheld withheld.json` (`[{seq, entry_id, reason}]`) and bridges the chain through those seqs on
their published digests, `--anchor` (repeatable) or `--anchors-file`, and `--json`; with anchors or a withheld list it
prints the coverage line (how many published entries the holding anchors pin, how many withholding leaves unpinned,
how many sit after the last anchor).

exit codes: 0 done / re-derives / every anchor holds; 1 refused, does not re-derive, or an anchor does not hold;
2 usage or i/o error. `exhibit <url>` (below) fetches a published exhibit and re-derives it.

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

## protocol v0 (read only)

v0 read mode: `verify` reads the header's schema. a `darkflobi.gate/log/v0` file (darkflobi's own ledger) is read
under v0's rules, the exhibit verify.js's: the domain `darkflobi.gate/log/v0`, the fixed anchor word `gate`, no kinds
check, the day as verify.js reads it in the header's `anchor_tz`; everything else is v1's. `--protocol v1` forces
v1 (and a v0 file then gets `no_header`, "this verifier reads v1 only"). the exhibit's 10 v0 vectors are
[vectors/v0/](https://github.com/fathom-lab/styxx-ledger/tree/main/vectors/v0) in the repository, byte for byte, and both
packages answer 10 of 10. the writer stays v1 only.

```python
from styxx_ledger import detect_protocol, verify_auto, parse_anchor_text_v0, check_anchor_v0
r = verify_auto(raw, withheld)          # r["protocol"] is "v0" or "v1"
check_anchor_v0(r["entries"], parse_anchor_text_v0("gate anchor 2026-11-07 head <64 hex> seq 729"), withheld)["ok"]
```

## opentimestamps proofs (native)

`styxx_ledger.ots` reads `.ots` files with no opentimestamps library: `parse_ots(data)`, `attestations(proof)`,
`verify_bitcoin(digest, {merkle_root, timestamp})`, and `verify_proof(data, target=bytes | digest=hex,
get_header=fn)`, which returns a status (`verified`, `pending`, `unverified`, `failed`, `commitment_mismatch`,
`refused` with a code, `no_attestation`), each bitcoin attestation with its height and attested time, and the lowest.
it never fetches: `get_header(height)` is the caller's (an explorer, a node, a fixture). a bitcoin attestation shows
the stamped bytes existed before that block, not that they were published anywhere. sha256, sha1 and ripemd160 come
from hashlib (`ots.ripemd160_available()` says whether this python's OpenSSL has ripemd160; a proof that needs it is
refused with `ripemd160_unavailable` otherwise); keccak256 is implemented in the module. on the 14 anchor proofs and
22 witness proofs in [vectors/ots/](https://github.com/fathom-lab/styxx-ledger/tree/main/vectors/ots) it agrees, offline, with
javascript-opentimestamps 0.4.9 on every height, attested time and digest.

stamping (optional): `styxx_ledger.ots.stamp_text(text, path)` writes the exact anchor text to a file and runs
`ots stamp` on it when an `ots` client is on PATH (`pip install opentimestamps-client`); the client talks to the
calendars, this package does no network. not a dependency, not required, not exercised by the suite.

## exhibit: re-derive a published exhibit by url

    styxx-ledger exhibit https://fathom-lab.github.io/styxx/ledger/
    styxx-ledger exhibit <url> [--explorer <esplora api url> ...] [--sample <n>] [--no-ots] [--save <dir>]
                       [--allow-redirect] [--today <YYYY-MM-DD>] [--json]

fetches `ledger.jsonl`, `withheld.json`, `anchors/index.json` (and every `.txt` / `.txt.ots` it names) and
`witness/index.json` from the base url (urllib, 30 s per file, 20 MB cap, 3 tries on 5xx / no answer), then
re-derives the chain (v0 or v1 by the header), checks each anchor `.txt` against the index and against the chain
(section 5), verifies each anchor proof natively against bitcoin block headers asked of every `--explorer` (default
`https://blockstream.info/api` and `https://mempool.space/api`; all must give the same hash, merkle root and time, or
the block is "explorers disagree: not verified"), checks that every witness record names the chain's entry_id at its
seq, and verifies a seeded sample of witness proofs (seed = the ledger file's sha256; `--sample` of them, default 20,
plus the earliest and latest attested lines) to the block and block time the index states. the text report carries
every count with its denominator; `--json` is the full record (each fetched file's url, length, sha256; each explorer
answer; each attestation). `--save` keeps the fetched bytes and the explorers' answers. exit 0 every check passed, 1
any failed, 2 usage, or a file or an explorer did not answer. a url with no ledger.jsonl behind it (a 404) is exit
2, with the url fetched and "check that the url names the exhibit's folder", never a failed check; an explorer that
does not answer is named once, near the top, with the reason ("the connection was refused", "the host name did not
resolve (dns)", ...: the javascript cli uses the same words), and the checks it left unmade are counted on one
line. in code: `styxx_ledger.exhibit.run_exhibit(url, ...)`
(the fetch is injectable: `get=fn(url) -> (status, bytes[, final url])`) and `render_text(report)`.

a withheld record counts only when a later published line's prev names its digest (one naming a published seq, or
one no later line binds, fails); an index that names no block for a verified proof fails; a block every explorer
answers 404 for fails the proof, one 404 against one header is disagreement; an explorer still answering 429 after 5
tries (its Retry-After, capped at 60 s, else 2, 4, 8, 16 s) is named as rate-limited and left out; a file served from
another host (a redirect off the url's host or off https) fails unless `--allow-redirect`. the report gives each
anchor's lag from its date to its lowest block (late above 7 days), the last holding anchor's age against the run
day (`--today` sets it), and an anchor the index marks pending reads PEND until 7 days after its date, then fails.
the public explorers rate-limit (blockstream.info's notice: 700 requests an hour per ip, unauthenticated); one run
asks each explorer 28 times for the exhibit's 14 blocks.

a proof attests that bytes existed before a block, not that they were published at a url; the anchor texts come from
the lab's page (the supergroup they were posted to needs an account); the headers are the explorers' word; nothing is
signed; a copy that is older but consistent passes every check (compare the head and the last anchor date with the
posts, and with a run of your own on another day). the javascript cli prints the same report line for line (apart
from its name and the wall clock).

## tests and counts

from the root of a checkout (the tests and the vectors are in the repository, not in the package), with the venv
above activated, so `python` is its python, after `pip install "./python[test]"` in it (pytest), and, for the tests
that run both clis, node on PATH:

    python -B vectors/run_vectors.py
    cd python
    python -B -m pytest -q

as read on this box (windows 11, python 3.12.10, tzdata 2025.3, 2026-11-08 and 09):

    vectors (run_vectors.py)          145 of 145 vectors answered as the file says (2026-11-09; 118 of 118 before
                                      27 write-side cases were added)
    v0 vectors (run_vectors.py)       10 of 10 v0 vectors answered as the file says
    vectors, python 3.14.2, no tzdata exit 2, "pip install tzdata" (58 of 118 before the 2026-11-09 fix)
    pytest                            541 passed of 541, what `python -B -m pytest -q` in python/ prints with node
                                      on PATH (with no node: 523 passed, 18 skipped); 472 of 472 without
                                      tests/test_census.py (2026-11-09, after the improvement sweep; the 472 include
                                      tests/test_zone_database.py 12, tests/test_v0.py 37, tests/test_ots.py 73,
                                      tests/test_exhibit.py 45: cases a-e, the review-3e regressions and the
                                      sweep's n-p against a local server, tests/test_writer_rules.py 42,
                                      tests/test_cli_parity.py 15, which runs both clis and skips without node,
                                      and tests/test_packaging.py 7: the license copies, the pyproject's license
                                      form and registry fields, the package readmes' links, the kit's .gitignore)
    exhibit, live, 2026-11-09 05:28Z  68 of 69 checks, 1 pending (the 2026-11-08 anchor, as the index says), exit
                                      0; 14 of 15 anchor proofs, 22 of 22 witness proofs verify; 2 explorers agree
                                      on 14 of 14 blocks (15.5 s wall clock)
    of those, cross tests             5 of 5: the python fixture re-written byte for byte; each of the 3
                                      js/tests/fixtures/*.jsonl (js_written, js_cli_written, mixed_written)
                                      re-derives here with the head and sha256 its sidecar names, and its anchors
                                      hold; py_written.jsonl and a fresh log verify under node's js/lib/verify.js
                                      with the same head

the pytest count includes the 145 vectors once more, one case each. without js/ present the js cross tests skip
and say why. ci has not run (the workflow is written, not pushed: 0 runs as of 2026-11-09), so python 3.10 / 3.13
carry no number here; one ubuntu leg was read by hand on this box under WSL on 2026-11-09 (python 3.12.3): vectors
118 of 118 answered as the file says, and 145 of 145 after the additions the same day. pytest was not run on that
leg.

the cross tests: `tests/fixtures/py_written.jsonl` (12 entries, agent pybot, Europe/Berlin across the 2026-10-25 dst
end, 2 anchors, 1 of them late) is what `tests/make_fixture.py` writes with the Ledger class; the javascript suite verifies it and must
state the head in `py_written.json`. every `js/tests/fixtures/*.jsonl` is verified here the same way, and when node
and `js/lib/verify.js` are present, a log python writes during the run is verified by the javascript verifier.

## forbidden claims

these sentences are not made about this package, here or anywhere it is described: "stdlib-only", "dependency-free",
"gate your agent in a day", any zero-to-anchored time, "first", "no one", "provably", "independent".
