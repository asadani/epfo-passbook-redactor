"""Refuse to commit a PDF that is not a generated synthetic sample.

This repo exists to keep real passbooks private. A real one landing in git
history would be the single worst thing that could happen to it, so the check
is mechanical rather than advisory.

Two conditions, both required:

1. The path is inside ``samples/input/`` or ``samples/output/``.
2. Every page carries the marker ``epfo-synth`` stamps under the banner.

The second one is the real guard. A path allowlist alone would wave through a
real passbook that someone redacted into ``samples/output/`` by mistake -- and
``-o samples/output`` is exactly the typo that produces one. The marker
survives redaction and merging, so a file that lacks it on any page did not
come out of the generator.
"""

import sys
from pathlib import Path

ALLOWED = (Path("samples/input"), Path("samples/output"))
MARKER = "SYNTHETIC SAMPLE"


def _reject(path: str) -> str | None:
    """Why this PDF may not be committed, or None if it may."""
    parents = Path(path).parents
    if not any(allowed in parents for allowed in ALLOWED):
        return "outside samples/input/ and samples/output/"
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - dependency guard
        return "cannot be checked: PyMuPDF is not installed"
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pragma: no cover - unreadable file
        return f"cannot be opened: {exc}"
    try:
        blank = [page.number + 1 for page in doc if MARKER not in page.get_text("text")]
    finally:
        doc.close()
    if blank:
        listed = ", ".join(str(n) for n in blank[:5])
        return f"page(s) {listed} are not marked as a synthetic sample"
    return None


def main(argv: list[str]) -> int:
    offenders = [
        (arg, reason)
        for arg in argv
        if arg.lower().endswith(".pdf")
        for reason in [_reject(arg)]
        if reason
    ]
    if offenders:
        print("Refusing to commit these PDFs:", file=sys.stderr)
        for path, reason in offenders:
            print(f"  {path}: {reason}", file=sys.stderr)
        print(
            "\nIf this is a real passbook, it must not enter this repo. "
            "Use `epfo-synth` to make a synthetic sample instead.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
