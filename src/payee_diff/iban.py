"""IBAN checks: country length plus the ISO 13616 mod-97 rule.

No registry lookup. A passing checksum only means the check digits agree.
"""

from __future__ import annotations

import re

# Lengths from the IBAN registry. Unknown countries are rejected.
IBAN_LENGTHS: dict[str, int] = {
    "AL": 28,
    "AD": 24,
    "AT": 20,
    "AZ": 28,
    "BH": 22,
    "BE": 16,
    "BA": 20,
    "BR": 29,
    "BG": 22,
    "CR": 22,
    "HR": 21,
    "CY": 28,
    "CZ": 24,
    "DK": 18,
    "DO": 28,
    "EE": 20,
    "FO": 18,
    "FI": 18,
    "FR": 27,
    "GE": 22,
    "DE": 22,
    "GI": 23,
    "GR": 27,
    "GL": 18,
    "GT": 28,
    "HU": 28,
    "IS": 26,
    "IE": 22,
    "IL": 23,
    "IT": 27,
    "JO": 30,
    "KZ": 20,
    "XK": 20,
    "KW": 30,
    "LV": 21,
    "LB": 28,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "MT": 31,
    "MR": 27,
    "MU": 30,
    "MC": 27,
    "MD": 24,
    "ME": 22,
    "NL": 18,
    "MK": 19,
    "NO": 15,
    "PK": 24,
    "PS": 29,
    "PL": 28,
    "PT": 25,
    "QA": 29,
    "RO": 24,
    "SM": 27,
    "SA": 24,
    "RS": 22,
    "SK": 24,
    "SI": 19,
    "ES": 24,
    "SE": 24,
    "CH": 21,
    "TN": 24,
    "TR": 26,
    "AE": 23,
    "GB": 22,
    "VA": 22,
    "VG": 24,
}

_COMPACT = re.compile(r"[^A-Za-z0-9]")


def compact_iban(value: str) -> str:
    return _COMPACT.sub("", value).upper()


def _to_digits(value: str) -> str:
    digits: list[str] = []
    for ch in value:
        if ch.isdigit():
            digits.append(ch)
        elif "A" <= ch <= "Z":
            digits.append(str(ord(ch) - 55))
        else:
            return ""
    return "".join(digits)


def mod97(value: str) -> int:
    digits = _to_digits(value)
    if not digits:
        return -1
    remainder = 0
    for ch in digits:
        remainder = (remainder * 10 + int(ch)) % 97
    return remainder


def iban_is_valid(value: str) -> bool:
    compact = compact_iban(value)
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", compact or ""):
        return False
    expected = IBAN_LENGTHS.get(compact[:2])
    if expected is None or len(compact) != expected:
        return False
    rearranged = compact[4:] + compact[:4]
    return mod97(rearranged) == 1


def make_iban(country: str, bban: str) -> str:
    """Build a checksum-valid IBAN from a country code and BBAN.

    Used for fixtures. The result is valid-format, not a real account.
    """
    country = country.upper()
    bban = compact_iban(bban)
    if country not in IBAN_LENGTHS:
        raise ValueError(f"unknown IBAN country {country}")
    if len(country) + 2 + len(bban) != IBAN_LENGTHS[country]:
        raise ValueError(
            f"{country} BBAN must produce length {IBAN_LENGTHS[country]}, "
            f"got {len(country) + 2 + len(bban)}"
        )
    remainder = mod97(bban + country + "00")
    if remainder < 0:
        raise ValueError("BBAN must be alphanumeric")
    check = 98 - remainder
    iban = f"{country}{check:02d}{bban}"
    if not iban_is_valid(iban):
        raise ValueError("generated IBAN failed validation")
    return iban
