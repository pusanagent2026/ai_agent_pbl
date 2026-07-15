# GitHub AI Tool Agent

사용자의 질문을 보고 AI가 필요한 GitHub MCP, Notion, Google Calendar tool을 스스로 선택해 호출하는 예제 프로젝트입니다.

## 주요 기능

- GitHub MCP tool을 통해 저장소 기록을 읽어 프로젝트 상태를 분석합니다.
- 저장소의 팀원 GitHub ID를 contributors, collaborators, organization members 정보에서 자동으로 읽어옵니다.
- "팀원이 누구야?", "누구누구 있어?", "참여자 알려줘"처럼 의미가 같은 질문에 팀원 목록을 답합니다.
- "할 일을 팀원들에게 배분해줘", "각자 뭐 하면 돼?", "오늘 할 일 나눠줘"처럼 의미가 같은 요청에 작업을 분배합니다.
- 최근 커밋, 이슈, PR 기록을 바탕으로 팀원별 작업 성향을 추정하고 비슷한 작업을 우선 배정합니다.
- 사용자가 프로젝트 전체 마감일을 입력하면, AI가 그 기한 안에서 각 작업의 마감일을 자동 생성합니다.
- AI가 제안한 작업은 바로 저장되지 않고, UI에서 사용자가 승인한 항목만 Notion 또는 Google Calendar에 등록됩니다.

## GitHub MCP 인증

GitHub 데이터는 직접 REST API backend로 읽지 않고, `GITHUB_MCP_COMMAND`로 실행되는 GitHub MCP 서버를 통해서만 읽습니다.

서비스형 구조에서는 사용자가 직접 token을 입력하지 않도록 GitHub App installation token을 사용합니다.

### GitHub App 만들기

1. GitHub에서 조직 또는 계정의 `Settings`로 이동합니다.
2. `Developer settings` → `GitHub Apps` → `New GitHub App`을 선택합니다.
3. App 이름을 입력합니다.
4. `Homepage URL`은 로컬 테스트라면 `http://127.0.0.1:8787`로 둡니다.
5. Webhook은 지금 단계에서는 끄거나 비워도 됩니다.
6. Repository permissions를 설정합니다.

권장 권한:

```text
Contents: Read and write        # 코드 조회 + README 자동 갱신 PR 생성에 필요
Issues: Read-only
Pull requests: Read and write   # README 자동 갱신 PR 생성에 필요
Actions: Read-only
Metadata: Read-only
Administration: Read-only       # collaborators 조회가 필요할 때
```

기존에 설치된 App의 권한을 바꾼 경우, GitHub이 자동으로 반영하지 않습니다. `Install App` 화면에서 설치를 다시 열어 바뀐 권한을 조직/계정 관리자가 재승인해야 새 권한이 실제로 적용됩니다.

Organization members를 읽어야 한다면 Organization permissions에서 `Members: Read-only`도 추가합니다.

7. GitHub App을 생성합니다.
8. App 상세 화면에서 `App ID`를 복사합니다.
9. `Private keys` 섹션에서 private key를 생성하고 `.pem` 파일을 다운로드합니다.
10. `Install App`에서 `pusanagent2026/ai_agent_pbl` 저장소에 설치합니다.
11. 설치 후 URL의 `installation_id`를 확인합니다.

설치 URL 예시:

```text
https://github.com/organizations/pusanagent2026/settings/installations/12345678
```

여기서 `12345678`이 `GITHUB_APP_INSTALLATION_ID`입니다.

### GitHub MCP Docker 설정

Docker Desktop이 설치되어 있으면 `.env`에 아래처럼 설정합니다.

```env
GITHUB_OWNER=pusanagent2026
GITHUB_REPO=ai_agent_pbl

GITHUB_APP_ID=your-github-app-id
GITHUB_APP_INSTALLATION_ID=your-installation-id
GITHUB_APP_PRIVATE_KEY_FILE=C:\secure-path\your-github-app.private-key.pem

GITHUB_MCP_COMMAND=C:\Progra~1\Docker\Docker\resources\bin\docker.exe run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server
```

앱은 실행 시 `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, private key로 GitHub App installation token을 자동 발급하고, 그 값을 `GITHUB_PERSONAL_ACCESS_TOKEN`으로 MCP 서버에 주입합니다.

따라서 서비스 사용자는 GitHub PAT를 직접 입력하지 않아도 됩니다.

## OpenAI 설정

```env
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini
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

```env
GOOGLE_CALENDAR_BACKEND=api
GOOGLE_CALENDAR_ID=your-calendar-id
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure-path\google-service-account.json
GOOGLE_CALENDAR_TIMEZONE=Asia/Seoul
```

Calendar 등록은 작업의 `due` 날짜를 all-day 이벤트로 생성합니다. `due`는 사용자가 입력한 프로젝트 전체 마감일 안에서 AI가 자동 생성합니다.

