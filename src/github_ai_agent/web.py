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

    .shell {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: 100vh;
    }

    aside {
      border-right: 1px solid var(--line);
      background: #eef3f6;
      padding: 24px;
    }

    main {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 18px;
      padding: 24px;
    }

    h1 {
      margin: 0 0 10px;
      font-size: 24px;
      line-height: 1.2;
      letter-spacing: 0;
    }

    h2 {
      margin: 0 0 12px;
      font-size: 16px;
      letter-spacing: 0;
    }

    .muted { color: var(--muted); }

    .repo, .composer, section, .task {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }

    .repo {
      padding: 14px;
      margin: 18px 0;
    }

    .repo strong {
      display: block;
      overflow-wrap: anywhere;
    }

    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }

    .chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
    }

    .examples {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }

    button {
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
      font: inherit;
    }

    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    .example {
      text-align: left;
      padding: 10px 12px;
    }

    .example:hover { border-color: var(--accent); }

    .composer {
      display: grid;
      gap: 10px;
      padding: 14px;
    }

    textarea {
      width: 100%;
      min-height: 94px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      color: var(--text);
      font: inherit;
    }

    textarea:focus {
      outline: 2px solid rgba(15, 118, 110, 0.22);
      border-color: var(--accent);
    }

    .actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .primary, .approve {
      min-width: 132px;
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
      padding: 10px 14px;
      font-weight: 700;
    }

    .primary:hover, .approve:hover { background: var(--accent-dark); }

    .results {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
      gap: 18px;
      min-height: 0;
    }

    section {
      padding: 16px;
      min-width: 0;
      overflow: auto;
    }

    .answer {
      white-space: pre-wrap;
      word-break: keep-all;
      overflow-wrap: anywhere;
    }

    .task {
      padding: 12px;
      margin-bottom: 10px;
    }

    .task-head {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: 8px;
    }

    .task-title {
      font-weight: 800;
      overflow-wrap: anywhere;
    }

    .task-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 8px 0;
    }

    .tag {
      border-radius: 999px;
      background: #edf2f7;
      color: #334155;
      padding: 3px 8px;
      font-size: 12px;
    }

    .tool {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 10px;
      background: #fbfcfe;
    }

    pre {
      margin: 8px 0 0;
      overflow: auto;
      border-radius: 8px;
      background: var(--code);
      padding: 10px;
      font-size: 12px;
    }

    .error {
      color: var(--warn);
      font-weight: 700;
    }

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
      <p class="muted">GitHub 내용을 분석해 할 일을 제안하고, 승인한 항목만 Notion에 등록합니다.</p>

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
        <button class="example" data-question="우리 팀 프로젝트 지금 뭐해야 해?">우리 팀 프로젝트 지금 뭐해야 해?</button>
        <button class="example" data-question="오늘 뭐부터 하면 좋을까?">오늘 뭐부터 하면 좋을까?</button>
        <button class="example" data-question="프로젝트 상태 어때?">프로젝트 상태 어때?</button>
        <button class="example" data-question="팀원들 작업 흐름 보고 다음 할 일 알려줘">팀원 작업 흐름 기반 추천</button>
      </div>
    </aside>

    <main>
      <div class="composer">
        <textarea id="question" placeholder="예: 우리 팀 프로젝트 지금 뭐해야 해?"></textarea>
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
        div.innerHTML = `
          <strong>${index + 1}. ${escapeHtml(item.tool)}</strong>
          <pre>${escapeHtml(JSON.stringify(item.arguments || {}, null, 2))}</pre>
        `;
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
      answer.textContent = "GitHub 내용을 확인하고 할 일 후보를 생성하는 중입니다.";
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
        renderTools([...(payload.selected_tools || [])]);
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
    server_version = "GitHubAIAgentUI/0.3"

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

    if backend == "mcp":
        github_client = GitHubMcpClient()
    else:
        github_client = DirectGitHubToolClient()

    analysis_prompt = (
        "사용자가 아래처럼 짧거나 일상적인 질문을 하더라도, 당신의 역할은 "
        "GitHub 데이터를 근거로 팀이 지금 해야 할 일을 자동으로 도출하는 것입니다.\n\n"
        f"사용자 질문: {question}\n\n"
        "질문에 'Notion', '등록', '할 일 후보'라는 말이 없어도 항상 다음을 수행하세요.\n"
        "1. GitHub commits/issues/PR/workflow 정보를 필요한 만큼 확인합니다.\n"
        "2. 현재 팀이 해야 할 구체적인 작업 후보를 추론합니다.\n"
        "3. 후보를 사용자가 승인할 수 있도록 proposed_tasks에 넣습니다.\n"
        "4. Notion에는 아직 저장하지 않습니다.\n\n"
        "반드시 아래 JSON 형식만 출력하세요.\n"
        "{\n"
        '  "answer": "사용자에게 보여줄 한국어 분석 결과",\n'
        '  "proposed_tasks": [\n'
        "    {\n"
        '      "title": "구체적인 할 일 제목",\n'
        '      "status": "To do",\n'
        '      "priority": "High 또는 Medium 또는 Low",\n'
        '      "source": "GitHub commits/issues/PRs 등 근거 출처",\n'
        '      "due": "",\n'
        '      "reason": "GitHub 근거 기반으로 왜 필요한지"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "answer는 긴 문단 하나로 쓰지 마세요. 내용별로 자연스럽게 나누어 "
        "1., 2., 3.처럼 번호를 매기고, 각 번호에는 짧은 제목과 핵심 내용을 넣으세요. "
        "필요하면 각 번호 아래에 '-' 불릿을 사용하세요. "
        "번호 제목은 실제 분석 내용에 맞게 자유롭게 정하세요. "
        "할 일은 최대 5개만 제안하세요. 근거가 부족해도 최근 활동을 바탕으로 "
        "합리적인 점검/확인 작업을 제안하세요."
    )

    async with github_client as tools:
        result = await agent.run(analysis_prompt, tools)

    parsed = _parse_task_json(result.answer)
    return {
        "answer": parsed.get("answer") or result.answer,
        "proposed_tasks": _normalize_tasks(parsed.get("proposed_tasks", [])),
        "selected_tools": result.selected_tools,
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

    return {
        "created": created,
        "selected_tools": selected_tools,
    }


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
