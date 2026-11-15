"""Deterministic one-page and multi-page PDF bytes for fixtures and tests.

No timestamps, no font subsetting, no third-party PDF library.
"""

from __future__ import annotations


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_block(
    lines: list[str],
    *,
    x: int = 72,
    y: int = 740,
    size: int = 11,
    color: tuple[float, float, float] = (0, 0, 0),
    render: int = 0,
) -> str:
    red, green, blue = color
    ops = [
        "BT",
        f"/F1 {size} Tf",
        f"{_num(red)} {_num(green)} {_num(blue)} rg",
        f"{int(render)} Tr",
        f"1 0 0 1 {x} {y} Tm",
    ]
    for index, line in enumerate(lines):
        if index:
            ops.append("0 -16 Td")
        ops.append(f"({escape_pdf_text(line)}) Tj")
    ops.append("ET")
    return "\n".join(ops) + "\n"


def filled_rect(
    x: int,
    y: int,
    width: int,
    height: int,
    color: tuple[float, float, float],
) -> str:
    red, green, blue = color
    return f"{_num(red)} {_num(green)} {_num(blue)} rg\n{x} {y} {width} {height} re\nf\n"


def image_draw() -> str:
    return "q\n160 0 0 64 72 500 cm\n/Im1 Do\nQ\n"


def sample_image() -> tuple[bytes, int, int]:
    """2x2 DeviceRGB image. Not a picture of text."""
    pixels = bytes(
        [
            30, 64, 120,
            30, 64, 120,
            240, 240, 240,
            240, 240, 240,
        ]
    )
    return pixels, 2, 2


def build_pdf(pages: list[dict]) -> bytes:
    """Build a PDF 1.4 document.

    Each page dict may contain:
    - content: str of content-stream operators
    - cropbox: optional (x0, y0, x1, y1), default is the media box
    - image: optional raw RGB bytes
    - image_size: (width, height), required when image is set
    """
    if not pages:
        raise ValueError("at least one page is required")

    font_id = 3
    next_id = 4
    plan: list[dict] = []
    for page in pages:
        page_id = next_id
        content_id = next_id + 1
        next_id += 2
        image_id = None
        if page.get("image") is not None:
            image_id = next_id
            next_id += 1
        plan.append(
            {
                "page_id": page_id,
                "content_id": content_id,
                "image_id": image_id,
                "spec": page,
            }
        )

    objects: list[bytes] = [b""] * (next_id - 1)
    kids = " ".join(f"{item['page_id']} 0 R" for item in plan)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(plan)} >>".encode()
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for item in plan:
        spec = item["spec"]
        content = spec.get("content", "").encode("ascii")
        objects[item["content_id"] - 1] = (
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream"
        )
        resources = [f"/Font << /F1 {font_id} 0 R >>"]
        if item["image_id"] is not None:
            image = spec["image"]
            width, height = spec["image_size"]
            if len(image) != width * height * 3:
                raise ValueError("image byte length does not match width*height*3")
            resources.append(f"/XObject << /Im1 {item['image_id']} 0 R >>")
            objects[item["image_id"] - 1] = (
                f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length {len(image)} >>\n"
                f"stream\n".encode()
                + image
                + b"\nendstream"
            )
        crop = spec.get("cropbox", (0, 0, 612, 792))
        objects[item["page_id"] - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/CropBox [{crop[0]} {crop[1]} {crop[2]} {crop[3]}] "
            f"/Contents {item['content_id']} 0 R "
            f"/Resources << {' '.join(resources)} >> >>"
        ).encode()

    return _serialize(objects)


def _serialize(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode()
        out += obj
        out += b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _num(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-"} else "0"
