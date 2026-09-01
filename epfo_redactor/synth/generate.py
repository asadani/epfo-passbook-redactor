"""Generate synthetic EPFO member passbooks.

Everything about the *content* here is invented. Names and employers come from
Faker, establishment codes are random letter groups (real EPFO office codes are
a fixed published set, so a random one cannot collide with a real office), and
the money is simulated from the statutory contribution rules rather than copied
from anyone's statement.

Everything about the *shape* is taken from the real template, to the point:
grid coordinates, column right edges, row heights, font sizes, the bilingual
Hindi/English labels, the red "Total Withdrawals" row, the disclaimer block and
the EPFO banner across the top. The redactor has to see the same structure it
would on a genuine passbook, and a reviewer looking at a sample has to
recognise it, which is why the geometry is copied down to the tenth of a point.

Every page is stamped ``SYNTHETIC SAMPLE - NOT A REAL EPFO DOCUMENT`` under the
banner. That line is what ``scripts/check_no_real_pdfs.py`` looks for before it
will let a PDF into the repo, so it is load-bearing -- do not remove it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf

from .fonts import Face, FaceSet, load_faces

# --- statutory constants ------------------------------------------------
EPF_RATE = 0.12
EPS_RATE = 0.0833
EPS_WAGE_CEILING = 15000
EPS_MAX = 1250
INTEREST_RATE = 0.0815

# --- page geometry ------------------------------------------------------
# Every number below was measured off a real 2026-era passbook page. Changing
# one changes what the redactor's column detection is tested against, so treat
# them as observations rather than preferences.
PAGE_W, PAGE_H = 595.0, 842.0

ASSETS = Path(__file__).parent / "assets"
BANNER_FILE = ASSETS / "epfo_banner.png"
BANNER_RECT = pymupdf.Rect(37.8, 27.0, 559.2, 75.0)

MARKER = "SYNTHETIC SAMPLE - NOT A REAL EPFO DOCUMENT"
MARKER_Y = 84.0
MARKER_SIZE = 6.0
MARKER_COLOR = (0.45, 0.45, 0.45)

CENTRE_X = PAGE_W / 2
TITLE_Y = (100.4, 101.0, 102.5)  # hindi 12, slash 12, english 10

RULE_X0, RULE_X1 = 25.0, 568.46
TOP_RULE_Y = 118.0
RULE_SIZE = 8.0

HINDI_X = 27.0
LABEL_X = 113.05
VALUE_X = 256.47
HEADER_SIZE = 10.0
# (hindi baseline anchor, english baseline anchor, hindi label, english label)
HEADER_ROWS = (
    (128.0, 128.5, "स्थापना " "आईडी/नाम", "| Establishment ID/Name"),
    (142.0, 142.5, "सदस्य " "आईडी/नाम", "| Member ID/Name"),
    (156.0, 156.5, "जन्म तिथि", "| Date of Birth"),
    (170.0, 170.5, "यू ए न", "| UAN"),
)

FY_TITLE_Y = (203.0, 203.5, 202.75)

# Vertical grid boundaries. The table is drawn cell by cell, as the real one is.
GRID_X = (
    25.0,
    82.37,
    139.74,
    168.42,
    283.16,
    340.53,
    397.89,
    455.26,
    512.63,
    570.0,
)
TABLE_L, TABLE_R = GRID_X[0], GRID_X[-1]
CELL_PAD = 2.0

# Right edges the numbers align to: the cell boundary less the padding.
X_EPF = GRID_X[5] - CELL_PAD
X_EPS = GRID_X[6] - CELL_PAD
X_EMPLOYEE = GRID_X[7] - CELL_PAD
X_EMPLOYER = GRID_X[8] - CELL_PAD
X_PENSION = GRID_X[9] - CELL_PAD

BAL_HEADER_TOP = 213.0
OB_TOP = 246.0
TXN_HEADER_TOP = 261.0
TXN_HEADER_SPLIT = 279.0
FIRST_ROW_TOP = 306.0
ROW_H = 15.0
TEXT_INSET = 4.25  # span top, measured down from the band top
BODY_SIZE = 9.0
# Every face on the real page sits 3/4 of its size below the top of its
# span. Using one ratio rather than each face's own ascender keeps a
# substitute font on the same baselines as the original.
ASCENT = 0.75

# The whole closing block hangs off the bottom of the table, which moves with
# the number of monthly rows -- a twelve-month year pushes it 90pt down the
# page. Offsets are measured from the top of the End Of Statement line.
FOOTER_GAP = 22.25  # table bottom to the End Of Statement line
DISCLAIMER_OFFSET = (14.35, 26.75)  # Hindi, English
FOOTER_RULE_OFFSET = (38.75, 91.25)
BULLET_OFFSET = (51.5, 65.0, 78.5)
BULLET_SIZE = 9.0
MEMBER_FOOTER_Y = 826.4
PAGE_FOOTER_Y = 827.33
FOOTER_SIZE = 8.0

RED = (1.0, 0.0, 0.0)
BLACK = (0.0, 0.0, 0.0)
GRID_COLOR = (0.0, 0.0, 0.0)
GRID_WIDTH = 0.5

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

DISCLAIMER_HI = (
    "प्रतिख्यान – "
    "उपर दी गई जानका"
    "री केन्द्रीय "
    "सर्वर पर दी गई "
    "जानकारी के आधा"
    "र पर है । यह जान"
    "कारी कानूनी प्"
    "रयोजन के लिए उप"
    "योग नहीं की जा "
    "सकती हैं ।"
)
DISCLAIMER_EN = (
    "Disclaimer - Information shown above is based on available data on central "
    "server.This information may not be use for legal purpose."
)
BULLETS = (
    "* Please never respond to any call for sharing any personal details like "
    "Aadhar, PAN, Bank details, OTP or request for any payment.",
    "* EPFO never calls members/ pensioners to deposit any amount.",
    "* Please do not make any payment based on any such call.",
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

    @property
    def prefix(self) -> str:
        """The 5-letter regional office code the outputs are labelled with."""
        return self.establishment_id[:5]


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


class Sheet:
    """A page plus the fonts to write on it.

    Coordinates passed in are the *top* of the text, which is how the real
    document was measured; the baseline is worked out from the face's own
    ascender so a substitute font still lines up with the grid.
    """

    def __init__(self, page: pymupdf.Page, faces: FaceSet) -> None:
        self.page = page
        self.faces = faces
        faces.register(page)

    def draw(
        self,
        x: float,
        top: float,
        text: str,
        face: Face,
        size: float,
        color: tuple = BLACK,
        align: str = "left",
        max_width: float | None = None,
    ) -> float:
        """Write ``text`` and return the width it took."""
        if not text:
            return 0.0
        size = face.fitted_size(text, size, max_width)
        width = face.width(text, size)
        if align == "right":
            x -= width
        elif align == "centre":
            x -= width / 2
        self.page.insert_text(
            (x, top + ASCENT * size),
            text,
            fontname=face.alias,
            fontsize=size,
            color=color,
        )
        return width

    def run(
        self,
        x: float,
        pieces,
        centre: float | None = None,
        max_width: float | None = None,
    ) -> None:
        """Lay out ``(face, size, top, text)`` pieces side by side.

        Used for every line the real template sets as a bilingual run -- the
        title, the financial-year heading, the column headings, the
        end-of-statement line -- where the Hindi and English halves sit on
        slightly different baselines. Laying them out in sequence rather than
        at the coordinates measured off the real page matters: Devanagari set
        in Nirmala is wider than the same words in Kruti Dev, so the fixed
        positions would collide.
        """
        pieces = [p for p in pieces if p[0] is not None and p[3]]
        if not pieces:
            return
        total = sum(face.width(text, size) for face, size, _, text in pieces)
        if max_width is not None and total > max_width > 0:
            scale = max(max_width / total, 0.55)
            pieces = [(f, s * scale, top, t) for f, s, top, t in pieces]
            total = sum(face.width(text, size) for face, size, _, text in pieces)
        if centre is not None:
            x = centre - total / 2
        for face, size, top, text in pieces:
            x += self.draw(x, top, text, face, size)

    def cells(self, top: float, bottom: float, xs) -> None:
        """Stroke one row of cells, the way the real template draws its grid."""
        shape = self.page.new_shape()
        for left, right in zip(xs, xs[1:]):
            shape.draw_rect(pymupdf.Rect(left, top, right, bottom))
        shape.finish(color=GRID_COLOR, width=GRID_WIDTH)
        shape.commit()


def _bilingual(
    sheet: Sheet,
    x: float,
    hindi: tuple[float, str],
    english: tuple[float, str],
    size: float,
    face: Face,
    max_width: float | None = None,
) -> None:
    """A left-aligned label in both scripts, English alone if there is no
    Devanagari face."""
    hy, htext = hindi
    ey, etext = english
    if sheet.faces.hindi is None:
        sheet.draw(x, ey, etext.lstrip("/ ").strip(), face, size, max_width=max_width)
        return
    sheet.run(
        x,
        ((sheet.faces.hindi, size, hy, htext), (face, size, ey, etext)),
        max_width=max_width,
    )


def _balance_head(sheet: Sheet, right: float, hindi: str, english: str) -> None:
    """One right-aligned '<x> Balance' column heading."""
    room = GRID_X[7] - GRID_X[6] - 2 * CELL_PAD
    if sheet.faces.hindi is not None:
        sheet.draw(
            right,
            216.8,
            hindi,
            sheet.faces.hindi,
            BODY_SIZE,
            align="right",
            max_width=room,
        )
    sheet.draw(right, 226.25, english, sheet.faces.bold, BODY_SIZE, align="right")
    sheet.draw(right, 235.25, "Balance", sheet.faces.bold, BODY_SIZE, align="right")


# Transaction-table headings, each centred in the cell it spans:
# (first grid line, last grid line, Hindi top, English top, Hindi, English).
# Where the two tops coincide the label reads as one run across the cell;
# where they differ the real template stacks the scripts on two lines.
TXN_HEADINGS = (
    (0, 1, 276.8, 286.25, "वेतन माह  /", "Wage Month"),
    (1, 3, 267.8, 268.25, "ट्रांसक्शन", "/ Transaction"),
    (3, 4, 281.3, 281.75, "विवरण", "/ Particulars"),
    (4, 6, 267.8, 268.25, "वेतन", "/ Wages"),
    (6, 9, 267.8, 268.25, "अंशदान", "/ Contribution"),
    (1, 2, 290.3, 290.75, "दिनांक", "/ Date"),
    (2, 3, 284.3, 293.75, "प्रकार", "/ Type"),
    (4, 5, 290.3, 290.75, "ई पी एफ", "/ EPF"),
    (5, 6, 290.3, 290.75, "ई पी एस", "/ EPS"),
    (6, 7, 285.8, 295.25, "कर्मचारी  /", "Employee"),
    (7, 8, 285.8, 295.25, "नियोक्ता  /", "Employer"),
    (8, 9, 285.8, 295.25, "पेंशन  /", "Pension"),
)

BALANCE_HEADS = (
    (X_EMPLOYEE, "कर्मचारी शेष /", "Employee"),
    (X_EMPLOYER, "नियोक्ता शेष /", "Employer"),
    (X_PENSION, "पेंशन शेष /", "Pension"),
)


def _txn_heading(
    sheet: Sheet,
    left: int,
    right: int,
    hindi_top: float,
    english_top: float,
    hindi: str,
    english: str,
) -> None:
    """One column heading, centred in its cell as the real template centres it."""
    cell_left, cell_right = GRID_X[left], GRID_X[right]
    centre = (cell_left + cell_right) / 2
    room = cell_right - cell_left - 2 * CELL_PAD
    face = sheet.faces.bold
    if sheet.faces.hindi is None:
        sheet.draw(
            centre,
            english_top,
            english.lstrip("/ ").strip(),
            face,
            BODY_SIZE,
            align="centre",
            max_width=room,
        )
    elif abs(hindi_top - english_top) < 4.0:
        sheet.run(
            0.0,
            (
                (sheet.faces.hindi, BODY_SIZE, hindi_top, hindi + "  "),
                (face, BODY_SIZE, english_top, english),
            ),
            centre=centre,
            max_width=room,
        )
    else:
        sheet.draw(
            centre,
            hindi_top,
            hindi,
            sheet.faces.hindi,
            BODY_SIZE,
            align="centre",
            max_width=room,
        )
        sheet.draw(
            centre,
            english_top,
            english.lstrip("/ ").strip(),
            face,
            BODY_SIZE,
            align="centre",
            max_width=room,
        )


def _banner(sheet: Sheet) -> None:
    """The EPFO letterhead across the top, plus the synthetic-sample stamp."""
    if BANNER_FILE.is_file():
        sheet.page.insert_image(BANNER_RECT, filename=str(BANNER_FILE))
    sheet.draw(
        CENTRE_X,
        MARKER_Y,
        MARKER,
        sheet.faces.latin,
        MARKER_SIZE,
        color=MARKER_COLOR,
        align="centre",
    )


def _rule(sheet: Sheet, top: float) -> None:
    """The real template rules its page with a run of hyphens, not a line."""
    face = sheet.faces.latin
    unit = face.width("-", RULE_SIZE) or 1.0
    count = max(1, int((RULE_X1 - RULE_X0) / unit))
    sheet.draw(RULE_X0, top, "-" * count, face, RULE_SIZE)


def _identity_block(sheet: Sheet, member: Member, employer: Employer) -> None:
    values = (
        f"{employer.establishment_id} / {employer.name}",
        f"{employer.member_id} / {member.name}",
        member.dob,
        member.uan,
    )
    for (hy, ey, hindi, english), value in zip(HEADER_ROWS, values):
        if sheet.faces.hindi is not None:
            sheet.draw(
                HINDI_X,
                hy,
                hindi,
                sheet.faces.hindi,
                HEADER_SIZE,
                max_width=LABEL_X - HINDI_X - CELL_PAD,
            )
            sheet.draw(LABEL_X, ey, english, sheet.faces.latin, HEADER_SIZE)
        else:
            sheet.draw(HINDI_X, ey, english, sheet.faces.latin, HEADER_SIZE)
        sheet.draw(VALUE_X, ey, value, sheet.faces.latin, HEADER_SIZE)


def _summary_rows(sheet: Sheet, sheet_data: YearSheet, top: float) -> float:
    """The three 'Total ...' rows. Withdrawals is red on the real page."""
    fy = sheet_data.fiscal_year
    entries = (
        (
            f"Total Contributions for the year [ {fy} ]",
            sheet_data.total_employee,
            sheet_data.total_employer,
            sheet_data.total_pension,
            BLACK,
        ),
        (f"Total Transfer-Ins/VDRs for the year [ {fy} ]", 0, 0, 0, BLACK),
        (f"Total Withdrawals  for the year [ {fy} ]", 0, 0, 0, RED),
    )
    for label, ee, er, ps, color in entries:
        text_top = top + TEXT_INSET
        sheet.draw(
            X_EPS, text_top, label, sheet.faces.bold, BODY_SIZE, color, align="right"
        )
        for x, value in ((X_EMPLOYEE, ee), (X_EMPLOYER, er), (X_PENSION, ps)):
            sheet.draw(
                x,
                text_top,
                inr(value),
                sheet.faces.bold,
                BODY_SIZE,
                color,
                align="right",
            )
        sheet.cells(
            top, top + ROW_H, (GRID_X[0], GRID_X[6], GRID_X[7], GRID_X[8], GRID_X[9])
        )
        top += ROW_H
    return top


def _wide_row(
    sheet: Sheet,
    top: float,
    label: str,
    values: tuple[int, int, int],
    face: Face,
) -> float:
    """A full-width label row: the opening balance, interest, closing balance."""
    text_top = top + TEXT_INSET
    sheet.draw(GRID_X[0] + CELL_PAD, text_top, label, face, BODY_SIZE)
    for x, value in zip((X_EMPLOYEE, X_EMPLOYER, X_PENSION), values):
        sheet.draw(x, text_top, inr(value), face, BODY_SIZE, align="right")
    sheet.cells(
        top, top + ROW_H, (GRID_X[0], GRID_X[6], GRID_X[7], GRID_X[8], GRID_X[9])
    )
    return top + ROW_H


def render_page(
    doc: pymupdf.Document,
    member: Member,
    employer: Employer,
    sheet_data: YearSheet,
    faces: FaceSet | None = None,
) -> pymupdf.Page:
    """Draw one financial year as one page."""
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    sheet = Sheet(page, faces or load_faces())
    latin, bold, hindi = sheet.faces.latin, sheet.faces.bold, sheet.faces.hindi
    fy = sheet_data.fiscal_year

    _banner(sheet)
    sheet.run(
        0.0,
        (
            (hindi, 12.0, TITLE_Y[0], "सदस्य " "पासबुक"),
            (latin, 12.0, TITLE_Y[1], " / " if hindi else ""),
            (bold, HEADER_SIZE, TITLE_Y[2], "Member Passbook"),
        ),
        centre=CENTRE_X,
    )
    _rule(sheet, TOP_RULE_Y)
    _identity_block(sheet, member, employer)

    span = f"{fy}-{fy + 1}"
    sheet.run(
        0.0,
        (
            (hindi, HEADER_SIZE, FY_TITLE_Y[0], "ईपीएफ पासबुक  "),
            (latin, HEADER_SIZE, FY_TITLE_Y[1], "[ " if hindi else ""),
            (hindi, HEADER_SIZE, FY_TITLE_Y[0], "वित्तीय वर्ष"),
            (latin, HEADER_SIZE, FY_TITLE_Y[1], f" - {span} ] / " if hindi else ""),
            (bold, 11.0, FY_TITLE_Y[2], f"EPF Passbook [ Financial Year - {span} ]"),
        ),
        centre=CENTRE_X,
    )

    # Balance header block, then the opening-balance row.
    _bilingual(
        sheet,
        HINDI_X,
        (225.8, "विवरण"),
        (226.25, "/ Particulars"),
        BODY_SIZE,
        bold,
    )
    for right, hindi_label, english in BALANCE_HEADS:
        _balance_head(sheet, right, hindi_label, english)
    sheet.cells(
        BAL_HEADER_TOP,
        OB_TOP,
        (GRID_X[0], GRID_X[6], GRID_X[7], GRID_X[8], GRID_X[9]),
    )
    _wide_row(
        sheet,
        OB_TOP,
        f"OB Int. Updated upto 31/03/{fy}",
        (
            sheet_data.open_employee,
            sheet_data.open_employer,
            sheet_data.open_pension,
        ),
        latin,
    )

    # Transaction header: two bands of merged cells above the monthly rows.
    for heading in TXN_HEADINGS:
        _txn_heading(sheet, *heading)
    sheet.cells(TXN_HEADER_TOP, TXN_HEADER_SPLIT, (GRID_X[1], GRID_X[3]))
    sheet.cells(TXN_HEADER_TOP, TXN_HEADER_SPLIT, (GRID_X[4], GRID_X[6], GRID_X[9]))
    sheet.cells(TXN_HEADER_TOP, FIRST_ROW_TOP, (GRID_X[0], GRID_X[1]))
    sheet.cells(TXN_HEADER_TOP, FIRST_ROW_TOP, (GRID_X[3], GRID_X[4]))
    sheet.cells(
        TXN_HEADER_SPLIT,
        FIRST_ROW_TOP,
        (GRID_X[1], GRID_X[2], GRID_X[3]),
    )
    sheet.cells(
        TXN_HEADER_SPLIT,
        FIRST_ROW_TOP,
        (GRID_X[4], GRID_X[5], GRID_X[6], GRID_X[7], GRID_X[8], GRID_X[9]),
    )

    top = FIRST_ROW_TOP
    for row in sheet_data.rows:
        text_top = top + TEXT_INSET
        sheet.draw(
            GRID_X[1] - CELL_PAD, text_top, row.month, latin, BODY_SIZE, align="right"
        )
        sheet.draw(GRID_X[1] + CELL_PAD, text_top, row.posted, latin, BODY_SIZE)
        sheet.draw(GRID_X[2] + CELL_PAD, text_top, "CR", latin, BODY_SIZE)
        sheet.draw(
            GRID_X[3] + CELL_PAD,
            text_top,
            f"Cont. for Due-Month {row.due}",
            latin,
            BODY_SIZE,
        )
        for x, value in (
            (X_EPF, row.epf_wage),
            (X_EPS, row.eps_wage),
            (X_EMPLOYEE, row.employee),
            (X_EMPLOYER, row.employer),
            (X_PENSION, row.pension),
        ):
            sheet.draw(x, text_top, inr(value), latin, BODY_SIZE, align="right")
        sheet.cells(top, top + ROW_H, GRID_X)
        top += ROW_H

    top = _summary_rows(sheet, sheet_data, top)
    top = _wide_row(
        sheet,
        top,
        f"Int. Updated upto 31/03/{fy + 1}",
        (
            sheet_data.int_employee,
            sheet_data.int_employer,
            sheet_data.int_pension,
        ),
        latin,
    )
    top = _wide_row(
        sheet,
        top,
        f"Closing Balance as on 31/03/{fy + 1}",
        (
            sheet_data.close_employee,
            sheet_data.close_employer,
            sheet_data.close_pension,
        ),
        bold,
    )

    # The Hindi half of these two runs carries the separating slash, so the
    # English half loses its leading one when there is no Devanagari face.
    slash = "/" if hindi is not None else ""
    end_top = top + FOOTER_GAP
    sheet.run(
        90.28,
        (
            (latin, BODY_SIZE, end_top + 0.45, "-" * 22),
            (hindi, BODY_SIZE, end_top, "विवरण " "की समाप्ति"),
            (latin, BODY_SIZE, end_top + 0.45, slash + "End Of Statement" + "-" * 22),
        ),
    )
    sheet.run(
        435.79,
        (
            (hindi, BODY_SIZE, end_top, "मुद्रित"),
            (latin, BODY_SIZE, end_top + 0.45, slash + "Printed On : "),
            (latin, FOOTER_SIZE, end_top + 1.2, "01-01-2026 00:00:00"),
        ),
    )

    if hindi is not None:
        sheet.draw(
            RULE_X0,
            end_top + DISCLAIMER_OFFSET[0],
            DISCLAIMER_HI,
            hindi,
            RULE_SIZE,
        )
    sheet.draw(RULE_X0, end_top + DISCLAIMER_OFFSET[1], DISCLAIMER_EN, latin, RULE_SIZE)
    _rule(sheet, end_top + FOOTER_RULE_OFFSET[0])
    for offset, text in zip(BULLET_OFFSET, BULLETS):
        sheet.draw(RULE_X0, end_top + offset, text, latin, BULLET_SIZE)
    _rule(sheet, end_top + FOOTER_RULE_OFFSET[1])

    sheet.draw(HINDI_X, MEMBER_FOOTER_Y, employer.member_id, latin, FOOTER_SIZE)
    sheet.draw(TABLE_R, PAGE_FOOTER_Y, "Page 1 of 1", latin, FOOTER_SIZE, align="right")
    return page


# --- assembly -----------------------------------------------------------

METADATA = {
    "title": "EPF Member Passbook",
    "author": "EPFO",
    "subject": "Synthetic sample - not a real passbook",
    "keywords": "synthetic",
    "creator": "epfo-passbook-redactor",
    "producer": "epfo-passbook-redactor",
}


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


def _save(doc: pymupdf.Document, dest: Path) -> Path:
    doc.set_metadata(dict(METADATA))
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        # An embedded font goes in whole, and Nirmala UI alone is 2.4MB -- more
        # than the sample tree can carry, and far more than a real passbook,
        # which embeds a subset. Subsetting brings a page back under 60KB.
        doc.subset_fonts()
    except Exception:  # pragma: no cover - older PyMuPDF, or an odd face
        pass
    doc.save(dest, garbage=4, deflate=True)
    return dest


def generate(
    out_dir: Path,
    employers: int = 2,
    years: tuple[int, int] = (2015, 2021),
    seed: int | None = None,
    locale: str = "en_IN",
    combined: bool = False,
) -> list[Path]:
    """Write synthetic passbooks and return the paths.

    Two shapes, because both turn up in practice. One PDF per financial year in
    ``<out_dir>/<PREFIX>/`` is what you get downloading a year at a time; a
    single multi-page PDF per employer at ``<out_dir>/`` is what the portal
    hands over when you ask for the whole account, one financial year per page.
    ``combined`` adds the second shape alongside the first.
    """
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

    faces = load_faces()
    member = make_member(fake, rng)
    written: list[Path] = []

    for employer in make_employers(fake, rng, employers, years):
        folder = out_dir / employer.prefix
        sheets = build_years(employer, rng)
        for sheet_data in sheets:
            doc = pymupdf.open()
            try:
                render_page(doc, member, employer, sheet_data, faces)
                written.append(
                    _save(
                        doc,
                        folder / f"{employer.member_id}_{sheet_data.fiscal_year}.pdf",
                    )
                )
            finally:
                doc.close()

        if combined and sheets:
            doc = pymupdf.open()
            try:
                for sheet_data in sheets:
                    render_page(doc, member, employer, sheet_data, faces)
                span = f"{sheets[0].fiscal_year}-{sheets[-1].fiscal_year}"
                written.append(
                    _save(
                        doc,
                        out_dir / f"EPFO_Passbook_{employer.prefix}_FY{span}.pdf",
                    )
                )
            finally:
                doc.close()
    return written


def today_year() -> int:
    return date.today().year
