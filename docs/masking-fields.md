# Fields reference

Every redactable element, what it does, and why the default is what it is.
`epfo-redact --list-fields` prints the same list from the installed version.

The examples below use the committed sample in `samples/input/`, which you can
regenerate with `epfo-synth --seed 42`; `samples/output/` holds what the tool makes of
it. Like everything else in this repo, the values are invented.

## Identity fields

Located by their header labels, so they are found wherever the template puts them.
Identifiers that repeat elsewhere on the page — the member ID is reprinted in the footer
of every page — are matched by value, so every occurrence is covered.

| Field | Default | Keeps | Example |
|---|---|---|---|
| `establishment-id` | **on** | first 5 | `BACGH9703905715` → `BACGH██████████` |
| `employer-name` | **on** | legal-form suffix | `CHAHAL PRIVATE LIMITED` → `██████ PRIVATE LIMITED` |
| `member-id` | **on** | first 5 | `BACGH97039057153335943` → `BACGH█████████████████` |
| `uan` | **on** | first 4 | `115631219101` → `1156████████` |
| `member-name` | off | — | `ARYAN MAHARAJ` → `█████████████` |
| `dob` | off | — | `31-12-1978` → `██████████` |

The retained prefix is computed from per-character boxes, so the split lands exactly on
a glyph boundary even in a proportional font — the kept prefix is never clipped and no
fragment of the redacted part survives. Change any of them with
`--keep-chars FIELD=N`; `0` redacts the whole value.

**Why name and DOB are off.** A verifier usually needs them to tie the passbook to you;
a document that proves *someone* was employed proves nothing. Turn them on with
`--mask member-name --mask dob`, or use `--profile strict`.

**The 5-letter prefixes are kept on purpose.** The first five letters are the EPFO regional
office codes, so keeping them shows the account is real and regionally plausible without
identifying the employer. If that is more than you want to disclose, use
`--keep-chars establishment-id=0 --keep-chars member-id=0`. Note that the prefix also
appears in the output filename.

## Financial fields

Whole table columns, named after the header labels EPFO prints. Each covers both the
contribution rows and the balance rows, because those share a column.

| Field | Default | Column |
|---|---|---|
| `epf-wages` | **on** | Wages → EPF — your actual monthly salary |
| `epf-employee` | **on** | Contribution → Employee, and Employee Balance |
| `epf-employer` | **on** | Contribution → Employer, and Employer Balance |
| `eps-wages` | off | Wages → EPS |
| `eps-pension` | off | Contribution → Pension, and Pension Balance |

A redacted column clears every row: opening balance, each month, the three yearly totals,
the interest row and the closing balance.

### Why EPS stays readable

EPS wages are capped at the statutory ceiling (₹15,000 since 2014) and the pension
contribution is 8.33% of that ceiling, capped at ₹1,250. Neither moves with your actual
salary, so publishing them reveals nothing about pay — while EPF wages reveal it exactly,
and the EPF employee contribution is 12% of it, which reveals it just as exactly. That is
why `epf-wages` and `epf-employee` are both on: masking one and not the other would leak
the salary through arithmetic.

Keeping the EPS columns leaves the document useful. The pension corpus and its growth
still demonstrate continuous employment and continuous contributions, which is what a
verifier is checking.

## Row kinds

`--keep-rows` exempts named rows from column redaction.

| Kind | Row |
|---|---|
| `opening` | `OB Int. Updated upto DD/MM/YYYY` |
| `contributions` | `Total Contributions for the year [ YYYY ]` |
| `transfers` | `Total Transfer-Ins/VDRs for the year [ YYYY ]` |
| `withdrawals` | `Total Withdrawals for the year [ YYYY ]` |
| `interest` | `Int. Updated upto DD/MM/YYYY` |
| `closing` | `Closing Balance as on DD/MM/YYYY` |

Withdrawals is the one worth thinking about. It usually reads `0`, and a zero withdrawal
is favourable evidence — it shows the corpus was never dipped into. It is redacted by
default only because it sits in the EPF columns. `--keep-rows withdrawals` keeps it.

## Styles

| Style | Appearance |
|---|---|
| `black` | Solid black. Default for identity fields |
| `grey` | Solid grey. Default for the table, so it still reads as a table |
| `white` | White with a thin border — a visible gap |
| `hatch` | Light grey with diagonal lines |

Set globally with `--style`, or per field or kind with `--field-style`:

```bash
epfo-redact AZJHH/ --style hatch --field-style member-id=black
epfo-redact AZJHH/ --field-style financial=white
```

Precedence: per-field → per-kind (`identity` / `financial`) → global → built-in default.
The style is cosmetic. The text is removed either way.

## Profiles

| Profile | Fields |
|---|---|
| `default` | `establishment-id`, `employer-name`, `member-id`, `uan`, `epf-wages`, `epf-employee`, `epf-employer` |
| `strict` | All eleven |
| `identity` | The four identity fields that are on by default |
| `financial` | The three EPF columns |
| `none` | Nothing — build a set up with `--mask` |

Composable: `--profile identity --mask epf-wages` redacts the header plus the wage
column and nothing else.
