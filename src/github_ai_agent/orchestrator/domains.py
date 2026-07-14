"""Domain registration point.

To add a new domain (code review, meeting, ...):
1. Build your domain's own agent/tool logic in your own module(s) — do not
   edit this file's existing entries.
2. Add one `build_<domain>_domain_agent()` function here that returns a
   `DomainAgent` (name, description, async run(question) -> str).
3. Append it to the list passed into `OrchestratorAgent(domains=[...])` in
   cli.py / web.py.

The orchestrator only ever calls `DomainAgent.run(question)` — your domain's
internal tools, prompts, and backends stay private to your module.

This file also owns two structured (non-orchestrator) workflows that the web
UI's approval flow depends on: GitHub task analysis (`analyze_tasks`) and the
bulk Notion/Calendar creation calls used once a user approves proposed
tasks. Those return structured JSON rather than a plain string answer, so
they don't fit the `DomainAgent.run(question) -> str` contract and are called
directly instead of through the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from typing import Any

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_api_client import DirectGitHubToolClient
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent.orchestrator.agent import DomainAgent


# ---------------------------------------------------------------------------
# github domain — plain Q&A, used by the orchestrator (CLI / delegate tool)
# ---------------------------------------------------------------------------


def build_github_domain_agent(
    *,
    owner: str | None = None,
    repo: str | None = None,
    backend: str | None = None,
) -> DomainAgent:
    """Wraps the existing GitHub tool-calling flow as one delegate tool."""

    async def run(question: str) -> str:
        agent = GitHubToolChoosingAgent(owner=owner, repo=repo)
        resolved_backend = backend or os.environ.get("GITHUB_TOOL_BACKEND", "github-api")
        github_client = (
            GitHubMcpClient()
            if resolved_backend == "mcp"
            else DirectGitHubToolClient(owner=owner, repo=repo)
        )
        async with github_client as tools:
            result = await agent.run(question, tools)
        return result.answer

    return DomainAgent(
        name="github",
        description=(
            "Answers questions about this GitHub repository: issues, pull "
            "requests, commits, contributors, and workflow runs."
        ),
        run=run,
    )


# ---------------------------------------------------------------------------
# github domain — task analysis + approval workflow, used by the web UI
# ---------------------------------------------------------------------------


async def analyze_tasks(question: str, *, project_deadline: str = "") -> dict[str, Any]:
    backend = os.environ.get("GITHUB_TOOL_BACKEND", "github-api")
    agent = GitHubToolChoosingAgent()
    github_client = GitHubMcpClient() if backend == "mcp" else DirectGitHubToolClient()

    preloaded_context = ""
    preloaded_tools: list[dict[str, Any]] = []
    if backend == "github-api":
        async with github_client as tools:
            preloaded_context = await _load_repo_context(tools)
            preloaded_tools = [
                {"tool": "list_contributors", "arguments": {"per_page": 20}},
                {"tool": "list_collaborators", "arguments": {"per_page": 20}},
                {"tool": "list_organization_members", "arguments": {"per_page": 20}},
                {"tool": "list_commits", "arguments": {"per_page": 20}},
                {"tool": "list_issues", "arguments": {"state": "open", "per_page": 20}},
                {"tool": "list_pull_requests", "arguments": {"state": "open", "per_page": 20}},
            ]
        github_client = DirectGitHubToolClient()

    analysis_prompt = _build_analysis_prompt(question, preloaded_context, project_deadline)

    async with github_client as tools:
        result = await agent.run(analysis_prompt, tools)

    parsed = _parse_task_json(result.answer)
    return {
        "answer": parsed.get("answer") or result.answer,
        "proposed_tasks": _normalize_tasks(
            parsed.get("proposed_tasks", []),
            project_deadline=project_deadline,
        ),
        "selected_tools": [*preloaded_tools, *result.selected_tools],
    }


def load_config_members() -> dict[str, Any]:
    if os.environ.get("GITHUB_TOOL_BACKEND", "github-api") != "github-api":
        return {"members": [], "member_warnings": ["MCP backend에서는 UI 사전 조회 생략"]}
    try:
        client = DirectGitHubToolClient()
    except Exception:
        return {"members": [], "member_warnings": ["GitHub 설정 확인 필요"]}

    async def load() -> dict[str, Any]:
        contributors_raw = "[]"
        collaborators_raw = "[]"
        organization_members_raw = "[]"
        warnings: list[str] = []
        async with client as tools:
            try:
                contributors_raw = await tools.call_tool("list_contributors", {"per_page": 20})
            except Exception:
                warnings.append("contributors 조회 실패")
            try:
                collaborators_raw = await tools.call_tool("list_collaborators", {"per_page": 20})
            except Exception:
                warnings.append("collaborators 조회 실패")
            try:
                organization_members_raw = await tools.call_tool(
                    "list_organization_members", {"per_page": 20}
                )
            except Exception:
                warnings.append("organization members 조회 실패")
        warnings.extend(_extract_warnings(collaborators_raw, "collaborators"))
        warnings.extend(_extract_warnings(organization_members_raw, "organization members"))
        if _is_empty_list(organization_members_raw):
            warnings.append("organization members 권한 필요")
        return {
            "members": _extract_members(contributors_raw, collaborators_raw, organization_members_raw),
            "member_warnings": warnings,
        }

    try:
        return asyncio.run(load())
    except Exception:
        return {"members": [], "member_warnings": ["GitHub 팀원 조회 실패"]}


async def _load_repo_context(tools: DirectGitHubToolClient) -> str:
    chunks: list[str] = []
    calls = (
        ("list_contributors", {"per_page": 20}),
        ("list_collaborators", {"per_page": 20}),
        ("list_organization_members", {"per_page": 20}),
        ("list_commits", {"per_page": 20}),
        ("list_issues", {"state": "open", "per_page": 20}),
        ("list_pull_requests", {"state": "open", "per_page": 20}),
    )
    for tool_name, arguments in calls:
        try:
            result = await tools.call_tool(tool_name, arguments)
        except Exception as error:
            result = json.dumps({"error": str(error)}, ensure_ascii=False)
        chunks.append(f"{tool_name}:\n{result}")
    return "\n\n".join(chunks)


def _build_analysis_prompt(
    question: str,
    preloaded_context: str,
    project_deadline: str,
) -> str:
    today = date.today().isoformat()
    deadline_rule = (
        f"사용자가 입력한 프로젝트 전체 마감일은 {project_deadline}입니다. "
        "모든 proposed_tasks의 due는 오늘 이후이면서 이 날짜 이하인 YYYY-MM-DD로 반드시 채우세요. "
        "우선순위가 높은 작업은 더 이른 날짜에 배치하고, 작업들이 같은 날에 과도하게 몰리지 않게 분산하세요."
        if project_deadline
        else "사용자가 프로젝트 전체 마감일을 아직 입력하지 않았습니다. 작업 배분은 하되 due는 빈 문자열로 두고, answer에서 전체 마감일 입력이 필요하다고 안내하세요."
    )
    return f"""
