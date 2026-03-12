"""PDF fixtures for local tests."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject


def write_simple_text_pdf(path: Path) -> None:
    """Create a tiny two-page PDF with text/header/footer/footnote patterns."""

    writer = PdfWriter()

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)

    pages = [
        [
            (72, 800, "Book Title"),
            (72, 730, "Main body text on page one [1]."),
            (72, 90, "1 Footnote example."),
            (72, 40, "Page 1"),
        ],
        [
            (72, 800, "Book Title"),
            (72, 730, "Main body text on page two."),
            (72, 40, "Page 2"),
        ],
    ]

    for text_items in pages:
        page = writer.add_blank_page(width=595, height=842)
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
            }
        )
        page[NameObject("/Resources")] = resources

        stream = DecodedStreamObject()
        stream_lines: list[str] = []
        for x, y, text in text_items:
            stream_lines.append(f"BT /F1 12 Tf {x} {y} Td ({_escape_pdf_text(text)}) Tj ET")

        stream.set_data("\n".join(stream_lines).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)

    with path.open("wb") as file:
        writer.write(file)


def write_pdf_with_caption_and_image(path: Path) -> None:
    """Create one-page PDF that includes image XObject and caption text."""

    writer = PdfWriter()

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)

    image_stream = DecodedStreamObject()
    image_stream.set_data(bytes([255, 0, 0]))
    image_stream.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_ref = writer._add_object(image_stream)

    page = writer.add_blank_page(width=595, height=842)
    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
            NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): image_ref}),
        }
    )
    page[NameObject("/Resources")] = resources

    stream = DecodedStreamObject()
    stream_data = "\n".join(
        [
            "q 160 0 0 100 230 520 cm /Im1 Do Q",
            "BT /F1 12 Tf 72 500 Td (Figure 1: Sample image.) Tj ET",
            "BT /F1 12 Tf 72 40 Td (Page 1) Tj ET",
        ]
    )
    stream.set_data(stream_data.encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    with path.open("wb") as file:
        writer.write(file)


def write_multi_paragraph_pdf(path: Path, paragraph_count: int = 6) -> None:
    """Create one-page PDF with multiple plain paragraphs."""

    writer = PdfWriter()

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)

    page = writer.add_blank_page(width=595, height=842)
    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        }
    )
    page[NameObject("/Resources")] = resources

    stream = DecodedStreamObject()
    lines: list[str] = []
    y = 760
    for idx in range(paragraph_count):
        text = f"paragraph line {idx + 1} with local context."
        lines.append(f"BT /F1 12 Tf 72 {y} Td ({_escape_pdf_text(text)}) Tj ET")
        y -= 38

    stream.set_data("\n".join(lines).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    with path.open("wb") as file:
        writer.write(file)


def write_corrupted_pdf_with_signature(path: Path) -> None:
    """Create intentionally broken PDF-like file for error handling tests."""

    path.write_bytes(b"%PDF-1.7\nTHIS_IS_NOT_A_VALID_PDF\n")


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
