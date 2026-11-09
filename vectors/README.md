# vectors — protocol v1 conformance

    base_v1.jsonl      a fixed 60-line ledger (header + 59 entries), agent kitbot, kinds anchor/note/started
    vectors_v1.json    32 read-side cases + 86 write-side cases = 118 vectors
    make_vectors.py    writes both files once, every expect computed by the python package
    mutate_core.py     mutation calibration: 57 one-line mutants of the python core against the runner
    run_vectors.py     answers the vectors with python/src/styxx_ledger
    run_vectors.mjs    answers the vectors with js/lib/verify.js
    v0/                the exhibit's protocol v0 set: base.jsonl + vectors.json (10 cases), byte for byte
    ots/               opentimestamps proofs of darkflobi's exhibit, block headers, and what the library said of them
    exhibit/           a snapshot of the published exhibit (ledger, withheld, both indexes, 2 proofs) for the exhibit tests

    python -B vectors/run_vectors.py [-v] [--src python/src] [--only v1|v0|both]
    node vectors/run_vectors.mjs [-v] [--verify js/lib/verify.js] [--v0-verify js/lib/v0.js] [--only v1|v0|both]

by default each runner answers the v0 set first ("k of n v0 vectors answered as the file says", with the package's
v0 read mode) and then the v1 set, whose tally stays the last line; the exit is 0 only when both are answered in full.

each prints its per-group tallies, the implementation and platform, then `k of n vectors answered as the file says`,
and exits 0 only when k == n (1 on a miss, 2 when the base file or the module cannot be read). a checkout that
turned lf into crlf changes the base's sha256 and the runner says so; keep `* -text` for this folder.

`make_vectors.py` refuses to overwrite either file with other bytes unless `--force` is given: a receipt is history,
and every forced regeneration goes in BUILD_LOG_3a.md. `--check` recomputes and compares only. `base_v1.jsonl` has
kept one sha256 (`09fcf1d7...a8e4`) through every regeneration; only `vectors_v1.json` has grown.

## what the cases are

read side (32): the 10 v0 cases carried over (identity, one field rewritten, prev rewritten, a dropped line, a
dropped line withheld with its digest and with a wrong one, a cr byte, a duplicated key, a truncated tail, a flip
re-chained); the anchor cases (present, after a later line, another agent's word, a later line with no own entry,
own entry disagreeing, the head withheld, the strict text form); a kind not declared; header kinds missing started;
a v0 header; a day rewritten at the dst edge; a v0 entry schema; and, from the fix pass of 2026-11-08, a timestamp
with a trailing lf and one with fullwidth digits (each re-chained, so only `day` fails), a withheld seq written
`33.0`, lines nested 33 and 1200 deep, an empty file, a file of blank lines, a header with an extra key (the
verifier is silent on it: a writer-side refusal), a seq written `5.0`, and non-ascii keys in code-point order (the
last two compare `ok` only, see PROTOCOL section 4).

write side (86): `jcs` 20 (13 dumps, the depth-32 bound among them; 7 refusals), `day_of` 32 (17 days, among them
the 1000 and 9998 year edges; 15 refusals: offset, fraction, 30 february, hour 24, second 60, unknown zone, a
trailing lf, fullwidth digits, years 0001 / 9999 / 0999, zones `utc`, `UTC `, `Factory`, `america/new_york`),
`late_of` 10 (section 5's rule at its 00:10:00 edge in new york on both sides of the dst end, in utc and berlin, and
one refusal), `anchor_text` 8 (2 texts, 6 refusals), `header_digest` 2, `entry_id` 2, `build_entry` 12 (5 lines,
7 refusals, among them an anchor whose `late` contradicts the rule and a field 33 containers deep).

## what the javascript module must export

`run_vectors.mjs` loads `js/lib/verify.js` with `require` (commonjs) and awaits every call, so each function may
return a value or a promise.

