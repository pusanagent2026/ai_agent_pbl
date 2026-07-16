from __future__ import annotations

import json
import os
import urllib.error
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
            raise ValueError("Notion login and a task database are required.")

        payload = self._build_flexible_create_page_payload(arguments)
        response = self._request_json("/v1/pages", payload)
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

    def _build_flexible_create_page_payload(self, arguments: dict[str, Any]) -> dict[str, Any]:
        schema = self.retrieve_database(self.config.database_id)
        properties_schema = schema.get("properties")
        if not isinstance(properties_schema, dict):
            return self._build_create_page_payload(arguments)

        properties: dict[str, Any] = {}
        title_property = self._find_property(properties_schema, ("title", "name", "이름"), "title")
        if not title_property:
            raise ValueError("Selected Notion database does not have a title property.")
        properties[title_property] = {
            "title": [{"text": {"content": str(arguments.get("title") or "Untitled task")}}]
        }

        mapping = {
            "status": (self.config.status_property, "status", "state", "상태"),
            "priority": (self.config.priority_property, "priority", "우선순위", "중요도"),
            "source": (self.config.source_property, "source", "출처", "근거"),
            "due": (self.config.due_property, "due", "deadline", "마감일", "날짜"),
            "reason": (self.config.reason_property, "reason", "이유", "근거", "메모"),
            "assignee": (self.config.assignee_property, "assignee", "owner", "담당자"),
        }
        for field, aliases in mapping.items():
            value: Any = arguments.get(field)
            if field == "assignee":
                assignee = str(arguments.get("assignee") or "")
                github_id = str(arguments.get("assignee_github") or "")
                value = f"{assignee} ({github_id})" if github_id and assignee else assignee or github_id
            if not value:
                continue
            property_name = self._find_property(properties_schema, aliases)
            if not property_name:
                continue
            notion_value = self._property_value_for_schema(
                properties_schema[property_name],
                value,
            )
            if notion_value:
                properties[property_name] = notion_value

        children = self._task_detail_blocks(arguments)
        payload: dict[str, Any] = {
            "parent": {"database_id": self.config.database_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children
        return payload

    def retrieve_database(self, database_id: str | None = None) -> dict[str, Any]:
        database_id = database_id or self.config.database_id
        if not self.config.token or not database_id:
            return {}
        return self._request_json(f"/v1/databases/{database_id}", None, method="GET")

    def create_report_page(
        self,
        *,
        parent_page_id: str,
        title: str,
        body: str = "",
        tasks: list[dict[str, Any]] | None = None,
        review: dict[str, Any] | None = None,
        checklist: bool = False,
    ) -> dict[str, str]:
        if not self.config.token:
            raise ValueError("Notion login is required.")
        if not parent_page_id:
            raise ValueError("A parent Notion page is required.")
        children = self._report_blocks(body=body, tasks=tasks or [], review=review or {}, checklist=checklist)
        response = self._request_json(
            "/v1/pages",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "properties": {
                    "title": [{"text": {"content": title or "AI Agent 기록"}}],
                },
                "children": children[:90],
            },
        )
        return {
            "id": str(response.get("id") or ""),
            "title": title,
            "url": str(response.get("url") or ""),
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

    def list_databases(self) -> list[dict[str, str]]:
        if not self.config.token:
            return []
        response = self._request_json(
            "/v1/search",
            {
                "filter": {"value": "database", "property": "object"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 50,
            },
        )
        databases: list[dict[str, str]] = []
        for item in response.get("results", []):
            if not isinstance(item, dict) or item.get("object") != "database":
                continue
            database_id = str(item.get("id") or "")
            title = self._plain_title(item.get("title"))
            if database_id:
                databases.append(
                    {
                        "id": database_id,
                        "title": title or "Untitled database",
                        "url": str(item.get("url") or ""),
                    }
                )
        return databases

    def list_pages(self) -> list[dict[str, str]]:
        if not self.config.token:
            return []
        response = self._request_json(
            "/v1/search",
            {
                "filter": {"value": "page", "property": "object"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 50,
            },
        )
        pages: list[dict[str, str]] = []
        for item in response.get("results", []):
            if not isinstance(item, dict) or item.get("object") != "page":
                continue
            page_id = str(item.get("id") or "")
            title = self._page_title(item)
            if page_id:
                pages.append(
                    {
                        "id": page_id,
                        "title": title or "Untitled page",
                        "url": str(item.get("url") or ""),
                    }
                )
        return pages

    def create_task_database(
        self,
        *,
        parent_page_id: str,
        title: str = "AI Agent Tasks",
    ) -> dict[str, str]:
        if not self.config.token:
            raise ValueError("Notion login is required.")
        if not parent_page_id:
            raise ValueError("A parent Notion page is required to create a database.")

        properties: dict[str, Any] = {
            self.config.title_property: {"title": {}},
            self.config.status_property: {
                "select": {
                    "options": [
                        {"name": "To do", "color": "gray"},
                        {"name": "In progress", "color": "blue"},
                        {"name": "Done", "color": "green"},
                    ]
                }
            },
            self.config.priority_property: {
                "select": {
                    "options": [
                        {"name": "High", "color": "red"},
                        {"name": "Medium", "color": "yellow"},
                        {"name": "Low", "color": "green"},
                    ]
                }
            },
            self.config.source_property: {"rich_text": {}},
            self.config.due_property: {"date": {}},
            self.config.reason_property: {"rich_text": {}},
        }
        if self.config.assignee_property:
            properties[self.config.assignee_property] = {"rich_text": {}}

        response = self._request_json(
            "/v1/databases",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": properties,
            },
        )
        return {
            "id": str(response.get("id") or ""),
            "title": self._plain_title(response.get("title")) or title,
            "url": str(response.get("url") or ""),
        }

    def _request_json(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        method: str = "POST",
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.notion.com" + path,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ValueError(f"Notion API error {error.code}: {body}") from error

        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {}

    def _find_property(
        self,
        properties_schema: dict[str, Any],
        aliases: tuple[str, ...],
        property_type: str | None = None,
    ) -> str:
        normalized_aliases = {alias.strip().lower() for alias in aliases if alias}
        for name, schema in properties_schema.items():
            if property_type and isinstance(schema, dict) and schema.get("type") != property_type:
                continue
            lowered = name.strip().lower()
            if lowered in normalized_aliases:
                return name
        for name, schema in properties_schema.items():
            if property_type and isinstance(schema, dict) and schema.get("type") == property_type:
                return name
        return ""

    def _property_value_for_schema(self, schema: Any, value: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {}
        property_type = str(schema.get("type") or "")
        text = str(value)
        if property_type == "rich_text":
            return {"rich_text": [{"text": {"content": text[:1900]}}]}
        if property_type == "select":
            return {"select": {"name": text[:100]}}
        if property_type == "status":
            return {"status": {"name": text[:100]}}
        if property_type == "date":
            return {"date": {"start": text[:10]}}
        if property_type == "number":
            try:
                return {"number": float(text)}
            except ValueError:
                return {}
        if property_type == "url":
            return {"url": text}
        if property_type == "email":
            return {"email": text}
        if property_type == "phone_number":
            return {"phone_number": text}
        if property_type == "checkbox":
            return {"checkbox": text.lower() in {"true", "1", "yes", "done", "완료"}}
        return {}

    def _task_detail_blocks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        lines = []
        for label, key in (
            ("담당자", "assignee"),
            ("GitHub ID", "assignee_github"),
            ("출처", "source"),
            ("근거", "reason"),
        ):
            value = str(task.get(key) or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        return [self._paragraph_block(line) for line in lines]

    def _report_blocks(
        self,
        *,
        body: str,
        tasks: list[dict[str, Any]],
        review: dict[str, Any],
        checklist: bool,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for paragraph in self._split_paragraphs(body):
            blocks.append(self._paragraph_block(paragraph))
        if tasks:
            blocks.append(self._heading_block("작업 목록"))
            for task in tasks:
                title = str(task.get("title") or "Untitled task")
                detail = self._format_task_line(task)
                blocks.append(self._todo_block(detail or title) if checklist else self._bulleted_block(detail or title))
        if review:
            summary = str(review.get("summary") or "")
            if summary:
                blocks.append(self._heading_block("코드 리뷰 요약"))
                blocks.append(self._paragraph_block(summary))
            errors = review.get("errors") if isinstance(review.get("errors"), list) else []
            if errors:
                blocks.append(self._heading_block("발견된 문제"))
                for item in errors:
                    if isinstance(item, dict):
                        blocks.append(self._bulleted_block(self._format_review_error(item)))
            comments = review.get("comments") if isinstance(review.get("comments"), list) else []
            if comments:
                blocks.append(self._heading_block("리뷰 코멘트"))
                for item in comments:
                    if isinstance(item, dict):
                        blocks.append(self._bulleted_block(str(item.get("comment") or "")))
        return blocks or [self._paragraph_block("기록할 내용이 없습니다.")]

    def _format_task_line(self, task: dict[str, Any]) -> str:
        parts = [str(task.get("title") or "Untitled task")]
        if task.get("assignee") or task.get("assignee_github"):
            parts.append(f"담당: {task.get('assignee') or ''} {task.get('assignee_github') or ''}".strip())
        if task.get("priority"):
            parts.append(f"우선순위: {task.get('priority')}")
        if task.get("due"):
            parts.append(f"마감: {task.get('due')}")
        if task.get("reason"):
            parts.append(f"근거: {task.get('reason')}")
        return " | ".join(parts)

    def _format_review_error(self, item: dict[str, Any]) -> str:
        location = str(item.get("file") or "")
        if item.get("line"):
            location += f":{item.get('line')}"
        issue = str(item.get("issue") or "")
        fix = str(item.get("fix") or "")
        return " | ".join(part for part in (location, issue, f"수정: {fix}" if fix else "") if part)

    def _split_paragraphs(self, body: str) -> list[str]:
        return [part.strip() for part in str(body or "").split("\n") if part.strip()]

    def _heading_block(self, text: str) -> dict[str, Any]:
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]},
        }

    def _paragraph_block(self, text: str) -> dict[str, Any]:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]},
        }

    def _bulleted_block(self, text: str) -> dict[str, Any]:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]},
        }

    def _todo_block(self, text: str) -> dict[str, Any]:
        return {
            "object": "block",
            "type": "to_do",
            "to_do": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}], "checked": False},
        }

    def _plain_title(self, title: Any) -> str:
        if not isinstance(title, list):
            return ""
        parts: list[str] = []
        for item in title:
            if not isinstance(item, dict):
                continue
            plain_text = item.get("plain_text")
            if plain_text:
                parts.append(str(plain_text))
        return "".join(parts).strip()

    def _page_title(self, page: dict[str, Any]) -> str:
        properties = page.get("properties")
        if not isinstance(properties, dict):
            return ""
        for value in properties.values():
            if isinstance(value, dict) and value.get("type") == "title":
                return self._plain_title(value.get("title"))
        return ""
