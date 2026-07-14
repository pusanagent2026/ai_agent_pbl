from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from github_ai_agent.mcp_client import McpTool


@dataclass(frozen=True)
class NotionConfig:
    token: str
    database_id: str
    title_property: str
    status_property: str
    priority_property: str
    source_property: str
    due_property: str
    reason_property: str
    assignee_property: str


class NotionToolClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        database_id: str | None = None,
    ) -> None:
        self.config = NotionConfig(
            token=token
            or os.environ.get("NOTION_API_KEY", "")
            or os.environ.get("NOTION_TOKEN", ""),
            database_id=database_id or os.environ.get("NOTION_DATABASE_ID", ""),
            title_property=os.environ.get("NOTION_TITLE_PROPERTY", "Name"),
            status_property=os.environ.get("NOTION_STATUS_PROPERTY", "Status"),
            priority_property=os.environ.get("NOTION_PRIORITY_PROPERTY", "Priority"),
            source_property=os.environ.get("NOTION_SOURCE_PROPERTY", "Source"),
            due_property=os.environ.get("NOTION_DUE_PROPERTY", "Due"),
            reason_property=os.environ.get("NOTION_REASON_PROPERTY", "Reason"),
            assignee_property=os.environ.get("NOTION_ASSIGNEE_PROPERTY", ""),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.config.token and self.config.database_id)

    async def __aenter__(self) -> "NotionToolClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def list_tools(self) -> list[McpTool]:
        if not self.enabled:
            return []

        return [
            McpTool(
                name="create_notion_task",
                description=(
                    "Create a task in the connected Notion task database. "
                    "Use only when the user asks to save, record, add, or auto-save tasks."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short action-oriented task title.",
                        },
                        "status": {
                            "type": "string",
                            "description": "Task status.",
                            "default": "To do",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["High", "Medium", "Low"],
                            "default": "Medium",
                        },
                        "source": {
                            "type": "string",
                            "description": "Where this task came from, such as GitHub commits or PRs.",
                        },
                        "due": {
                            "type": "string",
                            "description": "Optional due date in YYYY-MM-DD format.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief evidence-based reason for creating the task.",
                        },
                        "assignee": {
                            "type": "string",
                            "description": "Assigned team member name.",
                        },
                        "assignee_github": {
                            "type": "string",
                            "description": "Assigned team member GitHub username.",
                        },
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "create_notion_task":
            raise ValueError(f"Unknown Notion tool: {name}")
        if not self.enabled:
            raise ValueError("NOTION_API_KEY and NOTION_DATABASE_ID are required.")

        payload = self._build_create_page_payload(arguments)
        response = self._post_json("/v1/pages", payload)
        return json.dumps(
            {
                "created": True,
                "title": arguments.get("title"),
                "notion_page_id": response.get("id"),
                "url": response.get("url"),
            },
            ensure_ascii=False,
            indent=2,
        )

    def _build_create_page_payload(self, arguments: dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {
            self.config.title_property: {
                "title": [
                    {
                        "text": {
                            "content": str(arguments.get("title", "Untitled task"))
                        }
                    }
                ]
            }
        }

        self._set_select(properties, self.config.status_property, arguments.get("status"))
        self._set_select(
            properties,
            self.config.priority_property,
            arguments.get("priority"),
        )
        self._set_rich_text(properties, self.config.source_property, arguments.get("source"))
        self._set_rich_text(properties, self.config.reason_property, arguments.get("reason"))
        self._set_date(properties, self.config.due_property, arguments.get("due"))
        if self.config.assignee_property:
            assignee = str(arguments.get("assignee") or "")
            github_id = str(arguments.get("assignee_github") or "")
            label = f"{assignee} ({github_id})" if github_id else assignee
            self._set_rich_text(properties, self.config.assignee_property, label)

        return {
            "parent": {"database_id": self.config.database_id},
            "properties": properties,
        }

    def _set_select(
        self,
        properties: dict[str, Any],
        name: str,
        value: Any,
    ) -> None:
        if value:
            properties[name] = {"select": {"name": str(value)}}

    def _set_rich_text(
        self,
        properties: dict[str, Any],
        name: str,
        value: Any,
    ) -> None:
        if value:
            properties[name] = {"rich_text": [{"text": {"content": str(value)}}]}

    def _set_date(
        self,
        properties: dict[str, Any],
        name: str,
        value: Any,
    ) -> None:
        if value:
            properties[name] = {"date": {"start": str(value)}}

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            "https://api.notion.com" + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ValueError(f"Notion API error {error.code}: {body}") from error

        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {}