| export | signature | returns / throws |
|---|---|---|
| `verifyBytes` | `(u8: Uint8Array, {withheld})` | `{header, entries, problems, bridged, head, ok}`; `entries` is `[{line, entry}]`; each problem has `seq` (int, or null/undefined for reading and header problems) and `code` (string) or `codes` (string[]) |
| `checkAnchor` | `(entries, a, withheld, header)` | `{ok, ...}`; `a` is what `parseAnchorText` returns; with `header`, `a.agent` must equal `header.agent` |
| `parseAnchorText` | `(text)` | `{agent, date, head, seq}` or `null` (also `null` when seq > 2^53) |
| `coverage` | `(entries, withheld, anchorSeqs)` | `{pinned, unpinned_by_withholding, unpinned_ranges, after_last_anchor, withheld, last_anchor_seq}` (verify.js v0's shape) |
| `jcs` | `(value)` | the canonical string; throws on a refused value |
| `dump` | `(value)` | the unchecked compact key-sorted string (used by the runner's transforms) |
| `dayOf` | `(timestamp, tz)` | `YYYY-MM-DD`; throws `timestamp` / `anchor_tz` |
| `lateOf` | `(anchorDate, timestamp, tz)` | boolean, section 5's rule; throws `anchor_form` / `timestamp` / `anchor_tz` |
| `headerDigest` | `(header)` | 64 hex: sha256("styxx.ledger/log/v1\n" + jcs(header)) |
| `entryId` | `(coreOrEntry)` | 64 hex: sha256(jcs(core)); the runner passes an object without `entry_id` |
| `anchorText` | `(agent, date, head, seq)` | the text; throws `anchor_form` |
| `buildEntry` | `(header, seq, prev, kind, timestamp, fields)` | the entry object with `day` and `entry_id`; the runner compares `dump(entry)` to the expected line |

transform ops both runners implement: `identity`, `crlf_first_line`, `truncate_last`, `set_field`,
`set_field_rechain`, `set_header`, `set_header_rechain`, `drop_seq`, `dup_key`, `replace_in_line` (bytes of one
seq's line, first occurrence), `append_nested` (a line `{"deep":[[...1...]]}` of the given depth), `replace_all`
(the whole input is the given text).

refusals are thrown errors whose `.code` is exactly one of:
`float`, `int_range`, `non_ascii_key`, `lone_surrogate`, `depth`, `type`, `reserved_field`, `kind_not_declared`,
`started_writer`, `anchor_form`, `timestamp`, `anchor_tz` (and `header_form` for a header check, not vectored).
an error without `.code` counts as a miss.

problem codes the read side compares (sorted set): `cr_byte`, `unparsable`, `not_object`, `not_canonical`,
`no_header`, `header_kinds`, `core_not_canonical`, `schema`, `kind_not_declared`, `entry_id`, `prev`, `seq`, `day`
(`duplicate_key` is python-only, and its one case compares `ok` only).

## how the vectors were checked for power

a vectors file two implementations pass by construction proves little, so the python core is mutated, one source
change at a time, and the runner re-run against each mutant (`python -B vectors/mutate_core.py`).

    first file (75 vectors):    36 of 42 mutants killed; 6 survived (entry schema, the anchor's later-line,
                                own-entry and withheld-head checks, coverage's bound, the anchor parse)
    second file (80 vectors):   42 of 42 mutants killed, after 5 read cases were added for the 6 survivors
    this file (118 vectors):    57 of 57 mutants killed (2026-11-08 fix pass): the 5 day/timestamp mutants
                                re-pointed at the changed source, and 15 added, one or more per review finding
                                (trailing lf, unicode digits, year range, zone list, Factory, late cutoff ignored
                                and made inclusive, late not enforced at build, depth bound off and off by one,
                                the reader's depth scan off, integral-float withheld ignored, no_header only with
                                entries, the agent regex with `$`, the anchor seq bound off)

a mutant whose source line has since changed is printed as "not applied", not counted. 57 mutants are the ones
written, not every possible defect: a mutant nobody wrote is not measured, and the javascript package gets no
mutation run here.

## v0/ — protocol v0 conformance (the exhibit's set)

    base.jsonl       sha256 8029fce0bed73a52067d2e7e3552555d45c81d837187a93b6dd20d48ad8861f1 (120 entries + header)
    vectors.json     sha256 be43667f1662e822fd31d5941e6166fdd7ce145de72b6dfea9b32bbb4ae69d4b (10 cases)

copied byte for byte on 2026-11-08 from darkflobi's published exhibit, https://fathom-lab.github.io/styxx/ledger/vectors/
(the local worktree C:/Users/heyzo/clawd/wt/exhibit/ledger/vectors/, commit 6db83fc0 "ledger: protocol v0 and
conformance vectors"; the sha256 of vectors.json is the one the styxx shelf fetched live the same day). the exhibit's
verify.js is the reference v0 implementation and its run_vectors.cjs the reference runner; both runners here apply the
same transforms (identity, set_field, drop_seq, crlf_first_line, dup_key, truncate_last, set_field_rechain) and
compare the same keys (ok, problem_seqs, problems_without_seq, head, bridged, anchors_ok; the duplicate-key case
compares ok only). these files are not regenerated here: a receipt is history.

v0 differs from v1 only where PROTOCOL_v1.md's "what changed from v0" says: the `darkflobi.gate/log/v0` and
`darkflobi.gate/entry/v0` schemas, a header of schema / created / anchor_tz / certifies (no agent, no kinds), the
fixed anchor word `gate`, and no kinds check. the day is read as verify.js reads it (Date.parse: fractional seconds
and offsets accepted, a naive time read as utc) and checked only when an entry carries a timestamp; `no_header` is
reported only when the file holds entries.

## ots/ — opentimestamps proofs (both packages' native readers)

    anchors/<date>.txt(.ots)   the 14 anchor texts of darkflobi's exhibit and their proofs (anchors/index.json, 14 in
                               bitcoin), byte for byte
    witness/<entry_id>.ots     22 witness proofs: 20 attested entries sampled by a seeded rule (attested entry_ids
                               ranked by sha256(bytes(seed) + bytes(entry_id)), seed = the exhibit ledger.jsonl's
                               sha256 b9cdb57d...f533, first 20) and 2 pending-only entries by the same rank
    block_headers.json         14 bitcoin block headers as blockstream.info returned them, each compared with
                               mempool.space's answer (all 14 agree): 8 captured by the styxx shelf
                               (2026-11-08T20:47:05Z), 6 by the 3e build (975028, 975030, 975060, 975074, 975101,
                               975102)
    expect.json                what javascript-opentimestamps 0.4.9 says of each of the 36 proofs: file digest, every
                               attestation (kind, attested digest, height), each bitcoin attestation's attested time
                               read through the library's own explorer path (blockstream.info), and the lowest
    fixtures.json              where each file came from, the sample rule and its seed
    crafted/<name>.ots         10 hand-built proofs (review 3e) and crafted.json, each with its sha256 and the answer
                               both readers must give, written by hand in make_crafted.py (not read back from a
                               reader): heights 2^32 - 1 (read), 2^32, 2^53, 2^60, 2^63 (refused,
                               attestation_payload), an argument length of 2^60 (refused, varuint), nested forks and
                               a fork with attestation branches first (3 attestations each, in walk order), a pending
                               uri with bytes ff fe (pending_uri), a bitcoin payload with a trailing byte
                               (attestation_payload). `python -B vectors/ots/make_crafted.py --check` rebuilds them

both packages' ots tests verify every proof offline against block_headers.json and must equal expect.json exactly
(240 attestations, 96 of them bitcoin). the anchors' lowest heights are the shelf's: 974530 (11 anchors), 974635,
974768, 975028; the 20 attested witness proofs carry 975101 and 975102.

## exhibit/ — a snapshot of the published exhibit (the `exhibit` command's end-to-end tests)

    ledger.jsonl                 sha256 b9cdb57dc29e7c0f8fe0c5bbf4dbaf58383d819a85f00e01c4e814502857f533 (1251502 bytes;
                                 header + 738 entries, 5 withheld lines, protocol v0)
    withheld.json                sha256 096e3123c16e10bfcf8853ba82c6bc1bd75bdb935c34674d9ceba829b6c60f59
    anchors/index.json           sha256 3fc4cf452855c302a9a7b03cdbd4519ba57bbdbda20f537defd9b2b3380e353d (14 anchors)
    witness/index.json           sha256 e5d6eb3a26987c9c6986ab27a80ee88ef50bcb72b76d40f73eb8a1f499530f3b (743 records:
                                 734 bitcoin, 9 pending)
    witness/proofs/<id>.ots      the proofs of the earliest and latest attested lines (seq 1, 12ba9592...; seq 734,
                                 0e5a698d...), which the command samples beside the seeded 20 in ots/witness/

copied byte for byte on 2026-11-09 from the exhibit worktree (C:/Users/heyzo/clawd/wt/exhibit/ledger/), whose four
files were read the same hour from https://fathom-lab.github.io/styxx/ledger/ with the same sha256. the anchor texts
and proofs, and the other 22 witness proofs, are ots/'s. the two seq-1 / seq-734 proofs were checked with
javascript-opentimestamps 0.4.9 (heights 975101 and 975102, times 1794174086 and 1794175060, the native readers'
values). both suites assemble ledger/ from these files in a temp dir, serve it on 127.0.0.1 with two fake explorers
answering ots/block_headers.json, and run the command: a clean copy (exit 0, 66 of 66 checks), an altered anchor
.txt, explorers that disagree, a swapped witness proof, a truncated ledger (exit 1 each, the failing check named),
and the review-3e regressions built on the same copy (a phantom withheld seq after the last line, a withheld record
naming a published line, an index without block or block_time, a pending anchor before and after 7 days, a redirect
to another host, a block no explorer knows, a 2^60 height, a rate-limited explorer).

## counts as read on this box (windows 11, 2026-11-08)

    python/src/styxx_ledger, python 3.12.10, win32 (tzdata 2025.3 installed)   118 of 118
    js/lib/verify.js, node 24.13.0, win32                                      118 of 118
    python/src/styxx_ledger/v0.py, v0 set                                       10 of 10
    js/lib/v0.js, v0 set                                                        10 of 10
    python/src/styxx_ledger, python 3.14.2, win32 (no tzdata installed)         58 of 118

the 3.14 line is the dependency the readmes name: without `tzdata`, windows python has no zone database, every
named zone is refused, and 60 vectors miss. the ubuntu rows, and python 3.10 / 3.13 and node 20 / 22, come from ci,
not from this box.
