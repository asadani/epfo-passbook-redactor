"""Refuse to commit a PDF from anywhere except samples/synthetic/.

This repo exists to keep real passbooks private. A real one landing in git
history would be the single worst thing that could happen to it, so the check
is mechanical rather than advisory.
"""

import sys
from pathlib import Path

ALLOWED = Path("samples/synthetic")


def main(argv: list[str]) -> int:
    offenders = [
        arg
        for arg in argv
        if arg.lower().endswith(".pdf") and ALLOWED not in Path(arg).parents
    ]
    if offenders:
        print("Refusing to commit PDFs outside samples/synthetic/:", file=sys.stderr)
        for path in offenders:
            print(f"  {path}", file=sys.stderr)
        print(
            "\nIf this is a real passbook, it must not enter this repo. "
            "Use `epfo-synth` to make a synthetic sample instead.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
