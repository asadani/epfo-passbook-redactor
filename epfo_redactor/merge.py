"""Group redacted pages into output PDFs.

The default grouping is one PDF per employer, pages in financial-year order --
which is what a background-check reviewer wants to receive. The output file is
named after the 5-letter regional prefix only, never the full establishment
code, so the filename does not undo the redaction inside the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .redact import PageReport

SCRUBBED_METADATA = {
    "title": "EPF Member Passbook (redacted)",
    "author": "EPFO",
    "subject": "EPF Member Passbook",
    "keywords": "",
    "creator": "",
    "producer": "",
    "creationDate": "",
    "modDate": "",
}

YEAR_IN_NAME = re.compile(r"(19|20)\d{2}")


@dataclass
class Source:
    """One redacted input document, still open."""

    path: Path
    doc: pymupdf.Document
    reports: list[PageReport]

    @property
    def fiscal_year(self) -> int | None:
        for report in self.reports:
            if report.fiscal_year is not None:
                return report.fiscal_year
        match = YEAR_IN_NAME.search(self.path.stem)
        return int(match.group(0)) if match else None

    @property
    def establishment_id(self) -> str | None:
        for report in self.reports:
            if report.establishment_id:
                return report.establishment_id
        return None


@dataclass
class Output:
    """One PDF to write."""

    label: str
    sources: list[Source] = field(default_factory=list)

    @property
    def years(self) -> list[int]:
        return sorted(s.fiscal_year for s in self.sources if s.fiscal_year is not None)

    def filename(self) -> str:
        years = self.years
        if years:
            span = f"{years[0]}-{years[-1]}" if years[0] != years[-1] else f"{years[0]}"
            return f"EPFO_Passbook_{self.label}_FY{span}_redacted.pdf"
        return f"EPFO_Passbook_{self.label}_redacted.pdf"


def _sort_key(source: Source) -> tuple:
    return (
        source.fiscal_year if source.fiscal_year is not None else 9999,
        source.path.name,
    )


def group(sources: list[Source], mode: str, merge: bool) -> list[Output]:
    """Bucket sources into outputs according to --group-by / --no-merge."""
    if not merge:
        return [Output(label=s.path.stem, sources=[s]) for s in sources]

    buckets: dict[str, list[Source]] = {}
    labels: dict[str, str] = {}
    for source in sources:
        if mode == "establishment":
            est = source.establishment_id
            key = est or source.path.parent.name
            # Show only the regional prefix; the full code is redacted inside.
            label = est[:5] if est else source.path.parent.name
        elif mode == "dir":
            key = label = source.path.parent.name
        else:
            key = label = source.path.stem
        buckets.setdefault(key, []).append(source)
        labels[key] = label

    # Two employers can share a regional prefix; keep the labels distinct.
    seen: dict[str, int] = {}
    outputs = []
    for key, group_sources in buckets.items():
        label = labels[key]
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            label = f"{label}-{seen[label]}"
        outputs.append(
            Output(label=label, sources=sorted(group_sources, key=_sort_key))
        )
    return outputs


def write(output: Output, out_dir: Path) -> Path:
    """Merge an output's sources and write it, with metadata scrubbed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / output.filename()
    merged = pymupdf.open()
    try:
        for source in output.sources:
            merged.insert_pdf(source.doc)
        merged.set_metadata(dict(SCRUBBED_METADATA))
        merged.del_xml_metadata()
        merged.save(dest, garbage=4, deflate=True, clean=True)
    finally:
        merged.close()
    return dest
