from __future__ import annotations

import argparse
import base64
import asyncio
import json
import os
import secrets
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
import urllib.request

from dotenv import load_dotenv

from github_ai_agent import code_review
from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_app_auth import GitHubAppTokenProvider, resolve_default_repository
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent import readme_review

SESSIONS: dict[str, dict[str, Any]] = {}
OAUTH_STATES: dict[str, str] = {}

WEB_ASSET_DIR = Path(__file__).with_name("web_assets")


def _read_web_asset(name: str) -> str:
    return (WEB_ASSET_DIR / name).read_text(encoding="utf-8")


ONBOARDING_HTML = _read_web_asset("onboarding.html")
APP_HTML = _read_web_asset("app.html")
ASSET_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "GitHubAIAgentUI/0.9"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/" or self.path.startswith("/?"):
            self._send_html(ONBOARDING_HTML)
            return
        if parsed_url.path == "/app":
            self._send_html(APP_HTML)
            return
        if parsed_url.path.startswith("/assets/"):
            self._send_asset(parsed_url.path.removeprefix("/assets/"))
            return
        if parsed_url.path == "/auth/github":
            self._redirect_to_github_login()
            return
        if parsed_url.path == "/auth/github/callback":
            self._handle_github_callback(parsed_url.query)
            return
        if parsed_url.path == "/auth/github/install":
            self._redirect_to_github_install()
            return
        if parsed_url.path == "/auth/github/setup":
            self._handle_github_setup(parsed_url.query)
            return
        if parsed_url.path == "/auth/google":
            self._redirect_to_google_login()
            return
        if parsed_url.path == "/auth/google/callback":
            self._handle_google_callback(parsed_url.query)
            return
        if parsed_url.path == "/auth/notion":
            self._redirect_to_notion_login()
            return
        if parsed_url.path == "/auth/notion/callback":
            self._handle_notion_callback(parsed_url.query)
            return
        if parsed_url.path == "/api/config":
            session = self._session()
            notion_databases = _load_notion_databases(session)
            notion_pages = _load_notion_pages(session)
            if session.get("notion_access_token") and not session.get("notion_database_id") and notion_databases:
                session["notion_database_id"] = notion_databases[0]["id"]
            if session.get("notion_access_token") and not session.get("notion_page_id") and notion_pages:
                session["notion_page_id"] = notion_pages[0]["id"]
            notion = NotionToolClient(
                token=str(session.get("notion_access_token") or "") or None,
                database_id=str(session.get("notion_database_id") or "") or None,
            )
            calendar = GoogleCalendarToolClient()
            repositories = _load_repositories(session)
            owner, repo, installation_id = _select_default_repository(repositories)
            self._send_json(
                {
                    "owner": owner,
                    "repo": repo,
                    "installation_id": installation_id,
                    "repositories": repositories,
                    "github_user": session.get("github_login", ""),
                    "google_user": session.get("google_email", ""),
                    "notion_workspace": session.get("notion_workspace_name", ""),
                    "notion_database_id": session.get("notion_database_id", notion.config.database_id),
                    "notion_databases": notion_databases,
                    "notion_page_id": session.get("notion_page_id", ""),
                    "notion_pages": notion_pages,
                    "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    "backend": "github-mcp",
                    "notion_enabled": notion.enabled or bool(session.get("notion_access_token")),
                    "calendar_enabled": _calendar_enabled_for_session(calendar, session),
                    "calendar_timezone": calendar.config.timezone,
                    "assignee_property": notion.config.assignee_property,
                    **_load_config_members(owner, repo, installation_id),
                }
            )
            return
        if parsed_url.path == "/api/members":
            query = parse_qs(parsed_url.query)
            owner = (query.get("owner") or [""])[0].strip()
            repo = (query.get("repo") or [""])[0].strip()
            installation_id = (query.get("installation_id") or [""])[0].strip()
            if not owner or not repo:
                repositories = _load_repositories(self._session())
                owner, repo, installation_id = _select_default_repository(repositories)
            self._send_json(_load_config_members(owner, repo, installation_id))
            return
        if parsed_url.path == "/api/calendar-events":
            self._handle_calendar_events()
            return
        if parsed_url.path == "/api/branches":
            self._handle_list_branches(parsed_url.query)
            return
        if parsed_url.path == "/api/repo-tree":
            self._handle_repo_tree(parsed_url.query)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/analyze-tasks":
            self._handle_analyze_tasks()
            return
        if self.path == "/api/approve-tasks":
            self._handle_approve_tasks()
            return
        if self.path == "/api/select-notion-database":
            self._handle_select_notion_database()
            return
        if self.path == "/api/create-notion-database":
            self._handle_create_notion_database()
            return
        if self.path == "/api/save-review-to-notion":
            self._handle_save_review_to_notion()
            return
        if self.path == "/api/approve-calendar-events":
            self._handle_approve_calendar_events()
            return
        if self.path == "/api/review-file":
            self._handle_review_file()
            return
        if self.path == "/api/analyze-readme":
            self._handle_analyze_readme()
            return
        if self.path == "/api/apply-readme-update":
            self._handle_apply_readme_update()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_analyze_tasks(self) -> None:
        try:
            payload = self._read_json()
            question = str(payload.get("question", "")).strip()
            project_deadline = str(payload.get("project_deadline", "")).strip()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            if not question:
                self._send_json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
                return
            result = asyncio.run(
                analyze_tasks(
                    question,
                    project_deadline=project_deadline,
                    owner=owner,
                    repo=repo,
                    installation_id=installation_id,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_calendar_events(self) -> None:
        try:
            session = self._session()
            google_access_token = str(session.get("google_access_token") or "")
            google_email = str(session.get("google_email") or "")
            if not google_access_token:
                self._send_json(
                    {"error": "Google Calendar 연결 후 다시 시도해 주세요."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            calendar = GoogleCalendarToolClient(mcp_auth_token=google_access_token or None)
            self._send_json(
                {
                    "calendar_url": _google_calendar_url(google_email),
                    "events": calendar.list_upcoming_events(),
                }
            )
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_approve_tasks(self) -> None:
        try:
            payload = self._read_json()
            tasks = payload.get("tasks", [])
            save_mode = str(payload.get("save_mode") or "database").strip()
            page_id = str(payload.get("page_id") or "").strip()
            answer_text = str(payload.get("answer") or "").strip()
            if not isinstance(tasks, list):
                tasks = []
            if save_mode not in {"database", "page", "checklist"}:
                save_mode = "database"
            if save_mode == "database" and not tasks:
                self._send_json({"error": "tasks are required for database save"}, HTTPStatus.BAD_REQUEST)
                return
            session = self._session()
            notion_token = str(session.get("notion_access_token") or "")
            notion_database_id = str(session.get("notion_database_id") or "")
            if not notion_token and not os.environ.get("NOTION_API_KEY") and not os.environ.get("NOTION_TOKEN"):
                self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            if save_mode in {"page", "checklist"}:
                if not notion_token:
                    self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                    return
                if not page_id:
                    pages = _load_notion_pages(session)
                    if pages:
                        page_id = pages[0]["id"]
                        session["notion_page_id"] = page_id
                if not page_id:
                    self._send_json({"error": "Notion에 기록할 위치를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                    return
                result = asyncio.run(
                    create_notion_report(
                        tasks,
                        body=answer_text,
                        title="AI Agent 작업 분석 기록",
                        checklist=save_mode == "checklist",
                        notion_token=notion_token,
                        notion_page_id=page_id,
                    )
                )
                result["save_mode"] = save_mode
                self._send_json(result)
                return
            if notion_token and not notion_database_id:
                databases = _load_notion_databases(session)
                if databases:
                    notion_database_id = databases[0]["id"]
                    session["notion_database_id"] = notion_database_id
                else:
                    notion = NotionToolClient(token=notion_token, database_id="placeholder")
                    pages = notion.list_pages()
                    if not pages:
                        self._send_json({"error": "Notion 데이터베이스를 만들 페이지를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                        return
                    created_database = notion.create_task_database(parent_page_id=pages[0]["id"], title="AI Agent Tasks")
                    notion_database_id = created_database["id"]
                    session["notion_database_id"] = notion_database_id
            result = asyncio.run(create_notion_tasks(tasks, notion_token=notion_token, notion_database_id=notion_database_id))
            result["save_mode"] = save_mode
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_select_notion_database(self) -> None:
        try:
            payload = self._read_json()
            database_id = str(payload.get("database_id") or "").strip()
            if not database_id:
                self._send_json({"error": "database_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            self._session()["notion_database_id"] = database_id
            self._send_json({"selected": True, "database_id": database_id})
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_create_notion_database(self) -> None:
        try:
            session = self._session()
            token = str(session.get("notion_access_token") or "")
            if not token:
                self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            payload = self._read_json()
            title = str(payload.get("title") or "AI Agent Tasks").strip()
            notion = NotionToolClient(token=token, database_id="placeholder")
            pages = notion.list_pages()
            if not pages:
                self._send_json({"error": "Notion 데이터베이스를 만들 페이지를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            database = notion.create_task_database(parent_page_id=pages[0]["id"], title=title)
            database_id = database.get("id", "")
            if not database_id:
                raise ValueError("Notion database creation did not return an id.")
            session["notion_database_id"] = database_id
            databases = _load_notion_databases(session)
            self._send_json({"created": True, "database_id": database_id, "database": database, "databases": databases})
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_save_review_to_notion(self) -> None:
        try:
            payload = self._read_json()
            review = payload.get("review")
            if not isinstance(review, dict):
                self._send_json({"error": "review is required"}, HTTPStatus.BAD_REQUEST)
                return
            session = self._session()
            notion_token = str(session.get("notion_access_token") or "")
            if not notion_token:
                self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            page_id = str(payload.get("page_id") or session.get("notion_page_id") or "").strip()
            if not page_id:
                pages = _load_notion_pages(session)
                if pages:
                    page_id = pages[0]["id"]
                    session["notion_page_id"] = page_id
            if not page_id:
                self._send_json({"error": "Notion에 기록할 페이지를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            save_mode = str(payload.get("save_mode") or "page").strip()
            result = asyncio.run(create_notion_report([], title="AI Agent 코드 리뷰 기록", review=review, checklist=save_mode == "checklist", notion_token=notion_token, notion_page_id=page_id))
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_list_branches(self, query_string: str) -> None:
        try:
            query = parse_qs(query_string)
            owner = (query.get("owner") or [""])[0].strip()
            repo = (query.get("repo") or [""])[0].strip()
            installation_id = (query.get("installation_id") or [""])[0].strip()
            if not owner or not repo:
                repositories = _load_repositories(self._session())
                owner, repo, installation_id = _select_default_repository(repositories)
            session_token = str(self._session().get("github_access_token") or "")
            branches = asyncio.run(
                code_review.list_branches(
                    owner,
                    repo,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json({"branches": branches})
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_repo_tree(self, query_string: str) -> None:
        try:
            query = parse_qs(query_string)
            owner = (query.get("owner") or [""])[0].strip()
            repo = (query.get("repo") or [""])[0].strip()
            branch = (query.get("branch") or [""])[0].strip()
            installation_id = (query.get("installation_id") or [""])[0].strip()
            if not owner or not repo:
                repositories = _load_repositories(self._session())
                owner, repo, installation_id = _select_default_repository(repositories)
            if not branch:
                self._send_json({"error": "branch is required"}, HTTPStatus.BAD_REQUEST)
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                code_review.list_repo_tree(
                    owner,
                    repo,
                    branch,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_review_file(self) -> None:
        try:
            payload = self._read_json()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            branch = str(payload.get("branch", "")).strip()
            path = str(payload.get("path", "")).strip()
            if not owner or not repo or not branch or not path:
                self._send_json(
                    {"error": "owner, repo, branch, path are required"}, HTTPStatus.BAD_REQUEST
                )
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                code_review.review_file(
                    owner,
                    repo,
                    branch,
                    path,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_analyze_readme(self) -> None:
        try:
            payload = self._read_json()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            branch = str(payload.get("branch", "")).strip()
            if not owner or not repo or not branch:
                self._send_json(
                    {"error": "owner, repo, branch are required"}, HTTPStatus.BAD_REQUEST
                )
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                readme_review.analyze_readme_update(
                    owner,
                    repo,
                    branch,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_apply_readme_update(self) -> None:
        try:
            payload = self._read_json()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            base_branch = str(payload.get("base_branch", "")).strip()
            readme_content = str(payload.get("readme_content", ""))
            summary = str(payload.get("summary", ""))
            if not owner or not repo or not base_branch or not readme_content:
                self._send_json(
                    {"error": "owner, repo, base_branch, readme_content are required"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                readme_review.apply_readme_update(
                    owner,
                    repo,
                    base_branch,
                    readme_content,
                    summary,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_approve_calendar_events(self) -> None:
        try:
            payload = self._read_json()
            tasks = payload.get("tasks", [])
            if not isinstance(tasks, list) or not tasks:
                self._send_json({"error": "tasks are required"}, HTTPStatus.BAD_REQUEST)
                return
            google_access_token = str(self._session().get("google_access_token") or "")
            if not google_access_token:
                self._send_json(
                    {"error": "Google Calendar 연결 후 다시 등록해 주세요."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            result = asyncio.run(
                create_calendar_events(
                    tasks,
                    google_access_token=google_access_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _redirect_to_github_login(self) -> None:
        client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
        if not client_id:
            self._send_json(
                {"error": "GITHUB_APP_CLIENT_ID is required for GitHub login."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        session_id = self._session_id()
        state = secrets.token_urlsafe(24)
        OAUTH_STATES[state] = session_id
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": _base_url() + "/auth/github/callback",
                "state": state,
                "scope": "read:user",
            }
        )
        self._redirect(f"https://github.com/login/oauth/authorize?{params}", session_id)

    def _handle_github_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not code or not session_id:
            self._send_json({"error": "Invalid GitHub OAuth callback."}, HTTPStatus.BAD_REQUEST)
            return

        token = _exchange_github_code(code)
        user = _github_get("/user", token)
        session = SESSIONS.setdefault(session_id, {})
        session["github_access_token"] = token
        session["github_login"] = str(user.get("login") or "")
        self._redirect("/", session_id)

    def _redirect_to_github_install(self) -> None:
        slug = os.environ.get("GITHUB_APP_SLUG", "").strip()
        if not slug:
            self._send_json(
                {"error": "GITHUB_APP_SLUG is required for GitHub App installation."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        session_id = self._session_id()
        self._redirect(f"https://github.com/apps/{slug}/installations/new", session_id)

    def _handle_github_setup(self, query_string: str) -> None:
        query = parse_qs(query_string)
        installation_id = (query.get("installation_id") or [""])[0].strip()
        session_id = self._session_id()
        if installation_id:
            SESSIONS.setdefault(session_id, {})["installation_id"] = installation_id
        self._redirect("/", session_id)

    def _redirect_to_google_login(self) -> None:
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            self._send_json(
                {"error": "GOOGLE_OAUTH_CLIENT_ID is required for Google Calendar login."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        session_id = self._session_id()
        state = secrets.token_urlsafe(24)
        OAUTH_STATES[state] = session_id
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": _base_url() + "/auth/google/callback",
                "response_type": "code",
                "state": state,
                "scope": os.environ.get(
                    "GOOGLE_OAUTH_SCOPES",
                    "https://www.googleapis.com/auth/calendar "
                    "https://www.googleapis.com/auth/userinfo.email",
                ),
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        self._redirect(
            f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
            session_id,
            extra_cookies={"google_oauth_state": state},
        )

    def _handle_google_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not session_id and state and self._cookie("google_oauth_state") == state:
            session_id = self._session_id()
        if not code or not session_id:
            self._send_json({"error": "Invalid Google OAuth callback."}, HTTPStatus.BAD_REQUEST)
            return

        token_payload = _exchange_google_code(code)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            self._send_json({"error": "Google OAuth did not return access_token."}, HTTPStatus.BAD_REQUEST)
            return
        user = _google_get_userinfo(access_token)
        session = SESSIONS.setdefault(session_id, {})
        session["google_access_token"] = access_token
        if token_payload.get("refresh_token"):
            session["google_refresh_token"] = str(token_payload.get("refresh_token"))
        session["google_email"] = str(user.get("email") or "")
        self._redirect("/", session_id)

    def _redirect_to_notion_login(self) -> None:
        client_id = os.environ.get("NOTION_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            self._send_json({"error": "NOTION_OAUTH_CLIENT_ID is required for Notion login."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        session_id = self._session_id()
        state = secrets.token_urlsafe(24)
        OAUTH_STATES[state] = session_id
        params = urlencode(
            {
                "owner": "user",
                "client_id": client_id,
                "redirect_uri": _notion_base_url() + "/auth/notion/callback",
                "response_type": "code",
                "state": state,
            }
        )
        auth_url = os.environ.get("NOTION_AUTH_URL", "https://api.notion.com/v1/oauth/authorize").strip()
        self._redirect(f"{auth_url}?{params}", session_id, extra_cookies={"notion_oauth_state": state})

    def _handle_notion_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        error = (query.get("error") or [""])[0]
        if error:
            self._send_json({"error": f"Notion authorization failed: {error}"}, HTTPStatus.BAD_REQUEST)
            return
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not session_id and state and self._cookie("notion_oauth_state") == state:
            session_id = self._session_id()
        if not code or not session_id:
            self._send_json({"error": "Invalid Notion OAuth callback."}, HTTPStatus.BAD_REQUEST)
            return
        token_payload = _exchange_notion_code(code)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            self._send_json({"error": "Notion OAuth did not return access_token."}, HTTPStatus.BAD_REQUEST)
            return
        session = SESSIONS.setdefault(session_id, {})
        session["notion_access_token"] = access_token
        if token_payload.get("refresh_token"):
            session["notion_refresh_token"] = str(token_payload.get("refresh_token"))
        session["notion_workspace_id"] = str(token_payload.get("workspace_id") or "")
        session["notion_workspace_name"] = str(token_payload.get("workspace_name") or "Notion")
        databases = _load_notion_databases(session)
        pages = _load_notion_pages(session)
        if databases:
            session["notion_database_id"] = databases[0]["id"]
        if pages:
            session["notion_page_id"] = pages[0]["id"]
        self._redirect("/", session_id)

    def _session_id(self) -> str:
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "github_ai_agent_session" and value:
                SESSIONS.setdefault(value, {})
                return value
        session_id = secrets.token_urlsafe(24)
        SESSIONS.setdefault(session_id, {})
        return session_id

    def _session(self) -> dict[str, Any]:
        return SESSIONS.setdefault(self._session_id(), {})

    def _cookie(self, cookie_name: str) -> str:
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == cookie_name:
                return value
        return ""

    def _redirect(
        self,
        location: str,
        session_id: str | None = None,
        extra_cookies: dict[str, str] | None = None,
    ) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        if session_id:
            self.send_header(
                "Set-Cookie",
                f"github_ai_agent_session={session_id}; Path=/; HttpOnly; SameSite=Lax",
            )
        for name, value in (extra_cookies or {}).items():
            self.send_header(
                "Set-Cookie",
                f"{name}={value}; Path=/; HttpOnly; SameSite=Lax",
            )
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}

    def _send_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_asset(self, name: str) -> None:
        if "/" in name or "\\" in name or name.startswith("."):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = WEB_ASSET_DIR / name
        content_type = ASSET_TYPES.get(path.suffix)
        if not content_type or not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        encoded = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, body: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


async def analyze_tasks(
    question: str,
    *,
    project_deadline: str = "",
    owner: str = "",
    repo: str = "",
    installation_id: str = "",
) -> dict[str, Any]:
    agent = GitHubToolChoosingAgent(owner=owner or None, repo=repo or None)
    async with GitHubMcpClient(installation_id=installation_id or None) as github_tools:
        result = await agent.run(
            _build_analysis_prompt(question, project_deadline),
            github_tools,
        )

    parsed = _parse_task_json(result.answer)
    return {
        "answer": parsed.get("answer") or result.answer,
        "proposed_tasks": _normalize_tasks(
            parsed.get("proposed_tasks", []),
            project_deadline=project_deadline,
        ),
        "selected_tools": [
            {"tool": "github_backend", "arguments": {"backend": "mcp"}},
            *result.selected_tools,
        ],
    }


async def create_notion_tasks(
    tasks: list[Any],
    *,
    notion_token: str = "",
    notion_database_id: str = "",
) -> dict[str, Any]:
    notion = NotionToolClient(token=notion_token or None, database_id=notion_database_id or None)
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with notion:
        for task in _normalize_tasks(tasks):
            selected_tools.append({"tool": "create_notion_task", "arguments": task})
            raw = await notion.call_tool("create_notion_task", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}


async def create_notion_report(
    tasks: list[Any],
    *,
    title: str,
    body: str = "",
    review: dict[str, Any] | None = None,
    checklist: bool = False,
    notion_token: str = "",
    notion_page_id: str = "",
) -> dict[str, Any]:
    notion = NotionToolClient(token=notion_token or None, database_id="placeholder")
    normalized_tasks = _normalize_tasks(tasks)
    selected_tools = [
        {
            "tool": "create_notion_report_page",
            "arguments": {
                "title": title,
                "parent_page_id": notion_page_id,
                "task_count": len(normalized_tasks),
                "format": "checklist" if checklist else "document",
            },
        }
    ]
    async with notion:
        page = notion.create_report_page(
            parent_page_id=notion_page_id,
            title=title,
            body=body,
            tasks=normalized_tasks,
            review=review or {},
            checklist=checklist,
        )
    return {"created": [page], "selected_tools": selected_tools, "url": page.get("url", "")}


async def create_calendar_events(
    tasks: list[Any],
    *,
    google_access_token: str = "",
) -> dict[str, Any]:
    calendar = GoogleCalendarToolClient(mcp_auth_token=google_access_token or None)
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with calendar:
        for task in _normalize_tasks(tasks):
            selected_tools.append({"tool": "create_calendar_event", "arguments": task})
            raw = await calendar.call_tool("create_calendar_event", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                if "error" in raw.lower() or "forbidden" in raw.lower():
                    raise ValueError(raw)
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}


def _build_analysis_prompt(
    question: str,
    project_deadline: str,
) -> str:
    today = date.today().isoformat()
    deadline_rule = (
        f"사용자가 입력한 프로젝트 전체 마감일은 {project_deadline}입니다. "
        "모든 proposed_tasks의 due는 오늘 이후이면서 이 날짜 이하인 YYYY-MM-DD로 반드시 채우세요. "
        "우선순위가 높은 작업은 더 이른 날짜에 배치하고, 작업들이 같은 날에 과도하게 몰리지 않게 분산하세요."
        if project_deadline
        else "사용자가 프로젝트 전체 마감일을 아직 입력하지 않았습니다. 작업 배분은 하되 due는 빈 문자열로 두고, answer에서 전체 마감일 입력이 필요하다고 안내하세요."
    )
    return f"""
사용자 질문을 문장 그대로만 보지 말고 의미와 맥락으로 해석하세요.

오늘 날짜: {today}
프로젝트 전체 마감일 규칙: {deadline_rule}

사용자 질문:
{question}

GitHub에서 미리 조회한 저장소 활동 정보:
MCP backend에서는 사용 가능한 GitHub MCP tool 목록을 보고 필요한 tool을 직접 선택해서 호출하세요.

처리 규칙:
1. 팀원 목록은 GitHub contributors, collaborators, organization members 결과에서 자동으로 판단합니다.
2. collaborators나 organization members 조회가 권한 오류 또는 빈 결과를 반환하면 그 사실을 설명하고 contributors와 commits 기준으로 확인 가능한 팀원을 말합니다.
3. 사용자가 "팀원이 누구야", "누구누구 있어", "우리 팀 구성 알려줘", "참여자 알려줘"처럼 묻는 경우는 모두 팀원 조회 요청으로 처리합니다.
4. 사용자가 "할 일 배분", "분담", "나눠줘", "누가 뭘 하면 돼", "각자 맡을 일", "오늘 할 일 정해줘"처럼 묻는 경우는 모두 작업 배분 요청으로 처리합니다.
5. 작업 배분 요청이면 최근 commit message, author/login, open issues, open PRs를 근거로 팀원별 작업 성향을 추정하고 담당자를 배정합니다.
6. 특정 팀원이 특정 종류의 작업을 많이 했다면 비슷한 작업을 우선 배정하되, 한 사람에게 과도하게 몰리지 않게 균형을 고려합니다.
7. open issue나 PR이 없어도 "할 일이 없음"으로 끝내지 말고, 최근 커밋과 저장소 상태를 근거로 점검, 문서화, 테스트, 다음 기능 계획 같은 현실적인 작업 후보를 만듭니다.
8. 사용자가 팀원 목록만 물었다면 proposed_tasks는 빈 배열로 둡니다.
9. 사용자가 작업 배분이나 오늘 할 일을 물었다면 proposed_tasks에 담당자, 담당자 GitHub ID, 마감일 due를 포함한 작업 후보를 최대 5개 넣습니다.
10. Notion과 Google Calendar에는 아직 저장하지 않습니다. 저장은 사용자가 UI에서 승인 버튼을 누른 뒤에만 실행됩니다.

반드시 아래 JSON 형식만 출력하세요. JSON 바깥에는 어떤 설명도 쓰지 마세요.

{{
  "answer": "현재 상태\n1. 확인한 GitHub 근거...\n\nAgent의 판단\n1. 판단 내용...\n\n실행 계획\n1. [High / 예상 2시간] 작업명 - 근거...\n\n실행한 작업\n1. 실제로 확인한 도구와 결과...\n\n사용자 승인이 필요한 작업\n1. Notion 저장, Calendar 등록 등 승인 필요한 작업...\n\n다음 권장 행동\n1. 바로 할 일...",
  "proposed_tasks": [
    {{
      "title": "구체적인 할 일 제목",
      "status": "To do",
      "priority": "High 또는 Medium 또는 Low",
      "source": "GitHub 근거 출처",
      "due": "YYYY-MM-DD 또는 빈 문자열",
      "reason": "GitHub 근거와 이 담당자에게 배정한 이유",
      "assignee": "담당자 GitHub ID 또는 이름",
      "assignee_github": "담당자 GitHub ID"
    }}
  ]
}}

answer 작성 규칙:
1. answer는 반드시 위 예시처럼 "현재 상태", "Agent의 판단", "실행 계획", "실행한 작업", "사용자 승인이 필요한 작업", "다음 권장 행동" 섹션을 모두 포함합니다.
2. 각 섹션 제목 앞뒤에는 줄바꿈을 넣습니다.
3. 한 문단 안에 1. 2. 3.을 이어 쓰지 않습니다.
4. 각 번호 항목은 반드시 새 줄에서 시작합니다.
5. 실행 계획의 작업 항목에는 우선순위, 예상 시간, 근거를 같이 씁니다.
6. 실제로 호출하지 않은 도구나 확인하지 않은 정보는 실행한 작업에 쓰지 않습니다.
7. Notion 저장이나 Calendar 등록은 승인 전에는 실행하지 않았다고 명확히 씁니다.
"""


def _base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8787").rstrip("/")


def _notion_base_url() -> str:
    return os.environ.get("NOTION_REDIRECT_BASE_URL", _base_url()).rstrip("/")


def _google_calendar_url(email: str = "") -> str:
    base_url = "https://calendar.google.com/calendar/u/0/r"
    if not email:
        return base_url
    return f"{base_url}?authuser={quote(email)}"


def _exchange_github_code(code: str) -> str:
    client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GITHUB_APP_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("GITHUB_APP_CLIENT_ID and GITHUB_APP_CLIENT_SECRET are required.")
    data = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _base_url() + "/auth/github/callback",
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
        raise ValueError(f"GitHub OAuth token response did not include access_token: {payload.get('error_description', '')}")
    return str(token)


def _github_get(path: str, token: str) -> dict[str, Any]:
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


def _exchange_google_code(code: str) -> dict[str, Any]:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are required.")
    data = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _base_url() + "/auth/google/callback",
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


def _exchange_notion_code(code: str) -> dict[str, Any]:
    client_id = os.environ.get("NOTION_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NOTION_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("NOTION_OAUTH_CLIENT_ID and NOTION_OAUTH_CLIENT_SECRET are required.")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    data = json.dumps(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _notion_base_url() + "/auth/notion/callback",
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


def _google_get_userinfo(access_token: str) -> dict[str, Any]:
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


def _calendar_enabled_for_session(
    calendar: GoogleCalendarToolClient,
    session: dict[str, Any],
) -> bool:
    if not calendar.enabled:
        return False
    if calendar.config.backend != "mcp":
        return calendar.enabled
    return bool(session.get("google_access_token"))


def _friendly_error(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        parts = [_friendly_error(item) for item in error.exceptions]
        return "; ".join(part for part in parts if part) or str(error)
    return str(error)


def _load_notion_databases(session: dict[str, Any]) -> list[dict[str, str]]:
    token = str(session.get("notion_access_token") or "")
    if not token:
        return []
    try:
        databases = NotionToolClient(token=token, database_id="placeholder").list_databases()
    except Exception:
        return []
    selected = str(session.get("notion_database_id") or "")
    return sorted(
        databases,
        key=lambda database: (
            0 if database.get("id") == selected else 1,
            0 if any(keyword in database.get("title", "").lower() for keyword in ("task", "todo", "할일", "작업")) else 1,
            database.get("title", "").lower(),
        ),
    )


def _load_notion_pages(session: dict[str, Any]) -> list[dict[str, str]]:
    token = str(session.get("notion_access_token") or "")
    if not token:
        return []
    try:
        pages = NotionToolClient(token=token, database_id="placeholder").list_pages()
    except Exception:
        return []
    selected = str(session.get("notion_page_id") or "")
    return sorted(pages, key=lambda page: (0 if page.get("id") == selected else 1, page.get("title", "").lower()))


def _load_repositories(session: dict[str, Any] | None = None) -> list[dict[str, str]]:
    session = session or {}
    user_token = str(session.get("github_access_token") or "")
    if user_token:
        return _load_user_installation_repositories(user_token)

    provider = GitHubAppTokenProvider()
    if not provider.enabled:
        return []
    repositories = provider.list_installation_repositories()
    installation_id = provider.config.installation_id
    return _format_repositories(repositories, installation_id)


def _load_user_installation_repositories(token: str) -> list[dict[str, str]]:
    installations = _github_get("/user/installations?per_page=100", token).get("installations", [])
    result: list[dict[str, str]] = []
    if not isinstance(installations, list):
        return result
    for installation in installations:
        if not isinstance(installation, dict):
            continue
        installation_id = str(installation.get("id") or "")
        if not installation_id:
            continue
        payload = _github_get(f"/user/installations/{installation_id}/repositories?per_page=100", token)
        repositories = payload.get("repositories", [])
        if isinstance(repositories, list):
            result.extend(_format_repositories(repositories, installation_id))
    return result


def _format_repositories(
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


def _select_default_repository(repositories: list[dict[str, str]]) -> tuple[str, str, str]:
    if repositories:
        first = repositories[0]
        return first.get("owner", ""), first.get("repo", ""), first.get("installation_id", "")
    owner, repo = resolve_default_repository()
    return owner, repo, os.environ.get("GITHUB_APP_INSTALLATION_ID", "")


def _load_config_members(owner: str, repo: str, installation_id: str = "") -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        warnings: list[str] = []
        raw_payloads: list[str] = []
        async with GitHubMcpClient(installation_id=installation_id or None) as tools:
            available_tools = await tools.list_tools()
            tool_names = {tool.name for tool in available_tools}
            for tool_name, arguments in _mcp_member_tool_calls(tool_names, owner, repo):
                try:
                    raw_payloads.append(await tools.call_tool(tool_name, arguments))
                except Exception as error:
                    warnings.append(f"{tool_name} 조회 실패: {error}")
        members = _extract_members(*raw_payloads)
        if not members:
            warnings.append("MCP에서 확인된 팀원 ID 없음")
        return {"members": members, "member_warnings": warnings}

    try:
        return asyncio.run(load())
    except Exception as error:
        return {"members": [], "member_warnings": [f"GitHub MCP 연결 실패: {error}"]}


def _mcp_member_tool_calls(
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

    # Fallback for MCP servers that expose different GitHub tool names.
    for tool_name in sorted(tool_names):
        lowered = tool_name.lower()
        if any(keyword in lowered for keyword in ("contributor", "collaborator", "member")):
            calls.append((tool_name, {}))
    return calls


def _extract_warnings(raw: str, label: str) -> list[str]:
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


def _is_empty_list(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list) and len(parsed) == 0


def _extract_members(*raw_payloads: str) -> list[dict[str, str]]:
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


def _parse_task_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"answer": raw, "proposed_tasks": []}
    return parsed if isinstance(parsed, dict) else {"answer": raw, "proposed_tasks": []}


def _normalize_tasks(
    tasks: Any,
    *,
    project_deadline: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(tasks, list):
        return []
    normalized: list[dict[str, Any]] = []
    allowed_priorities = {"High", "Medium", "Low"}
    for task in tasks[:5]:
        if not isinstance(task, dict):
            continue
        title = str(task.get("title", "")).strip()
        if not title:
            continue
        priority = str(task.get("priority", "Medium")).strip()
        if priority not in allowed_priorities:
            priority = "Medium"
        due = str(task.get("due") or "").strip()
        if project_deadline and (not due or due > project_deadline):
            due = project_deadline
        normalized.append(
            {
                "title": title,
                "status": str(task.get("status") or "To do"),
                "priority": priority,
                "source": str(task.get("source") or "GitHub analysis"),
                "due": due,
                "reason": str(task.get("reason") or ""),
                "assignee": str(task.get("assignee") or ""),
                "assignee_github": str(task.get("assignee_github") or ""),
            }
        )
    return normalized


def main() -> None:
    load_dotenv(override=True, encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description="Run the GitHub AI Agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"GitHub AI Agent UI running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
