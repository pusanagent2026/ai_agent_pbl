# GitHub AI Tool Agent

사용자 질문을 보고 AI가 적절한 GitHub tool을 스스로 선택해 호출하는 예제입니다.

현재는 Docker 없이 `github-api` backend를 기본으로 사용합니다. 나중에 Docker 또는 GitHub MCP 서버를 붙이면 `mcp` backend로 바꿀 수 있습니다.

## Setup

```powershell
cd "C:\Users\hyunj\Documents\Codex\2026-07-08\github-ai-tool-github-mcp-tool\outputs\github-ai-mcp-agent"
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

`.env`에는 아래 값을 넣습니다.

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

NOTION_TITLE_PROPERTY=Name
NOTION_STATUS_PROPERTY=Status
NOTION_PRIORITY_PROPERTY=Priority
NOTION_SOURCE_PROPERTY=Source
NOTION_DUE_PROPERTY=Due
NOTION_REASON_PROPERTY=Reason
```

Notion database에는 위 property들이 있어야 합니다. 이름이 다르면 `.env`의 property 이름만 바꾸면 됩니다.

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

패키지를 이미 설치했다면, UI 파일 추가 후 한 번 더 설치합니다.

```powershell
pip install -e .
github-ai-agent-ui
```

또는 모듈로 직접 실행할 수 있습니다.

```powershell
python -m github_ai_agent.web
```

브라우저에서 엽니다.

```text
http://127.0.0.1:8787
```

## 핵심 구조

```text
src/github_ai_agent/
  agent.py             # LLM tool-selection loop
  cli.py               # terminal interface
  web.py               # web UI server
  github_api_client.py # GitHub REST API tool backend
  mcp_client.py        # MCP backend for later
  prompts.py           # system prompt
```

## What To Check

UI에서 질문을 입력하면 오른쪽 `Selected Tools` 영역에 AI가 고른 tool이 표시됩니다. 예를 들어:

```text
list_issues
list_pull_requests
list_commits
list_workflow_runs
create_notion_task
```

이 부분이 이 프로젝트의 핵심입니다. 질문마다 AI가 필요한 tool을 다르게 선택하고, 그 결과를 바탕으로 답변합니다.