사용자 질문을 문장 그대로만 보지 말고 의미와 맥락으로 해석하세요.

오늘 날짜: {today}
프로젝트 전체 마감일 규칙: {deadline_rule}

사용자 질문:
{question}

GitHub에서 미리 조회한 저장소 활동 정보:
{preloaded_context or "미리 조회된 GitHub 활동 정보 없음"}

처리 규칙:
1. 팀원 목록은 GitHub contributors, collaborators, organization members 결과에서 자동으로 판단합니다.
2. collaborators나 organization members 조회가 권한 오류 또는 빈 결과를 반환하면 그 사실을 설명하고 contributors와 commits 기준으로 확인 가능한 팀원을 말합니다.
3. 사용자가 "팀원이 누구야", "누구누구 있어", "우리 팀 구성 알려줘", "참여자 알려줘"처럼 묻는 경우는 모두 팀원 조회 요청으로 처리합니다.
4. 사용자가 "할 일 배분", "분담", "나눠줘", "누가 뭘 하면 돼", "각자 맡을 일", "오늘 할 일 정해줘"처럼 묻는 경우는 모두 작업 배분 요청으로 처리합니다.
5. 작업 배분 요청이면 최근 commit message, author/login, open issues, open PRs를 근거로 팀원별 작업 성향을 추정하고 담당자를 배정합니다.
6. 특정 팀원이 특정 종류의 작업을 많이 했다면 비슷한 작업을 우선 배정하되, 한 사람에게 과도하게 몰리지 않게 균형을 고려합니다.
7. open issue나 PR이 없어도 "할 일이 없음"으로 끝내지 말고, 최근 커밋과 저장소 상태를 근거로 점검, 문서화, 테스트, 다음 기능 계획 같은 현실적인 작업 후보를 만듭니다.
8. 사용자가 팀원 목록만 물었다면 proposed_tasks는 빈 배열로 둡니다.
9. 사용자가 작업 배분이나 오늘 할 일을 물었다면 proposed_tasks에 담당자, 담당자 GitHub ID, 마감일 due를 포함한 작업 후보를 최대 5개 넣습니다.
10. Notion과 Google Calendar에는 아직 저장하지 않습니다. 저장은 사용자가 UI에서 승인 버튼을 누른 뒤에만 실행됩니다.

