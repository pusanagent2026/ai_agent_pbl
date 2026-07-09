from __future__ import annotations

from typing import Any

from github_ai_agent.mcp_client import McpTool


class CombinedToolClient:
    def __init__(self, clients: list[Any]) -> None:
        self.clients = clients
        self.tool_to_client: dict[str, Any] = {}

    async def __aenter__(self) -> "CombinedToolClient":
        for client in self.clients:
            enter = getattr(client, "__aenter__", None)
            if enter is not None:
                await enter()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        for client in reversed(self.clients):
            exit_ = getattr(client, "__aexit__", None)
            if exit_ is not None:
                await exit_(exc_type, exc, tb)

    async def list_tools(self) -> list[McpTool]:
        tools: list[McpTool] = []
        self.tool_to_client = {}

        for client in self.clients:
            for tool in await client.list_tools():
                if tool.name in self.tool_to_client:
                    raise ValueError(f"Duplicate tool name: {tool.name}")
                self.tool_to_client[tool.name] = client
                tools.append(tool)

        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        client = self.tool_to_client.get(name)
        if client is None:
            await self.list_tools()
            client = self.tool_to_client.get(name)
        if client is None:
            raise ValueError(f"Unknown tool: {name}")
        return await client.call_tool(name, arguments)
