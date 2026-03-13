"""Core data models for manifests, extraction and translation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, cast


def utcnow_iso() -> str:
    """Return timezone-aware UTC timestamp in ISO format."""

    return datetime.now(timezone.utc).isoformat()


def _coerce_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    return None


def _coerce_translation_status(value: Any) -> Literal["pending", "done", "failed"]:
    status = str(value).strip().lower()
    if status in {"pending", "done", "failed"}:
        return cast(Literal["pending", "done", "failed"], status)
    return "pending"


def _coerce_qa_severity(value: Any) -> Literal["low", "medium", "high"]:
    severity = str(value).strip().lower()
    if severity in {"low", "medium", "high"}:
        return cast(Literal["low", "medium", "high"], severity)
    return "low"


def _coerce_codex_job_status(value: Any) -> Literal["queued", "running", "finished", "failed"]:
    status = str(value).strip().lower()
    if status in {"queued", "running", "finished", "failed"}:
        return cast(Literal["queued", "running", "finished", "failed"], status)
    return "queued"


@dataclass(slots=True)
class Block:
    """Structured content block with relation slots for document graph."""

    block_id: str
    page_num: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None = None
    reading_order: int = 0
    style_metadata: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    section_id: str | None = None
    prev_block_id: str | None = None
    next_block_id: str | None = None

    @property
    def page_number(self) -> int:
        """Backward-compatible alias."""

        return self.page_num

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_num": self.page_num,
            "page_number": self.page_num,
            "block_type": self.block_type,
            "kind": self.block_type,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "reading_order": self.reading_order,
            "text": self.text,
            "style_metadata": self.style_metadata,
            "metadata": self.style_metadata,
            "flags": self.flags,
            "section_id": self.section_id,
            "prev_block_id": self.prev_block_id,
            "next_block_id": self.next_block_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        page_num = int(data.get("page_num", data.get("page_number", 0)))
        block_type = str(data.get("block_type", data.get("kind", "text")))
        style_metadata = dict(data.get("style_metadata", data.get("metadata", {})))

        return cls(
            block_id=str(data["block_id"]),
            page_num=page_num,
            block_type=block_type,
            text=str(data.get("text", "")),
            bbox=_coerce_bbox(data.get("bbox")),
            reading_order=int(data.get("reading_order", 0)),
            style_metadata=style_metadata,
            flags=[str(item) for item in data.get("flags", [])],
            section_id=str(data["section_id"]) if data.get("section_id") is not None else None,
            prev_block_id=str(data["prev_block_id"]) if data.get("prev_block_id") is not None else None,
            next_block_id=str(data["next_block_id"]) if data.get("next_block_id") is not None else None,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []

        if not self.block_id.strip():
            errors.append("block_id is empty")
        if self.page_num < 1:
            errors.append(f"block {self.block_id}: page_num must be >= 1")
        if self.reading_order < 0:
            errors.append(f"block {self.block_id}: reading_order must be >= 0")

        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if x1 < x0 or y1 < y0:
                errors.append(f"block {self.block_id}: invalid bbox coordinates")

        confidence = self.style_metadata.get("confidence")
        if confidence is not None:
            try:
                value = float(confidence)
                if not 0.0 <= value <= 1.0:
                    errors.append(f"block {self.block_id}: confidence out of [0,1]")
            except (TypeError, ValueError):
                errors.append(f"block {self.block_id}: confidence is not numeric")

        return errors


@dataclass(slots=True)
class PageInfo:
    """Page model with references to blocks and sections."""

    page_num: int
    width: float | None = None
    height: float | None = None
    block_ids: list[str] = field(default_factory=list)
    section_ids: list[str] = field(default_factory=list)
    image_ids: list[str] = field(default_factory=list)
    reading_order_strategy: str | None = None
    flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)

    @property
    def page_number(self) -> int:
        """Backward-compatible alias."""

        return self.page_num

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_num": self.page_num,
            "page_number": self.page_num,
            "width": self.width,
            "height": self.height,
            "block_ids": self.block_ids,
            "section_ids": self.section_ids,
            "image_ids": self.image_ids,
            "reading_order_strategy": self.reading_order_strategy,
            "flags": self.flags,
            "metadata": self.metadata,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageInfo":
        blocks = [Block.from_dict(item) for item in data.get("blocks", [])]
        block_ids = [str(item) for item in data.get("block_ids", [])]
        if not block_ids and blocks:
            block_ids = [block.block_id for block in blocks]

        return cls(
            page_num=int(data.get("page_num", data.get("page_number", 0))),
            width=float(data["width"]) if data.get("width") is not None else None,
            height=float(data["height"]) if data.get("height") is not None else None,
            block_ids=block_ids,
            section_ids=[str(item) for item in data.get("section_ids", [])],
            image_ids=[str(item) for item in data.get("image_ids", [])],
            reading_order_strategy=(
                str(data["reading_order_strategy"]) if data.get("reading_order_strategy") is not None else None
            ),
            flags=[str(item) for item in data.get("flags", [])],
            metadata=dict(data.get("metadata", {})),
            blocks=blocks,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.page_num < 1:
            errors.append("page_num must be >= 1")
        return errors


@dataclass(slots=True)
class FootnoteLink:
    """Relation between footnote marker and footnote body blocks."""

    link_id: str
    marker_block_id: str | None
    body_block_id: str | None
    marker: str | None = None
    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "marker_block_id": self.marker_block_id,
            "body_block_id": self.body_block_id,
            "marker": self.marker,
            "confidence": self.confidence,
            "flags": self.flags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FootnoteLink":
        return cls(
            link_id=str(data["link_id"]),
            marker_block_id=(str(data["marker_block_id"]) if data.get("marker_block_id") is not None else None),
            body_block_id=(str(data["body_block_id"]) if data.get("body_block_id") is not None else None),
            marker=str(data["marker"]) if data.get("marker") is not None else None,
            confidence=float(data.get("confidence", 0.0)),
            flags=[str(item) for item in data.get("flags", [])],
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.link_id.strip():
            errors.append("footnote link_id is empty")
        if self.marker_block_id is None and self.body_block_id is None:
            errors.append(f"footnote {self.link_id}: both marker and body are missing")
        if not 0.0 <= self.confidence <= 1.0:
            errors.append(f"footnote {self.link_id}: confidence out of [0,1]")
        return errors


@dataclass(slots=True)
class ImageAsset:
    """Image asset in document model with optional caption relation."""

    image_id: str
    page_num: int
    object_name: str
    width: int | None = None
    height: int | None = None
    color_space: str | None = None
    bits_per_component: int | None = None
    filters: list[str] = field(default_factory=list)
    anchor_block_id: str | None = None
    caption_block_id: str | None = None
    caption_confidence: float | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_num": self.page_num,
            "object_name": self.object_name,
            "width": self.width,
            "height": self.height,
            "color_space": self.color_space,
            "bits_per_component": self.bits_per_component,
            "filters": self.filters,
            "anchor_block_id": self.anchor_block_id,
            "caption_block_id": self.caption_block_id,
            "caption_confidence": self.caption_confidence,
            "flags": self.flags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageAsset":
        caption_confidence = data.get("caption_confidence")
        return cls(
            image_id=str(data["image_id"]),
            page_num=int(data.get("page_num", 0)),
            object_name=str(data.get("object_name", "unknown")),
            width=int(data["width"]) if data.get("width") is not None else None,
            height=int(data["height"]) if data.get("height") is not None else None,
            color_space=str(data["color_space"]) if data.get("color_space") is not None else None,
            bits_per_component=(
                int(data["bits_per_component"]) if data.get("bits_per_component") is not None else None
            ),
            filters=[str(item) for item in data.get("filters", [])],
            anchor_block_id=(str(data["anchor_block_id"]) if data.get("anchor_block_id") is not None else None),
            caption_block_id=(str(data["caption_block_id"]) if data.get("caption_block_id") is not None else None),
            caption_confidence=(float(caption_confidence) if caption_confidence is not None else None),
            flags=[str(item) for item in data.get("flags", [])],
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.image_id.strip():
            errors.append("image_id is empty")
        if self.page_num < 1:
            errors.append(f"image {self.image_id}: page_num must be >= 1")
        if self.caption_confidence is not None and not 0.0 <= self.caption_confidence <= 1.0:
            errors.append(f"image {self.image_id}: caption_confidence out of [0,1]")
        return errors


@dataclass(slots=True)
class SectionInfo:
    """Logical section/chapter range with member blocks."""

    section_id: str
    title: str
    level: int
    start_page: int
    end_page: int
    heading_block_id: str | None = None
    block_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "level": self.level,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "heading_block_id": self.heading_block_id,
            "block_ids": self.block_ids,
            "confidence": self.confidence,
            "flags": self.flags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionInfo":
        return cls(
            section_id=str(data["section_id"]),
            title=str(data.get("title", "")),
            level=int(data.get("level", 1)),
            start_page=int(data.get("start_page", 1)),
            end_page=int(data.get("end_page", 1)),
            heading_block_id=(str(data["heading_block_id"]) if data.get("heading_block_id") is not None else None),
            block_ids=[str(item) for item in data.get("block_ids", [])],
            confidence=float(data.get("confidence", 0.0)),
            flags=[str(item) for item in data.get("flags", [])],
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.section_id.strip():
            errors.append("section_id is empty")
        if self.level < 1:
            errors.append(f"section {self.section_id}: level must be >= 1")
        if self.start_page < 1:
            errors.append(f"section {self.section_id}: start_page must be >= 1")
        if self.end_page < self.start_page:
            errors.append(f"section {self.section_id}: end_page is less than start_page")
        if not 0.0 <= self.confidence <= 1.0:
            errors.append(f"section {self.section_id}: confidence out of [0,1]")
        return errors


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    chapter_id: str | None
    page_range: tuple[int, int]
    block_ids: list[str]
    chunk_type: str
    source_text: str
    local_context_before: str = ""
    local_context_after: str = ""
    footnote_refs: list[dict[str, Any]] = field(default_factory=list)
    glossary_hints: list[str] = field(default_factory=list)
    token_estimate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def page_number(self) -> int:
        """Backward-compatible alias for legacy consumers."""

        return self.page_range[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "chapter_id": self.chapter_id,
            "page_range": [self.page_range[0], self.page_range[1]],
            "page_number": self.page_number,
            "block_ids": self.block_ids,
            "chunk_type": self.chunk_type,
            "source_text": self.source_text,
            "local_context_before": self.local_context_before,
            "local_context_after": self.local_context_after,
            "footnote_refs": self.footnote_refs,
            "glossary_hints": self.glossary_hints,
            "token_estimate": self.token_estimate,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        page_range_raw = data.get("page_range")
        if isinstance(page_range_raw, (list, tuple)) and len(page_range_raw) == 2:
            page_range = (int(page_range_raw[0]), int(page_range_raw[1]))
        else:
            page_number = int(data.get("page_number", 1))
            page_range = (page_number, page_number)

        return cls(
            chunk_id=str(data["chunk_id"]),
            chapter_id=(str(data["chapter_id"]) if data.get("chapter_id") is not None else None),
            page_range=page_range,
            block_ids=[str(item) for item in data.get("block_ids", [])],
            chunk_type=str(data.get("chunk_type", "paragraph_group")),
            source_text=str(data.get("source_text", "")),
            local_context_before=str(data.get("local_context_before", "")),
            local_context_after=str(data.get("local_context_after", "")),
            footnote_refs=[dict(item) for item in data.get("footnote_refs", []) if isinstance(item, dict)],
            glossary_hints=[str(item) for item in data.get("glossary_hints", [])],
            token_estimate=int(data["token_estimate"]) if data.get("token_estimate") is not None else None,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class TranslationRecord:
    chunk_id: str
    target_text: str
    backend: str = "codex_cli"
    status: Literal["pending", "done", "failed"] = "pending"
    updated_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "target_text": self.target_text,
            "backend": self.backend,
            "status": self.status,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranslationRecord":
        return cls(
            chunk_id=str(data["chunk_id"]),
            target_text=str(data.get("target_text", "")),
            backend=str(data.get("backend", "codex_cli")),
            status=_coerce_translation_status(data.get("status", "pending")),
            updated_at=str(data.get("updated_at", utcnow_iso())),
        )


@dataclass(slots=True)
class QAFlag:
    chunk_id: str
    severity: Literal["low", "medium", "high"]
    message: str
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "severity": self.severity,
            "message": self.message,
            "rule_id": self.rule_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QAFlag":
        return cls(
            chunk_id=str(data["chunk_id"]),
            severity=_coerce_qa_severity(data.get("severity", "low")),
            message=str(data.get("message", "")),
            rule_id=str(data["rule_id"]) if data.get("rule_id") is not None else None,
        )


@dataclass(slots=True)
class CodexJob:
    job_id: str
    prompt_path: str
    input_path: str
    output_path: str
    raw_stdout_path: str = ""
    raw_stderr_path: str = ""
    meta_path: str = ""
    timeout_seconds: int = 120
    max_attempts: int = 3
    status: Literal["queued", "running", "finished", "failed"] = "queued"

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "prompt_path": self.prompt_path,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "raw_stdout_path": self.raw_stdout_path,
            "raw_stderr_path": self.raw_stderr_path,
            "meta_path": self.meta_path,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodexJob":
        return cls(
            job_id=str(data["job_id"]),
            prompt_path=str(data.get("prompt_path", "")),
            input_path=str(data.get("input_path", "")),
            output_path=str(data.get("output_path", "")),
            raw_stdout_path=str(data.get("raw_stdout_path", "")),
            raw_stderr_path=str(data.get("raw_stderr_path", "")),
            meta_path=str(data.get("meta_path", "")),
            timeout_seconds=int(data.get("timeout_seconds", 120)),
            max_attempts=int(data.get("max_attempts", 3)),
            status=_coerce_codex_job_status(data.get("status", "queued")),
        )


@dataclass(slots=True)
class CodexResult:
    job_id: str
    return_code: int
    stdout: str
    stderr: str
    success: bool
    output_path: str | None = None
    failure_reason: str | None = None
    meta_path: str | None = None
    attempt_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "success": self.success,
            "output_path": self.output_path,
            "failure_reason": self.failure_reason,
            "meta_path": self.meta_path,
            "attempt_count": self.attempt_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodexResult":
        return cls(
            job_id=str(data["job_id"]),
            return_code=int(data.get("return_code", 1)),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            success=bool(data.get("success", False)),
            output_path=str(data["output_path"]) if data.get("output_path") is not None else None,
            failure_reason=(str(data["failure_reason"]) if data.get("failure_reason") is not None else None),
            meta_path=str(data["meta_path"]) if data.get("meta_path") is not None else None,
            attempt_count=int(data.get("attempt_count", 0)),
        )


@dataclass(slots=True)
class BookManifest:
    book_id: str
    source_pdf: str
    created_at: str = field(default_factory=utcnow_iso)
    pages: list[PageInfo] = field(default_factory=list)
    sections: list[SectionInfo] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    footnote_links: list[FootnoteLink] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    translations: list[TranslationRecord] = field(default_factory=list)
    qa_flags: list[QAFlag] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "source_pdf": self.source_pdf,
            "created_at": self.created_at,
            "pages": [page.to_dict() for page in self.pages],
            "sections": [section.to_dict() for section in self.sections],
            "images": [image.to_dict() for image in self.images],
            "footnote_links": [link.to_dict() for link in self.footnote_links],
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "translations": [record.to_dict() for record in self.translations],
            "qa_flags": [flag.to_dict() for flag in self.qa_flags],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BookManifest":
        return cls(
            book_id=str(data["book_id"]),
            source_pdf=str(data.get("source_pdf", "")),
            created_at=str(data.get("created_at", utcnow_iso())),
            pages=[PageInfo.from_dict(item) for item in data.get("pages", [])],
            sections=[SectionInfo.from_dict(item) for item in data.get("sections", [])],
            images=[ImageAsset.from_dict(item) for item in data.get("images", [])],
            footnote_links=[FootnoteLink.from_dict(item) for item in data.get("footnote_links", [])],
            chunks=[Chunk.from_dict(item) for item in data.get("chunks", [])],
            translations=[TranslationRecord.from_dict(item) for item in data.get("translations", [])],
            qa_flags=[QAFlag.from_dict(item) for item in data.get("qa_flags", [])],
            metadata=dict(data.get("metadata", {})),
        )
