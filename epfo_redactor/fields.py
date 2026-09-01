"""What can be redacted, and which profile turns it on.

A *field* is one redactable thing on the passbook. Identity fields live in the
header block; financial fields are whole table columns, and are named after the
column header labels EPFO prints (``Wages / EPF``, ``Contribution / Employee``,
and so on).

The default profile deliberately leaves every Employee Pension Scheme figure
readable. EPS wages are capped at the statutory ceiling and the pension
contribution derives from that ceiling, so neither reveals an actual salary --
while EPF wages and EPF contributions reveal it exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

IDENTITY = "identity"
FINANCIAL = "financial"

# Logical column keys, as produced by layout.detect_columns().
COL_EPF_WAGES = "wages:EPF"
COL_EPS_WAGES = "wages:EPS"
COL_EMPLOYEE = "amount:Employee"
COL_EMPLOYER = "amount:Employer"
COL_PENSION = "amount:Pension"


@dataclass(frozen=True)
class Field:
    """One redactable element."""

    name: str
    kind: str
    default_on: bool
    description: str
    keep_chars: int = 0
    column: str | None = None

    @property
    def is_financial(self) -> bool:
        return self.kind == FINANCIAL


FIELDS: tuple[Field, ...] = (
    Field(
        "establishment-id",
        IDENTITY,
        True,
        "Employer establishment code. Keeps the 5-letter regional office "
        "prefix, redacts the numeric part.",
        keep_chars=5,
    ),
    Field(
        "employer-name",
        IDENTITY,
        True,
        "Employer name. Keeps the legal-form suffix (PRIVATE LIMITED, LLP, ...) "
        "so the line still reads as a company.",
    ),
    Field(
        "member-id",
        IDENTITY,
        True,
        "Member ID, in the header and in the footer that repeats on every page. "
        "Keeps the 5-letter prefix.",
        keep_chars=5,
    ),
    Field(
        "uan",
        IDENTITY,
        True,
        "Universal Account Number. Keeps the first 4 digits.",
        keep_chars=4,
    ),
    Field(
        "member-name",
        IDENTITY,
        False,
        "Member name. Off by default -- a verifier usually needs it to tie the "
        "passbook to you.",
    ),
    Field(
        "dob",
        IDENTITY,
        False,
        "Date of birth. Off by default, for the same reason as member-name.",
    ),
    Field(
        "epf-wages",
        FINANCIAL,
        True,
        "Wages / EPF column -- your actual monthly salary.",
        column=COL_EPF_WAGES,
    ),
    Field(
        "epf-employee",
        FINANCIAL,
        True,
        "Employee column: EPF employee contribution and employee balance.",
        column=COL_EMPLOYEE,
    ),
    Field(
        "epf-employer",
        FINANCIAL,
        True,
        "Employer column: EPF employer contribution and employer balance.",
        column=COL_EMPLOYER,
    ),
    Field(
        "eps-wages",
        FINANCIAL,
        False,
        "Wages / EPS column. Off by default: capped at the statutory ceiling, "
        "so it reveals no actual salary.",
        column=COL_EPS_WAGES,
    ),
    Field(
        "eps-pension",
        FINANCIAL,
        False,
        "Pension column: EPS contribution and pension balance. Off by default.",
        column=COL_PENSION,
    ),
)

BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}

PROFILES: dict[str, frozenset[str]] = {
    # What the tool was originally built to produce.
    "default": frozenset(f.name for f in FIELDS if f.default_on),
    # Everything, including the EPS figures and your name.
    "strict": frozenset(f.name for f in FIELDS),
    # Header only -- keeps the full financial history readable.
    "identity": frozenset(
        f.name for f in FIELDS if f.kind == IDENTITY and f.default_on
    ),
    # Table only -- keeps the header readable.
    "financial": frozenset(
        f.name for f in FIELDS if f.kind == FINANCIAL and f.default_on
    ),
    # Nothing; build a set up from scratch with --mask.
    "none": frozenset(),
}

# Rows that --keep-rows can exempt from column redaction, keyed by a
# distinctive substring of the row's own label.
ROW_KINDS: dict[str, str] = {
    "opening": "OB Int. Updated",
    "contributions": "Total Contributions",
    "transfers": "Total Transfer",
    "withdrawals": "Total Withdrawals",
    "interest": "Int. Updated upto",
    "closing": "Closing Balance",
}


class FieldError(ValueError):
    """Raised for an unknown field or profile name."""


def resolve(
    profile: str = "default",
    add: tuple[str, ...] = (),
    remove: tuple[str, ...] = (),
) -> set[str]:
    """Resolve a profile plus overrides into a concrete set of field names."""
    if profile not in PROFILES:
        raise FieldError(
            f"unknown profile {profile!r}; choose from {', '.join(sorted(PROFILES))}"
        )
    selected = set(PROFILES[profile])
    for name in add:
        if name not in BY_NAME:
            raise FieldError(f"unknown field {name!r}; see `epfo-redact --list-fields`")
        selected.add(name)
    for name in remove:
        if name not in BY_NAME:
            raise FieldError(f"unknown field {name!r}; see `epfo-redact --list-fields`")
        selected.discard(name)
    return selected
