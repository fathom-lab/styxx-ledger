# the styxx ledger — protocol v1

what an agent's writer appends, what a stranger can check, and the cases two implementations must answer alike.
v1 is darkflobi's send ledger (protocol v0, deployed since 2026-10-24) with the darkflobi-specific parts taken out
and the agent named in the header, so that any agent can keep one. the chain math is v0's, unchanged. nothing here
is signed; the chain, the posted heads, and (optionally) a timestamp proof of each post are the whole of what fixes it.

this repository holds two reference implementations of it, `python/` (package `styxx_ledger`) and `js/` (package
`styxx-ledger`), and one vectors file, `vectors/vectors_v1.json`, that both are held to. an implementation is
conformant when it answers every vector as the file says (section 8).

## 1. the file

json lines, utf-8, lf; no cr byte anywhere. line 1 is the header; every later non-blank line is an entry.

    header  {"agent":"<name>","anchor_tz":"<iana zone>","certifies":"<one sentence>","created":"<utc>","kinds":[...],"schema":"styxx.ledger/log/v1"}
    entry   {"schema":"styxx.ledger/entry/v1","seq":<n>,"prev":"<64 hex>","kind":"<kind>","timestamp":"<utc>","day":"<YYYY-MM-DD>",...,"entry_id":"<64 hex>"}

the header carries exactly six keys, no others:

- `schema`: `styxx.ledger/log/v1`.
- `created`: utc, `YYYY-MM-DDTHH:MM:SSZ`.
- `anchor_tz`: an iana zone name (`America/New_York`, `Europe/Berlin`, `UTC`), the zone whose midnight closes a day.
  it is the exact-case name the zone database lists (`utc`, `UTC ` and `america/new_york` are refused), and never
  `Factory`. two zone databases can still differ on backward links: node's icu takes `US/Pacific-New` and
  `SystemV/EST5`, which the python zone list lacks. that residual is recorded here, not vectored; use a canonical
  `Area/City` name or `UTC`.
- `agent`: 1-32 characters of `[a-z0-9_-]`; it is the first word of the anchor text (section 5).
- `certifies`: one sentence, the writer's promise about what a line records and what it never carries: a string of
  1 to 500 characters (unicode code points, not utf-16 units) with no lf, not made only of whitespace. whitespace
  here is exactly these 30 code points: u+0009..u+000d, u+001c..u+0020, u+0085, u+00a0, u+1680, u+2000..u+200a,
  u+2028, u+2029, u+202f, u+205f, u+3000 and u+feff. that is the union of what python's `str.isspace` and
  javascript's `String.prototype.trim` call blank (python alone counts u+001c..u+001f and u+0085, javascript alone
  u+feff), so a certifies either runtime would call blank is refused by both writers (`header_form`), and a log
  either writes takes appends from the other. u+200b and the other format characters are not whitespace here. the
  writer judges the form only, never what the sentence says.
- `kinds`: the sorted, duplicate-free list of the kinds this writer may write; it contains `anchor` and `started`.

an entry carries the chain's keys (`schema`, `seq`, `prev`, `kind`, `timestamp`, `day`, `entry_id`) and the kind's
own fields beside them; a caller's fields may not use those seven names or begin with `_`. `kind` is one of
`header.kinds`. `timestamp` is utc `YYYY-MM-DDTHH:MM:SSZ` exactly (ascii digits only, nothing before or after it, no
trailing lf; no fraction, no offset; a real calendar instant: no hour 24, no second 60, no 30 february; a year from
1000 to 9998, so its day is a four-digit year in every zone), the writer's clock: a statement, not evidence of
order. `day` is that
timestamp's calendar day in `anchor_tz`, read with the platform's zone database (python `zoneinfo`, which on
windows is the `tzdata` package; node `Intl.DateTimeFormat`). a zone the database does not hold is refused, never
approximated.

two kinds every writer has:

