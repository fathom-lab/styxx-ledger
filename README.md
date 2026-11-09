# styxx-ledger

a reference writer and verifier for the styxx ledger protocol v1 (`PROTOCOL_v1.md`), in python and in javascript.

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
    .github/workflows/  ci.yml: ubuntu + windows, python 3.10 / 3.12 / 3.13, node 20 / 22, and the cross job

## what it is not

- not a coverage claim: a writer records what it is handed. an event its caller never hands it leaves no line, and
  nothing here can tell. showing that every event got a line is a census of the destinations against the ledger,
  done by someone else.
- not a truth claim: no field is checked for what it says. the writer does not read content.
- not a signature: nothing is signed and nothing names who wrote a line beyond the `started` entry's own statement.
  the chain and the posted heads are the whole of what fixes the bytes.
- no network in the core packages: the anchor step composes the text and hands it back. an optional helper shells
  out to an opentimestamps client if one is installed; neither package depends on it.

## counts, as read on this box

windows 11, 2026-11-08. ubuntu, python 3.10 / 3.13 and node 20 / 22 are ci's to read (`.github/workflows/ci.yml`);
no ubuntu number is claimed here until ci has run.

    vectors, python package (python 3.12.10, tzdata 2025.3)     118 of 118 answered as the file says
    vectors, javascript package (node 24.13.0)                   118 of 118 answered as the file says
    vectors, python 3.14.2 without tzdata                         58 of 118 (why the windows tzdata dependency exists)
    pytest (python/)                                              212 passed of 212 collected
    node --test (js/)                                             49 passed of 49, 0 skipped
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

exit codes in both: 0 done / re-derives / every anchor holds; 1 refused, does not re-derive, or an anchor does not
hold; 2 usage or i/o. differences that remain: `append` prints a summary in python and the written line in
javascript; javascript also takes `--field k=v`; python also takes `--fields -` (stdin), `--json` on `append` and
`head`, and `--max-problems` on `verify`; javascript accepts `--anchors-file` as a json array too. an anchor
entry's `late` is section 5's rule in both, never a flag.

## darkflobi's own ledger

v0 remains v0. darkflobi's ledger keeps its `darkflobi.gate/*/v0` schema strings and its own verifier; the v1
verifier does not read a v0 file and says so (`no_header`, "this verifier reads v1 only"). `PROTOCOL_v1.md` lists
exactly what changed from v0, and separately what was decided in the review pass.

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
