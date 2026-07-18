from __future__ import annotations

import unittest

from github_ai_agent.harness import AgentHarness, ApprovalRequiredError, Intent


class AgentHarnessTests(unittest.TestCase):
    def test_conversation_does_not_require_project_context(self) -> None:
        decision = AgentHarness().classify_intent("안녕하세요, 반가워요")
        self.assertEqual(decision.intent, Intent.CONVERSATION)
        self.assertFalse(decision.requires_project_context)

    def test_general_question_does_not_require_github_context(self) -> None:
        harness = AgentHarness()
        weather = harness.classify_intent("오늘 날씨는 어때?")
        notion = harness.classify_intent("Notion은 어떤 서비스야?")
        self.assertEqual(weather.intent, Intent.GENERAL_QUESTION)
        self.assertEqual(notion.intent, Intent.GENERAL_QUESTION)
        self.assertFalse(weather.requires_project_context)
        self.assertFalse(notion.requires_project_context)

    def test_task_planning_prioritizes_relevant_context(self) -> None:
        decision = AgentHarness().classify_intent("오늘 할 일을 팀원들에게 배분해줘")
        self.assertEqual(decision.intent, Intent.TASK_PLANNING)
        self.assertIn("recent_commits", decision.context_hints)

    def test_natural_team_question_is_a_read_only_team_query(self) -> None:
        decision = AgentHarness().classify_intent("우리 팀에 누가 참여하고 있어?")
        self.assertEqual(decision.intent, Intent.TEAM_QUERY)
        self.assertTrue(decision.requires_project_context)

    def test_natural_blocker_question_requires_github_context(self) -> None:
        decision = AgentHarness().classify_intent(
            "지금 진행을 막고 있는 문제가 있는지 확인해줘"
        )
        self.assertEqual(decision.intent, Intent.STATUS_QUERY)
        self.assertTrue(decision.requires_project_context)
        self.assertIn("failed_workflows", decision.context_hints)

    def test_recent_changes_has_specific_context(self) -> None:
        decision = AgentHarness().classify_intent("최근 변경사항 알려줘")
        self.assertEqual(decision.intent, Intent.RECENT_CHANGES)
        self.assertEqual(
            decision.context_hints,
            ("recent_commits", "branches", "pull_requests"),
        )

    def test_read_tool_is_allowed_even_if_name_contains_commit(self) -> None:
        harness = AgentHarness()
        self.assertFalse(harness.is_write_tool("list_commits"))
        harness.authorize_tool("list_commits")

    def test_write_tool_requires_exact_approval(self) -> None:
        with self.assertRaises(ApprovalRequiredError):
            AgentHarness().authorize_tool("create_notion_task")

        AgentHarness(approved_tools={"create_notion_task"}).authorize_tool(
            "create_notion_task"
        )

    def test_failure_and_blocked_action_are_recorded_truthfully(self) -> None:
        harness = AgentHarness()
        state = harness.start_run("프로젝트 상태를 확인해줘")
        harness.record_blocked_action(state, "create_calendar_event", {"title": "회의"})
        harness.record_failure(state, "list_issues", {}, RuntimeError("network down"))
        self.assertEqual(state.blocked_actions[0]["reason"], "사용자 승인 필요")
        self.assertEqual(state.failures[0].reason, "network down")

    def test_response_prompt_prefers_natural_language(self) -> None:
        from github_ai_agent.prompts import SYSTEM_PROMPT

        self.assertIn("자연스러운 한국어 문단", SYSTEM_PROMPT)
        self.assertIn("기계적인 1, 2, 3 번호 목록을 사용하지 않는다", SYSTEM_PROMPT)
        self.assertIn("확인한 사실과 Agent의 추정을 명확히 구분", SYSTEM_PROMPT)
        self.assertIn("민감정보", SYSTEM_PROMPT)
        self.assertIn("GitHub 읽기 요청의 범위가 다소 넓어도 범위를 되묻지 않는다", SYSTEM_PROMPT)
        self.assertIn('"확인해 드릴까요?", "진행할까요?"', SYSTEM_PROMPT)

    def test_web_task_prompt_keeps_json_contract_without_rigid_answer_sections(self) -> None:
        from github_ai_agent.webapp.task_planning import (
            build_harness_analysis_prompt,
            clean_answer_for_chat,
        )

        prompt = build_harness_analysis_prompt("오늘 할 일을 나눠줘", "")
        self.assertIn('"proposed_tasks"', prompt)
        self.assertIn("자연스러운 한국어", prompt)
        self.assertIn("범위나 진행 여부를 사용자에게 되묻지 마세요", prompt)
        self.assertIn("proposed_tasks에만 넣고 answer에서 생략하지 마세요", prompt)
        self.assertIn("GitHub URL을 출력하지 마세요", prompt)
        self.assertIn("최근 활동은 핵심 5건 이내", prompt)
        self.assertNotIn("현재 상태\\n1.", prompt)
        cleaned = clean_answer_for_chat(
            "활동입니다. (커밋 URL: https://github.com/o/r/commit/abc)\n"
            "다른 링크 https://github.com/o/r/pull/1"
        )
        self.assertNotIn("https://github.com", cleaned)
        self.assertEqual(cleaned, "활동입니다.\n다른 링크")

    def test_chat_ui_keeps_explicit_notion_and_calendar_execution_paths(self) -> None:
        from pathlib import Path

        app_js = (
            Path(__file__).parents[1]
            / "src"
            / "github_ai_agent"
            / "web_assets"
            / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("isExplicitNotionSaveRequest", app_js)
        self.assertIn("/api/approve-tasks", app_js)
        self.assertIn("isExplicitCalendarSaveRequest", app_js)
        self.assertIn("/api/approve-calendar-events", app_js)
        self.assertIn('payload.agent_intent', app_js)
        self.assertIn('"답변을 작성하는 중입니다."', app_js)
        self.assertIn("const notionHint = isLightweightReply", app_js)
        self.assertIn("function formatProposedTasksForChat", app_js)
        self.assertIn("const taskSummary = isLightweightReply", app_js)
        self.assertIn('tasks.classList.add("task-list")', app_js)
        self.assertIn('tasks.classList.remove("task-list")', app_js)

    def test_chat_ui_carries_affirmative_follow_up_project_context(self) -> None:
        from pathlib import Path

        app_js = (
            Path(__file__).parents[1]
            / "src"
            / "github_ai_agent"
            / "web_assets"
            / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function isAffirmativeFollowUp", app_js)
        self.assertIn("function continuesPendingProjectRequest", app_js)
        self.assertIn("const effectiveQuestion = contextualizeFollowUp(text)", app_js)
        self.assertIn("question: effectiveQuestion", app_js)
        self.assertIn("offeredProjectLookup && mentionsReadableGithubScope", app_js)
        self.assertNotIn("할까요)\\s*[?？]?$", app_js)


if __name__ == "__main__":
    unittest.main()
