"""Command line interface for epfo-synth."""

from __future__ import annotations

from pathlib import Path

import click

from .generate import generate


def _years(ctx, param, value: str) -> tuple[int, int]:
    try:
        start, _, end = value.partition(":")
        if not end:
            start = end = start
        first, last = int(start), int(end)
    except ValueError:
        raise click.BadParameter("expected START:END, e.g. 2015:2021") from None
    if first > last:
        raise click.BadParameter(f"start year {first} is after end year {last}")
    return first, last


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "-o",
    "--out",
    default="samples/synthetic",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where to write the generated passbooks.",
)
@click.option("--employers", default=2, show_default=True, help="Number of employers.")
@click.option(
    "--years",
    default="2015:2021",
    show_default=True,
    callback=_years,
    metavar="START:END",
    help="Financial years to cover, split across the employers.",
)
@click.option("--seed", type=int, help="Seed, for reproducible output.")
@click.option("--locale", default="en_IN", show_default=True, help="Faker locale.")
@click.option("-q", "--quiet", is_flag=True, help="Only print the summary line.")
def main(out, employers, years, seed, locale, quiet):
    """Generate fake EPFO passbook PDFs for testing and demos.

    Every name, employer, account number and rupee figure is invented. The
    contribution arithmetic follows the statutory rules (12% EPF, 8.33% EPS
    capped at the wage ceiling) so the output behaves like a real statement
    without containing anyone's data.

    \b
    Examples:
      epfo-synth --seed 42
      epfo-synth --employers 3 --years 2009:2026 -o /tmp/demo
    """
    written = generate(
        out_dir=out, employers=employers, years=years, seed=seed, locale=locale
    )
    if not quiet:
        for path in written:
            click.echo(f"  {path}")
    folders = sorted({p.parent.name for p in written})
    click.echo(
        f"wrote {len(written)} synthetic passbook(s) "
        f"across {len(folders)} employer(s): {', '.join(folders)}"
    )


if __name__ == "__main__":
    main()
