"""Label-and-regex extraction of payment details.

Each finder is deliberately narrow. Account numbers, sort codes, IFSC codes,
UPI ids, and payee names are kept only when a label sits next to them.
IBANs are kept when the country length and mod-97 check both agree.
Amounts need a currency, or an amount/total label plus a decimal number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from payee_diff.iban import IBAN_LENGTHS, iban_is_valid

FIELD_ORDER = (
    "iban",
    "account_number",
    "sort_code",
    "ifsc",
    "upi",
    "amount",
    "payee",
)

_CURRENCY_WORDS = {
    "GBP": "GBP",
    "EUR": "EUR",
    "USD": "USD",
    "INR": "INR",
    "£": "GBP",
    "€": "EUR",
    "$": "USD",
    "₹": "INR",
}

_AMOUNT_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}"
_CURRENCY = r"(?:GBP|EUR|USD|INR|£|€|\$|₹)"

_ACCOUNT_RE = re.compile(
    r"(?i)\b(?:account\s*(?:number|no\.?|num)|a/c(?:\s*(?:number|no\.?))?|acct)\b"
    r"\s*[:#\-]?\s*([0-9]{6,18})\b"
)
_SORT_RE = re.compile(
    r"(?i)\bsort\s*code\b\s*[:#\-]?\s*(\d{2}[-\s]\d{2}[-\s]\d{2})\b"
)
_IFSC_RE = re.compile(
    r"(?i)\bifsc\b\s*[:#\-]?\s*([A-Z]{4}0[A-Z0-9]{6})\b"
)
_UPI_RE = re.compile(
    r"(?i)\b(?:upi|vpa)\b\s*[:#\-]?\s*"
    r"([a-z0-9][a-z0-9._-]{0,255}@[a-z][a-z0-9]{1,63})\b"
)
_AMOUNT_LABELED_RE = re.compile(
    rf"(?i)\b(?:amount(?:\s+due)?|total(?:\s+due)?|balance\s+due|"
    rf"invoice\s+total|grand\s+total)\b\s*[:\-]?\s*({_CURRENCY})?\s*({_AMOUNT_NUMBER})\b"
)
_AMOUNT_BEFORE_RE = re.compile(rf"(?i)({_CURRENCY})\s*({_AMOUNT_NUMBER})\b")
_AMOUNT_AFTER_RE = re.compile(rf"(?i)\b({_AMOUNT_NUMBER})\s*({_CURRENCY})\b")
_PAYEE_RE = re.compile(
    r"(?i)\b(?:payee|beneficiary|account\s*name|account\s*holder|"
    r"payable\s*to|paid\s*to|payment\s*to)\b[ \t]*[:\-][ \t]*\n?[ \t]*"
    r"([A-Za-z][A-Za-z0-9&.'’,-]*(?:[ \t]+[A-Za-z][A-Za-z0-9&.'’,-]*){0,6})"
)
_PAYEE_STOP = re.compile(
    r"(?i)\b(?:iban|account|sort|ifsc|upi|vpa|amount|total|invoice|balance|swift|bic)\b"
)


@dataclass(frozen=True)
class Finding:
    field: str
    value: str
    normalized: str
    start: int
    end: int


def _context(text: str, start: int, end: int, width: int = 48) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    snippet = text[left:right].replace("\n", " ")
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    return snippet


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in spans)


def find_ibans(text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    upper = text.upper()
    length = len(text)
    i = 0
    while i < length - 4:
        prev_ok = i == 0 or not upper[i - 1].isalnum()
        if prev_ok and upper[i : i + 2].isalpha() and upper[i + 2 : i + 4].isdigit():
            country = upper[i : i + 2]
            expected = IBAN_LENGTHS.get(country)
            if expected is not None:
                j = i
                chars: list[str] = []
                while j < length and len(chars) < expected:
                    ch = text[j]
                    if ch.isalnum():
                        chars.append(ch)
                        j += 1
                    elif ch in " \t-" and chars:
                        j += 1
                    else:
                        break
                if len(chars) == expected and (j >= length or not text[j].isalnum()):
                    candidate = "".join(chars).upper()
                    span = (i, j)
                    if span not in seen and iban_is_valid(candidate):
                        seen.add(span)
                        findings.append(
                            Finding("iban", candidate, candidate, i, j)
                        )
                        i = j
                        continue
        i += 1
    return findings


def _currency_code(currency: str | None) -> str | None:
    if not currency:
        return None
    return _CURRENCY_WORDS.get(currency) or _CURRENCY_WORDS.get(currency.upper(), currency.upper())


def _amount_normalized(number: str, currency: str | None) -> str:
    numeric = f"{Decimal(number.replace(',', '')):.2f}"
    code = _currency_code(currency)
    if not code:
        return numeric
    return f"{code} {numeric}"


def _amount_display(number: str, currency: str | None) -> str:
    code = _currency_code(currency)
    if not code:
        return number
    return f"{code} {number}"


def _add_amount(
    findings: list[Finding],
    spans: list[tuple[int, int]],
    start: int,
    end: int,
    number: str,
    currency: str | None,
) -> None:
    if _overlaps(start, end, spans):
        return
    spans.append((start, end))
    findings.append(
        Finding(
            "amount",
            _amount_display(number, currency),
            _amount_normalized(number, currency),
            start,
            end,
        )
    )


def find_amounts(text: str) -> list[Finding]:
    findings: list[Finding] = []
    spans: list[tuple[int, int]] = []
    for match in _AMOUNT_LABELED_RE.finditer(text):
        _add_amount(
            findings,
            spans,
            match.start(),
            match.end(),
            match.group(2),
            match.group(1),
        )
    for match in _AMOUNT_BEFORE_RE.finditer(text):
        _add_amount(
            findings,
            spans,
            match.start(),
            match.end(),
            match.group(2),
            match.group(1),
        )
    for match in _AMOUNT_AFTER_RE.finditer(text):
        _add_amount(
            findings,
            spans,
            match.start(),
            match.end(),
            match.group(1),
            match.group(2),
        )
    return findings


def _clean_payee(raw: str) -> str | None:
    name = _PAYEE_STOP.split(raw, maxsplit=1)[0]
    name = re.sub(r"\s+", " ", name).strip(" \t:-,.")
    if len(name) < 3 or not re.search(r"[A-Za-z]", name):
        return None
    # Drop a trailing label fragment such as a lone "No".
    if name.casefold() in {"no", "name", "number", "code", "due"}:
        return None
    return name


def extract_findings(text: str) -> list[Finding]:
    findings: list[Finding] = []
    ibans = find_ibans(text)
    findings.extend(ibans)
    iban_spans = [(item.start, item.end) for item in ibans]

    for match in _ACCOUNT_RE.finditer(text):
        if _overlaps(match.start(1), match.end(1), iban_spans):
            continue
        digits = match.group(1)
        findings.append(Finding("account_number", digits, digits, match.start(1), match.end(1)))

    for match in _SORT_RE.finditer(text):
        parts = re.split(r"[-\s]", match.group(1).strip())
        normalized = "-".join(parts)
        findings.append(
            Finding("sort_code", match.group(1).strip(), normalized, match.start(1), match.end(1))
        )

    for match in _IFSC_RE.finditer(text):
        code = match.group(1).upper()
        if code[4] != "0":
            continue
        findings.append(Finding("ifsc", code, code, match.start(1), match.end(1)))

    for match in _UPI_RE.finditer(text):
        upi = match.group(1)
        local, _, handle = upi.partition("@")
        if "." in handle or not local:
            continue
        normalized = f"{local}@{handle}".lower()
        findings.append(Finding("upi", upi, normalized, match.start(1), match.end(1)))

    findings.extend(find_amounts(text))

    for match in _PAYEE_RE.finditer(text):
        name = _clean_payee(match.group(1))
        if not name:
            continue
        findings.append(
            Finding("payee", name, re.sub(r"\s+", " ", name).casefold(), match.start(1), match.start(1) + len(name))
        )

    findings.sort(key=lambda item: (FIELD_ORDER.index(item.field), item.start, item.normalized))
    # One spelling per field + normalized value inside this text.
    unique: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for item in findings:
        key = (item.field, item.normalized)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def finding_context(text: str, finding: Finding) -> str:
    return _context(text, finding.start, finding.end)
