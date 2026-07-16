from __future__ import annotations

import json
from datetime import date
from typing import Any

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient


async def analyze_tasks(
    question: str,
    *,
    project_deadline: str = "",
    owner: str = "",
    repo: str = "",
    installation_id: str = "",
) -> dict[str, Any]:
    agent = GitHubToolChoosingAgent(owner=owner or None, repo=repo or None)
    async with GitHubMcpClient(installation_id=installation_id or None) as github_tools:
        result = await agent.run(
            build_analysis_prompt(question, project_deadline),
            github_tools,
        )

    parsed = parse_task_json(result.answer)
    return {
        "answer": parsed.get("answer") or result.answer,
        "proposed_tasks": normalize_tasks(
            parsed.get("proposed_tasks", []),
            project_deadline=project_deadline,
        ),
        "selected_tools": [
            {"tool": "github_backend", "arguments": {"backend": "mcp"}},
            *result.selected_tools,
        ],
    }


async def create_notion_tasks(
    tasks: list[Any],
    *,
    notion_token: str = "",
    notion_database_id: str = "",
) -> dict[str, Any]:
    notion = NotionToolClient(token=notion_token or None, database_id=notion_database_id or None)
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with notion:
        for task in normalize_tasks(tasks):
            selected_tools.append({"tool": "create_notion_task", "arguments": task})
            raw = await notion.call_tool("create_notion_task", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}


async def create_notion_report(
    tasks: list[Any],
    *,
    title: str,
    body: str = "",
    review: dict[str, Any] | None = None,
    checklist: bool = False,
    notion_token: str = "",
    notion_page_id: str = "",
) -> dict[str, Any]:
    notion = NotionToolClient(token=notion_token or None, database_id="placeholder")
    normalized_tasks = normalize_tasks(tasks)
    selected_tools = [
        {
            "tool": "create_notion_report_page",
            "arguments": {
                "title": title,
                "parent_page_id": notion_page_id,
                "task_count": len(normalized_tasks),
                "format": "checklist" if checklist else "document",
            },
        }
    ]
    async with notion:
        page = notion.create_report_page(
            parent_page_id=notion_page_id,
            title=title,
            body=body,
            tasks=normalized_tasks,
            review=review or {},
            checklist=checklist,
        )
    return {"created": [page], "selected_tools": selected_tools, "url": page.get("url", "")}


async def create_calendar_events(
    tasks: list[Any],
    *,
    google_access_token: str = "",
) -> dict[str, Any]:
    calendar = GoogleCalendarToolClient(mcp_auth_token=google_access_token or None)
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with calendar:
        for task in normalize_tasks(tasks):
            selected_tools.append({"tool": "create_calendar_event", "arguments": task})
            raw = await calendar.call_tool("create_calendar_event", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                if "error" in raw.lower() or "forbidden" in raw.lower():
                    raise ValueError(raw)
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}


def build_analysis_prompt(
    question: str,
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
MCP backend에서는 사용 가능한 GitHub MCP tool 목록을 보고 필요한 tool을 직접 선택해서 호출하세요.

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

반드시 아래 JSON 형식만 출력하세요. JSON 바깥에는 어떤 설명도 쓰지 마세요.

{{
  "answer": "현재 상태\n1. 확인한 GitHub 근거...\n\nAgent의 판단\n1. 판단 내용...\n\n실행 계획\n1. [High / 예상 2시간] 작업명 - 근거...\n\n실행한 작업\n1. 실제로 확인한 도구와 결과...\n\n사용자 승인이 필요한 작업\n1. Notion 저장, Calendar 등록 등 승인 필요한 작업...\n\n다음 권장 행동\n1. 바로 할 일...",
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

answer 작성 규칙:
1. answer는 반드시 위 예시처럼 "현재 상태", "Agent의 판단", "실행 계획", "실행한 작업", "사용자 승인이 필요한 작업", "다음 권장 행동" 섹션을 모두 포함합니다.
2. 각 섹션 제목 앞뒤에는 줄바꿈을 넣습니다.
3. 한 문단 안에 1. 2. 3.을 이어 쓰지 않습니다.
4. 각 번호 항목은 반드시 새 줄에서 시작합니다.
5. 실행 계획의 작업 항목에는 우선순위, 예상 시간, 근거를 같이 씁니다.
6. 실제로 호출하지 않은 도구나 확인하지 않은 정보는 실행한 작업에 쓰지 않습니다.
7. Notion 저장이나 Calendar 등록은 승인 전에는 실행하지 않았다고 명확히 씁니다.
"""


def parse_task_json(raw: str) -> dict[str, Any]:
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


def normalize_tasks(
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
