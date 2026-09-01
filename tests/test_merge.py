"""Grouping, page order, output naming and metadata scrubbing."""

from __future__ import annotations

import pymupdf

from epfo_redactor.fields import resolve
from epfo_redactor.merge import Output, Source, group, write
from epfo_redactor.redact import redact_document

DEFAULT = resolve("default")


def _sources(pdfs):
    out = []
    for path in pdfs:
        doc, reports = redact_document(path, DEFAULT, {}, set())
        out.append(Source(path=path, doc=doc, reports=reports))
    return out


def test_groups_one_output_per_employer(synth_pdfs):
    sources = _sources(synth_pdfs)
    try:
        outputs = group(sources, "establishment", merge=True)
        assert len(outputs) == 2
        assert sum(len(o.sources) for o in outputs) == len(synth_pdfs)
    finally:
        for s in sources:
            s.doc.close()


def test_pages_come_out_in_financial_year_order(synth_pdfs):
    sources = _sources(list(reversed(synth_pdfs)))
    try:
        for output in group(sources, "establishment", merge=True):
            years = [s.fiscal_year for s in output.sources]
            assert years == sorted(years)
    finally:
        for s in sources:
            s.doc.close()


def test_no_merge_gives_one_output_per_input(synth_pdfs):
    sources = _sources(synth_pdfs)
    try:
        outputs = group(sources, "establishment", merge=False)
        assert len(outputs) == len(synth_pdfs)
    finally:
        for s in sources:
            s.doc.close()


def test_filename_uses_the_prefix_not_the_full_code(synth_pdfs):
    """The filename must not undo the redaction inside the document."""
    sources = _sources(synth_pdfs)
    try:
        for output in group(sources, "establishment", merge=True):
            name = output.filename()
            full = output.sources[0].establishment_id
            assert full is not None
            assert full not in name
            assert full[:5] in name
            assert name.endswith("_redacted.pdf")
    finally:
        for s in sources:
            s.doc.close()


def test_colliding_prefixes_get_distinct_labels():
    """Two employers under one regional office must not overwrite each other."""

    class Stub:
        def __init__(self, est, year, name):
            self.establishment_id = est
            self._year = year
            self.path = type(
                "P",
                (),
                {"stem": name, "name": name, "parent": type("D", (), {"name": "d"})()},
            )()

        @property
        def fiscal_year(self):
            return self._year

    a = Stub("ABCDE1111111111", 2019, "a")
    b = Stub("ABCDE2222222222", 2020, "b")
    outputs = group([a, b], "establishment", merge=True)
    labels = {o.label for o in outputs}
    assert len(outputs) == 2
    assert len(labels) == 2


def test_single_year_group_gets_a_single_year_name():
    class Stub:
        establishment_id = "ABCDE1111111111"
        fiscal_year = 2019
        fiscal_years = [2019]
        path = type("P", (), {"stem": "x", "name": "x"})()

    assert "FY2019_" in Output(label="ABCDE", sources=[Stub()]).filename()


def test_written_output_has_scrubbed_metadata(synth_pdfs, tmp_path):
    sources = _sources(synth_pdfs[:2])
    try:
        output = group(sources, "establishment", merge=True)[0]
        dest = write(output, tmp_path)
    finally:
        for s in sources:
            s.doc.close()

    doc = pymupdf.open(dest)
    try:
        assert doc.metadata["producer"] == ""
        assert doc.metadata["creator"] == ""
        assert "redacted" in doc.metadata["title"]
    finally:
        doc.close()


def test_a_multi_year_source_is_named_with_its_whole_span():
    """A single PDF can hold a financial year per page; naming it after the
    first would claim the document covers one year."""

    class Stub:
        establishment_id = "ABCDE1111111111"
        fiscal_year = 2015
        fiscal_years = [2015, 2016, 2017]
        path = type("P", (), {"stem": "x", "name": "x"})()

    assert "FY2015-2017_" in Output(label="ABCDE", sources=[Stub()]).filename()
