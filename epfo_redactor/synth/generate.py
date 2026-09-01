"""Generate synthetic EPFO member passbooks.

Everything here is invented. Names and employers come from Faker, establishment
codes are random letter groups (real EPFO office codes are a fixed published
set, so a random one cannot collide with a real office), and the money is
simulated from the statutory contribution rules rather than copied from anyone's
statement.

The page geometry mirrors the real template closely enough that the redactor
sees the same structure it would on a genuine passbook -- which is the point:
the tool can be demonstrated and regression-tested with no real data anywhere
near it. Labels are English only; the real document also prints Hindi in a
legacy non-Unicode font, which we deliberately do not reproduce.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf

# --- statutory constants ------------------------------------------------
EPF_RATE = 0.12
EPS_RATE = 0.0833
EPS_WAGE_CEILING = 15000
EPS_MAX = 1250
INTEREST_RATE = 0.0815

# --- page geometry (A4, matching the real template) ---------------------
PAGE_W, PAGE_H = 595.0, 842.0
LABEL_X = 119.9
VALUE_X = 256.5
HEADER_Y = (128.5, 142.5, 156.5, 170.5)
FY_TITLE_Y = 202.8
PARTICULARS_Y = 226.3
BALANCE_WORD_Y = 235.3
OB_Y = 250.3
TXN_GROUP_Y = 268.3
TXN_SUB_Y = 290.8
TXN_NAME_Y = 295.3
FIRST_ROW_Y = 310.3
ROW_H = 15.0
FOOTER_Y = 583.3
DISCLAIMER_Y = 610.0
MEMBER_FOOTER_Y = 826.4

GRID_X = (25.0, 82.0, 135.0, 170.0, 283.0, 342.0, 400.0, 458.0, 515.0, 571.0)
TABLE_L, TABLE_R = GRID_X[0], GRID_X[-1]

# Right edges the numbers align to.
X_EPF = 338.5
X_EPS = 395.9
X_EMPLOYEE = 453.3
X_EMPLOYER = 510.6
X_PENSION = 568.0

FONT = "helv"
FONT_BOLD = "hebo"
SIZE = 7.0
SIZE_LABEL = 7.5

MONTHS = (
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
    "Jan",
    "Feb",
    "Mar",
)

# Faker appends its own English company suffix; we want an Indian one.
FAKER_SUFFIXES = (
    "PLC",
    "LTD",
    "LTD.",
    "LLC",
    "INC",
    "INC.",
    "GROUP",
    "AND SONS",
    "LIMITED",
)


def inr(value: int | float) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567."""
    n = int(round(value))
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


@dataclass
class Member:
    """The synthetic person a set of passbooks belongs to."""

    name: str
    uan: str
    dob: str


@dataclass
class Employer:
    """One synthetic employer and the member's account with it."""

    name: str
    establishment_id: str
    member_id: str
    start_year: int
    end_year: int
    monthly_wage: int
    annual_hike: float = 0.08


@dataclass
class YearRow:
    month: str
    posted: str
    due: str
    epf_wage: int
    eps_wage: int
    employee: int
    employer: int
    pension: int


@dataclass
class YearSheet:
    """One financial year of one employer's passbook."""

    fiscal_year: int
    rows: list[YearRow] = field(default_factory=list)
    open_employee: int = 0
    open_employer: int = 0
    open_pension: int = 0
    int_employee: int = 0
    int_employer: int = 0
    int_pension: int = 0

    @property
    def total_employee(self) -> int:
        return sum(r.employee for r in self.rows)

    @property
    def total_employer(self) -> int:
        return sum(r.employer for r in self.rows)

    @property
    def total_pension(self) -> int:
        return sum(r.pension for r in self.rows)

    @property
    def close_employee(self) -> int:
        return self.open_employee + self.total_employee + self.int_employee

    @property
    def close_employer(self) -> int:
        return self.open_employer + self.total_employer + self.int_employer

    @property
    def close_pension(self) -> int:
        return self.open_pension + self.total_pension + self.int_pension


def _contributions(wage: int) -> tuple[int, int, int]:
    """(employee EPF, employer EPF, EPS) for one month at this wage."""
    employee = round(wage * EPF_RATE)
    pension = min(round(min(wage, EPS_WAGE_CEILING) * EPS_RATE), EPS_MAX)
    return employee, employee - pension, pension


