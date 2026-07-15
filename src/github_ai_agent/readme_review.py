"""README-update domain for the web UI's "README 갱신" tab: analyze a
branch's latest commit via the GitHub REST API and, on approval, open a PR
with the rewritten README.md. Mirrors code_review.py's shape (token
resolution, GitHub API fetch, then an LLM call) but uses the shared
filter/rewrite logic in readme_updater.py so this stays identical to the
GitHub Actions pipeline's judgment.
"""

from __future__ import annotations

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

    if not changed_files or readme_updater.is_doc_only_change(changed_files):
        return {
            "relevant": False,
            "changed": False,
            "commit_sha": commit["sha"],
            "commit_message": commit["message"],
            "current_readme": "",
            "proposed_readme": "",
            "summary": "",
        }

    current = fetch_file_content(token, owner, repo, README_PATH, branch)
    current_readme = current["content"]

    client = OpenAI(timeout=60)
    relevant = readme_updater.is_relevant(commit["diff_text"], changed_files, client)
    if not relevant:
        return {
            "relevant": False,
            "changed": False,
            "commit_sha": commit["sha"],
            "commit_message": commit["message"],
            "current_readme": current_readme,
            "proposed_readme": "",
            "summary": "",
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
