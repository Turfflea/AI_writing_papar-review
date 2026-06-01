const $ = (selector) => document.querySelector(selector);
const stepsEl = $("#steps");
const summaryLine = $("#summaryLine");
const jobBadge = $("#jobBadge");
const jobLog = $("#jobLog");
const fileKind = $("#fileKind");
const fileList = $("#fileList");
const fileEditor = $("#fileEditor");
const currentPath = $("#currentPath");
const overrideEditor = $("#overrideEditor");
let state = null;
let currentFilePath = "";

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function setTab(name) {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  $(`#${name}Tab`).classList.add("active");
}

function outputName(path) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function renderSteps() {
  const runningStep = state.job.running ? state.job.step_id : "";
  stepsEl.innerHTML = "";
  state.steps.forEach((step) => {
    const status = runningStep === step.id ? "running" : step.status;
    const node = document.createElement("article");
    node.className = `step ${status}`;
    node.innerHTML = `
      <div class="step-dot"></div>
      <div>
        <h3>${step.title}</h3>
        <p>${step.description}</p>
        <div class="step-outputs">
          ${step.outputs
            .map((item) => `<span class="output-chip ${item.exists ? "exists" : ""}">${outputName(item.path)}</span>`)
            .join("")}
        </div>
        <div class="step-actions">
          <button class="primary" data-run="${step.id}">运行</button>
          <button data-open="${step.id}">查看产出</button>
        </div>
      </div>
    `;
    stepsEl.appendChild(node);
  });
  stepsEl.querySelectorAll("[data-run]").forEach((button) => {
    button.addEventListener("click", () => runStep(button.dataset.run));
  });
  stepsEl.querySelectorAll("[data-open]").forEach((button) => {
    button.addEventListener("click", () => {
      fileKind.value = "outputs";
      setTab("editor");
      loadFileList();
    });
  });
}

function renderSummary() {
  const c = state.counts;
  summaryLine.textContent = `文献 ${c.papers} 篇 · 卡片 ${c.cards} 张 · 核心 ${c.core} 篇 · 综合 ${c.synthesis_files} 份 · 章节草稿 ${c.section_drafts} 份`;
  const running = state.job.running;
  jobBadge.textContent = running ? "运行中" : "空闲";
  jobBadge.className = `status-badge ${running ? "running" : "done"}`;
}

function renderSettings() {
  $("#baseUrl").value = state.settings.base_url;
  $("#modelName").value = state.settings.model;
  $("#temperature").value = state.settings.temperature;
  $("#timeout").value = state.settings.timeout;
  $("#settingsHint").textContent = state.settings.has_api_key
    ? `已配置 API Key：${state.settings.api_key_preview}`
    : "尚未配置 API Key";
}

function renderPaperOptions() {
  const select = $("#overridePaper");
  select.innerHTML = state.paper_ids.map((id) => `<option value="${id}">${id}</option>`).join("");
}

async function refreshState() {
  state = await api("/api/state");
  renderSummary();
  renderSteps();
  renderSettings();
  renderPaperOptions();
  await refreshJob();
}

async function refreshJob() {
  const job = await api("/api/job");
  jobLog.textContent = job.log || "";
  jobLog.scrollTop = jobLog.scrollHeight;
  if (job.running) {
    jobBadge.textContent = "运行中";
    jobBadge.className = "status-badge running";
  }
}

async function runStep(stepId) {
  const args = [];
  if ($("#forceRun").checked) args.push("--force");
  await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ step_id: stepId, args }),
  });
  setTab("logs");
  await refreshState();
}

async function loadFileList() {
  const data = await api(`/api/list?kind=${encodeURIComponent(fileKind.value)}`);
  fileList.innerHTML = data.files.map((file) => `<option value="${file.path}">${file.path}</option>`).join("");
}

async function loadFile(path = fileList.value) {
  if (!path) return;
  const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
  currentFilePath = data.path;
  currentPath.textContent = data.path;
  fileEditor.value = data.content;
}

