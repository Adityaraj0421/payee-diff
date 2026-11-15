"""Dispatch one local file to the HTML, PDF, or email scanner."""

from __future__ import annotations

import hashlib
from pathlib import Path

from payee_diff.eml_input import EmailReadError, scan_eml
from payee_diff.html_input import scan_html
from payee_diff.models import Report, build_report
from payee_diff.pdf_input import PdfReadError, scan_pdf

_SUFFIXES = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".eml": "eml",
}

_UNSUPPORTED = "unsupported input: expected a .pdf, .html, .htm, or .eml file"


def scan_path(path: Path) -> Report:
    display = str(path)
    if not path.exists():
        return build_report(path=display, kind=None, sha256=None, error=f"file not found: {display}")
    if not path.is_file():
        return build_report(path=display, kind=None, sha256=None, error=f"not a file: {display}")
    kind = _SUFFIXES.get(path.suffix.lower())
    if kind is None:
        return build_report(path=display, kind=None, sha256=None, error=_UNSUPPORTED)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    try:
        return _scan_bytes(data, kind, path=display, sha256=digest)
    except (PdfReadError, EmailReadError) as exc:
        return build_report(path=display, kind=kind, sha256=digest, error=str(exc))


def _scan_bytes(data: bytes, kind: str, *, path: str, sha256: str) -> Report:
    if kind == "pdf":
        scan = scan_pdf(data)
    elif kind == "html":
        text = data.decode("utf-8-sig", errors="replace")
        scan = scan_html(text)
    elif kind == "eml":
        scan = scan_eml(data)
    else:
        return build_report(path=path, kind=kind, sha256=sha256, error=_UNSUPPORTED)
    return build_report(path=path, kind=kind, sha256=sha256, scan=scan)
