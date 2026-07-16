from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.parse import quote, urlencode
import urllib.request


def base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8787").rstrip("/")


def notion_base_url() -> str:
    return os.environ.get("NOTION_REDIRECT_BASE_URL", base_url()).rstrip("/")


def google_calendar_url(email: str = "") -> str:
    url = "https://calendar.google.com/calendar/u/0/r"
    if not email:
        return url
    return f"{url}?authuser={quote(email)}"


def exchange_github_code(code: str) -> str:
    client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GITHUB_APP_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("GITHUB_APP_CLIENT_ID and GITHUB_APP_CLIENT_SECRET are required.")
    data = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": base_url() + "/auth/github/callback",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://github.com/login/oauth/access_token",
        data=data,
        method="POST",
        headers={"Accept": "application/json", "User-Agent": "github-ai-mcp-agent"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not token:
        detail = payload.get("error_description", "")
        raise ValueError(f"GitHub OAuth token response did not include access_token: {detail}")
    return str(token)


def github_get(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.github.com" + path,
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
    return payload if isinstance(payload, dict) else {}


def exchange_google_code(code: str) -> dict[str, Any]:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are required.")
    data = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": base_url() + "/auth/google/callback",
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        method="POST",
        headers={"Accept": "application/json", "User-Agent": "github-ai-mcp-agent"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def exchange_notion_code(code: str) -> dict[str, Any]:
    client_id = os.environ.get("NOTION_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NOTION_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("NOTION_OAUTH_CLIENT_ID and NOTION_OAUTH_CLIENT_SECRET are required.")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    data = json.dumps(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": notion_base_url() + "/auth/notion/callback",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.notion.com/v1/oauth/token",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
            "User-Agent": "github-ai-mcp-agent",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def google_get_userinfo(access_token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "github-ai-mcp-agent",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}
