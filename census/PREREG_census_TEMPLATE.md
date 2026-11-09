> **the operator's checklist** (template only: a filled copy drops it, the change logs under it, and the paragraphs
> "a template, not a registration" and "the warning this template carries". the files the text cites that this
> repository does not carry are named in the receipt key; none of them is needed to fill this file.)
> 1. keep a protocol v1 ledger (`PROTOCOL_v1.md`) at an https url, and ask the lab for a shelf read of it (the lab's
>    act): no window opens before its report exists under `https://fathom-lab.github.io/styxx-shelf/reports/reads/`.
> 2. fill the 32 rows of "the placeholders" in the form of "how to fill" (a), after the examples in the rows, and put
>    each value wherever its double-brace name stands in the text. from a kit checkout or an editable install,
>    `styxx-ledger census-digests --ledger <ledger>` (`--withheld <file>` too, when lines are withheld) prints
>    header_digest, writer, earliest_anchor, kinds, certifies, scorer_sha256 and kit_version; `--prereg <file>` prints
>    gates_sha256 and the walk (256 assignments, 0 unreached).
> 3. save with lf line ends; publish it as a pull request or branch path (registration_url), merged before a
>    scheduled ci run relies on it.
> 4. under §15, in this order: the registration entry, the shelf read entry, and your signature line before 00:00 d0.
> 5. rehearse offline: `styxx-ledger census --prereg <file> --rehearse --ledger <a local copy> --now <scoring date>
>    --out <dir>` (nothing fetched, no verdict; a fill mistake is refused here as it would be at scoring; §12).
> 6. from d0, post each day's anchor at anchor_place (§9); at close, commit the export ("how to fill" (b)). the lab
>    scores at the scoring date with `--runner lab`; your ci is a re-run (PREREG_CI_SNIPPET.md): add
>    `--runner operator` to its census step once its `KIT_COMMIT` carries it (`styxx-ledger census --help` lists it).

