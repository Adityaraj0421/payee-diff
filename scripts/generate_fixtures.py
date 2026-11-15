"""Write the synthetic fixtures under fixtures/.

Run from the repo root:

    python scripts/generate_fixtures.py

Companies, amounts, and IBANs are fictional. IBANs pass the mod-97 check
so the scanner's validator accepts them. Nothing here is a real account.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from payee_diff.iban import make_iban  # noqa: E402
from payee_diff.unicode_tags import encode_tag_payload  # noqa: E402
from pdf_factory import build_pdf, image_draw, sample_image, text_block  # noqa: E402

FIXTURES = ROOT / "fixtures"

VISIBLE_IBAN = make_iban("GB", "FAKE00112210293847")
HIDDEN_IBAN = make_iban("DE", "000000009988776655")

VISIBLE_LINES = [
    "Northwind Paper Ltd",
    "Invoice NW-1042",
    "Payee: Northwind Paper Ltd",
    f"IBAN: {VISIBLE_IBAN}",
    "Account number: 10293847",
    "Sort code: 00-11-22",
    "IFSC: FAKE0NWP123",
    "UPI: northwind.paper@upi",
    "Amount due: GBP 1,250.00",
]
HIDDEN_LINES = [
    "Payee: Grey Harbor Supplies GmbH",
    f"IBAN: {HIDDEN_IBAN}",
    "Amount due: GBP 9,875.00",
]


def visible_pdf() -> bytes:
    return build_pdf([{"content": text_block(VISIBLE_LINES)}])


def white_text_pdf() -> bytes:
    content = text_block(VISIBLE_LINES) + text_block(
        HIDDEN_LINES, y=420, color=(1, 1, 1), render=0
    )
    return build_pdf([{"content": content}])


def render_mode_pdf() -> bytes:
    content = text_block(VISIBLE_LINES) + text_block(
        HIDDEN_LINES, y=420, color=(0, 0, 0), render=3
    )
    return build_pdf([{"content": content}])


def image_only_pdf() -> bytes:
    pixels, width, height = sample_image()
    return build_pdf(
        [
            {
                "content": image_draw(),
                "image": pixels,
                "image_size": (width, height),
            }
        ]
    )


def _html_document(extra: str) -> str:
    rows = "\n".join(f"  <p>{_escape(line)}</p>" for line in VISIBLE_LINES)
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><meta charset=\"utf-8\"><title>Invoice NW-1042</title></head>\n"
        "<body style=\"background-color:#ffffff;color:#000000\">\n"
        f"{rows}\n"
        f"{extra}\n"
        "</body>\n"
        "</html>\n"
    )


def clean_html() -> str:
    return _html_document("")


def white_on_white_html() -> str:
    hidden = "\n".join(_escape(line) for line in HIDDEN_LINES)
    extra = (
        "  <p style=\"color:#ffffff;background-color:#ffffff\">\n"
        f"{hidden}\n"
        "  </p>"
    )
    return _html_document(extra)


def display_none_html() -> str:
    hidden = "\n".join(_escape(line) for line in HIDDEN_LINES)
    extra = "  <span style=\"display:none\">\n" f"{hidden}\n" "  </span>"
    return _html_document(extra)


def unicode_tags_html() -> str:
    payload = encode_tag_payload(" ".join(HIDDEN_LINES))
    extra = f"  <p>{payload}</p>"
    return _html_document(extra)


def _plain() -> str:
    return "\n".join(VISIBLE_LINES) + "\n"


def clean_eml() -> bytes:
    return _eml(_plain(), clean_html(), visible_pdf())


def hidden_span_eml() -> bytes:
    return _eml(_plain(), display_none_html(), None)


def _eml(plain: str, html: str, pdf: bytes | None) -> bytes:
    alt = "payee-diff-fixture-alt"
    mixed = "payee-diff-fixture-boundary"
    alternative = (
        f"--{alt}\r\n"
        "Content-Type: text/plain; charset=\"utf-8\"\r\n"
        "Content-Transfer-Encoding: 8bit\r\n"
        "\r\n"
        f"{plain}"
        f"--{alt}\r\n"
        "Content-Type: text/html; charset=\"utf-8\"\r\n"
        "Content-Transfer-Encoding: 8bit\r\n"
        "\r\n"
        f"{html}"
        f"--{alt}--\r\n"
    )
    if pdf is None:
        headers = _headers(f'multipart/alternative; boundary="{alt}"')
        return (headers + alternative).encode("utf-8")
    encoded = base64.encodebytes(pdf).decode("ascii")
    body = (
        f"--{mixed}\r\n"
        f"Content-Type: multipart/alternative; boundary=\"{alt}\"\r\n"
        "\r\n"
        f"{alternative}"
        f"--{mixed}\r\n"
        "Content-Type: application/pdf; name=\"invoice.pdf\"\r\n"
        "Content-Disposition: attachment; filename=\"invoice.pdf\"\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{encoded}"
        f"--{mixed}--\r\n"
    )
    headers = _headers(f'multipart/mixed; boundary="{mixed}"')
    return (headers + body).encode("utf-8")


def _headers(content_type: str) -> str:
    return (
        "From: accounts@northwind-paper.example\r\n"
        "To: accounts-payable@example-buyer.test\r\n"
        "Subject: Invoice NW-1042\r\n"
        "Date: Thu, 01 Jan 2026 00:00:00 +0000\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: {content_type}\r\n"
        "\r\n"
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes | str] = {
        "clean.pdf": visible_pdf(),
        "clean.html": clean_html(),
        "clean.eml": clean_eml(),
        "html_white_on_white.html": white_on_white_html(),
        "html_display_none.html": display_none_html(),
        "html_unicode_tags.html": unicode_tags_html(),
        "pdf_white_text.pdf": white_text_pdf(),
        "pdf_render_mode_3.pdf": render_mode_pdf(),
        "eml_hidden_span.eml": hidden_span_eml(),
        "image_only.pdf": image_only_pdf(),
    }
    for name, content in files.items():
        path = FIXTURES / name
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
