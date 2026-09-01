"""Layout detection: columns, rows, and the identifiers in the header."""

from __future__ import annotations

import pymupdf
import pytest

from epfo_redactor.fields import (
    COL_EMPLOYEE,
    COL_EMPLOYER,
    COL_EPF_WAGES,
    COL_EPS_WAGES,
    COL_PENSION,
)
from epfo_redactor.layout import (
    MEMBER_ID,
    _bracketed,
    analyse,
    chars_of,
    detect_columns,
    find_table_bounds,
    group_lines,
    numeric_cells,
    tail_rect,
    words_of,
)

ALL_COLUMNS = {
    COL_EPF_WAGES,
    COL_EPS_WAGES,
    COL_EMPLOYEE,
    COL_EMPLOYER,
    COL_PENSION,
}


def test_all_five_columns_are_found_from_labels(page):
    layout = analyse(page, selected=set(), keep_rows=set())
    assert set(layout.columns) == ALL_COLUMNS
    assert layout.detected_columns, "should not have fallen back to fixed geometry"


def test_columns_are_ordered_left_to_right(page):
    layout = analyse(page, selected=set(), keep_rows=set())
    order = [
        layout.columns[k]
        for k in (
            COL_EPF_WAGES,
            COL_EPS_WAGES,
            COL_EMPLOYEE,
            COL_EMPLOYER,
            COL_PENSION,
        )
    ]
    assert order == sorted(order)


def test_table_bounds_sit_between_the_header_and_the_closing_row(page):
    lines = group_lines(words_of(page))
    top, bottom, detected = find_table_bounds(lines)
    assert detected
    assert top < bottom
    text_above = [
        y
        for y, ws in lines
        if y < top and "Financial Year" in " ".join(w[4] for w in ws)
    ]
    assert text_above, "the financial-year title should be above the table"


def test_bracketed_year_is_not_treated_as_a_cell(page):
    """`Total Contributions for the year [ 2021 ]` puts a year inside a column band.

    It is a row label. Redacting it would corrupt the statement, and it must
    never be counted as a value.
    """
    lines = group_lines(words_of(page))
    top, bottom, _ = find_table_bounds(lines)
    total_line = next(
        ws for y, ws in lines if "Total Contributions" in " ".join(w[4] for w in ws)
    )
    texts = [w[4] for w in total_line]
    year = next(t for t in texts if t.isdigit() and len(t) == 4)
    assert year in texts

    skipped = {texts[i] for i in _bracketed(total_line)}
    assert year in skipped

    cells = numeric_cells(lines, top, bottom)
    on_that_row = [w[4] for w in cells if w in total_line]
    assert year not in on_that_row


def test_bracketed_handles_unbalanced_brackets():
    def word(text, i):
        return (i * 10.0, 0.0, i * 10.0 + 5, 8.0, text, 0, 0, i)

    ws = [word(t, i) for i, t in enumerate(["Total", "[", "2021", "extra"])]
    assert _bracketed(ws) == {2, 3}
    ws = [word(t, i) for i, t in enumerate(["a", "]", "2021"])]
    assert _bracketed(ws) == set()


def test_tail_rect_splits_on_a_glyph_boundary(page):
    """The retained prefix must be untouched and the rest fully covered."""
    words = words_of(page)
    chars = chars_of(page)
    member = next(w for w in words if MEMBER_ID.match(w[4]))
    rect = tail_rect(chars, member, 5)
    box = pymupdf.Rect(member[:4])

    prefix = [
        r
        for r, _ in chars
        if box.contains(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        and r.x1 <= rect.x0 + 0.01
    ]
    assert len(prefix) == 5, "exactly the 5 kept characters sit left of the box"
    assert rect.x1 == pytest.approx(box.x1, abs=0.5)


def test_tail_rect_falls_back_when_keep_exceeds_the_word(page):
    """Asking to keep more characters than exist must not under-redact."""
    words = words_of(page)
    chars = chars_of(page)
    uan = next(w for w in words if w[4].isdigit() and len(w[4]) == 12)
    rect = tail_rect(chars, uan, 99)
    assert rect.x1 == pytest.approx(pymupdf.Rect(uan[:4]).x1, abs=0.5)


def test_detect_columns_falls_back_without_anchors():
    columns, detected = detect_columns(cells=[], anchors={})
    assert not detected
    assert set(columns) == ALL_COLUMNS


def test_row_kinds_are_classified(page):
    layout = analyse(page, selected=set(), keep_rows=set())
    kinds = {kind for _, _, kind in layout.rows}
    assert {"opening", "contributions", "transfers", "withdrawals", "closing"} <= kinds


def test_fiscal_year_and_establishment_are_read(page):
    layout = analyse(page, selected=set(), keep_rows=set())
    assert layout.fiscal_year is not None
    assert 2000 < layout.fiscal_year < 2100
    assert layout.establishment_id and layout.establishment_id[:5].isalpha()
