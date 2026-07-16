const question = document.querySelector("#question");
    const projectDeadline = document.querySelector("#projectDeadline");
    const analyze = document.querySelector("#analyze");
    const approveNotion = document.querySelector("#approveNotion");
    const approveCalendar = document.querySelector("#approveCalendar");
    let answer = document.querySelector("#answer");
    const chatThread = document.querySelector("#chatThread");
    const tasks = document.querySelector("#tasks");
    const status = document.querySelector("#status");
    const repoSelect = document.querySelector("#repoSelect");
    const connectGithub = document.querySelector("#connectGithub");
    const refreshGithubSync = document.querySelector("#refreshGithubSync");
    const githubSyncTime = document.querySelector("#githubSyncTime");
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
    const appShell = document.querySelector("#appShell");

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
    let connectedGoogleUser = "";
    let selectedRepository = { owner: "", repo: "", installation_id: "" };
    let lastGithubSyncAt = null;
    let branchesLoaded = false;
    let currentBranch = "";
    let allFiles = [];
    let selectedFilePath = "";
    let readmeBranchesLoaded = false;
    let readmeCurrentBranch = "";
    let readmeProposal = null;
    let lastReviewResult = null;
    let branchShaBaseline = {};
    let pushPollTimer = null;
    let calendarView = "list";
    let loadedCalendarEvents = [];
    let lastUserQuestion = "";
    let lastAnalysisAnswerText = "";
    let currentNotionSaveMode = "database";
    let shouldCreateNotionDatabaseBeforeSave = false;

    document.querySelectorAll(".example").forEach((button) => {
      button.addEventListener("click", () => {
        question.value = button.dataset.question;
        question.focus();
      });
    });

    function formatRelativeSyncTime(date) {
      if (!date) return "마지막 동기화: 확인 중";
      const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
      if (diffSeconds < 10) return "마지막 동기화: 방금 전";
      if (diffSeconds < 60) return `마지막 동기화: ${diffSeconds}초 전`;
      const diffMinutes = Math.floor(diffSeconds / 60);
      if (diffMinutes < 60) return `마지막 동기화: ${diffMinutes}분 전`;
      const diffHours = Math.floor(diffMinutes / 60);
      return `마지막 동기화: ${diffHours}시간 전`;
    }

    function updateGithubSyncTime() {
      if (!githubSyncTime) return;
      githubSyncTime.textContent = formatRelativeSyncTime(lastGithubSyncAt);
    }

    async function loadConfig() {
      const response = await fetch("/api/config");
      const config = await response.json();
      selectedRepository = readSavedRepository(config);
      renderRepositorySelect(config.repositories || []);
      const selectedRepoLabel = selectedRepository.owner && selectedRepository.repo ? `${selectedRepository.owner}/${selectedRepository.repo}` : "";
      const githubConnected = Boolean(config.github_user);
      if (!selectedRepository.owner || !selectedRepository.repo) {
        status.textContent = "GitHub \uC5F0\uACB0 \uD544\uC694";
        answer.innerHTML = "<span class='error'>GitHub \uC5F0\uACB0 \uD6C4 \uC800\uC7A5\uC18C\uB97C \uC120\uD0DD\uD574\uC57C \uBD84\uC11D\uC744 \uC2DC\uC791\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.</span>";
      }
      connectedGoogleUser = config.google_user || "";
      notionEnabled = Boolean(config.notion_enabled);
      calendarEnabled = Boolean(config.calendar_enabled);
      setServiceCard(connectGithub, selectedRepoLabel || "GitHub 연결", Boolean(selectedRepoLabel || githubConnected));
      setServiceCard(connectNotion, "Notion 연결", notionEnabled);
      setServiceCard(connectGoogle, connectedGoogleUser ? `Calendar: ${connectedGoogleUser}` : "Google Calendar 연결", calendarEnabled);
      const devBypassConnections = new URLSearchParams(window.location.search).get("dev") === "1";
      const readyForDashboard = devBypassConnections || Boolean(selectedRepoLabel);
      if (!readyForDashboard) {
        window.location.replace("/");
        return;
      }
      appShell.classList.remove("is-hidden");
      renderNotionDatabases(config.notion_databases || [], config.notion_database_id || "", notionEnabled);
      renderNotionPages(config.notion_pages || [], config.notion_page_id || "", notionEnabled);
      googleCalendarLink.href = calendarEnabled ? googleCalendarUrl(connectedGoogleUser) : "/auth/google";
      await loadCalendarEvents();
      renderMembers(config.members || [], config.member_warnings || []);
      if (selectedRepository.owner !== config.owner || selectedRepository.repo !== config.repo) {
        await loadMembers(selectedRepository.owner, selectedRepository.repo);
      }
      refreshApproveButtons();
      if (selectedRepository.owner && selectedRepository.repo) {
        startPushPolling();
      }
      lastGithubSyncAt = new Date();
      updateGithubSyncTime();
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
        const option = document.createElement("option");
        option.value = "";
        option.textContent = notionConnected ? "Notion 연결됨 - 선택 가능한 DB 없음" : "Notion 연결 필요";
        notionDatabaseSelect.appendChild(option);
        notionDatabaseSelect.disabled = true;
        notionDatabaseField.hidden = !notionConnected;
      } else {
        notionDatabaseSelect.disabled = false;
        databases.forEach((database) => {
          const option = document.createElement("option");
          option.value = database.id;
          option.textContent = database.title || "Untitled database";
          option.selected = database.id === selectedDatabaseId;
          notionDatabaseSelect.appendChild(option);
        });
        notionDatabaseField.hidden = false;
      }
      if (createNotionDatabase) {
        createNotionDatabase.hidden = !notionConnected;
      }
      if (notionSaveModeField) {
        notionSaveModeField.hidden = true;
      }
    }

    function renderNotionPages(pages, selectedPageId, notionConnected) {
      notionPageSelect.innerHTML = "";
      if (!pages.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = notionConnected ? "Notion 연결됨 - 선택 가능한 페이지 없음" : "Notion 연결 필요";
        notionPageSelect.appendChild(option);
        notionPageSelect.disabled = true;
        notionPageField.hidden = !notionConnected;
        return;
      }
      notionPageSelect.disabled = false;
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
          item.href = withGoogleAuthUser(event.html_link, connectedGoogleUser);
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
            item.href = withGoogleAuthUser(event.html_link, connectedGoogleUser);
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
      const repositories = config.repositories || [];
      const saved = localStorage.getItem("selectedRepository");
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          const stillAvailable = repositories.some((repository) => (
            repository.owner === parsed.owner && repository.repo === parsed.repo
          ));
          if (parsed.owner && parsed.repo && (!repositories.length || stillAvailable)) {
            return parsed;
          }
        } catch (_) {}
      }
      if (config.owner && config.repo) {
        const matched = repositories.find((repository) => repository.owner === config.owner && repository.repo === config.repo);
        const fallback = {
          owner: config.owner,
          repo: config.repo,
          installation_id: matched ? matched.installation_id || "" : config.installation_id || "",
        };
        localStorage.setItem("selectedRepository", JSON.stringify(fallback));
        return fallback;
      }
      if (repositories.length) {
        const first = repositories[0];
        const fallback = {
          owner: first.owner,
          repo: first.repo,
          installation_id: first.installation_id || "",
        };
        localStorage.setItem("selectedRepository", JSON.stringify(fallback));
        return fallback;
      }
      return { owner: "", repo: "", installation_id: "" };
    }

    function renderRepositorySelect(repositories) {
      const selectedRepoLabel = selectedRepository.owner && selectedRepository.repo ? `${selectedRepository.owner}/${selectedRepository.repo}` : "저장소를 선택해주세요";
      document.querySelector("#repo").textContent = selectedRepoLabel;
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
      startPushPolling();
    });

    if (refreshGithubSync) {
      refreshGithubSync.addEventListener("click", async () => {
        refreshGithubSync.disabled = true;
        refreshGithubSync.classList.add("is-syncing");
        status.textContent = "GitHub 동기화 중...";
        try {
          await loadConfig();
          status.textContent = "GitHub 동기화 완료";
        } catch (error) {
          status.textContent = "동기화 실패";
          if (answer) {
            answer.innerHTML += `<br><span class="error">${escapeHtml(error.message)}</span>`;
          }
        } finally {
          refreshGithubSync.disabled = false;
          refreshGithubSync.classList.remove("is-syncing");
        }
      });
    }

    async function switchTab(target) {
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
        // Callers set the branch right after this returns, so the options must
        // exist by then — a bare call would let them run against an empty select.
        await loadReadmeBranches();
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

    function googleCalendarUrl(email = "") {
      const baseUrl = "https://calendar.google.com/calendar/u/0/r";
      return email ? `${baseUrl}?authuser=${encodeURIComponent(email)}` : baseUrl;
    }

    function withGoogleAuthUser(url, email = "") {
      if (!url || !email) return url;
      try {
        const parsed = new URL(url);
        if (parsed.hostname.endsWith("calendar.google.com")) {
          parsed.searchParams.set("authuser", email);
        }
        return parsed.toString();
      } catch {
        return url;
      }
    }

    function setServiceCard(card, label, connected) {
      if (!card) return;
      const labelEl = card.querySelector(".service-label");
      const statusEl = card.querySelector(".service-status");
      if (labelEl) labelEl.textContent = label;
      if (statusEl) statusEl.textContent = connected ? "연결됨" : "연결 필요";
      card.classList.toggle("is-connected", connected);
    }

    function scrollChatToBottom() {
      if (!chatThread) return;
      chatThread.scrollTop = chatThread.scrollHeight;
    }

    function wait(ms) {
      return new Promise((resolve) => window.setTimeout(resolve, ms));
    }

    function appendUserChatMessage(text) {
      if (!chatThread) return;
      const message = document.createElement("div");
      message.className = "chat-message user";
      message.innerHTML = `
        <div class="chat-bubble">
          <div class="chat-name">나</div>
          <div>${escapeHtml(text)}</div>
        </div>
        <div class="chat-avatar">ME</div>
      `;
      chatThread.appendChild(message);
      scrollChatToBottom();
    }

    function appendAssistantChatMessage(text) {
      if (!chatThread) {
        answer.textContent = text;
        return answer;
      }
      const message = document.createElement("div");
      message.className = "chat-message assistant";
      message.innerHTML = `
        <div class="chat-avatar">AI</div>
        <div class="chat-bubble">
          <div class="chat-name">DEVFLOW AI Agent</div>
          <div class="answer"></div>
        </div>
      `;
      const answerEl = message.querySelector(".answer");
      answerEl.textContent = text;
      chatThread.appendChild(message);
      answer = answerEl;
      scrollChatToBottom();
      return answerEl;
    }

    function refreshApproveButtons() {
      const hasTasks = proposedTasks.length > 0;
      updateNotionSaveModeFromText(lastUserQuestion || question.value || answer.textContent);
      approveNotion.disabled = !canApproveNotion();
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

    function renderTaskEmptyState(message, icon = "☑") {
      tasks.innerHTML = `
        <div class="task-empty-state">
          <span class="empty-illustration">${escapeHtml(icon)}</span>
          <span>${escapeHtml(message)}</span>
        </div>
      `;
    }

    function renderTasks(items) {
      proposedTasks = items || [];
      if (!proposedTasks.length) {
        renderTaskEmptyState("제안된 할 일이 없습니다.");
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

    function inferNotionSaveMode(text) {
      const normalized = (text || "").toLowerCase();
      if (/(체크리스트|체크\s*리스트|checklist|check list|체크박스|todo\s*list)/i.test(normalized)) {
        return "checklist";
      }
      if (/(데이터베이스|database|\bdb\b|표|테이블|행으로|팀원별|담당자별|할\s*일|작업\s*분배|업무\s*분배|db\s*생성|db\s*만들|데이터베이스\s*생성|데이터베이스\s*만들)/i.test(normalized)) {
        return "database";
      }
      if (/(페이지|문서|기록|정리|분석\s*내용|코드\s*리뷰|리뷰\s*내용|본문|노트)/i.test(normalized)) {
        return "page";
      }
      return proposedTasks.length ? "database" : "page";
    }

    function notionSaveModeLabel(mode) {
      if (mode === "checklist") return "체크리스트";
      if (mode === "page") return "페이지 기록";
      return "DB 작업 등록";
    }

    function updateNotionSaveModeFromText(text) {
      currentNotionSaveMode = inferNotionSaveMode(text);
      shouldCreateNotionDatabaseBeforeSave = /(db|데이터베이스).{0,12}(생성|만들|새로|자동)|(?:생성|만들|새로|자동).{0,12}(db|데이터베이스)/i.test(text || "");
      if (notionSaveMode) {
        notionSaveMode.value = currentNotionSaveMode;
      }
      approveNotion.textContent = shouldCreateNotionDatabaseBeforeSave && currentNotionSaveMode === "database"
        ? "Notion DB 생성 후 저장 승인"
        : `Notion ${notionSaveModeLabel(currentNotionSaveMode)} 승인`;
      return currentNotionSaveMode;
    }

    function canApproveNotion() {
      const hasTasks = proposedTasks.length > 0;
      const hasAnswer = Boolean(answer && answer.textContent && answer.textContent.trim());
      return notionEnabled && (hasTasks || (hasAnswer && ["page", "checklist"].includes(currentNotionSaveMode)));
    }

    function isFollowUpNotionSaveRequest(text) {
      const normalized = (text || "").toLowerCase();
      const mentionsNotion = /(notion|노션)/i.test(normalized);
      const asksToSave = /(저장|기록|등록|남겨|올려|업로드|추가)/i.test(normalized);
      const refersPrevious = /(방금|위\s*내용|이\s*내용|이전|아까|분석\s*내용|답변|결과)/i.test(normalized);
      return mentionsNotion && asksToSave && refersPrevious && Boolean(lastAnalysisAnswerText || answer.textContent.trim());
    }

    async function savePreviousAnswerToNotion(text) {
      lastUserQuestion = text;
      const saveMode = updateNotionSaveModeFromText(text);
      appendUserChatMessage(text);
      question.value = "";
      await wait(520);
      const currentAnswer = appendAssistantChatMessage(`방금 분석 내용을 '${notionSaveModeLabel(saveMode)}' 방식으로 Notion에 저장하는 중입니다.`);
      answer = currentAnswer;
      await postSelectedTasks("/api/approve-tasks", "Saving to Notion...", "Notion 등록 완료");
      scrollChatToBottom();
    }

    async function analyzeGithub() {
      const text = question.value.trim();
      if (!text) {
        question.focus();
        return;
      }
      if (isFollowUpNotionSaveRequest(text)) {
        await savePreviousAnswerToNotion(text);
        question.value = "";
        return;
      }
      if (!selectedRepository.owner || !selectedRepository.repo) {
        status.textContent = "GitHub 연결 필요";
        answer.innerHTML = "<span class='error'>먼저 GitHub에 연결하고 분석할 저장소를 선택해주세요.</span>";
        renderTaskEmptyState("저장소가 선택되면 GitHub 기록을 분석할 수 있습니다.", "GH");
        connectGithub.focus();
        return;
      }
      lastUserQuestion = text;
      const requestedNotionMode = updateNotionSaveModeFromText(text);
      appendUserChatMessage(text);
      question.value = "";
      await wait(520);
      const currentAnswer = appendAssistantChatMessage("GitHub MCP/API 기록에서 팀원, 작업 성향, 마감일 후보를 분석하는 중입니다.");
      analyze.disabled = true;
      approveNotion.disabled = true;
      approveCalendar.disabled = true;
      status.textContent = "Analyzing GitHub...";
      renderTaskEmptyState("GitHub 기록을 바탕으로 할 일 후보를 생성하는 중입니다.", "…");

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
        lastAnalysisAnswerText = payload.answer || "";
        const notionHint = `\n\nNotion 저장 방식 판단\n1. 채팅 내용을 기준으로 '${notionSaveModeLabel(requestedNotionMode)}' 방식으로 해석했습니다.\n2. 저장하려면 아래의 'Notion ${notionSaveModeLabel(requestedNotionMode)} 승인' 버튼을 눌러주세요.`;
        currentAnswer.textContent = `${payload.answer}${notionHint}`;
        answer = currentAnswer;
        scrollChatToBottom();
        renderTools(payload.selected_tools || []);
        renderTasks(payload.proposed_tasks || []);
        status.textContent = "Approval required";
      } catch (error) {
        proposedTasks = [];
        currentAnswer.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
        answer = currentAnswer;
        scrollChatToBottom();
        renderTaskEmptyState("할 일 후보를 만들지 못했습니다.", "!");
        status.textContent = "Error";
      } finally {
        analyze.disabled = false;
        refreshApproveButtons();
      }
    }

    async function postSelectedTasks(url, savingText, successText) {
      const items = selectedTasks();
      const isNotionRequest = url.includes("approve-tasks");
      const saveMode = updateNotionSaveModeFromText(lastUserQuestion || question.value || answer.textContent);
      if (!items.length && (!isNotionRequest || !["page", "checklist"].includes(saveMode))) {
        status.textContent = "No selected tasks";
        return;
      }
      approveNotion.disabled = true;
      approveCalendar.disabled = true;
      analyze.disabled = true;
      status.textContent = savingText;
      try {
        if (isNotionRequest && saveMode === "database" && shouldCreateNotionDatabaseBeforeSave) {
          status.textContent = "Creating Notion database...";
          await createDefaultNotionDatabase("AI Agent Tasks");
          status.textContent = savingText;
        }
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tasks: items,
            save_mode: saveMode,
            page_id: notionPageSelect.value,
            answer: lastAnalysisAnswerText || answer.textContent,
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
        answer.innerHTML += `<br><br>${escapeHtml(successText)} (${escapeHtml(notionSaveModeLabel(saveMode))}): ${count}개${links ? "<br>" + links : ""}`;
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

    async function createDefaultNotionDatabase(title = "AI Agent Tasks") {
      const response = await fetch("/api/create-notion-database", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to create Notion database");
      }
      renderNotionDatabases(payload.databases || [], payload.database_id || "", true);
      notionEnabled = true;
      setServiceCard(connectNotion, "Notion 연결", notionEnabled);
      return payload;
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
      setServiceCard(connectNotion, "Notion 연결", notionEnabled);
      refreshApproveButtons();
    });
    if (createNotionDatabase) {
      createNotionDatabase.addEventListener("click", async () => {
        createNotionDatabase.disabled = true;
        status.textContent = "Creating Notion database...";
        try {
          await createDefaultNotionDatabase("AI Agent Tasks");
          status.textContent = "Notion database ready";
          refreshApproveButtons();
        } catch (error) {
          status.textContent = "Error";
          answer.innerHTML += `<br><span class="error">${escapeHtml(error.message)}</span>`;
        } finally {
          createNotionDatabase.disabled = false;
        }
      });
    }

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
      const rows = diff && diff.length
        ? diff
        : (fallbackText || "").split("\n").map((line) => (
            { left: line, left_type: "equal", right: line, right_type: "equal" }
          ));
      if (!rows.length) {
        readmeDiff.textContent = "-";
        return;
      }
      readmeDiff.innerHTML = rows.map((row) => {
        const leftCls = row.left_type === "remove" ? "diff-remove" : row.left_type === "empty" ? "diff-empty" : "";
        const rightCls = row.right_type === "add" ? "diff-add" : row.right_type === "empty" ? "diff-empty" : "";
        return `<div class="${leftCls}">${escapeHtml(row.left)}</div><div class="${rightCls}">${escapeHtml(row.right)}</div>`;
      }).join("");
    }

    function applyReadmeAnalysisResult(branch, payload) {
      readmeCurrentBranch = branch;
      renderReadmeDiff(payload.diff, payload.current_readme);
      if (!payload.relevant) {
        readmeVerdict.textContent = `이번 최신 커밋(${payload.commit_message || ""})은 README 갱신이 필요하지 않다고 판단했습니다.`;
        readmeProposal = null;
        applyReadmeUpdateButton.disabled = true;
      } else if (!payload.changed) {
        readmeVerdict.textContent = "관련 변경이지만 재작성 결과가 기존 README와 동일합니다.";
        readmeProposal = null;
        applyReadmeUpdateButton.disabled = true;
      } else {
        readmeVerdict.textContent = payload.summary || "README 갱신이 필요합니다.";
        readmeProposal = payload;
        applyReadmeUpdateButton.disabled = false;
      }
    }

    function baselineStorageKey() {
      return `readmePushBaseline:${selectedRepository.owner}/${selectedRepository.repo}`;
    }

    function loadBranchShaBaseline() {
      try {
        branchShaBaseline = JSON.parse(localStorage.getItem(baselineStorageKey()) || "{}");
      } catch (_) {
        branchShaBaseline = {};
      }
    }

    function saveBranchShaBaseline() {
      localStorage.setItem(baselineStorageKey(), JSON.stringify(branchShaBaseline));
    }

    function readmeNotificationText(branch, payload) {
      if (branch !== "main") {
        return `push하여 '${branch}'에서 README를 갱신했습니다`;
      }
      if (!payload.relevant) {
        return "main이 병합되었습니다 — README와 무관한 변경입니다";
      }
      if (!payload.changed) {
        return "main이 병합되었습니다 — README 변경 사항이 없습니다";
      }
      return "main이 병합되어 README 갱신이 필요합니다";
    }

    function addPushNotification(branch, payload) {
      const el = document.createElement("div");
      el.className = "push-notification";
      el.textContent = readmeNotificationText(branch, payload);
      el.addEventListener("click", async () => {
        await switchTab("readmeUpdate");
        readmeBranchSelect.value = branch;
        applyReadmeAnalysisResult(branch, payload);
        el.remove();
      });
      document.querySelector("#pushNotifications").prepend(el);
    }

    async function pollBranchPushes() {
      if (!selectedRepository.owner || !selectedRepository.repo) return;
      const params = new URLSearchParams({
        owner: selectedRepository.owner,
        repo: selectedRepository.repo,
        installation_id: selectedRepository.installation_id || "",
      });
      let branches;
      try {
        const response = await fetch(`/api/branches?${params.toString()}`);
        branches = (await response.json()).branches || [];
      } catch (_) {
        return;
      }

      const isFirstPoll = Object.keys(branchShaBaseline).length === 0;
      for (const b of branches) {
        const prevSha = branchShaBaseline[b.name];
        branchShaBaseline[b.name] = b.sha;
        if (isFirstPoll || prevSha === b.sha) continue;

        let payload;
        try {
          const res = await fetch("/api/analyze-readme", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              owner: selectedRepository.owner,
              repo: selectedRepository.repo,
              installation_id: selectedRepository.installation_id || "",
              branch: b.name,
            }),
          });
          payload = await res.json();
        } catch (_) {
          continue;
        }
        if (payload && (b.name === "main" || payload.changed)) {
          addPushNotification(b.name, payload);
        }
      }
      saveBranchShaBaseline();
    }

    function startPushPolling() {
      if (pushPollTimer) {
        clearInterval(pushPollTimer);
      }
      loadBranchShaBaseline();
      pollBranchPushes();
      pushPollTimer = setInterval(pollBranchPushes, 30000);
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
        applyReadmeAnalysisResult(readmeCurrentBranch, payload);
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
    window.setInterval(updateGithubSyncTime, 30000);
