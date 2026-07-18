from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Intent(str, Enum):
    CONVERSATION = "conversation"
    GENERAL_QUESTION = "general_question"
    STATUS_QUERY = "status_query"
    RECENT_CHANGES = "recent_changes"
    TEAM_QUERY = "team_query"
    TASK_PLANNING = "task_planning"
    CODE_CHANGE = "code_change"
    DOCUMENTATION = "documentation"


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    requires_project_context: bool
    context_hints: tuple[str, ...] = ()


@dataclass
class ToolFailure:
    tool: str
    arguments: dict[str, Any]
    reason: str


@dataclass
class HarnessRunState:
    decision: IntentDecision
    selected_tools: list[dict[str, Any]] = field(default_factory=list)
    blocked_actions: list[dict[str, Any]] = field(default_factory=list)
    failures: list[ToolFailure] = field(default_factory=list)


class ApprovalRequiredError(PermissionError):
    def __init__(self, tool: str) -> None:
        super().__init__(f"사용자 승인 전에는 {tool} 도구를 실행할 수 없습니다.")
        self.tool = tool


class AgentHarness:
    """Deterministic policy layer around the model-driven agent loop.

    The model decides what information is useful.  The harness decides whether
    a proposed tool may run, records failures, and supplies intent-specific
    context without forcing the final answer into a rigid template.
    """

    _CONVERSATION_TERMS = (
        "안녕",
        "고마워",
        "감사",
        "반가워",
        "잘 지내",
        "hello",
        "hi",
        "thanks",
    )
    _PROJECT_TERMS = (
        "github",
        "깃허브",
        "프로젝트",
        "이슈",
        "issue",
        "pr",
        "커밋",
        "commit",
        "브랜치",
        "코드",
        "readme",
        "리드미",
        "작업",
        "팀원",
        "우리 팀",
        "구성원",
        "멤버",
        "참여자",
        "배분",
        "리뷰",
        "최근",
        "변경사항",
        "blocker",
        "병목",
        "진행을 막",
        "진행 막",
        "차단 요인",
        "workflow",
        "워크플로",
        "notion",
        "노션",
        "calendar",
        "캘린더",
    )

    # Mutating verbs are intentionally conservative. Unknown tools remain
    # readable unless their name clearly describes a state change.
    _WRITE_MARKERS = (
        "create",
        "update",
        "delete",
        "remove",
        "write",
        "save",
        "commit",
        "push",
        "merge",
        "close",
        "reopen",
        "assign",
        "add_",
        "set_",
        "등록",
        "생성",
        "수정",
        "삭제",
    )
    _READ_PREFIXES = (
        "get_",
        "list_",
        "search_",
        "fetch_",
        "read_",
        "show_",
        "check_",
    )

    def __init__(self, *, approved_tools: Iterable[str] = ()) -> None:
        self.approved_tools = set(approved_tools)

    def classify_intent(self, user_input: str) -> IntentDecision:
        text = user_input.strip().lower()
        has_project_term = any(term in text for term in self._PROJECT_TERMS)
        if not has_project_term and any(term in text for term in self._CONVERSATION_TERMS):
            return IntentDecision(Intent.CONVERSATION, False)
        if not has_project_term:
            return IntentDecision(Intent.GENERAL_QUESTION, False)

        service_terms = ("notion", "노션", "calendar", "캘린더")
        project_operation_terms = (
            "github", "깃허브", "프로젝트", "이슈", "issue", "pr", "커밋",
            "commit", "브랜치", "코드", "readme", "리드미", "작업", "팀원",
            "배분", "리뷰", "workflow", "워크플로",
        )
        if any(term in text for term in service_terms) and not any(
            term in text for term in project_operation_terms
        ):
            return IntentDecision(Intent.GENERAL_QUESTION, False)

        if any(term in text for term in ("배분", "분배", "오늘 뭐", "할 일", "우선순위")):
            return IntentDecision(
                Intent.TASK_PLANNING,
                True,
                ("open_issues", "open_pull_requests", "recent_commits", "failed_checks_if_needed"),
            )
        if any(
            term in text
            for term in (
                "팀원", "우리 팀", "구성원", "멤버", "참여자", "누구", "누가",
                "contributor", "collaborator",
            )
        ):
            return IntentDecision(
                Intent.TEAM_QUERY,
                True,
                ("collaborators_or_contributors", "recent_commits", "pull_requests"),
            )
        if any(term in text for term in ("최근", "변경사항", "뭐가 바뀌", "recent")):
            return IntentDecision(
                Intent.RECENT_CHANGES,
                True,
                ("recent_commits", "branches", "pull_requests"),
            )
        if any(term in text for term in ("blocker", "병목", "진행을 막", "진행 막", "차단 요인")):
            return IntentDecision(
                Intent.STATUS_QUERY,
                True,
                ("open_issues", "blocking_pull_requests", "failed_workflows"),
            )
        if any(term in text for term in ("readme", "리드미", "문서")):
            return IntentDecision(Intent.DOCUMENTATION, True, ("recent_commits", "repository_files"))
        if any(term in text for term in ("고쳐", "수정", "구현", "코드 작성")):
            return IntentDecision(Intent.CODE_CHANGE, True, ("repository_files", "recent_changes"))
        return IntentDecision(
            Intent.STATUS_QUERY,
            True,
            ("open_issues", "open_pull_requests", "recent_commits", "workflows_if_relevant"),
        )

    def start_run(self, user_input: str) -> HarnessRunState:
        return HarnessRunState(decision=self.classify_intent(user_input))

    def is_write_tool(self, tool_name: str) -> bool:
        lowered = tool_name.lower().replace("-", "_").replace(".", "_")
        if lowered.startswith(self._READ_PREFIXES):
            return False
        return any(marker in lowered for marker in self._WRITE_MARKERS)

    def authorize_tool(self, tool_name: str) -> None:
        if self.is_write_tool(tool_name) and tool_name not in self.approved_tools:
            raise ApprovalRequiredError(tool_name)

    def record_tool_call(
        self,
        state: HarnessRunState,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        state.selected_tools.append({"tool": tool_name, "arguments": arguments})

    def record_blocked_action(
        self,
        state: HarnessRunState,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        state.blocked_actions.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "reason": "사용자 승인 필요",
            }
        )

    def record_failure(
        self,
        state: HarnessRunState,
        tool_name: str,
        arguments: dict[str, Any],
        error: Exception,
    ) -> None:
        state.failures.append(
            ToolFailure(tool=tool_name, arguments=arguments, reason=str(error))
        )

    def build_user_context(self, state: HarnessRunState) -> str:
        hints = ", ".join(state.decision.context_hints) or "없음"
        return (
            "하네스 판단:\n"
            f"- 의도: {state.decision.intent.value}\n"
            f"- 프로젝트 조회 필요: {state.decision.requires_project_context}\n"
            f"- 우선 확인 후보: {hints}\n"
            "후보를 전부 호출하지 말고 질문에 직접 필요한 도구만 선택하세요."
        )
