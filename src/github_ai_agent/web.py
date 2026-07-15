from __future__ import annotations

import argparse
import base64
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

from github_ai_agent import code_review
from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_app_auth import GitHubAppTokenProvider, resolve_default_repository
from github_ai_agent.google_calendar_client import GoogleCalendarToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent import readme_review

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
    .shell { display: grid; grid-template-columns: 420px minmax(0, 1fr); min-height: 100vh; }
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
    .calendar-panel { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
    .calendar-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .calendar-link { color: var(--accent-dark); font-weight: 700; text-decoration: none; font-size: 12px; }
    .calendar-view-toggle { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 10px; }
    .calendar-view-toggle button { padding: 7px 8px; font-size: 12px; font-weight: 700; }
    .calendar-view-toggle button.active { border-color: var(--accent); background: var(--accent); color: #fff; }
    .calendar-events { display: grid; gap: 8px; margin-top: 10px; }
    .calendar-event { display: grid; gap: 2px; padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; text-decoration: none; color: var(--text); }
    .calendar-event:hover { border-color: var(--accent); }
    .calendar-event strong { font-size: 13px; line-height: 1.35; }
    .calendar-event span { color: var(--muted); font-size: 12px; }
    .mini-calendar { margin-top: 10px; }
    .mini-calendar-title { font-size: 12px; font-weight: 800; color: var(--muted); margin-bottom: 8px; }
    .mini-calendar-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
    .mini-calendar-day-name { color: var(--muted); font-size: 10px; text-align: center; font-weight: 800; }
    .mini-calendar-cell { min-height: 82px; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 6px; overflow: hidden; }
    .mini-calendar-cell.muted-cell { background: #f8fafc; color: #94a3b8; }
    .mini-calendar-date { font-size: 12px; font-weight: 800; margin-bottom: 4px; }
    .mini-calendar-item { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--accent-dark); font-size: 11px; line-height: 1.35; text-decoration: none; }
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
    .diff-add { background: #ecfdf5; color: #166534; }
    .diff-remove { background: #fef2f2; color: #991b1b; }
    .tabs { display: flex; gap: 8px; }
    .tab-button { padding: 8px 14px; font-weight: 700; }
    .tab-button.active { border-color: var(--accent); background: var(--accent); color: #fff; }
    .review-select-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .review-select-row select, .review-select-row input { flex: 1; min-width: 220px; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--text); }
    .file-list { max-height: 260px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
    .file-item { padding: 7px 10px; cursor: pointer; font-size: 13px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
    .file-item:last-child { border-bottom: 0; }
    .file-item:hover { background: #f5f7fa; }
    .file-item.selected { background: var(--accent); color: #fff; }
    .error-card { border-left: 3px solid var(--warn); }
    .comment-card.good { border-left: 3px solid var(--accent); }
    .comment-card.bad { border-left: 3px solid var(--warn); }
    .badge { border-radius: 999px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
    .badge.good { background: #ecfdf5; color: var(--accent-dark); }
    .badge.bad { background: #fef2f2; color: var(--warn); }
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
          <a class="link-button" id="connectNotion" href="/auth/notion">Notion 연결</a>
          <a class="link-button" id="connectGoogle" href="/auth/google">Google Calendar 연결</a>
        </div>
        <div class="chips">
          <span class="chip" id="backend">backend</span>
          <span class="chip" id="model">model</span>
          <span class="chip" id="notion">notion</span>
          <span class="chip" id="calendar">calendar</span>
        </div>
        <label class="field" id="notionDatabaseField" hidden>
          Notion Database
          <select id="notionDatabaseSelect"></select>
        </label>
        <label class="field" id="notionPageField" hidden>
          Notion Page
          <select id="notionPageSelect"></select>
        </label>
        <label class="field" id="notionSaveModeField" hidden>
          Notion 저장 방식
          <select id="notionSaveMode">
            <option value="database">DB에 작업 행으로 등록</option>
            <option value="page">페이지에 분석 기록으로 저장</option>
            <option value="checklist">페이지에 체크리스트로 저장</option>
          </select>
        </label>
        <button class="example" id="createNotionDatabase" type="button" hidden>Notion 작업 DB 자동 생성</button>
        <div class="members">
          <span class="muted">GitHub IDs</span>
          <div class="member-list" id="members"><span class="chip">loading...</span></div>
        </div>
        <div class="calendar-panel">
          <div class="calendar-head">
            <span class="muted">Google Calendar</span>
            <a class="calendar-link" id="googleCalendarLink" href="https://calendar.google.com/calendar/u/0/r" target="_blank" rel="noreferrer">열기</a>
          </div>
          <div class="calendar-view-toggle">
            <button class="active" id="calendarListView" type="button">목록</button>
            <button id="calendarMonthView" type="button">달력</button>
          </div>
          <div class="calendar-events" id="calendarEvents"><span class="chip">연결 대기</span></div>
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
      <div class="tabs">
        <button class="tab-button active" id="tabTaskPlanner" type="button">작업 분배</button>
        <button class="tab-button" id="tabCodeReview" type="button">코드 리뷰</button>
        <button class="tab-button" id="tabReadmeUpdate" type="button">README 갱신</button>
      </div>

      <div id="taskPlannerView">
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
          </section>
          <section>
            <h2>Proposed Tasks</h2>
            <div id="tasks" class="muted">승인 전에는 Notion이나 Calendar에 아무것도 저장되지 않습니다.</div>
          </section>
        </div>
      </div>

      <div id="codeReviewView" hidden>
        <div class="composer">
          <div class="review-select-row">
            <select id="branchSelect"><option value="">브랜치를 불러오는 중...</option></select>
            <input id="fileFilter" type="text" placeholder="파일 경로 필터 (예: agent.py)" />
          </div>
          <div id="fileList" class="file-list muted">브랜치를 선택하면 파일 목록이 표시됩니다.</div>
          <div class="actions">
            <span class="muted" id="reviewStatus">Ready</span>
            <div class="button-row">
              <button class="primary" id="reviewFile" disabled>Review File</button>
              <button class="approve" id="saveReviewNotion" disabled>Notion에 리뷰 저장</button>
            </div>
          </div>
        </div>

        <div class="results">
          <section>
            <h2>Summary</h2>
            <div class="answer" id="reviewSummary">아직 리뷰 결과가 없습니다.</div>
            <h2 style="margin-top:18px;">오류</h2>
            <div id="reviewErrors" class="muted">아직 리뷰하지 않았습니다.</div>
          </section>
          <section>
            <h2>코멘트</h2>
            <div id="reviewComments" class="muted">잘한 점과 아쉬운 점이 여기에 표시됩니다.</div>
          </section>
        </div>
      </div>

      <div id="readmeUpdateView" hidden>
        <div class="composer">
          <div class="review-select-row">
            <select id="readmeBranchSelect"><option value="">브랜치를 불러오는 중...</option></select>
          </div>
          <div class="actions">
            <span class="muted" id="readmeStatus">Ready</span>
            <div class="button-row">
              <button class="primary" id="analyzeReadme">Analyze README</button>
              <button class="approve" id="applyReadmeUpdate" disabled>PR 생성</button>
            </div>
          </div>
        </div>

        <div class="results">
          <section>
            <h2>판단 결과</h2>
            <div class="answer" id="readmeVerdict">아직 분석하지 않았습니다.</div>
          </section>
          <section>
            <h2>변경 사항</h2>
            <pre id="readmeDiff" class="muted" style="white-space:pre-wrap;max-height:400px;">-</pre>
          </section>
        </div>
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
    const tasks = document.querySelector("#tasks");
    const status = document.querySelector("#status");
    const repoSelect = document.querySelector("#repoSelect");
    const connectGithub = document.querySelector("#connectGithub");
    const installGithub = document.querySelector("#installGithub");
    const connectNotion = document.querySelector("#connectNotion");
    const notionDatabaseField = document.querySelector("#notionDatabaseField");
    const notionDatabaseSelect = document.querySelector("#notionDatabaseSelect");
    const notionPageField = document.querySelector("#notionPageField");
    const notionPageSelect = document.querySelector("#notionPageSelect");
    const notionSaveModeField = document.querySelector("#notionSaveModeField");
    const notionSaveMode = document.querySelector("#notionSaveMode");
    const createNotionDatabase = document.querySelector("#createNotionDatabase");
    const connectGoogle = document.querySelector("#connectGoogle");
    const googleCalendarLink = document.querySelector("#googleCalendarLink");
    const calendarEvents = document.querySelector("#calendarEvents");
    const calendarListView = document.querySelector("#calendarListView");
    const calendarMonthView = document.querySelector("#calendarMonthView");

    const tabTaskPlanner = document.querySelector("#tabTaskPlanner");
    const tabCodeReview = document.querySelector("#tabCodeReview");
    const tabReadmeUpdate = document.querySelector("#tabReadmeUpdate");
    const taskPlannerView = document.querySelector("#taskPlannerView");
    const codeReviewView = document.querySelector("#codeReviewView");
    const readmeUpdateView = document.querySelector("#readmeUpdateView");
    const branchSelect = document.querySelector("#branchSelect");
    const fileFilter = document.querySelector("#fileFilter");
    const fileListEl = document.querySelector("#fileList");
    const reviewFile = document.querySelector("#reviewFile");
    const saveReviewNotion = document.querySelector("#saveReviewNotion");
    const reviewStatus = document.querySelector("#reviewStatus");
    const reviewSummary = document.querySelector("#reviewSummary");
    const reviewErrors = document.querySelector("#reviewErrors");
    const reviewComments = document.querySelector("#reviewComments");
    const readmeBranchSelect = document.querySelector("#readmeBranchSelect");
    const analyzeReadmeButton = document.querySelector("#analyzeReadme");
    const applyReadmeUpdateButton = document.querySelector("#applyReadmeUpdate");
    const readmeStatus = document.querySelector("#readmeStatus");
    const readmeVerdict = document.querySelector("#readmeVerdict");
    const readmeDiff = document.querySelector("#readmeDiff");

    let proposedTasks = [];
    let notionEnabled = false;
    let calendarEnabled = false;
    let selectedRepository = { owner: "", repo: "", installation_id: "" };
    let branchesLoaded = false;
    let currentBranch = "";
    let allFiles = [];
    let selectedFilePath = "";
<<<<<<< HEAD
    let readmeBranchesLoaded = false;
    let readmeCurrentBranch = "";
    let readmeProposal = null;
=======
    let lastReviewResult = null;
>>>>>>> 2a1c1985d0f87104b616d9facf9e684a4710e80f
    let calendarView = "list";
    let loadedCalendarEvents = [];

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
      if (!selectedRepository.owner || !selectedRepository.repo) {
        status.textContent = "GitHub 연결 필요";
        answer.innerHTML = "<span class='error'>GitHub 연결 후 저장소를 선택해야 분석을 시작할 수 있습니다.</span>";
      }
      connectGithub.textContent = config.github_user ? `@${config.github_user}` : "GitHub 연결";
      connectGoogle.textContent = config.google_user ? `Calendar: ${config.google_user}` : "Google Calendar 연결";
      installGithub.hidden = Boolean((config.repositories || []).length);
      document.querySelector("#backend").textContent = config.backend;
      document.querySelector("#model").textContent = config.model;
      notionEnabled = Boolean(config.notion_enabled);
      calendarEnabled = Boolean(config.calendar_enabled);
      document.querySelector("#notion").textContent = notionEnabled ? "notion on" : "notion off";
      document.querySelector("#calendar").textContent = calendarEnabled ? "calendar on" : "calendar off";
      renderNotionDatabases(config.notion_databases || [], config.notion_database_id || "", Boolean(config.notion_workspace));
      renderNotionPages(config.notion_pages || [], config.notion_page_id || "", Boolean(config.notion_workspace));
      googleCalendarLink.href = calendarEnabled ? "https://calendar.google.com/calendar/u/0/r" : "/auth/google";
      await loadCalendarEvents();
      renderMembers(config.members || [], config.member_warnings || []);
      if (selectedRepository.owner !== config.owner || selectedRepository.repo !== config.repo) {
        await loadMembers(selectedRepository.owner, selectedRepository.repo);
      }
      refreshApproveButtons();
    }

    async function loadCalendarEvents() {
      if (!calendarEnabled) {
        calendarEvents.innerHTML = "<span class='chip'>Google Calendar 연결 필요</span>";
        return;
      }
      calendarEvents.innerHTML = "<span class='chip'>일정 불러오는 중...</span>";
      try {
        const response = await fetch("/api/calendar-events");
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Calendar request failed");
        }
        loadedCalendarEvents = payload.events || [];
        renderCalendarView();
      } catch (error) {
        calendarEvents.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    }

    function renderNotionDatabases(databases, selectedDatabaseId, notionConnected) {
      notionDatabaseSelect.innerHTML = "";
      if (!databases.length) {
        notionDatabaseField.hidden = true;
        createNotionDatabase.hidden = !notionConnected;
      } else {
        databases.forEach((database) => {
          const option = document.createElement("option");
          option.value = database.id;
          option.textContent = database.title || "Untitled database";
          option.selected = database.id === selectedDatabaseId;
          notionDatabaseSelect.appendChild(option);
        });
        notionDatabaseField.hidden = false;
        createNotionDatabase.hidden = !notionConnected;
      }
      notionSaveModeField.hidden = !notionConnected;
    }

    function renderNotionPages(pages, selectedPageId, notionConnected) {
      notionPageSelect.innerHTML = "";
      if (!pages.length) {
        notionPageField.hidden = true;
        return;
      }
      pages.forEach((page) => {
        const option = document.createElement("option");
        option.value = page.id;
        option.textContent = page.title || "Untitled page";
        option.selected = page.id === selectedPageId;
        notionPageSelect.appendChild(option);
      });
      notionPageField.hidden = false;
    }

    function renderCalendarView() {
      calendarListView.classList.toggle("active", calendarView === "list");
      calendarMonthView.classList.toggle("active", calendarView === "month");
      if (calendarView === "month") {
        renderCalendarMonth(loadedCalendarEvents);
      } else {
        renderCalendarEvents(loadedCalendarEvents);
      }
    }

    function renderCalendarEvents(events) {
      calendarEvents.innerHTML = "";
      if (!events.length) {
        calendarEvents.innerHTML = "<span class='chip'>다가오는 일정 없음</span>";
        return;
      }
      events.forEach((event) => {
        const item = document.createElement(event.html_link ? "a" : "div");
        item.className = "calendar-event";
        if (event.html_link) {
          item.href = event.html_link;
          item.target = "_blank";
          item.rel = "noreferrer";
        }
        item.innerHTML = `
          <strong>${escapeHtml(event.title || "(제목 없음)")}</strong>
          <span>${escapeHtml(formatCalendarDate(event.start))}</span>
        `;
        calendarEvents.appendChild(item);
      });
    }

    function renderCalendarMonth(events) {
      calendarEvents.innerHTML = "";
      if (!events.length) {
        calendarEvents.innerHTML = "<span class='chip'>달력에 표시할 일정 없음</span>";
        return;
      }
      const anchor = firstEventDate(events) || new Date();
      const year = anchor.getFullYear();
      const month = anchor.getMonth();
      const first = new Date(year, month, 1);
      const start = new Date(first);
      start.setDate(first.getDate() - first.getDay());
      const byDate = groupEventsByDate(events);
      const wrapper = document.createElement("div");
      wrapper.className = "mini-calendar";
      wrapper.innerHTML = `
        <div class="mini-calendar-title">${year}.${String(month + 1).padStart(2, "0")}</div>
        <div class="mini-calendar-grid" id="miniCalendarGrid"></div>
      `;
      calendarEvents.appendChild(wrapper);
      const grid = wrapper.querySelector("#miniCalendarGrid");
      ["일", "월", "화", "수", "목", "금", "토"].forEach((day) => {
        const label = document.createElement("div");
        label.className = "mini-calendar-day-name";
        label.textContent = day;
        grid.appendChild(label);
      });
      for (let index = 0; index < 42; index += 1) {
        const date = new Date(start);
        date.setDate(start.getDate() + index);
        const key = toDateKey(date);
        const cell = document.createElement("div");
        cell.className = `mini-calendar-cell${date.getMonth() === month ? "" : " muted-cell"}`;
        cell.innerHTML = `<div class="mini-calendar-date">${date.getDate()}</div>`;
        (byDate.get(key) || []).slice(0, 2).forEach((event) => {
          const item = document.createElement(event.html_link ? "a" : "span");
          item.className = "mini-calendar-item";
          item.textContent = event.title || "(제목 없음)";
          if (event.html_link) {
            item.href = event.html_link;
            item.target = "_blank";
            item.rel = "noreferrer";
          }
          cell.appendChild(item);
        });
        const hiddenCount = Math.max((byDate.get(key) || []).length - 2, 0);
        if (hiddenCount) {
          const more = document.createElement("span");
          more.className = "mini-calendar-item";
          more.textContent = `+${hiddenCount}`;
          cell.appendChild(more);
        }
        grid.appendChild(cell);
      }
    }

    function groupEventsByDate(events) {
      const grouped = new Map();
      events.forEach((event) => {
        const key = eventDateKey(event);
        if (!key) {
          return;
        }
        const items = grouped.get(key) || [];
        items.push(event);
        grouped.set(key, items);
      });
      return grouped;
    }

    function firstEventDate(events) {
      for (const event of events) {
        const key = eventDateKey(event);
        if (key) {
          return new Date(`${key}T00:00:00`);
        }
      }
      return null;
    }

    function eventDateKey(event) {
      const value = event.start || "";
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return value;
      }
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return "";
      }
      return toDateKey(parsed);
    }

    function toDateKey(date) {
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    }

    function formatCalendarDate(value) {
      if (!value) {
        return "날짜 없음";
      }
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return value;
      }
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return value;
      }
      return parsed.toLocaleString("ko-KR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
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
      branchesLoaded = false;
      readmeBranchesLoaded = false;
      await loadMembers(owner, repo);
      if (!codeReviewView.hidden) {
        await loadBranches();
      }
      if (!readmeUpdateView.hidden) {
        await loadReadmeBranches();
      }
    });

    function switchTab(target) {
      taskPlannerView.hidden = target !== "taskPlanner";
      codeReviewView.hidden = target !== "codeReview";
      readmeUpdateView.hidden = target !== "readmeUpdate";
      tabTaskPlanner.classList.toggle("active", target === "taskPlanner");
      tabCodeReview.classList.toggle("active", target === "codeReview");
      tabReadmeUpdate.classList.toggle("active", target === "readmeUpdate");
      if (target === "codeReview" && !branchesLoaded) {
        loadBranches();
      }
      if (target === "readmeUpdate" && !readmeBranchesLoaded) {
        loadReadmeBranches();
      }
    }

    tabTaskPlanner.addEventListener("click", () => switchTab("taskPlanner"));
    tabCodeReview.addEventListener("click", () => switchTab("codeReview"));
    tabReadmeUpdate.addEventListener("click", () => switchTab("readmeUpdate"));

    async function loadBranches() {
      if (!selectedRepository.owner || !selectedRepository.repo) {
        branchSelect.innerHTML = "<option value=''>먼저 저장소를 연결하세요</option>";
        return;
      }
      branchSelect.innerHTML = "<option value=''>브랜치를 불러오는 중...</option>";
      try {
        const params = new URLSearchParams({
          owner: selectedRepository.owner,
          repo: selectedRepository.repo,
          installation_id: selectedRepository.installation_id || "",
        });
        const response = await fetch(`/api/branches?${params.toString()}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        const branches = payload.branches || [];
        branchesLoaded = true;
        if (!branches.length) {
          branchSelect.innerHTML = "<option value=''>브랜치가 없습니다</option>";
          return;
        }
        branchSelect.innerHTML = "";
        branches.forEach((branch) => {
          const option = document.createElement("option");
          option.value = branch.name;
          option.textContent = branch.name;
          branchSelect.appendChild(option);
        });
        currentBranch = branches[0].name;
        await loadFileTree(currentBranch);
      } catch (error) {
        branchSelect.innerHTML = "<option value=''>브랜치를 불러오지 못했습니다</option>";
        reviewStatus.textContent = error.message;
      }
    }

    branchSelect.addEventListener("change", async () => {
      currentBranch = branchSelect.value;
      selectedFilePath = "";
      reviewFile.disabled = true;
      await loadFileTree(currentBranch);
    });

    async function loadFileTree(branch) {
      if (!branch) {
        return;
      }
      fileListEl.innerHTML = "<span class='muted'>파일 목록을 불러오는 중...</span>";
      try {
        const params = new URLSearchParams({
          owner: selectedRepository.owner,
          repo: selectedRepository.repo,
          branch,
          installation_id: selectedRepository.installation_id || "",
        });
        const response = await fetch(`/api/repo-tree?${params.toString()}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        allFiles = payload.files || [];
        renderFileList(payload.truncated);
      } catch (error) {
        fileListEl.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    }

    function renderFileList(truncated) {
      const filterText = fileFilter.value.trim().toLowerCase();
      const filtered = filterText
        ? allFiles.filter((file) => file.path.toLowerCase().includes(filterText))
        : allFiles;

      if (!filtered.length) {
        fileListEl.innerHTML = "<span class='muted'>표시할 파일이 없습니다.</span>";
        return;
      }

      fileListEl.innerHTML = "";
      if (truncated) {
        const notice = document.createElement("div");
        notice.className = "muted";
        notice.style.padding = "6px 10px";
        notice.textContent = "저장소가 커서 일부 파일만 표시됩니다.";
        fileListEl.appendChild(notice);
      }
      filtered.forEach((file) => {
        const div = document.createElement("div");
        div.className = "file-item" + (file.path === selectedFilePath ? " selected" : "");
        div.textContent = file.path;
        div.addEventListener("click", () => {
          selectedFilePath = file.path;
          reviewFile.disabled = false;
          fileListEl.querySelectorAll(".file-item").forEach((el) => el.classList.remove("selected"));
          div.classList.add("selected");
        });
        fileListEl.appendChild(div);
      });
    }

    fileFilter.addEventListener("input", () => renderFileList(false));

    function renderReviewErrors(errors) {
      if (!errors || !errors.length) {
        reviewErrors.innerHTML = "<span class='muted'>발견된 오류가 없습니다.</span>";
        return;
      }
      reviewErrors.innerHTML = "";
      errors.forEach((item) => {
        const div = document.createElement("div");
        div.className = "task error-card";
        div.innerHTML = `
          <div class="task-title">${escapeHtml(item.file || "")}${item.line ? `:${item.line}` : ""}</div>
          <div>${escapeHtml(item.issue || "")}</div>
          <div class="muted" style="margin-top:6px;"><strong>수정 방법:</strong> ${escapeHtml(item.fix || "")}</div>
        `;
        reviewErrors.appendChild(div);
      });
    }

    function renderReviewComments(comments) {
      if (!comments || !comments.length) {
        reviewComments.innerHTML = "<span class='muted'>코멘트가 없습니다.</span>";
        return;
      }
      reviewComments.innerHTML = "";
      comments.forEach((item) => {
        const div = document.createElement("div");
        div.className = `task comment-card ${item.type === "bad" ? "bad" : "good"}`;
        div.innerHTML = `
          <span class="badge ${item.type === "bad" ? "bad" : "good"}">${item.type === "bad" ? "개선 필요" : "잘한 점"}</span>
          ${item.file ? `<span class="tag" style="margin-left:6px;">${escapeHtml(item.file)}</span>` : ""}
          <div style="margin-top:6px;">${escapeHtml(item.comment || "")}</div>
        `;
        reviewComments.appendChild(div);
      });
    }

    async function reviewSelectedFile() {
      if (!selectedFilePath) {
        reviewStatus.textContent = "리뷰할 파일을 선택하세요";
        return;
      }
      reviewFile.disabled = true;
      reviewStatus.textContent = "Reviewing file...";
      reviewSummary.textContent = "파일 코드를 분석하는 중입니다.";
      reviewErrors.innerHTML = "<span class='muted'>분석 중...</span>";
      reviewComments.innerHTML = "<span class='muted'>분석 중...</span>";
      try {
        const response = await fetch("/api/review-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            owner: selectedRepository.owner,
            repo: selectedRepository.repo,
            installation_id: selectedRepository.installation_id,
            branch: currentBranch,
            path: selectedFilePath,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        reviewSummary.textContent = payload.summary || "요약이 없습니다.";
        renderReviewErrors(payload.errors || []);
        renderReviewComments(payload.comments || []);
        lastReviewResult = payload;
        saveReviewNotion.disabled = !notionEnabled;
        reviewStatus.textContent = "Done";
      } catch (error) {
        reviewSummary.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
        reviewErrors.innerHTML = "<span class='muted'>리뷰에 실패했습니다.</span>";
        reviewComments.innerHTML = "<span class='muted'>리뷰에 실패했습니다.</span>";
        reviewStatus.textContent = "Error";
      } finally {
        reviewFile.disabled = false;
      }
    }

    reviewFile.addEventListener("click", reviewSelectedFile);

    async function saveReviewToNotion() {
      if (!lastReviewResult) {
        reviewStatus.textContent = "리뷰할 파일을 선택하세요.";
        return;
      }
      saveReviewNotion.disabled = true;
      reviewStatus.textContent = "Saving review to Notion...";
      try {
        const response = await fetch("/api/save-review-to-notion", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            review: lastReviewResult,
            page_id: notionPageSelect.value,
            save_mode: notionSaveMode.value === "checklist" ? "checklist" : "page",
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        const url = payload.url ? `: ${payload.url}` : "";
        reviewStatus.textContent = `Saved to Notion${url}`;
      } catch (error) {
        reviewStatus.textContent = "Error";
        reviewSummary.innerHTML += `<br><span class="error">${escapeHtml(error.message)}</span>`;
      } finally {
        saveReviewNotion.disabled = !notionEnabled || !lastReviewResult;
      }
    }

    saveReviewNotion.addEventListener("click", saveReviewToNotion);

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
      saveReviewNotion.disabled = !notionEnabled || !lastReviewResult;
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
      return;
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
      if (!selectedRepository.owner || !selectedRepository.repo) {
        status.textContent = "GitHub 연결 필요";
        answer.innerHTML = "<span class='error'>먼저 GitHub에 연결하고 분석할 저장소를 선택해주세요.</span>";
        tasks.innerHTML = "<span class='muted'>저장소가 선택되면 GitHub 기록을 분석할 수 있습니다.</span>";
        connectGithub.focus();
        return;
      }
      if (!text) {
        question.focus();
        return;
      }
      analyze.disabled = true;
      approveNotion.disabled = true;
      approveCalendar.disabled = true;
      status.textContent = "Analyzing GitHub...";
      answer.textContent = "GitHub MCP/API 기록에서 팀원, 작업 성향, 마감일 후보를 분석하는 중입니다.";
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
          body: JSON.stringify({
            tasks: items,
            save_mode: notionSaveMode.value,
            page_id: notionPageSelect.value,
            answer: answer.textContent,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        const count = (payload.created || []).length;
        const links = (payload.created || [])
          .filter((item) => item.url)
          .map((item, index) => `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Notion에서 열기 ${index + 1}</a>`)
          .join("<br>");
        answer.innerHTML += `<br><br>${escapeHtml(successText)}: ${count}?${links ? "<br>" + links : ""}`;
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
    notionDatabaseSelect.addEventListener("change", async () => {
      const databaseId = notionDatabaseSelect.value;
      if (!databaseId) return;
      await fetch("/api/select-notion-database", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ database_id: databaseId }),
      });
      notionEnabled = true;
      document.querySelector("#notion").textContent = "notion on";
      refreshApproveButtons();
    });
    createNotionDatabase.addEventListener("click", async () => {
      createNotionDatabase.disabled = true;
      status.textContent = "Creating Notion database...";
      try {
        const response = await fetch("/api/create-notion-database", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: "AI Agent Tasks" }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Failed to create Notion database");
        renderNotionDatabases(payload.databases || [], payload.database_id || "", true);
        notionEnabled = true;
        document.querySelector("#notion").textContent = "notion on";
        status.textContent = "Notion database ready";
        refreshApproveButtons();
      } catch (error) {
        status.textContent = "Error";
        answer.innerHTML += `<br><span class="error">${escapeHtml(error.message)}</span>`;
      } finally {
        createNotionDatabase.disabled = false;
      }
    });

    calendarListView.addEventListener("click", () => {
      calendarView = "list";
      renderCalendarView();
    });
    calendarMonthView.addEventListener("click", () => {
      calendarView = "month";
      renderCalendarView();
    });
    question.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        analyzeGithub();
      }
    });
    async function loadReadmeBranches() {
      if (!selectedRepository.owner || !selectedRepository.repo) {
        readmeBranchSelect.innerHTML = "<option value=''>먼저 저장소를 연결하세요</option>";
        return;
      }
      readmeBranchSelect.innerHTML = "<option value=''>브랜치를 불러오는 중...</option>";
      try {
        const params = new URLSearchParams({
          owner: selectedRepository.owner,
          repo: selectedRepository.repo,
          installation_id: selectedRepository.installation_id || "",
        });
        const response = await fetch(`/api/branches?${params.toString()}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        const branches = payload.branches || [];
        readmeBranchesLoaded = true;
        if (!branches.length) {
          readmeBranchSelect.innerHTML = "<option value=''>브랜치가 없습니다</option>";
          return;
        }
        readmeBranchSelect.innerHTML = "";
        branches.forEach((branch) => {
          const option = document.createElement("option");
          option.value = branch.name;
          option.textContent = branch.name;
          readmeBranchSelect.appendChild(option);
        });
        readmeCurrentBranch = branches[0].name;
      } catch (error) {
        readmeBranchSelect.innerHTML = "<option value=''>브랜치를 불러오지 못했습니다</option>";
        readmeStatus.textContent = error.message;
      }
    }

    readmeBranchSelect.addEventListener("change", () => {
      readmeCurrentBranch = readmeBranchSelect.value;
      readmeProposal = null;
      applyReadmeUpdateButton.disabled = true;
    });

    function renderReadmeDiff(diff, fallbackText) {
      if (!diff || !diff.length) {
        readmeDiff.textContent = fallbackText || "-";
        return;
      }
      readmeDiff.innerHTML = diff.map((line) => {
        const prefix = line.type === "add" ? "+ " : line.type === "remove" ? "- " : "  ";
        const cls = line.type === "add" ? "diff-add" : line.type === "remove" ? "diff-remove" : "";
        return `<div class="${cls}">${escapeHtml(prefix + line.text)}</div>`;
      }).join("");
    }

    async function analyzeReadme() {
      if (!readmeCurrentBranch) {
        readmeStatus.textContent = "브랜치를 먼저 선택하세요";
        return;
      }
      analyzeReadmeButton.disabled = true;
      applyReadmeUpdateButton.disabled = true;
      readmeProposal = null;
      readmeStatus.textContent = "Analyzing...";
      readmeVerdict.textContent = "분석 중입니다...";
      readmeDiff.textContent = "-";
      try {
        const response = await fetch("/api/analyze-readme", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            owner: selectedRepository.owner,
            repo: selectedRepository.repo,
            installation_id: selectedRepository.installation_id || "",
            branch: readmeCurrentBranch,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        renderReadmeDiff(payload.diff, payload.current_readme);
        if (!payload.relevant) {
          readmeVerdict.textContent = `이번 최신 커밋(${payload.commit_message || ""})은 README 갱신이 필요하지 않다고 판단했습니다.`;
        } else if (!payload.changed) {
          readmeVerdict.textContent = "관련 변경이지만 재작성 결과가 기존 README와 동일합니다.";
        } else {
          readmeVerdict.textContent = payload.summary || "README 갱신이 필요합니다.";
          readmeProposal = payload;
          applyReadmeUpdateButton.disabled = false;
        }
        readmeStatus.textContent = "Done";
      } catch (error) {
        readmeVerdict.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
        readmeStatus.textContent = "Error";
      } finally {
        analyzeReadmeButton.disabled = false;
      }
    }

    async function applyReadmeUpdate() {
      if (!readmeProposal) {
        return;
      }
      applyReadmeUpdateButton.disabled = true;
      readmeStatus.textContent = "Creating PR...";
      try {
        const response = await fetch("/api/apply-readme-update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            owner: selectedRepository.owner,
            repo: selectedRepository.repo,
            installation_id: selectedRepository.installation_id || "",
            base_branch: readmeCurrentBranch,
            readme_content: readmeProposal.proposed_readme,
            summary: readmeProposal.summary,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        readmeVerdict.innerHTML = `PR이 생성되었습니다: <a href="${escapeHtml(payload.pr_url)}" target="_blank" rel="noopener">${escapeHtml(payload.pr_url)}</a>`;
        readmeStatus.textContent = "PR created";
        readmeProposal = null;
      } catch (error) {
        readmeVerdict.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
        readmeStatus.textContent = "Error";
        applyReadmeUpdateButton.disabled = false;
      }
    }

    analyzeReadmeButton.addEventListener("click", analyzeReadme);
    applyReadmeUpdateButton.addEventListener("click", applyReadmeUpdate);

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
        if parsed_url.path == "/auth/notion":
            self._redirect_to_notion_login()
            return
        if parsed_url.path == "/auth/notion/callback":
            self._handle_notion_callback(parsed_url.query)
            return
        if parsed_url.path == "/api/config":
            session = self._session()
            notion_databases = _load_notion_databases(session)
            notion_pages = _load_notion_pages(session)
            if session.get("notion_access_token") and not session.get("notion_database_id") and notion_databases:
                session["notion_database_id"] = notion_databases[0]["id"]
            if session.get("notion_access_token") and not session.get("notion_page_id") and notion_pages:
                session["notion_page_id"] = notion_pages[0]["id"]
            notion = NotionToolClient(
                token=str(session.get("notion_access_token") or "") or None,
                database_id=str(session.get("notion_database_id") or "") or None,
            )
            calendar = GoogleCalendarToolClient()
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
                    "notion_workspace": session.get("notion_workspace_name", ""),
                    "notion_database_id": session.get("notion_database_id", notion.config.database_id),
                    "notion_databases": notion_databases,
                    "notion_page_id": session.get("notion_page_id", ""),
                    "notion_pages": notion_pages,
                    "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    "backend": "github-mcp",
                    "notion_enabled": notion.enabled or bool(session.get("notion_access_token")),
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
        if parsed_url.path == "/api/calendar-events":
            self._handle_calendar_events()
            return
        if parsed_url.path == "/api/branches":
            self._handle_list_branches(parsed_url.query)
            return
        if parsed_url.path == "/api/repo-tree":
            self._handle_repo_tree(parsed_url.query)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/analyze-tasks":
            self._handle_analyze_tasks()
            return
        if self.path == "/api/approve-tasks":
            self._handle_approve_tasks()
            return
        if self.path == "/api/select-notion-database":
            self._handle_select_notion_database()
            return
        if self.path == "/api/create-notion-database":
            self._handle_create_notion_database()
            return
        if self.path == "/api/save-review-to-notion":
            self._handle_save_review_to_notion()
            return
        if self.path == "/api/approve-calendar-events":
            self._handle_approve_calendar_events()
            return
        if self.path == "/api/review-file":
            self._handle_review_file()
            return
        if self.path == "/api/analyze-readme":
            self._handle_analyze_readme()
            return
        if self.path == "/api/apply-readme-update":
            self._handle_apply_readme_update()
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
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_calendar_events(self) -> None:
        try:
            google_access_token = str(self._session().get("google_access_token") or "")
            if not google_access_token:
                self._send_json(
                    {"error": "Google Calendar 연결 후 다시 시도해 주세요."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            calendar = GoogleCalendarToolClient(mcp_auth_token=google_access_token or None)
            self._send_json(
                {
                    "calendar_url": "https://calendar.google.com/calendar/u/0/r",
                    "events": calendar.list_upcoming_events(),
                }
            )
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_approve_tasks(self) -> None:
        try:
            payload = self._read_json()
            tasks = payload.get("tasks", [])
            save_mode = str(payload.get("save_mode") or "database").strip()
            page_id = str(payload.get("page_id") or "").strip()
            answer_text = str(payload.get("answer") or "").strip()
            if not isinstance(tasks, list) or not tasks:
                self._send_json({"error": "tasks are required"}, HTTPStatus.BAD_REQUEST)
                return
            session = self._session()
            notion_token = str(session.get("notion_access_token") or "")
            notion_database_id = str(session.get("notion_database_id") or "")
            if not notion_token and not os.environ.get("NOTION_API_KEY") and not os.environ.get("NOTION_TOKEN"):
                self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            if save_mode in {"page", "checklist"}:
                if not notion_token:
                    self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                    return
                if not page_id:
                    pages = _load_notion_pages(session)
                    if pages:
                        page_id = pages[0]["id"]
                        session["notion_page_id"] = page_id
                if not page_id:
                    self._send_json({"error": "Notion에 기록할 위치를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                    return
                result = asyncio.run(
                    create_notion_report(
                        tasks,
                        body=answer_text,
                        title="AI Agent 작업 분석 기록",
                        checklist=save_mode == "checklist",
                        notion_token=notion_token,
                        notion_page_id=page_id,
                    )
                )
                self._send_json(result)
                return
            if notion_token and not notion_database_id:
                databases = _load_notion_databases(session)
                if databases:
                    notion_database_id = databases[0]["id"]
                    session["notion_database_id"] = notion_database_id
                else:
                    notion = NotionToolClient(token=notion_token, database_id="placeholder")
                    pages = notion.list_pages()
                    if not pages:
                        self._send_json({"error": "Notion 데이터베이스를 만들 페이지를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                        return
                    created_database = notion.create_task_database(parent_page_id=pages[0]["id"], title="AI Agent Tasks")
                    notion_database_id = created_database["id"]
                    session["notion_database_id"] = notion_database_id
            result = asyncio.run(create_notion_tasks(tasks, notion_token=notion_token, notion_database_id=notion_database_id))
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_select_notion_database(self) -> None:
        try:
            payload = self._read_json()
            database_id = str(payload.get("database_id") or "").strip()
            if not database_id:
                self._send_json({"error": "database_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            self._session()["notion_database_id"] = database_id
            self._send_json({"selected": True, "database_id": database_id})
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_create_notion_database(self) -> None:
        try:
            session = self._session()
            token = str(session.get("notion_access_token") or "")
            if not token:
                self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            payload = self._read_json()
            title = str(payload.get("title") or "AI Agent Tasks").strip()
            notion = NotionToolClient(token=token, database_id="placeholder")
            pages = notion.list_pages()
            if not pages:
                self._send_json({"error": "Notion 데이터베이스를 만들 페이지를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            database = notion.create_task_database(parent_page_id=pages[0]["id"], title=title)
            database_id = database.get("id", "")
            if not database_id:
                raise ValueError("Notion database creation did not return an id.")
            session["notion_database_id"] = database_id
            databases = _load_notion_databases(session)
            self._send_json({"created": True, "database_id": database_id, "database": database, "databases": databases})
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_save_review_to_notion(self) -> None:
        try:
            payload = self._read_json()
            review = payload.get("review")
            if not isinstance(review, dict):
                self._send_json({"error": "review is required"}, HTTPStatus.BAD_REQUEST)
                return
            session = self._session()
            notion_token = str(session.get("notion_access_token") or "")
            if not notion_token:
                self._send_json({"error": "Notion 연결이 필요합니다."}, HTTPStatus.UNAUTHORIZED)
                return
            page_id = str(payload.get("page_id") or session.get("notion_page_id") or "").strip()
            if not page_id:
                pages = _load_notion_pages(session)
                if pages:
                    page_id = pages[0]["id"]
                    session["notion_page_id"] = page_id
            if not page_id:
                self._send_json({"error": "Notion에 기록할 페이지를 찾을 수 없습니다."}, HTTPStatus.BAD_REQUEST)
                return
            save_mode = str(payload.get("save_mode") or "page").strip()
            result = asyncio.run(create_notion_report([], title="AI Agent 코드 리뷰 기록", review=review, checklist=save_mode == "checklist", notion_token=notion_token, notion_page_id=page_id))
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_list_branches(self, query_string: str) -> None:
        try:
            query = parse_qs(query_string)
            owner = (query.get("owner") or [""])[0].strip()
            repo = (query.get("repo") or [""])[0].strip()
            installation_id = (query.get("installation_id") or [""])[0].strip()
            if not owner or not repo:
                repositories = _load_repositories(self._session())
                owner, repo, installation_id = _select_default_repository(repositories)
            session_token = str(self._session().get("github_access_token") or "")
            branches = asyncio.run(
                code_review.list_branches(
                    owner,
                    repo,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json({"branches": branches})
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_repo_tree(self, query_string: str) -> None:
        try:
            query = parse_qs(query_string)
            owner = (query.get("owner") or [""])[0].strip()
            repo = (query.get("repo") or [""])[0].strip()
            branch = (query.get("branch") or [""])[0].strip()
            installation_id = (query.get("installation_id") or [""])[0].strip()
            if not owner or not repo:
                repositories = _load_repositories(self._session())
                owner, repo, installation_id = _select_default_repository(repositories)
            if not branch:
                self._send_json({"error": "branch is required"}, HTTPStatus.BAD_REQUEST)
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                code_review.list_repo_tree(
                    owner,
                    repo,
                    branch,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_review_file(self) -> None:
        try:
            payload = self._read_json()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            branch = str(payload.get("branch", "")).strip()
            path = str(payload.get("path", "")).strip()
            if not owner or not repo or not branch or not path:
                self._send_json(
                    {"error": "owner, repo, branch, path are required"}, HTTPStatus.BAD_REQUEST
                )
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                code_review.review_file(
                    owner,
                    repo,
                    branch,
                    path,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_analyze_readme(self) -> None:
        try:
            payload = self._read_json()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            branch = str(payload.get("branch", "")).strip()
            if not owner or not repo or not branch:
                self._send_json(
                    {"error": "owner, repo, branch are required"}, HTTPStatus.BAD_REQUEST
                )
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                readme_review.analyze_readme_update(
                    owner,
                    repo,
                    branch,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_apply_readme_update(self) -> None:
        try:
            payload = self._read_json()
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            installation_id = str(payload.get("installation_id", "")).strip()
            base_branch = str(payload.get("base_branch", "")).strip()
            readme_content = str(payload.get("readme_content", ""))
            summary = str(payload.get("summary", ""))
            if not owner or not repo or not base_branch or not readme_content:
                self._send_json(
                    {"error": "owner, repo, base_branch, readme_content are required"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            session_token = str(self._session().get("github_access_token") or "")
            result = asyncio.run(
                readme_review.apply_readme_update(
                    owner,
                    repo,
                    base_branch,
                    readme_content,
                    summary,
                    installation_id=installation_id,
                    session_token=session_token,
                )
            )
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
            google_access_token = str(self._session().get("google_access_token") or "")
            if not google_access_token:
                self._send_json(
                    {"error": "Google Calendar 연결 후 다시 등록해 주세요."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            result = asyncio.run(
                create_calendar_events(
                    tasks,
                    google_access_token=google_access_token,
                )
            )
            self._send_json(result)
        except Exception as error:
            self._send_json({"error": _friendly_error(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
                "scope": os.environ.get(
                    "GOOGLE_OAUTH_SCOPES",
                    "https://www.googleapis.com/auth/calendar "
                    "https://www.googleapis.com/auth/userinfo.email",
                ),
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        self._redirect(
            f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
            session_id,
            extra_cookies={"google_oauth_state": state},
        )

    def _handle_google_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not session_id and state and self._cookie("google_oauth_state") == state:
            session_id = self._session_id()
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

    def _redirect_to_notion_login(self) -> None:
        client_id = os.environ.get("NOTION_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            self._send_json({"error": "NOTION_OAUTH_CLIENT_ID is required for Notion login."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        session_id = self._session_id()
        state = secrets.token_urlsafe(24)
        OAUTH_STATES[state] = session_id
        params = urlencode(
            {
                "owner": "user",
                "client_id": client_id,
                "redirect_uri": _notion_base_url() + "/auth/notion/callback",
                "response_type": "code",
                "state": state,
            }
        )
        auth_url = os.environ.get("NOTION_AUTH_URL", "https://api.notion.com/v1/oauth/authorize").strip()
        self._redirect(f"{auth_url}?{params}", session_id, extra_cookies={"notion_oauth_state": state})

    def _handle_notion_callback(self, query_string: str) -> None:
        query = parse_qs(query_string)
        error = (query.get("error") or [""])[0]
        if error:
            self._send_json({"error": f"Notion authorization failed: {error}"}, HTTPStatus.BAD_REQUEST)
            return
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        session_id = OAUTH_STATES.pop(state, "")
        if not session_id and state and self._cookie("notion_oauth_state") == state:
            session_id = self._session_id()
        if not code or not session_id:
            self._send_json({"error": "Invalid Notion OAuth callback."}, HTTPStatus.BAD_REQUEST)
            return
        token_payload = _exchange_notion_code(code)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            self._send_json({"error": "Notion OAuth did not return access_token."}, HTTPStatus.BAD_REQUEST)
            return
        session = SESSIONS.setdefault(session_id, {})
        session["notion_access_token"] = access_token
        if token_payload.get("refresh_token"):
            session["notion_refresh_token"] = str(token_payload.get("refresh_token"))
        session["notion_workspace_id"] = str(token_payload.get("workspace_id") or "")
        session["notion_workspace_name"] = str(token_payload.get("workspace_name") or "Notion")
        databases = _load_notion_databases(session)
        pages = _load_notion_pages(session)
        if databases:
            session["notion_database_id"] = databases[0]["id"]
        if pages:
            session["notion_page_id"] = pages[0]["id"]
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

    def _cookie(self, cookie_name: str) -> str:
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == cookie_name:
                return value
        return ""

    def _redirect(
        self,
        location: str,
        session_id: str | None = None,
        extra_cookies: dict[str, str] | None = None,
    ) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        if session_id:
            self.send_header(
                "Set-Cookie",
                f"github_ai_agent_session={session_id}; Path=/; HttpOnly; SameSite=Lax",
            )
        for name, value in (extra_cookies or {}).items():
            self.send_header(
                "Set-Cookie",
                f"{name}={value}; Path=/; HttpOnly; SameSite=Lax",
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


async def create_notion_tasks(
    tasks: list[Any],
    *,
    notion_token: str = "",
    notion_database_id: str = "",
) -> dict[str, Any]:
    notion = NotionToolClient(token=notion_token or None, database_id=notion_database_id or None)
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


async def create_notion_report(
    tasks: list[Any],
    *,
    title: str,
    body: str = "",
    review: dict[str, Any] | None = None,
    checklist: bool = False,
    notion_token: str = "",
    notion_page_id: str = "",
) -> dict[str, Any]:
    notion = NotionToolClient(token=notion_token or None, database_id="placeholder")
    normalized_tasks = _normalize_tasks(tasks)
    selected_tools = [
        {
            "tool": "create_notion_report_page",
            "arguments": {
                "title": title,
                "parent_page_id": notion_page_id,
                "task_count": len(normalized_tasks),
                "format": "checklist" if checklist else "document",
            },
        }
    ]
    async with notion:
        page = notion.create_report_page(
            parent_page_id=notion_page_id,
            title=title,
            body=body,
            tasks=normalized_tasks,
            review=review or {},
            checklist=checklist,
        )
    return {"created": [page], "selected_tools": selected_tools, "url": page.get("url", "")}


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
                if "error" in raw.lower() or "forbidden" in raw.lower():
                    raise ValueError(raw)
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


def _notion_base_url() -> str:
    return os.environ.get("NOTION_REDIRECT_BASE_URL", "http://localhost:8787").rstrip("/")


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


def _exchange_notion_code(code: str) -> dict[str, Any]:
    client_id = os.environ.get("NOTION_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NOTION_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("NOTION_OAUTH_CLIENT_ID and NOTION_OAUTH_CLIENT_SECRET are required.")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    data = json.dumps(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _notion_base_url() + "/auth/notion/callback",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.notion.com/v1/oauth/token",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
            "User-Agent": "github-ai-mcp-agent",
        },
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


def _friendly_error(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        parts = [_friendly_error(item) for item in error.exceptions]
        return "; ".join(part for part in parts if part) or str(error)
    return str(error)


def _load_notion_databases(session: dict[str, Any]) -> list[dict[str, str]]:
    token = str(session.get("notion_access_token") or "")
    if not token:
        return []
    try:
        databases = NotionToolClient(token=token, database_id="placeholder").list_databases()
    except Exception:
        return []
    selected = str(session.get("notion_database_id") or "")
    return sorted(
        databases,
        key=lambda database: (
            0 if database.get("id") == selected else 1,
            0 if any(keyword in database.get("title", "").lower() for keyword in ("task", "todo", "할일", "작업")) else 1,
            database.get("title", "").lower(),
        ),
    )


def _load_notion_pages(session: dict[str, Any]) -> list[dict[str, str]]:
    token = str(session.get("notion_access_token") or "")
    if not token:
        return []
    try:
        pages = NotionToolClient(token=token, database_id="placeholder").list_pages()
    except Exception:
        return []
    selected = str(session.get("notion_page_id") or "")
    return sorted(pages, key=lambda page: (0 if page.get("id") == selected else 1, page.get("title", "").lower()))


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
