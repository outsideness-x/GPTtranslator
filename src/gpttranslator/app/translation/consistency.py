"""Terminology and consistency checks for translated artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.logging import get_logger
from ..core.models import Chunk
from ..memory.glossary_manager import parse_glossary_entries
from .editor import RewriteLevel
from .protocol import utcnow_iso

logger = get_logger("translation.consistency")


@dataclass(frozen=True, slots=True)
class ConsistencyOptions:
    """Consistency pass options controlled by CLI flags."""

    strict_terminology: bool = True
    preserve_literalness: bool = False
    rewrite_level: RewriteLevel = "medium"


@dataclass(frozen=True, slots=True)
class ConsistencyResult:
    """Consistency pass summary and artifacts."""

    flags_path: Path
    checked_chunks: int
    flags_count: int
    conflict_count: int


def run_consistency_pass(
    *,
    book_root: Path,
    options: ConsistencyOptions,
) -> ConsistencyResult:
    """Run deterministic consistency checks and persist explicit flags."""

    translated_dir = book_root / "translated"
    flags_path = translated_dir / "consistency_flags.jsonl"
    source_chunks = _load_chunks_map(book_root / "analysis" / "chunks.jsonl")
    glossary_entries, _ = parse_glossary_entries(book_root / "memory" / "glossary.md")

    edited_rows = _load_jsonl(translated_dir / "edited_chunks.jsonl")
    input_rows = [row for row in edited_rows if str(row.get("status", "")) == "completed"]
    if not input_rows:
        translated_rows = _load_jsonl(translated_dir / "translated_chunks.jsonl")
        input_rows = [row for row in translated_rows if str(row.get("status", "")) == "completed"]

    stable_expression_index: dict[str, set[str]] = {}
    for row in input_rows:
        source_text = _chunk_source_text(source_chunks, row)
        target_text = str(row.get("target_text", ""))
        if not source_text.strip() or not target_text.strip():
            continue
        stable_expression_index.setdefault(_normalize(source_text), set()).add(_normalize(target_text))

    flags: list[dict[str, Any]] = []
    for row in input_rows:
        chunk_id = str(row.get("chunk_id", ""))
        target_text = str(row.get("target_text", ""))
        source_text = _chunk_source_text(source_chunks, row)
        if not chunk_id:
            continue

        if options.strict_terminology:
            for entry in glossary_entries:
                source_term = entry.source_term.strip()
                expected_target = entry.target_term.strip()
                if not source_term or not expected_target:
                    continue
                if _contains_phrase(source_text, source_term) and not _contains_phrase(target_text, expected_target):
                    flags.append(
                        _make_flag(
                            chunk_id=chunk_id,
                            flag_type="terminology_conflict",
                            severity="high",
                            message=f"Missing glossary target for '{source_term}' -> '{expected_target}'.",
                            details={
                                "source_term": source_term,
                                "expected_target": expected_target,
                            },
                        )
                    )

        source_key = _normalize(source_text)
        targets = stable_expression_index.get(source_key, set())
        if len(targets) > 1:
            flags.append(
                _make_flag(
                    chunk_id=chunk_id,
                    flag_type="stable_expression_inconsistency",
                    severity="medium",
                    message="Identical source segment has multiple target variants.",
                    details={"variants": sorted(targets)},
                )
            )

        if options.preserve_literalness:
            source_len = max(1, len(source_text.split()))
            target_len = max(1, len(target_text.split()))
            ratio = target_len / source_len
            if ratio < 0.45 or ratio > 2.2:
                flags.append(
                    _make_flag(
                        chunk_id=chunk_id,
                        flag_type="literalness_drift",
                        severity="medium",
                        message=f"Source/target length ratio is suspicious: {ratio:.2f}",
                        details={"ratio": round(ratio, 3)},
                    )
                )

        source_entities = _extract_named_entities(source_text)
        for entity in source_entities:
            if entity in _STOP_NAMES:
                continue
            if options.strict_terminology and entity.lower() not in _normalize(target_text):
                flags.append(
                    _make_flag(
                        chunk_id=chunk_id,
                        flag_type="name_consistency_warning",
                        severity="low",
                        message=f"Potential inconsistency for named entity: {entity}",
                        details={"entity": entity},
                    )
                )

    flags_path.write_text("", encoding="utf-8")
    conflict_count = 0
    for flag in flags:
        flag_type = str(flag.get("type", ""))
        if "conflict" in flag_type or "inconsistency" in flag_type:
            conflict_count += 1
            logger.warning(
                "consistency conflict detected: chunk_id=%s type=%s message=%s",
                flag.get("chunk_id", ""),
                flag_type,
                flag.get("message", ""),
            )
        _append_jsonl(flags_path, flag)

    return ConsistencyResult(
        flags_path=flags_path,
        checked_chunks=len(input_rows),
        flags_count=len(flags),
        conflict_count=conflict_count,
    )


def _make_flag(*, chunk_id: str, flag_type: str, severity: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "type": flag_type,
        "severity": severity,
        "message": message,
        "details": details,
        "updated_at": utcnow_iso(),
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item:
            continue
        payload = json.loads(item)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_chunks_map(path: Path) -> dict[str, Chunk]:
    mapping: dict[str, Chunk] = {}
    for row in _load_jsonl(path):
        if "chunk_id" not in row:
            continue
        chunk = Chunk.from_dict(row)
        mapping[chunk.chunk_id] = chunk
    return mapping


def _chunk_source_text(source_chunks: dict[str, Chunk], row: dict[str, Any]) -> str:
    chunk_id = str(row.get("chunk_id", ""))
    chunk = source_chunks.get(chunk_id)
    if chunk is not None:
        return chunk.source_text
    return str(row.get("source_text", ""))


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return _normalize(phrase) in _normalize(text)


def _normalize(text: str) -> str:
    compact = re.sub(r"\s+", " ", text.strip().lower())
    return compact


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _extract_named_entities(text: str) -> list[str]:
    return re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text)


_STOP_NAMES: frozenset[str] = frozenset({"The", "A", "An", "In", "On", "At", "By", "Of"})
