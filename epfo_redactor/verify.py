"""Prove the output is actually redacted.

Three independent checks, because the failure mode this tool exists to prevent
is a document that *looks* redacted:

1. no redacted literal survives in the extracted text;
2. no redacted literal survives in the raw file bytes, which catches a value
   that is hidden visually but still present in the content stream;
3. no numeric cell remains in a column that was supposed to be cleared, which
   catches a row the planner missed rather than a value it knew about.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .layout import NUMERIC, find_table_bounds, group_lines, numeric_cells, words_of
from .redact import PageReport

CLUSTER_TOLERANCE = 2.0


@dataclass
class Problem:
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


def verify(
    path: Path, reports: list[PageReport], expect_pages: int | None = None
) -> list[Problem]:
    """Check a written output file. An empty list means it is clean."""
    problems: list[Problem] = []
    literals = sorted({lit for r in reports for lit in r.literals})
    edges = sorted({e for r in reports for e in r.masked_edges})
    exempt = [band for r in reports for band in getattr(r, "exempt_bands", ())]

    doc = pymupdf.open(path)
    try:
        if expect_pages is not None and doc.page_count != expect_pages:
            problems.append(
                Problem(
                    "page-count",
                    f"{path.name}: expected {expect_pages} pages, "
                    f"got {doc.page_count}",
                )
            )

        text = "\n".join(page.get_text() for page in doc)
        for literal in literals:
            if literal in text:
                problems.append(
                    Problem("text-leak", f"{path.name}: {literal!r} still readable")
                )

        for page in doc:
            lines = group_lines(words_of(page))
            top, bottom, _ = find_table_bounds(lines)
            for cell in numeric_cells(lines, top, bottom):
                if _exempt(cell, exempt):
                    continue
                if any(abs(cell[2] - e) <= CLUSTER_TOLERANCE for e in edges):
                    problems.append(
                        Problem(
                            "cell-leak",
                            f"{path.name} p{page.number + 1}: {cell[4]!r} "
                            f"remains in a redacted column",
                        )
                    )
        for literal in literals:
            where = _in_content_streams(doc, literal)
            if where:
                problems.append(
                    Problem(
                        "byte-leak",
                        f"{path.name}: {literal!r} still in the content stream "
                        f"of page {where}",
                    )
                )
    finally:
        doc.close()

    raw = path.read_bytes()
    for literal in literals:
        if literal.encode("utf-8") in raw:
            problems.append(
                Problem("byte-leak", f"{path.name}: {literal!r} present in file bytes")
            )

    return problems


def _exempt(cell, bands) -> bool:
    """True if this cell sits in a row the user asked to keep."""
    return any(top - 1.0 <= cell[1] <= bottom + 1.0 for top, bottom in bands)


def _in_content_streams(doc: pymupdf.Document, literal: str) -> int | None:
    """Page number whose decompressed content stream still holds ``literal``.

    Text extraction alone is not enough: a value can sit in the content stream
    in a form the extractor skips. Streams are deflated, so searching the file
    bytes finds nothing either -- we have to decompress first, and look for both
    ways a PDF writer stores a string. iText writes ASCII literals ``(ABC123)``;
    MuPDF writes hex ``<414243313233>``.

    A string broken across kerned pieces would evade this substring search; the
    text-extraction check above is what covers that case.
    """
    ascii_form = literal.encode("utf-8")
    hex_form = ascii_form.hex().encode("ascii")
    for page in doc:
        content = page.read_contents()
        if not content:
            continue
        if ascii_form in content:
            return page.number + 1
        lowered = content.lower()
        if hex_form in lowered:
            return page.number + 1
    return None


def expected_to_remain(path: Path, needles: list[str]) -> list[Problem]:
    """Warn when something we meant to keep has gone missing."""
    doc = pymupdf.open(path)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return [
        Problem("over-redacted", f"{path.name}: expected {n!r} to remain")
        for n in needles
        if n not in text
    ]


__all__ = ["Problem", "verify", "expected_to_remain", "NUMERIC"]