def build_years(employer: Employer, rng: random.Random) -> list[YearSheet]:
    """Simulate every financial year of one employment, balances carried over."""
    sheets: list[YearSheet] = []
    wage = employer.monthly_wage
    bal_ee = bal_er = bal_ps = 0

    for fy in range(employer.start_year, employer.end_year + 1):
        sheet = YearSheet(
            fiscal_year=fy,
            open_employee=bal_ee,
            open_employer=bal_er,
            open_pension=bal_ps,
        )
        # A joining or leaving year is usually partial.
        first = rng.randint(4, 9) if fy == employer.start_year else 0
        last = rng.randint(6, 11) if fy == employer.end_year else 11

        for idx in range(first, last + 1):
            month = MONTHS[idx]
            wage_year = fy if idx < 9 else fy + 1
            post_month = idx + 5 if idx < 8 else idx - 7
            post_year = fy if idx < 8 else fy + 1
            employee, er, pension = _contributions(wage)
            sheet.rows.append(
                YearRow(
                    month=f"{month}-{wage_year}",
                    posted=f"01-{post_month:02d}-{post_year}",
                    due=f"{post_month:02d}{post_year}",
                    epf_wage=wage,
                    eps_wage=min(wage, EPS_WAGE_CEILING),
                    employee=employee,
                    employer=er,
                    pension=pension,
                )
            )

        # Interest on opening balance plus roughly half a year of contributions.
        sheet.int_employee = round(
            (sheet.open_employee + sheet.total_employee / 2) * INTEREST_RATE
        )
        sheet.int_employer = round(
            (sheet.open_employer + sheet.total_employer / 2) * INTEREST_RATE
        )
        sheet.int_pension = 0  # EPS earns no credited interest in the passbook.

        bal_ee, bal_er, bal_ps = (
            sheet.close_employee,
            sheet.close_employer,
            sheet.close_pension,
        )
        sheets.append(sheet)
        wage = int(wage * (1 + employer.annual_hike))
    return sheets


# --- drawing ------------------------------------------------------------


def _right(
    page: pymupdf.Page, x: float, y: float, text: str, bold: bool = False
) -> None:
    font = FONT_BOLD if bold else FONT
    width = pymupdf.get_text_length(text, fontname=font, fontsize=SIZE)
    page.insert_text((x - width, y), text, fontname=font, fontsize=SIZE)


def _left(
    page: pymupdf.Page, x: float, y: float, text: str, bold: bool = False, size=SIZE
) -> None:
    page.insert_text((x, y), text, fontname=FONT_BOLD if bold else FONT, fontsize=size)


def _centre(page: pymupdf.Page, y: float, text: str, bold: bool = True) -> None:
    font = FONT_BOLD if bold else FONT
    width = pymupdf.get_text_length(text, fontname=font, fontsize=SIZE_LABEL)
    page.insert_text(
        ((PAGE_W - width) / 2, y), text, fontname=font, fontsize=SIZE_LABEL
    )


def _rule(page: pymupdf.Page, y: float) -> None:
    shape = page.new_shape()
    shape.draw_line(pymupdf.Point(TABLE_L, y), pymupdf.Point(PAGE_W - 27, y))
    shape.finish(color=(0.4, 0.4, 0.4), width=0.4, dashes="[1 1] 0")
    shape.commit()


def _table_frame(page: pymupdf.Page, top: float, bottom: float, splits) -> None:
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(TABLE_L, top, TABLE_R, bottom))
    for y in splits:
        shape.draw_line(pymupdf.Point(TABLE_L, y), pymupdf.Point(TABLE_R, y))
    shape.finish(color=(0.55, 0.55, 0.55), width=0.5)
    shape.commit()


def _verticals(page: pymupdf.Page, top: float, bottom: float, xs) -> None:
    shape = page.new_shape()
    for x in xs:
        shape.draw_line(pymupdf.Point(x, top), pymupdf.Point(x, bottom))
    shape.finish(color=(0.55, 0.55, 0.55), width=0.5)
    shape.commit()


