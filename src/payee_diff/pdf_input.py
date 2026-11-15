"""PDF text-layer check.

Glyphs come from the text operators. A glyph is raw-only when it is in
render mode 3 or 7 (not painted), falls outside the crop box, is smaller
than half a point, or its painted colour matches the fill behind it
(default page fill is white). There is no raster comparison and no OCR.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from pdfminer.converter import PDFLayoutAnalyzer
from pdfminer.layout import LTChar, LTFigure, LTImage, LTRect
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.psparser import PSException
from pdfminer.utils import apply_matrix_rect

from payee_diff.extract import extract_findings, finding_context
from payee_diff.models import (
    NOT_CHECKED_MESSAGE,
    RAW_ONLY,
    UNICODE_TAG,
    VISIBLE,
    Candidate,
    PartScan,
    dedupe_candidates,
)
from payee_diff.unicode_tags import prepare_text, tag_payloads

# Half a point. Below this, the glyph is not something a person can read.
_MIN_VISIBLE_SIZE = 0.5
_COLOR_TOLERANCE = 12
_PAGE_WHITE = (255, 255, 255)


class PdfReadError(Exception):
    pass


@dataclass
class _Glyph:
    text: str
    x0: float
    x1: float
    y0: float
    size: float
    origin: str
    detail: str


class _Analyzer(PDFLayoutAnalyzer):
    def __init__(self, rsrcmgr: PDFResourceManager) -> None:
        super().__init__(rsrcmgr, laparams=None)
        self.pages = []
        self._render_mode = 0

    def begin_page(self, page, ctm) -> None:  # type: ignore[no-untyped-def]
        super().begin_page(page, ctm)
        try:
            x0, y0, x1, y1 = apply_matrix_rect(ctm, page.cropbox)
            box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        except (TypeError, ValueError):
            box = tuple(self.cur_item.bbox)
        self.cur_item.visible_box = box  # type: ignore[attr-defined]

    def render_string(self, textstate, seq, ncs, graphicstate) -> None:  # type: ignore[no-untyped-def]
        try:
            self._render_mode = int(textstate.render)
        except (TypeError, ValueError):
            self._render_mode = 0
        super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate) -> float:  # type: ignore[no-untyped-def]
        advance = super().render_char(
            matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate
        )
        children = list(self.cur_item)
        if children and isinstance(children[-1], LTChar):
            children[-1].render_mode = self._render_mode  # type: ignore[attr-defined]
        return advance

    def receive_layout(self, ltpage) -> None:  # type: ignore[no-untyped-def]
        self.pages.append(ltpage)


def scan_pdf(data: bytes, *, part: str | None = None) -> PartScan:
    try:
        pages = _interpret(data)
    except (PDFEncryptionError, PDFPasswordIncorrect) as exc:
        raise PdfReadError("encrypted PDF is not supported") from exc
    except PSException as exc:
        raise PdfReadError(f"could not read PDF: {exc}") from exc

    result = PartScan(saw_pdf=True, pdf_pages=len(pages))
    empty_pages: list[int] = []
    for page in pages:
        glyphs, images = _page_glyphs(page)
        result.images += images
        selectable = sum(1 for glyph in glyphs if glyph.text.strip())
        result.selectable_characters += selectable
        page_no = int(getattr(page, "pageid", 0) or 0)
        if selectable == 0:
            empty_pages.append(page_no)
            continue
        _emit_glyphs(result, glyphs, page_no, part)

    if result.selectable_characters == 0:
        result.unchecked.append(NOT_CHECKED_MESSAGE)
    else:
        for page_no in empty_pages:
            result.unchecked.append(f"page {page_no}: {NOT_CHECKED_MESSAGE}")
    result.candidates = dedupe_candidates(result.candidates)
    return result


def _interpret(data: bytes):
    resource_manager = PDFResourceManager()
    device = _Analyzer(resource_manager)
    interpreter = PDFPageInterpreter(resource_manager, device)
    with io.BytesIO(data) as handle:
        for page in PDFPage.get_pages(handle, check_extractable=False):
            interpreter.process_page(page)
    return device.pages


def _page_glyphs(page) -> tuple[list[_Glyph], int]:
    glyphs: list[_Glyph] = []
    images = [0]
    rects: list[LTRect] = []
    visible_box = getattr(page, "visible_box", tuple(page.bbox))
    _walk(page, rects, glyphs, images, visible_box)
    return glyphs, images[0]


def _walk(container, rects, glyphs, images, visible_box) -> None:
    for child in container:
        if isinstance(child, LTFigure):
            _walk(child, rects, glyphs, images, visible_box)
        elif isinstance(child, LTImage):
            images[0] += 1
        elif isinstance(child, LTRect) and child.fill:
            rects.append(child)
        elif isinstance(child, LTChar):
            origin, detail = _classify(child, rects, visible_box)
            glyphs.append(
                _Glyph(
                    text=child.get_text(),
                    x0=float(child.x0),
                    x1=float(child.x1),
                    y0=float(child.y0),
                    size=float(child.size),
                    origin=origin,
                    detail=detail,
                )
            )


def _classify(char: LTChar, rects: list[LTRect], visible_box: tuple) -> tuple[str, str]:
    mode = int(getattr(char, "render_mode", 0) or 0)
    if mode in {3, 7}:
        return RAW_ONLY, f"invisible render mode {mode}"
    if not _on_page(char, visible_box):
        return RAW_ONLY, "outside page box"
    if float(char.size) <= _MIN_VISIBLE_SIZE:
        return RAW_ONLY, "font size too small to render"
    background = _background(char, rects)
    painted = _painted_colors(mode, char)
    if painted and all(_close(color, background) for color in painted):
        return RAW_ONLY, "fill colour matches background"
    return VISIBLE, "rendered text"


def _on_page(char: LTChar, box: tuple) -> bool:
    x0, y0, x1, y1 = box
    return not (char.x1 < x0 or char.x0 > x1 or char.y1 < y0 or char.y0 > y1)


def _background(char: LTChar, rects: list[LTRect]) -> tuple[int, int, int]:
    cx = (float(char.x0) + float(char.x1)) / 2
    cy = (float(char.y0) + float(char.y1)) / 2
    found = _PAGE_WHITE
    for rect in rects:
        if rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1:
            colour = _rgb(rect.non_stroking_color)
            if colour is not None:
                found = colour
    return found


def _painted_colors(mode: int, char: LTChar) -> list[tuple[int, int, int]]:
    fill = _rgb(char.graphicstate.ncolor)
    stroke = _rgb(char.graphicstate.scolor)
    if mode == 1 or mode == 5:
        return [stroke] if stroke is not None else []
    if mode in {2, 6}:
        return [color for color in (fill, stroke) if color is not None]
    return [fill] if fill is not None else []


def _rgb(color) -> tuple[int, int, int] | None:
    if color is None:
        return None
    if isinstance(color, (int, float)):
        return _scale((float(color), float(color), float(color)))
    if isinstance(color, (list, tuple)):
        if len(color) == 1:
            return _rgb(color[0])
        if len(color) == 3:
            return _scale(tuple(float(channel) for channel in color))
        if len(color) == 4:
            cyan, magenta, yellow, black = (float(channel) for channel in color)
            return (
                int(round(255 * (1 - cyan) * (1 - black))),
                int(round(255 * (1 - magenta) * (1 - black))),
                int(round(255 * (1 - yellow) * (1 - black))),
            )
    return None


def _scale(channels: tuple[float, float, float]) -> tuple[int, int, int]:
    if max(channels) > 1:
        scaled = channels
    else:
        scaled = tuple(channel * 255 for channel in channels)
    return tuple(max(0, min(255, int(round(channel)))) for channel in scaled)  # type: ignore[return-value]


def _close(left: tuple[int, int, int], right: tuple[int, int, int]) -> bool:
    return all(abs(a - b) <= _COLOR_TOLERANCE for a, b in zip(left, right))


def _emit_glyphs(result: PartScan, glyphs: list[_Glyph], page_no: int, part: str | None) -> None:
    lines: list[list[_Glyph]] = []
    for glyph in sorted(glyphs, key=lambda item: (-round(item.y0), item.x0)):
        if lines and abs(glyph.y0 - lines[-1][0].y0) <= 2:
            lines[-1].append(glyph)
        else:
            lines.append([glyph])
    buckets: dict[tuple[str, str], list[str]] = {}
    for line in lines:
        line.sort(key=lambda item: item.x0)
        runs: list[tuple[str, str, str]] = []
        buffer: list[str] = []
        current: tuple[str, str] | None = None
        previous: _Glyph | None = None
        for glyph in line:
            key = (glyph.origin, glyph.detail)
            if current is not None and key != current:
                runs.append((current[0], current[1], "".join(buffer)))
                buffer = []
                previous = None
            if (
                previous is not None
                and glyph.x0 - previous.x1 > max(1.5, previous.size * 0.3)
                and buffer
                and not buffer[-1].isspace()
                and not glyph.text.isspace()
            ):
                buffer.append(" ")
            buffer.append(glyph.text)
            current = key
            previous = glyph
        if current is not None and buffer:
            runs.append((current[0], current[1], "".join(buffer)))
        for origin, detail, text in runs:
            buckets.setdefault((origin, detail), []).append(text)
    for (origin, detail), parts in buckets.items():
        text = "\n".join(parts)
        for payload in tag_payloads(text):
            _collect(result, payload, UNICODE_TAG, "unicode tags", page_no, part)
        _collect(result, prepare_text(text), origin, detail, page_no, part)


def _collect(
    result: PartScan,
    text: str,
    origin: str,
    detail: str,
    page_no: int,
    part: str | None,
) -> None:
    if not text.strip():
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
                page=page_no,
                part=part,
            )
        )
