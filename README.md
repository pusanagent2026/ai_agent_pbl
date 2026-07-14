# GitHub AI Tool Agent

사용자 질문을 보고 AI가 적절한 GitHub/Notion tool을 스스로 선택해 호출하는 예제입니다.

현재 기본 backend는 Docker가 필요 없는 `github-api`입니다. 나중에 Docker 또는 GitHub MCP 서버를 붙이면 `mcp` backend로 바꿀 수 있습니다.

## Setup

```powershell
cd "C:\Users\hyunj\Documents\Codex\2026-07-08\github-ai-tool-github-mcp-tool\outputs\github-ai-mcp-agent"
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채웁니다. `.env`에는 실제 API key가 들어가므로 GitHub에 올리지 않습니다.

```env
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini

GITHUB_TOKEN=your-github-token
GITHUB_OWNER=your-github-id-or-org
GITHUB_REPO=your-repo
GITHUB_TOOL_BACKEND=github-api
```

Notion에 할 일을 저장하려면 아래 값도 추가합니다.

```env
NOTION_API_KEY=your-notion-integration-secret
NOTION_DATABASE_ID=your-notion-database-id

NOTION_TITLE_PROPERTY=이름
NOTION_STATUS_PROPERTY=상태
NOTION_PRIORITY_PROPERTY=우선순위
NOTION_SOURCE_PROPERTY=출처
NOTION_DUE_PROPERTY=마감일
NOTION_REASON_PROPERTY=이유
```

Notion database 컬럼 타입은 아래처럼 맞춥니다.

```text
이름     - Title
상태     - Select
우선순위 - Select
출처     - Text
마감일   - Date
이유     - Text
```

## CLI 실행

```powershell
python -m github_ai_agent.cli "프로젝트 상태 분석해줘" --debug
python -m github_ai_agent.cli "오늘 뭐부터 해야 돼?" --debug
python -m github_ai_agent.cli "최근 변경사항 요약해줘" --debug
```

Notion에 할 일을 자동 기록하려면:

```powershell
python -m github_ai_agent.cli "오늘 뭐부터 해야 돼?" --debug --save-to-notion
```

## UI 실행

```powershell
python -m github_ai_agent.web
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8787
```

UI에서 `Save tasks to Notion`을 켜면 AI가 구체적인 할 일을 `create_notion_task` tool로 저장할 수 있습니다.

## 구조

```text
src/github_ai_agent/
  agent.py             # 범용 LLM tool-selection 루프 (system_prompt 주입 가능)
  cli.py               # terminal interface
  web.py               # web UI server
  github_api_client.py # GitHub REST API tool backend
  notion_client.py     # Notion task creation tool backend
  tool_client.py       # combines multiple tool clients
  mcp_client.py        # MCP backend for later
  prompts.py           # GitHub 도메인 system prompt

  orchestrator/
    agent.py           # OrchestratorAgent — 질문을 보고 도메인에 위임
    domains.py         # 도메인 등록 지점 (build_<domain>_domain_agent)
    prompts.py         # 오케스트레이터 system prompt
```

`cli.py`/`web.py`는 이제 도메인 agent를 직접 부르지 않고 `OrchestratorAgent`를 거칩니다.

### 새 도메인(코드 리뷰어, 회의록, 캘린더 등) 추가하는 법

1. 자기 도메인의 tool/agent 로직은 자기 모듈에서 구현 (`orchestrator/domains.py`의 기존 항목은 건드리지 않음)
2. `build_<domain>_domain_agent() -> DomainAgent`를 하나 만들어서 `orchestrator/domains.py`에 추가
   - `DomainAgent`는 `name`, `description`, `async def run(question: str) -> str`만 있으면 됨
3. `cli.py`/`web.py`에서 `OrchestratorAgent(domains=[...])` 리스트에 한 줄 추가

오케스트레이터는 각 도메인의 내부 tool/프롬프트/backend를 몰라도 되고, 도메인도 오케스트레이터 내부를 몰라도 됩니다 — `DomainAgent.run(question)` 하나가 유일한 접점입니다.

## 핵심 확인 포인트

질문마다 AI가 필요한 tool을 다르게 선택합니다.

```text
list_issues
list_pull_requests
list_commits
list_workflow_runs
create_notion_task
```

이 프로젝트의 핵심은 GitHub 데이터를 가져오는 것 자체가 아니라, AI가 질문 의도를 보고 필요한 tool을 선택한 뒤 결과를 바탕으로 답변하거나 Notion에 기록하는 구조입니다.
