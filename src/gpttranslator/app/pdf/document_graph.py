"""Document graph assembly from extraction artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from ..core.models import Block, FootnoteLink, ImageAsset, PageInfo, SectionInfo
from .extractor import ExtractedFootnote, ExtractionResult

_CAPTION_HINT_RE = re.compile(r"^(figure|fig\.?|table|image|photo)\s*\d*\s*[:.\-)]\s+", re.IGNORECASE)


class DocumentGraphError(RuntimeError):
    """Raised when document graph cannot be constructed or validated."""


@dataclass(slots=True)
class DocumentGraph:
    """Typed document graph for downstream local processing."""

    source_pdf: str
    generated_at: str
    pages: list[PageInfo]
    blocks: list[Block]
    sections: list[SectionInfo]
    images: list[ImageAsset]
    footnote_links: list[FootnoteLink]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "source_pdf": self.source_pdf,
            "generated_at": self.generated_at,
            "summary": {
                "page_count": len(self.pages),
                "block_count": len(self.blocks),
                "section_count": len(self.sections),
                "image_count": len(self.images),
                "footnote_link_count": len(self.footnote_links),
            },
            "pages": [item.to_dict() for item in self.pages],
            "sections": [item.to_dict() for item in self.sections],
            "blocks": [item.to_dict() for item in self.blocks],
            "images": [item.to_dict() for item in self.images],
            "footnote_links": [item.to_dict() for item in self.footnote_links],
            "edges": self._edges(),
            "warnings": self.warnings,
        }

    def _edges(self) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []

        for block in self.blocks:
            if block.next_block_id:
                edges.append(
                    {
                        "type": "adjacent",
                        "from_block_id": block.block_id,
                        "to_block_id": block.next_block_id,
                        "confidence": 1.0,
                    }
                )
            if block.section_id:
                edges.append(
                    {
                        "type": "block_section",
                        "from_block_id": block.block_id,
                        "to_section_id": block.section_id,
                        "confidence": 1.0,
                    }
                )

        for image in self.images:
            if image.caption_block_id:
                edges.append(
                    {
                        "type": "caption_image",
                        "from_block_id": image.caption_block_id,
                        "to_image_id": image.image_id,
                        "confidence": image.caption_confidence,
                    }
                )

        for link in self.footnote_links:
            if link.marker_block_id and link.body_block_id:
                edges.append(
                    {
                        "type": "footnote_link",
                        "from_block_id": link.marker_block_id,
                        "to_block_id": link.body_block_id,
                        "confidence": link.confidence,
                        "link_id": link.link_id,
                    }
                )

        return edges


def build_document_graph(result: ExtractionResult) -> DocumentGraph:
    """Build linked document graph from extraction output."""

    warnings = list(result.warnings)

    blocks = _build_blocks(result)
    block_by_id = {block.block_id: block for block in blocks}

    sections, section_warnings = _build_sections(blocks)
    warnings.extend(section_warnings)
    _assign_block_sections(blocks, sections)

    images = [
        ImageAsset(
            image_id=item.image_id,
            page_num=item.page_num,
            object_name=item.object_name,
            width=item.width,
            height=item.height,
            color_space=item.color_space,
            bits_per_component=item.bits_per_component,
            filters=list(item.filters),
            anchor_block_id=item.anchor_block_id,
            flags=list(item.flags),
        )
        for item in result.images
    ]

    image_warnings = _link_captions_to_images(images, blocks)
    warnings.extend(image_warnings)

    footnote_links, footnote_warnings = _build_footnote_links(
        footnotes=result.footnotes,
        block_by_id=block_by_id,
    )
    warnings.extend(footnote_warnings)

    pages = _build_pages(result=result, blocks=blocks, sections=sections, images=images)

    graph = DocumentGraph(
        source_pdf=result.source_pdf,
        generated_at=datetime.now(timezone.utc).isoformat(),
        pages=pages,
        blocks=blocks,
        sections=sections,
        images=images,
        footnote_links=footnote_links,
        warnings=warnings,
    )

    validate_document_graph(graph)
    return graph


def validate_document_graph(graph: DocumentGraph) -> None:
    """Validate cross-entity references and basic data consistency."""

    errors: list[str] = []

    block_by_id = {block.block_id: block for block in graph.blocks}
    if len(block_by_id) != len(graph.blocks):
        errors.append("duplicate block_id values detected")

    section_by_id = {section.section_id: section for section in graph.sections}
    if len(section_by_id) != len(graph.sections):
        errors.append("duplicate section_id values detected")

    image_by_id = {image.image_id: image for image in graph.images}
    if len(image_by_id) != len(graph.images):
        errors.append("duplicate image_id values detected")

    footnote_by_id = {link.link_id: link for link in graph.footnote_links}
    if len(footnote_by_id) != len(graph.footnote_links):
        errors.append("duplicate footnote link_id values detected")

    for block in graph.blocks:
        errors.extend(block.validate())

        if block.section_id is None:
            errors.append(f"block {block.block_id}: missing section_id")
        elif block.section_id not in section_by_id:
            errors.append(f"block {block.block_id}: unknown section_id {block.section_id}")

        if block.prev_block_id and block.prev_block_id not in block_by_id:
            errors.append(f"block {block.block_id}: prev_block_id does not exist")
        if block.next_block_id and block.next_block_id not in block_by_id:
            errors.append(f"block {block.block_id}: next_block_id does not exist")

    for block in graph.blocks:
        if block.next_block_id:
            next_block = block_by_id.get(block.next_block_id)
            if next_block is None:
                continue
            if next_block.prev_block_id != block.block_id:
                errors.append(
                    f"adjacency mismatch: {block.block_id} -> {block.next_block_id} without reverse prev link"
                )

    for page in graph.pages:
        errors.extend(page.validate())
        for block_id in page.block_ids:
            page_block = block_by_id.get(block_id)
            if page_block is None:
                errors.append(f"page {page.page_num}: unknown block_id {block_id}")
                continue
            if page_block.page_num != page.page_num:
                errors.append(f"page {page.page_num}: block {block_id} belongs to page {page_block.page_num}")

        for section_id in page.section_ids:
            if section_id not in section_by_id:
                errors.append(f"page {page.page_num}: unknown section_id {section_id}")

    for section in graph.sections:
        errors.extend(section.validate())
        for block_id in section.block_ids:
            if block_id not in block_by_id:
                errors.append(f"section {section.section_id}: unknown block_id {block_id}")

    for image in graph.images:
        errors.extend(image.validate())
        if image.anchor_block_id and image.anchor_block_id not in block_by_id:
            errors.append(f"image {image.image_id}: anchor_block_id does not exist")
        if image.caption_block_id and image.caption_block_id not in block_by_id:
            errors.append(f"image {image.image_id}: caption_block_id does not exist")

    for link in graph.footnote_links:
        errors.extend(link.validate())
        if link.marker_block_id and link.marker_block_id not in block_by_id:
            errors.append(f"footnote {link.link_id}: marker_block_id does not exist")
        if link.body_block_id and link.body_block_id not in block_by_id:
            errors.append(f"footnote {link.link_id}: body_block_id does not exist")

    if errors:
        prefix = "Document graph validation failed:"
        details = "\n".join(f"- {item}" for item in errors[:50])
        raise DocumentGraphError(f"{prefix}\n{details}")


def save_document_graph_artifacts(analysis_dir: Path, graph: DocumentGraph) -> dict[str, str]:
    """Save document graph and sections artifacts."""

    root = analysis_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    graph_path = root / "document_graph.json"
    sections_path = root / "sections.jsonl"

    graph_path.write_text(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with sections_path.open("w", encoding="utf-8") as file:
        for section in graph.sections:
            file.write(json.dumps(section.to_dict(), ensure_ascii=False) + "\n")

    return {
        "document_graph": str(graph_path),
        "sections": str(sections_path),
    }


def _build_blocks(result: ExtractionResult) -> list[Block]:
    blocks = [
        Block(
            block_id=item.block_id,
            page_num=item.page_num,
            block_type=item.block_type,
            text=item.text,
            bbox=item.bbox,
            reading_order=item.reading_order,
            style_metadata=dict(item.style_metadata),
            flags=list(item.flags),
        )
        for item in sorted(result.blocks, key=lambda block: (block.page_num, block.reading_order, block.block_id))
    ]

    for index, block in enumerate(blocks):
        block.prev_block_id = blocks[index - 1].block_id if index > 0 else None
        block.next_block_id = blocks[index + 1].block_id if index + 1 < len(blocks) else None

    return blocks


def _build_sections(blocks: list[Block]) -> tuple[list[SectionInfo], list[str]]:
    warnings: list[str] = []

    content_blocks = [block for block in blocks if block.block_type not in {"header", "footer", "image_anchor"}]

    if not content_blocks:
        section = SectionInfo(
            section_id="sec-0001",
            title="Document",
            level=1,
            start_page=1,
            end_page=1,
            heading_block_id=None,
            block_ids=[block.block_id for block in blocks],
            confidence=0.3,
            flags=["low_confidence_section_detection", "no_content_blocks"],
        )
        return [section], warnings

    heading_blocks = [block for block in content_blocks if block.block_type == "heading"]

    if not heading_blocks:
        section = SectionInfo(
            section_id="sec-0001",
            title="Document",
            level=1,
            start_page=min(block.page_num for block in content_blocks),
            end_page=max(block.page_num for block in content_blocks),
            heading_block_id=None,
            block_ids=[block.block_id for block in content_blocks],
            confidence=0.45,
            flags=["low_confidence_section_detection"],
        )
        return [section], warnings

    order_map = {block.block_id: index for index, block in enumerate(content_blocks)}
    heading_fonts = [
        float(block.style_metadata.get("max_font_size", 0.0))
        for block in heading_blocks
        if float(block.style_metadata.get("max_font_size", 0.0)) > 0
    ]
    heading_median = median(heading_fonts) if heading_fonts else 12.0

    sections: list[SectionInfo] = []
    sorted_headings = sorted(heading_blocks, key=lambda block: order_map[block.block_id])

    for section_index, heading in enumerate(sorted_headings, start=1):
        start = order_map[heading.block_id]
        end = (
            order_map[sorted_headings[section_index].block_id] - 1
            if section_index < len(sorted_headings)
            else len(content_blocks) - 1
        )

        members = content_blocks[start : end + 1]
        title = heading.text.strip() or f"Section {section_index}"

        flags: list[str] = []
        confidence = 0.9
        if "low_confidence_block_type" in heading.flags:
            confidence = 0.62
            flags.append("low_confidence_heading")

        level = _infer_heading_level(heading=heading, median_heading_font=heading_median)

        sections.append(
            SectionInfo(
                section_id=f"sec-{section_index:04d}",
                title=title,
                level=level,
                start_page=members[0].page_num,
                end_page=members[-1].page_num,
                heading_block_id=heading.block_id,
                block_ids=[block.block_id for block in members],
                confidence=round(confidence, 3),
                flags=flags,
            )
        )

    return sections, warnings


def _infer_heading_level(heading: Block, median_heading_font: float) -> int:
    text = heading.text.strip().lower()
    if text.startswith("chapter"):
        return 1

    font_size = float(heading.style_metadata.get("max_font_size", 0.0) or 0.0)
    if font_size >= median_heading_font * 1.15:
        return 1
    return 2


def _assign_block_sections(blocks: list[Block], sections: list[SectionInfo]) -> None:
    section_by_id = {section.section_id: section for section in sections}
    block_by_id = {block.block_id: block for block in blocks}

    for section in sections:
        for block_id in section.block_ids:
            block = block_by_id.get(block_id)
            if block is None:
                continue
            block.section_id = section.section_id

    document_order = sorted(blocks, key=lambda block: (block.page_num, block.reading_order, block.block_id))
    assigned = [block for block in document_order if block.section_id is not None]

    for block in document_order:
        if block.section_id is not None:
            continue

        section_id = _infer_section_for_block(block, assigned)
        if section_id and section_id in section_by_id:
            block.section_id = section_id
            block.flags.append("section_inferred")

    for section in sections:
        section.block_ids = [block.block_id for block in document_order if block.section_id == section.section_id]


def _infer_section_for_block(block: Block, assigned: list[Block]) -> str | None:
    same_page = [candidate for candidate in assigned if candidate.page_num == block.page_num]

    if same_page:
        nearest = min(same_page, key=lambda item: abs(item.reading_order - block.reading_order))
        return nearest.section_id

    previous = [
        candidate
        for candidate in assigned
        if (candidate.page_num, candidate.reading_order) < (block.page_num, block.reading_order)
    ]
    if previous:
        return previous[-1].section_id

    return assigned[0].section_id if assigned else None


def _build_pages(
    result: ExtractionResult,
    blocks: list[Block],
    sections: list[SectionInfo],
    images: list[ImageAsset],
) -> list[PageInfo]:
    section_ids = {section.section_id for section in sections}

    pages: list[PageInfo] = []
    for page in sorted(result.pages, key=lambda item: item.page_num):
        page_blocks = [block for block in blocks if block.page_num == page.page_num]
        page_block_ids = [block.block_id for block in sorted(page_blocks, key=lambda item: item.reading_order)]

        raw_section_ids = [block.section_id for block in page_blocks if block.section_id]
        unique_section_ids = [item for item in dict.fromkeys(raw_section_ids) if item in section_ids]

        page_image_ids = [image.image_id for image in images if image.page_num == page.page_num]

        pages.append(
            PageInfo(
                page_num=page.page_num,
                width=page.width,
                height=page.height,
                block_ids=page_block_ids,
                section_ids=unique_section_ids,
                image_ids=page_image_ids,
                reading_order_strategy=page.reading_order_strategy,
                flags=list(page.flags),
                metadata={
                    "block_count": page.block_count,
                    "image_count": page.image_count,
                    "footnote_count": page.footnote_count,
                },
            )
        )

    return pages


def _build_footnote_links(
    footnotes: list[ExtractedFootnote],
    block_by_id: dict[str, Block],
) -> tuple[list[FootnoteLink], list[str]]:
    warnings: list[str] = []

    markers = [item for item in footnotes if item.kind == "marker"]
    bodies = [item for item in footnotes if item.kind == "body"]

    body_by_marker: dict[str, list[ExtractedFootnote]] = {}
    for body in bodies:
        key = _normalize_marker(body.marker)
        body_by_marker.setdefault(key, []).append(body)

    links: list[FootnoteLink] = []
    used_bodies: set[str] = set()
    link_index = 1

    for marker in markers:
        marker_block_id = marker.source_block_id if marker.source_block_id in block_by_id else None
        marker_key = _normalize_marker(marker.marker)

        candidates = [body for body in body_by_marker.get(marker_key, []) if body.source_block_id not in used_bodies]

        matched = None
        confidence = 0.2
        flags: list[str] = []

        if candidates:
            matched = min(
                candidates,
                key=lambda body: (abs(body.page_num - marker.page_num), body.page_num),
            )
            confidence = 0.92 if matched.page_num == marker.page_num else 0.76
            if matched.page_num != marker.page_num:
                flags.append("cross_page_link")
        else:
            same_page = [
                body for body in bodies if body.page_num == marker.page_num and body.source_block_id not in used_bodies
            ]
            if same_page:
                matched = same_page[0]
                confidence = 0.55
                flags.append("low_confidence_marker_match")

        if matched is not None:
            used_bodies.add(matched.source_block_id)

        links.append(
            FootnoteLink(
                link_id=f"fnlink-{link_index:04d}",
                marker_block_id=marker_block_id,
                body_block_id=(matched.source_block_id if matched and matched.source_block_id in block_by_id else None),
                marker=marker.marker,
                confidence=round(confidence, 3),
                flags=flags,
            )
        )
        link_index += 1

    for body in bodies:
        if body.source_block_id in used_bodies:
            continue

        links.append(
            FootnoteLink(
                link_id=f"fnlink-{link_index:04d}",
                marker_block_id=None,
                body_block_id=body.source_block_id if body.source_block_id in block_by_id else None,
                marker=body.marker,
                confidence=0.35,
                flags=["unpaired_footnote_body"],
            )
        )
        link_index += 1

    for link in links:
        if link.marker_block_id is None and link.body_block_id is None:
            warnings.append(f"footnote link {link.link_id} has unresolved references")

    return links, warnings


def _link_captions_to_images(images: list[ImageAsset], blocks: list[Block]) -> list[str]:
    warnings: list[str] = []
    block_by_id = {block.block_id: block for block in blocks}

    for image in images:
        page_blocks = [block for block in blocks if block.page_num == image.page_num]
        if not page_blocks:
            image.flags.append("no_blocks_on_image_page")
            continue

        anchor = block_by_id.get(image.anchor_block_id) if image.anchor_block_id else None
        anchor_order = anchor.reading_order if anchor else 10**9

        caption_candidates = [block for block in page_blocks if block.block_type == "caption"]

        selected: Block | None = None
        confidence = 0.0

        if caption_candidates:
            selected = min(
                caption_candidates,
                key=lambda item: abs(item.reading_order - anchor_order),
            )
            confidence = 0.92 if selected.reading_order <= anchor_order else 0.78
            if selected.reading_order > anchor_order:
                image.flags.append("caption_after_image_anchor")
        else:
            fallback = [
                block
                for block in page_blocks
                if block.block_type == "paragraph" and _CAPTION_HINT_RE.match(block.text.strip())
            ]
            if fallback:
                selected = min(
                    fallback,
                    key=lambda item: abs(item.reading_order - anchor_order),
                )
                confidence = 0.55
                image.flags.append("low_confidence_caption_link")

        if selected is None:
            image.caption_block_id = None
            image.caption_confidence = 0.0
            image.flags.append("no_caption_found")
            warnings.append(f"image {image.image_id}: caption not linked")
            continue

        image.caption_block_id = selected.block_id
        image.caption_confidence = round(confidence, 3)

    return warnings


def _normalize_marker(value: str | None) -> str:
    if not value:
        return ""

    digits = re.sub(r"\D", "", value)
    if digits:
        return digits
    return value.strip().lower()
