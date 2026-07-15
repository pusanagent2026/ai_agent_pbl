"""Analyzes a push diff and rewrites README.md when the change is user-facing.

Invoked by .github/workflows/readme-autoupdate.yml as:
    python scripts/update_readme.py <base_sha> <head_sha>

Writes `readme_changed` (and `summary` when true) to $GITHUB_OUTPUT so the
workflow can decide whether to open a PR. Never writes secrets to stdout.

The filter/rewrite LLM logic lives in github_ai_agent.readme_updater (shared
with the web UI's "README 갱신" tab); only git-specific diff extraction and
the GITHUB_OUTPUT writer stay in this script.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI  # noqa: E402

from github_ai_agent.readme_updater import (  # noqa: E402
    MAX_DIFF_CHARS,
    is_doc_only_change,
    is_relevant,
    rewrite_readme,
)

README_PATH = Path("README.md")
ALL_ZERO_SHA = "0" * 40


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def resolve_diff_range(base_sha: str, head_sha: str) -> tuple[str, str] | None:
    if not base_sha or base_sha == ALL_ZERO_SHA:
        return None
    try:
        run_git(["cat-file", "-e", base_sha])
    except RuntimeError:
        return None
    return base_sha, head_sha


def get_changed_files(base_sha: str, head_sha: str) -> list[str]:
    raw = run_git(["diff", "--name-only", base_sha, head_sha])
    return [line for line in raw.splitlines() if line]


def get_diff(base_sha: str, head_sha: str) -> str:
    raw = run_git(["diff", base_sha, head_sha])
    if len(raw) > MAX_DIFF_CHARS:
        return raw[:MAX_DIFF_CHARS] + "\n... (diff truncated for length)"
    return raw


def write_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"[GITHUB_OUTPUT unavailable] {name}={value}")
        return
    delimiter = f"ghadelim_{uuid.uuid4().hex}"
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: update_readme.py <base_sha> <head_sha>")
        sys.exit(1)

    base_sha, head_sha = sys.argv[1], sys.argv[2]
    diff_range = resolve_diff_range(base_sha, head_sha)
    if diff_range is None:
        print("No usable base commit (initial push or missing history); skipping.")
        write_github_output("readme_changed", "false")
        return

    base_sha, head_sha = diff_range
    try:
        changed_files = get_changed_files(base_sha, head_sha)
    except RuntimeError as error:
        print(f"Failed to compute changed files: {error}")
        write_github_output("readme_changed", "false")
        return

    if is_doc_only_change(changed_files):
        print("Only README/docs changed (or nothing changed); skipping to avoid loops.")
        write_github_output("readme_changed", "false")
        return

    diff_text = get_diff(base_sha, head_sha)
    client = OpenAI(timeout=60)

    if not is_relevant(diff_text, changed_files, client):
        print("Filter model judged that no README update is needed.")
        write_github_output("readme_changed", "false")
        return

    current_readme = README_PATH.read_text(encoding="utf-8")
    new_readme, summary = rewrite_readme(diff_text, changed_files, current_readme, client)

    if new_readme.strip() == current_readme.strip():
        print("Rewrite produced no effective change; skipping PR.")
        write_github_output("readme_changed", "false")
        return

    README_PATH.write_text(new_readme, encoding="utf-8")
    write_github_output("readme_changed", "true")
    write_github_output("summary", summary or "README를 최신 변경 사항에 맞게 갱신했습니다.")
    print("README.md updated.")


if __name__ == "__main__":
    main()
