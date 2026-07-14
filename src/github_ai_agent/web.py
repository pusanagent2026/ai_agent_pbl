from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
import urllib.request

from dotenv import load_dotenv

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_app_auth import GitHubAppTokenProvider, resolve_default_repository
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient

SESSIONS: dict[str, dict[str, Any]] = {}
OAUTH_STATES: dict[str, str] = {}

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
    .repo select { width: 100%; margin-top: 8px; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--text); }
    .connect-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .link-button { display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--accent); border-radius: 8px; padding: 8px 10px; color: #fff; background: var(--accent); text-decoration: none; font-weight: 700; }
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
      <p class="muted">GitHub MCP/API 기록에서 팀원과 작업 성향을 읽고, 승인된 작업만 Notion과 Google Calendar에 등록합니다.</p>

      <div class="repo">
        <span class="muted">Repository</span>
        <strong id="repo">loading...</strong>
        <select id="repoSelect" hidden></select>
        <div class="connect-row">
          <a class="link-button" id="connectGithub" href="/auth/github">GitHub 연결</a>
          <a class="link-button" id="installGithub" href="/auth/github/install" hidden>앱 설치</a>
          <a class="link-button" id="connectGoogle" href="/auth/google">Google Calendar 연결</a>
        </div>
        <div class="chips">
          <span class="chip" id="backend">backend</span>
          <span class="chip" id="model">model</span>
          <span class="chip" id="notion">notion</span>
          <span class="chip" id="calendar">calendar</span>
        </div>
        <div class="members">
          <span class="muted">GitHub IDs</span>
          <div class="member-list" id="members"><span class="chip">loading...</span></div>
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
    const repoSelect = document.querySelector("#repoSelect");
    const connectGithub = document.querySelector("#connectGithub");
    const installGithub = document.querySelector("#installGithub");
    const connectGoogle = document.querySelector("#connectGoogle");

    let proposedTasks = [];
    let notionEnabled = false;
    let calendarEnabled = false;
    let selectedRepository = { owner: "", repo: "", installation_id: "" };

    document.querySelectorAll(".example").forEach((button) => {
      button.addEventListener("click", () => {
        question.value = button.dataset.question;
        question.focus();
      });
    });

    async function loadConfig() {
      const response = await fetch("/api/config");
      const config = await response.json();
      selectedRepository = readSavedRepository(config);
      renderRepositorySelect(config.repositories || []);
      connectGithub.textContent = config.github_user ? `@${config.github_user}` : "GitHub 연결";
      connectGoogle.textContent = config.google_user ? `Calendar: ${config.google_user}` : "Google Calendar 연결";
      installGithub.hidden = Boolean((config.repositories || []).length);
      document.querySelector("#backend").textContent = config.backend;
      document.querySelector("#model").textContent = config.model;
      notionEnabled = Boolean(config.notion_enabled);
      calendarEnabled = Boolean(config.calendar_enabled);
      document.querySelector("#notion").textContent = notionEnabled ? "notion on" : "notion off";
      document.querySelector("#calendar").textContent = calendarEnabled ? "calendar on" : "calendar off";
      renderMembers(config.members || [], config.member_warnings || []);
      if (selectedRepository.owner !== config.owner || selectedRepository.repo !== config.repo) {
        await loadMembers(selectedRepository.owner, selectedRepository.repo);
      }
      refreshApproveButtons();
    }

    function readSavedRepository(config) {
      const saved = localStorage.getItem("selectedRepository");
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (parsed.owner && parsed.repo) {
            return parsed;
          }
        } catch (_) {}
      }
      return {
        owner: config.owner || "",
        repo: config.repo || "",
        installation_id: config.installation_id || "",
      };
    }

    function renderRepositorySelect(repositories) {
      document.querySelector("#repo").textContent = `${selectedRepository.owner}/${selectedRepository.repo}`;
      repoSelect.innerHTML = "";
      if (!repositories.length) {
        repoSelect.hidden = true;
        return;
      }
      repositories.forEach((repository) => {
        const option = document.createElement("option");
        option.value = repository.full_name;
        option.textContent = repository.full_name;
        option.dataset.owner = repository.owner;
        option.dataset.repo = repository.repo;
        option.dataset.installationId = repository.installation_id || "";
        option.selected = repository.owner === selectedRepository.owner && repository.repo === selectedRepository.repo;
        repoSelect.appendChild(option);
      });
      repoSelect.hidden = false;
    }

    repoSelect.addEventListener("change", async () => {
      const option = repoSelect.selectedOptions[0];
      const owner = option.dataset.owner;
      const repo = option.dataset.repo;
      selectedRepository = { owner, repo, installation_id: option.dataset.installationId || "" };
      localStorage.setItem("selectedRepository", JSON.stringify(selectedRepository));
      document.querySelector("#repo").textContent = `${owner}/${repo}`;
      await loadMembers(owner, repo);
    });

    async function loadMembers(owner, repo) {
      const params = new URLSearchParams({
        owner,
        repo,
        installation_id: selectedRepository.installation_id || "",
      });
      const response = await fetch(`/api/members?${params.toString()}`);
      const payload = await response.json();
      renderMembers(payload.members || [], payload.member_warnings || []);
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
      answer.textContent = "GitHub MCP/API 기록에서 팀원, 작업 성향, 마감일 후보를 분석하는 중입니다.";
      tools.innerHTML = "<span class='muted'>Tool 선택 대기 중...</span>";
      tasks.innerHTML = "<span class='muted'>할 일 후보 생성 중...</span>";

      try {
        const response = await fetch("/api/analyze-tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: text,
            project_deadline: projectDeadline.value,
            owner: selectedRepository.owner,
            repo: selectedRepository.repo,
            installation_id: selectedRepository.installation_id,
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
    server_version = "GitHubAIAgentUI/0.9"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/" or self.path.startswith("/?"):
            self._send_html(HTML)
            return
        if parsed_url.path == "/auth/github":
            self._redirect_to_github_login()
            return
        if parsed_url.path == "/auth/github/callback":
            self._handle_github_callback(parsed_url.query)
            return
        if parsed_url.path == "/auth/github/install":
            self._redirect_to_github_install()
            return
        if parsed_url.path == "/auth/github/setup":
            self._handle_github_setup(parsed_url.query)
            return
        if parsed_url.path == "/auth/google":
            self._redirect_to_google_login()
            return
        if parsed_url.path == "/auth/google/callback":
            self._handle_google_callback(parsed_url.query)
            return
        if parsed_url.path == "/api/config":
            notion = NotionToolClient()
            calendar = GoogleCalendarToolClient()
            session = self._session()
            repositories = _load_repositories(session)
            owner, repo, installation_id = _select_default_repository(repositories)
            self._send_json(
                {
                    "owner": owner,
                    "repo": repo,
                    "installation_id": installation_id,
                    "repositories": repositories,
                    "github_user": session.get("github_login", ""),
                    "google_user": session.get("google_email", ""),
                    "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    "backend": "github-mcp",
                    "notion_enabled": notion.enabled,
                    "calendar_enabled": _calendar_enabled_for_session(calendar, session),
                    "calendar_timezone": calendar.config.timezone,
                    "assignee_property": notion.config.assignee_property,
                    **_load_config_members(owner, repo, installation_id),
                }
            )
            return
        if parsed_url.path == "/api/members":
            query = parse_qs(parsed_url.query)
            owner = (query.get("owner") or [""])[0].strip()
            repo = (query.get("repo") or [""])[0].strip()
            installation_id = (query.get("installation_id") or [""])[0].strip()
            if not owner or not repo:
                repositories = _load_repositories(self._session())
                owner, repo, installation_id = _select_default_repository(repositories)
            self._send_json(_load_config_members(owner, repo, installation_id))
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
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            if not question:
                self._send_json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
                return
            result = asyncio.run(
                analyze_tasks(
                    question,
                    project_deadline=project_deadline,
                    owner=owner,
                    repo=repo,
                    installation_id=installation_id,
                )
            )
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
            result = asyncio.run(
                create_calendar_events(
                    tasks,
                    google_access_token=str(self._session().get("google_access_token") or ""),
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _redirect_to_github_login(self) -> None:
        client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
        if not client_id:
            self._send_json(
                {"error": "GITHUB_APP_CLIENT_ID is required for GitHub login."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        session_id = self._session_id()
        state = secrets.token_urlsafe(24)
        OAUTH_STATES[state] = session_id
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": _base_url() + "/auth/github/callback",
                "state": state,
                "scope": "read:user",
            }
        )
        self._redirect(f"https://github.com/login/oauth/authorize?{params}", session_id)

    def _handle_github_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not code or not session_id:
            self._send_json({"error": "Invalid GitHub OAuth callback."}, HTTPStatus.BAD_REQUEST)
            return

        token = _exchange_github_code(code)
        user = _github_get("/user", token)
        session = SESSIONS.setdefault(session_id, {})
        session["github_access_token"] = token
        session["github_login"] = str(user.get("login") or "")
        self._redirect("/", session_id)

    def _redirect_to_github_install(self) -> None:
        slug = os.environ.get("GITHUB_APP_SLUG", "").strip()
        if not slug:
            self._send_json(
                {"error": "GITHUB_APP_SLUG is required for GitHub App installation."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        session_id = self._session_id()
        self._redirect(f"https://github.com/apps/{slug}/installations/new", session_id)

    def _handle_github_setup(self, query_string: str) -> None:
        query = parse_qs(query_string)
        installation_id = (query.get("installation_id") or [""])[0].strip()
        session_id = self._session_id()
        if installation_id:
            SESSIONS.setdefault(session_id, {})["installation_id"] = installation_id
        self._redirect("/", session_id)

    def _redirect_to_google_login(self) -> None:
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            self._send_json(
                {"error": "GOOGLE_OAUTH_CLIENT_ID is required for Google Calendar login."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        session_id = self._session_id()
        state = secrets.token_urlsafe(24)
        OAUTH_STATES[state] = session_id
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": _base_url() + "/auth/google/callback",
                "response_type": "code",
                "state": state,
                "scope": (
                    "https://www.googleapis.com/auth/calendar.events "
                    "https://www.googleapis.com/auth/userinfo.email"
                ),
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        self._redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}", session_id)

    def _handle_google_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not code or not session_id:
            self._send_json({"error": "Invalid Google OAuth callback."}, HTTPStatus.BAD_REQUEST)
            return

        token_payload = _exchange_google_code(code)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            self._send_json({"error": "Google OAuth did not return access_token."}, HTTPStatus.BAD_REQUEST)
            return
        user = _google_get_userinfo(access_token)
        session = SESSIONS.setdefault(session_id, {})
        session["google_access_token"] = access_token
        if token_payload.get("refresh_token"):
            session["google_refresh_token"] = str(token_payload.get("refresh_token"))
        session["google_email"] = str(user.get("email") or "")
        self._redirect("/", session_id)

    def _session_id(self) -> str:
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "github_ai_agent_session" and value:
                SESSIONS.setdefault(value, {})
                return value
        session_id = secrets.token_urlsafe(24)
        SESSIONS.setdefault(session_id, {})
        return session_id

    def _session(self) -> dict[str, Any]:
        return SESSIONS.setdefault(self._session_id(), {})

    def _redirect(self, location: str, session_id: str | None = None) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        if session_id:
            self.send_header(
                "Set-Cookie",
                f"github_ai_agent_session={session_id}; Path=/; HttpOnly; SameSite=Lax",
            )
        self.end_headers()

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


async def analyze_tasks(
    question: str,
    *,
    project_deadline: str = "",
    owner: str = "",
    repo: str = "",
    installation_id: str = "",
) -> dict[str, Any]:
    agent = GitHubToolChoosingAgent(owner=owner or None, repo=repo or None)
    async with GitHubMcpClient(installation_id=installation_id or None) as github_tools:
        result = await agent.run(
            _build_analysis_prompt(question, project_deadline),
            github_tools,
        )

    parsed = _parse_task_json(result.answer)
    return {
        "answer": parsed.get("answer") or result.answer,
        "proposed_tasks": _normalize_tasks(
            parsed.get("proposed_tasks", []),
            project_deadline=project_deadline,
        ),
        "selected_tools": [
            {"tool": "github_backend", "arguments": {"backend": "mcp"}},
            *result.selected_tools,
        ],
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


async def create_calendar_events(
    tasks: list[Any],
    *,
    google_access_token: str = "",
) -> dict[str, Any]:
    calendar = GoogleCalendarToolClient(mcp_auth_token=google_access_token or None)
    created: list[dict[str, Any]] = []
    selected_tools: list[dict[str, Any]] = []
    async with calendar:
        for task in _normalize_tasks(tasks):
            selected_tools.append({"tool": "create_calendar_event", "arguments": task})
            raw = await calendar.call_tool("create_calendar_event", task)
            try:
                created.append(json.loads(raw))
            except json.JSONDecodeError:
                created.append({"created": True, "raw": raw})
    return {"created": created, "selected_tools": selected_tools}


def _build_analysis_prompt(
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

반드시 아래 JSON 형식만 출력하세요.

{{
  "answer": "번호가 붙은 한국어 분석 결과",
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

answer는 긴 한 문단으로 이어 쓰지 말고, 내용별로 1., 2., 3.처럼 번호를 매겨 읽기 쉽게 작성하세요.
"""


def _base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://127.0.0.1:8787").rstrip("/")


def _exchange_github_code(code: str) -> str:
    client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GITHUB_APP_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("GITHUB_APP_CLIENT_ID and GITHUB_APP_CLIENT_SECRET are required.")
    data = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _base_url() + "/auth/github/callback",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://github.com/login/oauth/access_token",
        data=data,
        method="POST",
        headers={"Accept": "application/json", "User-Agent": "github-ai-mcp-agent"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not token:
        raise ValueError(f"GitHub OAuth token response did not include access_token: {payload.get('error_description', '')}")
    return str(token)


def _github_get(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.github.com" + path,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "github-ai-mcp-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _exchange_google_code(code: str) -> dict[str, Any]:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are required.")
    data = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _base_url() + "/auth/google/callback",
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        method="POST",
        headers={"Accept": "application/json", "User-Agent": "github-ai-mcp-agent"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _google_get_userinfo(access_token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "github-ai-mcp-agent",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _calendar_enabled_for_session(
    calendar: GoogleCalendarToolClient,
    session: dict[str, Any],
) -> bool:
    if not calendar.enabled:
        return False
    if calendar.config.backend != "mcp":
        return calendar.enabled
    return bool(session.get("google_access_token"))


def _load_repositories(session: dict[str, Any] | None = None) -> list[dict[str, str]]:
    session = session or {}
    user_token = str(session.get("github_access_token") or "")
    if user_token:
        return _load_user_installation_repositories(user_token)

    provider = GitHubAppTokenProvider()
    if not provider.enabled:
        return []
    repositories = provider.list_installation_repositories()
    installation_id = provider.config.installation_id
    return _format_repositories(repositories, installation_id)


def _load_user_installation_repositories(token: str) -> list[dict[str, str]]:
    installations = _github_get("/user/installations?per_page=100", token).get("installations", [])
    result: list[dict[str, str]] = []
    if not isinstance(installations, list):
        return result
    for installation in installations:
        if not isinstance(installation, dict):
            continue
        installation_id = str(installation.get("id") or "")
        if not installation_id:
            continue
        payload = _github_get(f"/user/installations/{installation_id}/repositories?per_page=100", token)
        repositories = payload.get("repositories", [])
        if isinstance(repositories, list):
            result.extend(_format_repositories(repositories, installation_id))
    return result


def _format_repositories(
    repositories: list[Any],
    installation_id: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in repositories:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "")
        if "/" not in full_name:
            continue
        owner, repo = full_name.split("/", 1)
        result.append(
            {
                "owner": owner,
                "repo": repo,
                "full_name": full_name,
                "installation_id": installation_id,
            }
        )
    return result


def _select_default_repository(repositories: list[dict[str, str]]) -> tuple[str, str, str]:
    if repositories:
        first = repositories[0]
        return first.get("owner", ""), first.get("repo", ""), first.get("installation_id", "")
    owner, repo = resolve_default_repository()
    return owner, repo, os.environ.get("GITHUB_APP_INSTALLATION_ID", "")


def _load_config_members(owner: str, repo: str, installation_id: str = "") -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        warnings: list[str] = []
        raw_payloads: list[str] = []
        async with GitHubMcpClient(installation_id=installation_id or None) as tools:
            available_tools = await tools.list_tools()
            tool_names = {tool.name for tool in available_tools}
            for tool_name, arguments in _mcp_member_tool_calls(tool_names, owner, repo):
                try:
                    raw_payloads.append(await tools.call_tool(tool_name, arguments))
                except Exception as error:
                    warnings.append(f"{tool_name} 조회 실패: {error}")
        members = _extract_members(*raw_payloads)
        if not members:
            warnings.append("MCP에서 확인된 팀원 ID 없음")
        return {"members": members, "member_warnings": warnings}

    try:
        return asyncio.run(load())
    except Exception as error:
        return {"members": [], "member_warnings": [f"GitHub MCP 연결 실패: {error}"]}


def _mcp_member_tool_calls(
    tool_names: set[str],
    owner: str,
    repo: str,
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    exact_candidates = (
        ("list_repository_collaborators", {"owner": owner, "repo": repo, "perPage": 50}),
        ("list_contributors", {"owner": owner, "repo": repo, "perPage": 50}),
        ("list_collaborators", {"owner": owner, "repo": repo, "perPage": 50}),
        ("list_commits", {"owner": owner, "repo": repo, "perPage": 50}),
    )
    for tool_name, arguments in exact_candidates:
        if tool_name in tool_names:
            calls.append((tool_name, arguments))
    if calls:
        return calls

    # Fallback for MCP servers that expose different GitHub tool names.
    for tool_name in sorted(tool_names):
        lowered = tool_name.lower()
        if any(keyword in lowered for keyword in ("contributor", "collaborator", "member")):
            calls.append((tool_name, {}))
    return calls


def _extract_warnings(raw: str, label: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict) and parsed.get("error"):
        code = parsed.get("error")
        if code in {401, 403}:
            return [f"{label} 권한 필요"]
        return [f"{label} 조회 오류 {code}"]
    return []


def _is_empty_list(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list) and len(parsed) == 0


def _extract_members(*raw_payloads: str) -> list[dict[str, str]]:
    by_login: dict[str, dict[str, str]] = {}
    for raw in raw_payloads:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if parsed.get("error"):
                continue
            items = parsed.get("items", [])
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            login = str(item.get("login") or "").strip()
            if not login:
                user = item.get("user")
                if isinstance(user, dict):
                    login = str(user.get("login") or "").strip()
            if not login:
                author = item.get("author")
                if isinstance(author, dict):
                    login = str(author.get("login") or "").strip()
            if not login:
                committer = item.get("committer")
                if isinstance(committer, dict):
                    login = str(committer.get("login") or "").strip()
            if not login:
                continue
            current = by_login.setdefault(
                login.lower(),
                {"github_id": login, "name": str(item.get("name") or login), "source": "github"},
            )
            if item.get("contributions") is not None:
                current["contributions"] = str(item.get("contributions"))
            if item.get("role_name"):
                current["role"] = str(item.get("role_name"))
    return sorted(by_login.values(), key=lambda member: member["github_id"].lower())


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


def _normalize_tasks(
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
