import json
from pathlib import Path

from payee_diff.cli import main
from payee_diff.iban import make_iban

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

VISIBLE_IBAN = make_iban("GB", "FAKE00112210293847")
HIDDEN_IBAN = make_iban("DE", "000000009988776655")

VISIBLE = {
    ("iban", VISIBLE_IBAN),
    ("account_number", "10293847"),
    ("sort_code", "00-11-22"),
    ("ifsc", "FAKE0NWP123"),
    ("upi", "northwind.paper@upi"),
    ("amount", "GBP 1250.00"),
    ("payee", "northwind paper ltd"),
}
HIDDEN = {
    ("iban", HIDDEN_IBAN),
    ("amount", "GBP 9875.00"),
    ("payee", "grey harbor supplies gmbh"),
}

CLEAN = ["clean.pdf", "clean.html", "clean.eml"]
ATTACKS = {
    "html_white_on_white.html": "hidden-css",
    "html_display_none.html": "hidden-css",
    "html_unicode_tags.html": "unicode-tag",
    "pdf_white_text.pdf": "raw-only",
    "pdf_render_mode_3.pdf": "raw-only",
    "eml_hidden_span.eml": "hidden-css",
}


def _run(name: str) -> tuple[int, dict]:
    from io import StringIO
    from contextlib import redirect_stdout

    buffer = StringIO()
    with redirect_stdout(buffer):
        code = main([str(FIXTURES / name), "--format", "json"])
    return code, json.loads(buffer.getvalue())


def _pairs(report: dict, origin: str) -> set[tuple[str, str]]:
    return {
        (item["field"], item["normalized"])
        for item in report["candidates"]
        if item["origin"] == origin
    }


def test_clean_fixtures_have_visible_values_and_exit_0():
    for name in CLEAN:
        code, report = _run(name)
        assert code == 0, name
        assert report["exit_code"] == 0
        assert report["status"] == "no_conflict"
        assert report["not_checked"] is False
        assert report["conflicts"] == []
        assert _pairs(report, "visible") == VISIBLE
        assert _pairs(report, "raw-only") == set()
        assert _pairs(report, "hidden-css") == set()
        assert _pairs(report, "unicode-tag") == set()


def test_attack_fixtures_conflict_on_hidden_payment_fields():
    for name, origin in ATTACKS.items():
        code, report = _run(name)
        assert code == 1, name
        assert report["status"] == "conflict"
        assert report["not_checked"] is False
        assert _pairs(report, "visible") == VISIBLE, name
        assert _pairs(report, origin) == HIDDEN, name
        other = {"visible", "raw-only", "hidden-css", "unicode-tag"} - {"visible", origin}
        for leftover in other:
            assert _pairs(report, leftover) == set(), (name, leftover)
        conflict_fields = {item["field"] for item in report["conflicts"]}
        assert conflict_fields == {"iban", "amount", "payee"}
        for item in report["conflicts"]:
            assert item["reason"] == "hidden or raw-only value differs from the visible value"


def test_pdf_attack_details():
    _, white = _run("pdf_white_text.pdf")
    _, invisible = _run("pdf_render_mode_3.pdf")
    white_details = {item["detail"] for item in white["candidates"] if item["origin"] == "raw-only"}
    mode_details = {
        item["detail"] for item in invisible["candidates"] if item["origin"] == "raw-only"
    }
    assert white_details == {"fill colour matches background"}
    assert mode_details == {"invisible render mode 3"}


def test_image_only_fixture_is_not_a_pass():
    code, report = _run("image_only.pdf")
    assert code == 3
    assert report["status"] == "not_checked"
    assert report["not_checked"] is True
    assert report["message"] == "no selectable text, not checked"
    assert report["candidates"] == []
    assert report["conflicts"] == []
    assert report["stats"]["selectable_characters"] == 0
    assert report["stats"]["images"] == 1
    assert report["stats"]["pdf_pages"] == 1


def test_generator_reproduces_committed_fixtures():
    import generate_fixtures as generator

    expected = {
        "clean.pdf": generator.visible_pdf(),
        "clean.html": generator.clean_html(),
        "clean.eml": generator.clean_eml(),
        "html_white_on_white.html": generator.white_on_white_html(),
        "html_display_none.html": generator.display_none_html(),
        "html_unicode_tags.html": generator.unicode_tags_html(),
        "pdf_white_text.pdf": generator.white_text_pdf(),
        "pdf_render_mode_3.pdf": generator.render_mode_pdf(),
        "eml_hidden_span.eml": generator.hidden_span_eml(),
        "image_only.pdf": generator.image_only_pdf(),
    }
    for name, content in expected.items():
        path = FIXTURES / name
        actual = path.read_text(encoding="utf-8") if isinstance(content, str) else path.read_bytes()
        assert actual == content, name
