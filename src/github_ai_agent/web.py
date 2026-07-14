from __future__ import annotations

import argparse
import asyncio
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from dotenv import load_dotenv

from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent.orchestrator.domains import (
    analyze_tasks,
    create_calendar_events,
    create_notion_tasks,
    load_config_members,
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
    .chips, .task-meta, .member-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .chip, .tag {
      border-radius: 999px;
      padding: 5px 9px;
      background: #fff;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .tag { background: #edf2f7; color: #334155; border: 0; }
    .members { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
    .examples { display: grid; gap: 8px; margin-top: 12px; }
    label.field { display: grid; gap: 6px; color: var(--muted); }
    input[type="date"], textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      color: var(--text);
      font: inherit;
      background: #fff;
    }
    textarea { resize: vertical; }
    textarea:focus, input[type="date"]:focus {
      outline: 2px solid rgba(15, 118, 110, 0.22);
      border-color: var(--accent);
    }
    #question { min-height: 110px; }
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
    .composer { display: grid; gap: 10px; padding: 14px; }
    .actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .button-row { display: flex; gap: 10px; flex-wrap: wrap; }
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
      <p class="muted">GitHub 기록에서 팀원과 작업 성향을 읽고, 승인된 작업만 Notion과 Google Calendar에 등록합니다.</p>

      <div class="repo">
        <span class="muted">Repository</span>
        <strong id="repo">loading...</strong>
        <div class="chips">
          <span class="chip" id="backend">backend</span>
          <span class="chip" id="model">model</span>
          <span class="chip" id="notion">notion</span>
          <span class="chip" id="calendar">calendar</span>
        </div>
        <div class="members">
          <span class="muted">GitHub IDs</span>
          <div class="member-list" id="members">
            <span class="chip">loading...</span>
          </div>
        </div>
      </div>

      <h2>Examples</h2>
      <div class="examples">
        <button class="example" data-question="우리 팀 누구누구 있어?">우리 팀 누구누구 있어?</button>
        <button class="example" data-question="할 일을 팀원들에게 배분해줘">할 일을 팀원들에게 배분해줘</button>
        <button class="example" data-question="각자 최근에 많이 한 작업 기준으로 오늘 할 일을 나눠줘">작업 성향 기준으로 할 일 분담</button>
        <button class="example" data-question="오늘 뭐부터 하면 좋을까?">오늘 뭐부터 하면 좋을까?</button>
      </div>
    </aside>

    <main>
      <div class="composer">
        <label class="field">
          프로젝트 전체 마감일
          <input id="projectDeadline" type="date" />
        </label>
        <textarea id="question" placeholder="예: 할 일을 팀원들에게 배분해줘"></textarea>
        <div class="actions">
          <span class="muted" id="status">Ready</span>
          <div class="button-row">
            <button class="primary" id="analyze">Analyze GitHub</button>
            <button class="approve" id="approveNotion" disabled>Notion 등록</button>
            <button class="approve" id="approveCalendar" disabled>Calendar 등록</button>
          </div>
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
          <h2>Proposed Tasks</h2>
          <div id="tasks" class="muted">승인 전에는 Notion이나 Calendar에 아무것도 저장되지 않습니다.</div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const question = document.querySelector("#question");
    const projectDeadline = document.querySelector("#projectDeadline");
    const analyze = document.querySelector("#analyze");
    const approveNotion = document.querySelector("#approveNotion");
    const approveCalendar = document.querySelector("#approveCalendar");
    const answer = document.querySelector("#answer");
    const tools = document.querySelector("#tools");
    const tasks = document.querySelector("#tasks");
    const status = document.querySelector("#status");

    let proposedTasks = [];
    let notionEnabled = false;
    let calendarEnabled = false;

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
      calendarEnabled = Boolean(config.calendar_enabled);
      document.querySelector("#notion").textContent = notionEnabled ? "notion on" : "notion off";
      document.querySelector("#calendar").textContent = calendarEnabled ? "calendar on" : "calendar off";
      renderMembers(config.members || [], config.member_warnings || []);
      refreshApproveButtons();
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function refreshApproveButtons() {
      const hasTasks = proposedTasks.length > 0;
      approveNotion.disabled = !notionEnabled || !hasTasks;
      approveCalendar.disabled = !calendarEnabled || !hasTasks;
    }

    function renderMembers(members, warnings) {
      const membersEl = document.querySelector("#members");
      membersEl.innerHTML = "";
      if (!members.length) {
        membersEl.innerHTML = "<span class='chip'>확인된 ID 없음</span>";
      } else {
        members.forEach((member) => {
          const span = document.createElement("span");
          span.className = "chip";
          const label = member.github_id || member.login || member.name || "unknown";
          span.title = member.role || member.contributions ? `${member.role || ""} ${member.contributions || ""}`.trim() : "";
          span.textContent = label.startsWith("@") ? label : `@${label}`;
          membersEl.appendChild(span);
        });
      }
      warnings.forEach((warning) => {
        const span = document.createElement("span");
        span.className = "chip";
        span.textContent = warning;
        membersEl.appendChild(span);
      });
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
        refreshApproveButtons();
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
            ${task.due ? `<span class="tag">마감: ${escapeHtml(task.due)}</span>` : ""}
          </div>
          <div class="muted">${escapeHtml(task.reason || "")}</div>
          <pre>${escapeHtml(JSON.stringify(task, null, 2))}</pre>
        `;
        tasks.appendChild(div);
      });
      refreshApproveButtons();
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
      approveNotion.disabled = true;
      approveCalendar.disabled = true;
      status.textContent = "Analyzing GitHub...";
      answer.textContent = "GitHub 기록에서 팀원, 작업 성향, 마감일 후보를 분석하는 중입니다.";
      tools.innerHTML = "<span class='muted'>Tool 선택 대기 중...</span>";
      tasks.innerHTML = "<span class='muted'>할 일 후보 생성 중...</span>";

      try {
        const response = await fetch("/api/analyze-tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: text,
            project_deadline: projectDeadline.value,
          }),
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
        tools.innerHTML = "<span class='muted'>요청에 실패했습니다.</span>";
        tasks.innerHTML = "<span class='muted'>할 일 후보를 만들지 못했습니다.</span>";
        status.textContent = "Error";
      } finally {
        analyze.disabled = false;
        refreshApproveButtons();
      }
    }

    async function postSelectedTasks(url, savingText, successText) {
      const items = selectedTasks();
      if (!items.length) {
        status.textContent = "No selected tasks";
        return;
      }
      approveNotion.disabled = true;
      approveCalendar.disabled = true;
      analyze.disabled = true;
      status.textContent = savingText;
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tasks: items }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        const count = (payload.created || []).length;
        answer.textContent += `\n\n${successText}: ${count}개`;
        renderTools(payload.selected_tools || []);
        status.textContent = "Saved";
      } catch (error) {
        answer.innerHTML += `<br><span class="error">${escapeHtml(error.message)}</span>`;
        status.textContent = "Error";
      } finally {
        analyze.disabled = false;
        refreshApproveButtons();
      }
    }

    analyze.addEventListener("click", analyzeGithub);
    approveNotion.addEventListener("click", () => postSelectedTasks("/api/approve-tasks", "Saving to Notion...", "Notion 등록 완료"));
    approveCalendar.addEventListener("click", () => postSelectedTasks("/api/approve-calendar-events", "Saving to Calendar...", "Calendar 등록 완료"));
    question.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
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
    server_version = "GitHubAIAgentUI/0.8"

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._send_html(HTML)
            return
        if self.path == "/api/config":
            notion = NotionToolClient()
            calendar = GoogleCalendarToolClient()
            self._send_json(
                {
                    "owner": os.environ.get("GITHUB_OWNER", ""),
                    "repo": os.environ.get("GITHUB_REPO", ""),
                    "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    "backend": os.environ.get("GITHUB_TOOL_BACKEND", "github-api"),
                    "notion_enabled": notion.enabled,
                    "calendar_enabled": calendar.enabled,
                    "calendar_timezone": calendar.config.timezone,
                    "assignee_property": notion.config.assignee_property,
                    **load_config_members(),
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
        if self.path == "/api/approve-calendar-events":
            self._handle_approve_calendar_events()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_analyze_tasks(self) -> None:
        try:
            payload = self._read_json()
            question = str(payload.get("question", "")).strip()
            project_deadline = str(payload.get("project_deadline", "")).strip()
            if not question:
                self._send_json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
                return
            result = asyncio.run(analyze_tasks(question, project_deadline=project_deadline))
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

    def _handle_approve_calendar_events(self) -> None:
        try:
            payload = self._read_json()
            tasks = payload.get("tasks", [])
            if not isinstance(tasks, list) or not tasks:
                self._send_json({"error": "tasks are required"}, HTTPStatus.BAD_REQUEST)
                return
            result = asyncio.run(create_calendar_events(tasks))
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


def main() -> None:
    load_dotenv(override=True, encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description="Run the GitHub AI Agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"GitHub AI Agent UI running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
