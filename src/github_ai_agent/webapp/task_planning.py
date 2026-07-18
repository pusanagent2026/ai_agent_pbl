from __future__ import annotations

import json
from datetime import date
from typing import Any

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient


class _NoToolsClient:
    async def list_tools(self) -> list[Any]:
        return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        raise ValueError(f"대화 응답에서는 도구를 호출할 수 없습니다: {name}")


def build_harness_analysis_prompt(question: str, project_deadline: str) -> str:
    today = date.today().isoformat()
    if project_deadline:
        deadline_instruction = (
            f"프로젝트 전체 마감일은 {project_deadline}입니다. 작업별 마감일은 이 날짜를 "
            "넘지 않도록 우선순위와 작업량을 고려해 분산하세요."
        )
    else:
        deadline_instruction = (
            "프로젝트 전체 마감일이 입력되지 않았습니다. 임의의 마감일을 만들지 말고 "
            "작업의 due는 빈 문자열로 두세요."
        )
    return f"""
오늘 날짜: {today}
{deadline_instruction}

사용자 요청:
{question}

질문에 직접 필요한 GitHub 도구만 선택해 사실을 확인하세요. 팀원이나 작업 분배 요청이면
contributors 또는 collaborators, 최근 커밋, 열린 이슈와 PR을 필요한 범위에서 확인하세요.
GitHub 조회는 읽기 전용이므로 범위나 진행 여부를 사용자에게 되묻지 마세요. 질문에 맞는 최소 범위를
스스로 선택해 이번 응답에서 바로 도구를 호출하고 결과를 제시하세요. 팀원 질문은 collaborators 또는
contributors와 최근 commit/PR 작성자를, 막힌 문제 질문은 blocker/high-priority 열린 issue, 병합을
막는 PR 상태, 최근 실패 workflow를 기본 범위로 사용하세요.
권한 때문에 collaborators 조회가 실패하면 그 사실을 밝히고 확인 가능한 contributor와
최근 활동만 근거로 사용하세요. 근거가 부족한 담당자 배정은 추정이라고 표시하세요.

사용자가 팀 목록만 요청했다면 proposed_tasks는 빈 배열로 두세요. 작업 분배 요청이면
구체적인 작업을 최대 5개 제안하고 priority, reason, assignee와 GitHub 근거를 포함하세요.
작업을 제안했다면 answer 본문에도 각 작업의 제목, 우선순위, 담당자와 핵심 근거를 빠뜨리지 말고
읽기 쉬운 목록으로 보여주세요. proposed_tasks에만 넣고 answer에서 생략하지 마세요.
열린 이슈나 PR이 없더라도 확인하지 않은 일을 사실처럼 만들지 마세요.
마감일이 입력되지 않았다는 사실은 필요할 때 한 문장으로만 안내하고, "due를 빈 문자열로 둔다" 같은
내부 데이터 표현을 사용자 답변에 노출하지 마세요.
Notion 저장과 Calendar 등록은 이 분석 단계에서 실행하지 마세요.

응답은 아래 JSON 객체 하나만 출력하세요. answer는 고정 섹션이나 기계적인 번호 목록을
강제하지 말고, 핵심 결과와 근거 및 다음 행동을 자연스러운 한국어로 작성하세요.
사용자가 링크를 요청하지 않았다면 GitHub URL을 출력하지 마세요. 커밋 SHA가 필요하면 앞 7자리만
표시하고, 원시 ISO 시간 대신 YYYY-MM-DD 형식의 날짜를 사용하세요.
팀원·활동 조회 답변은 짧은 결론 다음에 '구성원', '최근 활동', 'Agent 판단'처럼 내용에 맞는 짧은
제목으로 나누세요. 구성원은 한 사람당 한 줄, 최근 활동은 핵심 5건 이내로 제한하고, 같은 근거와
조회 방법을 본문·참고·제안에서 반복하지 마세요. 추가 조회 제안은 마지막 한 문장 이내로 작성하세요.

{{
  "answer": "자연스러운 한국어 답변",
  "proposed_tasks": [
    {{
      "title": "구체적인 작업 제목",
      "status": "To do",
      "priority": "High 또는 Medium 또는 Low",
      "source": "확인한 GitHub 근거",
      "due": "YYYY-MM-DD 또는 빈 문자열",
      "reason": "배정 근거와 필요한 이유",
      "assignee": "담당자 이름 또는 GitHub ID",
      "assignee_github": "담당자 GitHub ID"
    }}
  ]
}}
""".strip()


async def analyze_tasks(
    question: str,
    *,
    project_deadline: str = "",
    owner: str = "",
    repo: str = "",
    installation_id: str = "",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    agent = GitHubToolChoosingAgent(owner=owner or None, repo=repo or None)
    analysis_prompt = build_harness_analysis_prompt(question, project_deadline)
    decision = agent.harness.classify_intent(question)
    if not decision.requires_project_context:
        result = await agent.run(
            question,
            _NoToolsClient(),
            intent_input=question,
            history=history,
        )
    else:
        async with GitHubMcpClient(installation_id=installation_id or None) as github_tools:
            result = await agent.run(
                analysis_prompt,
                github_tools,
                intent_input=question,
                history=history,
            )

    parsed = parse_task_json(result.answer)
    answer = clean_answer_for_chat(parsed.get("answer") or result.answer)
    return {
        "answer": answer,
        "proposed_tasks": normalize_tasks(
            parsed.get("proposed_tasks", []),
            project_deadline=project_deadline,
        ),
        "selected_tools": [
            *(
                [{"tool": "github_backend", "arguments": {"backend": "mcp"}}]
                if decision.requires_project_context
                else []
            ),
            *result.selected_tools,
        ],
        "agent_intent": result.intent,
        "blocked_actions": result.blocked_actions,
        "tool_failures": result.failures,
    }


def clean_answer_for_chat(answer: str) -> str:
    """Remove noisy raw links that make the dashboard chat hard to scan."""
    import re

    cleaned = re.sub(
        r"\s*\((?:커밋\s*)?URL\s*:\s*https?://[^)\s]+\)",
        "",
        answer,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"https?://github\.com/\S+", "", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


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
