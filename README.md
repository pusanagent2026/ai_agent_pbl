# GitHub AI Tool Agent

사용자의 질문을 보고 AI가 필요한 GitHub, Notion, Google Calendar tool을 스스로 선택해 호출하는 예제 프로젝트입니다.

## 주요 기능

- GitHub 저장소 기록을 읽어 프로젝트 상태를 분석합니다.
- 저장소의 팀원 GitHub ID를 contributors, collaborators, organization members 정보에서 자동으로 읽어옵니다.
- "팀원이 누구야?", "누구누구 있어?", "참여자 알려줘"처럼 의미가 같은 질문에 팀원 목록을 답합니다.
- "할 일을 팀원들에게 배분해줘", "각자 뭐 하면 돼?", "오늘 할 일 나눠줘"처럼 의미가 같은 요청에 작업을 분배합니다.
- 최근 커밋, 이슈, PR 기록을 바탕으로 팀원별 작업 성향을 추정하고 비슷한 작업을 우선 배정합니다.
- 사용자가 프로젝트 전체 마감일을 입력하면, AI가 그 기한 안에서 각 작업의 마감일을 자동 생성합니다.
- AI가 제안한 작업은 바로 저장되지 않고, UI에서 사용자가 승인한 항목만 Notion 또는 Google Calendar에 등록됩니다.

## GitHub에서 읽어오는 정보

```text
get_repository             저장소 이름, 설명, 기본 브랜치, 최근 push 시각, 열린 이슈 수
list_issues                열린/닫힌 이슈 목록과 제목, 본문, 상태, 작성자
list_pull_requests         열린/닫힌 PR 목록과 제목, 상태, 작성자, 병합 여부
list_commits               최근 커밋 메시지, 작성자, 작성 시각
list_contributors          커밋 기반 contributor GitHub ID와 기여 수
list_collaborators         저장소 collaborator GitHub ID와 role
list_organization_members  조직 멤버 GitHub ID
list_workflow_runs         GitHub Actions 실행 상태와 결론
```

## Setup

```powershell
cd "C:\ai_agent_pbl2"
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

프로젝트 루트에 `.env` 파일을 만들고 값을 채웁니다. `.env`에는 실제 API key가 들어가므로 GitHub에 올리면 안 됩니다.

```env
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini

GITHUB_TOKEN=your-github-token
GITHUB_OWNER=pusanagent2026
GITHUB_REPO=ai_agent_pbl
GITHUB_TOOL_BACKEND=github-api
```

## Notion 설정

```env
NOTION_API_KEY=your-notion-integration-secret
NOTION_DATABASE_ID=your-notion-database-id

NOTION_TITLE_PROPERTY=이름
NOTION_STATUS_PROPERTY=상태
NOTION_PRIORITY_PROPERTY=우선순위
NOTION_SOURCE_PROPERTY=출처
NOTION_DUE_PROPERTY=마감일
NOTION_REASON_PROPERTY=이유
NOTION_ASSIGNEE_PROPERTY=담당자
```

## Google Calendar API 설정

기능 구현과 테스트는 안정적인 Google Calendar API 방식으로 진행합니다.

1. Google Cloud Console에서 Calendar API를 사용 설정합니다.
2. 서비스 계정을 만들고 JSON key 파일을 내려받습니다.
3. Google Calendar에서 사용할 캘린더를 서비스 계정 이메일에 공유합니다.
4. 서비스 계정 권한은 이벤트 생성이 가능하도록 설정합니다.
5. `.env`에 아래 값을 추가합니다.

```env
GOOGLE_CALENDAR_BACKEND=api
GOOGLE_CALENDAR_ID=your-calendar-id
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure-path\google-service-account.json
GOOGLE_CALENDAR_TIMEZONE=Asia/Seoul
```

`GOOGLE_CALENDAR_ID`는 Google Calendar의 `설정 및 공유` → `캘린더 통합` → `캘린더 ID`에서 확인합니다.

`GOOGLE_SERVICE_ACCOUNT_FILE`은 Google Cloud 서비스 계정에서 내려받은 JSON key 파일의 실제 경로입니다.

Calendar 등록은 작업의 `due` 날짜를 all-day 이벤트로 생성합니다. `due`는 사용자가 입력한 프로젝트 전체 마감일 안에서 AI가 자동 생성합니다.

## Calendar MCP 확장 방향

Google Calendar remote MCP endpoint는 아래처럼 설정할 수 있지만, 실제 사용에는 Google OAuth token flow가 추가로 필요합니다. 현재 구현 테스트는 API backend를 사용합니다.

```env
GOOGLE_CALENDAR_BACKEND=mcp
CALENDAR_MCP_URL=https://calendarmcp.googleapis.com/mcp/v1
CALENDAR_MCP_AUTH_TOKEN=
CALENDAR_MCP_CREATE_EVENT_TOOL=
GOOGLE_CALENDAR_ID=your-calendar-id
GOOGLE_CALENDAR_TIMEZONE=Asia/Seoul
```

## UI 실행

```powershell
cd "C:\ai_agent_pbl2"
.venv\Scripts\activate
python -m github_ai_agent.web
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8787
```

UI는 아래 흐름으로 동작합니다.

```text
1. 프로젝트 전체 마감일 입력
2. Analyze GitHub
3. 제안된 작업 확인 및 체크
4. Notion 등록 또는 Calendar 등록 승인
```

입력창에서는 `Enter`로 바로 분석을 실행하고, 줄바꿈은 `Shift + Enter`로 입력합니다.

## 구조

```text
src/github_ai_agent/
  agent.py                  # LLM tool-selection loop
  cli.py                    # terminal interface
  web.py                    # web UI server and approval flow
  github_api_client.py      # GitHub REST API tool backend
  notion_client.py          # Notion task creation tool backend
  google_calendar_client.py # Google Calendar event creation tool backend
  tool_client.py            # combines multiple tool clients
  mcp_client.py             # MCP backend for later
  prompts.py                # system prompt
```

## README 갱신 원칙

README는 단순 코드 수정마다 갱신하지 않고, 사용자에게 보이는 기능, 실행 방법, 설정값, 외부 연동, 권한 요구사항이 바뀔 때 갱신합니다.
