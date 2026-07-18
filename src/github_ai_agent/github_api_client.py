from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from github_ai_agent.github_app_auth import GitHubAppTokenProvider
from github_ai_agent.mcp_client import McpTool


@dataclass(frozen=True)
class GitHubApiConfig:
    token: str
    owner: str
    repo: str


class DirectGitHubToolClient:
    """Expose GitHub REST endpoints using the same list_tools/call_tool shape."""

    def __init__(
        self,
        *,
        token: str | None = None,
        owner: str | None = None,
        repo: str | None = None,
    ) -> None:
        self.config = GitHubApiConfig(
            token=token or os.environ.get("GITHUB_TOKEN", ""),
            owner=owner or os.environ.get("GITHUB_OWNER", ""),
            repo=repo or os.environ.get("GITHUB_REPO", ""),
        )
        if not self.config.token:
            raise ValueError("GITHUB_TOKEN is required.")
        if not self.config.owner or not self.config.repo:
            raise ValueError("GITHUB_OWNER and GITHUB_REPO are required.")

    async def __aenter__(self) -> "DirectGitHubToolClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                name="get_repository",
                description="Get repository metadata, default branch, counts, and timestamps.",
                input_schema=self._schema({}),
            ),
            McpTool(
                name="list_issues",
                description="List repository issues. Useful for blockers, todos, bugs, and planning today's work.",
                input_schema=self._schema(
                    {
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "default": "open",
                        },
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 10,
                        },
                    }
                ),
            ),
            McpTool(
                name="list_pull_requests",
                description="List repository pull requests. Useful for review status, pending work, and recent activity.",
                input_schema=self._schema(
                    {
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "default": "open",
                        },
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 10,
                        },
                    }
                ),
            ),
            McpTool(
                name="list_commits",
                description="List recent commits. Useful for summarizing recent changes and project momentum.",
                input_schema=self._schema(
                    {
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 10,
                        }
                    }
                ),
            ),
            McpTool(
                name="list_contributors",
                description=(
                    "List repository contributors based on commits. Useful when the user asks "
                    "who is on the team or who has been active in the repository."
                ),
                input_schema=self._schema(
                    {
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 20,
                        }
                    }
                ),
            ),
            McpTool(
                name="list_collaborators",
                description=(
                    "List repository collaborators visible to the token. Useful for identifying "
                    "people who have access to the repository. May require additional GitHub token permissions."
                ),
                input_schema=self._schema(
                    {
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 20,
                        }
                    }
                ),
            ),
            McpTool(
                name="list_organization_members",
                description=(
                    "List members of the organization that owns the repository. Useful as a fallback "
                    "when collaborator lookup is restricted for organization-owned repositories."
                ),
                input_schema=self._schema(
                    {
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 20,
                        }
                    }
                ),
            ),
            McpTool(
                name="list_workflow_runs",
                description="List recent GitHub Actions workflow runs. Useful for CI status and broken builds.",
                input_schema=self._schema(
                    {
                        "per_page": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 10,
                        }
                    }
                ),
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "get_repository":
            return self._get_json(f"/repos/{self.config.owner}/{self.config.repo}")
        if name == "list_issues":
            return self._get_json(
                f"/repos/{self.config.owner}/{self.config.repo}/issues",
                self._pick(arguments, state="open", per_page=10),
            )
        if name == "list_pull_requests":
            return self._get_json(
                f"/repos/{self.config.owner}/{self.config.repo}/pulls",
                self._pick(arguments, state="open", per_page=10),
            )
        if name == "list_commits":
            return self._get_json(
                f"/repos/{self.config.owner}/{self.config.repo}/commits",
                self._pick(arguments, per_page=10),
            )
        if name == "list_contributors":
            return self._get_json(
                f"/repos/{self.config.owner}/{self.config.repo}/contributors",
                self._pick(arguments, per_page=20),
            )
        if name == "list_collaborators":
            return self._get_json(
                f"/repos/{self.config.owner}/{self.config.repo}/collaborators",
                self._pick(arguments, per_page=20),
            )
        if name == "list_organization_members":
            return self._get_json(
                f"/orgs/{self.config.owner}/members",
                self._pick(arguments, per_page=20),
            )
        if name == "list_workflow_runs":
            return self._get_json(
                f"/repos/{self.config.owner}/{self.config.repo}/actions/runs",
                self._pick(arguments, per_page=10),
            )
        raise ValueError(f"Unknown GitHub API tool: {name}")

    def _schema(self, properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }

    def _pick(self, arguments: dict[str, Any], **defaults: Any) -> dict[str, Any]:
        picked = dict(defaults)
        for key in defaults:
            if key in arguments and arguments[key] is not None:
                picked[key] = arguments[key]
        return picked

    def _get_json(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = "https://api.github.com" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.config.token}",
                "User-Agent": "github-ai-tool-choosing-agent",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            return json.dumps(
                {"error": error.code, "message": body, "url": url},
                ensure_ascii=False,
            )

        parsed = json.loads(payload)
        return json.dumps(self._compact(parsed), ensure_ascii=False, indent=2)

    def _compact(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._compact(item) for item in value[:20]]

        if not isinstance(value, dict):
            return value

        keep = {
            "id",
            "number",
            "state",
            "title",
            "body",
            "html_url",
            "created_at",
            "updated_at",
            "closed_at",
            "merged_at",
            "name",
            "full_name",
            "description",
            "default_branch",
            "open_issues_count",
            "stargazers_count",
            "forks_count",
            "pushed_at",
            "status",
            "conclusion",
            "event",
            "head_branch",
            "run_number",
            "run_started_at",
            "message",
            "login",
            "type",
            "contributions",
            "permissions",
            "role_name",
        }
        compacted: dict[str, Any] = {}

        for key, item in value.items():
            if key in keep:
                compacted[key] = item
            elif key in {"user", "author"} and isinstance(item, dict):
                compacted[key] = {"login": item.get("login")}
            elif key == "commit" and isinstance(item, dict):
                compacted[key] = {
                    "message": item.get("message"),
                    "author": item.get("author"),
                }
            elif key == "workflow_runs":
                compacted[key] = self._compact(item)

        return compacted


