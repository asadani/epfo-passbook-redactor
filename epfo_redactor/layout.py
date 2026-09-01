"""Read the structure of an EPFO passbook page.

Nothing here is hardcoded to a particular passbook. Columns are found by
locating the English header labels EPFO prints (``EPF``, ``EPS``, ``Employee``,
``Employer``, ``Pension``), clustering the numeric cells by their right edge --
the table is right-aligned -- and matching each cluster to the label above it.
That way the tool works on a passbook whose template has shifted, and it can be
tested against synthetic pages.

``FALLBACK_COLUMNS`` records the geometry observed on the 2026-era template, and
is used only when label detection fails outright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from .fields import (
    COL_EMPLOYEE,
    COL_EMPLOYER,
    COL_EPF_WAGES,
    COL_EPS_WAGES,
    COL_PENSION,
    ROW_KINDS,
)

# A cell value: 1,23,456 / 0 / -1,200 / 1234.50
NUMERIC = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
ESTABLISHMENT_ID = re.compile(r"^[A-Z]{2,6}\d{6,}$")
MEMBER_ID = re.compile(r"^[A-Z]{2,6}\d{10,}$")
UAN = re.compile(r"^\d{12}$")
DATE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
FISCAL_YEAR = re.compile(r"Financial\s+Year\s*-\s*(\d{4})")

# Words that end a company name rather than identifying it.
LEGAL_SUFFIXES = {
    "PRIVATE",
    "PVT",
    "PVT.",
    "LIMITED",
    "LTD",
    "LTD.",
    "LLP",
    "(P)",
    "(OPC)",
}

# Right edges seen on the 2026 template, used only if detection fails.
FALLBACK_COLUMNS: dict[str, float] = {
    COL_EPF_WAGES: 338.5,
    COL_EPS_WAGES: 395.9,
    COL_EMPLOYEE: 453.3,
    COL_EMPLOYER: 510.6,
    COL_PENSION: 568.0,
}
FALLBACK_TABLE = (243.5, 560.0)

# How far a numeric cluster may sit from its label before we refuse the match.
MAX_LABEL_DISTANCE = 40.0
# Right edges within this many points are the same column.
CLUSTER_TOLERANCE = 2.0

_WAGE_LABELS = {"EPF": COL_EPF_WAGES, "EPS": COL_EPS_WAGES}
_AMOUNT_LABELS = {
    "Employee": COL_EMPLOYEE,
    "Employer": COL_EMPLOYER,
    "Pension": COL_PENSION,
}


class LayoutError(RuntimeError):
    """Raised when a page does not look like an EPFO passbook."""


@dataclass
class Target:
    """One thing to redact, with the literal it covers."""

    rect: pymupdf.Rect
    literal: str
    field: str
    row: str = ""


@dataclass
class PageLayout:
    """Everything the redactor needs to know about one page."""

    number: int
    columns: dict[str, float]
    table_top: float
    table_bottom: float
    rows: list[tuple[float, float, str]]
    identity: dict[str, list[Target]] = field(default_factory=dict)
    cells: dict[str, list[Target]] = field(default_factory=dict)
    fiscal_year: int | None = None
    establishment_id: str | None = None
    detected_columns: bool = True

    @property
    def all_targets(self) -> list[Target]:
        out: list[Target] = []
        for group in (self.identity, self.cells):
            for targets in group.values():
                out.extend(targets)
        return out


def words_of(page: pymupdf.Page) -> list[tuple]:
    return page.get_text("words")


def chars_of(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    """Every character with its own box, for splitting a word mid-token."""
    out: list[tuple[pymupdf.Rect, str]] = []
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span["chars"]:
                    out.append((pymupdf.Rect(ch["bbox"]), ch["c"]))
    return out


def group_lines(words: list[tuple]) -> list[tuple[float, list[tuple]]]:
    """Group words into visual lines, ordered top to bottom, left to right."""
    lines: dict[int, list[tuple]] = {}
    for w in words:
        lines.setdefault(round(w[1]), []).append(w)
    return [
        (float(y), sorted(ws, key=lambda w: w[0])) for y, ws in sorted(lines.items())
    ]


def tail_rect(
    chars: list[tuple[pymupdf.Rect, str]], word: tuple, keep: int
) -> pymupdf.Rect:
    """Box around a word's characters after the first ``keep`` of them.

    Working per character rather than by proportion means the split lands
    exactly on a glyph boundary even in a proportional font, so the retained
    prefix is never clipped and no fragment of the redacted part survives.
    """
    box = pymupdf.Rect(word[:4])
    inside = [
        (r, c) for r, c in chars if box.contains(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    ]
    inside.sort(key=lambda rc: rc[0].x0)
    if len(inside) <= keep:
        # No character data (or fewer glyphs than we meant to keep): fall back
        # to a proportional split rather than under-redacting.
        span = box.x1 - box.x0
        frac = keep / max(len(word[4]), 1)
        return pymupdf.Rect(box.x0 + span * frac, box.y0, box.x1, box.y1)
    rect = pymupdf.Rect(inside[keep][0])
    for r, _ in inside[keep + 1 :]:
        rect |= r
    return rect


def _first_line_with(lines, *needles: str) -> tuple[float, list[tuple]] | None:
    for y, ws in lines:
        text = " ".join(w[4] for w in ws)
        if all(n in text for n in needles):
            return y, ws
    return None


def find_table_bounds(lines) -> tuple[float, float, bool]:
    """(top, bottom, detected). Top is under the balance header, bottom is the
    closing-balance row."""
    header = _first_line_with(lines, "Particulars")
    closing = _first_line_with(lines, "Closing Balance")
    if header is None or closing is None:
        return (*FALLBACK_TABLE, False)
    top = max(w[3] for w in header[1])
    bottom = max(w[3] for w in closing[1]) + 2.0
    return top, bottom, True


def _label_anchors(lines) -> dict[str, tuple[float, float]]:
    """x-ranges of the column header labels, unioned per logical column.

    Balance and contribution columns share a right edge, so ``Employee``
    appearing in both headers folds into one anchor.
    """
    anchors: dict[str, tuple[float, float]] = {}
    header_line = _first_line_with(lines, "Particulars")
    if header_line is None:
        return anchors
    lo = header_line[0] - 14.0
    hi = header_line[0] + 90.0

    for y, ws in lines:
        if not (lo <= y <= hi):
            continue
        text = " ".join(w[4] for w in ws)
        # The document title also says "EPF Passbook [ Financial Year ... ]".
        if "Passbook" in text or "Financial" in text:
            continue
        for w in ws:
            key = _WAGE_LABELS.get(w[4]) or _AMOUNT_LABELS.get(w[4])
            if key is None:
                continue
            x0, x1 = w[0], w[2]
            if key in anchors:
                prev = anchors[key]
                anchors[key] = (min(prev[0], x0), max(prev[1], x1))
            else:
                anchors[key] = (x0, x1)
    return anchors


def _bracketed(ws: list[tuple]) -> set[int]:
    """Indices of words sitting between '[' and ']' on a line.

    The "Total Contributions for the year [ 2021 ]" rows put a bare year inside
    the EPS-wages column band. It is a label, not a cell, and must never be
    treated as one.
    """
    out: set[int] = set()
    depth = 0
    for i, w in enumerate(ws):
        if w[4] == "[":
            depth += 1
        elif w[4] == "]":
            depth = max(0, depth - 1)
        elif depth:
            out.add(i)
    return out


def numeric_cells(lines, table_top: float, table_bottom: float) -> list[tuple]:
    """Table cell words, with row labels and bracketed years filtered out."""
    cells = []
    for y, ws in lines:
        if not (table_top < y < table_bottom):
            continue
        skip = _bracketed(ws)
        for i, w in enumerate(ws):
            if i not in skip and NUMERIC.match(w[4]):
                cells.append(w)
    return cells


def detect_columns(cells, anchors) -> tuple[dict[str, float], bool]:
    """Map right-edge clusters of cells onto the header labels."""
    if not anchors or not cells:
        return dict(FALLBACK_COLUMNS), False

    edges = sorted(w[2] for w in cells)
    clusters: list[list[float]] = []
    for x in edges:
        if clusters and x - clusters[-1][-1] <= CLUSTER_TOLERANCE:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    columns: dict[str, float] = {}
    for group in clusters:
        if len(group) < 2:
            continue
        edge = sum(group) / len(group)
        best, best_dist = None, None
        for key, (ax0, ax1) in anchors.items():
            dist = 0.0 if ax0 <= edge <= ax1 else min(abs(edge - ax0), abs(edge - ax1))
            if best_dist is None or dist < best_dist:
                best, best_dist = key, dist
        if best is None or best_dist > MAX_LABEL_DISTANCE:
            continue
        # Widest cluster wins if two land on the same label.
        if best not in columns or len(group) > 1:
            columns[best] = edge
    if not columns:
        return dict(FALLBACK_COLUMNS), False
    return columns, True


def classify_rows(lines, table_top: float, table_bottom: float) -> list:
    """y-bands for the named summary rows; everything else is 'monthly'."""
    rows = []
    for y, ws in lines:
        if not (table_top < y < table_bottom):
            continue
        text = " ".join(w[4] for w in ws)
        kind = "monthly"
        for name, marker in ROW_KINDS.items():
            if marker in text:
                kind = name
                break
        rows.append((y, max(w[3] for w in ws), kind))
    return rows


def _row_kind(rows, y: float) -> str:
    for top, bottom, kind in rows:
        if top - 1.0 <= y <= bottom + 1.0:
            return kind
    return "monthly"


def _identity_targets(page, lines, chars, selected, keep_chars):
    """Locate the header identifiers, honouring each field's retained prefix.

    Identifiers that repeat elsewhere on the page -- the member ID is reprinted
    in the footer of every page -- are found by matching the literal, so a
    template that repeats them somewhere new is still covered.
    """
    from .fields import BY_NAME

    words = words_of(page)
    found: dict[str, list[Target]] = {}
    literals: dict[str, str] = {}
    word_groups: dict[str, list[tuple]] = {}

    est = _first_line_with(lines, "Establishment", "ID/Name")
    if est:
        ws = est[1]
        for i, w in enumerate(ws):
            if ESTABLISHMENT_ID.match(w[4]):
                literals["establishment-id"] = w[4]
                rest = [x for x in ws[i + 1 :] if x[4] != "/"]
                while rest and rest[-1][4].upper() in LEGAL_SUFFIXES:
                    rest.pop()
                if rest:
                    word_groups["employer-name"] = rest
                break

    member = _first_line_with(lines, "Member", "ID/Name")
    if member:
        ws = member[1]
        for i, w in enumerate(ws):
            if MEMBER_ID.match(w[4]):
                literals["member-id"] = w[4]
                name = [x for x in ws[i + 1 :] if x[4] != "/"]
                if name:
                    word_groups["member-name"] = name
                break

    uan = _first_line_with(lines, "UAN")
    if uan:
        for w in uan[1]:
            if UAN.match(w[4]):
                literals["uan"] = w[4]
                break

    dob = _first_line_with(lines, "Date", "Birth")
    if dob:
        for w in dob[1]:
            if DATE.match(w[4]):
                word_groups["dob"] = [w]
                break

    # Prefix-preserving identifiers: redact every occurrence on the page.
    for name, literal in literals.items():
        if name not in selected:
            continue
        keep = keep_chars.get(name, BY_NAME[name].keep_chars)
        targets = [
            Target(tail_rect(chars, w, keep), literal, name)
            for w in words
            if w[4] == literal
        ]
        if targets:
            found[name] = targets

    # Multi-word values: one box across the whole group.
    for name, group in word_groups.items():
        if name not in selected:
            continue
        rect = pymupdf.Rect(group[0][:4])
        for w in group[1:]:
            rect |= pymupdf.Rect(w[:4])
        found[name] = [Target(rect, " ".join(w[4] for w in group), name)]

    return found, literals


def analyse(
    page: pymupdf.Page,
    selected: set[str],
    keep_rows: set[str],
    keep_chars: dict[str, int] | None = None,
) -> PageLayout:
    """Build the redaction plan for one page."""
    from .fields import BY_NAME

    words = words_of(page)
    if not words:
        raise LayoutError(f"page {page.number + 1} has no extractable text")
    lines = group_lines(words)
    chars = chars_of(page)

    table_top, table_bottom, _ = find_table_bounds(lines)
    anchors = _label_anchors(lines)
    cells = numeric_cells(lines, table_top, table_bottom)
    columns, detected = detect_columns(cells, anchors)
    rows = classify_rows(lines, table_top, table_bottom)

    identity, _literals = _identity_targets(
        page, lines, chars, selected, keep_chars or {}
    )

    wanted = {
        BY_NAME[n].column: n
        for n in selected
        if BY_NAME[n].is_financial and BY_NAME[n].column in columns
    }
    cell_targets: dict[str, list[Target]] = {}
    for w in cells:
        for col_key, field_name in wanted.items():
            if abs(w[2] - columns[col_key]) > CLUSTER_TOLERANCE:
                continue
            kind = _row_kind(rows, w[1])
            if kind in keep_rows:
                continue
            rect = pymupdf.Rect(w[0] - 0.5, w[1], w[2] + 0.5, w[3])
            cell_targets.setdefault(field_name, []).append(
                Target(rect, w[4], field_name, kind)
            )
            break

    text = page.get_text()
    fy = FISCAL_YEAR.search(text)
    est_word = _first_line_with(lines, "Establishment", "ID/Name")
    est_id = None
    if est_word:
        for w in est_word[1]:
            if ESTABLISHMENT_ID.match(w[4]):
                est_id = w[4]
                break

    return PageLayout(
        number=page.number,
        columns=columns,
        table_top=table_top,
        table_bottom=table_bottom,
        rows=rows,
        identity=identity,
        cells=cell_targets,
        fiscal_year=int(fy.group(1)) if fy else None,
        establishment_id=est_id,
        detected_columns=detected,
    )
