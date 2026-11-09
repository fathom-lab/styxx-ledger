# vectors — protocol v1 conformance

    base_v1.jsonl      a fixed 60-line ledger (header + 59 entries), agent kitbot, kinds anchor/note/started
    vectors_v1.json    32 read-side cases + 86 write-side cases = 118 vectors
    make_vectors.py    writes both files once, every expect computed by the python package
    mutate_core.py     mutation calibration: 57 one-line mutants of the python core against the runner
    run_vectors.py     answers the vectors with python/src/styxx_ledger
    run_vectors.mjs    answers the vectors with js/lib/verify.js

    python -B vectors/run_vectors.py [-v] [--src python/src]
    node vectors/run_vectors.mjs [-v] [--verify js/lib/verify.js]

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

## counts as read on this box (windows 11, 2026-11-08)

    python/src/styxx_ledger, python 3.12.10, win32 (tzdata 2025.3 installed)   118 of 118
    js/lib/verify.js, node 24.13.0, win32                                      118 of 118
    python/src/styxx_ledger, python 3.14.2, win32 (no tzdata installed)         58 of 118

the 3.14 line is the dependency the readmes name: without `tzdata`, windows python has no zone database, every
named zone is refused, and 60 vectors miss. the ubuntu rows, and python 3.10 / 3.13 and node 20 / 22, come from ci,
not from this box.
