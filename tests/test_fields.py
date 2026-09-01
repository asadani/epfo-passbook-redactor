"""The field registry and profile resolution."""

from __future__ import annotations

import pytest

from epfo_redactor.fields import (
    BY_NAME,
    FIELDS,
    FINANCIAL,
    IDENTITY,
    PROFILES,
    FieldError,
    resolve,
)

EPS_FIELDS = {"eps-wages", "eps-pension"}


def test_default_profile_keeps_every_eps_field_readable():
    """The core promise of the default profile."""
    assert not (PROFILES["default"] & EPS_FIELDS)


def test_default_profile_redacts_the_epf_money():
    assert {"epf-wages", "epf-employee", "epf-employer"} <= PROFILES["default"]


def test_default_profile_keeps_identity_you_need_to_prove_ownership():
    assert "member-name" not in PROFILES["default"]
    assert "dob" not in PROFILES["default"]


def test_strict_covers_everything():
    assert PROFILES["strict"] == {f.name for f in FIELDS}


def test_identity_and_financial_profiles_are_disjoint():
    assert not (PROFILES["identity"] & PROFILES["financial"])


def test_every_financial_field_names_a_column():
    for f in FIELDS:
        if f.kind == FINANCIAL:
            assert f.column, f"{f.name} must map to a column"
        else:
            assert f.kind == IDENTITY


def test_profiles_only_reference_real_fields():
    for name, members in PROFILES.items():
        assert members <= set(BY_NAME), name


def test_resolve_applies_add_then_remove():
    assert resolve("none", add=("uan",)) == {"uan"}
    assert "uan" not in resolve("default", remove=("uan",))
    assert resolve("none", add=("uan",), remove=("uan",)) == set()


def test_resolve_rejects_unknown_names():
    with pytest.raises(FieldError, match="unknown profile"):
        resolve("paranoid")
    with pytest.raises(FieldError, match="unknown field"):
        resolve("default", add=("salary",))
    with pytest.raises(FieldError, match="unknown field"):
        resolve("default", remove=("salary",))


def test_keep_chars_are_sane():
    assert BY_NAME["establishment-id"].keep_chars == 5
    assert BY_NAME["member-id"].keep_chars == 5
    assert BY_NAME["uan"].keep_chars == 4
    assert BY_NAME["member-name"].keep_chars == 0