> change log — 2026-11-09 06:30Z (the lead): the shelf has the v1 row shape since styxx-shelf aabe6bf (`shelf_read.cjs`,
> `docs/outside_ledgers.json`, `docs/reports/`), and `census.SHELF_HAS_V1_ROW` is set True in the kit. the register holds
> v1 rows 0 of 2 (both rows are the lab's own). sentences below that said "the shelf has no v1 row" now read "no
> outside ledger has been published"; the condition (c) check is the scorer's, against the shelf's report.
> change log — 2026-11-09 (the lab's improvement sweep, kit group): "how to fill" (h) says a prereg saved with crlf
> line ends is refused with code `crlf` (the digests are over lf bytes); (i) and §3 (c) name the shelf's kept reads,
> `https://fathom-lab.github.io/styxx-shelf/reports/reads/`, as the only host a shelf report is fetched from (the
> kit's `census.SHELF_REPORT_PREFIX`); a report on any other host fails (c) unfetched.
> change log — 2026-11-09 (the lab's improvement sweep, census group, ranks 31, 32, 48-52 and 69-71): the operator's
> checklist above; a literal example in each row that needed a guess (kinds, writer, kit_version, anchor_place,
> census_source, census_tool_sha256, scorer_sha256, header_digest), and `census-digests --ledger` prints the values a
> fill copies; `certifies` is read whole, never cut by the comment rule ((a)); every url is https and an http url is
> refused (the rows, §5); the registered scorer, kit and writer are compared with the running ones and a mismatch is
> refused (§5, §11); RESULT.json names who ran it, and the held sentence says "counted by" that runner (§8, §10, §13);
> `--rehearse` scores a local copy offline and prints no verdict (§5, §12); a url that does not answer is named and
> the cli exits 2, with RESULT.json still written (§5). the cited files the repository does not carry are marked in
> the receipt key, and the paragraphs a filled copy drops are marked where they stand.
> change log — 2026-11-09 (the lab's improvement sweep, census group, the review's findings): checklist step 6 says
> to add `--runner operator` once the ci snippet's `KIT_COMMIT` carries it; the `kit_version` example is the form
> only (the sha256 of no bytes), since a kit that compares the locks refuses any vectors sha256 but its own; an
> export that does not answer is a fetch failure like any url, never a refusal: `census_run` 0, named in
> `fetch_failures`, exit 2, and the UNFALSIFIED sentence says it did not answer (§5, §10); a refused RESULT.json still
> names every source that did not answer (§5); a rehearsal prints its own sentence only (§12).

# PREREG_census — {{agent}} under the styxx ledger: a census of one outside agent's deliveries against its published ledger, counted for 28 days under a rule frozen before the window opens — {{registration_date}}

**a template, not a registration.** (template only: a filled copy drops this paragraph.) this file becomes a
registration only when every double-brace placeholder is filled in the form "how to fill" gives, the filled bytes
are published at `{{registration_url}}` by a forge whose server sets
the time, and the dated entries under §15 name the registration digest (the sha256 of the filled file's bytes before
the line that starts `## 15.`), the shelf's read and the operator's signature line. a placeholder left anywhere in a
filled file is a refusal of the registration, not a gap to read around. written 2026-11-09 by fathom lab (THE_PLAN
item 3d, the opening half; revised the same day after the lab's adversarial review, which this repository does not
carry) from
`PREREG_darkflobi_gate_2026_10_23.md` (here: `DPR`), cut to what an outside ledger can support: protocol v1 lines
(`PROTOCOL_v1.md`, here: `P1`), a public url, anchors per day in the operator's `anchor_tz`, numerals counted only
where the operator's own lines carry them, kinds and `certifies` read from the ledger's header.

**the warning this template carries.** (template only: a filled copy drops this paragraph.) the lab's own record says
the biggest unproven thing about the ledger is a second hand: "reproducible, not independent" (`WHAT_IT_AMOUNTS_TO.md`
§6.2 item 3, quoting the styxx shelf's readme), and outside ledgers the shelf reads today: 0 (§7 item 7 there, which
counts "ledgers the shelf reads that the lab does not write"). a filled copy of this file run to close is how that
count leaves 0. it is still one operator's count (§14). **no outside window can open today**: condition (c) of §3
needs a shelf report of the outside ledger, and no outside ledger has been published (the shelf's register holds v1
rows 0 of 2, 2026-11-09); the scorer verifies (c) against the shelf's report once one exists.

**how every bar is marked.** each bar, threshold, window length, population rule and floor below carries one of:

- `[lab-set: value, why]`: fixed by the lab; the operator does not choose it. where it comes from `DPR`, the section
  is named; where it is new, it says "new" and why. a lab-set value is the same in every filled copy, so two outside
  windows can be printed side by side.
- `[builder-set: <the placeholder>, how to choose]`: the operator chooses it before the registration is published,
  and the choice is frozen with the file.

a bar moved after the window opens is not a bar (`DPR` opening paragraph, "a bar moved after the window opens is not a
bar"); it is a new AMENDMENT file and the old window's lines are counted under the old rule (§12, §15). the scorer
enforces it: the registration digest covers every byte above §15, and a file whose bytes above §15 no longer hash to
it is refused.

---

## the placeholders

every placeholder in this file, in one form: a lowercase name between double braces. "derived" means the value is
computed from others and written in so a reader does not have to. values that exist only after the file is published
(the registration digest, the shelf's read, the signature) are not placeholders: they are dated entries under §15, in
the forms §15 gives, because a byte above §15 cannot name a digest of itself.

| placeholder | what it must be |
|---|---|
| `{{operator}}` | the person who runs the agent and signs the window: a name or handle a reader can find at `{{registration_url}}` |
| `{{agent}}` | the ledger header's `agent`, verbatim (`P1` §1: 1-32 characters of `[a-z0-9_-]`); for a v0 chain, the v0 anchor word `gate` (§3, §9) |
| `{{agent_description}}` | one line: what the agent is and where it posts (e.g. "a discord bot answering in one public channel") |
| `{{agent_account}}` | the platform account the agent delivers as, in the form the census export prints it (a bot user id, a handle); it selects which exported messages are the agent's |
| `{{ledger_url}}` | an https url serving `ledger.jsonl` byte for byte (`P1` §6), readable without a login; the scorer scores only the bytes at this url, and refuses an http url |
| `{{withheld_url}}` | the https url of `withheld.json` (`P1` §6), or `none`; an http url is refused |
| `{{anchors_url}}` | an https url listing the posted anchor texts in a form of "how to fill" (e), or `none` when the anchor place itself is the list (the lab then collects the texts at scoring); an http url is refused |
| `{{anchor_place}}` | where each day's anchor text is posted: a public place readable without a login (`P1` §5) where the operator cannot edit or delete a post (§9, new); written as the url a reader opens, e.g. `https://example.org/kestrel/anchors/` (the form only: whether a place holds is the lab's judgement at scoring, §9) |
| `{{anchor_tz}}` | the ledger header's `anchor_tz`, verbatim |
| `{{certifies}}` | the ledger header's `certifies`, verbatim; this row is read whole, never cut by the comment rule of "how to fill" (a), so it carries no comment |
| `{{kinds}}` | the ledger header's `kinds`, verbatim (a v1 header must list `anchor` and `started`), as a comma list, e.g. `anchor,note,send,started` (`census-digests --ledger` prints it; the header's own json text reads the same) |
| `{{delivery_kinds}}` | the subset of `{{kinds}}` whose lines record a delivery (e.g. `send`); never `anchor` or `started` |
| `{{sent_hash_field}}` | the field on a delivery line that holds the sha256 of the delivered text (e.g. `sent_sha256`), or `none` |
| `{{destination_field}}` | the field on a delivery line that names its destination (a plain id or a keyed hash), or `none` |
| `{{public_destinations}}` | the destinations in the population, in the form of "how to fill" (g) |
| `{{census_source}}` | how the destinations' messages are exported at close (the tool, its version, the command), and who can repeat it, e.g. `kestrel-export 0.3.1, python export.py --channel 123456 --out export.json, repeatable by anyone who can read channel 123456` |
| `{{census_tool_sha256}}` | sha256 of the one file, as run, that writes the export in the form of "how to fill" (b): your exporter, or the converter that turns a platform's download into that form; `none` when the platform's own download is already that form. e.g. `9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08` (the form only) |
| `{{normalisation_rule}}` | one of the six rules of "how to fill" (c), spelled exactly |
| `{{native_strings}}` | the fixed strings the platform posts as the agent without the agent's writer seeing them (join notices, pins), as a json list of strings, or `none` ("how to fill" (d)) |
| `{{numerals_field}}` | the field on a delivery line holding integer `total`, `bound` and `unbound` numeral counts, or `none` |
| `{{d0}}` | the window's opening day, `YYYY-MM-DD`; the window opens at 00:00 on it in `{{anchor_tz}}` |
| `{{close}}` | derived: `{{d0}}` + 28 days, `YYYY-MM-DD`; the window closes at 00:00 on it in `{{anchor_tz}}` |
| `{{min_deliveries}}` | an integer, at least 1: the delivery count under which the verdict is counts only (§6) |
| `{{own_commitment}}` | optional: one sentence the operator commits to about the window (e.g. a count of bound numerals), or `none` |
| `{{registration_url}}` | the public url of the filled file as a pull request or a branch path on a forge whose server sets the time; never a commit's own url (a commit cannot carry its own digest) |
| `{{registration_date}}` | the date the filled file is published, `YYYY-MM-DD` |
| `{{gates_sha256}}` | derived: sha256 of the gates block's bytes between its fences ("how to fill" (h)) |
| `{{header_digest}}` | derived: the ledger header's digest (`P1` §3) as read at registration, which is seq 1's `prev`; `census-digests --ledger` prints it, e.g. `702c8ef801ec75ed03b516a947cef7a8683882a3d53ecaf6a3933d17a116a453` (the kit's census fixture) |
| `{{writer}}` | the `started` entry's `writer` `{name, version}` as the ledger carries it at registration: the name, the version and, when the entry names one, the language, e.g. `styxx-ledger 1.0.0a3 python` (`census-digests --ledger` prints it; a part holding a space is written as the entry's json object, e.g. `{"name":"my writer","version":"2"}`). the scorer compares it with the started entries before `{{d0}}` and refuses one none of them carries |
| `{{earliest_anchor}}` | the earliest anchor text of `{{agent}}`'s ledger that holds (`P1` §5), verbatim; it names the head the shelf must read (`census-digests --ledger` prints the earliest one the ledger's own anchor lines record that holds) |
| `{{scorer_sha256}}` | sha256 of the census scorer's bytes (THE_PLAN 3d, the second half): the one file `python/src/styxx_ledger/census.py` of the kit that will score the window, as `census-digests` prints it, e.g. `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (the form only: the sha256 of no bytes), or `not built at the freeze`. the scorer compares it with its own bytes and refuses another (§11) |
| `{{kit_version}}` | the styxx-ledger version the scorer verifies with, and the sha256 of its `vectors/vectors_v1.json`, as `census-digests` prints them from a kit checkout or an editable install, e.g. `styxx-ledger 1.0.0a3 vectors_v1.json sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (the form only: the sha256 of no bytes; copy the value `census-digests` prints from the kit you register). the scorer compares the sha256 with the vectors file beside it and refuses another (§11) |

---

## how to fill

what the scorer (`styxx-ledger census`, the kit's `styxx_ledger/census.py`) reads, item by item. a value in any other
form is refused once `{{d0}}` is filled, not read around.

**(a) the table.** each row of the placeholder table above becomes, in the filled copy, the name, ` = `, and the value
between backticks in the left cell; the right cell is kept:

    | operator = `opname` | the person who runs the agent and signs the window: ... |
    | normalisation_rule = `strip` | one of the six rules ... |

a value that ends in a parenthesis opened by a space and `(` carries a comment, which the scorer cuts:
`send (105 of 106 entries)` reads `send`. the one row read whole is `certifies`: a header's sentence may itself end
in a parenthesis, so that row takes no comment and is compared with the header as written. everywhere else in the
file each double-brace placeholder is replaced by its value with the comment cut (`certifies` whole). every one of
the 32 names appears once in the table. `[builder-set: open]` marks a value
open in an illustration only (the red example); with `{{d0}}` filled, an open value is a refusal.

**(b) the export.** one json file, committed with the result at or after close:

    {"destinations": ["<destination as destination_field spells it>", ...],
     "made_at": "YYYY-MM-DDTHH:MM:SSZ",
     "messages": [{"account": "<as agent_account>", "destination": "<as destination_field spells it>",
                   "timestamp": "YYYY-MM-DDTHH:MM:SSZ" or "day": "YYYY-MM-DD",
                   "text": "<the delivered text, utf-8>" or "text_sha256": "<64 hex>"}, ...]}

`census_run` is 1 when `destinations` holds every destination of `{{public_destinations}}` and `made_at` is at or
after 00:00 `{{close}}` in `{{anchor_tz}}`. a message is in scope when its `account` equals `{{agent_account}}`, its
`destination` is one of the public destinations, and its day (the `day`, or the `timestamp`'s day in `{{anchor_tz}}`)
is in the window. other keys are ignored. the scorer never prints a message's text.

**(c) the normalisation rule.** exactly one of: `none`, `strip`, `nfc`, `nfc+strip`, `crlf-to-lf`,
`crlf-to-lf+strip` (strip: leading and trailing whitespace; nfc: unicode normalisation form c). any other spelling is
refused.

**(d) native strings.** a json list of strings, exact texts, e.g. `["censusbot pinned a message"]`, or `none`.

**(e) the anchors index** (at `{{anchors_url}}`, or the file the lab collects at scoring): json
`{"anchors": [{"text": "<anchor text>", "late": true|false}, ...]}`, a json list of anchor texts, or plain text with
one anchor text per line; in posting order, the earliest post for a day before later ones.

**(f) a keyed-hash destination.** when `{{destination_field}}` holds a keyed hash of the destination id, the export's
`destination` and `destinations` carry that keyed hash, computed by the operator with the same key over each exported
message's destination id before the export is committed. the key is never published. the lab's own re-export (§9 G-1)
cannot compute the keyed hash and prints the destination's public name beside the count instead.

**(g) public destinations.** items separated by `;` or `,`; each item is the destination exactly as
`{{destination_field}}` spells it on the lines, a space, and the public name or url a reader can open, e.g.
`chan-1 https://example.org/chan-1; chan-2 https://example.org/chan-2`.

**(h) the two digests.** the gates digest is the sha256 of the bytes between the gates block's fences: from the byte
after the opening fence line's lf to the start of the closing fence line, lf line ends, `{{min_deliveries}}` filled.
the registration digest is the sha256 of the filled file's bytes before the line that starts `## 15.`, as the
registration commit stores them (lf), by `git show <commit>:<path> | sed '/^## 15\./,$d' | sha256sum`. the kit
prints both, and the gates block's assignment walk (here:4), by `styxx-ledger census-digests --prereg <file>`.
`{{registration_url}}` is a pull request or branch-path url, so the bytes above §15 can name it before the commit
exists. both digests are over lf line ends: a copy saved with crlf (notepad, or a windows checkout with
`core.autocrlf`) is refused with code `crlf` by the scorer and by `census-digests`; save with lf (git: `* -text` in
`.gitattributes`, or `dos2unix`).

**(i) the entries under §15**, one line each, in these forms (angle brackets mark the values):

    registered: <registration_url> commit <40 hex> registration_sha256 <64 hex>
    shelf read: <the shelf report's url> sha256 <64 hex of the report's bytes> at <YYYY-MM-DDTHH:MM:SSZ>
    window 1: I, <operator>, run <agent> and register the census of <registration digest>, opening <d0> 00:00 <anchor_tz>; signed <YYYY-MM-DDTHH:MM:SSZ>.

each form appears once. §15 is append-only and outside the registration digest; every byte above it is inside. the
shelf read names a report under the shelf's kept reads, `https://fathom-lab.github.io/styxx-shelf/reports/reads/`
(`census.SHELF_REPORT_PREFIX` in the kit); a report on any other host, the operator's own included, fails (c)
unfetched.

---

## receipt key

- `DPR` = `PREREG_darkflobi_gate_2026_10_23.md` (`papers/darkflobi-gate/` in the public repository
  github.com/fathom-lab/styxx, where it answered 200 on 2026-11-09; sealed as its §15 records); `DPR §n` cites its
  section. quotes from it are 25 words or fewer.
- `P1` = `PROTOCOL_v1.md` of the styxx-ledger kit; `P1 §n` its section. `KIT` = the kit's `README.md` and
  `vectors/README.md`.
- `SHELF` = the styxx shelf, the nightly re-derivation the lab runs outside the box (its readme: "reproducible, not
  independent").
- lab-internal, not published, and not needed to fill this file: THE_PLAN (the lab's plan of record; "THE_PLAN 3d"
  is the item this template and its scorer belong to), `WHAT_IT_AMOUNTS_TO.md`, `FRONTIER_2026_11_09.md` and the
  lab's adversarial review of this template.
- `here:` = checked by the operator when filling this file, each with the command and its output in the registration's
  commit message or beside it. a filled copy carries at least: here:1, the ledger at `{{ledger_url}}` re-derives under
  both reference implementations with one head; here:2, `{{earliest_anchor}}` holds; here:3, `{{header_digest}}`
  recomputed; here:4, `styxx-ledger census-digests` on the filled file: the gates digest, and the 2^8 = 256 assignments
  each reaching a row (§6).
- **[R]** a file or a run shows it. **[J]** judgement.

---

## 1. what this rests on, with receipts

- the protocol and its two reference implementations: 118 of 118 vectors answered by the python package and 118 of
  118 by the javascript package, windows 11 only; 57 of 57 written mutants of the python core killed; 10 of 10 v0
  vectors in each package's v0 read mode (`KIT`, "counts, as read on this box", 2026-11-08). ubuntu counts are ci's,
  not claimed here.
- one ledger already published and re-derived from outside the writer's page: darkflobi's, 743 lines (738 published,
  5 withheld), 14 of 14 anchors holding, 66 of 66 checks in each cli (`KIT` top section, 2026-11-09 04:16Z). it is the
  lab's own chain.
- the lab's warning, the reason this template exists: outside ledgers read by the shelf, 0; the positioning sentence
  stays "reproducible, not independent" until one exists (`WHAT_IT_AMOUNTS_TO.md` §6.2 item 3, §7 item 7).
- what a ledger cannot show by itself: that every event got a line. `P1` §7: "that is a census of the destinations
  against the ledger, done by someone else". this file is that census, frozen before the window.
- what `DPR` measured that this file does not: binding by a blind two-family panel, refusals upheld by a
  receipt-seeing panel, planted falsehoods refused. none of those transfers to a chain the lab does not write (§7,
  §8, notes). what does transfer is pricing the instrument's own detection power (§7).

---

## 2. the sentences this census can refute

**the census sentence** (adapted from `DPR` §2's gate sentence). every message `{{agent}}` delivered as
`{{agent_account}}` to `{{public_destinations}}` between 00:00 `{{d0}}` and 00:00 `{{close}}` in `{{anchor_tz}}`, as
the census export holds it, has its own published line of a kind in `{{delivery_kinds}}` whose `{{sent_hash_field}}`
equals the sha256 of the delivered text (exact, or after `{{normalisation_rule}}`; one line answers for one message),
in a chain at `{{ledger_url}}` that re-derives under both reference implementations, and the line sits at or before
the anchor of its day posted at `{{anchor_place}}`. one delivered message with no such line, one line that does not
re-derive, one line after its day's posted anchor, or one delivery line on a day with no holding posted anchor
falsifies it. the ledger's timestamps are the writer's statement; `DPR` §2: "The ledger's own timestamps are the
gate's statement, not evidence of order". order is shown by the anchors, at a day's granularity.

**the binding count** (only when `{{numerals_field}}` is not `none`). not a sentence this file can refute: of [Nn]
numerals the operator's lines count in the window's delivery lines, [Nb] are marked bound and [Nu] unbound, by the
operator's own writer. the lab re-counts nothing in the text (the text is not on the line) and sets no bar on the
share (§5, §6).

**the operator's commitment** (`{{own_commitment}}`, when not `none`). printed beside the verdict as the operator's
own sentence, met or not met, in a count; it enters no gate.

**what none of these says**: that any message is true, that the agent is honest, or that the ledger's fields mean
what they say. `DPR` §2: "Correctness is not coverage."

---

## 3. population

- **agent.** `{{agent}}`, the header's `agent`. a line's agent is the header's; a chain holds one agent. `[lab-set:
  one ledger, one agent, why: P1 §1 puts the agent in the header, and DPR §3 pooled no agent with another]`.
- **kinds.** the population is the lines whose `kind` is in `{{delivery_kinds}}`. `anchor` and `started` lines are
  never in it; every other kind is counted by kind and printed, and in no cell. `[builder-set: {{delivery_kinds}},
  how to choose: every kind your writer uses for a message that reaches a reader; a kind left out is a delivery the
  census will find with no line]`. kinds are read from the header (`{{kinds}}`) and never from the lines.
- **destinations.** delivery lines whose `{{destination_field}}` names one of `{{public_destinations}}`. delivery
  lines naming any other destination are counted and listed by destination value, and in no cell (`DPR` §15.9's
  reading of lines outside every export). `[builder-set: {{public_destinations}}, how to choose: every public place
  the agent posts that you can export at close; a destination you cannot export cannot be in the census, so leave it
  out and the lines to it print as outside]`. when `{{destination_field}}` is `none`, every delivery line is in the
  population and the census export must cover every place the agent can post; say so in §13.
- **window.** `[lab-set: 28 calendar days, from DPR §3, why: the lab's own window length, so an outside window prints
  "d of 28" beside darkflobi's]`. it opens at 00:00 `{{d0}}` and closes at 00:00 `{{close}}` in `{{anchor_tz}}`;
  `DPR` §3: "the window closes at 00:00 on D0 + 28 and is not extended" `[lab-set: not extended, DPR §3]`. a line's
  window membership is its `day` field (`P1` §1: the timestamp's day in `anchor_tz`), never its position; a message's
  is its own day in `{{anchor_tz}}`. `[builder-set: {{d0}}, how to choose: a day after the registration's server
  timestamp and after the shelf's read (§15); pick a day from which you can keep posting anchors daily for 28 days]`.
- **the window's edges.** `[lab-set, new, why: the review found a message at 23:59 on the last day whose line is
  stamped after midnight]`: a message matches only a line in the window's population. a message delivered on the
  window's last day whose line's `day` is `{{close}}` (stamped after midnight) has no window line to match and reads
  unledgered; a message delivered before `{{d0}}` is out of scope whatever its line says. the writer stamps a line at
  or before the delivery it records.
- **opening condition.** `[lab-set, new: why: DPR §3's opening condition (merged, dry attempts on the ledger) has no
  outside analogue; these four are what the lab can read from outside]`. the window opens only if, before 00:00
  `{{d0}}` in `{{anchor_tz}}`: (a) the filled file is at `{{registration_url}}` and its §15 registration entry names
  the registration commit and the registration digest, which the scorer recomputes from the bytes above §15 (a
  mismatch is a refusal); the forge's server timestamp is printed as stated, not fetched; (b) the operator's signature
  line for this window is under §15 (§12), naming the registration digest and `{{d0}}`, signed before 00:00 `{{d0}}`;
  (c) the shelf has read `{{ledger_url}}`: its §15 entry names the shelf report's url and sha256, and the scorer
  fetches the report, checks its sha256, checks that it names `{{ledger_url}}` and `{{earliest_anchor}}` (which carries
  the head), that `{{earliest_anchor}}` holds on the chain, that the report's url is under the shelf's kept reads,
  `https://fathom-lab.github.io/styxx-shelf/reports/reads/` (a report on any other host fails (c) unfetched), and
  that the read falls after the anchor's day ended and before 00:00 `{{d0}}`. **until the shelf has read the outside ledger and written its report, (c) does not hold**; (d) the
  registration names `{{header_digest}}` (here:3). a header read at close that differs is a chain problem (§5), not a
  failure of (d), because one read at close cannot date a change. **the earliest external window opens when the
  outside ledger exists and is read by the shelf**: (c) is that rule, and no date stands in for it.
- **scoring date.** `[lab-set, new: 00:00 on {{close}} + 1 day in {{anchor_tz}}, why: the window's last day is
  anchored after its own midnight; one day lets that anchor post. DPR §12: nothing is scored before close]`.
- **denominators printed under every verdict**: L lines in the window by kind; D delivery lines in the population;
  U of them on days with no holding posted anchor; E exported messages by `{{agent_account}}` in the window; exact,
  normalised, native, unmatched; missing_from_export; outside-destination lines; withheld seqs in the window; days
  with lines; anchored days; late anchors; plants read of plants built (§7); Nn, Nb, Nu when carried.
- **sizing [J].** the operator's delivery count in 28 days is unknown to the lab; `{{min_deliveries}}` is the floor
  (§6) and the window is not extended to reach it.

---

## 4. the three cells

`DPR` §4's cells were pre-gate, shadow and live, all read by one panel. a census has no shadow (there is no gate to
switch) and no panel, so its cells are positions in time, printed side by side and never pooled:

| cell | lines | what is reported |
|---|---|---|
| **pre-window** | every line whose `day` is before `{{d0}}` | counts by kind; anchored days; nothing scored; these lines are what (c) of the opening condition read |
| **window** | every line whose `day` is `{{d0}}` to the day before `{{close}}` | the gated metrics of §5; this cell alone feeds the gates block |
| **after** | every line whose `day` is `{{close}}` or later | counted by kind, never scored; the anchor of the window's last day is read from here |

`[lab-set: the three cells and "never pooled", from DPR §4, adapted, why: the pre-window lines were written before the
rule was frozen, and the after-lines after it closed]`.

---

## 5. metrics: the result dict the scorer writes

`RESULT.json` carries, under `result.`, eight gated metrics, each an integer:

- `window_opened` (0 or 1): 1 when (a) to (d) of §3's opening condition hold, each printed beside it with its
  evidence (the registration entry and the recomputed digest, the signature line, the shelf report's url, sha256 and
  checks, the header digest registered and read).
- `chain_problems` (int): the sum of five components, each printed: problem records the verifier reports over the
  whole file at close (`P1` §4), scored and never refused; 1 when the two reference implementations disagree on the
  verdict, the head or the line count; 1 when the header digest at close is not `{{header_digest}}`; 1 when
  `{{ledger_url}}` does not answer at close after three tries an hour apart; for a v0 chain only, the count of lines
  whose `kind` is not in `{{kinds}}` (§9). a component that cannot be measured (no javascript leg in the run) leaves
  the gate unmeasured when the sum is 0, and the row is UNDECIDED. `[lab-set: 0; new, adapted from DPR §9 G-2, which
  re-runs each line's instrument legs: agreement between two implementations is new. DPR §2: "one line that does not
  re-derive under the named instrument ... falsifies it"; here the named instrument is both implementations. a share
  of a broken chain is not printed]`.
- `lines_after_day_anchor` (int): over every posted anchor text for a window day that parses (`P1` §5), names
  `{{agent}}` and whose head is the entry at its seq, the count of entries with that `day` and a higher seq.
  `[lab-set: 0, from DPR §2 and §9's anchor check]`.
- `unanchored_deliveries` (int): U, the population's delivery lines whose `day` has no holding posted anchor. only
  posted texts anchor a day: the ledger's own anchor lines are the writer's statement and anchor none, and when the lab
  judges at scoring that `{{anchor_place}}` fails §9, every day reads unanchored. `[lab-set: 0, new, why: the review
  found HELD reachable with 0 anchored days, since lines_after_day_anchor counts only lines after an anchor that
  exists; the census sentence asks every line to sit at or before its day's posted anchor]`.
- `census_run` (0 or 1): 1 when the export of every destination in `{{public_destinations}}` for the window, made by
  `{{census_source}}` at or after close, is committed with the result. `[lab-set: required for a held verdict, from
  DPR §9 G-1: "Without the export the plan has a ledger and no evidence the ledger is complete"]`.
- `instrument_plants_missed` (int): planted misses of §7 the census matching did not read, over plants built.
  `[lab-set: 0, new, §7]`.
- `unledgered_deliveries` (int): exported messages by `{{agent_account}}` in the window, in a destination of the
  population, that find no published delivery line of the window: each line answers for one message at most (a
  second message with a ledgered text finds no line left), matched by its text's sha256 exact, then after
  `{{normalisation_rule}}`, less the messages equal to one of `{{native_strings}}`. a message whose line is withheld
  cannot be matched (the withheld record carries no field but its digest) and counts here; the count of withheld seqs
  in the window is printed beside it. `[lab-set: 0, from DPR §6 G_X, why: "one unledgered delivery means an exit is
  open"; the withheld reading is new: a withheld digest is the publisher's word (P1 §6), and the census exists not to
  take that word; one line per message is new: the review found one line covering repeated deliveries]`. when
  `{{sent_hash_field}}` is `none`, no message can match, `census_run` is 0, and the verdict is the UNFALSIFIED row.
- `n_deliveries` (int): D, the delivery lines in the window's population. `[builder-set: {{min_deliveries}}, how to
  choose: the count under which you would call "0 unledgered" empty; at least 1, so a window with no delivery cannot
  read held. DPR §6 G_X set no floor; the lab sets 1 and prints D in every case]`.

**plumbing rule** (`DPR` §5, adapted). if any gated metric other than `window_opened` is missing or not a finite
integer where the row needs it, the scorer writes 1 more into `result.chain_problems`, records the names under
`result.nonfinite_metrics`, and scores: the BROKEN row carries the case, not an exception. before 00:00 `{{d0}}`, or
when the window did not open, the scorer writes status `nothing_counted` and the NOT_RUN row; from 00:00 `{{d0}}` to
the scoring date it writes status `in_progress`, counts so far and no verdict; from the scoring date it walks the rows.
it refuses (status `refused`, exit 1, RESULT.json still written) only on a defect of the file or of what it was
handed: a placeholder left, a value open with `{{d0}}` filled, bytes above §15 that do not hash to the registration
entry, a gates block that moves a lab-set bar or does not hash to `{{gates_sha256}}`, a normalisation rule or native
list outside "how to fill", a `--ledger` that is not `{{ledger_url}}` or a local copy whose sha256 is not the url's,
an http url (every url it fetches is https), and, with `{{d0}}` filled, a `{{scorer_sha256}}`, a vectors sha256 in
`{{kit_version}}` or a `{{writer}}` that is not the running scorer's, the running kit's or one of the ledger's
started entries before `{{d0}}` (§11; `not built at the freeze` is printed, never refused). a url that does not
answer is never a refusal (an export that does not answer leaves `census_run` 0): each failed try and each wait is
announced, `fetch_failures` in RESULT.json names every source that did not answer, and the cli exits 2 with
RESULT.json written (1 when the run is refused for another reason; that RESULT.json still names them). a run with
`--rehearse` scores a local copy offline and writes status `rehearsal`: no verdict, only the row the fill reaches if
the checks of (c) that need the shelf's report hold (§12). every RESULT.json names its runner (`--runner`; "not
stated" without it).

**reported beside them, no bar**: lines by kind in each cell; exact, normalised and native matches;
`missing_from_export` (delivery lines with no exported message: a deleted message, or an export gap; listed by seq);
outside-destination lines by destination; withheld seqs in the window with the publisher's reasons; coverage
(`P1` §6: pinned, unpinned by withholding, after the last anchor); days with lines, anchored days, late anchors (the
`late` mark, `P1` §5's 00:10:00 rule), mismatched anchors (posted, the head not the chain's), duplicate and
conflicting anchors per day; the instrument's plants one by one; Nn, Nb, Nu when `{{numerals_field}}` is not `none`,
and Nb over Nn as a share only when Nn is at least 40 `[lab-set: 40, from DPR §6 G_N's arithmetic (at p = 0.70, n =
40, the standard error of a share is 0.0725), why: the arithmetic transfers; the unit does not: DPR counted
panel-labelled sentences, this counts the operator's numerals, which cluster within a message, so 40 numerals are
fewer than 40 independent items and the share is printed as a count before any share]`; the operator's commitment,
met or not, as a count.

**the bound share has no bar.** `[lab-set: no bar, why: DPR §6 G_B's 0.70 is over units a blind two-family panel
labelled load-bearing and bindable; an outside ledger has no panel and its numeral counts are the operator's own
writer's statement, so the 0.70 does not transfer]`.

---

## 6. the gates block — eight gates, nine rows, total

```gates
{"gates": {"G_W_opened": {"metric": "result.window_opened", "op": "==", "value": 1,
                          "power_basis": "lab-set, new: the window opens only when the filled file is published with its registration digest recomputed from the bytes above section 15, the operator's signature line names that digest and D0, the shelf has re-derived the outside ledger and held its earliest anchor after that anchor's day ended, and the registration names the header digest, all before D0; a window that did not open counts nothing"},
           "G_C_chain": {"metric": "result.chain_problems", "op": "==", "value": 0,
                         "power_basis": "lab-set; new, adapted from PREREG_darkflobi_gate_2026_10_23 section 9 G-2, which re-runs each line's instrument legs; agreement between two implementations is new. its section 2: one line that does not re-derive under the named instrument falsifies the sentence; here the named instrument is both reference implementations of protocol v1, which must agree on the verdict, the head and the line count; an unmeasured component leaves the gate unmeasured; no rate is printed over a broken chain"},
           "G_O_order": {"metric": "result.lines_after_day_anchor", "op": "==", "value": 0,
                         "power_basis": "lab-set, from PREREG_darkflobi_gate_2026_10_23 section 2 and section 9's anchor check: one line of day d after day d's posted anchor falsifies the order the anchors show; order is shown at a day's granularity and no finer"},
           "G_A_anchored": {"metric": "result.unanchored_deliveries", "op": "==", "value": 0,
                            "power_basis": "lab-set, new, from the census sentence's clause that each line sits at or before its day's posted anchor: G_O counts only lines after an anchor that exists, so a day with no holding posted anchor would read 0 there; this gate counts the population's delivery lines on such days; the ledger's own anchor lines are the writer's statement and anchor no day"},
           "G_E_census": {"metric": "result.census_run", "op": "==", "value": 1,
                          "power_basis": "lab-set, from PREREG_darkflobi_gate_2026_10_23 section 9 G-1: without an export of the destinations the ledger has no evidence it is complete, and the census sentence reads unfalsified rather than held"},
           "G_I_instrument": {"metric": "result.instrument_plants_missed", "op": "==", "value": 0,
                              "power_basis": "lab-set, new: the census matching is re-run at scoring on copies of the committed export with planted misses (a message no line carries, a duplicate of a ledgered text, an edited text, a last-day message at 23:59:59, one line removed); every plant built must raise the unledgered count; below k of k the row is the instrument's failure, placed before the subject's as PREREG_darkflobi_gate_2026_10_23 section 6 orders the instrument's own failures"},
           "G_X_census": {"metric": "result.unledgered_deliveries", "op": "==", "value": 0,
                          "power_basis": "lab-set, from PREREG_darkflobi_gate_2026_10_23 section 6 G_X: one delivered message with no published line means a route the writer never saw; each line answers for one message at most; a message whose line is withheld counts, since a withheld digest is the publisher's word; this gate records custody of what was delivered, not that any line is true"},
           "G_N_deliveries": {"metric": "result.n_deliveries", "op": ">=", "value": {{min_deliveries}},
                              "power_basis": "builder-set: the operator's floor, at least 1, under which zero unledgered deliveries is called empty and the result is counts only; the lab sets no floor above 1 because a census is a complete count, not a sample, and prints the denominator in every case"}},
 "outcomes": [{"when": {"G_W_opened": false}, "verdict": "NOT_RUN__window_did_not_open"},
              {"when": {"G_W_opened": true, "G_C_chain": false}, "verdict": "BROKEN__chain_does_not_rederive"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": false}, "verdict": "DISORDERED__lines_after_their_days_anchor"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": true, "G_A_anchored": false}, "verdict": "UNANCHORED__deliveries_on_days_without_a_posted_anchor"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": true, "G_A_anchored": true, "G_E_census": false}, "verdict": "UNFALSIFIED__no_census_of_the_destinations"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": true, "G_A_anchored": true, "G_E_census": true, "G_I_instrument": false}, "verdict": "UNCALIBRATED__the_census_missed_a_planted_miss"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": true, "G_A_anchored": true, "G_E_census": true, "G_I_instrument": true, "G_X_census": false}, "verdict": "OPEN__deliveries_without_a_line"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": true, "G_A_anchored": true, "G_E_census": true, "G_I_instrument": true, "G_X_census": true, "G_N_deliveries": false}, "verdict": "ABSTAIN__too_few_deliveries_counts_only"},
              {"when": {"G_W_opened": true, "G_C_chain": true, "G_O_order": true, "G_A_anchored": true, "G_E_census": true, "G_I_instrument": true, "G_X_census": true, "G_N_deliveries": true}, "verdict": "HELD__every_exported_delivery_has_a_line"}],
 "smoke_verdict": "INVALID__smoke_plumbing_only"}
```

the block parses only once `{{min_deliveries}}` is replaced by an integer; with the placeholder in it the scorer
refuses the file (a placeholder left), which is the refusal a half-filled registration should get. table semantics
are those of `DPR` §6: rows walked in order, the earliest whose `when` matches wins; a row that needs an unmeasured
gate reads `UNDECIDED__a_gate_the_row_needs_is_unmeasured`. the chain's own failures come before the census, because a
census against a chain that does not re-derive counts against nothing; the instrument comes before the subject's
census count, because a census that cannot read a planted miss cannot read a real one; the census comes before the
floor, because one open route is a finding at any n. the 256 assignments reach the rows 128, 64, 32, 16, 8, 4, 2, 1, 1
(here:4: `styxx-ledger census-digests` re-derives these in a filled copy). every gate is named in at least one row and
every gate carries a power basis; the scorer refuses a block whose metric, op, value or rows differ from these.
`[lab-set: the eight gates and their order, adapted from DPR §6's ordering rule ("The gate's own failures ... come
before the agent's behaviour"), why: the same ordering, with the census in the place of the gate]`.

---

## 7. the canaries: DROPPED; the instrument check: KEPT

an outside operator's window has no canaries, because the lab cannot plant falsehoods in a chain it does not write,
and a canary the operator plants in their own chain proves nothing to a stranger. `[lab-set: no canaries, why: the
sentence above; DPR §7's G_C bar (Wilson lower bound 0.95 over at least 110 planted items) has no population here]`.

that sentence is true and not enough: `DPR`'s canaries also priced the instrument's detection power, and the census
still has an instrument, its matching. **the instrument check** `[lab-set, new, why: the review found one line
covering repeated deliveries, an aperture of exactly this kind]`: at scoring the scorer re-runs the census matching on
copies of the committed export, one plant per copy: (1) a message no line carries; (2) a duplicate of a message that
matched a line exactly; (3) that message's text edited; (4) a message on the window's last day at 23:59:59
`{{anchor_tz}}` with no line; (5) the line that message matched removed from the pool. a plant is read when the
copy's unledgered count rises above the export's own. plants (2), (3) and (5) need an exact match to copy and are
printed "not built" without one. it prints "k of k read OPEN" over plants built; below k of k the row is
`UNCALIBRATED__the_census_missed_a_planted_miss`, the instrument's failure, placed before the subject's.

---

## 8. the panel: none; who counts

`DPR` §8's two-family panel and its decoys are dropped: no question in this census needs a judgement. a delivered
message matches a line's hash or it does not; numerals are the operator's writer's own counts and are not re-read.
`[lab-set: no panel, why: every gated metric above is a count from bytes]`. one judgement remains, and it is the
lab's, printed with the result: whether `{{anchor_place}}` meets §9 (`--anchor-place-holds` or
`--anchor-place-fails WHY`; without either the result says "not judged in this run").

**who counts.** the scorer (`{{scorer_sha256}}`), run by anyone who holds `{{ledger_url}}`, the posted anchors and
the committed export. the operator exports and signs; the lab reads and runs the scorer at the scoring date and
publishes its output whatever the row. the operator does not run the scorer that reports on their window, and if
they do, the lab's run is the one cited. each run names its runner in RESULT.json (`--runner lab`, `operator` or
`other`; "not stated" without it), and the held sentence of §10 says "counted by" that runner, so an operator's
own run never prints the lab as its counter. **open outside run**: the scorer, this file and the export are public from
close; j outside re-runs reporting the same receipt sha256 are printed, including j = 0 (`DPR` §8's open outside
seat, adapted).

---

## 9. the checks of the ledger itself

- **G-1, the census** (`DPR` §9 G-1, adapted). at or after close the operator exports every destination in
  `{{public_destinations}}` for the window by `{{census_source}}` and commits the export ("how to fill" (b)) with the
  result. the scorer hashes each exported message by `{{agent_account}}` and matches it to delivery lines'
  `{{sent_hash_field}}`, one line per message at most: `exact`, then `normalised` under `{{normalisation_rule}}`, then
  `native` against `{{native_strings}}`; the rest is `[u]`. it prints `missing_from_export` (lines with no message) by
  seq. a public destination is re-exported by the lab at the scoring date when it can be read without the operator,
  and a difference between the two exports is printed message by message.
- **G-2, re-derivation** (new, adapted from `DPR` §9 G-2). both reference implementations (`{{kit_version}}`) verify
  the whole file at close, with the withheld list from `{{withheld_url}}` when not `none` (a withheld list that does
  not answer is printed, and the chain is verified without it); they must agree on the verdict, line count and head;
  a leg that cannot run leaves G_C unmeasured. a v1 file is read under `P1` §4; a v0 file only under each package's v0
  read mode (`KIT`, "darkflobi's own ledger"), and the scorer then applies `{{kinds}}` itself (a v0 header carries no
  kinds), each line of a kind outside it counted into `chain_problems`. a chain that does not re-derive is scored to
  the BROKEN row with its codes and seqs, never refused. `[lab-set: v0 accepted under the v0 read mode, why: the lab's
  two published chains are v0; the scorer reads them with the same code the kit's 10 of 10 v0 vectors pin]`.
- **the header check** (new). `certifies`, `kinds` and `anchor_tz` are read from the header at close and printed
  verbatim; a header digest at close other than `{{header_digest}}` is a new chain and counts into `chain_problems`.
- **the anchor check** (`DPR` §9, adapted to `P1` §5). for each window day with at least one line, the scorer reads
  the posted texts (`{{anchors_url}}`, or the texts the lab collects at `{{anchor_place}}`), parses each anchor text
  (`P1` §5: the whole text is the form), and checks the four conditions; the earliest posted text for a day that holds
  is the day's anchor, later ones are listed as `duplicate` (same head) or `conflict` (another head). it prints `[d]`
  anchored days of `[dl]` days with lines and of 28 `[lab-set: printed, no bar, from DPR §10's "[d] of 28", adapted,
  why: a v1 writer that wrote nothing on a day has no head to post for it, so days with lines is the honest
  denominator]`, `[late]` late marks, `[mm]` mismatched, `lines_after_day_anchor` and `unanchored_deliveries`. the
  ledger's own anchor lines are the writer's statement and anchor no day. a post's time at the anchor place is the
  place's statement; an opentimestamps proof of the anchor text, when published, is read natively (`KIT`) and its block
  printed.
- **the anchor place** `[lab-set: readable without a login, from P1 §5 ("outside the box", "without a login"); and a
  place where the operator cannot edit or delete a post: new, why: DPR §15.9 found darkflobi's telegram supergroup
  readable only in a client, and a page the operator hosts can be rewritten]`. an index at `{{anchors_url}}` the
  operator can edit is the writer's statement and is labelled so in the result. the lab judges the place at the
  scoring date; a place that fails prints every day as unanchored and says why (`--anchor-place-fails WHY`), which
  sends a window with deliveries to the UNANCHORED row.
- **dropped from DPR §9**: G_X's reconciliation over the gateway's own transcripts and the weekly operator hash over
  the box's files. the lab has no access to an outside operator's box, and an operator's hash of their own files is
  their word, not a check (notes).

---

## 10. the printable sentences, as counts under the frozen rule

every bracket is a count from the ledger, the export or the scorer, each with its line; nothing is a rate called
recall. the verdict is the row the block walks to; the paragraph under it is what the lab prints, with §3's
denominators in every case.

**if it holds** — `HELD__every_exported_delivery_has_a_line`:

> between {{d0}} and {{close}} ({{anchor_tz}}), {{agent}}, {{agent_description}}, run by {{operator}}, wrote [L]
> lines to a hash-chained ledger published at {{ledger_url}}, [D] of them deliveries to {{public_destinations}}; the
> chain re-derives under two reference implementations of the styxx ledger protocol to one head ([L_all] lines,
> head [h]), and its heads were posted at {{anchor_place}} on [d] of [dl] days with lines, every day with a delivery
> among them ([late] late, [cf] with a conflicting later anchor listed; the place [judged]), with 0 lines after the
> anchor of their day. an export of those destinations by {{census_source}} held [E] messages by {{agent_account}} in
> the window, of which [ex] matched a line exactly, [no] after {{normalisation_rule}}, and [g] were the platform's own
> strings the registration enumerated, each line matching one message at most: 0 delivered messages with no published
> line, under a rule frozen at {{registration_url}} on {{registration_date}}; the census read [k] of [k] planted
> misses. [m] lines had no exported message ([m] of [D], listed by seq); [w] seqs in the window were withheld by the
> publisher. [where numerals are carried: of [Nn] numerals the operator's writer counted, [Nb] were marked bound and
> [Nu] unbound, the writer's own counts.] this is one operator's ledger counted by [runner] under a frozen rule:
> custody of what was delivered, not that any message is true, and nothing in it is signed.

[runner] is the run's own `--runner`, in words: "the lab", "its operator", "a runner other than the lab and the
operator", or "a runner this run does not name" when none was given; the run that is cited is the lab's (§8).

**if it fails**, under the verdict's own title, counts in every case:

- `BROKEN__chain_does_not_rederive`: "the ledger at {{ledger_url}} did not re-derive at close: [cp] problem records
  ([codes], at seqs [s]); [dis] disagreement between the two implementations; [hd] header change; [ur] unreachable
  (after [t] tries); [kx] lines of a kind outside the registration. the census was not scored against it and no count
  of coverage is printed."
- `DISORDERED__lines_after_their_days_anchor`: "[a] lines sit in the chain after the posted anchor of the day their
  `day` names ([a_d] days, listed); the order the anchors were to show does not hold for those days; the census counts
  are printed and no sentence of coverage is licensed."
- `UNANCHORED__deliveries_on_days_without_a_posted_anchor`: "[U] of [D] delivery lines in the population sit on days
  with no holding posted anchor ([u_d] days, listed; anchor source; the place [judged]); the order those lines were to
  show is not shown, and no sentence of coverage is licensed."
- `UNFALSIFIED__no_census_of_the_destinations`: "the ledger re-derives ([L_all] lines, head [h]) and was anchored on
  [d] of [dl] days with lines, but no export of {{public_destinations}} for the window was committed [or: the lines
  carry no hash of the delivered text; or: the export of {{public_destinations}} for the window named for this run
  did not answer]; the ledger has no evidence it is complete, and the census sentence reads unfalsified, not held."
- `UNCALIBRATED__the_census_missed_a_planted_miss`: "the census instrument read [r] of [k] planted misses (missed:
  [listed]); the row is the instrument's failure, not the subject's, and no count of coverage is printed."
- `OPEN__deliveries_without_a_line`: "[u] of [E] messages {{agent_account}} delivered in the window match no published
  line ([u_w] withheld seqs sit in the window); the writer did not record every delivery and no share of coverage is
  printed. [m] lines had no exported message."
- `ABSTAIN__too_few_deliveries_counts_only`: "[D] deliveries in 28 days, under the {{min_deliveries}} the
  registration set; 0 of [E] exported messages had no line; counts only, and the window is not extended."
- `UNDECIDED__a_gate_the_row_needs_is_unmeasured`: "verdict UNDECIDED: [the gate and why it is unmeasured]; counts
  only."

**the census sentence's own failures**, printed under their titles whatever the row: G-1 — "[u] messages reached a
destination with no published line beyond the [g] enumerated platform strings"; G-2 — "[j] problem records over
[L_all] lines ([codes]); the javascript leg agrees / disagrees / is unmeasured"; the anchor check — "[a] lines sit
after the anchor of their day, [U] population delivery lines sit on days with no holding posted anchor, and [dl − d]
of [dl] days with lines read unanchored ([dup] duplicate, [mm] mismatched, [ms] missing, [late] late) and [cf] days
stand on the earlier of two conflicting anchors"; the instrument check — "[r] of [k] planted misses read ([n] not
built)".

**nothing counted** — `NOT_RUN__window_did_not_open`: "the census registered at {{registration_url}} did not open
([which of (a) to (d) failed, each with its evidence]); {{agent}}'s ledger at {{ledger_url}} was not counted, and no
sentence about its coverage is licensed. its [L] lines are printed as pre-window counts only." `[lab-set: printed in
these words, from DPR §10's "Not run" sentence, adapted]`.

---

## 11. lock hashes

what is frozen with the filled file, each a sha256 of bytes as they stand when it is published. a row reading
`not built at the freeze` names a piece that did not exist; its hash is a dated entry under §15 before `{{d0}}`, and a
row still blank at `{{d0}}` means the window runs without the piece, said so in the result. `[lab-set: the rows, from
DPR §11, cut to what exists off the box]`.

| what | where | sha256 | note |
|---|---|---|---|
| this file above §15 | `{{registration_url}}` | the registration entry under §15 | the bytes before the line that starts `## 15.`, lf, as the registration commit stores them; the scorer recomputes it and refuses on a mismatch |
| the gates block | `#gates` of the filled file | `{{gates_sha256}}` | the bytes between the fences, lf, `{{min_deliveries}}` filled ("how to fill" (h)); the scorer refuses on a mismatch |
| the ledger's header | `{{ledger_url}}` line 1 | `{{header_digest}}` | `P1` §3's header digest; `certifies`, `kinds`, `anchor_tz` verbatim below |
| the writer | `started` entry | `{{writer}}` | the writer's own statement (`P1` §1), not a hash of its code; the scorer compares it with the ledger's started entries before `{{d0}}` and refuses one none of them carries |
| the scorer | THE_PLAN 3d second half: `python/src/styxx_ledger/census.py` | `{{scorer_sha256}}` | moves only by AMENDMENT; the scorer compares it with its own bytes and refuses another; `not built at the freeze` is printed beside the running hash |
| the reference implementations | styxx-ledger | `{{kit_version}}` | the vectors file's sha256 beside the version; the scorer compares it with the vectors file beside it and refuses another (a value naming no sha256 is printed "not compared") |
| the export tool | `{{census_source}}` | `{{census_tool_sha256}}` | `none` when the export is a platform's own download |

the header, verbatim: `certifies` = `{{certifies}}`; `kinds` = `{{kinds}}`; `anchor_tz` = `{{anchor_tz}}`.

never a lock row, by design: the ledger itself (it grows; it is fixed by its chain and its anchors, not by this file),
the anchor posts, the export (committed with the result, after close), the withheld list.

---

## 12. the seal, the anchors, the signature and the order of operations

1. **filled and hashed** by the operator: `styxx-ledger census-digests --prereg <file>` prints the gates digest
   (written into the table) and the assignment walk (here:4). no bar, kind, destination or floor moves after it.
2. **published** at `{{registration_url}}` (a pull request or branch path) by a forge whose server sets the time: the
   freeze anchor. the registration entry (§15, "how to fill" (i)) names the registration commit and the registration
   digest, the sha256 of that commit's bytes above §15 (`DPR` §12's seal rule, from the committed bytes, never the
   working copy). it may sit in the same commit or a later one: §15 is outside the digest.
3. **the signature line for the window**, appended under §15 as a dated entry in the operator's own words, one line,
   in the form of "how to fill" (i). `[lab-set: one operator signature line per window, from THE_PLAN 3d ("one
   operator signature per external window"), why: the window is the operator's act, and a line not signed is a window
   not opened]`. a second window is a new filled file with its own line; a signature never covers two windows.
4. **the shelf reads the ledger**: the chain re-derives and `{{earliest_anchor}}` holds; the shelf read entry names
   the report's url and sha256 and the read's utc time. the earliest external window opens when the outside ledger
   exists and is read by the shelf; before that read, `{{d0}}` cannot fall. the shelf reads v1 ledgers since 2026-11-09
   (styxx-shelf aabe6bf); no outside ledger has been read yet.
5. **D0.** the window cell begins; the operator posts each day's anchor at `{{anchor_place}}` after midnight in
   `{{anchor_tz}}`.
6. **close** at 00:00 `{{close}}`; the last anchor posts; the export is made and committed.
7. **scoring date** (§3): the lab runs the scorer, publishes `RESULT.json` and the sentence of §10 for the row it
   reaches, whatever the row.

**a rehearsal**, any time after the §15 entries exist and before `{{d0}}`: `styxx-ledger census --prereg <file>
--rehearse --ledger <a local copy of the ledger> --now <the scoring date> --out <dir>`, with `--anchors` and
`--export` as local files when there are any. nothing is fetched; the checks of (c) that need the shelf's report
read "not fetched"; RESULT.json says status `rehearsal` and names, under `rehearsal.row_if_report_holds`, the row
the fill would reach if those checks hold. it prints no verdict and one sentence, its own (no G-1, G-2, anchor or
instrument line: those would be counts of a copy bound to nothing), the readme check refuses it, and a fill mistake
(a digest, a lock, a form) is refused in a rehearsal as it would be at scoring.

nothing is scored before the scoring date. an amendment before `{{d0}}` is a dated entry under §15 and never an edit
of the text above it (an edit above §15 breaks the registration digest, and the scorer refuses the file); after
`{{d0}}` a change to any rule, bar or lock is a new AMENDMENT file beside this one, with lines under the old rule
counted under the old rule (`DPR` §12).

---

## 13. the decisions this file assumes, and the alternatives that would change it

| line | default assumed here | the alternative, and what it does to this file |
|---|---|---|
| withheld delivery lines | count into `unledgered_deliveries` (§5) | publish the delivered text's hash in the withheld record: the protocol's withheld record does not carry it (`P1` §6), so this is a protocol change, not a filling choice; open for the lead |
| no destination field | every delivery line in the population; the export covers every place the agent posts | a destination field: lines to other places print as outside |
| normalisation | one of six rules, or `none` | a second rule: not allowed; one rule, frozen, so `normalised` means one thing |
| the javascript leg | required: unmeasured leaves G_C unmeasured and the row UNDECIDED | optional: not offered; the sentence names two implementations |
| the anchor place | judged by the lab at scoring; the ledger's own anchor lines anchor no day | the operator's own page: the writer's statement, every day unanchored |
| v0 chain | read under the kit's v0 read mode, `{{kinds}}` applied by the scorer | v1 only: a v0 chain cannot register |
| numerals | counted only where `{{numerals_field}}` carries them; no bar | a bar on the share: not offered; a bar needs a population a panel labels (§5) |
| operator's commitment | printed, no gate | none |
| the scorer's runner | the lab, named in RESULT.json and in the held sentence (`--runner lab`) | the operator: allowed as a re-run, named `--runner operator`, so its "counted by" says the operator; the lab's run is the one cited (§8) |

---

## 14. what this preregistration does not establish

- nothing about truth: no line is checked for what it says, and no message is checked against anything. `DPR` §14:
  "Nothing here says a post is true, that the agent is honest, or that any other agent would behave the same."
- nothing about honesty, and nothing about other agents: one agent, one operator, one window.
- a chain proves custody, not binding: it fixes bytes and their order once a head is posted; it does not show that a
  line's fields bind to anything outside it. numerals marked bound are the operator's writer's word.
- one operator's count is one hand's: the operator writes the ledger, chooses the destinations, makes the export and
  signs. the lab reads and counts; it does not see the box. "every count is one hand's" (`FRONTIER_2026_11_09.md` §4,
  as `WHAT_IT_AMOUNTS_TO.md` §6.2 item 3 quotes it) holds for each outside window too, until a second operator's
  window is printed beside it.
- that the export is complete: a message the platform's export omits, or a destination left out of
  `{{public_destinations}}`, is outside the census. a census shows what it exported.
- that the writer saw every route: a route that bypasses both the writer and the exported destinations (a direct
  message, another account) leaves no trace in either (`DPR` §14's routes (f) and (i), in kind).
- order finer than a day: the anchors show order at a day's granularity, no finer (`DPR` §14).
- that the anchor posts were made when the place says: the place's timestamp is its own statement; an
  opentimestamps proof shows the text existed before a block, not that it was posted anywhere.
- that the instrument check covers every miss: five plant shapes are read; a miss of another shape is not priced.
- any priority, adoption or replication, and nothing on the lab's must-not-say lists; not that the protocol is
  independent of the lab, which wrote the protocol, the kit, the shelf and the scorer.

---

## 15. amendments before D0, and the signature lines

dated entries only, appended; the text above is never edited, and this section is outside the registration digest.
expected, in this order, each as a `### 15.n — <date>: <what>` heading with its line in the form of "how to fill"
(i): (1) the registration entry, by the operator on the day the file is published; (2) the rows of §11 that read
`not built at the freeze`, by the commit that adds the piece; (3) the shelf read entry; (4) the signature line of §12
step 3, last, before 00:00 `{{d0}}`.