def _github_request(path: str, token: str, query: dict[str, Any] | None = None) -> Any:
    """Direct authenticated GitHub REST call, independent of DirectGitHubToolClient's
    env-var-only token (callers here may hold an OAuth session token or a GitHub App
    installation token instead)."""

    url = "https://api.github.com" + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "github-ai-mcp-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"GitHub API error {error.code} for {path}: {body}") from error


def _github_write_request(path: str, token: str, method: str, data: dict[str, Any]) -> Any:
    """POST/PUT counterpart to _github_request, for the branch/commit/PR
    creation calls used by the web UI's README-update approval flow."""

    url = "https://api.github.com" + path
    body = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "github-ai-mcp-agent",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"GitHub API error {error.code} for {method} {path}: {error_body}") from error


MAX_TREE_FILES = 1000
MAX_FILE_CONTENT_BYTES = 200_000
MAX_DIFF_CHARS = 12000


def fetch_branches(
    token: str,
    owner: str,
    repo: str,
    *,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    payload = _github_request(
        f"/repos/{owner}/{repo}/branches",
        token,
        {"per_page": per_page},
    )
    if not isinstance(payload, list):
        return []
    return [
        {
            "name": item.get("name"),
            "sha": (item.get("commit") or {}).get("sha", ""),
        }
        for item in payload
        if isinstance(item, dict)
    ]


def fetch_repo_tree(
    token: str,
    owner: str,
    repo: str,
    branch: str,
) -> tuple[list[dict[str, Any]], bool]:
    payload = _github_request(
        f"/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(branch, safe='')}",
        token,
        {"recursive": "1"},
    )
    if not isinstance(payload, dict):
        return [], False

    entries = payload.get("tree", [])
    if not isinstance(entries, list):
        entries = []

    files = [
        {"path": item.get("path"), "size": item.get("size") or 0}
        for item in entries
        if isinstance(item, dict) and item.get("type") == "blob"
    ]

    truncated = bool(payload.get("truncated"))
    if len(files) > MAX_TREE_FILES:
        files = files[:MAX_TREE_FILES]
        truncated = True

    return files, truncated


def fetch_file_content(
    token: str,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    payload = _github_request(
        f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}",
        token,
        {"ref": ref},
    )
    if not isinstance(payload, dict):
        return {"content": "", "too_large": False, "binary": True, "sha": ""}

    sha = str(payload.get("sha") or "")
    size = payload.get("size") or 0
    if size > MAX_FILE_CONTENT_BYTES:
        return {"content": "", "too_large": True, "binary": False, "sha": sha}

    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        return {"content": "", "too_large": False, "binary": True, "sha": sha}

    try:
        raw_bytes = base64.b64decode(payload["content"])
        content = raw_bytes.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return {"content": "", "too_large": False, "binary": True, "sha": sha}

    return {"content": content, "too_large": False, "binary": False, "sha": sha}


def fetch_latest_commit_diff(
    token: str,
    owner: str,
    repo: str,
    branch: str,
) -> dict[str, Any]:
    """Diff of the latest commit on `branch`, built from the GitHub API's
    per-file patches (no local git checkout needed)."""

    payload = _github_request(f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(branch, safe='')}", token)
    if not isinstance(payload, dict):
        return {"sha": "", "message": "", "changed_files": [], "diff_text": ""}

    files = payload.get("files", [])
    files = files if isinstance(files, list) else []

    changed_files = [str(item.get("filename")) for item in files if isinstance(item, dict) and item.get("filename")]
    diff_parts = []
    for item in files:
        if not isinstance(item, dict) or not item.get("patch"):
            continue
        filename = item.get("filename", "")
        diff_parts.append(f"--- {filename}\n+++ {filename}\n{item['patch']}")
    diff_text = "\n\n".join(diff_parts)
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n... (diff truncated for length)"

    commit = payload.get("commit") if isinstance(payload.get("commit"), dict) else {}
    return {
        "sha": str(payload.get("sha") or ""),
        "message": str(commit.get("message") or ""),
        "changed_files": changed_files,
        "diff_text": diff_text,
    }


def get_branch_head_sha(token: str, owner: str, repo: str, branch: str) -> str:
    payload = _github_request(f"/repos/{owner}/{repo}/git/ref/heads/{urllib.parse.quote(branch, safe='')}", token)
    if not isinstance(payload, dict):
        raise ValueError(f"Could not resolve head sha for branch {branch!r}.")
    object_info = payload.get("object")
    sha = object_info.get("sha") if isinstance(object_info, dict) else None
    if not sha:
        raise ValueError(f"Could not resolve head sha for branch {branch!r}.")
    return str(sha)


def create_branch(token: str, owner: str, repo: str, new_branch: str, from_sha: str) -> None:
    _github_write_request(
        f"/repos/{owner}/{repo}/git/refs",
        token,
        "POST",
        {"ref": f"refs/heads/{new_branch}", "sha": from_sha},
    )


def update_file_content(
    token: str,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    content: str,
    message: str,
    sha: str,
) -> None:
    _github_write_request(
        f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}",
        token,
        "PUT",
        {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
            "sha": sha,
        },
    )


def create_pull_request(
    token: str,
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
) -> dict[str, Any]:
    payload = _github_write_request(
        f"/repos/{owner}/{repo}/pulls",
        token,
        "POST",
        {"title": title, "body": body, "head": head, "base": base},
    )
    if not isinstance(payload, dict):
        raise ValueError("Unexpected response creating pull request.")
    return {"html_url": str(payload.get("html_url") or ""), "number": payload.get("number")}


def resolve_github_token(installation_id: str, session_token: str) -> str:
    provider = GitHubAppTokenProvider(installation_id or None)
    if provider.enabled:
        return provider.create_installation_token()
    if session_token:
        return session_token
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token
    raise ValueError("GitHub 인증 정보가 없습니다. 저장소를 먼저 연결하세요.")
