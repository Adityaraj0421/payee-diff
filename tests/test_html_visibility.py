from payee_diff.iban import make_iban
from payee_diff.models import HIDDEN_CSS, RAW_ONLY, UNICODE_TAG, VISIBLE, build_report
from payee_diff.html_input import scan_html
from payee_diff.unicode_tags import encode_tag_payload

IBAN = make_iban("GB", "FAKE00112210293847")
OTHER = make_iban("DE", "000000009988776655")


def _origins(html: str) -> dict[tuple[str, str], str]:
    scan = scan_html(html)
    return {(item.field, item.normalized): item.origin for item in scan.candidates}


def _details(html: str) -> dict[tuple[str, str], str]:
    scan = scan_html(html)
    return {(item.field, item.normalized): item.detail for item in scan.candidates}


def test_plain_paragraph_is_visible():
    html = f"<p>IBAN: {IBAN}</p>"
    assert _origins(html)[("iban", IBAN)] == VISIBLE


def test_display_none_class_rule():
    html = (
        "<style>.secret { display: none }</style>"
        f"<p>IBAN: {IBAN}</p>"
        f"<span class=\"secret\">IBAN: {OTHER}</span>"
    )
    origins = _origins(html)
    assert origins[("iban", IBAN)] == VISIBLE
    assert origins[("iban", OTHER)] == HIDDEN_CSS
    assert _details(html)[("iban", OTHER)] == "display:none"


def test_visibility_hidden_and_zero_font_and_offscreen():
    html = (
        f"<p style=\"visibility:hidden\">IBAN: {IBAN}</p>"
        f"<p style=\"font-size:0\">IBAN: {OTHER}</p>"
    )
    details = _details(html)
    assert details[("iban", IBAN)] == "visibility:hidden"
    assert details[("iban", OTHER)] == "font-size:0"

    moved = (
        f"<p style=\"position:absolute;left:-9999px\">IBAN: {IBAN}</p>"
    )
    assert _details(moved)[("iban", IBAN)] == "off-screen"


def test_white_on_white_and_explicit_match():
    white = f"<p style=\"color:#ffffff\">IBAN: {IBAN}</p>"
    assert _details(white)[("iban", IBAN)] == "color matches background"
    red = (
        "<div style=\"background:#ff0000;color:#ff0000\">"
        f"IBAN: {IBAN}</div>"
    )
    assert _details(red)[("iban", IBAN)] == "color matches background"
    contrast = (
        "<div style=\"background:#000000;color:#ffffff\">"
        f"IBAN: {IBAN}</div>"
    )
    assert _origins(contrast)[("iban", IBAN)] == VISIBLE


def test_important_color_beats_inline():
    html = (
        "<style>p { color: #ffffff !important; }</style>"
        "<body style=\"background:#ffffff\">"
        f"<p style=\"color:#000000\">IBAN: {IBAN}</p>"
        "</body>"
    )
    assert _details(html)[("iban", IBAN)] == "color matches background"


def test_comment_script_and_hidden_input_are_raw_only():
    html = (
        f"<p>IBAN: {IBAN}</p>"
        f"<!-- IBAN: {OTHER} -->"
        f"<script>var x = 'IBAN: {OTHER}'</script>"
        f"<input type=\"hidden\" value=\"IBAN: {OTHER}\">"
    )
    scan = scan_html(html)
    visible = [c for c in scan.candidates if c.origin == VISIBLE]
    raw = [c for c in scan.candidates if c.origin == RAW_ONLY]
    assert [c.normalized for c in visible] == [IBAN]
    assert raw
    assert {c.normalized for c in raw} == {OTHER}
    assert {c.detail for c in raw} >= {"comment", "script", "hidden input"}


def test_unicode_tags_are_their_own_origin():
    payload = encode_tag_payload(f"IBAN: {OTHER}")
    html = f"<p>IBAN: {IBAN}{payload}</p>"
    origins = _origins(html)
    assert origins[("iban", IBAN)] == VISIBLE
    assert origins[("iban", OTHER)] == UNICODE_TAG


def test_same_hidden_value_is_not_a_conflict():
    html = (
        f"<p>IBAN: {IBAN}</p>"
        f"<p style=\"display:none\">IBAN: {IBAN}</p>"
    )
    report = build_report(path="x", kind="html", sha256=None, scan=scan_html(html))
    assert report.exit_code == 0
    assert report.status == "no_conflict"
    data = report.to_dict()
    assert data["fields"][0]["hidden"][0]["normalized"] == IBAN
    assert data["conflicts"] == []


def test_hidden_only_value_is_a_conflict():
    html = f"<p style=\"display:none\">IBAN: {OTHER}</p>"
    report = build_report(path="x", kind="html", sha256=None, scan=scan_html(html))
    assert report.exit_code == 1
    assert report.to_dict()["conflicts"][0]["reason"] == (
        "payment value appears only in hidden or raw text"
    )


def test_opacity_ancestor_hides_child():
    html = f"<div style=\"opacity:0\"><p>IBAN: {IBAN}</p></div>"
    assert _details(html)[("iban", IBAN)] == "opacity:0"
