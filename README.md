# styxx-ledger

a reference writer and verifier for the styxx ledger protocol v1 (`PROTOCOL_v1.md`), in python and in javascript.

## verify it yourself, from a checkout

darkflobi publishes its send ledger at https://fathom-lab.github.io/styxx/ledger/. one command fetches it and
re-derives it on your own machine, with no browser and no trust in the lab's page. neither package is on npm or pypi
yet, so run it from a clone:

    git clone https://github.com/fathom-lab/styxx-ledger && cd styxx-ledger
    node js/bin/styxx-ledger.cjs exhibit https://fathom-lab.github.io/styxx/ledger/     # javascript (node 20+), no install
    pip install ./python                                                                  # python (3.10+), in a venv
    styxx-ledger exhibit https://fathom-lab.github.io/styxx/ledger/

python without installing the package: on windows, `pip install tzdata` before anything else (python.org windows
builds carry no zone database; `pip install ./python` pulls it in), then `python -m styxx_ledger exhibit <url>` with
`python/src` on the path (`PYTHONPATH=python/src`; in powershell `$env:PYTHONPATH = "python/src"`). a python with no
zone database ends exit 2 with "this python has no zone database: pip install tzdata" and verifies nothing; it never
reports the chain as broken. the opentimestamps proofs are read natively, by code in each package.

after publication (not yet: as of 2026-11-09 both names answer 404 on npm and on pypi, so do not run these until the
lab has published them; whoever holds a name runs their code on the machine that types it):

    npx styxx-ledger exhibit https://fathom-lab.github.io/styxx/ledger/
    pip install styxx-ledger

what it fetches: `ledger.jsonl`, `withheld.json`, `anchors/index.json` and every anchor `.txt` and `.txt.ots` it names,
`witness/index.json` and a sample of the witness proofs (30 s timeout and a 20 MB cap per file). what it asks: two
block explorers, blockstream.info and mempool.space (`GET /block-height/<h>`, then `GET /block/<hash>`), for every
bitcoin block a proof names. what each line of the report means:

    chain            the ledger re-derives: lines (published + withheld), head, problem records; withheld lines are
                     bridged on the digests the publisher lists (their word for what they hold back); a withheld
                     record counts only when a later published line's prev names its digest, and a record that
                     names a published seq, or that no later line binds, fails the check
    anchors          each anchor text (the .txt) is the index's text, and holds against the chain under section 5 of
                     the v0 protocol: the line at its seq carries its head, no line of that day after it, the
                     ledger's own anchor entry agrees
    anchor proofs    each .ots commits to the .txt bytes and verifies natively: the digest at each bitcoin
                     attestation, byte-reversed, is that block's merkle root; the lowest verified block is the one
                     the index names (an index that names no block fails); each anchor's line gives the days from
                     its date to that block, marked late above 7. an anchor the index marks pending reads PEND, and
                     fails once its date is more than 7 days before the run
    coverage         how many published lines a holding anchor pins (section 6)
    age              the last holding anchor's date against the run day, and the lines after it that nothing pins
    witness index    every witness record names the chain's entry_id at its seq
    witness proofs   a seeded sample (seed = the ledger file's sha256; default 20, plus the earliest and latest
                     attested lines): each proof commits to its entry_id and verifies to the block and block time the
                     index states
    explorers        both explorers gave the same hash, merkle root and time for every block asked; when they do not,
                     every proof on that block is "explorers disagree: not verified". a block both explorers answer
                     404 for does not exist and the proof fails; one 404 against one header is disagreement. an
                     explorer still answering HTTP 429 after 5 tries (on its Retry-After, at most 60 s, else 2, 4, 8,
                     16 s) is named as rate-limited and left out for the run
    result           k of n checks; exit 0 every check passed, 1 any failed, 2 usage, or a file or an explorer did
                     not answer, or this python has no zone database (python only: "pip install tzdata")

