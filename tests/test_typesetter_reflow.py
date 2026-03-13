"""Unit tests for deterministic reflow and wrapping rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.render.composer import BuildComposition, ComposedPage, ComposedTextBlock
from gpttranslator.app.render.typesetter import PageMargins, TypesettingConfig, typeset_composition


def _composition_with_block(*, text: str, bbox: tuple[float, float, float, float] | None) -> BuildComposition:
    page = ComposedPage(
        page_num=1,
        width=595.0,
        height=842.0,
        overlay_blocks=(
            ComposedTextBlock(
                block_id="blk-1",
                chunk_id="chunk-1",
                page_num=1,
                block_type="paragraph",
                text=text,
                bbox=bbox,
                font_size=10.0,
            ),
        ),
        image_items=tuple(),
        footnote_items=tuple(),
    )
    return BuildComposition(
        book_id="book-typesetter",
        source_pdf_path=Path("/tmp/source.pdf"),
        pages=(page,),
        reflow_blocks=tuple(),
        translation_source="translated_chunks.jsonl",
        translated_chunk_count=1,
        mapped_block_count=1,
        warnings=tuple(),
    )


def test_widow_orphan_control_adjusts_split_and_keeps_two_lines() -> None:
    text = "".join(
        [
            "Первая строка для проверки переноса.\n",
            "Вторая строка для проверки переноса.\n",
            "Третья строка для проверки переноса.\n",
            "Четвертая строка для проверки переноса.",
        ]
    )
    composition = _composition_with_block(text=text, bbox=(72.0, 700.0, 180.0, 740.0))

    result = typeset_composition(
        composition,
        config=TypesettingConfig(
            fallback_mode="conservative",
            font_scale_min=1.0,
            font_scale_max=1.0,
            line_spacing=1.2,
            widow_lines=2,
            orphan_lines=2,
        ),
    )

    assert len(result.annotations) == 1
    assert len(result.reflow_pages) >= 1
    assert len(result.annotations[0].text.splitlines()) <= 3
    assert len(result.reflow_pages[0].body_lines) >= 2
    assert result.metrics.multi_page_block_count >= 1


def test_footnotes_are_typeset_on_page_level_with_reserved_area() -> None:
    page = ComposedPage(
        page_num=1,
        width=595.0,
        height=842.0,
        overlay_blocks=(
            ComposedTextBlock(
                block_id="blk-main",
                chunk_id="chunk-main",
                page_num=1,
                block_type="paragraph",
                text="Основной текст страницы с маркером [1].",
                bbox=(72.0, 120.0, 520.0, 220.0),
                font_size=10.0,
            ),
        ),
        image_items=tuple(),
        footnote_items=(
            {
                "footnote_id": "fn-1",
                "page_num": 1,
                "kind": "body",
                "marker": "[1]",
                "text": "Сноска страницы для локальной проверки.",
                "source_block_id": "blk-footnote",
            },
        ),
    )
    composition = BuildComposition(
        book_id="book-footnotes",
        source_pdf_path=Path("/tmp/source.pdf"),
        pages=(page,),
        reflow_blocks=tuple(),
        translation_source="translated_chunks.jsonl",
        translated_chunk_count=1,
        mapped_block_count=1,
        warnings=tuple(),
    )

    result = typeset_composition(
        composition,
        config=TypesettingConfig(
            fallback_mode="conservative",
            footnote_area_policy="reserve",
            footnote_area_ratio=0.2,
            line_spacing=1.3,
            page_margins=PageMargins(left=36.0, right=36.0, top=36.0, bottom=36.0),
        ),
    )

    assert any(item.kind == "footnote_page" for item in result.annotations)
    assert result.metrics.footnote_annotation_count >= 1


def test_aggressive_reflow_reduces_overflow_pages_vs_conservative() -> None:
    long_text = " ".join(["Очень длинный абзац для теста reflow."] * 120)
    composition = _composition_with_block(text=long_text, bbox=(72.0, 600.0, 320.0, 700.0))

    conservative = typeset_composition(
        composition,
        config=TypesettingConfig(
            fallback_mode="conservative",
            font_scale_min=1.0,
            font_scale_max=1.0,
            line_spacing=1.35,
        ),
    )
    aggressive = typeset_composition(
        composition,
        config=TypesettingConfig(
            fallback_mode="aggressive_reflow",
            font_scale_min=0.7,
            font_scale_max=1.1,
            line_spacing=1.2,
        ),
    )

    assert len(aggressive.reflow_pages) <= len(conservative.reflow_pages)
