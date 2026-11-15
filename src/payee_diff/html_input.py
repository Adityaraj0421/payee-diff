"""HTML visibility. A small cascade, not a browser.

Recognises display:none, visibility:hidden, opacity:0, a zero font size,
a font colour that matches the effective background (including white on a
default white page), transparent colour, and common off-screen positioning.
External stylesheets are not fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from payee_diff.extract import extract_findings, finding_context
from payee_diff.models import (
    HIDDEN_CSS,
    RAW_ONLY,
    UNICODE_TAG,
    VISIBLE,
    Candidate,
    PartScan,
    dedupe_candidates,
)
from payee_diff.unicode_tags import prepare_text, tag_payloads

_NAMED_COLORS = {
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "red": (255, 0, 0, 255),
    "green": (0, 128, 0, 255),
    "lime": (0, 255, 0, 255),
    "blue": (0, 0, 255, 255),
    "yellow": (255, 255, 0, 255),
    "gray": (128, 128, 128, 255),
    "grey": (128, 128, 128, 255),
    "silver": (192, 192, 192, 255),
    "maroon": (128, 0, 0, 255),
    "purple": (128, 0, 128, 255),
    "fuchsia": (255, 0, 255, 255),
    "aqua": (0, 255, 255, 255),
    "navy": (0, 0, 128, 255),
    "teal": (0, 128, 128, 255),
    "olive": (128, 128, 0, 255),
    "orange": (255, 165, 0, 255),
}

# Colours within this per-channel distance count as the same.
_COLOR_TOLERANCE = 12
# A computed font size at or below this (CSS pixels) is treated as not rendered.
_ZERO_FONT_PX = 0.5

_INHERITED = {"color", "visibility", "font-size"}
_OWN_DEFAULTS = {
    "display": "",
    "background-color": "transparent",
    "background": "",
    "position": "static",
    "left": "",
    "top": "",
    "right": "",
    "bottom": "",
    "text-indent": "",
    "width": "",
    "height": "",
    "overflow": "visible",
    "opacity": "1",
    "transform": "",
    "clip": "",
}


@dataclass
class _Selector:
    compounds: list[tuple[str | None, str | None, frozenset[str]]]
    combinators: list[str]
    specificity: tuple[int, int, int]


@dataclass
class _Rule:
    selector: _Selector
    declarations: dict[str, tuple[str, bool]]
    order: int


@dataclass
class _Stylesheet:
    rules: list[_Rule] = field(default_factory=list)


def scan_html(html: str, *, part: str | None = None) -> PartScan:
    result = PartScan()
    for payload in tag_payloads(html):
        _collect(result, payload, UNICODE_TAG, "unicode tags", part)
    soup = BeautifulSoup(html, "html.parser")
    stylesheet = _parse_stylesheet("\n".join(tag.get_text() for tag in soup.find_all("style")))
    cache: dict[int, dict[str, str]] = {}

    for node in soup.descendants:
        if isinstance(node, Comment):
            text = prepare_text(str(node))
            _collect(result, text, RAW_ONLY, "comment", part)
            continue
        if not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if parent is None or not isinstance(parent, Tag):
            continue
        text = prepare_text(str(node))
        if not text.strip():
            continue
        if _ancestor_named(parent, {"script", "style", "title", "noscript"}):
            # noscript is visible in a client that does not run JavaScript.
            if _ancestor_named(parent, {"noscript"}) and not _ancestor_named(
                parent, {"script", "style", "title"}
            ):
                style = _effective_style(parent, stylesheet, cache)
                reason = _hidden_reason(parent, style, stylesheet, cache)
                if reason:
                    _collect(result, text, HIDDEN_CSS, reason, part)
                else:
                    _collect(result, text, VISIBLE, "rendered text", part)
            else:
                detail = _raw_ancestor_name(parent)
                _collect(result, text, RAW_ONLY, detail, part)
            continue
        style = _effective_style(parent, stylesheet, cache)
        reason = _hidden_reason(parent, style, stylesheet, cache)
        if reason:
            _collect(result, text, HIDDEN_CSS, reason, part)
        else:
            _collect(result, text, VISIBLE, "rendered text", part)

    for tag in soup.find_all(True):
        if tag.name == "meta":
            content = tag.get("content")
            if isinstance(content, str) and content.strip():
                _collect(result, prepare_text(content), RAW_ONLY, "meta", part)
        if tag.name == "input" and str(tag.get("type", "")).lower() == "hidden":
            value = tag.get("value")
            if isinstance(value, str) and value.strip():
                _collect(result, prepare_text(value), RAW_ONLY, "hidden input", part)
        for attr, raw in tag.attrs.items():
            if not attr.startswith("data-"):
                continue
            if isinstance(raw, list):
                text = " ".join(raw)
            else:
                text = str(raw)
            if text.strip():
                _collect(result, prepare_text(text), RAW_ONLY, f"attribute {attr}", part)
    result.candidates = dedupe_candidates(result.candidates)
    return result


def _collect(result: PartScan, text: str, origin: str, detail: str, part: str | None) -> None:
    if not text or not text.strip():
        return
    for finding in extract_findings(text):
        result.candidates.append(
            Candidate(
                field=finding.field,
                value=finding.value,
                normalized=finding.normalized,
                origin=origin,
                detail=detail,
                context=finding_context(text, finding),
                part=part,
            )
        )


def _ancestor_named(tag: Tag, names: set[str]) -> bool:
    node: Tag | None = tag
    while node is not None and isinstance(node, Tag):
        if node.name in names:
            return True
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None
    return False


def _raw_ancestor_name(tag: Tag) -> str:
    node: Tag | None = tag
    while node is not None and isinstance(node, Tag):
        if node.name in {"script", "style", "title"}:
            return node.name
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None
    return "source"


def _parse_stylesheet(css: str) -> _Stylesheet:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    sheet = _Stylesheet()
    order = 0
    for selector_text, body in _iter_rule_bodies(css):
        if selector_text.strip().startswith("@"):
            continue
        declarations = _parse_declarations(body)
        if not declarations:
            continue
        for selector in _split_selectors(selector_text):
            parsed = _parse_selector(selector)
            if parsed is None:
                continue
            sheet.rules.append(_Rule(parsed, declarations, order))
            order += 1
    return sheet


def _iter_rule_bodies(css: str):
    """Yield (prelude, body) pairs, including rules nested in @media blocks."""
    i = 0
    length = len(css)
    while i < length:
        while i < length and css[i].isspace():
            i += 1
        if i >= length:
            break
        if css.startswith("@", i):
            brace = css.find("{", i)
            if brace < 0:
                break
            header = css[i:brace].strip()
            body, end = _read_braces(css, brace)
            if header.lower().startswith("@media") or header.lower().startswith("@supports"):
                yield from _iter_rule_bodies(body)
            i = end
            continue
        brace = css.find("{", i)
        if brace < 0:
            break
        selector = css[i:brace].strip()
        body, end = _read_braces(css, brace)
        if selector:
            yield selector, body
        i = end


def _read_braces(css: str, open_at: int) -> tuple[str, int]:
    depth = 0
    i = open_at
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_at + 1 : i], i + 1
        i += 1
    return css[open_at + 1 :], len(css)


def _split_selectors(selector_text: str) -> list[str]:
    return [part.strip() for part in selector_text.split(",") if part.strip()]


def _parse_selector(selector: str) -> _Selector | None:
    selector = selector.strip()
    # Pseudo-classes, attribute selectors, and sibling combinators are not applied.
    if not selector or any(token in selector for token in (":", "[", "+", "~")):
        return None
    tokens = re.findall(r"[^>\s]+|[>]", selector)
    if not tokens or any(token == ">" for token in (tokens[0], tokens[-1])):
        return None
    compounds = []
    combinators: list[str] = []
    pending_combo = " "
    expecting_compound = True
    ids = classes = tags = 0
    for token in tokens:
        if token == ">":
            if expecting_compound:
                return None
            pending_combo = ">"
            expecting_compound = True
            continue
        compound = _parse_compound(token)
        if compound is None:
            return None
        if compounds:
            combinators.append(pending_combo)
        tag, ident, class_set = compound
        if ident:
            ids += 1
        classes += len(class_set)
        if tag:
            tags += 1
        compounds.append(compound)
        pending_combo = " "
        expecting_compound = False
    if not compounds or expecting_compound:
        return None
    return _Selector(compounds, combinators, (ids, classes, tags))


def _parse_compound(token: str) -> tuple[str | None, str | None, frozenset[str]] | None:
    match = re.fullmatch(
        r"(?P<tag>\*|[A-Za-z][A-Za-z0-9]*)?(?P<rest>(?:#[A-Za-z_][\w-]*|\.[A-Za-z_][\w-]*)*)",
        token,
    )
    if not match:
        return None
    tag = match.group("tag")
    rest = match.group("rest") or ""
    if tag == "*":
        tag = None
    ident = None
    classes: list[str] = []
    for piece in re.findall(r"[#.][^#.]+", rest):
        if piece.startswith("#"):
            if ident is not None:
                return None
            ident = piece[1:]
        else:
            classes.append(piece[1:])
    if tag is None and ident is None and not classes:
        return None
    return (tag.lower() if tag else None, ident, frozenset(classes))


def _parse_declarations(body: str) -> dict[str, tuple[str, bool]]:
    declarations: dict[str, tuple[str, bool]] = {}
    for part in _split_declarations(body):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if not name or not value:
            continue
        important = False
        if value.lower().endswith("!important"):
            important = True
            value = value[: -len("!important")].strip()
        declarations[name] = (value, important)
    return declarations


def _split_declarations(body: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        if ch == ";" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _compound_matches(
    compound: tuple[str | None, str | None, frozenset[str]],
    tag: Tag,
) -> bool:
    want_tag, ident, classes = compound
    if want_tag and (tag.name or "").lower() != want_tag:
        return False
    if ident and tag.get("id") != ident:
        return False
    have = set(tag.get("class") or [])
    return classes.issubset(have)


def _selector_matches(selector: _Selector, tag: Tag) -> bool:
    compounds = selector.compounds
    if not _compound_matches(compounds[-1], tag):
        return False
    node: Tag | None = tag
    for compound, combinator in zip(reversed(compounds[:-1]), reversed(selector.combinators)):
        parent = node.parent if node is not None else None
        if combinator == ">":
            if not isinstance(parent, Tag) or not _compound_matches(compound, parent):
                return False
            node = parent
            continue
        found = False
        while isinstance(parent, Tag):
            if _compound_matches(compound, parent):
                node = parent
                found = True
                break
            parent = parent.parent if isinstance(parent.parent, Tag) else None
        if not found:
            return False
    return True


def _specified(tag: Tag, stylesheet: _Stylesheet) -> dict[str, str]:
    ranked: dict[str, tuple[tuple[int, int, int, int, int], str]] = {}

    def consider(prop: str, value: str, important: bool, specificity: tuple[int, int, int], order: int) -> None:
        key = (1 if important else 0, *specificity, order)
        current = ranked.get(prop)
        if current is None or key >= current[0]:
            ranked[prop] = (key, value)

    if tag.has_attr("hidden"):
        consider("display", "none", False, (0, 0, 1), -30)
    bgcolor = tag.get("bgcolor")
    if isinstance(bgcolor, str):
        consider("background-color", bgcolor, False, (0, 0, 1), -20)
    if tag.name == "font":
        color = tag.get("color")
        if isinstance(color, str):
            consider("color", color, False, (0, 0, 1), -10)
    for rule in stylesheet.rules:
        if not _selector_matches(rule.selector, tag):
            continue
        for prop, (value, important) in rule.declarations.items():
            consider(prop, value, important, rule.selector.specificity, rule.order)
    style_attr = tag.get("style")
    if isinstance(style_attr, str):
        for prop, (value, important) in _parse_declarations(style_attr).items():
            consider(prop, value, important, (1, 0, 0), 10**6)
    return {prop: value for prop, (_key, value) in ranked.items()}


def _effective_style(tag: Tag, stylesheet: _Stylesheet, cache: dict[int, dict[str, str]]) -> dict[str, str]:
    key = id(tag)
    cached = cache.get(key)
    if cached is not None:
        return cached
    parent = tag.parent if isinstance(tag.parent, Tag) else None
    if parent is not None and parent.name is not None:
        base = dict(_effective_style(parent, stylesheet, cache))
    else:
        base = {
            "color": "#000000",
            "visibility": "visible",
            "font-size": "16px",
        }
    for prop, default in _OWN_DEFAULTS.items():
        base[prop] = default
    for prop, value in _specified(tag, stylesheet).items():
        if value.lower() in {"inherit", "unset"}:
            continue
        if value.lower() == "initial":
            continue
        base[prop] = value
    # `font` shorthand can carry a zero size when font-size itself was not set.
    if "font" in _specified(tag, stylesheet) and "font-size" not in _specified(tag, stylesheet):
        size = _font_shorthand_size(_specified(tag, stylesheet)["font"])
        if size:
            base["font-size"] = size
    cache[key] = base
    return base


def _font_shorthand_size(value: str) -> str | None:
    match = re.search(r"(?:^|\s)(\d+(?:\.\d+)?)(px|pt|em|rem|%)\b", value, flags=re.I)
    if not match:
        return None
    return match.group(1) + match.group(2)


def _hidden_reason(
    tag: Tag,
    style: dict[str, str],
    stylesheet: _Stylesheet,
    cache: dict[int, dict[str, str]],
) -> str | None:
    node: Tag | None = tag
    while isinstance(node, Tag) and node.name is not None:
        ancestor_style = style if node is tag else _effective_style(node, stylesheet, cache)
        display = ancestor_style.get("display", "").strip().lower()
        if display == "none":
            return "display:none"
        visibility = ancestor_style.get("visibility", "").strip().lower()
        if visibility in {"hidden", "collapse"}:
            return "visibility:hidden"
        if _opacity_zero(ancestor_style.get("opacity", "1")):
            return "opacity:0"
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None
    if _font_size_zero(style.get("font-size", "")):
        return "font-size:0"
    if _is_offscreen(style):
        return "off-screen"
    colour = _parse_color(style.get("color", ""))
    if colour is not None and colour[3] <= 20:
        return "transparent colour"
    background = _effective_background(tag, stylesheet, cache)
    if colour is not None and _colors_close(colour[:3], background):
        return "color matches background"
    return None


def _effective_background(
    tag: Tag,
    stylesheet: _Stylesheet,
    cache: dict[int, dict[str, str]],
) -> tuple[int, int, int]:
    node: Tag | None = tag
    while isinstance(node, Tag) and node.name is not None:
        style = _effective_style(node, stylesheet, cache)
        for prop in ("background-color", "background"):
            colour = _first_color(style.get(prop, ""))
            if colour is not None and colour[3] > 20:
                return colour[:3]
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None
    return (255, 255, 255)


def _first_color(value: str) -> tuple[int, int, int, int] | None:
    if not value or value.lower() == "transparent":
        return None
    # Pull the first colour token out of a background shorthand.
    match = re.search(
        r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|[a-zA-Z]+)",
        value,
    )
    if not match:
        return None
    return _parse_color(match.group(1))


def _parse_color(value: str) -> tuple[int, int, int, int] | None:
    raw = value.strip().lower()
    if not raw or raw in {"transparent", "inherit", "initial", "unset", "currentcolor"}:
        return None
    if raw in _NAMED_COLORS:
        return _NAMED_COLORS[raw]
    hex_match = re.fullmatch(r"#([0-9a-f]{3,8})", raw)
    if hex_match:
        hex_digits = hex_match.group(1)
        if len(hex_digits) == 3:
            hex_digits = "".join(ch * 2 for ch in hex_digits)
        if len(hex_digits) == 4:
            hex_digits = "".join(ch * 2 for ch in hex_digits)
        if len(hex_digits) == 6:
            hex_digits += "ff"
        if len(hex_digits) != 8:
            return None
        return tuple(int(hex_digits[i : i + 2], 16) for i in range(0, 8, 2))  # type: ignore[return-value]
    func = re.fullmatch(r"rgba?\(([^)]+)\)", raw)
    if not func:
        return None
    pieces = [piece.strip() for piece in func.group(1).replace("/", " ").split(",") if piece.strip()]
    if len(pieces) < 3:
        pieces = func.group(1).replace("/", " ").split()
    if len(pieces) < 3:
        return None
    channels: list[int] = []
    for piece in pieces[:3]:
        if piece.endswith("%"):
            channels.append(int(round(float(piece[:-1]) * 2.55)))
        else:
            channels.append(int(round(float(piece))))
    alpha = 255
    if len(pieces) >= 4:
        alpha_token = pieces[3]
        if alpha_token.endswith("%"):
            alpha = int(round(float(alpha_token[:-1]) * 2.55))
        else:
            alpha_value = float(alpha_token)
            alpha = int(round(alpha_value * 255 if alpha_value <= 1 else alpha_value))
    return (channels[0], channels[1], channels[2], max(0, min(255, alpha)))


def _colors_close(left: tuple[int, int, int], right: tuple[int, int, int]) -> bool:
    return all(abs(a - b) <= _COLOR_TOLERANCE for a, b in zip(left, right))


def _parse_px(value: str) -> float | None:
    raw = value.strip().lower()
    match = re.fullmatch(r"(-?(?:\d+\.?\d*|\.\d+))(px|pt|em|rem|%)?", raw)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "px"
    if number == 0:
        return 0.0
    if unit == "px":
        return number
    if unit == "pt":
        return number * 96 / 72
    if unit in {"em", "rem"}:
        return number * 16
    return None


def _font_size_zero(value: str) -> bool:
    size = _parse_px(value)
    return size is not None and size <= _ZERO_FONT_PX


def _opacity_zero(value: str) -> bool:
    try:
        return float(value.strip()) <= 0.01
    except ValueError:
        return False


def _is_offscreen(style: dict[str, str]) -> bool:
    position = style.get("position", "").strip().lower()
    offsets = [
        _parse_px(style.get(prop, ""))
        for prop in ("left", "top", "right", "bottom")
    ]
    if position in {"absolute", "fixed"} and any(
        offset is not None and offset <= -50 for offset in offsets
    ):
        return True
    indent = _parse_px(style.get("text-indent", ""))
    if indent is not None and indent <= -50:
        return True
    overflow = style.get("overflow", "").strip().lower()
    width = _parse_px(style.get("width", ""))
    height = _parse_px(style.get("height", ""))
    if overflow == "hidden" and (
        (width is not None and width <= 1) or (height is not None and height <= 1)
    ):
        return True
    transform = style.get("transform", "")
    match = re.search(
        r"translate(?:3d|[xy])?\(\s*(-?\d+(?:\.\d+)?)",
        transform,
        flags=re.I,
    )
    if match and float(match.group(1)) <= -50:
        return True
    clip = re.sub(r"\s+", "", style.get("clip", "").lower())
    if clip.startswith("rect(0") and clip.count(",0") >= 2:
        return True
    return False
