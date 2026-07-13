from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

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