응답 형식:
반드시 아래 JSON 형식만 출력하세요.

{{
  "answer": "번호가 붙은 한국어 분석 결과",
  "proposed_tasks": [
    {{
      "title": "구체적인 할 일 제목",
      "status": "To do",
      "priority": "High 또는 Medium 또는 Low",
      "source": "GitHub 근거 출처",
      "due": "YYYY-MM-DD 또는 빈 문자열",
      "reason": "GitHub 근거와 이 담당자에게 배정한 이유",
      "assignee": "담당자 GitHub ID 또는 이름",
      "assignee_github": "담당자 GitHub ID"
    }}
  ]
}}

answer는 긴 한 문단으로 이어 쓰지 말고, 내용별로 1., 2., 3.처럼 번호를 매겨 읽기 쉽게 작성하세요.
"""


def _extract_warnings(raw: str, label: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict) and parsed.get("error"):
        code = parsed.get("error")
        if code in {401, 403}:
            return [f"{label} 권한 필요"]
        return [f"{label} 조회 오류 {code}"]
    return []


def _is_empty_list(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list) and len(parsed) == 0


def _extract_members(*raw_payloads: str) -> list[dict[str, str]]:
    by_login: dict[str, dict[str, str]] = {}
    for raw in raw_payloads:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if parsed.get("error"):
                continue
            items = parsed.get("items", [])
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            login = str(item.get("login") or "").strip()
            if not login:
                user = item.get("user")
                if isinstance(user, dict):
                    login = str(user.get("login") or "").strip()
            if not login:
                continue
            current = by_login.setdefault(
                login.lower(),
                {"github_id": login, "name": str(item.get("name") or login), "source": "github"},
            )
            if item.get("contributions") is not None:
                current["contributions"] = str(item.get("contributions"))
            if item.get("role_name"):
                current["role"] = str(item.get("role_name"))
    return sorted(by_login.values(), key=lambda member: member["github_id"].lower())


def _parse_task_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"answer": raw, "proposed_tasks": []}
    return parsed if isinstance(parsed, dict) else {"answer": raw, "proposed_tasks": []}


def _normalize_tasks(
    tasks: Any,
    *,
    project_deadline: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(tasks, list):
        return []
    normalized: list[dict[str, Any]] = []
    allowed_priorities = {"High", "Medium", "Low"}
    for task in tasks[:5]:
        if not isinstance(task, dict):
            continue
        title = str(task.get("title", "")).strip()
        if not title:
            continue
        priority = str(task.get("priority", "Medium")).strip()
        if priority not in allowed_priorities:
            priority = "Medium"
        due = str(task.get("due") or "").strip()
        if project_deadline and (not due or due > project_deadline):
            due = project_deadline
        normalized.append(
            {
                "title": title,
                "status": str(task.get("status") or "To do"),
                "priority": priority,
                "source": str(task.get("source") or "GitHub analysis"),
                "due": due,
                "reason": str(task.get("reason") or ""),
                "assignee": str(task.get("assignee") or ""),
                "assignee_github": str(task.get("assignee_github") or ""),
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# notion domain
# ---------------------------------------------------------------------------

NOTION_DOMAIN_SYSTEM_PROMPT = """
You create tasks in a connected Notion database using the create_notion_task
tool. Read the question, extract concrete action items, and call
create_notion_task once per task with a short action-oriented title,
priority, source, and a brief evidence-based reason. Do not dump raw JSON.
If there is nothing concrete to save, say so without calling any tool.

