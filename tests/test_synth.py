"""The synthetic generator: correct arithmetic, reproducible, and clearly fake."""

from __future__ import annotations

import random
import re

import pymupdf
import pytest

from epfo_redactor.fields import (
    COL_EMPLOYEE,
    COL_EMPLOYER,
    COL_EPF_WAGES,
    COL_EPS_WAGES,
    COL_PENSION,
)
from epfo_redactor.layout import analyse

from epfo_redactor.synth.generate import (
    EPS_MAX,
    MARKER,
    EPS_WAGE_CEILING,
    Employer,
    _contributions,
    build_years,
    generate,
    inr,
    make_member,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0"),
        (999, "999"),
        (1000, "1,000"),
        (99999, "99,999"),
        (118344, "1,18,344"),
        (10000000, "1,00,00,000"),
        (-1500, "-1,500"),
    ],
)
def test_indian_digit_grouping(value, expected):
    assert inr(value) == expected


def test_pension_is_capped_at_the_statutory_maximum():
    _, _, pension = _contributions(200000)
    assert pension == EPS_MAX


def test_below_the_ceiling_pension_tracks_the_wage():
    wage = 10000
    _, _, pension = _contributions(wage)
    assert pension == round(wage * 0.0833)
    assert pension < EPS_MAX


def test_employer_share_is_epf_less_pension():
    for wage in (9000, EPS_WAGE_CEILING, 45000):
        employee, employer, pension = _contributions(wage)
        assert employee == employer + pension


def test_balances_carry_across_years():
    employer = Employer(
        name="X PRIVATE LIMITED",
        establishment_id="ABCDE1234567890",
        member_id="ABCDE12345678900000001",
        start_year=2015,
        end_year=2018,
        monthly_wage=40000,
    )
    sheets = build_years(employer, random.Random(1))
    assert len(sheets) == 4
    for previous, current in zip(sheets, sheets[1:]):
        assert current.open_employee == previous.close_employee
        assert current.open_employer == previous.close_employer
        assert current.open_pension == previous.close_pension
    assert sheets[0].open_employee == 0
    assert sheets[-1].close_employee > sheets[0].close_employee


def test_closing_balance_is_opening_plus_contributions_plus_interest():
    employer = Employer(
        name="X PRIVATE LIMITED",
        establishment_id="ABCDE1234567890",
        member_id="ABCDE12345678900000001",
        start_year=2015,
        end_year=2016,
        monthly_wage=30000,
    )
    for sheet in build_years(employer, random.Random(2)):
        assert sheet.close_employee == (
            sheet.open_employee + sheet.total_employee + sheet.int_employee
        )


def test_generation_is_reproducible(tmp_path):
    a = generate(tmp_path / "a", employers=1, years=(2019, 2020), seed=99)
    b = generate(tmp_path / "b", employers=1, years=(2019, 2020), seed=99)
    assert [p.name for p in a] == [p.name for p in b]

    def text(path):
        doc = pymupdf.open(path)
        try:
            return "\n".join(p.get_text() for p in doc)
        finally:
            doc.close()

    assert text(a[0]) == text(b[0])


def test_different_seeds_give_different_people(tmp_path):
    a = generate(tmp_path / "a", employers=1, years=(2019, 2019), seed=1)
    b = generate(tmp_path / "b", employers=1, years=(2019, 2019), seed=2)
    assert a[0].name != b[0].name


def test_generated_pages_carry_the_labels_the_redactor_needs(tmp_path):
    paths = generate(tmp_path, employers=1, years=(2019, 2019), seed=5)
    doc = pymupdf.open(paths[0])
    try:
        text = doc[0].get_text()
    finally:
        doc.close()
    for needle in (
        "Establishment ID/Name",
        "Member ID/Name",
        "UAN",
        "Particulars",
        "Employee",
        "Employer",
        "Pension",
        "EPF",
        "EPS",
        "Closing Balance",
        "Financial Year",
    ):
        assert needle in text


def test_employer_name_ends_in_a_single_legal_suffix(tmp_path):
    paths = generate(tmp_path, employers=2, years=(2019, 2020), seed=11)
    doc = pymupdf.open(paths[0])
    try:
        line = next(
            line
            for line in doc[0].get_text().splitlines()
            if " / " in line and "PRIVATE" in line
        )
    finally:
        doc.close()
    name = line.split(" / ", 1)[1]
    assert name.endswith("PRIVATE LIMITED")
    assert name.count("PRIVATE LIMITED") == 1
    assert " PLC " not in f" {name} "


def test_one_file_per_employer_year(tmp_path):
    paths = generate(tmp_path, employers=2, years=(2015, 2018), seed=3)
    assert len(paths) == 4
    assert len({p.parent.name for p in paths}) == 2