flags (both): `--explorer <url>` (repeatable; replaces the default two; any esplora instance), `--sample <n>`,
`--no-ots` (no proof, no explorer), `--save <dir>` (keep every fetched byte and every explorer answer),
`--allow-redirect` (accept files served from another host; without it a redirect off the url's host, or off https,
fails), `--today <YYYY-MM-DD>` (the day the ages are counted against; default today in utc), `--json` (the full
record: every fetched file's url, final url, length and sha256, every explorer answer, every attestation).

the public explorers rate-limit. blockstream.info's own 429 notice caps unauthenticated use at 700 requests an hour
per ip; one run asks each explorer two calls per block, 28 for the exhibit's 14 blocks. a run that meets the limit
says which explorer rate-limited and ends exit 2 with nothing called verified; run again later, or pass
`--explorer` with another esplora instance (your own node's, for one).

read it this way:

- a proof attests that the bytes existed before a bitcoin block, not that they were published at a url or posted
  anywhere at a time.
- the anchor texts come from the lab's page; the telegram supergroup they were posted to needs an account to read.
- the block headers are the two explorers' word, compared with each other, not read from a bitcoin node; nothing is
  signed. the run is reproducible by anyone: the same url gives the same bytes and the same answers.
- a copy that is older but consistent passes every check here: compare the head and the last anchor date with the
  posts, and with a run of your own on another day. the report's age line says how old the last holding anchor is.

as read on this box (windows 11, 2026-11-09 05:28Z, both clis against the live exhibit, which had grown since the
04:16Z run of the same day):

    chain                792 lines = 787 published + 5 withheld, head 3f9fe35a...16cf3b (seq 792), 0 problem records
    anchors              15 of 15 texts hold against the chain; 15 of 15 .txt files are the index's text
    anchor proofs        14 of 15 verify: block 974530 x11, 974635, 974768, 975028 (each the index's block); the
                         15th, 2026-11-08, is pending as the index says (calendar receipts, no block yet: PEND)
    lag                  1 to 11 days from an anchor's date to its lowest block; 4 of 14 over 7 days (late)
    coverage             748 of 787 published lines pinned; 32 unpinned by withholding; 7 after the last anchor
    age                  last holding anchor 2026-11-08 (seq 785), 1 day before the run
    witness index        790 records (734 bitcoin, 56 pending) for 790 of 792 chain lines
    witness proofs       22 of 22 sampled (of 734 attested) commit and verify to block 975101
    explorers            14 of 14 blocks: blockstream.info and mempool.space agree on hash, merkle root and time
    result               68 of 69 checks passed, 1 pending, 0 failed, exit 0, in each cli (python 15.5 s, javascript
                         5.8 s wall clock)

an earlier run the same hour (04:55Z) met blockstream.info's rate limit after this box's review runs: 0 of 14 blocks
answered there, 36 of 66 checks could not be made, exit 2, nothing called verified (recorded in the lab's build log,
which this repository does not carry).

the two clis print the same report, line for line, apart from the implementation's name and the wall clock.

## the protocol

the protocol is the one darkflobi's send ledger has run under since 2026-10-24 (protocol v0), generalized to any
agent: one json line per event an agent's writer is handed, each line chained to the one before by sha256, a header
naming the agent, its zone and the kinds it may write, and once a day an anchor text

    <agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>

that the caller posts somewhere public. a stranger holding the file and the posts recomputes every digest; there is
no key.

    PROTOCOL_v1.md      the protocol: file, canonical form, chain, writer, verifier, anchor, publication, conformance
    vectors/            base_v1.jsonl + vectors_v1.json (118 vectors) and one runner per language
    python/             package styxx_ledger (pypi name styxx-ledger), writer + verifier + cli, pytest suite
    js/                 package styxx-ledger (npm), commonjs, writer + verifier + cli, node:test suite
    tools/              cross_verify.py: the two clis against each other's bytes
    ci.yml              written, not pushed (the lab's tokens cannot push .github/; the operator pastes it); 0 runs
                        as of 2026-11-09. it runs ubuntu + windows, python 3.10 / 3.12 / 3.13, node 20 / 22, the
                        census tests and the cross job once it is in .github/workflows/

## what it is not

- not a coverage claim: a writer records what it is handed. an event its caller never hands it leaves no line, and
  nothing here can tell. showing that every event got a line is a census of the destinations against the ledger,
  done by someone else.
- not a truth claim: no field is checked for what it says. the writer does not read content.
- not a signature: nothing is signed and nothing names who wrote a line beyond the `started` entry's own statement.
  the chain and the posted heads are the whole of what fixes the bytes.
- no network in the core packages: the anchor step composes the text and hands it back. each package reads
  opentimestamps proofs natively (`ots.py`, `lib/ots.js`: parse, walk, verify a bitcoin attestation against a block
  header the caller fetched); an optional helper shells out to an opentimestamps client, if one is installed, to
  stamp. neither package depends on it. the `exhibit` command (`exhibit.py`, `lib/exhibit.js`) is the one part that
  fetches: the exhibit's files over http(s) and block headers from the explorers named.

## counts, as read on this box

windows 11, 2026-11-08 and 09. ci has not run (the workflow is written, not pushed: 0 runs as of 2026-11-09), so
python 3.10 / 3.13 and node 20 / 22 carry no number here. one ubuntu leg was read by hand on this box under WSL on
2026-11-09 (ubuntu, python 3.12.3, no node; the kit-user pass of the lab's improvement sweep), python
package only: vectors 118 of 118 answered as the file says, and the live exhibit from the checkout 68 of 69 checks,
exit 0.

    vectors, python package (python 3.12.10, tzdata 2025.3)     118 of 118 answered as the file says
    vectors, javascript package (node 24.13.0)                   118 of 118 answered as the file says
    v0 vectors (vectors/v0, the exhibit's), python package        10 of 10 answered as the file says
    v0 vectors (vectors/v0, the exhibit's), javascript package    10 of 10 answered as the file says
    ots proofs (vectors/ots), each package, offline               36 of 36 agree with javascript-opentimestamps 0.4.9
    vectors, python 3.14.2 without tzdata                         exit 2, "this python has no zone database: pip
                                                                  install tzdata", 0 answered (58 of 118 before the
                                                                  2026-11-09 fix counted the missing database as misses)
    ots crafted proofs (vectors/ots/crafted), each package        10 of 10 answered as crafted.json says
    exhibit end to end, offline (local server, fake explorers)   cases a-e and the review-3e regressions f-m pass in
                                                                  each (31 pytest, 20 node tests)
    exhibit, both clis on one served copy, 14 cases               14 of 14 reports identical line for line
    exhibit, live (fathom-lab.github.io/styxx/ledger/)            68 of 69 checks, 1 pending, exit 0, in each cli
    pytest (python/), the ledger kit's tests                      365 passed of 365 collected without
                                                                  tests/test_census.py; 413 of 413 with it (2026-11-09)
    pytest census (the readme check, the red smoke)               9 passed of 9 (2026-11-09)
    node --test (js/)                                             94 passed of 94, 0 skipped
    tools/cross_verify.py                                         13 of 13 cross checks hold
    vectors/mutate_core.py (python core mutants)                  57 of 57 applied mutants killed

the cross checks: the same 41 cli calls through both command lines write byte-identical files (41 lines, sha256
`60033975...`); each cli verifies the other's file to the same head; every committed fixture verifies under the
cli of the language that did not write it. the vectors' expected values were computed once, by the python package;
the javascript package answers them on its own code. the mutation run covers the python core only.

## quickstart

python (`pip install ./python` from a checkout; not published):

    styxx-ledger init agent.jsonl --agent mybot --tz UTC \
        --certifies "one line per tool call mybot was handed; arguments hashed, never stored" --kinds tool_call
    styxx-ledger append agent.jsonl --kind tool_call --fields '{"tool":"search","args_sha256":"<64 hex>"}'
    styxx-ledger anchor-text agent.jsonl                          # after midnight in anchor_tz: yesterday's text
    styxx-ledger anchor-text agent.jsonl --date 2026-11-08 --record   # once posted: the anchor entry
    styxx-ledger verify agent.jsonl --anchor "mybot anchor 2026-11-08 head <64 hex> seq 41"

javascript (`node js/bin/styxx-ledger.cjs ...` from a checkout; not published): the same commands and flags.

| command | flags both clis take |
|---|---|
| `init <log>` | `--agent` `--tz` `--certifies` (all required), `--kinds a,b`, `--created <utc>`, `--timestamp <utc>` (the started entry's), `--no-started` / `--no-start` |
| `append <log>` | `--kind` (required), `--fields '<json>'`, `--fields-file <f>`, `--timestamp <utc>` |
| `verify <log>` | `--withheld <f>`, `--anchor '<text>'` (repeatable), `--anchors-file <f>`, `--json` |
| `anchor-text <log>` | `--date YYYY-MM-DD`, `--timestamp <utc>`, `--record` (without it nothing is written) |
| `head <log>` | — |
| `exhibit <url>` | `--explorer <url>` (repeatable), `--sample <n>`, `--no-ots`, `--save <dir>`, `--json` |

exit codes in both: 0 done / re-derives / every anchor holds; 1 refused, does not re-derive, or an anchor does not
hold; 2 usage or i/o (`exhibit`: 0 every check passed, 1 any failed, 2 usage, or a file or an explorer did not
answer). differences that remain: `append` prints a summary in python and the written line in
javascript; javascript also takes `--field k=v`; python also takes `--fields -` (stdin), `--json` on `append` and
`head`, and `--max-problems` on `verify`; javascript accepts `--anchors-file` as a json array too. an anchor
entry's `late` is section 5's rule in both, never a flag.

## darkflobi's own ledger

v0 remains v0. darkflobi's ledger keeps its `darkflobi.gate/*/v0` schema strings and its own verifier; the v1
writer never writes v0 and the v1 functions (`verify_bytes`, `verifyBytesSync`) do not read it (`no_header`, "this
verifier reads v1 only"). each package also has a v0 read mode (`styxx_ledger.v0`, `lib/v0.js`): `verify` picks it
from the header's schema and applies the exhibit verify.js's rules (the `darkflobi.gate/log/v0` domain, the fixed
anchor word `gate`, no kinds check, the day as verify.js reads it); both answer the exhibit's 10 v0 vectors
(`vectors/v0/`, copied byte for byte). `PROTOCOL_v1.md` lists exactly what changed from v0, and separately what was
decided in the review pass.

## forbidden claims

no text about this protocol or these packages, here or anywhere they are described, says:

- "stdlib-only" or "dependency-free" (the python package needs `tzdata` on windows; the optional timestamp client
  has its own dependencies);
- "gate your agent in a day", or any zero-to-anchored time;
- "first", "no one", "provably", "independent";
- that a ledger shows every event got a line, that a line is true, or who wrote it.

every count printed about the packages carries its denominator: k of n vectors, per implementation, per os.

## license

MIT (`LICENSE`).