Answer in Korean unless the user asks for another language.
""".strip()


def build_notion_domain_agent() -> DomainAgent:
    """Wraps the Notion task-creation tool as a free-text delegate."""

    async def run(question: str) -> str:
        tool_client = NotionToolClient()
        if not tool_client.enabled:
            return "Notion 연동이 설정되어 있지 않습니다 (NOTION_API_KEY / NOTION_DATABASE_ID 필요)."

        agent = GitHubToolChoosingAgent(
            system_prompt=NOTION_DOMAIN_SYSTEM_PROMPT,
            max_tool_rounds=4,
        )
        async with tool_client as tools:
            result = await agent.run(question, tools)
        return result.answer

    return DomainAgent(
        name="notion",
        description=(
            "Creates tasks in the connected Notion database. Use only when "
            "the user explicitly asks to save/record/add tasks, or Notion "
            "auto-save is enabled and there are concrete action items to save."
        ),
        run=run,
    )


async def create_notion_tasks(tasks: list[Any]) -> dict[str, Any]:
    """Bulk-creates already-approved, already-structured tasks (no LLM)."""

    notion = NotionToolClient()
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with notion:
        for task in _normalize_tasks(tasks):
            selected_tools.append({"tool": "create_notion_task", "arguments": task})
            raw = await notion.call_tool("create_notion_task", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}


# ---------------------------------------------------------------------------
# calendar domain
# ---------------------------------------------------------------------------

CALENDAR_DOMAIN_SYSTEM_PROMPT = """
You create Google Calendar events for tasks using the create_calendar_event
tool. Read the question, extract concrete tasks with a due date, and call
create_calendar_event once per task. A due date (YYYY-MM-DD) is required —
if none is given or implied, ask for one instead of guessing.

Answer in Korean unless the user asks for another language.
""".strip()


def build_calendar_domain_agent() -> DomainAgent:
    """Wraps the Google Calendar event-creation tool as a free-text delegate."""

    async def run(question: str) -> str:
        tool_client = GoogleCalendarToolClient()
        if not tool_client.enabled:
            return "Google Calendar 연동이 설정되어 있지 않습니다 (GOOGLE_CALENDAR_ID / 서비스 계정 필요)."

        agent = GitHubToolChoosingAgent(
            system_prompt=CALENDAR_DOMAIN_SYSTEM_PROMPT,
            max_tool_rounds=4,
        )
        async with tool_client as tools:
            result = await agent.run(question, tools)
        return result.answer

    return DomainAgent(
        name="calendar",
        description=(
            "Creates Google Calendar events for tasks with a due date. Use "
            "only when the user explicitly asks to add something to the "
            "calendar and a due date is known."
        ),
        run=run,
    )


async def create_calendar_events(tasks: list[Any]) -> dict[str, Any]:
    """Bulk-creates already-approved, already-structured calendar events (no LLM)."""

    calendar = GoogleCalendarToolClient()
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with calendar:
        for task in _normalize_tasks(tasks):
            selected_tools.append({"tool": "create_calendar_event", "arguments": task})
            raw = await calendar.call_tool("create_calendar_event", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}
