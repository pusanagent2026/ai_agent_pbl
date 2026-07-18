from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from github_ai_agent.github_app_auth import resolve_default_repository
from github_ai_agent.harness import AgentHarness, ApprovalRequiredError, Intent
from github_ai_agent.mcp_client import GitHubMcpClient, McpTool
from github_ai_agent.prompts import SYSTEM_PROMPT


@dataclass
class AgentResult:
    answer: str
    selected_tools: list[dict[str, Any]] = field(default_factory=list)
    blocked_actions: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    intent: str = ""


class GitHubToolChoosingAgent:
    def __init__(
        self,
        *,
        model: str | None = None,
        owner: str | None = None,
        repo: str | None = None,
        max_tool_rounds: int = 6,
        system_prompt: str | None = None,
        approved_tools: set[str] | None = None,
        harness: AgentHarness | None = None,
        client: Any | None = None,
    ) -> None:
        self.client = client or AsyncOpenAI()
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        default_owner, default_repo = resolve_default_repository()
        self.owner = owner or default_owner
        self.repo = repo or default_repo
        self.max_tool_rounds = max_tool_rounds
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.harness = harness or AgentHarness(approved_tools=approved_tools or set())

    async def run(
        self,
        question: str,
        mcp: GitHubMcpClient,
        *,
        intent_input: str | None = None,
    ) -> AgentResult:
        state = self.harness.start_run(intent_input or question)
        mcp_tools = [] if state.decision.intent == Intent.CONVERSATION else await mcp.list_tools()
        tool_name_map = {self._safe_tool_name(tool.name): tool.name for tool in mcp_tools}
        tool_schema_map = {tool.name: tool.input_schema for tool in mcp_tools}
        openai_tools = [self._to_openai_tool(tool) for tool in mcp_tools]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    self._build_user_message(
                        question,
                        include_repository=state.decision.requires_project_context,
                    )
                    + "\n\n"
                    + self.harness.build_user_context(state)
                ),
            },
        ]

        for round_index in range(self.max_tool_rounds):
            request: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }
            if openai_tools:
                # A project-information request must perform at least one
                # read attempt before it can answer. This prevents the model
                # from replacing a harmless lookup with another confirmation
                # question such as "조회할까요?".
                tool_choice = (
                    "required"
                    if state.decision.requires_project_context
                    and round_index == 0
                    and not state.selected_tools
                    else "auto"
                )
                request.update({"tools": openai_tools, "tool_choice": tool_choice})
            completion = await self.client.chat.completions.create(**request)
            message = completion.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                return self._result(message.content or "", state)

            for tool_call in message.tool_calls:
                openai_tool_name = tool_call.function.name
                tool_name = tool_name_map.get(openai_tool_name, openai_tool_name)
                arguments = self._parse_arguments(tool_call.function.arguments)
                arguments = self._inject_repo_defaults(
                    arguments,
                    tool_schema_map.get(tool_name, {}),
                )
                self.harness.record_tool_call(state, tool_name, arguments)
                try:
                    self.harness.authorize_tool(tool_name)
                    tool_result = await mcp.call_tool(tool_name, arguments)
                except ApprovalRequiredError as error:
                    self.harness.record_blocked_action(state, tool_name, arguments)
                    tool_result = str(error)
                except Exception as error:
                    self.harness.record_failure(state, tool_name, arguments, error)
                    tool_result = f"도구 실행 실패: {error}"
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
                        "도구 호출 최대 횟수에 도달했습니다. 지금까지 확인된 결과만 근거로 "
                        "자연스러운 한국어 최종 답변을 작성하세요. 실행하지 않은 작업을 "
                        "실행했다고 표현하지 마세요."
                    ),
                },
            ],
        )
        return self._result(final.choices[0].message.content or "", state)

    def _result(self, answer: str, state: Any) -> AgentResult:
        return AgentResult(
            answer=answer,
            selected_tools=state.selected_tools,
            blocked_actions=state.blocked_actions,
            failures=[failure.__dict__ for failure in state.failures],
            intent=state.decision.intent.value,
        )

    def _build_user_message(
        self,
        question: str,
        *,
        include_repository: bool = True,
    ) -> str:
        if not include_repository:
            return f"사용자 질문:\n{question}"
        context = {"default_owner": self.owner, "default_repo": self.repo}
        return (
            "사용자 질문:\n"
            f"{question}\n\n"
            "기본 GitHub 저장소 컨텍스트:\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )

    def _to_openai_tool(self, tool: McpTool) -> dict[str, Any]:
        schema = dict(tool.input_schema or {})
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}, "additionalProperties": True}
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
