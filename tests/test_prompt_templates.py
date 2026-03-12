"""Tests for production prompt template rendering."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.translation.protocol import (
    OUTPUT_SCHEMA_VERSION,
    PROMPT_TEMPLATE_SPECS,
    build_prompt_template_payload,
    render_prompt,
)


@pytest.mark.parametrize("template_id", sorted(PROMPT_TEMPLATE_SPECS.keys()))
def test_render_prompt_renders_all_templates_without_placeholders(template_id: str) -> None:
    payload = build_prompt_template_payload(
        job_id="job-123",
        input_json_path=Path("/tmp/workspace/book/jobs/job-123/input.json"),
        output_json_path=Path("/tmp/workspace/book/jobs/job-123/output.json"),
        template_id=template_id,
    )

    rendered = render_prompt(payload)

    assert template_id in rendered
    assert "job-123" in rendered
    assert "/tmp/workspace/book/jobs/job-123/input.json" in rendered
    assert "/tmp/workspace/book/jobs/job-123/output.json" in rendered
    assert OUTPUT_SCHEMA_VERSION in rendered
    assert "payload.glossary" in rendered
    assert "payload.style_guide" in rendered
    assert "payload.chapter_notes" in rendered
    assert "footnote markers" in rendered.lower()
    assert "block_ids" in rendered
    assert "{{" not in rendered
    assert "}}" not in rendered
    assert "```json" in rendered


def test_render_prompt_rejects_unknown_template_id() -> None:
    with pytest.raises(ValueError, match="Unknown template_id"):
        build_prompt_template_payload(
            job_id="job-123",
            input_json_path=Path("/tmp/in.json"),
            output_json_path=Path("/tmp/out.json"),
            template_id="unknown_template",
        )
