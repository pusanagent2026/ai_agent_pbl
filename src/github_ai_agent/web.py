from __future__ import annotations

import argparse
import asyncio
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from dotenv import load_dotenv

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_api_client import DirectGitHubToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient


HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GitHub AI Agent</title>
  <style>
    :root {
      --bg: #f5f7fa;
      --panel: #fff;
      --line: #d8dee8;
      --text: #172033;
      --muted: #647086;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --warn: #9a3412;
      --code: #edf2f7;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.5;
    }
    .shell { display: grid; grid-template-columns: 320px minmax(0, 1fr); min-height: 100vh; }
    aside { border-right: 1px solid var(--line); background: #eef3f6; padding: 24px; }
    main { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 18px; padding: 24px; }
    h1 { margin: 0 0 10px; font-size: 24px; line-height: 1.2; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }
    .muted { color: var(--muted); }
    .repo, .composer, section, .task {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    .repo { padding: 14px; margin: 18px 0; }
    .repo strong { display: block; overflow-wrap: anywhere; }
    .chips, .task-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .chip, .tag {
      border-radius: 999px;
      padding: 5px 9px;
      background: #fff;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .tag { background: #edf2f7; color: #334155; border: 0; }
    .examples { display: grid; gap: 8px; margin-top: 12px; }
    button {
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
      font: inherit;
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .example { text-align: left; padding: 10px 12px; }
    .example:hover { border-color: var(--accent); }
    textarea {
      width: 100%;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      color: var(--text);
      font: inherit;
    }
    textarea:focus { outline: 2px solid rgba(15, 118, 110, 0.22); border-color: var(--accent); }
    #question { min-height: 110px; }
    .composer { display: grid; gap: 10px; padding: 14px; }
    .actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .primary, .approve {
      min-width: 132px;
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
      padding: 10px 14px;
      font-weight: 700;
    }
    .primary:hover, .approve:hover { background: var(--accent-dark); }
    .results { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr); gap: 18px; min-height: 0; }
    section { padding: 16px; min-width: 0; overflow: auto; }
    .answer { white-space: pre-wrap; word-break: keep-all; overflow-wrap: anywhere; }
    .task { padding: 12px; margin-bottom: 10px; }
    .task-head { display: flex; gap: 10px; align-items: flex-start; justify-content: space-between; margin-bottom: 8px; }
    .task-title { font-weight: 800; overflow-wrap: anywhere; }
    .tool { border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin-bottom: 10px; background: #fbfcfe; }
    pre { margin: 8px 0 0; overflow: auto; border-radius: 8px; background: var(--code); padding: 10px; font-size: 12px; }
    .error { color: var(--warn); font-weight: 700; }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .results { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>GitHub AI Agent</h1>
      <p class="muted">GitHub 기록에서 팀원과 작업 성향을 자동으로 읽고, 승인된 작업만 Notion에 등록합니다.</p>

      <div class="repo">
        <span class="muted">Repository</span>
        <strong id="repo">loading...</strong>
        <div class="chips">
          <span class="chip" id="backend">backend</span>
          <span class="chip" id="model">model</span>
          <span class="chip" id="notion">notion</span>
        </div>
      </div>

      <h2>Examples</h2>
      <div class="examples">
        <button class="example" data-question="우리 팀 누구누구 있어?">우리 팀 누구누구 있어?</button>
        <button class="example" data-question="할 일을 팀원들에게 배분해줘">할 일을 팀원들에게 배분해줘</button>
        <button class="example" data-question="각자 최근에 많이 한 작업 기준으로 역할 나눠줘">작업 성향 기준 역할 분담</button>
        <button class="example" data-question="오늘 뭐부터 하면 좋을까?">오늘 뭐부터 하면 좋을까?</button>
      </div>
    </aside>

    <main>
      <div class="composer">
        <textarea id="question" placeholder="예: 할 일을 팀원들에게 배분해줘"></textarea>
        <div class="actions">
          <span class="muted" id="status">Ready</span>
          <button class="primary" id="analyze">Analyze GitHub</button>
          <button class="approve" id="approve" disabled>Notion에 등록 승인</button>
        </div>
      </div>

      <div class="results">
        <section>
          <h2>AI Analysis</h2>
          <div class="answer" id="answer">아직 분석 결과가 없습니다.</div>
          <h2 style="margin-top:18px;">Selected Tools</h2>
          <div id="tools" class="muted">AI가 GitHub 분석에 사용한 tool이 여기에 표시됩니다.</div>
        </section>
        <section>
          <h2>Proposed Notion Tasks</h2>
          <div id="tasks" class="muted">승인 전에는 Notion에 아무것도 저장되지 않습니다.</div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const question = document.querySelector("#question");
    const analyze = document.querySelector("#analyze");
    const approve = document.querySelector("#approve");
    const answer = document.querySelector("#answer");
    const tools = document.querySelector("#tools");
    const tasks = document.querySelector("#tasks");
    const status = document.querySelector("#status");

    let proposedTasks = [];
    let notionEnabled = false;

    document.querySelectorAll(".example").forEach((button) => {
      button.addEventListener("click", () => {
        question.value = button.dataset.question;
        question.focus();
      });
    });

    async function loadConfig() {
      const response = await fetch("/api/config");
      const config = await response.json();
      document.querySelector("#repo").textContent = `${config.owner}/${config.repo}`;
      document.querySelector("#backend").textContent = config.backend;
      document.querySelector("#model").textContent = config.model;
      notionEnabled = Boolean(config.notion_enabled);
      document.querySelector("#notion").textContent = notionEnabled ? "notion on" : "notion off";
      refreshApproveButton();
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function refreshApproveButton() {
      approve.disabled = !notionEnabled || proposedTasks.length === 0;
    }

    function renderTools(selectedTools) {
      if (!selectedTools.length) {
        tools.innerHTML = "<span class='muted'>선택된 tool이 없습니다.</span>";
        return;
      }
      tools.innerHTML = "";
      selectedTools.forEach((item, index) => {
        const div = document.createElement("div");
        div.className = "tool";
        div.innerHTML = `<strong>${index + 1}. ${escapeHtml(item.tool)}</strong><pre>${escapeHtml(JSON.stringify(item.arguments || {}, null, 2))}</pre>`;
        tools.appendChild(div);
      });
    }

    function renderTasks(items) {
      proposedTasks = items || [];
      if (!proposedTasks.length) {
        tasks.innerHTML = "<span class='muted'>제안된 할 일이 없습니다.</span>";
        refreshApproveButton();
        return;
      }
      tasks.innerHTML = "";
      proposedTasks.forEach((task, index) => {
        const div = document.createElement("div");
        div.className = "task";
        div.innerHTML = `
          <div class="task-head">
            <div class="task-title">${index + 1}. ${escapeHtml(task.title)}</div>
            <label><input type="checkbox" data-index="${index}" checked /> 등록</label>
          </div>
          <div class="task-meta">
            <span class="tag">${escapeHtml(task.priority || "Medium")}</span>
            <span class="tag">${escapeHtml(task.status || "To do")}</span>
            ${task.assignee ? `<span class="tag">담당: ${escapeHtml(task.assignee)}</span>` : ""}
            ${task.assignee_github ? `<span class="tag">@${escapeHtml(task.assignee_github)}</span>` : ""}
            ${task.due ? `<span class="tag">${escapeHtml(task.due)}</span>` : ""}
          </div>
          <div class="muted">${escapeHtml(task.reason || "")}</div>
          <pre>${escapeHtml(JSON.stringify(task, null, 2))}</pre>
        `;
        tasks.appendChild(div);
      });
      refreshApproveButton();
    }

    function selectedTasks() {
      return proposedTasks.filter((_, index) => {
        const checkbox = tasks.querySelector(`input[data-index="${index}"]`);
        return checkbox && checkbox.checked;
      });
    }

    async function analyzeGithub() {
      const text = question.value.trim();
      if (!text) {
        question.focus();
        return;
      }
      analyze.disabled = true;
      approve.disabled = true;
      status.textContent = "Analyzing GitHub...";
      answer.textContent = "GitHub 기록에서 팀원, 작업 성향, 할 일 후보를 분석하는 중입니다.";
      tools.innerHTML = "<span class='muted'>Tool 선택 대기 중...</span>";
      tasks.innerHTML = "<span class='muted'>할 일 후보 생성 중...</span>";

      try {
        const response = await fetch("/api/analyze-tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: text }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        answer.textContent = payload.answer;
        renderTools(payload.selected_tools || []);
        renderTasks(payload.proposed_tasks || []);
        status.textContent = "Approval required";
      } catch (error) {
        proposedTasks = [];
        answer.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
        tools.innerHTML = "<span class='muted'>요청이 실패했습니다.</span>";
        tasks.innerHTML = "<span class='muted'>할 일 후보를 만들지 못했습니다.</span>";
        status.textContent = "Error";
      } finally {
        analyze.disabled = false;
        refreshApproveButton();
      }
    }

    async function approveTasks() {
      const items = selectedTasks();
      if (!items.length) {
        status.textContent = "No selected tasks";
        return;
      }
      approve.disabled = true;
      analyze.disabled = true;
      status.textContent = "Saving to Notion...";
      try {
        const response = await fetch("/api/approve-tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tasks: items }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        answer.textContent += `\n\nNotion에 ${payload.created.length}개의 할 일을 등록했습니다.`;
        renderTools(payload.selected_tools || []);
        status.textContent = "Saved";
      } catch (error) {
        answer.innerHTML += `<br><span class="error">${escapeHtml(error.message)}</span>`;
        status.textContent = "Error";
      } finally {
        analyze.disabled = false;
        refreshApproveButton();
      }
    }

    analyze.addEventListener("click", analyzeGithub);
    approve.addEventListener("click", approveTasks);
    question.addEventListener("keydown", (event) => {
      if (event.ctrlKey && event.key === "Enter") {
        analyzeGithub();
      }
    });
    loadConfig().catch(() => {
      document.querySelector("#repo").textContent = "config error";
    });
  </script>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    server_version = "GitHubAIAgentUI/0.5"

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._send_html(HTML)
            return
        if self.path == "/api/config":
            notion = NotionToolClient()
            self._send_json(
                {
                    "owner": os.environ.get("GITHUB_OWNER", ""),
                    "repo": os.environ.get("GITHUB_REPO", ""),
                    "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    "backend": os.environ.get("GITHUB_TOOL_BACKEND", "github-api"),
                    "notion_enabled": notion.enabled,
                    "assignee_property": notion.config.assignee_property,
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/analyze-tasks":
            self._handle_analyze_tasks()
            return
        if self.path == "/api/approve-tasks":
            self._handle_approve_tasks()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_analyze_tasks(self) -> None:
        try:
            payload = self._read_json()
            question = str(payload.get("question", "")).strip()
            if not question:
                self._send_json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
                return
            result = asyncio.run(analyze_tasks(question))
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_approve_tasks(self) -> None:
        try:
            payload = self._read_json()
            tasks = payload.get("tasks", [])
            if not isinstance(tasks, list) or not tasks:
                self._send_json({"error": "tasks are required"}, HTTPStatus.BAD_REQUEST)
                return
            result = asyncio.run(create_notion_tasks(tasks))
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}

    def _send_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, body: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


async def analyze_tasks(question: str) -> dict[str, Any]:
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
                {"tool": "list_commits", "arguments": {"per_page": 20}},
            ]
        github_client = DirectGitHubToolClient()

    analysis_prompt = (
        "사용자의 질문 표현이 달라도 맥락을 해석하세요. 사용자가 팀원, 구성원, 누가 있는지, "
        "역할, 담당, 분배, 분담, 배정, 할 일 나누기 등을 묻는다면 모두 팀원/일 배분 요청으로 처리하세요.\n\n"
        f"사용자 질문: {question}\n\n"
        "GitHub에서 미리 조회한 repo 활동 정보:\n"
        f"{preloaded_context or '미리 조회된 GitHub 활동 정보 없음'}\n\n"
        "중요 규칙:\n"
        "1. 팀원 목록은 사용자가 입력하는 값이 아니라 GitHub contributors/collaborators 결과에서 자동으로 판단합니다.\n"
        "2. collaborators 조회가 권한 오류를 반환하면 그 사실을 설명하고 contributors와 commits 기준으로 판단합니다.\n"
        "3. contributors는 커밋 기여자 목록이므로, repo 접근 권한이 있는 모든 팀원과 다를 수 있음을 필요하면 설명합니다.\n"
        "4. 할 일 배분 요청이면 최근 commit message, author/login, 이슈/PR 상태를 근거로 팀원별 작업 성향을 추정하세요.\n"
        "5. 특정 팀원이 특정 종류의 작업을 많이 했다면 비슷한 작업을 우선 배정하세요. 단, 한 사람에게 과도하게 몰리면 균형을 고려하세요.\n"
        "6. 사용자가 팀원 목록만 물었다면 proposed_tasks는 빈 배열로 두세요.\n"
        "7. 사용자가 일 배분, 할 일, 오늘 할 일, 역할 분담을 물었다면 proposed_tasks에 담당자 포함 작업 후보를 반드시 넣으세요.\n"
        "   열린 이슈나 PR이 없어도 빈 배열로 두지 마세요. 최근 커밋, README/설정 변경, 워크플로우 부재, "
        "   테스트 부재, 문서 정리 필요성 같은 GitHub 근거에서 점검/정리/개선 작업을 추론해서 배분하세요.\n"
        "8. Notion에는 아직 저장하지 않습니다. 승인 버튼 이후에만 저장됩니다.\n\n"
        "반드시 아래 JSON 형식만 출력하세요.\n"
        "{\n"
        '  "answer": "번호와 짧은 제목을 사용한 한국어 분석 결과",\n'
        '  "proposed_tasks": [\n'
        "    {\n"
        '      "title": "구체적인 할 일 제목",\n'
        '      "status": "To do",\n'
        '      "priority": "High 또는 Medium 또는 Low",\n'
        '      "source": "GitHub 근거 출처",\n'
        '      "due": "",\n'
        '      "reason": "GitHub 근거와 담당자 배정 이유",\n'
        '      "assignee": "담당자 GitHub ID 또는 이름",\n'
        '      "assignee_github": "담당자 GitHub ID"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "answer는 긴 문단 하나로 쓰지 말고, 내용별로 1., 2., 3.처럼 번호를 매기세요. "
        "팀원 질문이면 첫 항목에 '확인된 팀원/기여자'를 두고 GitHub ID 목록을 나열하세요. "
        "일 배분 질문이면 각 작업의 담당자와 배정 이유를 명확히 쓰세요. "
        "할 일은 최대 5개만 제안하세요."
    )

    async with github_client as tools:
        result = await agent.run(analysis_prompt, tools)

    parsed = _parse_task_json(result.answer)
    return {
        "answer": parsed.get("answer") or result.answer,
        "proposed_tasks": _normalize_tasks(parsed.get("proposed_tasks", [])),
        "selected_tools": [*preloaded_tools, *result.selected_tools],
    }


async def create_notion_tasks(tasks: list[Any]) -> dict[str, Any]:
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


async def _load_repo_context(tools: DirectGitHubToolClient) -> str:
    chunks: list[str] = []
    for tool_name, arguments in (
        ("list_contributors", {"per_page": 20}),
        ("list_collaborators", {"per_page": 20}),
        ("list_commits", {"per_page": 20}),
    ):
        try:
            result = await tools.call_tool(tool_name, arguments)
        except Exception as error:
            result = json.dumps({"error": str(error)}, ensure_ascii=False)
        chunks.append(f"{tool_name}:\n{result}")
    return "\n\n".join(chunks)


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


def _normalize_tasks(tasks: Any) -> list[dict[str, Any]]:
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
        normalized.append(
            {
                "title": title,
                "status": str(task.get("status") or "To do"),
                "priority": priority,
                "source": str(task.get("source") or "GitHub analysis"),
                "due": str(task.get("due") or ""),
                "reason": str(task.get("reason") or ""),
                "assignee": str(task.get("assignee") or ""),
                "assignee_github": str(task.get("assignee_github") or ""),
            }
        )
    return normalized


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the GitHub AI Agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"GitHub AI Agent UI running at {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
