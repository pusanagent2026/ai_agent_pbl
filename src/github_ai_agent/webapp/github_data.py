from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from github_ai_agent.github_app_auth import GitHubAppTokenProvider, resolve_default_repository
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.webapp.auth import github_get


def load_repositories(session: dict[str, Any] | None = None) -> list[dict[str, str]]:
    session = session or {}
    user_token = str(session.get("github_access_token") or "")
    if user_token:
        return load_user_installation_repositories(user_token)

    provider = GitHubAppTokenProvider()
    if not provider.enabled:
        return []
    repositories = provider.list_installation_repositories()
    installation_id = provider.config.installation_id
    return format_repositories(repositories, installation_id)


def load_user_installation_repositories(token: str) -> list[dict[str, str]]:
    installations = github_get("/user/installations?per_page=100", token).get("installations", [])
    result: list[dict[str, str]] = []
    if not isinstance(installations, list):
        return result
    for installation in installations:
        if not isinstance(installation, dict):
            continue
        installation_id = str(installation.get("id") or "")
        if not installation_id:
            continue
        payload = github_get(f"/user/installations/{installation_id}/repositories?per_page=100", token)
        repositories = payload.get("repositories", [])
        if isinstance(repositories, list):
            result.extend(format_repositories(repositories, installation_id))
    return result


def format_repositories(
    repositories: list[Any],
    installation_id: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in repositories:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "")
        if "/" not in full_name:
            continue
        owner, repo = full_name.split("/", 1)
        result.append(
            {
                "owner": owner,
                "repo": repo,
                "full_name": full_name,
                "installation_id": installation_id,
            }
        )
    return result


def select_default_repository(repositories: list[dict[str, str]]) -> tuple[str, str, str]:
    if repositories:
        first = repositories[0]
        return first.get("owner", ""), first.get("repo", ""), first.get("installation_id", "")
    owner, repo = resolve_default_repository()
    return owner, repo, os.environ.get("GITHUB_APP_INSTALLATION_ID", "")


def load_config_members(owner: str, repo: str, installation_id: str = "") -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        warnings: list[str] = []
        raw_payloads: list[str] = []
        async with GitHubMcpClient(installation_id=installation_id or None) as tools:
            available_tools = await tools.list_tools()
            tool_names = {tool.name for tool in available_tools}
            for tool_name, arguments in mcp_member_tool_calls(tool_names, owner, repo):
                try:
                    raw_payloads.append(await tools.call_tool(tool_name, arguments))
                except Exception as error:
                    warnings.append(f"{tool_name} 조회 실패: {error}")
        members = extract_members(*raw_payloads)
        if not members:
            warnings.append("MCP에서 확인된 팀원 ID 없음")
        return {"members": members, "member_warnings": warnings}

    try:
        return asyncio.run(load())
    except Exception as error:
        return {"members": [], "member_warnings": [f"GitHub MCP 연결 실패: {error}"]}


def mcp_member_tool_calls(
    tool_names: set[str],
    owner: str,
    repo: str,
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    exact_candidates = (
        ("list_repository_collaborators", {"owner": owner, "repo": repo, "perPage": 50}),
        ("list_contributors", {"owner": owner, "repo": repo, "perPage": 50}),
        ("list_collaborators", {"owner": owner, "repo": repo, "perPage": 50}),
        ("list_commits", {"owner": owner, "repo": repo, "perPage": 50}),
    )
    for tool_name, arguments in exact_candidates:
        if tool_name in tool_names:
            calls.append((tool_name, arguments))
    if calls:
        return calls

    for tool_name in sorted(tool_names):
        lowered = tool_name.lower()
        if any(keyword in lowered for keyword in ("contributor", "collaborator", "member")):
            calls.append((tool_name, {}))
    return calls


def extract_warnings(raw: str, label: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict) and parsed.get("error"):
        code = parsed.get("error")
        if code in {401, 403}:
            return [f"{label} 권한 필요"]
        return [f"{label} 조회 오류 {code}"]
    return []


def is_empty_list(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list) and len(parsed) == 0


def extract_members(*raw_payloads: str) -> list[dict[str, str]]:
    by_login: dict[str, dict[str, str]] = {}
    for raw in raw_payloads:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if parsed.get("error"):
                continue
            items = parsed.get("items", [])
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            login = str(item.get("login") or "").strip()
            if not login:
                user = item.get("user")
                if isinstance(user, dict):
                    login = str(user.get("login") or "").strip()
            if not login:
                author = item.get("author")
                if isinstance(author, dict):
                    login = str(author.get("login") or "").strip()
            if not login:
                committer = item.get("committer")
                if isinstance(committer, dict):
                    login = str(committer.get("login") or "").strip()
            if not login:
                continue
            current = by_login.setdefault(
                login.lower(),
                {"github_id": login, "name": str(item.get("name") or login), "source": "github"},
            )
            if item.get("contributions") is not None:
                current["contributions"] = str(item.get("contributions"))
            if item.get("role_name"):
                current["role"] = str(item.get("role_name"))
    return sorted(by_login.values(), key=lambda member: member["github_id"].lower())
