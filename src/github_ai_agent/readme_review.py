"""README-update domain for the web UI's "README 갱신" tab: analyze a
branch's latest commit via the GitHub REST API and, on approval, open a PR
with the rewritten README.md. Mirrors code_review.py's shape (token
resolution, GitHub API fetch, then an LLM call) but uses the shared
filter/rewrite logic in readme_updater.py so this stays identical to the
GitHub Actions pipeline's judgment.
"""

from __future__ import annotations

import difflib
import time
from typing import Any

from openai import OpenAI

from github_ai_agent import readme_updater
from github_ai_agent.github_api_client import (
    create_branch,
    create_pull_request,
    fetch_file_content,
    fetch_latest_commit_diff,
    get_branch_head_sha,
    resolve_github_token,
    update_file_content,
)

README_PATH = "README.md"
PR_TITLE = "docs: README 자동 최신화"


def _build_line_diff(current: str, proposed: str) -> list[dict[str, str]]:
    """Side-by-side diff rows: each row pairs a line from the old README
    (left) with a line from the new one (right) so both stay visible at
    once, instead of one interleaved unified list.
    """
    current_lines = current.splitlines()
    proposed_lines = proposed.splitlines()
    matcher = difflib.SequenceMatcher(None, current_lines, proposed_lines)
    rows: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for left, right in zip(current_lines[i1:i2], proposed_lines[j1:j2]):
                rows.append(
                    {"left": left, "left_type": "equal", "right": right, "right_type": "equal"}
                )
            continue
        left_slice = current_lines[i1:i2]
        right_slice = proposed_lines[j1:j2]
        for idx in range(max(len(left_slice), len(right_slice))):
            has_left = idx < len(left_slice)
            has_right = idx < len(right_slice)
            rows.append(
                {
                    "left": left_slice[idx] if has_left else "",
                    "left_type": "remove" if has_left else "empty",
                    "right": right_slice[idx] if has_right else "",
                    "right_type": "add" if has_right else "empty",
                }
            )
    return rows


async def analyze_readme_update(
    owner: str,
    repo: str,
    branch: str,
    *,
    installation_id: str = "",
    session_token: str = "",
) -> dict[str, Any]:
    token = resolve_github_token(installation_id, session_token)
    commit = fetch_latest_commit_diff(token, owner, repo, branch)
    changed_files = commit["changed_files"]

    # Cheap path-only pre-check so a hard-skip avoids the README fetch below.
    if not changed_files or readme_updater.layer1_rule_filter(changed_files, [])["hard_skip"]:
        return {
            "relevant": False,
            "changed": False,
            "commit_sha": commit["sha"],
            "commit_message": commit["message"],
            "current_readme": "",
            "proposed_readme": "",
            "summary": "",
            "diff": [],
        }

    current = fetch_file_content(token, owner, repo, README_PATH, branch)
    current_readme = current["content"]

    client = OpenAI(timeout=60)
    relevant, trace = readme_updater.should_update_readme(
        commit["diff_text"], changed_files, [commit["message"]], client
    )
    print(f"3-layer filter trace: {trace}")
    if not relevant:
        return {
            "relevant": False,
            "changed": False,
            "commit_sha": commit["sha"],
            "commit_message": commit["message"],
            "current_readme": current_readme,
            "proposed_readme": "",
            "summary": "",
            "diff": [],
        }

    proposed_readme, summary = readme_updater.rewrite_readme(
        commit["diff_text"], changed_files, current_readme, client
    )
    changed = proposed_readme.strip() != current_readme.strip()

    return {
        "relevant": True,
        "changed": changed,
        "commit_sha": commit["sha"],
        "commit_message": commit["message"],
        "current_readme": current_readme,
        "proposed_readme": proposed_readme if changed else current_readme,
        "summary": summary,
        "diff": _build_line_diff(current_readme, proposed_readme) if changed else [],
    }


async def apply_readme_update(
    owner: str,
    repo: str,
    base_branch: str,
    readme_content: str,
    summary: str,
    *,
    installation_id: str = "",
    session_token: str = "",
) -> dict[str, Any]:
    token = resolve_github_token(installation_id, session_token)

    head_sha = get_branch_head_sha(token, owner, repo, base_branch)
    new_branch = f"docs/web-readme-update-{int(time.time())}"
    create_branch(token, owner, repo, new_branch, head_sha)

    existing = fetch_file_content(token, owner, repo, README_PATH, new_branch)
    update_file_content(
        token,
        owner,
        repo,
        README_PATH,
        new_branch,
        readme_content,
        PR_TITLE,
        existing["sha"],
    )

    pr = create_pull_request(
        token,
        owner,
        repo,
        PR_TITLE,
        summary or "README를 최신 변경 사항에 맞게 갱신했습니다.",
        new_branch,
        base_branch,
    )
    return {"pr_url": pr["html_url"], "branch": new_branch}