def test_every_page_is_stamped_as_a_synthetic_sample(tmp_path):
    """The pre-commit hook refuses any PDF without this on every page."""
    paths = generate(tmp_path, employers=2, years=(2015, 2018), seed=3, combined=True)
    for path in paths:
        doc = pymupdf.open(path)
        try:
            for page in doc:
                assert MARKER in page.get_text()
        finally:
            doc.close()


def test_text_extracts_with_ordinary_spaces_and_hyphens(tmp_path):
    """Embedded as a CID font, Calibri reports its space glyph as U+00A0 and
    its hyphen as U+2010, which would leave every label unmatchable."""
    paths = generate(tmp_path, employers=1, years=(2019, 2019), seed=5)
    doc = pymupdf.open(paths[0])
    try:
        words = {w[4] for w in doc[0].get_text("words")}
        text = doc[0].get_text()
    finally:
        doc.close()
    assert "Establishment" in words and "ID/Name" in words
    assert "\u2010" not in text  # a U+2010 hyphen written instead of "-"
    for latin in (
        "Establishment ID/Name",
        "Financial Year - 2019-2020",
        "Closing Balance as on",
        "Cont. for Due-Month",
    ):
        assert latin in text


def test_combined_writes_one_multi_page_pdf_per_employer(tmp_path):
    paths = generate(tmp_path, employers=2, years=(2015, 2020), seed=3, combined=True)
    combined = sorted(p for p in paths if p.parent == tmp_path)
    assert len(combined) == 2

    doc = pymupdf.open(combined[0])
    try:
        years = [
            int(re.search(r"Financial Year - (\d{4})", page.get_text()).group(1))
            for page in doc
        ]
    finally:
        doc.close()
    assert len(years) > 1
    assert years == sorted(years)
    assert len(set(years)) == len(years)


def test_the_banner_is_drawn_on_every_page(tmp_path):
    paths = generate(tmp_path, employers=1, years=(2019, 2020), seed=5, combined=True)
    doc = pymupdf.open(paths[-1])
    try:
        assert all(page.get_images() for page in doc)
    finally:
        doc.close()


def test_english_only_pages_when_no_devanagari_font_is_installed(tmp_path, monkeypatch):
    """CI runners generally have neither Calibri nor a Devanagari face. The
    page must still carry every label the redactor looks for."""
    import sys

    import pymupdf as _pymupdf

    from epfo_redactor.synth import fonts

    # `from .generate import generate` in the package __init__ rebinds the name,
    # so the module itself has to come from sys.modules.
    generate_mod = sys.modules["epfo_redactor.synth.generate"]

    plain = fonts.FaceSet(
        latin=fonts.Face("helv", _pymupdf.Font(fontname="helv"), None),
        bold=fonts.Face("hebo", _pymupdf.Font(fontname="hebo"), None),
        hindi=None,
    )
    monkeypatch.setattr(generate_mod, "load_faces", lambda: plain)

    paths = generate_mod.generate(tmp_path, employers=1, years=(2019, 2019), seed=5)
    doc = pymupdf.open(paths[0])
    try:
        text = doc[0].get_text()
        # The point is not that the labels are printed but that the redactor can
        # still find all five columns from them. This guards the regression CI
        # caught: centring "EPS" in its cell put it nearer the Employee label
        # than its own, and the EPS column silently went undetected.
        columns = set(analyse(doc[0], selected=set(), keep_rows=set()).columns)
    finally:
        doc.close()
    assert columns == {
        COL_EPF_WAGES,
        COL_EPS_WAGES,
        COL_EMPLOYEE,
        COL_EMPLOYER,
        COL_PENSION,
    }
    assert text.isascii()
    for needle in (
        MARKER,
        "Establishment ID/Name",
        "Member ID/Name",
        "UAN",
        "Particulars",
        "Wage Month",
        "Closing Balance",
        "Financial Year",
        "End Of Statement",
    ):
        assert needle in text


def test_a_seed_means_the_same_person_on_any_day():
    """Pinned to literals on purpose.

    The generator used Faker's date_of_birth, which counts back from today, so
    `--seed 42` produced a different member every day -- and the committed
    samples churned in git whenever they were regenerated on a new date. No
    same-process comparison can catch that, because both halves run on the same
    day. Only a literal can.
    """
    from faker import Faker

    for seed, name, uan, dob in (
        (42, "ARYAN MAHARAJ", "115631219101", "02-05-1979"),
        (99, "LAJITA IYENGAR", "153274680169", "25-05-1991"),
    ):
        Faker.seed(seed)
        member = make_member(Faker("en_IN"), random.Random(seed))
        assert (member.name, member.uan, member.dob) == (name, uan, dob)
