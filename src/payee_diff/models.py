"""Report model. The dict produced by `to_json_dict` is the stable schema."""

from __future__ import annotations

from dataclasses import dataclass, field

from payee_diff import __version__
from payee_diff.extract import FIELD_ORDER

SCHEMA_VERSION = "1.0"

VISIBLE = "visible"
RAW_ONLY = "raw-only"
UNICODE_TAG = "unicode-tag"
HIDDEN_CSS = "hidden-css"

ORIGINS = (VISIBLE, RAW_ONLY, UNICODE_TAG, HIDDEN_CSS)
HIDDEN_ORIGINS = (RAW_ONLY, UNICODE_TAG, HIDDEN_CSS)

EXIT_NO_CONFLICT = 0
EXIT_CONFLICT = 1
EXIT_ERROR = 2
EXIT_NOT_CHECKED = 3

NOT_CHECKED_MESSAGE = "no selectable text, not checked"

_DIFFERS = "hidden or raw-only value differs from the visible value"
_ONLY_HIDDEN = "payment value appears only in hidden or raw text"


@dataclass(frozen=True)
class Candidate:
    field: str
    value: str
    normalized: str
    origin: str
    detail: str
    context: str
    page: int | None = None
    part: str | None = None

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "normalized": self.normalized,
            "origin": self.origin,
            "detail": self.detail,
            "context": self.context,
            "page": self.page,
            "part": self.part,
        }


@dataclass
class PartScan:
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    pdf_pages: int = 0
    selectable_characters: int = 0
    images: int = 0
    saw_pdf: bool = False


@dataclass
class Report:
    path: str
    kind: str | None
    sha256: str | None
    status: str
    exit_code: int
    not_checked: bool
    message: str
    notes: list[str]
    candidates: list[Candidate]
    stats: dict

    def to_dict(self) -> dict:
        fields = _field_summaries(self.candidates)
        conflicts = [item for item in fields if item["conflict"]]
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "payee-diff",
            "tool_version": __version__,
            "input": {
                "path": self.path,
                "kind": self.kind,
                "sha256": self.sha256,
            },
            "status": self.status,
            "exit_code": self.exit_code,
            "not_checked": self.not_checked,
            "message": self.message,
            "notes": list(self.notes),
            "stats": {
                "pdf_pages": self.stats.get("pdf_pages"),
                "selectable_characters": self.stats.get("selectable_characters"),
                "images": self.stats.get("images"),
            },
            "candidates": [item.to_dict() for item in self.candidates],
            "fields": fields,
            "conflicts": conflicts,
        }


def _field_summaries(candidates: list[Candidate]) -> list[dict]:
    grouped: dict[str, list[Candidate]] = {name: [] for name in FIELD_ORDER}
    for candidate in candidates:
        grouped.setdefault(candidate.field, []).append(candidate)
    summaries: list[dict] = []
    for name in FIELD_ORDER:
        items = grouped.get(name) or []
        if not items:
            continue
        visible: list[str] = []
        visible_norm: list[str] = []
        hidden: list[dict] = []
        hidden_seen: set[tuple[str, str]] = set()
        for item in items:
            if item.origin == VISIBLE:
                if item.normalized not in visible_norm:
                    visible.append(item.value)
                    visible_norm.append(item.normalized)
            elif (item.normalized, item.origin) not in hidden_seen:
                hidden_seen.add((item.normalized, item.origin))
                hidden.append(
                    {
                        "value": item.value,
                        "normalized": item.normalized,
                        "origin": item.origin,
                    }
                )
        visible_set = set(visible_norm)
        conflict = any(item["normalized"] not in visible_set for item in hidden)
        reason = None
        if conflict:
            reason = _DIFFERS if visible_set else _ONLY_HIDDEN
        summaries.append(
            {
                "field": name,
                "visible": visible,
                "hidden": hidden,
                "conflict": conflict,
                "reason": reason,
            }
        )
    return summaries


