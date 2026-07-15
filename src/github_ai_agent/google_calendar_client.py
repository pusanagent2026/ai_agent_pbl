from __future__ import annotations

import json
import os
import shlex
import urllib.error
import urllib.request
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.stdio import stdio_client

from github_ai_agent.mcp_client import McpTool


@dataclass(frozen=True)
class GoogleCalendarConfig:
    backend: str
    calendar_id: str
    timezone: str
    service_account_file: str
    service_account_json: str
    mcp_command: str
    mcp_url: str
    mcp_auth_token: str
    mcp_create_event_tool: str


class GoogleCalendarToolClient:
    def __init__(
        self,
        *,
        mcp_auth_token: str | None = None,
        calendar_id: str | None = None,
    ) -> None:
        self.config = GoogleCalendarConfig(
            backend=os.environ.get("GOOGLE_CALENDAR_BACKEND", "api"),
            calendar_id=calendar_id or os.environ.get("GOOGLE_CALENDAR_ID", ""),
            timezone=os.environ.get("GOOGLE_CALENDAR_TIMEZONE", "Asia/Seoul"),
            service_account_file=os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
            service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            mcp_command=os.environ.get("CALENDAR_MCP_COMMAND", ""),
            mcp_url=os.environ.get("CALENDAR_MCP_URL", ""),
            mcp_auth_token=(
                mcp_auth_token
                or os.environ.get("CALENDAR_MCP_AUTH_TOKEN", "")
                or os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "")
            ),
            mcp_create_event_tool=os.environ.get("CALENDAR_MCP_CREATE_EVENT_TOOL", ""),
        )
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._tools: list[McpTool] = []

    @property
    def enabled(self) -> bool:
        if self.config.backend == "mcp":
            return bool(self.config.mcp_command or self.config.mcp_url)
        return self._api_enabled

    @property
    def _api_enabled(self) -> bool:
        has_credentials = bool(
            self.config.service_account_json
            or (self.config.service_account_file and Path(self.config.service_account_file).exists())
        )
        return bool(self.config.calendar_id and has_credentials)

    async def __aenter__(self) -> "GoogleCalendarToolClient":
        if self.config.backend == "mcp" and self.config.mcp_url:
            headers: dict[str, str] = {}
            if self.config.mcp_auth_token:
                headers["Authorization"] = f"Bearer {self.config.mcp_auth_token}"
            read_stream, write_stream, _ = await self._stack.enter_async_context(
                streamablehttp_client(self.config.mcp_url, headers=headers or None)
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        elif self.config.backend == "mcp" and self.config.mcp_command:
            parts = shlex.split(self.config.mcp_command, posix=os.name != "nt")
            if not parts:
                raise ValueError("CALENDAR_MCP_COMMAND is empty.")
            env = os.environ.copy()
            command_dir = os.path.dirname(parts[0])
            if command_dir and os.path.basename(parts[0]).lower() in {"docker", "docker.exe"}:
                env["PATH"] = command_dir + os.pathsep + env.get("PATH", "")
            read_stream, write_stream = await self._stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=parts[0],
                        args=parts[1:],
                        env=env,
                    )
                )
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self._stack.aclose()

    async def list_tools(self) -> list[McpTool]:
        if not self.enabled:
            return []
        if self.config.backend != "mcp":
            return [self._api_tool_schema()]
        if self._session is None:
            return []
        response = await self._session.list_tools()
        self._tools = [
            McpTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema or {"type": "object", "properties": {}},
            )
            for tool in response.tools
        ]
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self.config.backend != "mcp":
            return await self._call_api_tool(name, arguments)
        if not self.enabled:
            raise ValueError(
                "Calendar MCP is enabled, but CALENDAR_MCP_URL or CALENDAR_MCP_COMMAND is required."
            )
        if self._session is None:
            raise RuntimeError("Calendar MCP client is not connected.")
        tools = self._tools or await self.list_tools()
        tool = self._pick_create_event_tool(tools)
        mcp_arguments = self._build_mcp_event_arguments(tool, arguments)
        result = await self._session.call_tool(tool.name, mcp_arguments)

        chunks: list[str] = []
        for item in result.content:
            text = getattr(item, "text", None)
            chunks.append(text if text is not None else str(item))
        if result.isError:
            message = "\n".join(chunks)
            if self.config.mcp_auth_token and self._is_permission_error(message):
                return await self._call_oauth_calendar_api_tool(name, arguments)
            raise ValueError("MCP tool returned an error:\n" + message)
        return "\n".join(chunks) or json.dumps(
            {"created": True, "tool": tool.name, "arguments": mcp_arguments},
            ensure_ascii=False,
        )

    @staticmethod
    def _is_permission_error(message: str) -> bool:
        lowered = message.lower()
        return (
            "permission" in lowered
            or "forbidden" in lowered
            or "403" in lowered
            or "access_denied" in lowered
        )

    def _pick_create_event_tool(self, tools: list[McpTool]) -> McpTool:
        if self.config.mcp_create_event_tool:
            for tool in tools:
                if tool.name == self.config.mcp_create_event_tool:
                    return tool
            raise ValueError(
                f"CALENDAR_MCP_CREATE_EVENT_TOOL={self.config.mcp_create_event_tool} was not found."
            )

        preferred_keywords = ("create", "insert", "add")
        calendar_keywords = ("event", "calendar")
        for tool in tools:
            name = tool.name.lower()
            if any(word in name for word in preferred_keywords) and any(
                word in name for word in calendar_keywords
            ):
                return tool
        for tool in tools:
            if "event" in tool.name.lower():
                return tool
        names = ", ".join(tool.name for tool in tools) or "none"
        raise ValueError(
            "Could not find a Calendar MCP create-event tool. "
            f"Set CALENDAR_MCP_CREATE_EVENT_TOOL. Available tools: {names}"
        )

    def _build_mcp_event_arguments(
        self,
        tool: McpTool,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        properties = tool.input_schema.get("properties", {})
        if not isinstance(properties, dict) or not properties:
            return self._broad_event_arguments(task)

        broad = self._broad_event_arguments(task)
        args: dict[str, Any] = {}
        aliases = {
            "calendarId": "calendar_id",
            "calendar_id": "calendar_id",
            "calendar": "calendar_id",
            "summary": "summary",
            "title": "summary",
            "name": "summary",
            "description": "description",
            "details": "description",
            "start": "start",
            "startTime": "start",
            "start_time": "start",
            "startDate": "start_date",
            "start_date": "start_date",
            "end": "end",
            "endTime": "end",
            "end_time": "end",
            "endDate": "end_date",
            "end_date": "end_date",
            "date": "start_date",
            "due": "start_date",
            "timeZone": "timezone",
            "time_zone": "timezone",
            "timezone": "timezone",
        }
        for key in properties:
            source = aliases.get(key)
            if source and broad.get(source):
                args[key] = broad[source]
        return args or broad

    def _broad_event_arguments(self, task: dict[str, Any]) -> dict[str, Any]:
        due = str(task.get("due") or "").strip()
        if not due:
            raise ValueError("Task due date is required to create a calendar event.")
        start = datetime.strptime(due, "%Y-%m-%d").date()
        end = start + timedelta(days=1)
        description = self._description(task)
        return {
            "calendar_id": self.config.calendar_id,
            "calendarId": self.config.calendar_id,
            "summary": str(task.get("title") or "Task deadline"),
            "description": description,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "startTime": start.isoformat(),
            "endTime": end.isoformat(),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": self.config.timezone,
            "timeZone": self.config.timezone,
            "allDay": True,
        }

    def _api_tool_schema(self) -> McpTool:
        return McpTool(
            name="create_calendar_event",
            description="Create an all-day Google Calendar event for an approved task.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due": {"type": "string", "description": "YYYY-MM-DD"},
                    "assignee": {"type": "string"},
                    "assignee_github": {"type": "string"},
                    "priority": {"type": "string"},
                    "source": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["title", "due"],
                "additionalProperties": False,
            },
        )

    async def _call_api_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "create_calendar_event":
            raise ValueError(f"Unknown Google Calendar tool: {name}")
        if not self._api_enabled:
            raise ValueError(
                "GOOGLE_CALENDAR_ID and Google service account credentials are required."
            )
        service = self._build_service()
        event = self._build_api_event(arguments)
        try:
            created = service.events().insert(calendarId=self.config.calendar_id, body=event).execute()
        except Exception as error:
            raise ValueError(f"Google Calendar API error: {error!r}") from error
        return json.dumps(
            {
                "created": True,
                "title": arguments.get("title"),
                "calendar_event_id": created.get("id"),
                "html_link": created.get("htmlLink"),
            },
            ensure_ascii=False,
            indent=2,
        )

    async def _call_oauth_calendar_api_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "create_calendar_event":
            raise ValueError(f"Unknown Google Calendar tool: {name}")
        if not self.config.calendar_id:
            raise ValueError("GOOGLE_CALENDAR_ID is required.")
        if not self.config.mcp_auth_token:
            raise ValueError("Google OAuth access token is required.")

        event = self._build_api_event(arguments)
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{quote(self.config.calendar_id, safe='')}/events"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(event).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.mcp_auth_token}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                created = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ValueError(f"Google Calendar OAuth API error {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise ValueError(f"Google Calendar OAuth API error: {error.reason}") from error

        return json.dumps(
            {
                "created": True,
                "title": arguments.get("title"),
                "calendar_event_id": created.get("id"),
                "html_link": created.get("htmlLink"),
                "backend": "google-calendar-api-fallback",
            },
            ensure_ascii=False,
            indent=2,
        )

    def _build_service(self) -> Any:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as error:
            raise ValueError(
                "Google Calendar dependencies are missing. Run: pip install -e ."
            ) from error

        scopes = ["https://www.googleapis.com/auth/calendar.events"]
        if self.config.service_account_json:
            info = json.loads(self.config.service_account_json)
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=scopes,
            )
        else:
            credentials = service_account.Credentials.from_service_account_file(
                self.config.service_account_file,
                scopes=scopes,
            )
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def _build_api_event(self, arguments: dict[str, Any]) -> dict[str, Any]:
        due = str(arguments.get("due") or "").strip()
        if not due:
            raise ValueError("Task due date is required to create a calendar event.")
        start = datetime.strptime(due, "%Y-%m-%d").date()
        end = start + timedelta(days=1)
        return {
            "summary": str(arguments.get("title") or "Task deadline"),
            "description": self._description(arguments),
            "start": {"date": start.isoformat(), "timeZone": self.config.timezone},
            "end": {"date": end.isoformat(), "timeZone": self.config.timezone},
        }

    def _description(self, arguments: dict[str, Any]) -> str:
        assignee = str(arguments.get("assignee") or "")
        github_id = str(arguments.get("assignee_github") or "")
        priority = str(arguments.get("priority") or "")
        source = str(arguments.get("source") or "")
        reason = str(arguments.get("reason") or "")
        description_parts = [
            f"담당자: {assignee}" if assignee else "",
            f"GitHub: @{github_id}" if github_id else "",
            f"우선순위: {priority}" if priority else "",
            f"근거: {source}" if source else "",
            f"이유: {reason}" if reason else "",
        ]
        return "\n".join(part for part in description_parts if part)
