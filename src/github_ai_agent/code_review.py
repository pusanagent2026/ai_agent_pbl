"""Code review domain: browse a branch's files on GitHub and ask the LLM to
point out real errors (only if any exist) and leave 1-3 short good/bad
comments about a selected file. Structured JSON in, structured JSON out —
shown directly in the web UI, nothing is written back to GitHub.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from github_ai_agent.github_api_client import (
    fetch_branches,
    fetch_file_content,
    fetch_repo_tree,
)
from github_ai_agent.github_app_auth import GitHubAppTokenProvider

MAX_FILE_CHARS = 20000

REVIEW_FILE_SYSTEM_PROMPT = """
당신은 GitHub 저장소의 파일 전체 코드를 검토하는 코드 리뷰 에이전트입니다.

규칙:
1. errors는 실제 오류(문법 오류, 실행/환경 의존성 문제, 잘못되거나 오해를 부르는 변수명 등)가
   있을 때만 채우세요. 확실한 오류가 없으면 반드시 빈 배열로 두세요. 사소한 스타일 취향은
   오류로 넣지 마세요.
2. 각 오류 항목에는 파일의 어떤 문제인지(issue)와 구체적으로 어떻게 고치면 되는지(fix)를
   반드시 포함하세요. 라인 번호를 알 수 있으면 line에 채우고, 모르면 null로 두세요.
3. comments에는 이 파일에서 잘한 점과 아쉬운 점을 합쳐 1개에서 3개까지 작성하세요. 각 항목은
   1~3문장으로 짧고 구체적으로 쓰고, type은 "good" 또는 "bad" 중 하나여야 합니다.
4. summary는 이 파일이 하는 일과 전반적인 코드 품질을 한두 문장으로 요약하세요.
5. 반드시 한국어로 답하고, 아래 JSON 스키마만 그대로 출력하세요. 다른 텍스트는 출력하지 마세요.

{
  "summary": "짧은 전체 요약",
  "errors": [
    {"file": "path/to/file", "line": 12, "issue": "문제 설명", "fix": "구체적인 수정 방법"}
  ],
  "comments": [
    {"type": "good", "file": "path/to/file", "comment": "짧은 코멘트"}
  ]
}
""".strip()


def _resolve_github_token(installation_id: str, session_token: str) -> str:
    provider = GitHubAppTokenProvider(installation_id or None)
    if provider.enabled:
        return provider.create_installation_token()
    if session_token:
        return session_token
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token
    raise ValueError("GitHub 인증 정보가 없습니다. 저장소를 먼저 연결하세요.")


async def list_branches(
    owner: str,
    repo: str,
    *,
    installation_id: str = "",
    session_token: str = "",
) -> list[dict[str, Any]]:
    if not owner or not repo:
        return []
    token = _resolve_github_token(installation_id, session_token)
    return fetch_branches(token, owner, repo)


async def list_repo_tree(
    owner: str,
    repo: str,
    branch: str,
    *,
    installation_id: str = "",
    session_token: str = "",
) -> dict[str, Any]:
    if not owner or not repo or not branch:
        return {"files": [], "truncated": False}
    token = _resolve_github_token(installation_id, session_token)
    files, truncated = fetch_repo_tree(token, owner, repo, branch)
    return {"files": files, "truncated": truncated}


async def review_file(
    owner: str,
    repo: str,
    branch: str,
    path: str,
    *,
    installation_id: str = "",
    session_token: str = "",
) -> dict[str, Any]:
    token = _resolve_github_token(installation_id, session_token)
    file_info = fetch_file_content(token, owner, repo, path, branch)

    if file_info["too_large"]:
        return {
            "summary": "파일이 너무 커서 리뷰할 수 없습니다.",
            "errors": [],
            "comments": [],
            "files_reviewed": [path],
            "selected_tools": [{"tool": "fetch_file_content", "arguments": {"owner": owner, "repo": repo, "path": path, "ref": branch}}],
        }
    if file_info["binary"] or not file_info["content"]:
        return {
            "summary": "텍스트 파일이 아니거나 내용을 가져올 수 없어 리뷰할 수 없습니다.",
            "errors": [],
            "comments": [],
            "files_reviewed": [path],
            "selected_tools": [{"tool": "fetch_file_content", "arguments": {"owner": owner, "repo": repo, "path": path, "ref": branch}}],
        }

    content = file_info["content"]
    truncated = False
    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS] + "\n... (truncated)"
        truncated = True

    client = AsyncOpenAI()
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": REVIEW_FILE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{owner}/{repo} 저장소의 {branch} 브랜치, 파일 {path}의 전체 코드입니다"
                    f"{' (길이 제한으로 일부 생략됨)' if truncated else ''}:\n\n{content}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    result = _parse_review_json(completion.choices[0].message.content or "")
    result["files_reviewed"] = [path]
    result["selected_tools"] = [
        {"tool": "fetch_file_content", "arguments": {"owner": owner, "repo": repo, "path": path, "ref": branch}}
    ]
    return result


def _parse_review_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"summary": raw.strip() or "리뷰 결과를 파싱하지 못했습니다.", "errors": [], "comments": []}
    if not isinstance(parsed, dict):
        return {"summary": "리뷰 결과를 파싱하지 못했습니다.", "errors": [], "comments": []}

    errors = [item for item in parsed.get("errors", []) if isinstance(item, dict)] if isinstance(parsed.get("errors"), list) else []
    comments = [item for item in parsed.get("comments", []) if isinstance(item, dict)] if isinstance(parsed.get("comments"), list) else []

    normalized_errors = [
        {
            "file": str(item.get("file") or ""),
            "line": item.get("line") if isinstance(item.get("line"), int) else None,
            "issue": str(item.get("issue") or ""),
            "fix": str(item.get("fix") or ""),
        }
        for item in errors
    ]
    normalized_comments = [
        {
            "type": item.get("type") if item.get("type") in ("good", "bad") else "good",
            "file": str(item.get("file") or ""),
            "comment": str(item.get("comment") or ""),
        }
        for item in comments
    ][:3]

    return {
        "summary": str(parsed.get("summary") or ""),
        "errors": normalized_errors,
        "comments": normalized_comments,
    }
