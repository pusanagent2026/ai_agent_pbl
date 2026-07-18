from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.mcp_client import McpTool


class FakeMessage:
    def __init__(self, *, content: str = "", tool_calls: list[object] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none: bool = True) -> dict[str, object]:
        data: dict[str, object] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        return data


class FakeCompletions:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self.messages = list(messages)
        self.requests: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        message = self.messages.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAI:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(messages))


class FakeTools:
    def __init__(self, *, fail_reads: bool = False) -> None:
        self.list_count = 0
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_reads = fail_reads

    async def list_tools(self) -> list[McpTool]:
        self.list_count += 1
        return [
            McpTool("list_issues", "Read issues", {"type": "object", "properties": {}}),
            McpTool("create_notion_task", "Write task", {"type": "object", "properties": {}}),
        ]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, arguments))
        if self.fail_reads:
            raise RuntimeError("backend unavailable")
        return "{}"


def tool_call(name: str, arguments: dict[str, object]) -> object:
    return SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class AgentHarnessIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_never_lists_or_calls_tools(self) -> None:
        client = FakeOpenAI([FakeMessage(content="안녕하세요! 무엇을 도와드릴까요?")])
        tools = FakeTools()
        agent = GitHubToolChoosingAgent(client=client)
        result = await agent.run("안녕하세요", tools)
        self.assertEqual(result.intent, "conversation")
        self.assertEqual(tools.list_count, 0)
        self.assertEqual(tools.calls, [])
        self.assertNotIn("tools", client.chat.completions.requests[0])
        user_message = client.chat.completions.requests[0]["messages"][1]["content"]
        self.assertNotIn("기본 GitHub 저장소 컨텍스트", user_message)

    async def test_intent_can_be_classified_from_original_unwrapped_input(self) -> None:
        client = FakeOpenAI([FakeMessage(content="안녕하세요!")])
        tools = FakeTools()
        agent = GitHubToolChoosingAgent(client=client)
        result = await agent.run(
            "GitHub 분석 규칙과 JSON 스키마가 포함된 긴 내부 프롬프트",
            tools,
            intent_input="안녕하세요",
        )
        self.assertEqual(result.intent, "conversation")
        self.assertEqual(tools.list_count, 0)

    async def test_project_query_requires_a_tool_attempt_before_answering(self) -> None:
        client = FakeOpenAI(
            [
                FakeMessage(tool_calls=[tool_call("list_issues", {})]),
                FakeMessage(content="확인된 팀 활동을 정리했습니다."),
            ]
        )
        tools = FakeTools()
        await GitHubToolChoosingAgent(client=client).run(
            "우리 팀에 누가 참여하고 있어?", tools
        )
        requests = client.chat.completions.requests
        self.assertEqual(requests[0]["tool_choice"], "required")
        self.assertEqual(requests[1]["tool_choice"], "auto")
        self.assertEqual(tools.calls[0][0], "list_issues")

    async def test_unapproved_write_is_blocked_but_answer_can_continue(self) -> None:
        client = FakeOpenAI(
            [
                FakeMessage(tool_calls=[tool_call("create_notion_task", {"title": "문서화"})]),
                FakeMessage(content="Notion 등록은 승인 후 진행할 수 있어요."),
            ]
        )
        tools = FakeTools()
        result = await GitHubToolChoosingAgent(client=client).run(
            "프로젝트 작업을 Notion에 정리해줘", tools
        )
        self.assertEqual(tools.calls, [])
        self.assertEqual(result.blocked_actions[0]["tool"], "create_notion_task")
        self.assertIn("승인", result.answer)

    async def test_approved_write_executes(self) -> None:
        client = FakeOpenAI(
            [
                FakeMessage(tool_calls=[tool_call("create_notion_task", {"title": "문서화"})]),
                FakeMessage(content="승인된 작업을 등록했습니다."),
            ]
        )
        tools = FakeTools()
        agent = GitHubToolChoosingAgent(
            client=client,
            approved_tools={"create_notion_task"},
        )
        result = await agent.run("승인한 Notion 작업을 등록해줘", tools)
        self.assertEqual(tools.calls[0][0], "create_notion_task")
        self.assertEqual(result.blocked_actions, [])

    async def test_tool_failure_is_recorded_and_not_reported_as_execution(self) -> None:
        client = FakeOpenAI(
            [
                FakeMessage(tool_calls=[tool_call("list_issues", {})]),
                FakeMessage(content="이슈 조회가 실패해 현재 상태는 확인하지 못했습니다."),
            ]
        )
        tools = FakeTools(fail_reads=True)
        result = await GitHubToolChoosingAgent(client=client).run(
            "프로젝트 상태를 알려줘", tools
        )
        self.assertEqual(result.failures[0]["tool"], "list_issues")
        self.assertIn("실패", result.answer)


if __name__ == "__main__":
    unittest.main()
