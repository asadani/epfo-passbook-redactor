# CLAUDE.md

Context for working on this repo. Read [`docs/how-it-was-built.md`](docs/how-it-was-built.md)
for why it is shaped the way it is — several decisions look arbitrary until you know
what they are working around.

## What this is

A CLI that redacts EPFO member passbook PDFs and merges them, one file per employer.
It grew out of a one-off script that processed 20 real passbooks for a background check;
the repo is the generalised version, built so it can be tested and demonstrated with no
real data anywhere near it.

## Hard rules

**1. No real passbook data enters this repo. Ever.**

Not a PDF, not a UAN in a README example, not a real establishment code in a test
fixture, not an employer name in a docstring. This has already been violated once — the
first draft of the README used the author's own UAN, member ID, employer and date of
birth as illustrative examples. If you write documentation examples, take them from
`samples/synthetic/` (regenerate with `epfo-synth --seed 42`).

Enforced by `.gitignore` (blocks `*.pdf` outside `samples/synthetic/**`),
`scripts/check_no_real_pdfs.py` as a pre-commit hook, and the same check in CI. Those
catch PDFs. They do not catch an identifier pasted into prose — that is on you. Sweep
before committing docs:

```bash
python - <<'PY'
import pathlib, pymupdf
secrets = ["<identifiers you are checking for>"]
for f in pathlib.Path(".").rglob("*"):
    if not f.is_file() or any(p in (".git", ".venv", "__pycache__") for p in f.parts):
        continue
    if f.suffix.lower() == ".pdf":
        d = pymupdf.open(f); blob = "".join(p.get_text() for p in d) + str(d.metadata); d.close()
    else:
        blob = f.read_text(encoding="utf-8", errors="ignore")
    for s in secrets:
        if s in blob:
            print("HIT", f, s)
PY
```

**2. Redaction must remove text, not cover it.**

Everything goes through `page.add_redact_annot()` + `page.apply_redactions()`. Never
"redact" by drawing a filled rectangle — the string stays in the content stream and the
document leaks on copy-paste or `pdftotext`. `tests/test_verify.py` has a test that
draws a box the lazy way and asserts the verifier catches it; keep it passing.

**3. EPS stays readable by default.**

`eps-wages` and `eps-pension` are off in the `default` profile and must stay off. This
is the product decision the tool exists to express, not an oversight. EPS wages are
capped at the statutory ceiling and the pension contribution derives from that ceiling,
so neither reveals actual pay — while EPF wages and the 12% employee contribution reveal
it exactly. `tests/test_fields.py::test_default_profile_keeps_every_eps_field_readable`
guards it.

**4. Output filenames must not undo the redaction.**

`merge.py` labels output files with the 5-letter regional prefix only, never the full
establishment code. There is a test for this.

## Architecture

```
inputs → layout.analyse() → redact.redact_page() → merge.group()/write() → verify.verify()
```

| Module | Responsibility |
|---|---|
| `fields.py` | The field registry and profiles. The single source of truth for what is redactable. Adding a field starts here |
| `layout.py` | Reads page structure: column positions, row kinds, header identifier locations. No mutation |
| `redact.py` | Turns a layout into rectangles, applies them, returns a `PageReport` |
| `merge.py` | Grouping, financial-year ordering, merging, metadata scrub |
| `verify.py` | Three independent leak checks. Runs on every write |
| `config.py` | YAML config. Precedence: field defaults → profile → config → CLI flags |
| `synth/generate.py` | Synthetic passbooks. Draws at the real template's geometry |

`PageReport` is the contract between `redact.py` and `verify.py`. If you add something
redactable, make sure its literal or its column edge ends up in the report, or the
verifier will not check it.

## Gotchas

These are all things that already cost time once.

- **The bracketed year.** `Total Contributions for the year [ 2021 ]` puts a bare year
  inside the EPS-wages column band. It is a row label, not a cell. `layout._bracketed()`
  excludes it. Without that, enabling `eps-wages` silently redacts the year.
- **Deflated content streams.** Searching a PDF's raw bytes for a leaked string finds
  nothing, because streams are compressed. `verify._in_content_streams()` decompresses
  first and searches both ASCII (`(ABC123)`, how iText writes it) and hex
  (`<414243…>`, how MuPDF writes it). A raw-file search alone is security theatre.
- **`--keep-rows` vs. the column scan.** A row the user deliberately spared looks
  identical to a row the planner missed. `PageReport.exempt_bands` carries the spared
  y-bands so the verifier does not report them.
- **Windows console encoding.** `click.echo()` of a non-ASCII character raises
  `UnicodeEncodeError` on a cp1252 console. Keep CLI output ASCII. (Markdown files are
  fine — this is about terminal output only.)
- **Balance and contribution columns share a right edge.** One detected band covers
  both, which is why `epf-employee` redacts the employee contribution *and* the employee
  balance. Intentional.
- **Prefix splitting is per character.** `layout.tail_rect()` uses individual glyph
  boxes, not a proportional guess, so the kept prefix is never clipped in a proportional
  font. There is a fallback path when character data is missing that errs toward
  over-redacting; keep that direction.

## Column detection

Columns are found from the printed English header labels (`EPF`, `EPS`, `Employee`,
`Employer`, `Pension`), by clustering right-aligned numeric cells and matching each
cluster to the label whose x-range it falls in. `FALLBACK_COLUMNS` in `layout.py` holds
the geometry of the 2026-era template and is used only when detection fails outright —
a run that falls back prints `[fallback geometry]`.

Do not "simplify" this back to fixed coordinates. The fixed version only worked on the
two directories it was written against.

## Working on it

```bash
pip install -e ".[dev]"
pytest -q                  # ~10s, 81 tests
black . && flake8          # line length 88, extend-ignore E203,W503
epfo-synth --seed 42       # regenerate samples/synthetic
```

House style follows the sibling `git-branch-cleaner` repo: setuptools, click,
`[project.scripts]`, black 88, flake8, pre-commit, CI matrix on 3.10–3.12.

Tests build their own synthetic passbooks in `tmp_path` via the `synth_dir` fixture. No
test reads a committed file, so a test can never accidentally depend on real data.

### If you have real passbooks to test against

Run the tool from wherever they live, write output to a temp directory outside the repo,
and delete it afterwards. Never `cd` into the repo with them, and never set `-o` to a
path inside it.

## Not done yet

- Not pushed to GitHub. `gh repo create asadani/epfo-passbook-redactor --public --source=. --push`
- Multi-page passbooks are handled per page, but every real sample seen so far was a
  single page per financial year. A genuinely multi-page year is untested.
- Scanned or image-only passbooks are out of scope and are now refused outright, as is
  any PDF that produces zero redactions — both would otherwise write a file that looks
  processed and is not. There is no OCR path and probably should not be one: redacting
  a raster means burning boxes into pixels, which is a different tool.
- The verifier's content-stream check is a substring search, so a string split across
  kerned pieces would evade it. The text-extraction check covers that case, but the
  two are not independent for that specific failure.
- No `--version` flag on the CLI.
