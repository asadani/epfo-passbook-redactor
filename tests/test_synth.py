"""The synthetic generator: correct arithmetic, reproducible, and clearly fake."""

from __future__ import annotations

import random

import pymupdf
import pytest

from epfo_redactor.synth.generate import (
    EPS_MAX,
    EPS_WAGE_CEILING,
    Employer,
    _contributions,
    build_years,
    generate,
    inr,
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
