"""Tests for cost-aware economy logic layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.core.manifest import save_book_manifest
from gpttranslator.app.core.models import BookManifest, Chunk
from gpttranslator.app.memory.glossary_manager import GlossaryEntry
from gpttranslator.app.memory.translation_memory_manager import TranslationMemoryEntry
from gpttranslator.app.translation.economy.budget import BudgetEstimatorOptions, estimate_budget
from gpttranslator.app.translation.economy.complexity import assess_chunk_complexity, route_chunk_tier
from gpttranslator.app.translation.economy.context import (
    ContextBuildSettings,
    ContextPackage,
    build_context_package,
    slice_glossary_entries,
)
from gpttranslator.app.translation.economy.dedupe import (
    build_content_fingerprint,
    find_cache_hit,
    load_job_cache,
    save_job_cache,
    update_cache_record,
)
from gpttranslator.app.translation.economy.prefilter import PreFilterSettings, decide_prefilter_action
from gpttranslator.app.translation.economy.profiles import get_profile
from gpttranslator.app.translation.economy.retry import decide_retry_directive
from gpttranslator.app.translation.economy.service import (
    EconomyPlanRequest,
    build_economy_plan,
    estimate_book_budget,
    load_book_economy_data,
    write_budget_report,
)
from gpttranslator.app.translation.protocol import OUTPUT_SCHEMA_VERSION


def _chunk(
    *,
    chunk_id: str,
    text: str,
    chapter_id: str = "chapter-01",
    chunk_type: str = "paragraph_group",
    footnotes: list[dict[str, str]] | None = None,
    glossary_hints: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        chapter_id=chapter_id,
        page_range=(1, 1),
        block_ids=[f"block-{chunk_id}"],
        chunk_type=chunk_type,
        source_text=text,
        local_context_before="Context before with Newton and NASA.",
        local_context_after="Context after with Einstein.",
        footnote_refs=footnotes or [],
        glossary_hints=glossary_hints or [],
        metadata=metadata or {},
    )


def test_slice_glossary_entries_returns_exact_and_fuzzy_hits() -> None:
    glossary = [
        GlossaryEntry(source_term="theorem", target_term="теорема"),
        GlossaryEntry(source_term="proofs", target_term="доказательства"),
        GlossaryEntry(source_term="axiom", target_term="аксиома"),
    ]
    exact, fuzzy = slice_glossary_entries(
        "The proof of theorem is concise.",
        glossary,
        max_exact=3,
        max_fuzzy=3,
    )

    assert any(item.source_term == "theorem" for item in exact)
    assert any(item.source_term == "proofs" for item in fuzzy)
    assert all(item.source_term != "axiom" for item in exact + fuzzy)


def test_build_context_package_minimizes_payload() -> None:
    chunk = _chunk(
        chunk_id="chunk-1",
        text="Newton states theorem [1] with rigorous proof.",
        glossary_hints=["theorem", "proof"],
        footnotes=[{"marker": "[1]"}],
    )
    glossary = [
        GlossaryEntry(source_term="theorem", target_term="теорема"),
        GlossaryEntry(source_term="proof", target_term="доказательство"),
        GlossaryEntry(source_term="axiom", target_term="аксиома"),
    ]
    tm_entries = [
        TranslationMemoryEntry(
            source_text="Newton states theorem with rigorous proof.",
            target_text="Ньютон формулирует теорему с строгим доказательством.",
            chapter_id="chapter-01",
            quality="approved",
        ),
    ]
    style_guide = "# Style Guide\n- Keep formal tone.\n- Preserve technical terms.\n- Keep list formatting."
    chapter_notes = (
        "# Chapter Notes\n\n## Global Notes\n- Keep footnotes untouched.\n\n"
        "## chapter-01\n- Preserve canonical term forms."
    )

    package = build_context_package(
        chunk,
        glossary_entries=glossary,
        tm_entries=tm_entries,
        style_guide_text=style_guide,
        chapter_notes_text=chapter_notes,
        settings=ContextBuildSettings(
            max_context_entries=4,
            max_glossary_exact=2,
            max_glossary_fuzzy=1,
            max_tm_matches=2,
            max_style_rules=2,
            chapter_notes_char_limit=120,
        ),
        tm_exact_threshold=0.995,
        tm_near_threshold=0.90,
    )

    assert len(package.exact_glossary) <= 2
    assert len(package.fuzzy_glossary) <= 1
    assert len(package.style_rules) <= 2
    assert len(package.named_entities) <= 4
    assert len(package.chapter_notes_excerpt) <= 120
    assert package.context_weight > 0
    payload = package.to_compact_payload()
    assert "exact_glossary" in payload
    assert "tm_matches" in payload


def test_prefilter_reuses_translation_memory_before_codex() -> None:
    chunk = _chunk(chunk_id="chunk-tm", text="Exact reusable sentence.")
    tm_entries = [
        TranslationMemoryEntry(
            source_text="Exact reusable sentence.",
            target_text="Точное переиспользуемое предложение.",
            chapter_id="chapter-01",
        ),
    ]
    decision = decide_prefilter_action(
        chunk,
        tm_entries=tm_entries,
        repeated_translations={},
        settings=PreFilterSettings(tm_first=True, exact_threshold=0.995, near_threshold=0.9),
    )
    assert decision.action == "reuse"
    assert decision.reason == "translation_memory_exact"
    assert "переиспользуемое" in decision.target_text


def test_prefilter_skips_non_translatable_fragments() -> None:
    chunk = _chunk(chunk_id="chunk-num", text="12/2025", chunk_type="auxiliary")
    decision = decide_prefilter_action(
        chunk,
        tm_entries=[],
        repeated_translations={},
        settings=PreFilterSettings(),
    )
    assert decision.action == "skip"
    assert decision.reason == "non_translatable_fragment"


def test_job_dedup_cache_hit_returns_existing_output(tmp_path: Path) -> None:
    chunk = _chunk(chunk_id="chunk-cache", text="Cache me if you can.")
    context = ContextPackage(
        exact_glossary=(),
        fuzzy_glossary=(),
        named_entities=(),
        chapter_term_decisions=(),
        style_rules=(),
        chapter_notes_excerpt="",
        tm_matches=(),
        context_weight=0,
    )
    fingerprint = build_content_fingerprint(
        chunk=chunk,
        context_package=context,
        profile_name="balanced",
        template_id="translate_chunk",
        template_version=1,
    )

    output_path = tmp_path / "output.json"
    output_payload = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "template_id": "translate_chunk",
        "job_id": "job-cache",
        "status": "ok",
        "chunk_id": "chunk-cache",
        "block_ids": ["block-chunk-cache"],
        "translated_text": "Кэш-перевод.",
        "preserved_footnote_markers": [],
        "notes": [],
        "errors": [],
    }
    output_path.write_text(json.dumps(output_payload), encoding="utf-8")

    cache_path = tmp_path / "job_cache.json"
    cache: dict[str, object] = {}
    update_cache_record(
        cache=cache,  # type: ignore[arg-type]
        fingerprint=fingerprint,
        template_id="translate_chunk",
        output_path=output_path,
        created_at="2026-03-12T10:00:00+00:00",
    )
    save_job_cache(cache_path, cache)  # type: ignore[arg-type]
    loaded_cache = load_job_cache(cache_path)

    hit = find_cache_hit(
        cache=loaded_cache,
        fingerprint=fingerprint,
        expected_job_id=None,
        expected_template_id="translate_chunk",
    )
    assert hit == output_path


def test_tier_routing_for_simple_and_complex_chunks() -> None:
    profile = get_profile("balanced")
    simple = _chunk(chunk_id="simple", text="A short plain sentence.")
    complex_chunk = _chunk(
        chunk_id="complex",
        text="1. Formula x = y/z [1]\n2. List item with 42% and matrix |a|.\n3. Rare epistemological term.",
        footnotes=[{"marker": "[1]"}],
        glossary_hints=["epistemology", "matrix"],
        metadata={"flags": ["layout_warning"]},
    )

    simple_assessment = assess_chunk_complexity(simple)
    complex_assessment = assess_chunk_complexity(complex_chunk)

    assert simple_assessment.score < complex_assessment.score
    assert (
        route_chunk_tier(
            simple_assessment,
            tier_b_threshold=profile.tier_b_threshold,
            tier_c_threshold=profile.tier_c_threshold,
        )
        == "A"
    )
    complex_tier = route_chunk_tier(
        complex_assessment,
        tier_b_threshold=profile.tier_b_threshold,
        tier_c_threshold=profile.tier_c_threshold,
    )
    assert complex_tier in {"B", "C"}
    assert "footnote_markers" in complex_assessment.risk_flags


@pytest.mark.parametrize(
    ("failure_reason", "attempt", "max_attempts", "strict_mode", "expected_strategy"),
    [
        ("invalid_json", 1, 3, False, "repair_json"),
        ("partial_json", 1, 3, False, "repair_json"),
        ("output_schema_validation_failed", 1, 3, False, "lightweight_recovery"),
        ("timeout", 1, 3, False, "reduce_chunk"),
        ("missing_output_file", 1, 3, True, "none"),
    ],
)
def test_retry_economy_directives(
    failure_reason: str,
    attempt: int,
    max_attempts: int,
    strict_mode: bool,
    expected_strategy: str,
) -> None:
    directive = decide_retry_directive(
        failure_reason=failure_reason,
        attempt=attempt,
        max_attempts=max_attempts,
        strict_mode=strict_mode,
    )
    assert directive.strategy == expected_strategy
    if expected_strategy == "none":
        assert directive.retry is False
    else:
        assert directive.retry is True


def test_budget_estimator_reports_reuse_and_profile_recommendation() -> None:
    chunks = [
        _chunk(chunk_id="c1", text="Exact reusable sentence."),
        _chunk(
            chunk_id="c2",
            text="List:\n1. Item [1]\n2. Item with equation x = y + 2",
            footnotes=[{"marker": "[1]"}],
            glossary_hints=["equation", "notation", "term"],
        ),
        _chunk(chunk_id="c3", text="Another ordinary paragraph for translation."),
    ]
    tm_entries = [
        TranslationMemoryEntry(
            source_text="Exact reusable sentence.",
            target_text="Точное переиспользуемое предложение.",
            chapter_id="chapter-01",
        )
    ]
    estimate = estimate_budget(
        chunks=chunks,
        tm_entries=tm_entries,
        profile=get_profile("balanced"),
        page_count=520,
        options=BudgetEstimatorOptions(),
    )

    assert estimate.estimated_chunk_count == 3
    assert estimate.estimated_local_reuse_count >= 1
    assert estimate.estimated_codex_job_count >= 1
    assert estimate.recommended_profile == "economy"
    assert estimate.estimated_retries_risk in {"low", "medium", "high"}


def test_economy_service_builds_plan_and_budget_artifacts(tmp_path: Path) -> None:
    project_root = tmp_path
    workspace_root = project_root / "workspace"
    book_id = "book-economy"
    book_root = workspace_root / book_id
    memory_dir = book_root / "memory"
    logs_dir = book_root / "logs"
    translated_dir = book_root / "translated"
    for directory in (memory_dir, logs_dir, translated_dir):
        directory.mkdir(parents=True, exist_ok=True)

    chunks = [
        _chunk(chunk_id="chunk-1", text="Exact reusable sentence."),
        _chunk(
            chunk_id="chunk-2", text="A complex clause with [1] and formula x = y + z.", footnotes=[{"marker": "[1]"}]
        ),
    ]
    manifest = BookManifest(
        book_id=book_id,
        source_pdf="input/original.pdf",
        chunks=chunks,
        metadata={"extraction": {"page_count": 42}},
    )
    save_book_manifest(book_root / "manifest.json", manifest)

    (memory_dir / "glossary.md").write_text(
        "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| formula | формула | noun | preferred | keep strict |\n",
        encoding="utf-8",
    )
    (memory_dir / "style_guide.md").write_text("# Style Guide\n- Keep formal style.\n", encoding="utf-8")
    (memory_dir / "chapter_notes.md").write_text(
        "# Chapter Notes\n\n## Global Notes\n- Preserve markers.\n", encoding="utf-8"
    )
    (memory_dir / "translation_memory.jsonl").write_text(
        json.dumps({"source_text": "Exact reusable sentence.", "target_text": "Точное переиспользуемое предложение."})
        + "\n",
        encoding="utf-8",
    )

    data = load_book_economy_data(project_root=project_root, workspace_dir_name="workspace", book_id=book_id)
    request = EconomyPlanRequest(profile="balanced", max_context_entries=8, max_retries=2)
    plan_result = build_economy_plan(data=data, request=request)

    assert plan_result.plan_path.exists()
    assert plan_result.summary_path.exists()
    assert plan_result.summary.chunk_count == plan_result.chunks_after

    report = estimate_book_budget(data=data, request=request)
    budget_path = write_budget_report(data=data, report=report, request=request)
    assert budget_path.exists()
