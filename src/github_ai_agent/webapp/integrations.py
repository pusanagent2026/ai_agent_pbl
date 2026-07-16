from __future__ import annotations

from typing import Any

from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.notion_client import NotionToolClient


def calendar_enabled_for_session(
    calendar: GoogleCalendarToolClient,
    session: dict[str, Any],
) -> bool:
    if not calendar.enabled:
        return False
    if calendar.config.backend != "mcp":
        return calendar.enabled
    return bool(session.get("google_access_token"))


def friendly_error(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        parts = [friendly_error(item) for item in error.exceptions]
        return "; ".join(part for part in parts if part) or str(error)
    return str(error)


def load_notion_databases(session: dict[str, Any]) -> list[dict[str, str]]:
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


def load_notion_pages(session: dict[str, Any]) -> list[dict[str, str]]:
    token = str(session.get("notion_access_token") or "")
    if not token:
        return []
    try:
        pages = NotionToolClient(token=token, database_id="placeholder").list_pages()
    except Exception:
        return []
    selected = str(session.get("notion_page_id") or "")
    return sorted(pages, key=lambda page: (0 if page.get("id") == selected else 1, page.get("title", "").lower()))