def build_report(
    *,
    path: str,
    kind: str | None,
    sha256: str | None,
    scan: PartScan | None = None,
    error: str | None = None,
) -> Report:
    if error is not None:
        return Report(
            path=path,
            kind=kind,
            sha256=sha256,
            status="error",
            exit_code=EXIT_ERROR,
            not_checked=False,
            message=error,
            notes=[],
            candidates=[],
            stats={"pdf_pages": None, "selectable_characters": None, "images": None},
        )
    assert scan is not None
    candidates = _sorted_candidates(scan.candidates)
    fields = _field_summaries(candidates)
    conflict = any(item["conflict"] for item in fields)
    unchecked = bool(scan.unchecked)
    notes = list(scan.notes)
    for item in scan.unchecked:
        if item not in notes:
            notes.append(item)
    if conflict:
        status = "conflict"
        exit_code = EXIT_CONFLICT
        message = "payment-detail conflict"
    elif unchecked:
        status = "not_checked"
        exit_code = EXIT_NOT_CHECKED
        message = NOT_CHECKED_MESSAGE
    else:
        status = "no_conflict"
        exit_code = EXIT_NO_CONFLICT
        message = "no payment-detail conflict"
    stats = {
        "pdf_pages": scan.pdf_pages if scan.saw_pdf else None,
        "selectable_characters": scan.selectable_characters if scan.saw_pdf else None,
        "images": scan.images if scan.saw_pdf else None,
    }
    return Report(
        path=path,
        kind=kind,
        sha256=sha256,
        status=status,
        exit_code=exit_code,
        not_checked=unchecked,
        message=message,
        notes=notes,
        candidates=candidates,
        stats=stats,
    )


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple] = set()
    unique: list[Candidate] = []
    for item in candidates:
        key = (item.field, item.normalized, item.origin, item.detail, item.part, item.page)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _sorted_candidates(candidates: list[Candidate]) -> list[Candidate]:
    origin_order = {name: index for index, name in enumerate(ORIGINS)}

    def key(item: Candidate) -> tuple:
        return (
            FIELD_ORDER.index(item.field) if item.field in FIELD_ORDER else 99,
            origin_order.get(item.origin, 99),
            item.normalized,
            item.part or "",
            item.page or 0,
            item.detail,
            item.value,
        )

    return sorted(candidates, key=key)


def render_text(report: Report) -> str:
    data = report.to_dict()
    lines: list[str] = [
        f"payee-diff {data['tool_version']}",
        f"file: {data['input']['path']}",
        f"kind: {data['input']['kind']}",
    ]
    if data["input"]["sha256"]:
        lines.append(f"sha256: {data['input']['sha256']}")
    lines.append(f"status: {data['status']}")
    lines.append(f"exit_code: {data['exit_code']}")
    lines.append(f"message: {data['message']}")
    lines.append("")

    if data["status"] == "error":
        lines.append("The file was not compared.")
        lines.append("This report does not authorise a payment.")
        return "\n".join(lines) + "\n"

    if data["not_checked"] and not data["fields"]:
        lines.append(NOT_CHECKED_MESSAGE)
        lines.append("Nothing in this file was compared.")
        lines.append("This report does not authorise a payment.")
        return "\n".join(lines) + "\n"

    by_field: dict[str, list[Candidate]] = {}
    for candidate in report.candidates:
        by_field.setdefault(candidate.field, []).append(candidate)

    for summary in data["fields"]:
        lines.append(summary["field"])
        lines.append("  visible:")
        if not summary["visible"]:
            lines.append("    (none)")
        else:
            for value in summary["visible"]:
                lines.append(f"    {value}")
                _append_contexts(lines, by_field.get(summary["field"], []), VISIBLE, value)
        lines.append("  hidden:")
        if not summary["hidden"]:
            lines.append("    (none)")
        else:
            for hidden in summary["hidden"]:
                lines.append(f"    {hidden['value']}  [{hidden['origin']}]")
                _append_contexts(
                    lines,
                    by_field.get(summary["field"], []),
                    hidden["origin"],
                    hidden["value"],
                )
        if summary["conflict"]:
            lines.append(f"  CONFLICT: {summary['reason']}")
        lines.append("")

    if data["notes"]:
        lines.append("notes:")
        for note in data["notes"]:
            lines.append(f"  - {note}")
        lines.append("")

    lines.append(f"conflicts: {len(data['conflicts'])}")
    if data["not_checked"]:
        lines.append(NOT_CHECKED_MESSAGE)
    lines.append("This report does not authorise a payment.")
    return "\n".join(lines) + "\n"


def _append_contexts(
    lines: list[str],
    candidates: list[Candidate],
    origin: str,
    value: str,
) -> None:
    shown: set[tuple[str, str | None, int | None]] = set()
    for candidate in candidates:
        if candidate.origin != origin or candidate.value != value:
            continue
        marker = (candidate.detail, candidate.part, candidate.page)
        if marker in shown:
            continue
        shown.add(marker)
        where = candidate.detail
        if candidate.part:
            where = f"{where}; {candidate.part}"
        if candidate.page is not None:
            where = f"{where}; page {candidate.page}"
        lines.append(f"      {where}")
        if candidate.context:
            lines.append(f"      context: {candidate.context}")
