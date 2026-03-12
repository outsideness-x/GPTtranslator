"""Core data models for translation pipeline manifests and jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utcnow_iso() -> str:
    """Return timezone-aware UTC timestamp in ISO format."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Block:
    block_id: str
    page_number: int
    text: str
    kind: str = "text"
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_number": self.page_number,
            "text": self.text,
            "kind": self.kind,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        bbox = data.get("bbox")
        return cls(
            block_id=str(data["block_id"]),
            page_number=int(data["page_number"]),
            text=str(data.get("text", "")),
            kind=str(data.get("kind", "text")),
            bbox=tuple(bbox) if bbox is not None else None,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class PageInfo:
    page_number: int
    width: float | None = None
    height: float | None = None
    blocks: list[Block] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageInfo":
        return cls(
            page_number=int(data["page_number"]),
            width=float(data["width"]) if data.get("width") is not None else None,
            height=float(data["height"]) if data.get("height") is not None else None,
            blocks=[Block.from_dict(item) for item in data.get("blocks", [])],
        )


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    page_number: int
    block_ids: list[str]
    source_text: str
    token_estimate: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "page_number": self.page_number,
            "block_ids": self.block_ids,
            "source_text": self.source_text,
            "token_estimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        return cls(
            chunk_id=str(data["chunk_id"]),
            page_number=int(data["page_number"]),
            block_ids=[str(item) for item in data.get("block_ids", [])],
            source_text=str(data.get("source_text", "")),
            token_estimate=int(data["token_estimate"]) if data.get("token_estimate") is not None else None,
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
            status=str(data.get("status", "pending")),
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
            severity=str(data["severity"]),
            message=str(data.get("message", "")),
            rule_id=str(data["rule_id"]) if data.get("rule_id") is not None else None,
        )


@dataclass(slots=True)
class CodexJob:
    job_id: str
    prompt_path: str
    input_path: str
    output_path: str
    status: Literal["queued", "running", "finished", "failed"] = "queued"

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "prompt_path": self.prompt_path,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodexJob":
        return cls(
            job_id=str(data["job_id"]),
            prompt_path=str(data.get("prompt_path", "")),
            input_path=str(data.get("input_path", "")),
            output_path=str(data.get("output_path", "")),
            status=str(data.get("status", "queued")),
        )


@dataclass(slots=True)
class CodexResult:
    job_id: str
    return_code: int
    stdout: str
    stderr: str
    success: bool
    output_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "success": self.success,
            "output_path": self.output_path,
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
        )


@dataclass(slots=True)
class BookManifest:
    book_id: str
    source_pdf: str
    created_at: str = field(default_factory=utcnow_iso)
    pages: list[PageInfo] = field(default_factory=list)
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
            chunks=[Chunk.from_dict(item) for item in data.get("chunks", [])],
            translations=[TranslationRecord.from_dict(item) for item in data.get("translations", [])],
            qa_flags=[QAFlag.from_dict(item) for item in data.get("qa_flags", [])],
            metadata=dict(data.get("metadata", {})),
        )
