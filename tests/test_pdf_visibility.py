from payee_diff.iban import make_iban
from payee_diff.models import RAW_ONLY, VISIBLE, build_report
from payee_diff.pdf_input import scan_pdf
from pdf_factory import build_pdf, filled_rect, image_draw, sample_image, text_block

IBAN = make_iban("GB", "FAKE00112210293847")
OTHER = make_iban("DE", "000000009988776655")


def _scan(content: str, **page):
    page.setdefault("content", content)
    return scan_pdf(build_pdf([page]))


def test_black_text_is_visible():
    scan = _scan(text_block([f"IBAN: {IBAN}"]))
    assert [(c.origin, c.normalized) for c in scan.candidates] == [(VISIBLE, IBAN)]
    assert scan.unchecked == []


def test_white_text_matches_background():
    scan = _scan(text_block([f"IBAN: {OTHER}"], color=(1, 1, 1)))
    assert len(scan.candidates) == 1
    candidate = scan.candidates[0]
    assert candidate.origin == RAW_ONLY
    assert candidate.detail == "fill colour matches background"
    assert candidate.normalized == OTHER


def test_render_mode_3_is_raw_only_and_still_checked():
    scan = _scan(text_block([f"IBAN: {OTHER}"], render=3))
    candidate = scan.candidates[0]
    assert candidate.origin == RAW_ONLY
    assert candidate.detail == "invisible render mode 3"
    assert scan.unchecked == []
    report = build_report(path="x", kind="pdf", sha256=None, scan=scan)
    assert report.exit_code == 1
    assert report.not_checked is False


def test_text_outside_the_page_box():
    scan = _scan(text_block([f"IBAN: {OTHER}"], y=-40))
    candidate = scan.candidates[0]
    assert candidate.origin == RAW_ONLY
    assert candidate.detail == "outside page box"


def test_text_outside_the_crop_box():
    content = text_block([f"IBAN: {IBAN}"], y=740) + text_block(
        [f"IBAN: {OTHER}"], y=40
    )
    scan = _scan(content, cropbox=(0, 200, 612, 792))
    by_value = {c.normalized: c for c in scan.candidates}
    assert by_value[IBAN].origin == VISIBLE
    assert by_value[OTHER].origin == RAW_ONLY
    assert by_value[OTHER].detail == "outside page box"


def test_fill_colour_matches_a_painted_rectangle():
    content = filled_rect(60, 680, 400, 80, (1, 0, 0)) + text_block(
        [f"IBAN: {OTHER}"], x=72, y=720, color=(1, 0, 0)
    )
    scan = _scan(content)
    candidate = scan.candidates[0]
    assert candidate.origin == RAW_ONLY
    assert candidate.detail == "fill colour matches background"


def test_image_only_is_not_checked():
    pixels, width, height = sample_image()
    scan = scan_pdf(
        build_pdf(
            [
                {
                    "content": image_draw(),
                    "image": pixels,
                    "image_size": (width, height),
                }
            ]
        )
    )
    assert scan.candidates == []
    assert scan.selectable_characters == 0
    assert scan.images == 1
    assert scan.unchecked == ["no selectable text, not checked"]
    report = build_report(path="x", kind="pdf", sha256=None, scan=scan)
    assert report.exit_code == 3
    assert report.message == "no selectable text, not checked"


def test_text_page_plus_image_page_is_not_a_pass():
    pixels, width, height = sample_image()
    data = build_pdf(
        [
            {"content": text_block([f"IBAN: {IBAN}"])},
            {
                "content": image_draw(),
                "image": pixels,
                "image_size": (width, height),
            },
        ]
    )
    scan = scan_pdf(data)
    report = build_report(path="x", kind="pdf", sha256=None, scan=scan)
    assert any(c.normalized == IBAN and c.origin == VISIBLE for c in scan.candidates)
    assert report.exit_code == 3
    assert report.not_checked is True
    assert "no selectable text, not checked" in report.message
