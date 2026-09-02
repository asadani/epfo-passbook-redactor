# How this was built

A record of the decisions behind the code, written so someone picking it up later —
including a future me — does not have to rediscover why it is shaped this way. Several
choices look arbitrary until you know what they are working around.

Nothing in this document names a real employer, account or person. The passbooks that
started it are not in this repo and never will be.

## The original problem

A bank's pre-onboarding background check asked for EPF passbooks. What was available was
20 PDFs across two employers, one per financial year, spanning FY2009 to FY2026, sitting
in two folders. Two things needed to happen: merge them into one PDF per employer, and
remove the sensitive parts first.

The requirement that shaped everything: **mask the PF corpus, PF salary and PF
contributions, but do not mask the Employee Pension Scheme details.**

That distinction is the whole product. It is worth understanding before changing
anything:

- EPF wages are your actual monthly salary, printed twelve times a year for your whole
  career. The EPF employee contribution is 12% of it, so redacting the wage but not the
  contribution would leak the salary through arithmetic. Both go.
- EPS wages are capped at the statutory ceiling (₹15,000 since 2014) and the pension
  contribution is 8.33% of that ceiling, capped at ₹1,250. Neither moves with actual
  pay. Publishing them reveals nothing, and keeping them leaves the document useful —
  the pension corpus and its growth still demonstrate continuous employment, which is
  what a verifier is actually checking.

## Phase 1 — reading the documents

Before writing anything, the source PDFs were characterised:

- 20 files, all single-page A4 (595×842pt), one page per financial year.
- Fonts: Helvetica, Calibri, Times-Roman, and **KrutiDev010** — a legacy non-Unicode
  font used for the Hindi labels. This is why the tool keys entirely off the English
  labels, and why the synthetic generator does not attempt Hindi.
- Producer: `iText 5.1.0`. Relevant later: iText writes strings into the content stream
  as ASCII literals, where MuPDF writes hex. The verifier has to handle both.
- Metadata was benign (`title: EPF Member Passbook`, `author: EPFO`) but is scrubbed on
  output anyway.

Word-level coordinates were dumped for every file and the table geometry turned out to
be **identical across all 20**, with these right edges (the table is right-aligned):

| x | Column | Cells |
|---|---|---|
| 338.5 | Wages → EPF | 191 |
| 395.9 | Wages → EPS | 191 |
| 453.3 | Employee (contribution + balance) | 311 |
| 510.6 | Employer (contribution + balance) | 311 |
| 568.0 | Pension (contribution + balance) | 311 |

Balance and contribution columns sharing a right edge is why one detected band covers
both to this day.

## Phase 2 — the one-off script

A single script hardcoded those five x-values, matched the header identifiers by regex,
and used PyMuPDF redaction annotations. It produced the two merged PDFs and verified
them. That worked, and the output was checked by rendering pages to PNG and reading
them, not just by asserting on text.

**Why PyMuPDF and not a drawn box.** Covering a value with a filled rectangle leaves the
original string in the content stream, where copy-paste, `pdftotext` or a text search
finds it. That is the standard way "redacted" documents leak. `add_redact_annot()` +
`apply_redactions()` removes the glyphs before the file is written.

**Why per-character rectangles.** Keeping a prefix (`ABCDE` of a 15-character code)
means splitting a word mid-token. Estimating the split point proportionally is wrong in
a proportional font — it either clips the kept prefix or leaves a sliver of the redacted
part. `layout.tail_rect()` uses individual glyph boxes so the boundary lands exactly
between characters.

## Phase 3 — generalising into this repo

The script was disposable: coordinates tied to two folders, mask set baked in, no way to
run it on anyone else's passbook. The repo generalises it, with three significant
changes.

### Columns are detected, not hardcoded

Instead of the five constants, the tool now finds the printed header labels (`EPF`,
`EPS`, `Employee`, `Employer`, `Pension`), clusters numeric cells by right edge, and
matches each cluster to the label whose x-range contains it. Validated against all 20
real files before adopting it.

This matters for two reasons: it works on a passbook from a different template revision,
and it means the synthetic generator can be a genuine test surface rather than a
circular one.

`FALLBACK_COLUMNS` keeps the measured 2026 geometry for when detection fails outright,
and such a run prints `[fallback geometry]`.

**The trap found while validating it.** The rows reading
`Total Contributions for the year [ 2021 ]` place a bare year at x≈391.1 — inside the
EPS-wages band at 395.9. It is a row label, not a cell. Left alone, anyone enabling
`eps-wages` would silently redact the year out of their own statement.
`layout._bracketed()` excludes tokens between `[` and `]`.

### Synthetic data, because the repo cannot hold the real thing

`epfo-synth` generates passbooks with Faker names, random 5-letter establishment codes,
and money simulated from the statutory rules: 12% EPF employee, 8.33% EPS capped at
₹1,250, employer share as the difference, interest credited at year end, balances
carried across years, partial joining and leaving years. Pages are drawn at the real
template's geometry so the redactor sees the structure it would see on a real document.