def render_page(
    doc: pymupdf.Document, member: Member, employer: Employer, sheet: YearSheet
) -> None:
    """Draw one financial year as one page."""
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    _centre(page, 102.5, "Member Passbook")
    _rule(page, 118.0)

    rows = (
        ("| Establishment ID/Name", f"{employer.establishment_id} / {employer.name}"),
        ("| Member ID/Name", f"{employer.member_id} / {member.name}"),
        ("| Date of Birth", member.dob),
        ("| UAN", member.uan),
    )
    for y, (label, value) in zip(HEADER_Y, rows):
        _left(page, LABEL_X, y, label, size=SIZE_LABEL)
        _left(page, VALUE_X, y, value, size=SIZE_LABEL)

    fy = sheet.fiscal_year
    _centre(page, FY_TITLE_Y, f"EPF Passbook [ Financial Year - {fy}-{fy + 1} ]")

    # Balance header, then the opening-balance row.
    _left(page, TABLE_L + 2, PARTICULARS_Y, "Particulars", bold=True)
    for x, word in (
        (X_EMPLOYEE, "Employee"),
        (X_EMPLOYER, "Employer"),
        (X_PENSION, "Pension"),
    ):
        _right(page, x, PARTICULARS_Y, word, bold=True)
        _right(page, x, BALANCE_WORD_Y, "Balance", bold=True)

    _left(page, TABLE_L + 2, OB_Y, f"OB Int. Updated upto 31/03/{fy}")
    _right(page, X_EMPLOYEE, OB_Y, inr(sheet.open_employee))
    _right(page, X_EMPLOYER, OB_Y, inr(sheet.open_employer))
    _right(page, X_PENSION, OB_Y, inr(sheet.open_pension))

    # Transaction header.
    _left(page, 85.0, TXN_GROUP_Y, "Transaction", bold=True)
    _left(page, 315.0, TXN_GROUP_Y, "Wages", bold=True)
    _left(page, 443.0, TXN_GROUP_Y, "Contribution", bold=True)
    _left(page, 29.7, TXN_NAME_Y, "Wage Month", bold=True)
    _left(page, 86.0, TXN_SUB_Y, "Date", bold=True)
    _left(page, 142.5, TXN_NAME_Y, "Type", bold=True)
    _left(page, 192.8, TXN_SUB_Y, "Particulars", bold=True)
    _right(page, X_EPF, TXN_SUB_Y, "EPF", bold=True)
    _right(page, X_EPS, TXN_SUB_Y, "EPS", bold=True)
    _right(page, X_EMPLOYEE, TXN_NAME_Y, "Employee", bold=True)
    _right(page, X_EMPLOYER, TXN_NAME_Y, "Employer", bold=True)
    _right(page, X_PENSION, TXN_NAME_Y, "Pension", bold=True)

    y = FIRST_ROW_Y
    for row in sheet.rows:
        _left(page, 44.0, y, row.month)
        _left(page, 84.4, y, row.posted)
        _left(page, 141.7, y, "CR")
        _left(page, 170.4, y, f"Cont. for Due-Month {row.due}")
        _right(page, X_EPF, y, inr(row.epf_wage))
        _right(page, X_EPS, y, inr(row.eps_wage))
        _right(page, X_EMPLOYEE, y, inr(row.employee))
        _right(page, X_EMPLOYER, y, inr(row.employer))
        _right(page, X_PENSION, y, inr(row.pension))
        y += ROW_H

    summary_top = y - 11.0
    for label, ee, er, ps, bold in (
        (
            f"Total Contributions for the year [ {fy} ]",
            sheet.total_employee,
            sheet.total_employer,
            sheet.total_pension,
            True,
        ),
        (f"Total Transfer-Ins/VDRs for the year [ {fy} ]", 0, 0, 0, False),
        (f"Total Withdrawals  for the year [ {fy} ]", 0, 0, 0, False),
    ):
        width = pymupdf.get_text_length(
            label, fontname=FONT_BOLD if bold else FONT, fontsize=SIZE
        )
        _left(page, GRID_X[6] - 5 - width, y, label, bold=bold)
        _right(page, X_EMPLOYEE, y, inr(ee), bold=bold)
        _right(page, X_EMPLOYER, y, inr(er), bold=bold)
        _right(page, X_PENSION, y, inr(ps), bold=bold)
        y += ROW_H

    _left(page, TABLE_L + 2, y, f"Int. Updated upto 31/03/{fy + 1}")
    _right(page, X_EMPLOYEE, y, inr(sheet.int_employee))
    _right(page, X_EMPLOYER, y, inr(sheet.int_employer))
    _right(page, X_PENSION, y, inr(sheet.int_pension))
    y += ROW_H

    _left(page, TABLE_L + 2, y, f"Closing Balance as on 31/03/{fy + 1}", bold=True)
    _right(page, X_EMPLOYEE, y, inr(sheet.close_employee), bold=True)
    _right(page, X_EMPLOYER, y, inr(sheet.close_employer), bold=True)
    _right(page, X_PENSION, y, inr(sheet.close_pension), bold=True)
    table_bottom = y + 5.0

    _table_frame(
        page,
        PARTICULARS_Y - 10.0,
        table_bottom,
        (OB_Y - 10.0, OB_Y + 5.0, FIRST_ROW_Y - 10.0, summary_top),
    )
    _verticals(page, PARTICULARS_Y - 10.0, table_bottom, GRID_X[7:9])
    _verticals(page, FIRST_ROW_Y - 10.0, summary_top, GRID_X[1:7])
    _verticals(page, OB_Y + 5.0, FIRST_ROW_Y - 10.0, GRID_X[1:7])

    _centre(
        page,
        FOOTER_Y,
        "----------------------End Of Statement----------------------",
        bold=False,
    )
    _right(page, PAGE_W - 27, FOOTER_Y, "Printed On : 01-01-2026 00:00:00")
    _rule(page, 597.0)
    _left(
        page,
        TABLE_L,
        DISCLAIMER_Y,
        "Disclaimer - Information shown above is based on available data on central "
        "server.This information may not be use for legal purpose.",
    )
    _left(
        page,
        TABLE_L,
        DISCLAIMER_Y + 24,
        "* Please never respond to any call for sharing any personal details like "
        "Aadhar, PAN, Bank details, OTP or request for any payment.",
    )
    _left(
        page,
        TABLE_L,
        DISCLAIMER_Y + 37,
        "* EPFO never calls members/ pensioners to deposit any amount.",
    )
    _left(page, 27.0, MEMBER_FOOTER_Y, employer.member_id)
    _right(page, PAGE_W - 25, MEMBER_FOOTER_Y, "Page 1 of 1")