- `started`: written when a writer process opens the log; it carries at least `{"writer": {"name", "version"}}`
  and may carry more (framework, version, lockfile integrity: the writer's own statement).
- `anchor`: written after a day's anchor text is composed (section 5); it carries `anchor_date`, `anchor_head`,
  `anchor_head_seq`, `anchor_text_sha256` and `late` (a boolean, section 5's rule).

`lock_recovered` is written only by a writer whose header lists it (section 3b). every other kind (`note`, `send`,
`edit`, `tool_call`, ...) is the writer's choice, declared in the header before the first line that uses it.

## 2. the canonical form

a line's bytes are the compact, key-sorted dump of its object: `{` `}` `,` `:` with no spaces, keys sorted by code
point, strings escaped as json requires (`"`, `\`, u+0000-u+001f; the short forms `\b \f \n \r \t`, `\u00xx` with
lowercase hex for the other control characters; everything else raw utf-8, u+007f, u+2028 and u+2029 included).
strings are never normalised: a writer and a reader keep each string's code points as given (no nfc, nfd, nfkc or
nfkd, no case folding), so an e with an acute accent written as u+00e9 and written as u+0065 u+0301 are two strings
with two dumps and two entry_ids. a reader compares bytes, never a normal form.
the admitted value types are null, booleans, integers with |n| <= 2^53, strings without lone surrogates, arrays,
and objects whose keys are u+0000..u+007e, nested at most 32 containers deep (the outermost object or array counts
as one; a ledger line, being an object, leaves 31 for a field). for these types the dump is rfc 8785 (jcs).
anything else is refused at write time with a code:

    float            a non-integral number (1.5)
    int_range        an integer with |n| > 2^53
    non_ascii_key    an object key with a character above u+007e (u+007f included)
    lone_surrogate   a string holding an unpaired utf-16 surrogate
    depth            containers nested more than 32 deep
    type             any other value (a set, a date object, a non-string key)

so two implementations never disagree on a number's or a string's bytes. one consequence, stated: javascript
cannot tell `1.0` from `1`, so a javascript writer handed `1.0` writes `1`, where the python writer handed the float
`1.0` refuses it; both write only integers. a line whose bytes are not the canonical dump of its object is a
problem, whatever the object says.

## 3. the chain

    core(entry)      = every key of the entry except entry_id
    entry_id         = sha256( JCS(core) )                         64 lowercase hex
    header_digest    = sha256( "styxx.ledger/log/v1" LF JCS(header) )
    entry_1.prev     = header_digest
    entry_k.prev     = entry_{k-1}.entry_id
    entry_k.seq      = entry_{k-1}.seq + 1, entry_1.seq = 1
    head             = the last entry's entry_id (or header_digest when there is no entry)

the header's domain string keeps a header from ever passing as an entry. `timestamp` and `day` sit inside the core,
so a rewritten clock breaks the digest. anyone holding the file recomputes everything: there is no key.

### 3b. the writer

an append, in both languages:

1. take the lock: create `<log>.lock` beside the log, create-exclusive, holding the writer's pid. a lock older than
   30 s whose pid is not a live process may be broken; a writer that breaks one writes a `lock_recovered` entry
   before its own only if the header lists `lock_recovered`.
2. re-read the file and re-derive it (section 4). when the existing file does not re-derive, does not end with
   lf, or its header is not one a v1 writer may write (`header_form`, below), refuse: nothing is appended.
3. take `seq` and `prev` from the tail.
4. write the canonical line and one lf; fsync.
5. release the lock.

the composition of an entry (step 3's object) is pure: given the header, seq, prev, kind, timestamp and fields it
is one value, and the write-side vectors pin it (`build_entry`). its refusals, beside section 2's:

    reserved_field     a field named schema, seq, prev, kind, timestamp, day or entry_id, or beginning with _
    kind_not_declared  a kind not in header.kinds
    started_writer     a started entry without writer {name, version}
    anchor_form        an anchor entry without its five fields in form, or whose `late` is not section 5's rule
                       for its date and timestamp, or anchor text fields out of form (seq above 2^53 included)
    timestamp          a timestamp not in the v1 form, naming no calendar instant, or outside years 1000..9998
    anchor_tz          a zone the platform's database does not list, case for case, or Factory
    header_form        a header with a missing or extra key, or a key out of form (a certifies out of section 1's
                       form among them)

## 4. what a verifier reports

reading (each a problem record with no seq): a cr byte anywhere (`cr_byte`); an unparsable line, invalid utf-8
included, and a line nested more than 32 containers deep, which the reader declines before any parser recurses into
it (`unparsable`); a line that is not an object (`not_object`); a line whose bytes are not canonical
(`not_canonical`); no header on line 1 (`no_header`; a v0 header on line 1 is reported this way, with the words
"this verifier reads v1 only"; an empty file, or one of blank lines only, has no header and is reported the same
way, as a reading record and a chain record, both without seq). header: `header.kinds` missing `anchor` or `started` (`header_kinds`). chaining,
per entry: a core that cannot be canonicalised (`core_not_canonical`); `schema` is not `styxx.ledger/entry/v1`
(`schema`); `kind` not in `header.kinds` (`kind_not_declared`); `entry_id` does not re-derive from the core
(`entry_id`); `prev` does not name the line before (`prev`); `seq` is not the one expected (`seq`); `day` does not
re-derive from `timestamp` in the header's `anchor_tz`, or the timestamp is missing or out of form (`day`). a log
with no problem "re-derives"; the verifier then states the head.

a problem record carries `seq` (an integer, or null for a reading or header problem) and its code (`code`, or
`codes` for one entry's list). the vectors compare the set of seqs with problems, the count of records with no seq,
and the sorted set of codes.

the verifier reports header form only as far as `header.kinds` goes. an extra header key, an agent out of form,
unsorted kinds or a `created` out of form are refusals of the writer (`header_form`, section 3b), which will not
append to such a file; the verifier does not report them, and a vector pins that it does not.

known differences between the implementations, documented, never vectored as codes (their vectors compare `ok`
only; both readers answer that the log does not re-derive):

- a line with a key written twice is dropped by the python reader (`duplicate_key`; the chain then breaks after
  it) and kept by a json.parse reader with its bytes flagged `not_canonical`. kept from v0.
- a number a javascript reader rounds or re-prints: `5.0`, `1.0`, `1E2`, an integer above 2^53. python reads a
  float or an exact big integer (`core_not_canonical`, and `seq` when it is the seq); javascript reads a double whose
  dump differs from the bytes (`not_canonical`, sometimes `entry_id`).
- keys above u+007e: the dump order is defined for admitted keys only. python orders such keys by code point,
  javascript by utf-16 code unit (u+ff5e and u+1f600 swap), so each reader can call the other's order not
  canonical; both refuse the core (`core_not_canonical`).

## 5. the anchor

once a day, after 00:00 in `anchor_tz`, the writer composes the exact text

    <agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>

where `<agent>` is `header.agent`, `<YYYY-MM-DD>` the day just closed, `<n>` the seq of the last entry whose `day`
is that date and `<64 hex>` its `entry_id`, hands the text to the caller to post in a public place outside the
box, and writes an `anchor` entry (`anchor_date`, `anchor_head`, `anchor_head_seq`, `anchor_text_sha256` = sha256
of the text's utf-8 bytes, `late`).

a writer composes the text only for a day that has closed. it refuses, in this order: a date not `YYYY-MM-DD`
(`anchor_form`); a day that has not closed in `anchor_tz` at the writer's clock (`day_open`: the clock's own day
there is that date or an earlier one); a day the ledger already holds an anchor entry for (`already_anchored`); and
a day no entry has (`nothing_to_anchor`). a text composed for an open day would fail the stranger's check below as
soon as one more line of that day is written. composing writes nothing; the write-side vectors pin these refusals
(`compose_anchor`, over the base).

`late` is a rule, not the caller's word: it is true when the anchor entry's own local day in `anchor_tz` is after
the day following `anchor_date`, or is that following day with a local clock later than 00:10:00; otherwise false.
(darkflobi's v0 gate marks lateness with the same 00:10 cutoff.) both writers compute it, `build_entry` refuses an
anchor entry whose `late` disagrees (`anchor_form`), and the `late_of` vectors pin the edge on both sides of the
2026-11-01 dst end. the verifier does not judge lateness; it reports the mark (`ledger_anchor_line.late`). the core packages do no network: posting is the caller's. a place a stranger
cannot read without a login does not serve as an anchor place.

a stranger holding a posted text parses it (the whole text is the form; one trailing lf tolerated; no leading
zeros in `<n>`, and `<n>` at most 2^53; anything else is not an anchor) and checks: the text's agent is the header's; the entry at `<n>`
carries that digest (or, when that seq is withheld, the withheld list names that digest for it); no entry whose
`day` is that date sits after `<n>`; the ledger's own anchor entry for that date, if there is one, agrees on head
and seq. all four, or the anchor does not hold.

optionally, the post's bytes can be stamped with opentimestamps: their sha256 goes to the public calendars, which
commit them into a bitcoin block, and the proof attests that those bytes existed before that block. the packages
ship a helper that shells out to an `ots` client if one is installed; neither package depends on it, and a proof
made on a later day for an earlier post shows only that the post existed by the stamping day.

## 6. publication

a writer's log may be published whole, or with lines left out:

- `ledger.jsonl`: every published line byte for byte, in order, with the header.
- `withheld.json`: lines left out, each at least `{seq, entry_id}` and the reason. `seq` is an integer with
  |n| <= 2^53; an integral json number (`10.0`) is read as that integer, as a javascript reader cannot do otherwise;
  any other value leaves the item out. a verifier given the list
  bridges the chain through a withheld seq on its published digest: when the next line present is not that seq,
  `prev` must equal the withheld digest and the expected seq moves past it. the digest of a withheld line is the
  publisher's word, not the reader's derivation.
- coverage: a published line is pinned for the reader when no withheld seq sits after it and at or before the
  first posted head at or after it; a withheld line in between severs that, and the lines it leaves unpinned are
  counted and listed (`coverage`), never hidden. lines after the last posted head are counted as not yet pinned.
- the posts and, when made, their proofs.

## 7. what this protocol does not do

it does not show that every event got a line: a writer records what it is handed, and an event its caller never
hands it leaves no trace; that is a census of the destinations against the ledger, done by someone else. it does
not check the truth of any field. it does not sign anything, and it does not name who wrote a line beyond the
`started` entry's own statement. the core writer does not read content: its refusals are section 2's and 3b's,
never a judgement of what a string says. it fixes bytes and their order, in a place the writer does not control
once the head is posted, and lets anyone recompute the rest.

## 8. conformance

`vectors/vectors_v1.json` holds cases over `vectors/base_v1.jsonl` (a fixed 60-line ledger: header and 59 entries
for agent `kitbot`, kinds `anchor`, `note`, `started`, timestamps crossing the america/new_york dst end on
2026-11-01 and the 2026-12-31/2027-01-01 boundary, five anchors, one of them late).

- read-side cases (32): a transform of the base (identity; one field rewritten and re-dumped; prev rewritten; a
  dropped line; a dropped line with its digest withheld, right and wrong, and with its seq written `33.0`; a cr
  byte; a duplicated key; a truncated tail; a flip re-chained; a kind not declared; header kinds missing started;
  a v0 header; a header with an extra key; a day rewritten at the dst edge; a timestamp with a trailing lf and one
  with fullwidth digits; a v0 entry schema; an anchor's head withheld; lines nested 33 and 1200 deep; an empty
  file and a file of blank lines; a seq written `5.0` and non-ascii keys, which compare `ok` only) and anchor texts
  to check (present, after a later line, a later line with no own entry, own entry disagreeing, another agent's
  word, the strict text form), with what a verifier must answer (`ok`, problem seqs, problems without seq, problem
  codes, head, bridged seqs, anchor results, coverage).
- write-side cases (113): the canonical dump of 14 given objects (the depth-32 bound among them, and strings in nfc,
  nfd and compatibility forms, kept as given) and 7 refusals of values; `day` for 17 timestamps (8 in
  america/new_york across 2026-11-01 03:59:59z to 2026-11-02 05:00:00z, 4 in europe/berlin, 3 in utc, and the year
  edges 1000 and 9998) and 15 refusals of timestamps and zones; `late` for 9 anchors and 1 refusal; 2 header
  digests; 2 anchor texts and 6 refusals; 3 entry ids (one core with its string in nfc and in nfd); 5 composed
  entries and 7 refusals; 15 header checks (`check_header`, section 1's certifies rule: 5 headers accepted, among
  them u+200b and 500 astral characters, and 10 refused, among them u+feff, u+001c, u+001f, u+0085 and the 30
  blanks but lf); 10 anchor compositions over the base (`compose_anchor`, section 5: 2 texts and 8 refusals,
  `day_open` at local midnight and at the dst end, `already_anchored`, `nothing_to_anchor`, `anchor_form`).

every expected value was computed once, by the python package (`vectors/make_vectors.py`), and both runners
(`vectors/run_vectors.py`, `vectors/run_vectors.mjs`) re-ask it of their implementation. each prints
"k of n vectors answered as the file says". the vectors' power was measured by mutation: section 8's counts and the
mutants are in `vectors/README.md`.

## what changed from v0

- schema strings: header `styxx.ledger/log/v1`, entry `styxx.ledger/entry/v1`; header digest = sha256("styxx.ledger/log/v1" + lf + jcs(header)).
- header (line 1): `schema`, `created` (utc `YYYY-MM-DDTHH:MM:SSZ`), `anchor_tz` (an iana zone), `agent` (1-32 chars of `[a-z0-9_-]`), `certifies` (one sentence), `kinds` (a sorted list of the kinds this writer may use; must contain `anchor` and `started`). no other header keys.
- entry: `schema`, `seq`, `prev`, `kind` (in `header.kinds`), `timestamp` (utc z), `day` (the timestamp's calendar day in `anchor_tz`), the kind's own fields, `entry_id`; entry_id = sha256(jcs(core)), core = every key except entry_id; prev of entry 1 = header digest; seq starts at 1 and increments by 1. canonical form and admitted types exactly as v0 section 2 (rfc 8785 subset; floats and non-ascii keys refused at write time; |n| <= 2^53).
- anchor text: `<agent> anchor <YYYY-MM-DD> head <64 hex> seq <n>` (v0's fixed word `gate` becomes the header's agent). anchor entry fields: `anchor_date`, `anchor_head`, `anchor_head_seq`, `anchor_text_sha256`, `late` (bool). the verifier's anchor check is v0 section 5 with that text form.
- a `started` entry carries at least `{"writer": {"name", "version"}}` and may carry more.
- the verifier reports exactly v0 section 4's problem classes (plus "kind not in header.kinds" and "header.kinds missing anchor or started"); it accepts a withheld list and bridges as v0 section 6 says.
- writer durability (both languages): append = take a lock file beside the log (create-exclusive; a lock older than 30 s whose pid is dead may be broken, with a `lock_recovered` entry kind only if the header lists it), re-read the tail to get seq/prev, write the canonical line + lf, fsync, release; refuse to write when the existing file does not re-derive. day computed with the platform's zone database (python zoneinfo; node intl); the vectors pin the dst edges.
- nothing is signed. no network in the core packages; the anchor step is "compose the text and hand it to the caller" plus an optional opentimestamps helper that shells out to a client if present (documented, not required).

### decided after review (2026-11-08 fix pass; not in the list above, the lead's to keep or strike)

these came out of the adversarial conformance pass, where the two implementations disagreed on bytes or verdicts;
each is a shared vector, so both packages are held to it.

- form regexes match the whole string with ascii digits: a trailing lf or a non-ascii digit is not the form.
- timestamp years run 1000..9998.
- `anchor_tz` is the exact-case name the zone database lists, and never `Factory`.
- values nest at most 32 containers deep (`depth` at write time; `unparsable` at read time).
- `late` is section 5's rule (00:10:00 local on the following day), set by the writer, refused at build when wrong.
- a withheld seq written as an integral number (`10.0`) is that integer.
- a file with no header (empty, or blank lines only) is `no_header`.
- a writer refuses to append to a file whose header a v1 writer may not write; the verifier does not report header
  form beyond `kinds`.
- an anchor text whose seq exceeds 2^53 is not an anchor.

### decided in the improvement sweep (2026-11-09; the lead's to keep or strike)

each is a shared vector too (145 in the file now: 32 read-side, 113 write-side).

- `certifies` is 1 to 500 code points, no lf, not only whitespace, whitespace being the 30 code points section 1
  lists. before, the python writer used `str.strip` and the javascript writer `trim`: u+feff alone passed python and
  failed javascript, u+001c..u+001f and u+0085 alone the reverse, and each writer then refused to append to a log
  the other had made.
- strings are never normalised (section 2). both implementations already kept every string as given; the rule was
  implied by "raw utf-8" only, and is now stated and vectored.
- a writer composes an anchor text only for a closed day it has not anchored and that has a line (section 5:
  `day_open`, `already_anchored`, `nothing_to_anchor`). the javascript writer refused these before; the python
  writer's `anchor-text` (without `--record`) composed a postable text for an open day or an anchored one.

v0 remains v0: darkflobi's own ledger keeps its v0 schema strings, and the v1 verifier does not read a v0 file (it
reports `no_header` and says why).

## forbidden claims

no text about this protocol or these packages, in this repository or about it, says:

- "stdlib-only" or "dependency-free" (the python package needs `tzdata` on windows for any named zone; the
  optional timestamp client has its own dependencies);
- "gate your agent in a day", or any zero-to-anchored time (the anchor fires at a midnight, so that span measures
  the clock, not the kit);
- "first", "no one", "provably", "independent";
- that a ledger shows every event got a line, that a line is true, or who wrote it.

every count printed about the packages carries its denominator (k of n vectors, per implementation, per os).
