from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from dotenv import load_dotenv
from github_ai_agent import session_store
from github_ai_agent import conversation_store

from github_ai_agent import code_review
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent import readme_review
from github_ai_agent.webapp.assets import APP_HTML, ASSET_TYPES, ONBOARDING_HTML, WEB_ASSET_DIR
from github_ai_agent.webapp.auth import (
    base_url as _base_url,
    exchange_github_code as _exchange_github_code,
    exchange_google_code as _exchange_google_code,
    exchange_notion_code as _exchange_notion_code,
    github_get as _github_get,
    google_calendar_url as _google_calendar_url,
    google_get_userinfo as _google_get_userinfo,
    notion_base_url as _notion_base_url,
)
from github_ai_agent.webapp.github_data import (
    load_config_members as _load_config_members,
    load_repositories as _load_repositories,
    select_default_repository as _select_default_repository,
)
from github_ai_agent.webapp.integrations import (
    calendar_enabled_for_session as _calendar_enabled_for_session,
    friendly_error as _friendly_error,
    load_notion_databases as _load_notion_databases,
    load_notion_pages as _load_notion_pages,
)
from github_ai_agent.webapp.task_planning import (
    analyze_tasks,
    create_calendar_events,
    create_notion_report,
    create_notion_tasks,
)

SESSIONS: dict[str, dict[str, Any]] = {}
OAUTH_STATES: dict[str, str] = {}

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
        if parsed_url.path == "/logout":
            self._handle_logout()
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
            # Conversation memory needs a stable session id across turns. The
            # cookie is normally set during OAuth; if this request arrived
            # without one, mint an id now and persist it on the response so the
            # next turn reuses it.
            had_cookie = bool(self._cookie("github_ai_agent_session"))
            session_id = self._session_id()
            set_cookie = (
                None
                if had_cookie
                else f"github_ai_agent_session={session_id}; Path=/; HttpOnly; SameSite=Lax"
            )
            history = conversation_store.load_recent(session_id)
            result = asyncio.run(
                analyze_tasks(
                    question,
                    project_deadline=project_deadline,
                    owner=owner,
                    repo=repo,
                    installation_id=installation_id,
                    history=history,
                )
            )
            conversation_store.append(session_id, "user", question)
            conversation_store.append(session_id, "assistant", str(result.get("answer") or ""))
            conversation_store.save_analysis(session_id, result.get("proposed_tasks"))
            self._send_json(result, set_cookie=set_cookie)
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
        
    def _handle_logout(self) -> None:
        session_id = self._cookie("github_ai_agent_session")
        if session_id:
            SESSIONS.pop(session_id, None)
            for state, owner_session_id in list(OAUTH_STATES.items()):
                if owner_session_id == session_id:
                    OAUTH_STATES.pop(state, None)
            try:
                session_store.clear(session_id)
            except Exception as error:
                print(f"Session store logout cleanup failed: {error}")
            try:
                conversation_store.clear(session_id)
            except Exception as error:
                print(f"Conversation store logout cleanup failed: {error}")

        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            "github_ai_agent_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
        )
        self.send_header(
            "Set-Cookie",
            "google_oauth_state=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
        )
        self.send_header(
            "Set-Cookie",
            "notion_oauth_state=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
        )
        self.end_headers()

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

    def _send_json(
        self,
        body: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        *,
        set_cookie: str | None = None,
    ) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(encoded)


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
