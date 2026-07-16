from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from github_ai_agent.github_app_auth import resolve_default_repository
from github_ai_agent.mcp_client import GitHubMcpClient, McpTool
from github_ai_agent.prompts import SYSTEM_PROMPT


@dataclass
class AgentResult:
    answer: str
    selected_tools: list[dict[str, Any]] = field(default_factory=list)


class GitHubToolChoosingAgent:
    def __init__(
        self,
        *,
        model: str | None = None,
        owner: str | None = None,
        repo: str | None = None,
        max_tool_rounds: int = 6,
        system_prompt: str | None = None,
    ) -> None:
        self.client = AsyncOpenAI()
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        default_owner, default_repo = resolve_default_repository()
        self.owner = owner or default_owner
        self.repo = repo or default_repo
        self.max_tool_rounds = max_tool_rounds
        self.system_prompt = system_prompt or SYSTEM_PROMPT

    async def run(self, question: str, mcp: GitHubMcpClient) -> AgentResult:
        mcp_tools = await mcp.list_tools()
        tool_name_map = {self._safe_tool_name(tool.name): tool.name for tool in mcp_tools}
        tool_schema_map = {tool.name: tool.input_schema for tool in mcp_tools}
        openai_tools = [self._to_openai_tool(tool) for tool in mcp_tools]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": self._build_user_message(question),
            },
        ]
        selected_tools: list[dict[str, Any]] = []

        for _ in range(self.max_tool_rounds):
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )
            message = completion.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                return AgentResult(
                    answer=message.content or "",
                    selected_tools=selected_tools,
                )

            for tool_call in message.tool_calls:
                openai_tool_name = tool_call.function.name
                tool_name = tool_name_map.get(openai_tool_name, openai_tool_name)
                arguments = self._parse_arguments(tool_call.function.arguments)
                arguments = self._inject_repo_defaults(
                    arguments,
                    tool_schema_map.get(tool_name, {}),
                )

                selected_tools.append(
                    {
                        "tool": tool_name,
                        "arguments": arguments,
                    }
                )

                tool_result = await mcp.call_tool(tool_name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    }
                )

        final = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                *messages,
                {
                    "role": "user",
                    "content": (
                        "도구 호출 횟수 한도에 도달했습니다. 지금까지 확인한 "
                        "결과만 바탕으로 최종 답변을 작성하세요."
                    ),
                },
            ],
        )
        return AgentResult(
            answer=final.choices[0].message.content or "",
            selected_tools=selected_tools,
        )

    def _build_user_message(self, question: str) -> str:
        context = {
            "default_owner": self.owner,
            "default_repo": self.repo,
        }
        return (
            "User question:\n"
            f"{question}\n\n"
            "Default GitHub repository context:\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )

    def _to_openai_tool(self, tool: McpTool) -> dict[str, Any]:
        schema = dict(tool.input_schema or {})
        if schema.get("type") != "object":
            schema = {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            }

        return {
            "type": "function",
            "function": {
                "name": self._safe_tool_name(tool.name),
                "description": tool.description or f"Call tool {tool.name}.",
                "parameters": schema,
            },
        }

    def _safe_tool_name(self, name: str) -> str:
        return name.replace("-", "_").replace(".", "_")

    def _parse_arguments(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _inject_repo_defaults(
        self,
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        patched = dict(arguments)
        properties = schema.get("properties", {})

        owner_keys = ("owner", "org", "organization")
        repo_keys = ("repo", "repository")

        if self.owner and not any(patched.get(key) for key in owner_keys):
            owner_key = next((key for key in owner_keys if key in properties), None)
            if owner_key:
                patched[owner_key] = self.owner

        if self.repo and not any(patched.get(key) for key in repo_keys):
            repo_key = next((key for key in repo_keys if key in properties), None)
            if repo_key:
                patched[repo_key] = self.repo

        return patched
