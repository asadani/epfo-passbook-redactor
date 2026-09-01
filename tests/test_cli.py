"""End-to-end CLI behaviour, including the config file and its precedence."""

from __future__ import annotations

import pymupdf
import pytest
from click.testing import CliRunner

from epfo_redactor.cli import main
from epfo_redactor.config import Config, ConfigError, load


@pytest.fixture
def run():
    return CliRunner().invoke


def _text(path):
    doc = pymupdf.open(path)
    try:
        return "\n".join(p.get_text() for p in doc)
    finally:
        doc.close()


def test_list_fields_shows_the_defaults(run):
    result = run(main, ["--list-fields"])
    assert result.exit_code == 0
    assert "eps-pension" in result.output
    assert "strict" in result.output


def test_no_inputs_is_a_usage_error(run):
    result = run(main, [])
    assert result.exit_code != 0
    assert "at least one" in result.output


def test_end_to_end_produces_one_file_per_employer(run, synth_dir, tmp_path):
    out = tmp_path / "out"
    result = run(
        main, [str(synth_dir / p.name) for p in synth_dir.iterdir()] + ["-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "verified clean" in result.output
    written = sorted(out.glob("*.pdf"))
    assert len(written) == 2


def test_dry_run_writes_nothing(run, synth_dir, tmp_path):
    out = tmp_path / "out"
    result = run(main, [str(synth_dir), "--dry-run", "-o", str(out)])
    assert result.exit_code == 0
    assert "dry run" in result.output
    assert not out.exists()


def test_no_mask_leaves_the_wage_column_readable(run, one_pdf, tmp_path):
    out = tmp_path / "out"
    result = run(main, [str(one_pdf), "--no-mask", "epf-wages", "-o", str(out)])
    assert result.exit_code == 0, result.output
    text = _text(next(out.glob("*.pdf")))
    source = _text(one_pdf)
    wages = {line for line in source.splitlines() if line.replace(",", "").isdigit()}
    assert wages & set(text.splitlines())


def test_unknown_field_is_rejected(run, one_pdf, tmp_path):
    result = run(main, [str(one_pdf), "--mask", "salary", "-o", str(tmp_path)])
    assert result.exit_code != 0
    assert "unknown field" in result.output


def test_unknown_row_kind_is_rejected(run, one_pdf, tmp_path):
    result = run(main, [str(one_pdf), "--keep-rows", "bonus", "-o", str(tmp_path)])
    assert result.exit_code != 0
    assert "unknown row kind" in result.output


def test_profile_none_without_mask_is_rejected(run, one_pdf, tmp_path):
    result = run(main, [str(one_pdf), "--profile", "none", "-o", str(tmp_path)])
    assert result.exit_code != 0
    assert "nothing selected" in result.output


def test_missing_input_is_reported(run, tmp_path):
    result = run(main, [str(tmp_path / "nope.pdf"), "-o", str(tmp_path)])
    assert result.exit_code != 0


def test_no_merge_writes_each_year_separately(run, synth_dir, tmp_path):
    out = tmp_path / "out"
    result = run(main, [str(synth_dir), "--no-merge", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert len(list(out.glob("*.pdf"))) == len(list(synth_dir.glob("*/*.pdf")))


def test_config_file_is_picked_up(run, one_pdf, tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "epfo-redact.yaml").write_text(
        "profile: identity\nstyle: hatch\nout: from-config\n", encoding="utf-8"
    )
    monkeypatch.chdir(workdir)
    result = run(main, [str(one_pdf)])
    assert result.exit_code == 0, result.output
    assert "epfo-redact.yaml" in result.output
    assert (workdir / "from-config").is_dir()


def test_cli_flag_beats_the_config_file(run, one_pdf, tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "epfo-redact.yaml").write_text("profile: identity\n", encoding="utf-8")
    monkeypatch.chdir(workdir)
    out = tmp_path / "out"
    result = run(main, [str(one_pdf), "--profile", "strict", "-o", str(out)])
    assert result.exit_code == 0, result.output
    # strict removes the EPS ceiling figure; identity would have kept it.
    assert "15,000" not in _text(next(out.glob("*.pdf")))


def test_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "epfo-redact.yaml"
    path.write_text("profil: strict\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown key"):
        load(path)


def test_config_accepts_list_or_comma_string(tmp_path):
    path = tmp_path / "epfo-redact.yaml"
    path.write_text("mask: [dob, member-name]\nno-mask: epf-wages\n", encoding="utf-8")
    cfg = load(path)
    assert cfg.mask == ("dob", "member-name")
    assert cfg.no_mask == ("epf-wages",)


def test_empty_config_is_valid(tmp_path):
    path = tmp_path / "epfo-redact.yaml"
    path.write_text("", encoding="utf-8")
    assert load(path) == Config()