async function saveFile() {
  if (!currentFilePath) return;
  await api("/api/file", {
    method: "POST",
    body: JSON.stringify({ path: currentFilePath, content: fileEditor.value }),
  });
  await refreshState();
}

async function deleteFile() {
  if (!currentFilePath) return;
  if (!confirm(`删除 ${currentFilePath}？`)) return;
  await api("/api/delete", {
    method: "POST",
    body: JSON.stringify({ path: currentFilePath }),
  });
  currentFilePath = "";
  currentPath.textContent = "未打开文件";
  fileEditor.value = "";
  await loadFileList();
  await refreshState();
}

async function uploadPapers() {
  const files = Array.from($("#paperUpload").files || []);
  for (const file of files) {
    const content = await file.text();
    await api("/api/upload", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, content }),
    });
  }
  await loadFileList();
  await refreshState();
}

async function createPaper() {
  const name = $("#newPaperName").value.trim() || "new_paper.md";
  await api("/api/upload", {
    method: "POST",
    body: JSON.stringify({ filename: name, content: "# New Paper\n\n" }),
  });
  fileKind.value = "papers";
  await loadFileList();
  fileList.value = `papers_md/${name.endsWith(".md") ? name : `${name}.md`}`;
  await loadFile();
  await refreshState();
}

async function loadOverrides() {
  const data = await api(`/api/file?path=${encodeURIComponent("project_config/human_overrides.json")}`);
  overrideEditor.value = data.content;
}

function parseOverrides() {
  return JSON.parse(overrideEditor.value || "{}");
}

async function saveOverrides() {
  await api("/api/file", {
    method: "POST",
    body: JSON.stringify({
      path: "project_config/human_overrides.json",
      content: JSON.stringify(parseOverrides(), null, 2),
    }),
  });
}

async function addOverride() {
  const data = parseOverrides();
  data.core_selection ||= {};
  const action = $("#overrideAction").value;
  data.core_selection[action] ||= [];
  const paperId = $("#overridePaper").value;
  const roles = $("#overrideRoles")
    .value.split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const item = {
    paper_id: paperId,
    reason: $("#overrideReason").value.trim(),
  };
  if (action === "promote_to_core") {
    item.primary_roles = roles;
    item.priority = "high";
  }
  if (action === "move_to_supporting") item.possible_use = roles;
  data.core_selection[action].push(item);
  overrideEditor.value = JSON.stringify(data, null, 2);
  await saveOverrides();
}

async function applyOverrides() {
  await saveOverrides();
  await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ step_id: "screening", args: ["--apply-overrides-only"] }),
  });
  setTab("logs");
}

async function saveSettings() {
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      api_key: $("#apiKey").value.trim(),
      base_url: $("#baseUrl").value.trim(),
      model: $("#modelName").value.trim(),
      temperature: $("#temperature").value.trim(),
      timeout: $("#timeout").value.trim(),
    }),
  });
  $("#apiKey").value = "";
  await refreshState();
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

$("#refreshBtn").addEventListener("click", refreshState);
fileKind.addEventListener("change", loadFileList);
$("#loadFileBtn").addEventListener("click", () => loadFile());
$("#saveFileBtn").addEventListener("click", saveFile);
$("#deleteFileBtn").addEventListener("click", deleteFile);
$("#uploadBtn").addEventListener("click", uploadPapers);
$("#createPaperBtn").addEventListener("click", createPaper);
$("#addOverrideBtn").addEventListener("click", addOverride);
$("#applyOverrideBtn").addEventListener("click", applyOverrides);
$("#saveSettingsBtn").addEventListener("click", saveSettings);

setInterval(async () => {
  await refreshJob();
  if (state?.job?.running) await refreshState();
}, 1500);

(async function init() {
  await refreshState();
  await loadFileList();
  await loadOverrides();
})();

