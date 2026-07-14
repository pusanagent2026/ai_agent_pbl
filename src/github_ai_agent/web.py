from __future__ import annotations

import argparse
import asyncio
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from dotenv import load_dotenv

from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent.orchestrator.agent import OrchestratorAgent
from github_ai_agent.orchestrator.domains import (
    build_github_domain_agent,
    build_notion_domain_agent,
)


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

    .repo, .toggle, .composer, section {
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

    .example {
      text-align: left;
      padding: 10px 12px;
    }

    .example:hover { border-color: var(--accent); }

    .toggle {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      padding: 12px;
      margin-top: 18px;
    }

    input[type="checkbox"] {
      width: 18px;
      height: 18px;
      margin-top: 2px;
      accent-color: var(--accent);
    }

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
    }

    .primary {
      min-width: 116px;
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
      padding: 10px 14px;
      font-weight: 700;
    }

    .primary:hover { background: var(--accent-dark); }
    .primary:disabled { opacity: 0.55; cursor: wait; }

    .results {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.65fr);
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

    .tool {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 10px;
      background: #fbfcfe;
    }

    .tool-name {
      margin-bottom: 8px;
      font-weight: 700;
    }

    pre {
      margin: 0;
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

    @media (max-width: 880px) {
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
      <p class="muted">AI가 질문을 보고 GitHub와 Notion tool을 선택합니다.</p>

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
        <button class="example" data-question="프로젝트 상태 분석해줘">프로젝트 상태 분석해줘</button>
        <button class="example" data-question="오늘 뭐부터 해야 돼?">오늘 뭐부터 해야 돼?</button>
        <button class="example" data-question="최근 변경사항 요약해줘">최근 변경사항 요약해줘</button>
        <button class="example" data-question="팀원별 최근 커밋 활동을 요약해줘">팀원별 최근 커밋 활동을 요약해줘</button>
      </div>

      <label class="toggle">
        <input id="saveToNotion" type="checkbox" />
        <span>
          <strong>Save tasks to Notion</strong><br />
          <span class="muted">켜면 AI가 구체적인 할 일을 Notion DB에 기록합니다.</span>
        </span>
      </label>
    </aside>

    <main>
      <div class="composer">
        <textarea id="question" placeholder="GitHub repository에 대해 질문하세요."></textarea>
        <div class="actions">
          <span class="muted" id="status">Ready</span>
          <button class="primary" id="ask">Ask AI</button>
        </div>
      </div>

      <div class="results">
        <section>
          <h2>Answer</h2>
          <div class="answer" id="answer">아직 질문이 없습니다.</div>
        </section>
        <section>
          <h2>Selected Tools</h2>
          <div id="tools" class="muted">AI가 선택한 tool이 여기에 표시됩니다.</div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const question = document.querySelector("#question");
    const ask = document.querySelector("#ask");
    const answer = document.querySelector("#answer");
    const tools = document.querySelector("#tools");
    const status = document.querySelector("#status");
    const saveToNotion = document.querySelector("#saveToNotion");

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
      document.querySelector("#notion").textContent = config.notion_enabled ? "notion on" : "notion off";
      saveToNotion.disabled = !config.notion_enabled;
    }

    function escapeHtml(value) {
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
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
          <div class="tool-name">${index + 1}. ${escapeHtml(item.tool)}</div>
          <pre>${escapeHtml(JSON.stringify(item.arguments || {}, null, 2))}</pre>
        `;
        tools.appendChild(div);
      });
    }

    async function submitQuestion() {
      const text = question.value.trim();
      if (!text) {
        question.focus();
        return;
      }

      ask.disabled = true;
      status.textContent = "Thinking...";
      answer.textContent = "GitHub와 Notion tool을 확인하는 중입니다.";
      tools.innerHTML = "<span class='muted'>Tool 선택 대기 중...</span>";

      try {
        const response = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: text,
            save_to_notion: saveToNotion.checked,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        answer.textContent = payload.answer;
        renderTools(payload.selected_tools || []);
        status.textContent = "Done";
      } catch (error) {
        answer.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
        tools.innerHTML = "<span class='muted'>요청이 실패했습니다.</span>";
        status.textContent = "Error";
      } finally {
        ask.disabled = false;
      }
    }

    ask.addEventListener("click", submitQuestion);
    question.addEventListener("keydown", (event) => {
      if (event.ctrlKey && event.key === "Enter") {
        submitQuestion();
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
    server_version = "GitHubAIAgentUI/0.2"

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
        if self.path != "/api/ask":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json()
            question = str(payload.get("question", "")).strip()
            save_to_notion = bool(payload.get("save_to_notion", False))

            if not question:
                self._send_json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
                return

            result = asyncio.run(run_agent(question, save_to_notion))
            self._send_json(
                {
                    "answer": result.answer,
                    "selected_tools": result.selected_tools,
                }
            )
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


async def run_agent(question: str, save_to_notion: bool):
    github_domain = build_github_domain_agent()
    notion_domain = build_notion_domain_agent()
    orchestrator = OrchestratorAgent(domains=[github_domain, notion_domain])

    if save_to_notion:
        question += (
            "\n\nNotion auto-save is enabled. If you identify concrete tasks, "
            "create them in Notion using create_notion_task."
        )

    return await orchestrator.run(question)


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
