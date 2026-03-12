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


def write_valid_output(output_path: Path, job_id: str, attempt: int) -> None:
    payload = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "job_id": job_id,
        "status": "ok",
        "translated_text": f"translated-attempt-{attempt}",
        "notes": [],
        "errors": [],
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    job_dir = Path(args.job_dir).resolve()
    output_path = job_dir / "output.json"
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

    write_valid_output(output_path, args.job_id, attempt)
    print(f"mock stdout attempt {attempt}")
    print(f"mock stderr attempt {attempt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
