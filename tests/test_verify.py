"""The verifier has to actually catch a bad document.

A verifier that only ever passes is worse than none, so these tests hand it
deliberately broken output and check it complains.
"""

from __future__ import annotations

import pymupdf

from epfo_redactor.fields import resolve
from epfo_redactor.redact import redact_document
from epfo_redactor.verify import expected_to_remain, verify

DEFAULT = resolve("default")


def _write(path, one_pdf, selected=DEFAULT, keep_rows=frozenset()):
    doc, reports = redact_document(one_pdf, selected, {}, set(keep_rows))
    try:
        doc.save(path, garbage=4, deflate=True, clean=True)
        pages = doc.page_count
    finally:
        doc.close()
    return reports, pages


def test_clean_output_reports_no_problems(one_pdf, tmp_path):
    dest = tmp_path / "clean.pdf"
    reports, pages = _write(dest, one_pdf)
    assert verify(dest, reports, pages) == []


def test_a_covered_but_unremoved_value_is_caught(one_pdf, tmp_path):
    """Draw a black box the lazy way and confirm the verifier is not fooled."""
    dest = tmp_path / "covered.pdf"
    doc = pymupdf.open(one_pdf)
    try:
        page = doc[0]
        words = page.get_text("words")
        uan = next(w for w in words if w[4].isdigit() and len(w[4]) == 12)
        shape = page.new_shape()
        shape.draw_rect(pymupdf.Rect(uan[:4]))
        shape.finish(fill=(0, 0, 0), color=(0, 0, 0))
        shape.commit()
        doc.save(dest, garbage=4, deflate=True, clean=True)
        literal = uan[4]
    finally:
        doc.close()

    class FakeReport:
        literals = [literal]
        masked_edges: list[float] = []

    problems = verify(dest, [FakeReport()])
    kinds = {p.kind for p in problems}
    assert "text-leak" in kinds
    assert "byte-leak" in kinds


def test_a_missed_cell_is_caught(one_pdf, tmp_path):
    """Report a column as redacted while leaving it untouched."""
    dest = tmp_path / "missed.pdf"
    doc = pymupdf.open(one_pdf)
    try:
        edge = max(
            w[2] for w in doc[0].get_text("words") if w[4].replace(",", "").isdigit()
        )
        doc.save(dest, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    class FakeReport:
        literals: list[str] = []
        masked_edges = [edge]

    problems = verify(dest, [FakeReport()])
    assert any(p.kind == "cell-leak" for p in problems)


def test_wrong_page_count_is_caught(one_pdf, tmp_path):
    dest = tmp_path / "pages.pdf"
    reports, pages = _write(dest, one_pdf)
    problems = verify(dest, reports, expect_pages=pages + 1)
    assert any(p.kind == "page-count" for p in problems)


def test_over_redaction_is_reported(one_pdf, tmp_path):
    dest = tmp_path / "strict.pdf"
    _write(dest, one_pdf, selected=resolve("strict"))
    problems = expected_to_remain(dest, ["Closing Balance", "definitely-not-present"])
    assert len(problems) == 1
    assert "definitely-not-present" in problems[0].detail


def test_keep_rows_cells_are_not_reported_as_leaks(one_pdf, tmp_path):
    """A row spared by --keep-rows sits in a redacted column by design.

    The column scan cannot tell that apart from a row the planner missed, so
    the report carries the spared bands and the verifier honours them.
    """
    dest = tmp_path / "kept.pdf"
    reports, pages = _write(dest, one_pdf, keep_rows={"withdrawals", "transfers"})
    assert any(r.exempt_bands for r in reports)
    assert verify(dest, reports, pages) == []
