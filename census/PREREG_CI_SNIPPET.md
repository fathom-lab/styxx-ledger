> change log — 2026-11-09 06:30Z (the lead): the shelf has the v1 row shape since styxx-shelf aabe6bf (`shelf_read.cjs`,
> `docs/outside_ledgers.json`, `docs/reports/`), and `census.SHELF_HAS_V1_ROW` is set True in the kit. the register holds
> v1 rows 0 of 2 (both rows are the lab's own). sentences below that said "the shelf has no v1 row" now read "no
> outside ledger has been published"; the condition (c) check is the scorer's, against the shelf's report.

# PREREG_CI_SNIPPET — the census as a ci job in an outside operator's own repository

THE_PLAN item 3d, the second half. a github actions job an outside operator pastes into **their own** repository,
under their own `.github/workflows/`. nothing here is a workflow file in the styxx-ledger kit, and the kit carries
none for this. written 2026-11-09 by fathom lab; revised the same day after the lab's adversarial review
(`REVIEW_3d.md` M4, M8, S8).

**what this snippet does not lower.** the sentence "the barrier to being checked is one file" is held, not said: as
built, a stranger also needs a shelf read of their ledger (the shelf has the v1 row shape since 2026-11-09; the read
and the register row are the lab's acts), a kit commit carrying the scorer (fa0c78c and later), and the lab's run as
the one cited (template §8). the sentence the lab may carry is "one file plus a shelf row", for as long as the row
stays a lab act. the export schema and the digests are now in the
template ("how to fill" (b), (h)) and in the kit (`styxx-ledger census-digests`).

what the job does, in order:

1. checks out the operator's repository (their filled `PREREG_census.md` and `README.md`).
2. checks out the styxx-ledger kit from its public git url, pinned to one commit, and installs its python package
   editable (`pip install -e`), so the scorer finds the kit's javascript cli beside it and the chain is re-derived
   by both reference implementations (`node` is on github's ubuntu runners).
3. runs `styxx-ledger census` with their prereg; the scorer reads the ledger url from the prereg's `ledger_url`
   (no second copy of the url in the job), scores only the bytes at that url, and writes `census_out/RESULT.json` and
   `census_out/RESULT.md`.
4. runs `census/census_check_readme.py` from the same kit checkout: fails the job when RESULT.json's status is
   `refused`, or when a README sentence that quotes a RESULT number does not match RESULT.json.
5. uploads `census_out/` as an artifact, pass or fail, so the receipt survives the run.

what the job does not do: it does not open a window, sign anything, export the destinations, or post anchors. a
green job means the scorer ran, did not refuse, and the README's quoted numbers equal the receipt; it says nothing
about which verdict row the census reached, and nothing about whether any message is true. the lab's own run at the
scoring date is the one cited (template §8); the operator's ci is a re-run.

## the job

replace the two values marked `<...>` before pasting. `KIT_COMMIT` must be a commit of
`github.com/fathom-lab/styxx-ledger` that carries `python/src/styxx_ledger/census.py` and
`census/census_check_readme.py` (as of 2026-11-09 these are in the lab's working tree, not yet committed: the lead
commits them; until then there is no commit to pin and this job cannot run).

```yaml
name: census
on:
  push:
    paths: ["PREREG_census.md", "README.md"]
  schedule:
    - cron: "17 6 * * *"        # daily, after the operator's anchor for the day before has posted
  workflow_dispatch: {}

permissions:
  contents: read

jobs:
  census:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      KIT_COMMIT: <40-hex commit of fathom-lab/styxx-ledger carrying the census scorer>
      PREREG: <path of your filled prereg in this repository, e.g. PREREG_census.md>
      PYTHONDONTWRITEBYTECODE: "1"
    steps:
      - name: check out this repository
        uses: actions/checkout@v4

      - name: check out the styxx-ledger kit, pinned
        uses: actions/checkout@v4
        with:
          repository: fathom-lab/styxx-ledger
          ref: ${{ env.KIT_COMMIT }}
          path: styxx-ledger-kit

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: install the kit (editable, so the js reference implementation sits beside the scorer)
        run: python -m pip install -e ./styxx-ledger-kit/python

      - name: run the census
        run: |
          styxx-ledger census --prereg "$PREREG" --out census_out --tries 1 || true
          test -f census_out/RESULT.json

      - name: refuse a refused census, and a readme that misquotes it
        run: python -I -B styxx-ledger-kit/census/census_check_readme.py census_out/RESULT.json README.md --require 1

      - name: keep the receipt
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: census-result
          path: census_out/
```

notes on the job:

- `|| true` on the census step is deliberate: the scorer exits 1 on a refusal **after** writing RESULT.json, and the
  next step is the one that fails the job on it, with the reason printed. a missing RESULT.json (exit 2: a usage or
  i/o error) fails at `test -f`.
- `--now` is left to the scorer's default (the runner's utc clock), so a run before the scoring date reads
  `in_progress` or `nothing_counted`, never a verdict. until the shelf has read the outside ledger every run reads
  `nothing_counted`. pin `--now 2026-11-09T05:00:00Z` (any utc time) to reproduce
  a past run byte for byte.
- no `--export` is passed: the export ("how to fill" (b)) is committed with the result at close (template §9 G-1).
  once committed, add `--export path/to/export.json` to the census step; without it `census_run` is 0 and the row the
  scorer walks to is `UNFALSIFIED__no_census_of_the_destinations` at best. posted anchor texts go in with
  `--anchors path/to/anchors.json` when `anchors_url` is `none`; without posted texts every day reads unanchored.
- the javascript leg: with the editable install and node present, RESULT.json's `js_leg.status` is `measured` and
  `chain_problem_components.implementations_disagree` is 0 or 1. a plain `pip install
  "git+https://github.com/fathom-lab/styxx-ledger.git@<commit>#subdirectory=python"` also works, but the js cli is
  then not beside the package and the leg reads `unmeasured`: G_C is then unmeasured and a run at the scoring date
  reads `UNDECIDED__a_gate_the_row_needs_is_unmeasured`, never agreement.
- network: the scorer fetches `ledger_url`, `withheld_url` and `anchors_url` when the prereg names them (30 s per
  try). the template's rule is three tries an hour apart (the lab's run at the scoring date uses it); a ci re-run
  passes `--tries 1` so a job does not sleep for two hours, and RESULT.json records the tries allowed and used. a
  ledger url that does not answer is the `unreachable` component of `chain_problems`, not a refusal; an anchors url
  that does not answer reads every day unanchored.
- `--ledger` is left out on purpose: a url other than `ledger_url` is refused, and a local copy is scored only when
  its sha256 equals the url's bytes fetched in the same run.
- readme markers: put markers on `status` only while the window runs (`nothing_counted` before d0, `in_progress`
  from d0 to the scoring date); every `in_progress` count moves daily, so a marker on one goes red on the next
  scheduled run. from the scoring date on, mark `verdict` and the gated metrics under `result.`
  (`result.window_opened`, `result.chain_problems`, `result.lines_after_day_anchor`, `result.unanchored_deliveries`,
  `result.census_run`, `result.instrument_plants_missed`, `result.unledgered_deliveries`, `result.n_deliveries`),
  which no longer move. a status marker still needs one readme edit at each transition (three in a window).

## the readme check (`census/census_check_readme.py`)

a sentence in the operator's README that quotes a number from RESULT.json carries a marker naming the receipt path,
in the same sentence, in either form:

    the census counted 0 unledgered deliveries (census: result.unledgered_deliveries = 0).
    4 deliveries reached the public channel <!-- census: result.n_deliveries = 4 -->.
    the window read HELD (census: verdict = HELD__every_exported_delivery_has_a_line).

the path is dotted into RESULT.json; integers index lists (`anchors.window.missing_days.0`). the value is json (`0`,
`null`, `"2026-10-03"`) or a bare word compared with the string at that path. the check fails when:

1. RESULT.json's `status` is `refused` (the reason is printed);
2. a marker's path is not in RESULT.json;
3. RESULT.json's value at the path is not the marker's value (type included: `"4"` is not `4`);
4. a numeric marker's sentence (from the previous `. ` `! ` `? ` or the line start, up to the marker) does not say the
   number as a standalone numeral: `14 deliveries (census: result.n_deliveries = 4)` fails, so the prose cannot
   drift from its marker;
5. fewer than `--require` markers exist (default 1), so a README with no marker does not pass by saying nothing.

exit 0 every check passed, 1 any failed, 2 usage or i/o. what it does not catch: a number in the README with no
marker at all. a census number written without its receipt path is the operator's sentence, not the census's, and
the check cannot tell it from any other numeral; the house rule it serves is "every number names its receipt".

its tests: `census/test_census_check_readme.py`, 8 of 8 passing on this box (windows 11, python 3.12.10,
2026-11-09), run with `python -I -B -m pytest -q -p no:cacheprovider census/test_census_check_readme.py` from the kit
root. ubuntu is not claimed here.

## the filled prereg's form, as the scorer reads it

the template's "how to fill" section is the reference: (a) the table row form (the name, ` = `, and the value between backticks in the left cell), (b) the
export schema, (c) the six normalisation rules, (d) native strings as a json list, (e) the anchors index forms, (f) a
keyed-hash destination in an export, (g) the public destinations list, (h) the gates and registration digests
(`styxx-ledger census-digests --prereg PREREG_census.md` prints both and walks the gates block's 256 assignments),
(i) the three entries under §15. any double-brace placeholder left anywhere is a refusal; with `d0` filled, an open
value, an unknown normalisation rule, a non-json native list, bytes above §15 that do not hash to the registration
entry, or a gates block that does not hash to `gates_sha256` is a refusal. `tests/make_census_fixture.py --template
PREREG_census_TEMPLATE.md` in the kit shows the fill and the seal mechanically on a synthetic ledger.
