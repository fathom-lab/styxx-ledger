# styxx-ledger

a reference writer and verifier for the styxx ledger protocol v1 (`PROTOCOL_v1.md`), in python and in javascript.

## verify it yourself, from a checkout

darkflobi publishes its send ledger at https://fathom-lab.github.io/styxx/ledger/. one command fetches it and
re-derives it on your own machine, with no browser and no trust in the lab's page. neither package is on npm or pypi
yet, so run it from a clone. each route below starts in the folder you cloned into, and opens with the `cd` it
needs; each line is one command (windows powershell 5.1 has no `&&`):

    git clone https://github.com/fathom-lab/styxx-ledger

javascript (node 20+), no install. `js/bin/...` is relative to the root of the clone:

    cd styxx-ledger
    node js/bin/styxx-ledger.cjs exhibit https://fathom-lab.github.io/styxx/ledger/

python (3.10+), installed in a venv. `./python` is relative to the root of the clone. on ubuntu, run
`sudo apt install python3-venv` before these lines: there python3 has no pip, `python3 -m venv` fails without that
package ("ensurepip is not available"), and the system python is marked externally managed (pep 668), so a
`pip install` outside a venv is refused (read on ubuntu 24.04, python 3.12.3, under WSL, 2026-11-09):

    cd styxx-ledger
    python3 -m venv .venv
    .venv/bin/python -m pip install ./python
    .venv/bin/styxx-ledger exhibit https://fathom-lab.github.io/styxx/ledger/

on windows the same four lines read `cd styxx-ledger`, `python -m venv .venv`, `.venv\Scripts\python -m pip install
./python` and `.venv\Scripts\styxx-ledger exhibit <url>`; the install pulls in tzdata, the zone database windows
python lacks. once the venv is activated (`. .venv/bin/activate`; in powershell `.venv\Scripts\Activate.ps1`, where
scripts are allowed), `python`, `pip` and `styxx-ledger` are the venv's, as the quickstart and the tests below write
them.

python without installing. `PYTHONPATH=python/src` is relative, so it holds at the root of the clone only; on windows,
`pip install tzdata` before anything else (python.org windows builds carry no zone database):

    cd styxx-ledger
    PYTHONPATH=python/src python3 -m styxx_ledger exhibit https://fathom-lab.github.io/styxx/ledger/

