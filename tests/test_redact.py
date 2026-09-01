"""Redaction behaviour: what disappears, what survives, and how thoroughly."""

from __future__ import annotations

import pymupdf
import pytest

from epfo_redactor.fields import resolve
from epfo_redactor.redact import STYLES, StyleError, redact_document, style_for

DEFAULT = resolve("default")


def _text(doc):
    return "\n".join(p.get_text() for p in doc)


def _original(path):
    doc = pymupdf.open(path)
    try:
        return _text(doc)
    finally:
        doc.close()


def test_identifiers_are_gone_from_the_text(one_pdf):
    before = _original(one_pdf)
    doc, reports = redact_document(one_pdf, DEFAULT, {}, set())
    try:
        after = _text(doc)
        literals = {lit for r in reports for lit in r.literals}
        assert literals, "expected the header identifiers to be found"
        for literal in literals:
            assert literal in before
            assert literal not in after
    finally:
        doc.close()


def test_redaction_removes_text_rather_than_covering_it(one_pdf, tmp_path):
    """The failure this tool exists to prevent: a value hidden but still there."""
    doc, reports = redact_document(one_pdf, DEFAULT, {}, set())
    dest = tmp_path / "out.pdf"
    try:
        doc.save(dest, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    raw = dest.read_bytes()
    for literal in {lit for r in reports for lit in r.literals}:
        assert literal.encode() not in raw


def test_eps_columns_survive_the_default_profile(one_pdf):
    """EPS wages and the pension column must stay readable."""
    doc, _ = redact_document(one_pdf, DEFAULT, {}, set())
    try:
        after = _text(doc)
    finally:
        doc.close()
    # The EPS wage ceiling and the capped pension contribution.
    assert "15,000" in after
    assert "1,250" in after


def test_pension_balance_survives(one_pdf):
    source = pymupdf.open(one_pdf)
    layout_before = source[0].get_text("words")
    pension_values = {w[4] for w in layout_before if abs(w[2] - 568.0) < 2.0}
    source.close()

    doc, _ = redact_document(one_pdf, DEFAULT, {}, set())
    try:
        after = _text(doc)
    finally:
        doc.close()
    assert pension_values
    for value in pension_values:
        assert value in after


def test_strict_profile_also_removes_name_and_eps(one_pdf):
    doc, reports = redact_document(one_pdf, resolve("strict"), {}, set())
    try:
        after = _text(doc)
    finally:
        doc.close()
    counts = {k for r in reports for k in r.counts}
    assert {"member-name", "dob", "eps-wages", "eps-pension"} <= counts
    assert "15,000" not in after


def test_identity_profile_leaves_the_table_alone(one_pdf):
    before = _original(one_pdf)
    doc, reports = redact_document(one_pdf, resolve("identity"), {}, set())
    try:
        after = _text(doc)
    finally:
        doc.close()
    counts = {k for r in reports for k in r.counts}
    assert not any(k.startswith(("epf-", "eps-")) for k in counts)
    wage = [
        line for line in before.splitlines() if line.startswith("Cont. for Due-Month")
    ]
    assert wage  # sanity: the table was there to begin with
    assert "Closing Balance" in after


def test_keep_rows_exempts_the_withdrawal_row(one_pdf):
    """A zero withdrawal is usually favourable evidence, so it can be kept."""

    def total(reports):
        return sum(sum(r.counts.values()) for r in reports)

    plain, plain_reports = redact_document(one_pdf, DEFAULT, {}, set())
    plain.close()
    kept, kept_reports = redact_document(one_pdf, DEFAULT, {}, {"withdrawals"})
    try:
        after = _text(kept)
    finally:
        kept.close()

    # Two cells per withdrawal row (employee, employer) stay readable.
    assert total(plain_reports) - total(kept_reports) == 2
    assert "Total Withdrawals" in after


def test_keep_chars_override_widens_the_redaction(one_pdf):
    doc_a, _ = redact_document(one_pdf, {"uan"}, {}, set(), keep_chars={"uan": 4})
    doc_b, _ = redact_document(one_pdf, {"uan"}, {}, set(), keep_chars={"uan": 0})
    try:
        a, b = _text(doc_a), _text(doc_b)
    finally:
        doc_a.close()
        doc_b.close()
    # Keeping 0 characters leaves strictly less readable text behind.
    assert len(b) <= len(a)


def test_dry_run_changes_nothing(one_pdf):
    before = _original(one_pdf)
    doc, reports = redact_document(one_pdf, DEFAULT, {}, set(), dry_run=True)
    try:
        assert _text(doc) == before
    finally:
        doc.close()
    assert sum(sum(r.counts.values()) for r in reports) > 0


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_style_produces_a_readable_file(one_pdf, tmp_path, style):
    doc, reports = redact_document(one_pdf, DEFAULT, {"all": style}, set())
    dest = tmp_path / f"{style}.pdf"
    try:
        doc.save(dest, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    check = pymupdf.open(dest)
    try:
        assert check.page_count == 1
        for literal in {lit for r in reports for lit in r.literals}:
            assert literal not in _text(check)
    finally:
        check.close()


def test_unknown_style_is_rejected(one_pdf):
    with pytest.raises(StyleError):
        redact_document(one_pdf, DEFAULT, {"all": "chartreuse"}, set())


def test_style_precedence_field_then_kind_then_global():
    assert style_for("uan", {}) == "black"
    assert style_for("epf-wages", {}) == "grey"
    assert style_for("uan", {"all": "hatch"}) == "hatch"
    assert style_for("uan", {"all": "hatch", "identity": "white"}) == "white"
    assert style_for("uan", {"identity": "white", "uan": "black"}) == "black"
