from __future__ import annotations

import os
import shlex
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from github_ai_agent.github_app_auth import GitHubAppTokenProvider


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]


class GitHubMcpClient:
    def __init__(self, command: str | None = None, installation_id: str | None = None) -> None:
        self.command = command or os.environ.get("GITHUB_MCP_COMMAND")
        if not self.command:
            raise ValueError("GITHUB_MCP_COMMAND is required.")

        self.installation_id = installation_id
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "GitHubMcpClient":
        parts = shlex.split(self.command, posix=os.name != "nt")
        if not parts:
            raise ValueError("GITHUB_MCP_COMMAND is empty.")

        env = os.environ.copy()
        command_dir = os.path.dirname(parts[0])
        if command_dir and os.path.basename(parts[0]).lower() in {"docker", "docker.exe"}:
            env["PATH"] = command_dir + os.pathsep + env.get("PATH", "")

        app_token_provider = GitHubAppTokenProvider(self.installation_id)
        if app_token_provider.enabled:
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = app_token_provider.create_installation_token()
        elif env.get("GITHUB_TOKEN") and not env.get("GITHUB_PERSONAL_ACCESS_TOKEN"):
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = env["GITHUB_TOKEN"]

        server_params = StdioServerParameters(
            command=parts[0],
            args=parts[1:],
            env=env,
        )

        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(server_params)
        )
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self._stack.aclose()

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("GitHubMcpClient is not connected.")
        return self._session

    async def list_tools(self) -> list[McpTool]:
        response = await self.session.list_tools()
        return [
            McpTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema or {"type": "object", "properties": {}},
            )
            for tool in response.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self.session.call_tool(name, arguments)
        chunks: list[str] = []

        for item in result.content:
            text = getattr(item, "text", None)
            if text is not None:
                chunks.append(text)
            else:
                chunks.append(str(item))

        if result.isError:
            raise RuntimeError("MCP tool returned an error:\n" + "\n".join(chunks))

        return "\n".join(chunks)
