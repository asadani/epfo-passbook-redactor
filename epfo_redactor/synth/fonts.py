"""Font lookup for the synthetic generator.

The real passbook is set in Calibri with the Hindi half of every bilingual
label in a legacy Kruti Dev encoding. We reproduce the *look*, not the legacy
encoding: the Hindi is real Unicode Devanagari, so the generated page is
searchable and the text layer is honest about what it says.

Neither font ships with the package. We look for whatever the machine has and
degrade in a documented order:

* Latin  -- Calibri, then Carlito (metric-compatible), then any of the usual
  free sans faces, then the built-in Helvetica.
* Hindi  -- Nirmala UI, Noto Sans Devanagari, Mangal, Lohit. If none is
  installed the Hindi half of each label is left out and the page is English
  only, which is what the generator did before this existed.

Metrics matter: Calibri and Carlito are metric-compatible, so a page generated
on Linux CI lands its columns in the same places as one generated on Windows.
Falling back to Helvetica shifts glyph widths but not the grid, which is drawn
from fixed coordinates, so column detection still sees the real geometry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pymupdf

# Searched in order; the first hit wins.
LATIN_REGULAR = (
    "calibri.ttf",
    "Carlito-Regular.ttf",
    "LiberationSans-Regular.ttf",
    "DejaVuSans.ttf",
    "Arial.ttf",
)
LATIN_BOLD = (
    "calibrib.ttf",
    "Carlito-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "Arialbd.ttf",
)
DEVANAGARI = (
    "Nirmala.ttc",
    "NotoSansDevanagari-Regular.ttf",
    "NotoSansDevanagari_Condensed-Regular.ttf",
    "mangal.ttf",
    "Lohit-Devanagari.ttf",
    "lohit_hi.ttf",
    "Samyak-Devanagari.ttf",
)


def _font_dirs() -> list[Path]:
    home = Path.home()
    return [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
        home / "AppData/Local/Microsoft/Windows/Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".fonts",
        home / ".local/share/fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        home / "Library/Fonts",
    ]


@lru_cache(maxsize=None)
def find_font_file(candidates: tuple[str, ...]) -> str | None:
    """Absolute path of the first installed font in ``candidates``."""
    dirs = [d for d in _font_dirs() if d.is_dir()]
    for name in candidates:
        for directory in dirs:
            direct = directory / name
            if direct.is_file():
                return str(direct)
        for directory in dirs:
            # Linux buries faces under vendor subdirectories.
            for hit in directory.rglob(name):
                if hit.is_file():
                    return str(hit)
    return None


@dataclass(frozen=True)
class Face:
    """One font, ready to measure with and to draw with.

    ``simple`` embeds the face as a single-byte PDF font instead of the
    Identity-H default. That matters more than it looks: embedded as a CID
    font, MuPDF derives the ToUnicode map by walking the face's cmap
    backwards, and Calibri maps both U+0020 and U+00A0 to the same space
    glyph -- so every space in the extracted text comes back as a no-break
    space and every hyphen as U+2010. The redactor splits words on real
    spaces, so a page written that way is unreadable to it. Simple embedding
    keeps the ASCII round-trip honest, and is only an option for the Latin
    faces: Devanagari needs the multi-byte encoding to shape at all.
    """

    alias: str
    font: pymupdf.Font
    path: str | None
    simple: bool = True

    def width(self, text: str, size: float) -> float:
        return self.font.text_length(text, size)

    def fitted_size(self, text: str, size: float, max_width: float | None) -> float:
        """``size``, shrunk until ``text`` fits ``max_width``.

        Devanagari set in Nirmala is wider than the same label in Kruti Dev, so
        a label copied at the real template's size can overflow its cell. The
        real page never overflows, so neither should ours.
        """
        if max_width is None or size <= 0:
            return size
        while size > 5.0 and self.width(text, size) > max_width:
            size -= 0.25
        return size

    @property
    def ascender(self) -> float:
        return self.font.ascender

    def register(self, page: pymupdf.Page) -> None:
        if self.path is not None:
            page.insert_font(
                fontname=self.alias, fontfile=self.path, set_simple=self.simple
            )


@dataclass(frozen=True)
class FaceSet:
    latin: Face
    bold: Face
    hindi: Face | None

    @property
    def bilingual(self) -> bool:
        return self.hindi is not None

    def register(self, page: pymupdf.Page) -> None:
        for face in (self.latin, self.bold, self.hindi):
            if face is not None:
                face.register(page)


def _face(alias: str, candidates: tuple[str, ...], base14: str) -> Face:
    path = find_font_file(candidates)
    if path is None:
        return Face(base14, pymupdf.Font(fontname=base14), None)
    return Face(alias, pymupdf.Font(fontfile=path), path)


@lru_cache(maxsize=1)
def load_faces() -> FaceSet:
    """The best set of faces this machine can offer."""
    hindi_path = find_font_file(DEVANAGARI)
    return FaceSet(
        latin=_face("SynLatin", LATIN_REGULAR, "helv"),
        bold=_face("SynBold", LATIN_BOLD, "hebo"),
        hindi=(
            None
            if hindi_path is None
            else Face(
                "SynHindi",
                pymupdf.Font(fontfile=hindi_path),
                hindi_path,
                simple=False,
            )
        ),
    )
