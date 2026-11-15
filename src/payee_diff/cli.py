"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from payee_diff import __version__
from payee_diff.models import render_text
from payee_diff.scan import scan_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="payee-diff",
        description=(
            "Report payment details that a person can see on an invoice or "
            "supplier email when they differ from details that exist only in "
            "hidden or raw text."
        ),
    )
    parser.add_argument("file", help="a .pdf, .html, .htm, or .eml file")
    parser.add_argument(
        "--format",
        choices=("text", "json", "both"),
        default="both",
        help="text report, JSON report, or both (default: both)",
    )
    parser.add_argument("--version", action="version", version=f"payee-diff {__version__}")
    args = parser.parse_args(argv)

    report = scan_path(Path(args.file))
    if args.format in ("text", "both"):
        sys.stdout.write(render_text(report))
    if args.format == "both":
        sys.stdout.write("\n--- json ---\n")
    if args.format in ("json", "both"):
        json.dump(report.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