in windows powershell the second line is two: `$env:PYTHONPATH = "python/src"`, then
`python -m styxx_ledger exhibit <url>` (on windows `python3` is usually the microsoft store's stub, not a python). a
python with no zone database ends exit 2 with "this python has no zone database: pip install tzdata" and verifies
nothing; it never reports the chain as broken. the opentimestamps proofs are read natively, by code in each package.

javascript from the packed package, in `js/`: npx reads `./` from where it runs, so at the root of the clone the same
line ends `npm error enoent`. `npm pack` prints the tarball's name (the version in `js/package.json`):

    cd styxx-ledger/js
    npm pack
    npx --package=./styxx-ledger-1.0.0-alpha.3.tgz styxx-ledger exhibit https://fathom-lab.github.io/styxx/ledger/

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
                     fails once its date is more than 7 days before the run; an anchor whose proof could not be
                     checked (the explorers did not all answer) reads ----, never FAIL
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
                     not answer, or this python has no zone database (python only: "pip install tzdata"). a url
                     with no ledger.jsonl behind it (a 404: a typo, or a folder that is not the exhibit's) is exit
                     2, with the url fetched and what to check, never the exit of a failed check; an explorer that
                     does not answer is named once, with the reason, near the top

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

the two clis print the same report, line for line, apart from the implementation's name and the wall clock. since
2026-11-09 that holds on the error paths too: a network failure reads in one shared wording in both (for example
"the host name did not resolve (dns)", "the connection was refused"), where python printed
`URLError: [Errno 11001] getaddrinfo failed` and javascript `TypeError: ENOTFOUND`.

## the protocol

the protocol is the one darkflobi's send ledger has run under since 2026-10-24 (protocol v0), generalized to any
agent: one json line per event an agent's writer is handed, each line chained to the one before by sha256, a header
naming the agent, its zone and the kinds it may write, and once a day an anchor text

    <agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>

that the caller posts somewhere public. a stranger holding the file and the posts recomputes every digest; there is
no key.

    PROTOCOL_v1.md      the protocol: file, canonical form, chain, writer, verifier, anchor, publication, conformance
    vectors/            base_v1.jsonl + vectors_v1.json (145 vectors) and one runner per language
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

## run the tests

from the root of a checkout, with node 20+ on PATH and the venv above activated (so `python` is the venv's, ubuntu
included, where the system has only `python3`), after `pip install "./python[test]"` in it (pytest, and on windows
tzdata). each `cd` starts from where the line before it left you; nothing below writes into the checkout (`-B`, and
`-p no:cacheprovider`, which the python suite's pyproject also sets):

    python -B vectors/run_vectors.py
    node vectors/run_vectors.mjs
    python -B vectors/make_vectors.py --check
    python -B tools/cross_verify.py
    cd python
    python -B -m pytest -q
    cd ../js
    node --test
    cd ../census
    python -B -m pytest -q -p no:cacheprovider

what each printed on this box (windows 11, python 3.12.10 with tzdata 2025.3, node 24.13.0, 2026-11-09), every one
exit 0:

    run_vectors.py              145 of 145 vectors answered as the file says, and 10 of 10 v0 vectors
    run_vectors.mjs             the same 145 of 145 and 10 of 10, on the javascript package's own code
    make_vectors.py --check     {"differs": [], "read": 32, "write": 113}: the vectors file is what its generator writes
    cross_verify.py             13 of 13 cross checks hold (it runs both clis, so it needs node)
    pytest, in python/          541 passed of 541; with no node on PATH, 523 passed and 18 skipped of 541 (the tests
                                that run both clis or the javascript verifier)
    node --test, in js/         109 of 109 pass, 0 skipped
    pytest, in census/          10 passed of 10: the readme check (9) and the red smoke (1), which reads a live url and
                                skips, never fails, when that url does not answer. that is why census/ is outside the
                                python suite's testpaths and is its own command.

## counts, as read on this box

windows 11, 2026-11-08 and 09. ci has not run (the workflow is written, not pushed: 0 runs as of 2026-11-09), so
python 3.10 / 3.13 and node 20 / 22 carry no number here. one ubuntu leg was read by hand on this box under WSL on
2026-11-09 (ubuntu, python 3.12.3, no node; the kit-user pass of the lab's improvement sweep), python
package only: vectors 118 of 118 answered as the file says, and the live exhibit from the checkout 68 of 69 checks,
exit 0; after the vectors file grew to 145 the same day, the same leg (ubuntu 24.04.4): 145 of 145.

    vectors, python package (python 3.12.10, tzdata 2025.3)     145 of 145 answered as the file says (2026-11-09;
                                                                  118 of 118 before 27 write-side cases were added)
    vectors, javascript package (node 24.13.0)                   145 of 145 answered as the file says (the same)
    v0 vectors (vectors/v0, the exhibit's), python package        10 of 10 answered as the file says
    v0 vectors (vectors/v0, the exhibit's), javascript package    10 of 10 answered as the file says
    ots proofs (vectors/ots), each package, offline               36 of 36 agree with javascript-opentimestamps 0.4.9
    vectors, python 3.14.2 without tzdata                         exit 2, "this python has no zone database: pip
                                                                  install tzdata", 0 answered (58 of 118 before the
                                                                  2026-11-09 fix counted the missing database as misses)
    ots crafted proofs (vectors/ots/crafted), each package        10 of 10 answered as crafted.json says
    exhibit end to end, offline (local server, fake explorers)   cases a-e, the review-3e regressions f-m, and n-p (an
                                                                  explorer that does not answer, a mistyped url, the
                                                                  network wordings; 2026-11-09) pass in each (45
                                                                  pytest, 23 node tests)
    exhibit, both clis on one served copy, 14 cases               14 of 14 reports identical line for line
    exhibit error paths, both clis on one served copy             2 of 2 reports identical line for line, exit 2 in
                                                                  each: a mistyped url, an explorer that does not
                                                                  answer (2026-11-09, python/tests/test_cli_parity.py)
    exhibit, live (fathom-lab.github.io/styxx/ledger/)            68 of 69 checks, 1 pending, exit 0, in each cli
    pytest (python/), the ledger kit's tests                      541 passed of 541, what `python -m pytest -q` in
                                                                  python/ collects (2026-11-09); 472 of 472 without
                                                                  tests/test_census.py; with no node on PATH, 523
                                                                  passed and 18 skipped of 541
    pytest census (the readme check, the red smoke)               10 passed of 10 (2026-11-09; the red smoke skips
                                                                  when its url does not answer)
    node --test (js/)                                             109 passed of 109, 0 skipped (2026-11-09)
    tools/cross_verify.py                                         13 of 13 cross checks hold
    packages, built offline (setuptools 84.2.1, npm 11.6.2)       the wheel carries licenses/LICENSE and says
                                                                  License-Expression: MIT, the sdist carries LICENSE,
                                                                  no setuptools deprecation warning (the pyproject at
                                                                  26cce4d printed the one dated 2027-Feb-18 and put no
                                                                  license in the wheel); npm pack: 13 files with
                                                                  LICENSE (12 before, none the license) (2026-11-09)
    the venv route above, offline (a local wheelhouse for pypi)   windows python 3.14.2 and ubuntu 24.04.4 python 3.12.3
                                                                  under WSL: pip install ./python exit 0, verify of a
                                                                  fixture exit 0, vectors 145 of 145 from the venv's
                                                                  python (2026-11-09). on that ubuntu `python3 -m venv`
                                                                  exits 1 until python3-venv is installed; the run
                                                                  stood in for it with --without-pip and python's own
                                                                  bundled pip wheel
    vectors/mutate_core.py (python core mutants)                  67 of 67 applied mutants killed (2026-11-09; 57 of
                                                                  57 before 10 were written for the new cases)

the cross checks: the same 41 cli calls through both command lines write byte-identical files (41 lines, sha256
`60033975...`); each cli verifies the other's file to the same head; every committed fixture verifies under the
cli of the language that did not write it. the vectors' expected values were computed once, by the python package;
the javascript package answers them on its own code. the mutation run covers the python core only.

## quickstart

python (installed from a checkout into a venv, as above; not published; `styxx-ledger` here is the venv's: activate
it, or call `.venv/bin/styxx-ledger`, on windows `.venv\Scripts\styxx-ledger`). one command per line, with no line
continuation and no json on the command line, so each line reads the same in bash, zsh and windows powershell 5.1:

    styxx-ledger init agent.jsonl --agent mybot --tz UTC --certifies "one line per tool call mybot was handed; arguments hashed, never stored" --kinds tool_call
    styxx-ledger append agent.jsonl --kind tool_call --field tool=search --field args_sha256=c307eaf7779f92fcaed883b323596060d8cd0fd88d4688b95689d51a854ccb66
    styxx-ledger anchor-text agent.jsonl                          # after midnight in anchor_tz: yesterday's text
    styxx-ledger anchor-text agent.jsonl --date 2026-11-08 --record   # once posted: the anchor entry
    styxx-ledger verify agent.jsonl --anchor "mybot anchor 2026-11-08 head <64 hex> seq 41"

`--field k=v` sets one string field (repeatable). a field that is not a string (an integer, a list, an object) needs
json: in bash or zsh, `--fields '{"tool":"search","n":2}'`. windows powershell 5.1 strips the double quotes inside
that argument, and both clis then exit 2 with "--fields is not json"; there, write the json to a file as ascii (its
`-Encoding utf8` writes a byte order mark, which both clis refuse as not json) and pass the file:

    Set-Content -Path fields.json -Encoding ascii -Value '{"tool":"search","n":2}'
    styxx-ledger append agent.jsonl --kind tool_call --fields-file fields.json

read on this box in windows powershell 5.1, 2026-11-09, both clis: the `init` and `append` lines above and the
`Set-Content` route exit 0; the earlier `--fields '{...}'` line and a `-Encoding utf8` file exit 2. the
`anchor-text` lines exit 1 until a day with lines has closed in anchor_tz, and the `verify` line's head is a
placeholder for the text you posted.

javascript (`node js/bin/styxx-ledger.cjs ...` from the root of a checkout; not published): the same commands and
flags.

| command | flags both clis take |
|---|---|
| `init <log>` | `--agent` `--tz` `--certifies` (all required), `--kinds a,b`, `--created <utc>`, `--timestamp <utc>` (the started entry's), `--no-started` / `--no-start` |
| `append <log>` | `--kind` (required), `--fields '<json>'`, `--fields-file <f>`, `--field k=v` (repeatable; a string value, set after `--fields`), `--timestamp <utc>` |
| `verify <log>` | `--withheld <f>`, `--anchor '<text>'` (repeatable), `--anchors-file <f>`, `--json` |
| `anchor-text <log>` | `--date YYYY-MM-DD`, `--timestamp <utc>`, `--record` (without it nothing is written) |
| `head <log>` | — |
| `exhibit <url>` | `--explorer <url>` (repeatable), `--sample <n>`, `--no-ots`, `--save <dir>`, `--json` |

exit codes in both: 0 done / re-derives / every anchor holds; 1 refused, does not re-derive, or an anchor does not
hold; 2 usage or i/o (`exhibit`: 0 every check passed, 1 any failed, 2 usage, or a file or an explorer did not
answer). differences that remain: `append` prints a summary in python and the written line in
javascript; python also takes `--fields -` (stdin), `--json` on `append` and `head`, and `--max-problems` on
`verify`; javascript accepts `--anchors-file` as a json array too. `--field k=v` is the same in both since
2026-11-09 (the same bytes written, `python/tests/test_cross.py`). an anchor entry's `late` is section 5's rule in
both, never a flag. also the same in both since 2026-11-09 (`python/tests/test_cli_parity.py`): a flag given empty
(`--certifies ""`, `--agent ""`, `--tz ""`, `--kind ""`) is a refusal, exit 1 with its code, and only a flag not
given, or an empty `<log>`, is usage (exit 2); an empty `--kinds` item (`note,,send`) is refused, never dropped; a
certifies of whitespace only is refused by both, whitespace being the 30 code points PROTOCOL_v1.md section 1 lists;
and `anchor-text` refuses a day not yet closed in anchor_tz (`day_open`), a day already anchored
(`already_anchored`) and a day with no line (`nothing_to_anchor`), with or without `--record` (python composed a
postable text for an open day or an anchored one until then).

## the census (python only)

`styxx-ledger census` scores a filled census preregistration (`census/PREREG_census_TEMPLATE.md`) against a published
ledger and writes `RESULT.json` and `RESULT.md`; `styxx-ledger census-digests` prints the digests a filled file is
sealed with and, given `--ledger` (and `--withheld` when lines are withheld), the values a fill copies from the ledger
and from this kit. the javascript cli has no census command. offline, on the kit's own fixture, from the root of a
checkout with the package installed (nothing is fetched, and a rehearsal prints no verdict):

    styxx-ledger census --prereg python/tests/fixtures/census/PREREG_filled.md --rehearse --ledger python/tests/fixtures/census/ledger.jsonl --anchors python/tests/fixtures/census/anchors.json --export python/tests/fixtures/census/export_held.json --now 2026-11-01T00:00:00Z --out census_rehearsal

it exits 0 and says the window would still not open: the fixture's shelf read names a stand-in host, not the shelf's
kept reads, the kind of fill mistake a rehearsal is for. against the network the census fetches `ledger_url`,
`withheld_url`, `anchors_url`, the shelf's report and an `--export` given as a url, https only, three tries an hour
apart by default (the template's rule; `--tries 1` makes one try), and says each failed try and each wait on stderr.
exit codes: 0 scored, nothing counted, in progress, or a rehearsal; 1 refused (RESULT.json says why, and still names
any source that did not answer; a `--ledger` copy that cannot be read is refused); 2 usage, or a source it was to
read did not answer: a url, or an `--export`, `--anchors` or `--withheld` file, each named on the summary line
(RESULT.json is still written). `--runner lab|operator|other` names who ran it (RESULT.json, and "counted by" in the
held sentence). `census/PREREG_CI_SNIPPET.md` runs it in an operator's own ci.

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

MIT (`LICENSE`). each package carries a byte copy of it (`python/LICENSE`, `js/LICENSE`), so the wheel, the sdist and
the npm tarball ship the text; `python/tests/test_packaging.py` fails when a copy differs from `LICENSE`.
