"""Command line interface for epfo-redact."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import config as config_mod
from .fields import BY_NAME, FIELDS, PROFILES, ROW_KINDS, FieldError, resolve
from .merge import Source, group, write
from .redact import STYLES, StyleError, redact_document
from .verify import verify

DEFAULT_OUT = Path("redacted")


def _expand(inputs: tuple[str, ...]) -> list[Path]:
    """Turn files, directories and globs into a sorted list of PDFs."""
    found: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            # Point at the download folder or at one employer's folder; both work.
            direct = sorted(path.glob("*.pdf"))
            found.extend(direct or sorted(path.glob("**/*.pdf")))
        elif path.is_file():
            found.append(path)
        else:
            matches = sorted(Path().glob(item))
            if not matches:
                raise click.BadParameter(f"no such file or directory: {item}")
            found.extend(m for m in matches if m.suffix.lower() == ".pdf")
    if not found:
        raise click.BadParameter("no PDF files found in the given inputs")
    return found


def _parse_pairs(values: tuple[str, ...], what: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise click.BadParameter(f"{what} expects FIELD=VALUE, got {value!r}")
        key, _, val = value.partition("=")
        out[key.strip()] = val.strip()
    return out


def _print_fields() -> None:
    # Plain ASCII throughout: a Windows console defaults to cp1252 and raises
    # UnicodeEncodeError on a tick.
    click.echo("Fields ([x] = on in the default profile):\n")
    width = max(len(f.name) for f in FIELDS)
    for f in FIELDS:
        tick = "[x]" if f.default_on else "[ ]"
        click.echo(f"  {tick} {f.name:<{width}}  {f.description}")
    click.echo("\nProfiles:\n")
    for name, members in PROFILES.items():
        listed = ", ".join(sorted(members)) if members else "(nothing)"
        click.echo(f"  {name:<10} {listed}")
    click.echo("\nRow kinds for --keep-rows:\n")
    click.echo(f"  {', '.join(sorted(ROW_KINDS))}")
    click.echo(f"\nStyles: {', '.join(sorted(STYLES))}")


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("inputs", nargs=-1)
@click.option(
    "-o",
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    help=f"Output directory (default: ./{DEFAULT_OUT}).",
)
@click.option(
    "--profile",
    type=click.Choice(sorted(PROFILES), case_sensitive=False),
    help="Starting set of fields (default: default).",
)
@click.option("--mask", multiple=True, help="Add a field. Repeatable.")
@click.option("--no-mask", multiple=True, help="Remove a field. Repeatable.")
@click.option(
    "--keep-chars",
    multiple=True,
    metavar="FIELD=N",
    help="Characters to leave readable at the start of a field.",
)
@click.option(
    "--keep-rows",
    default="",
    help=f"Rows to leave readable inside redacted columns: "
    f"{', '.join(sorted(ROW_KINDS))}.",
)
@click.option(
    "--style",
    type=click.Choice(sorted(STYLES), case_sensitive=False),
    help="Style for every redaction (default: black header, grey table).",
)
@click.option(
    "--field-style",
    multiple=True,
    metavar="FIELD=STYLE",
    help="Style for one field or kind (identity, financial).",
)
@click.option(
    "--group-by",
    type=click.Choice(["establishment", "dir", "none"]),
    help="How to bucket inputs into output PDFs (default: establishment).",
)
@click.option(
    "--merge/--no-merge", default=None, help="Merge each group (default: on)."
)
@click.option(
    "--config",
    "config_path",
    help=f"YAML config (default: ./{config_mod.DEFAULT_FILENAME}).",
)
@click.option(
    "--dry-run", is_flag=True, help="Report what would change; write nothing."
)
@click.option(
    "--fail-on-leak/--no-fail-on-leak",
    default=True,
    help="Exit non-zero if verification finds a leak (default: on).",
)
@click.option("--list-fields", is_flag=True, help="Show fields, profiles and styles.")
@click.option("-q", "--quiet", is_flag=True, help="Only print warnings and errors.")
def main(
    inputs,
    out,
    profile,
    mask,
    no_mask,
    keep_chars,
    keep_rows,
    style,
    field_style,
    group_by,
    merge,
    config_path,
    dry_run,
    fail_on_leak,
    list_fields,
    quiet,
):
    """Redact EPFO member passbook PDFs and merge them, one file per employer.

    By default this removes the establishment code, employer name, member ID and
    UAN tail from the header, and the EPF wage, contribution and balance columns
    from the table -- while leaving every Employee Pension Scheme figure
    readable.

    \b
    Examples:
      epfo-redact AZJHH/ BACGH/ -o out/
      epfo-redact passbooks/*.pdf --profile strict
      epfo-redact AZJHH/ --no-mask epf-wages --keep-rows withdrawals
      epfo-redact AZJHH/ --dry-run
    """
    if list_fields:
        _print_fields()
        return

    if not inputs:
        raise click.UsageError("give at least one PDF, directory or glob to redact.")

    try:
        cfg_path = config_mod.discover(config_path)
        cfg = config_mod.load(cfg_path) if cfg_path else config_mod.Config()
    except config_mod.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if cfg_path and not quiet:
        click.echo(f"config: {cfg_path}")

    # CLI beats config beats profile beats field defaults.
    chosen_profile = profile or cfg.profile or "default"
    add = tuple(cfg.mask) + tuple(mask)
    drop = tuple(cfg.no_mask) + tuple(no_mask)
    try:
        selected = resolve(chosen_profile, add, drop)
    except FieldError as exc:
        raise click.ClickException(str(exc)) from exc

    if not selected:
        raise click.ClickException(
            "nothing selected to redact; use --mask or a different --profile"
        )

    overrides = dict(cfg.keep_chars)
    for key, value in _parse_pairs(keep_chars, "--keep-chars").items():
        if key not in BY_NAME:
            raise click.ClickException(f"unknown field {key!r} in --keep-chars")
        if not value.isdigit():
            raise click.ClickException(f"--keep-chars {key} expects a number")
        overrides[key] = int(value)

    styles = dict(cfg.styles)
    if style:
        styles["all"] = style
    styles.update(_parse_pairs(field_style, "--field-style"))
    for key, value in styles.items():
        if value not in STYLES:
            raise click.ClickException(f"unknown style {value!r} for {key!r}")

    rows_raw = keep_rows or ",".join(cfg.keep_rows)
    rows = {r.strip() for r in rows_raw.split(",") if r.strip()}
    unknown_rows = rows - set(ROW_KINDS)
    if unknown_rows:
        raise click.ClickException(
            f"unknown row kind(s) {', '.join(sorted(unknown_rows))}; "
            f"choose from {', '.join(sorted(ROW_KINDS))}"
        )

    mode = group_by or cfg.group_by or "establishment"
    do_merge = (
        merge if merge is not None else (cfg.merge if cfg.merge is not None else True)
    )
    out_dir = out or (Path(cfg.out) if cfg.out else DEFAULT_OUT)

    paths = _expand(inputs)
    if not quiet:
        click.echo(f"redacting {len(paths)} file(s): {', '.join(sorted(selected))}")

    sources: list[Source] = []
    try:
        for path in paths:
            try:
                doc, reports = redact_document(
                    path, selected, styles, rows, overrides, dry_run=dry_run
                )
            except StyleError as exc:
                raise click.ClickException(str(exc)) from exc
            sources.append(Source(path=path, doc=doc, reports=reports))
            if not quiet:
                total = sum(sum(r.counts.values()) for r in reports)
                fallback = any(not r.detected_columns for r in reports)
                note = "  [fallback geometry]" if fallback else ""
                click.echo(f"  {path.name}: {total} redaction(s){note}")

        if dry_run:
            _report_dry_run(sources)
            return

        outputs = group(sources, mode, do_merge)
        problems = []
        for output in outputs:
            dest = write(output, out_dir)
            pages = sum(s.doc.page_count for s in output.sources)
            found = verify(dest, [r for s in output.sources for r in s.reports], pages)
            problems.extend(found)
            if not quiet:
                status = "LEAKS" if found else "verified clean"
                click.echo(f"-> {dest}  ({pages} pages, {status})")
    finally:
        for source in sources:
            source.doc.close()

    for problem in problems:
        click.echo(f"  {problem}", err=True)
    if problems and fail_on_leak:
        raise SystemExit(1)


def _report_dry_run(sources: list[Source]) -> None:
    click.echo("\ndry run - nothing written\n")
    for source in sources:
        click.echo(f"{source.path}")
        totals: dict[str, int] = {}
        for report in source.reports:
            for name, count in report.counts.items():
                totals[name] = totals.get(name, 0) + count
        if not totals:
            click.echo("    (nothing matched)")
            continue
        width = max(len(n) for n in totals)
        for name in sorted(totals):
            click.echo(f"    {name:<{width}}  {totals[name]:>4}")


if __name__ == "__main__":
    sys.exit(main())