# --- assembly -----------------------------------------------------------


def _establishment_code(rng: random.Random) -> str:
    """A random 5-letter code.

    Real EPFO office codes are a fixed published set, so a random draw is
    overwhelmingly unlikely to name a real office, and never names a real one
    deliberately.
    """
    return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))


def _company(fake) -> str:
    """A company name that ends in PRIVATE LIMITED and not much else."""
    name = fake.company().upper().replace(",", "")
    changed = True
    while changed:
        changed = False
        for suffix in FAKER_SUFFIXES:
            if name.endswith(" " + suffix):
                name = name[: -len(suffix) - 1].strip()
                changed = True
    return f"{name} PRIVATE LIMITED"


def make_member(fake, rng: random.Random) -> Member:
    return Member(
        name=fake.name().upper(),
        uan=str(rng.randint(100000000000, 199999999999)),
        dob=fake.date_of_birth(minimum_age=25, maximum_age=55).strftime("%d-%m-%Y"),
    )


def make_employers(fake, rng: random.Random, count: int, years: tuple[int, int]):
    """Consecutive employments spanning the requested year range."""
    start, end = years
    total = end - start + 1
    per = max(1, total // count)
    employers = []
    cursor = start
    for i in range(count):
        last = end if i == count - 1 else min(end, cursor + per - 1)
        code = _establishment_code(rng)
        est_id = f"{code}{rng.randint(10 ** 9, 10 ** 10 - 1)}"
        employers.append(
            Employer(
                name=_company(fake),
                establishment_id=est_id,
                member_id=f"{est_id}{rng.randint(1, 9999999):07d}",
                start_year=cursor,
                end_year=last,
                monthly_wage=rng.randrange(18000, 95000, 500),
            )
        )
        cursor = last + 1
        if cursor > end:
            break
    return employers


def generate(
    out_dir: Path,
    employers: int = 2,
    years: tuple[int, int] = (2015, 2021),
    seed: int | None = None,
    locale: str = "en_IN",
) -> list[Path]:
    """Write one PDF per employer per financial year. Returns the paths."""
    try:
        from faker import Faker
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit(
            "the synthetic generator needs Faker: "
            "pip install 'epfo-passbook-redactor[synth]'"
        ) from exc

    rng = random.Random(seed)
    fake = Faker(locale)
    if seed is not None:
        Faker.seed(seed)

    member = make_member(fake, rng)
    written: list[Path] = []

    for employer in make_employers(fake, rng, employers, years):
        folder = out_dir / employer.establishment_id[:5]
        folder.mkdir(parents=True, exist_ok=True)
        for sheet in build_years(employer, rng):
            doc = pymupdf.open()
            try:
                render_page(doc, member, employer, sheet)
                doc.set_metadata(
                    {
                        "title": "EPF Member Passbook",
                        "author": "EPFO",
                        "subject": "Synthetic sample - not a real passbook",
                        "keywords": "synthetic",
                        "creator": "epfo-passbook-redactor",
                        "producer": "epfo-passbook-redactor",
                    }
                )
                dest = folder / f"{employer.member_id}_{sheet.fiscal_year}.pdf"
                doc.save(dest, garbage=4, deflate=True)
                written.append(dest)
            finally:
                doc.close()
    return written


def today_year() -> int:
    return date.today().year