The first version stopped at geometry and drew English labels in Helvetica, which was
enough for the redactor and not enough for a human — the samples did not read as
passbooks, which made them useless for showing anyone what the tool does. The second
version copies the letterhead, the bilingual Hindi/English column headings, the red
`Total Withdrawals` row and the disclaimer block, all measured off a real page. Two
things bit on the way:

- **The footer block is not at a fixed height.** It hangs off the bottom of the table,
  which moves by 90pt between a two-month year and a twelve-month one. Fixed
  coordinates put the disclaimer through the middle of a full year's rows.
- **Calibri embedded as a CID font lies about its own text.** MuPDF derives the
  ToUnicode map by walking the face's cmap backwards, and Calibri maps both `U+0020`
  and `U+00A0` to one space glyph, both `U+002D` and `U+2010` to one hyphen. Extracted
  text came back as `Establishment ID/Name` and `Financial Year ‐ 2015`, and
  the redactor — which splits words on real spaces — could not find a single label.
  Embedding the Latin faces as simple single-byte fonts (`set_simple=True`) fixes the
  round-trip. Devanagari still needs the multi-byte encoding, but nothing keys off the
  Hindi. `tests/test_synth.py` pins this.

Deterministic under `--seed`, so `samples/` is reproducible and tests are stable. That
claim was false for a while and nothing noticed: the member's date of birth came from
Faker's `date_of_birth`, which counts back from *today*, so a seed meant one person on
Tuesday and another on Wednesday. It surfaced as the committed samples showing a diff
whenever they were regenerated on a new date. Ages are now measured back from a fixed
reference date, and `tests/test_synth.py` pins the result to literals -- the only kind
of test that can catch it, since two runs in one process always share a today.

Every test fixture builds its own set in `tmp_path`; no test reads a committed file, so
no test can accidentally come to depend on real data.

### Configurability

Eleven fields, five profiles, per-field flags, four styles, a YAML config, and
`--keep-rows`. `--keep-rows` exists because of a specific observation: `Total
Withdrawals` reads `0` and a zero withdrawal is *favourable* evidence — it shows the
corpus was never touched. It is redacted by default only because it sits in the EPF
columns. Now it can be spared.

## How correctness was established

Four independent things, in increasing order of how much they would have caught:

1. **Unit and integration tests** — 83 of them, all on synthetic data.
2. **Visual checks** — pages rendered to PNG and actually looked at, before and after,
   for both the real and synthetic documents. Several layout details were only visible
   this way.
3. **Adversarial tests** — the verifier is handed deliberately broken output (a value
   covered with a box rather than removed; a column reported as redacted but untouched;
   a wrong page count) and must complain. A verifier that only ever passes is worse than
   none.
4. **Regression against the real documents** — the rewritten, label-driven pipeline was
   run over the original 20 files and its extracted text compared page-for-page against
   the output the one-off script had already produced. Identical. That is what made it
   safe to throw the script away. Output went to a temp directory outside the repo and
   was deleted.

## Bugs found during verification

Recorded because two of them were in code that looked correct and passed its own tests.

**1. The byte-level leak check could never have worked.** It searched the raw file bytes
for each redacted literal. PDF content streams are deflate-compressed, so the string is
not there in plaintext whether or not it leaked. The check passed on every input,
including inputs that leaked. It now decompresses the content streams and searches both
ASCII (`(ABC123)`) and hex (`<414243…>`), because iText and MuPDF write strings
differently. This was caught only by writing a test that deliberately leaked.

**2. `--keep-rows` produced false leak reports.** The column scan finds numeric cells
remaining in a redacted column. A row the user deliberately spared looks exactly like a
row the planner missed. `PageReport.exempt_bands` now carries the spared y-bands.

**3. `--list-fields` crashed on Windows.** A `✓` in `click.echo()` output raises
`UnicodeEncodeError` against a cp1252 console. CLI output is ASCII now.

## A mistake worth recording

The first draft of the README and the field reference used the author's own UAN, member
ID, establishment code, employer name, date of birth and full name as illustrative
examples — while the same README declared that no real data enters this repo.

It was caught by a scripted sweep run before the first commit, not by reading. Nothing
reached git history. All examples now come from the committed synthetic sample, which is
better anyway: a reader can reproduce them with `epfo-synth --seed 42`.

The lesson is in `CLAUDE.md` as a hard rule: the automated guards catch PDFs, and only
PDFs. An identifier pasted into prose needs a deliberate sweep.

## Things deliberately not done

- **The 5-letter prefixes are kept.** They are EPFO regional office codes. Keeping them
  shows the account is real and regionally plausible without identifying the employer.
  `--keep-chars establishment-id=0` removes them if that is not wanted. Note the prefix
  also appears in the output filename by design — the *full* code never does.
- **Name and date of birth stay readable by default.** A document proving *someone* was
  employed proves nothing. `--profile strict` redacts them.
- **No OCR.** Scanned passbooks are refused rather than handled. Redacting a raster
  means burning boxes into pixels, which is a different tool with different failure
  modes.
- **No Hindi in the synthetic generator.** The real document renders it through a legacy
  non-Unicode font. Reproducing that adds font-embedding complexity and tests nothing,
  since detection is entirely English-driven.
