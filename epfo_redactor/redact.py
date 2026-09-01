"""Apply the redaction plan to a document.

This removes the text from the PDF content stream -- it does not draw a box on
top of it. A drawn box leaves the original string sitting underneath, where
copy-paste, ``pdftotext`` or a text search will find it, which is the usual way
a "masked" document leaks. Everything here goes through MuPDF's redaction
annotations so the glyphs are gone before the file is written.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from .fields import BY_NAME, FINANCIAL
from .layout import PageLayout, Target, analyse

STYLES: dict[str, tuple[float, float, float] | None] = {
    "black": (0.0, 0.0, 0.0),
    "grey": (0.68, 0.68, 0.68),
    "gray": (0.68, 0.68, 0.68),
    "white": (1.0, 1.0, 1.0),
    "hatch": (0.93, 0.93, 0.93),
}

DEFAULT_STYLE = {"identity": "black", FINANCIAL: "grey"}


class StyleError(ValueError):
    """Raised for an unknown style name."""


@dataclass
class PageReport:
    """What was redacted on one page, for the verifier and the dry-run table."""

    number: int
    fiscal_year: int | None
    establishment_id: str | None
    detected_columns: bool
    literals: list[str]
    counts: dict[str, int]
    masked_edges: list[float]
    # y-bands of rows --keep-rows spared, so the verifier does not read
    # a deliberately kept cell as a missed one.
    exempt_bands: list[tuple[float, float]]


def style_for(field_name: str, styles: dict[str, str]) -> str:
    """Per-field override, then per-kind default."""
    if field_name in styles:
        return styles[field_name]
    kind = BY_NAME[field_name].kind
    if kind in styles:
        return styles[kind]
    if "all" in styles:
        return styles["all"]
    return DEFAULT_STYLE[kind]


def _fill(style: str) -> tuple[float, float, float]:
    if style not in STYLES:
        raise StyleError(
            f"unknown style {style!r}; choose from {', '.join(sorted(STYLES))}"
        )
    return STYLES[style]


def _decorate(page: pymupdf.Page, rect: pymupdf.Rect, style: str) -> None:
    """Post-redaction drawing for styles a flat fill cannot express."""
    shape = page.new_shape()
    if style == "hatch":
        step = 2.5
        x = rect.x0 - rect.height
        while x < rect.x1:
            shape.draw_line(
                pymupdf.Point(max(x, rect.x0), rect.y1),
                pymupdf.Point(min(x + rect.height, rect.x1), rect.y0),
            )
            x += step
        shape.finish(color=(0.45, 0.45, 0.45), width=0.4)
    elif style == "white":
        shape.draw_rect(rect)
        shape.finish(color=(0.35, 0.35, 0.35), width=0.5)
    else:
        return
    shape.commit()


def redact_page(
    page: pymupdf.Page,
    selected: set[str],
    styles: dict[str, str],
    keep_rows: set[str],
    keep_chars: dict[str, int] | None = None,
    dry_run: bool = False,
) -> PageReport:
    """Plan and (unless dry-running) apply the redactions for one page."""
    layout: PageLayout = analyse(page, selected, keep_rows, keep_chars)

    literals: list[str] = []
    counts: dict[str, int] = {}
    by_style: dict[str, list[Target]] = {}

    for name, targets in layout.identity.items():
        counts[name] = len(targets)
        literals.extend(t.literal for t in targets)
        by_style.setdefault(style_for(name, styles), []).extend(targets)

    for name, targets in layout.cells.items():
        counts[name] = len(targets)
        by_style.setdefault(style_for(name, styles), []).extend(targets)

    masked_edges = [
        layout.columns[BY_NAME[n].column] for n in layout.cells if BY_NAME[n].column
    ]
    exempt_bands = [
        (top, bottom) for top, bottom, kind in layout.rows if kind in keep_rows
    ]

    if not dry_run:
        for style, targets in by_style.items():
            fill = _fill(style)
            for target in targets:
                page.add_redact_annot(target.rect, fill=fill)
        if by_style:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        for style, targets in by_style.items():
            if style in ("hatch", "white"):
                for target in targets:
                    _decorate(page, target.rect, style)

    return PageReport(
        number=page.number,
        fiscal_year=layout.fiscal_year,
        establishment_id=layout.establishment_id,
        detected_columns=layout.detected_columns,
        literals=sorted(set(literals)),
        counts=counts,
        masked_edges=sorted(set(masked_edges)),
        exempt_bands=exempt_bands,
    )


def redact_document(
    path,
    selected: set[str],
    styles: dict[str, str],
    keep_rows: set[str],
    keep_chars: dict[str, int] | None = None,
    dry_run: bool = False,
) -> tuple[pymupdf.Document, list[PageReport]]:
    """Open a passbook PDF and redact every page. Caller closes the document."""
    doc = pymupdf.open(path)
    reports = [
        redact_page(page, selected, styles, keep_rows, keep_chars, dry_run=dry_run)
        for page in doc
    ]
    return doc, reports