## 실행

```powershell
cd "C:\ai_agent_pbl2"
.venv\Scripts\activate
pip install -e .
python -m github_ai_agent.web
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8787
```

UI 흐름:

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
  agent.py                  # 범용 LLM tool-selection 루프 (system_prompt 주입 가능)
  cli.py                    # terminal interface
  web.py                    # web UI server and approval flow
  mcp_client.py             # GitHub MCP backend
  github_app_auth.py        # GitHub App installation token provider
  notion_client.py          # Notion task creation tool backend
  google_calendar_client.py # Google Calendar event creation tool backend
  tool_client.py            # combines multiple tool clients
  mcp_client.py             # MCP backend for later
  prompts.py                # GitHub 도메인 system prompt
  code_review.py            # 코드 리뷰 탭 도메인 로직
  readme_review.py          # README 갱신 탭 도메인 로직 (분석 + PR 생성)
  readme_updater.py         # README 갱신 여부 판단/재작성 LLM 로직 (scripts/update_readme.py와 공유)

  orchestrator/
    agent.py                # OrchestratorAgent — 질문을 보고 도메인에 위임
    domains.py               # 도메인 로직 (build_<domain>_domain_agent, task 분석/승인 워크플로)
    prompts.py               # 오케스트레이터 system prompt
```

`cli.py`는 도메인 agent를 직접 부르지 않고 `OrchestratorAgent`를 거쳐 github/notion 도메인에 위임합니다. `web.py`의 승인 플로우(작업 제안 → 승인 → Notion/Calendar 등록)는 구조화된 JSON을 다뤄야 해서 `orchestrator/domains.py`가 제공하는 `analyze_tasks`/`create_notion_tasks`/`create_calendar_events` 함수를 직접 호출합니다.

### 새 도메인(코드 리뷰어, 회의록 등) 추가하는 법

1. 자기 도메인의 tool/agent 로직은 자기 모듈에서 구현 (`orchestrator/domains.py`의 기존 항목은 건드리지 않음)
2. `build_<domain>_domain_agent() -> DomainAgent`를 하나 만들어서 `orchestrator/domains.py`에 추가
   - `DomainAgent`는 `name`, `description`, `async def run(question: str) -> str`만 있으면 됨
3. `cli.py`에서 `OrchestratorAgent(domains=[...])` 리스트에 한 줄 추가
   - 승인 플로우처럼 구조화된 결과(JSON)가 필요하면 `DomainAgent` 대신 `analyze_tasks`류의 별도 함수로 만들어 `web.py`에서 직접 호출

오케스트레이터는 각 도메인의 내부 tool/프롬프트/backend를 몰라도 되고, 도메인도 오케스트레이터 내부를 몰라도 됩니다 — `DomainAgent.run(question)` 하나가 유일한 접점입니다.

## README 갱신 원칙

README는 단순 코드 수정마다 갱신하지 않고, 사용자에게 보이는 기능, 실행 방법, 설정값, 외부 연동, 권한 요구사항이 바뀔 때 갱신합니다.

## README 자동 업데이트 봇 설정

`main`에 push되면 `.github/workflows/readme-autoupdate.yml`이 변경 diff를 분석해 위 원칙에 해당하는 변경인지 판단하고, 필요한 경우에만 새 브랜치(`docs/auto-update-readme-<run number>`)에 커밋한 뒤 PR을 자동으로 엽니다. main에는 직접 커밋하지 않으며, 병합은 항상 사람이 직접 검토 후 진행합니다.

1차(관련성 판단, `gpt-4o-mini`)와 2차(재작성, `gpt-4o`) 모델은 워크플로 파일 상단의 `README_FILTER_MODEL`, `README_REWRITE_MODEL` 환경변수로 바꿀 수 있습니다.

설정 방법:

1. GitHub 저장소 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`에서 `OPENAI_API_KEY`를 등록합니다.
2. `Settings` → `Actions` → `General` → `Workflow permissions`에서 "Read and write permissions"를 켭니다(워크플로가 브랜치를 push하고 PR을 열 수 있어야 합니다).
3. 별도 설정 없이 `main`에 push하면 자동 실행되며, `workflow_dispatch`로 Actions 탭에서 수동 실행도 가능합니다.

웹 UI의 "README 갱신" 탭에서도 같은 판단/재작성 로직을 수동으로 실행할 수 있습니다. 브랜치를 고르고 "Analyze README"를 누르면 그 브랜치의 최신 커밋을 분석하고, "PR 생성"을 누르면 같은 방식으로 새 브랜치 + PR을 만듭니다(이때는 GitHub App의 Contents/Pull requests 쓰기 권한이 필요합니다 — 위 "GitHub App 만들기"의 권장 권한 참고).
