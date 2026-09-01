"""Shared fixtures.

Every fixture builds its own synthetic passbooks. No test ever reads a real
document, and there is none in the repo to read.
"""

from __future__ import annotations

import pytest

from epfo_redactor.synth.generate import generate


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory):
    """Two employers, four financial years, deterministic."""
    out = tmp_path_factory.mktemp("synth")
    generate(out_dir=out, employers=2, years=(2019, 2022), seed=7)
    return out


@pytest.fixture(scope="session")
def synth_pdfs(synth_dir):
    return sorted(synth_dir.glob("*/*.pdf"))


@pytest.fixture(scope="session")
def one_pdf(synth_pdfs):
    return synth_pdfs[0]


@pytest.fixture
def page(one_pdf):
    import pymupdf

    doc = pymupdf.open(one_pdf)
    yield doc[0]
    doc.close()
