"""Walk a .eml file. Plain parts are visible text. HTML and PDF parts are scanned."""

from __future__ import annotations

from email import policy
from email.message import Message
from email.parser import BytesParser

from payee_diff.html_input import scan_html
from payee_diff.models import VISIBLE, PartScan
from payee_diff.pdf_input import PdfReadError, scan_pdf
from payee_diff.unicode_tags import prepare_text, tag_payloads
from payee_diff.extract import extract_findings, finding_context
from payee_diff.models import UNICODE_TAG, Candidate


class EmailReadError(Exception):
    pass


def scan_eml(data: bytes) -> PartScan:
    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
    except Exception as exc:  # the parser raises a few different errors
        raise EmailReadError(f"could not read email: {exc}") from exc
    if not list(message.keys()):
        raise EmailReadError("unsupported input: file does not look like an email")

    combined = PartScan()
    saw_body = False
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        filename = part.get_filename()
        label = content_type if not filename else f"{content_type}; {filename}"
        if content_type == "text/plain":
            saw_body = True
            _merge(combined, _scan_plain(part, label))
        elif content_type == "text/html":
            saw_body = True
            _merge(combined, scan_html(_text(part), part=label))
        elif content_type == "application/pdf" or (filename or "").lower().endswith(".pdf"):
            payload = part.get_payload(decode=True)
            if not isinstance(payload, (bytes, bytearray)) or not payload:
                combined.notes.append(f"skipped empty part {label}")
                continue
            try:
                _merge(combined, scan_pdf(bytes(payload), part=label))
            except PdfReadError as exc:
                raise EmailReadError(f"{label}: {exc}") from exc
        else:
            combined.notes.append(f"skipped part {label}")
    if not saw_body and not combined.saw_pdf and not combined.candidates:
        # Still a successful read: there was simply nothing to compare.
        # An image-only attachment sets saw_pdf and unchecked on its own.
        if not combined.unchecked:
            combined.notes.append("email has no text, html, or pdf part")
    return combined


def _scan_plain(part: Message, label: str) -> PartScan:
    result = PartScan()
    text = _text(part)
    for payload in tag_payloads(text):
        for finding in extract_findings(payload):
            result.candidates.append(
                Candidate(
                    field=finding.field,
                    value=finding.value,
                    normalized=finding.normalized,
                    origin=UNICODE_TAG,
                    detail="unicode tags",
                    context=finding_context(payload, finding),
                    part=label,
                )
            )
    visible = prepare_text(text)
    for finding in extract_findings(visible):
        result.candidates.append(
            Candidate(
                field=finding.field,
                value=finding.value,
                normalized=finding.normalized,
                origin=VISIBLE,
                detail="text/plain",
                context=finding_context(visible, finding),
                part=label,
            )
        )
    return result


def _text(part: Message) -> str:
    content = part.get_content()  # type: ignore[attr-defined]
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        charset = part.get_content_charset() or "utf-8"
        return content.decode(charset, errors="replace")
    return str(content)


def _merge(into: PartScan, extra: PartScan) -> None:
    into.candidates.extend(extra.candidates)
    into.notes.extend(extra.notes)
    into.unchecked.extend(extra.unchecked)
    into.pdf_pages += extra.pdf_pages
    into.selectable_characters += extra.selectable_characters
    into.images += extra.images
    into.saw_pdf = into.saw_pdf or extra.saw_pdf
