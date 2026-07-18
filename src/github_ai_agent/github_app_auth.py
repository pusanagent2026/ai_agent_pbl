from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt


@dataclass(frozen=True)
class GitHubAppConfig:
    app_id: str
    installation_id: str
    private_key: str
    private_key_file: str


class GitHubAppTokenProvider:
    def __init__(self, installation_id: str | None = None) -> None:
        self.config = GitHubAppConfig(
            app_id=os.environ.get("GITHUB_APP_ID", ""),
            installation_id=installation_id or os.environ.get("GITHUB_APP_INSTALLATION_ID", ""),
            private_key=os.environ.get("GITHUB_APP_PRIVATE_KEY", ""),
            private_key_file=os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE", ""),
        )

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.app_id
            and self.config.installation_id
            and (self.config.private_key or self.config.private_key_file)
        )

    def create_installation_token(self) -> str:
        if not self.enabled:
            raise ValueError(
                "GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, and GitHub App private key are required."
            )
        jwt_token = self._create_jwt()
        request = urllib.request.Request(
            f"https://api.github.com/app/installations/{self.config.installation_id}/access_tokens",
            data=b"{}",
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt_token}",
                "User-Agent": "github-ai-mcp-agent",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = payload.get("token")
        if not token:
            raise ValueError("GitHub App installation token response did not include a token.")
        return str(token)

    def list_installation_repositories(self) -> list[dict[str, Any]]:
        token = self.create_installation_token()
        request = urllib.request.Request(
            "https://api.github.com/installation/repositories?per_page=100",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "github-ai-mcp-agent",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        repositories = payload.get("repositories", [])
        return repositories if isinstance(repositories, list) else []

    def _create_jwt(self) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iat": now - 60,
            "exp": now + 540,
            "iss": self.config.app_id,
        }
        return jwt.encode(payload, self._private_key(), algorithm="RS256")

    def _private_key(self) -> str:
        if self.config.private_key:
            return self.config.private_key.replace("\\n", "\n")
        path = Path(self.config.private_key_file)
        if not path.exists():
            raise ValueError(f"GitHub App private key file does not exist: {path}")
        return path.read_text(encoding="utf-8")


def resolve_default_repository() -> tuple[str, str]:
    owner = os.environ.get("GITHUB_OWNER", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    if owner and repo:
        return owner, repo

    provider = GitHubAppTokenProvider()
    if not provider.enabled:
        return owner, repo

    repositories = provider.list_installation_repositories()
    if not repositories:
        return owner, repo

    preferred_full_name = os.environ.get("GITHUB_APP_REPOSITORY", "").strip().lower()
    selected = None
    if preferred_full_name:
        selected = next(
            (
                item
                for item in repositories
                if str(item.get("full_name", "")).lower() == preferred_full_name
            ),
            None,
        )
    if selected is None:
        selected = repositories[0]

    full_name = str(selected.get("full_name") or "")
    if "/" not in full_name:
        return owner, repo
    resolved_owner, resolved_repo = full_name.split("/", 1)
    return owner or resolved_owner, repo or resolved_repo
