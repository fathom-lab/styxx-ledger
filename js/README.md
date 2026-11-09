# styxx-ledger (javascript)

the javascript reference writer and verifier for the styxx ledger protocol v1 (`../PROTOCOL_v1.md`): a json-lines
log an agent appends to, one hash-chained line per event it is handed, that anyone holding the file can re-derive.
the python package in `../python` implements the same protocol; both are held to `../vectors/vectors_v1.json`.

    node >= 20 · commonjs · no npm runtime dependencies (sha256 from node:crypto, the zone database from node's icu)
    version 1.0.0-alpha.1 · not published to npm

## what it is not

- not a coverage claim: a writer records what it is handed. an event the caller never hands it leaves no line.
- not a truth claim: the chain fixes bytes and their order, never whether a field is true.
- not a signature: nothing is signed, and nothing names who wrote a line beyond the `started` entry's own statement.
- no network: the anchor step composes the text and hands it back. posting it somewhere public is the caller's.

## counts, as read on this box (windows 11, node 24.13.0, 2026-11-08)

    ../vectors/run_vectors.mjs against lib/verify.js     118 of 118 vectors answered as the file says
    node --test (tests/*.test.js)                         49 of 49 tests pass, 0 skipped
    ubuntu, node 20 and 22                               not run here; ci.yml's matrix reads them

the vectors' expected values were computed once by the python package; this package answers them on its own code
(its canonicalizer is the exhibit verify.js v0 `dump`, unchanged).

## quickstart

    npx styxx-ledger init agent.jsonl --agent mybot --certifies "one line per tool call mybot was handed." --tz Europe/Berlin
    npx styxx-ledger append agent.jsonl --kind note --fields '{"note":"hello"}'
    npx styxx-ledger anchor-text agent.jsonl            # after midnight in anchor_tz: prints the text for yesterday
    npx styxx-ledger anchor-text agent.jsonl --date 2026-11-08 --record   # after posting it: the anchor entry
    npx styxx-ledger verify agent.jsonl --anchor "mybot anchor 2026-11-08 head <64 hex> seq <n>"
    npx styxx-ledger head agent.jsonl

`init` writes the header (`--tz` is required; `--kinds a,b` adds kinds, `anchor` and `started` are always there)
and one `started` entry at `--timestamp` or now (`--no-started` or `--no-start` for the header alone). `anchor-text`
prints the text and writes nothing unless `--record` is given (`--dry-run` is accepted and means the default); it
refuses a day that has not closed in anchor_tz, a day already anchored, and a day with no entry. the anchor entry's
`late` is section 5's rule, not a flag: `--late` is a usage error. exit codes: 0 done / re-derives and every
anchor holds; 1 refused / does not re-derive / an anchor does not hold; 2 usage.

from code:

```js
const { Ledger, verifyBytesSync, parseAnchorText, checkAnchor } = require("styxx-ledger");

const led = Ledger.init("agent.jsonl", { agent: "mybot", certifies: "one line per tool call mybot was handed.", anchorTz: "UTC", kinds: ["tool_call"] });
led.start({ framework: "my-agent 0.3" });                  // {writer: {language, name, version}, framework}
led.append("tool_call", { tool: "search", args_sha256: "…" });
const { text } = led.anchor("2026-11-08");                 // post `text` somewhere public; the entry is written

const r = verifyBytesSync(require("fs").readFileSync("agent.jsonl"));
r.ok; r.head; r.problems;                                  // problems carry seq and code / codes (PROTOCOL 4)
checkAnchor(r.entries, parseAnchorText(text), [], r.header).ok;
```

## the writer (PROTOCOL 3b)

every append, synchronously: create `<log>.lock` exclusively with this pid → re-read the file and re-derive it
(refuse, code `tamper`, when it does not, or when it does not end with lf) → take seq and prev from the tail →
write the canonical line and one lf → `fsync` → remove the lock. a lock older than 30 s whose pid is not a live
process (or that names no pid) is broken under a `<log>.lock.break` file, and a `lock_recovered` entry
(`stale_pid`, `stale_age_s`) is written before the caller's only when the header lists `lock_recovered`. the lock
file holds the pid in ascii, as the python writer's does, so the two writers share one file: 4 processes (2 node,
2 python) appending 15 lines each give 60 of 60 note lines in one chain that both verifiers re-derive to the same
head (tests/cross.test.js).

refusal codes, thrown as errors with `.code`: section 2's `float`, `int_range`, `non_ascii_key`,
`lone_surrogate`, `depth`, `type`; section 3b's `reserved_field`, `kind_not_declared`, `started_writer`, `anchor_form`,
`timestamp`, `anchor_tz`, `header_form`; the writer's own `tamper`, `locked`, `exists`, `no_log`,
`anchored_day` (an entry of a day already anchored would break that day's post), `day_open`,
`already_anchored`, `nothing_to_anchor`, `lock_release`.

## the verifier

`lib/verify.js` keeps the exhibit verify.js v0 api: `verifyBytes`, `verifyText`, `checkAnchor`, `coverage`,
`readLog`, `checkChain`, `headOf`, `headerDigest`, `entryIdOf`, `sha256Hex` return what they returned (the digests
and checks as promises), `jcs`, `dump`, `coreOf`, `parseAnchorText` are synchronous. what changed for v1:

- `anchorText(agent, date, head, seq)` takes the agent before the date; `parseAnchorText` adds `agent`; given the
  header, `checkAnchor(entries, a, withheld, header)` also requires `a.agent === header.agent`.
- `localDay(ts)` is `dayOf(ts, tz)`: v1 reads the day in the header's `anchor_tz`, not a fixed zone.
- every problem record carries `seq` and `code` / `codes`.
- node only (`node:crypto`), where v0 also ran in a browser through `crypto.subtle`.

added: `dayOf`, `lateOf`, `nextDay`, `entryId`, `headerDigestSync`, `verifyBytesSync`, `buildEntry`, `checkHeader`,
`makeHeader`.

## darkflobi's v0 ledger

v0 remains v0: darkflobi's own ledger keeps the `darkflobi.gate/*/v0` schema strings and its own verify.js. this
verifier does not read a v0 file; it reports `no_header` with the words "this verifier reads v1 only".

## known differences from the python package

- a line with a key written twice: python drops it (`duplicate_key`), JSON.parse keeps the last value and this
  reader flags the line `not_canonical`. both say the log does not re-derive; the one vector compares `ok` only.
- `1.0` in a javascript value is the integer 1 (the language cannot tell them apart), so it is written as `1`
  where python refuses the float.
- zone data: `day` comes from node's bundled icu here and from zoneinfo / tzdata in python. two releases of the zone
  database that disagree about a zone's rules would read different days; the vectors pin the 2026 dst edges they
  name, not every zone in every year.
- zone names: both packages refuse a case variant (`utc`), a name with a space, and `Factory` (vectors pin it);
  node's icu still takes a few backward links the python zone list lacks (`US/Pacific-New`, `SystemV/EST5`), which
  PROTOCOL section 1 records as the residual.
- numbers a javascript reader re-prints (`5.0` read as 5) and keys above u+007e give different problem codes in
  the two readers; both answer that the log does not re-derive (PROTOCOL section 4, two vectors compare `ok`).

## optional: opentimestamps

`require("styxx-ledger").ots.stamp(file)` shells out to an `ots` client when one is on PATH and reports
`{ok: false, reason}` when none is. the package does not depend on it, and nothing in the writer or the verifier
calls it. `ots stamp` uses the network; a proof made on a later day for an earlier post shows only that the post
existed by the stamping day.

## tests

    node --test                          unit, cli, writer (lock, recovery, 4 concurrent processes), cross, vectors
    node ../vectors/run_vectors.mjs      the shared vectors alone
    node tests/make_fixture.js --check   tests/fixtures/js_written.jsonl (30 lines) is what the writer writes now

the cross tests read `../vectors/base_v1.jsonl` and every `../python/tests/fixtures/*.jsonl` (python-written), check
each re-derives to its stated head, and rewrite each with this writer from its header, kinds, fields and timestamps:
the bytes must come out identical. the python suite reads `tests/fixtures/js_written.jsonl` and its `.json` sidecar
the other way. the mixed-writer test is skipped when no python with a zone database can import `../python/src`.

## forbidden claims

no text about this package says "stdlib-only" or "dependency-free", "gate your agent in a day" or any zero-to-anchored
time, "first", "no one", "provably" or "independent"; or that a ledger shows every event got a line, that a line is
true, or who wrote it. every count carries its denominator.
