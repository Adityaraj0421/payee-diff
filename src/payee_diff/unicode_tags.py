"""Unicode Tags (U+E0000..U+E007F).

U+E0020..U+E007E mirror ASCII 0x20..0x7E and do not render in normal text.
"""

from __future__ import annotations

import re

_TAG_RUN = re.compile(r"[\U000E0000-\U000E007F]+")
_STRIP = re.compile(r"[\U000E0000-\U000E007F]")

# Characters that are invisible but are not the Tags block. Stripped before
# matching so a zero-width break does not hide an otherwise ordinary value.
# This is not a separate finding: bidi and homoglyph spoofing are out of scope.
_INVISIBLE_FORMAT = re.compile(
    "[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)


def encode_tag_payload(text: str) -> str:
    """Encode printable ASCII as Unicode Tags. Used by the fixture generator."""
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if not 0x20 <= code <= 0x7E:
            raise ValueError(f"cannot encode {ch!r} as a Unicode tag")
        chars.append(chr(0xE0000 + code))
    return "".join(chars)


def decode_tag_run(run: str) -> str:
    chars: list[str] = []
    for ch in run:
        code = ord(ch) - 0xE0000
        if 0x20 <= code <= 0x7E:
            chars.append(chr(code))
    return "".join(chars)


def tag_payloads(text: str) -> list[str]:
    payloads: list[str] = []
    for run in _TAG_RUN.findall(text):
        decoded = decode_tag_run(run).strip()
        if decoded:
            payloads.append(decoded)
    return payloads


def strip_tag_chars(text: str) -> str:
    return _STRIP.sub("", text)


def strip_invisible_format(text: str) -> str:
    return _INVISIBLE_FORMAT.sub("", text)


def prepare_text(text: str) -> str:
    """Drop tag characters and invisible format characters before matching."""
    return strip_invisible_format(strip_tag_chars(text)).replace("\xa0", " ")
