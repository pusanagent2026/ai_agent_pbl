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
Contents: Read-only
Issues: Read-only
Pull requests: Read-only
Actions: Read-only
Metadata: Read-only
Administration: Read-only       # collaborators 조회가 필요할 때
```

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

`GITHUB_OWNER`/`GITHUB_REPO`/`GITHUB_APP_INSTALLATION_ID`는 CLI(`github-ai-agent`)와 GitHub App 자체 인증(`GITHUB_APP_ID`, private key)에 쓰이는 서버 전역 기본값입니다. 웹 UI는 브라우저 세션이 GitHub 로그인이나 앱 설치로 직접 연결한 저장소만 사용하며, 이 env 기본값으로 조용히 대체되지 않습니다 — 로그아웃하면 세션의 저장소 연결도 함께 사라집니다.

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
GOOGLE_CALENDAR_BACKEND=mcp
CALENDAR_MCP_URL=https://calendarmcp.googleapis.com/mcp/v1

GOOGLE_OAUTH_CLIENT_ID=your-google-oauth-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-google-oauth-client-secret
GOOGLE_CALENDAR_ID=your-calendar-id
GOOGLE_CALENDAR_TIMEZONE=Asia/Seoul
```

Calendar 등록은 작업의 `due` 날짜를 all-day 이벤트로 생성합니다. `due`는 사용자가 입력한 프로젝트 전체 마감일 안에서 AI가 자동 생성합니다.

## 웹 UI 세션 저장소 설정

웹 UI의 브라우저 세션(GitHub/Google 로그인 토큰, 앱 설치 installation_id)은 SQLite(`session_store_schema.sql`)에 저장되며, 토큰 컬럼은 Fernet으로 암호화합니다.

```env
SESSION_ENC_KEY=your-fernet-key
SESSION_DB_PATH=sessions.db
```

`SESSION_ENC_KEY`는 필수이며, 없으면 서버가 세션을 저장하려는 시점에 즉시 에러를 냅니다. 아래 명령으로 생성합니다.

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`SESSION_DB_PATH`는 선택 항목이며 기본값은 프로젝트 루트의 `sessions.db`입니다.

## 실행

Google Calendar는 사용자에게 API 키나 토큰을 직접 입력시키지 않습니다. 서비스 운영자가 Google OAuth Client ID/Secret을 서버 `.env`에 설정하고, 사용자는 UI의 `Google Calendar 연결` 버튼으로 로그인/권한 승인을 진행합니다.

Google OAuth 승인된 리디렉션 URI에는 아래 주소를 등록합니다.

```text
http://127.0.0.1:8787/auth/google/callback
```

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
```

`cli.py`와 `web.py` 둘 다 도메인 tool client(GitHub/Notion/Calendar)를 직접 조합해서 `GitHubToolChoosingAgent`를 호출합니다. 별도 라우팅 계층(오케스트레이터) 없이, 어떤 tool을 쓸지는 `CombinedToolClient`에 넘긴 tool 목록과 (web.py의 경우) UI에서 사용자가 누른 승인 버튼으로 결정됩니다.

## README 갱신 원칙

README는 단순 코드 수정마다 갱신하지 않고, 사용자에게 보이는 기능, 실행 방법, 설정값, 외부 연동, 권한 요구사항이 바뀔 때 갱신합니다.
