"""Mock Codex CLI executable used by protocol recovery tests."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

OUTPUT_SCHEMA_VERSION = "gpttranslator.codex.output.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--job-id", required=True)
    return parser.parse_args()


def next_attempt(job_dir: Path) -> int:
    counter_path = job_dir / ".mock_attempt_counter"
    if counter_path.exists():
        try:
            value = int(counter_path.read_text(encoding="utf-8").strip())
        except ValueError:
            value = 0
    else:
        value = 0

    attempt = value + 1
    counter_path.write_text(str(attempt), encoding="utf-8")
    return attempt


def _read_job_input(job_dir: Path) -> dict[str, object]:
    input_path = job_dir / "input.json"
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def write_valid_output(output_path: Path, job_input: dict[str, object], job_id: str, attempt: int) -> None:
    job_payload = job_input.get("job", {})
    content_payload = job_input.get("payload", {})

    template_id = "translate_chunk"
    if isinstance(job_payload, dict):
        raw_template_id = job_payload.get("template_id")
        if isinstance(raw_template_id, str) and raw_template_id.strip():
            template_id = raw_template_id

    chunk_id = "unknown-chunk"
    block_ids: list[str] = []
    footnote_markers: list[str] = []
    if isinstance(content_payload, dict):
        raw_chunk_id = content_payload.get("chunk_id")
        if isinstance(raw_chunk_id, str) and raw_chunk_id.strip():
            chunk_id = raw_chunk_id
        raw_block_ids = content_payload.get("block_ids")
        if isinstance(raw_block_ids, list):
            block_ids = [str(item) for item in raw_block_ids]
        raw_markers = content_payload.get("footnote_markers")
        if isinstance(raw_markers, list):
            footnote_markers = [str(item) for item in raw_markers]

    payload = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "template_id": template_id,
        "job_id": job_id,
        "status": "ok",
        "chunk_id": chunk_id,
        "block_ids": block_ids,
        "translated_text": f"translated-attempt-{attempt}",
        "preserved_footnote_markers": footnote_markers,
        "notes": [],
        "errors": [],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    job_dir = Path(args.job_dir).resolve()
    output_path = job_dir / "output.json"
    job_input = _read_job_input(job_dir)
    attempt = next_attempt(job_dir)
    scenario = os.environ.get("MOCK_CODEX_SCENARIO", "valid")

    if scenario == "invalid_then_valid" and attempt == 1:
        output_path.write_text("not-json\n", encoding="utf-8")
        print("mock stdout invalid")
        print("mock stderr invalid", file=sys.stderr)
        return 0

    if scenario == "partial_then_valid" and attempt == 1:
        output_path.write_text('{"schema_version":"gpttranslator.codex.output.v1",', encoding="utf-8")
        print("mock stdout partial")
        print("mock stderr partial", file=sys.stderr)
        return 0

    if scenario == "missing_then_valid" and attempt == 1:
        print("mock stdout missing")
        print("mock stderr missing", file=sys.stderr)
        return 0

    if scenario == "timeout_then_valid" and attempt == 1:
        time.sleep(float(os.environ.get("MOCK_CODEX_TIMEOUT_SLEEP", "2.0")))
        return 0

    if scenario == "interrupt_then_valid" and attempt == 1:
        os.kill(os.getpid(), signal.SIGTERM)
        return 0

    if scenario == "schema_invalid":
        output_path.write_text(json.dumps({"job_id": args.job_id}) + "\n", encoding="utf-8")
        print("mock stdout schema invalid")
        print("mock stderr schema invalid", file=sys.stderr)
        return 0

    write_valid_output(output_path, job_input, args.job_id, attempt)
    print(f"mock stdout attempt {attempt}")
    print(f"mock stderr attempt {attempt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
