const onboardingGithubTitle = document.querySelector("#onboardingGithubTitle");
const onboardingGithubDesc = document.querySelector("#onboardingGithubDesc");
const onboardingInstallGithub = document.querySelector("#onboardingInstallGithub");
const onboardingRepoField = document.querySelector("#onboardingRepoField");
const onboardingRepoSelect = document.querySelector("#onboardingRepoSelect");
const onboardingNotionTitle = document.querySelector("#onboardingNotionTitle");
const onboardingNotionDesc = document.querySelector("#onboardingNotionDesc");
const onboardingGoogleTitle = document.querySelector("#onboardingGoogleTitle");
const onboardingGoogleDesc = document.querySelector("#onboardingGoogleDesc");
const onboardingFoot = document.querySelector("#onboardingFoot");
const agentStart = document.querySelector("#agentStart");
const onboardingStepTrack = document.querySelector("#onboardingStepTrack");

function readSavedRepository(config) {
  if (!config.github_user) {
    sessionStorage.removeItem("onboardingSelectedRepository");
    return { owner: "", repo: "", installation_id: "" };
  }
  const repositories = config.repositories || [];
  const isAvailable = (repository) => {
    if (!repository || !repository.owner || !repository.repo) return false;
    return repositories.some((item) => item.owner === repository.owner && item.repo === repository.repo);
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem("onboardingSelectedRepository") || "null");
    if (isAvailable(saved)) return saved;
  } catch (_) {}
  return { owner: "", repo: "", installation_id: "" };
}

function renderRepositoryPicker(repositories, selectedRepository) {
  onboardingRepoSelect.innerHTML = '<option value="">\uc800\uc7a5\uc18c\ub97c \uc120\ud0dd\ud574\uc8fc\uc138\uc694</option>';
  repositories.forEach((repository) => {
    const option = document.createElement("option");
    option.value = `${repository.owner}/${repository.repo}`;
    option.textContent = `${repository.owner}/${repository.repo}`;
    option.dataset.owner = repository.owner;
    option.dataset.repo = repository.repo;
    option.dataset.installationId = repository.installation_id || "";
    option.selected = repository.owner === selectedRepository.owner && repository.repo === selectedRepository.repo;
    onboardingRepoSelect.appendChild(option);
  });
  onboardingRepoField.hidden = !repositories.length;
}

function setOnboardingStep(canStart) {
  onboardingStepTrack.classList.toggle("show-optional-step", canStart);
}

async function loadOnboardingConfig() {
  const response = await fetch("/api/config");
  const config = await response.json();
  const repositories = config.repositories || [];
  const githubConnected = Boolean(config.github_user);
  const selectedRepository = readSavedRepository(config);
  renderRepositoryPicker(githubConnected ? repositories : [], selectedRepository);
  const selectedRepoLabel = githubConnected && selectedRepository.owner && selectedRepository.repo
    ? `${selectedRepository.owner}/${selectedRepository.repo}`
    : "";
  const notionEnabled = Boolean(config.notion_connected);
  const calendarEnabled = Boolean(config.calendar_connected);
  const canStart = githubConnected && Boolean(selectedRepoLabel);

  onboardingGithubTitle.textContent = selectedRepoLabel || (githubConnected ? "GitHub \uc5f0\uacb0\ub428" : "GitHub \uc5f0\uacb0");
  onboardingGithubDesc.textContent = selectedRepoLabel
    ? "\uc120\ud0dd\ub41c \uc800\uc7a5\uc18c\uc785\ub2c8\ub2e4."
    : (githubConnected
      ? "\ubd84\uc11d\ud560 \uc800\uc7a5\uc18c\ub97c \uc120\ud0dd\ud558\uac70\ub098 \uc571\uc744 \uc124\uce58\ud574\uc8fc\uc138\uc694."
      : "GitHub \uacc4\uc815\uc744 \uc5f0\uacb0\ud558\uc5ec \uc800\uc7a5\uc18c\uc640 \uc774\uc288\uc5d0 \uc811\uadfc\ud569\ub2c8\ub2e4.");

  onboardingNotionTitle.textContent = notionEnabled ? "Notion \uc5f0\uacb0\ub428" : "Notion \uc5f0\uacb0";
  onboardingNotionDesc.textContent = notionEnabled
    ? "\ud398\uc774\uc9c0\uc640 \ub370\uc774\ud130\ubca0\uc774\uc2a4\ub97c \uc0ac\uc6a9\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
    : "Notion \uacc4\uc815\uc744 \uc5f0\uacb0\ud558\uc5ec \ud398\uc774\uc9c0\uc640 \ub370\uc774\ud130\ub97c \ud65c\uc6a9\ud569\ub2c8\ub2e4.";

  onboardingGoogleTitle.textContent = calendarEnabled ? "Google Calendar \uc5f0\uacb0\ub428" : "Google Calendar \uc5f0\uacb0";
  onboardingGoogleDesc.textContent = config.google_user || "Google \uacc4\uc815\uc744 \uc5f0\uacb0\ud558\uc5ec \uc77c\uc815\uc744 \uad00\ub9ac\ud569\ub2c8\ub2e4.";

  agentStart.hidden = !canStart;
  setOnboardingStep(canStart);
  onboardingFoot.textContent = canStart
    ? "GitHub 저장소가 선택되었습니다. Notion과 Google Calendar는 선택 연결입니다."
    : "작업 화면으로 이동하려면 GitHub 연결과 저장소 선택이 필요합니다.";

  if (selectedRepoLabel && notionEnabled && calendarEnabled) {
    onboardingFoot.textContent = "\uc5f0\uacb0 \uc644\ub8cc. \uc791\uc5c5 \ud654\uba74\uc73c\ub85c \uc774\ub3d9\ud569\ub2c8\ub2e4.";
    window.setTimeout(() => window.location.assign("/app"), 650);
  }
}

loadOnboardingConfig().catch((error) => {
  onboardingFoot.textContent = error.message;
});

onboardingRepoSelect.addEventListener("change", () => {
  const option = onboardingRepoSelect.selectedOptions[0];
  if (!option || !option.value) {
    sessionStorage.removeItem("onboardingSelectedRepository");
    localStorage.removeItem("selectedRepository");
    onboardingGithubTitle.textContent = "GitHub \uc5f0\uacb0\ub428";
    onboardingGithubDesc.textContent = "\ubd84\uc11d\ud560 \uc800\uc7a5\uc18c\ub97c \uc120\ud0dd\ud574\uc8fc\uc138\uc694.";
    agentStart.hidden = true;
    setOnboardingStep(false);
    onboardingFoot.textContent = "작업 화면으로 이동하려면 GitHub 저장소 선택이 필요합니다.";
    return;
  }
  const repository = {
    owner: option.dataset.owner,
    repo: option.dataset.repo,
    installation_id: option.dataset.installationId || "",
  };
  sessionStorage.setItem("onboardingSelectedRepository", JSON.stringify(repository));
  localStorage.setItem("selectedRepository", JSON.stringify(repository));
  loadOnboardingConfig();
});

agentStart.addEventListener("click", () => {
  window.location.assign("/app");
});
