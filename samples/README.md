# Samples

Everything here is generated. No real passbook, no real person, no real
employer, no real establishment code. Regenerate the whole tree with:

```bash
epfo-synth --seed 42                                  # writes samples/input
epfo-redact samples/input -o samples/output           # writes samples/output
```

Every page is stamped `SYNTHETIC SAMPLE - NOT A REAL EPFO DOCUMENT` under the
banner. The pre-commit hook refuses to commit a PDF that is missing that
stamp, so a real passbook cannot reach either directory by accident.

## `input/` -- what you would have downloaded

```
input/
  EPFO_Passbook_AZJHH_FY2015-2017.pdf    one employer, one financial year per page
  EPFO_Passbook_BACGH_FY2018-2021.pdf
  AZJHH/                                 the same account, one file per year
    AZJHH33423314449906821_2015.pdf
    ...
  BACGH/
    ...
```

Both shapes turn up in practice. Asking the member portal for a whole account
gives you a single multi-page PDF with a financial year on each page; pulling
one year at a time gives you a file per year, usually already sorted into a
folder per employer. The redactor takes either:

```bash
epfo-redact samples/input             # the two multi-page PDFs
epfo-redact samples/input/AZJHH       # the per-year files for one employer
```

Pointing it at a directory that has PDFs directly inside it uses those and
ignores the subdirectories, which is why the first command does not process
each account twice.

## `output/` -- what the tool produces

One PDF per employer, pages in financial-year order, named with the 5-letter
regional prefix only. The full establishment code stays out of the filename so
the name cannot undo the redaction inside the document.

Under the `default` profile, what is gone and what remains:

| Gone | Left readable |
|---|---|
| UAN, member ID, establishment ID (first 5 characters kept) | Every EPS column: EPS wages, pension contribution, pension balance |
| Member name, employer name | Wage months, transaction dates, row labels |
| EPF wages, employee and employer contributions, and their balances | Financial year, interest rows, the closing pension balance |

EPS stays readable on purpose. EPS wages are capped at the statutory ceiling
and the pension contribution derives from that ceiling, so neither reveals
actual pay -- while EPF wages and the 12% employee contribution reveal it
exactly. That is the whole product decision the tool exists to express; see
[`docs/masking-fields.md`](../docs/masking-fields.md) for how to change it.

## About the letterhead

The EPFO banner across the top is the real one, lifted from a real passbook so
the samples are recognisable at a glance. It is the organisation's letterhead,
not anyone's data. The `SYNTHETIC SAMPLE` stamp sits directly under it for the
same reason -- these pages should never be mistaken for a genuine statement.

The Hindi half of each label is real Unicode Devanagari and needs a Devanagari
font installed (Nirmala UI on Windows, Noto Sans Devanagari or Lohit on Linux).
Without one the generator writes the English labels alone. The real document
sets its Hindi in a legacy Kruti Dev encoding, which extracts as Latin
gibberish; reproducing that would have looked right and read wrong.
