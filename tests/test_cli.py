import json
import subprocess
import sys
from pathlib import Path

from payee_diff.cli import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "html_display_none.html"


def test_missing_file_and_unsupported_input(tmp_path, capsys):
    missing = tmp_path / "nope.pdf"
    assert main([str(missing), "--format", "json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "error"
    assert report["exit_code"] == 2

    other = tmp_path / "notes.txt"
    other.write_text("IBAN: GB82WEST12345698765432\n", encoding="utf-8")
    assert main([str(other), "--format", "json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert "unsupported input" in report["message"]


def test_text_report_names_the_conflict(capsys):
    assert main([str(FIXTURE), "--format", "text"]) == 1
    text = capsys.readouterr().out
    assert "CONFLICT:" in text
    assert "hidden-css" in text
    assert "no selectable text" not in text
    assert "safe" not in text.casefold()


def test_both_formats_include_a_json_document(capsys):
    assert main([str(FIXTURE), "--format", "both"]) == 1
    out = capsys.readouterr().out
    text, raw = out.split("\n--- json ---\n", 1)
    assert "CONFLICT:" in text
    report = json.loads(raw)
    assert report["schema_version"] == "1.0"
    assert report["tool"] == "payee-diff"
    assert report["exit_code"] == 1


def test_installed_console_script_matches_module():
    script_path = Path(sys.executable).with_name("payee-diff")
    script = subprocess.run(
        [str(script_path), str(ROOT / "fixtures" / "image_only.pdf"), "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    module = subprocess.run(
        [sys.executable, "-m", "payee_diff", str(ROOT / "fixtures" / "clean.html"), "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert script.returncode == 3
    assert "no selectable text, not checked" in script.stdout
    assert module.returncode == 0
    assert json.loads(module.stdout)["status"] == "no_conflict"


def test_package_does_not_import_network_or_model_clients():
    banned = (
        "urllib",
        "requests",
        "httpx",
        "socket",
        "openai",
        "anthropic",
        "pytesseract",
        "easyocr",
        "cv2",
    )
    root = ROOT / "src" / "payee_diff"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
