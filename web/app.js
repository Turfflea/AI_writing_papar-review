const $ = (selector) => document.querySelector(selector);

let appState = null;
let activeStepId = "inventory";
let activePromptPath = "";
let currentOutputPath = "";

const stepIdsWithPrompt = new Set(["cards", "screening", "synthesis", "evidence", "outline", "draft"]);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function outputName(path) {
  return path.split("/").pop() || path;
}

function selectedStep() {
  return appState.steps.find((step) => step.id === activeStepId) || appState.steps[0];
}

async function refreshState() {
  appState = await api("/api/state");
  if (!appState.steps.some((step) => step.id === activeStepId)) activeStepId = appState.steps[0].id;
  renderAll();
  await refreshJob();
}

function renderAll() {
  renderProjectBar();
  renderSummary();
  renderBrief();
  renderSettings();
  renderPapers();
  renderSteps();
  renderStepDetail();
}

function renderProjectBar() {
  $("#projectSelect").innerHTML = appState.projects
    .map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name || project.id)}</option>`)
    .join("");
  $("#projectSelect").value = appState.active_project.id;
  $("#projectName").textContent = appState.active_project.name || appState.active_project.id;
}

function renderSummary() {
  const c = appState.counts;
  $("#summaryLine").textContent = `当前项目：${appState.active_project.name || appState.active_project.id} · 文献 ${c.papers} 篇 · 卡片 ${c.cards} 张 · 核心 ${c.core} 篇 · 综合 ${c.synthesis_files} 份`;
  const running = appState.job.running;
  $("#jobBadge").textContent = running ? "运行中" : "空闲";
  $("#jobBadge").className = `status-badge ${running ? "running" : "done"}`;
}

async function renderBrief() {
  const editor = $("#briefEditor");
  if (document.activeElement === editor) return;
  const data = await api(`/api/file?path=${encodeURIComponent("project_config/review_brief.md")}`);
  editor.value = data.content;
}

function renderSettings() {
  $("#baseUrl").value = appState.settings.base_url;
  $("#modelName").value = appState.settings.model;
  $("#temperature").value = appState.settings.temperature;
  $("#timeout").value = appState.settings.timeout;
  $("#settingsHint").textContent = appState.settings.has_api_key
    ? `已配置 API Key：${appState.settings.api_key_preview}`
    : "尚未配置 API Key";
}

function renderPapers() {
  const progress = appState.card_progress;
  if (!progress.papers.length) {
    $("#paperList").innerHTML = `<p class="muted">还没有导入文献。</p>`;
    return;
  }
  $("#paperList").innerHTML = progress.papers
    .map(
      (paper) => `
        <button class="paper-item" data-output="${escapeHtml(paper.paper_file || paper.card_path)}">
          <span>${escapeHtml(paper.paper_id)}</span>
          <span class="mini-status ${paper.status}">${statusLabel(paper.status)}</span>
        </button>
      `,
    )
    .join("");
  $("#paperList").querySelectorAll("[data-output]").forEach((button) => {
    button.addEventListener("click", () => openOutput(button.dataset.output));
  });
}

function statusLabel(status) {
  return {
    success: "已生成",
    failed: "失败",
    pending: "未开始",
    prompted: "已生成提示词",
    done: "已完成",
    partial: "部分完成",
  }[status] || status;
}

function renderSteps() {
  $("#steps").innerHTML = appState.steps
    .map((step) => {
      const running = appState.job.running && appState.job.step_id === step.id;
      const status = running ? "running" : step.status;
      return `
        <button class="step ${status} ${activeStepId === step.id ? "active" : ""}" data-step="${step.id}">
          <span class="step-dot"></span>
          <span>
            <strong>${escapeHtml(step.title)}</strong>
            <small>${escapeHtml(statusLabel(status))}</small>
          </span>
        </button>
      `;
    })
    .join("");
  $("#steps").querySelectorAll("[data-step]").forEach((button) => {
    button.addEventListener("click", () => {
      activeStepId = button.dataset.step;
      currentOutputPath = "";
      renderStepDetail();
    });
  });
}

function renderStepDetail() {
  const step = selectedStep();
  $("#stepTitle").textContent = step.title;
  $("#stepDescription").textContent = step.description;
  $("#progressBtn").classList.toggle("hidden", step.id !== "cards");
  renderStepOptions(step);
  renderPromptPanel(step);
  renderOutputPanel(step);
}

function renderStepOptions(step) {
  if (step.id === "screening") {
    $("#stepOptions").innerHTML = `
      <label>核心文献筛选批大小
        <input id="batchSize" type="number" min="2" max="50" value="10" />
      </label>
      <p class="muted">这个数字决定每次给 AI 多少张文献卡片。文献多、卡片长时可调小；想减少 API 调用次数可调大。</p>
    `;
  } else {
    $("#stepOptions").innerHTML = "";
  }
}

function renderPromptPanel(step) {
  const panel = $("#promptPanel");
  if (!stepIdsWithPrompt.has(step.id) || !step.prompt_info.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  $("#promptHelp").textContent = "执行本步骤前，请确认这里的提示词和 AI 生成模板符合本项目目标。";
  $("#promptSelect").innerHTML = step.prompt_info
    .map((item) => `<option value="${escapeHtml(item.path)}">${escapeHtml(item.title)}</option>`)
    .join("");
  if (!activePromptPath || !step.prompt_info.some((item) => item.path === activePromptPath)) {
    activePromptPath = step.prompt_info[0].path;
  }
  $("#promptSelect").value = activePromptPath;
  const prompt = step.prompt_info.find((item) => item.path === activePromptPath) || step.prompt_info[0];
  $("#promptDescription").textContent = `${prompt.title}：${prompt.description}（文件：${prompt.filename}）`;
  $("#promptEditor").value = prompt.content;
}

function renderOutputPanel(step) {
  $("#outputHint").textContent = step.output_files.length ? `${step.output_files.length} 个文件` : "暂无产出";
  $("#outputList").innerHTML = step.output_files.length
    ? step.output_files
        .map((file) => `<button class="output-item" data-path="${escapeHtml(file.path)}">${escapeHtml(file.path)}</button>`)
        .join("")
    : `<p class="muted">执行本步骤后，这里会显示本步骤相关产出。</p>`;
  $("#outputList").querySelectorAll("[data-path]").forEach((button) => {
    button.addEventListener("click", () => openOutput(button.dataset.path));
  });
  if (!currentOutputPath) {
    $("#currentOutputPath").textContent = "请选择一个产出文件";
    $("#outputEditor").value = "";
  }
}

async function openOutput(path) {
  if (!path) return;
  const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
  currentOutputPath = data.path;
  $("#currentOutputPath").textContent = data.path;
  $("#outputEditor").value = data.content;
}

function runArgs(force = false) {
  const args = [];
  if (force) args.push("--force");
  if (activeStepId === "screening") {
    const value = $("#batchSize")?.value || "10";
    args.push("--batch-size", value);
  }
  return args;
}

async function runStep(force = false) {
  if (stepIdsWithPrompt.has(activeStepId)) {
    await savePrompt();
  }
  await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ step_id: activeStepId, args: runArgs(force) }),
  });
  await refreshState();
}

async function rollbackStep() {
  if (!confirm("撤回会删除本步骤及后续步骤的产出文件，确认继续？")) return;
  await api("/api/rollback", {
    method: "POST",
    body: JSON.stringify({ step_id: activeStepId }),
  });
  currentOutputPath = "";
  await refreshState();
}

async function saveBrief() {
  await api("/api/file", {
    method: "POST",
    body: JSON.stringify({ path: "project_config/review_brief.md", content: $("#briefEditor").value }),
  });
  await refreshState();
}

async function savePrompt() {
  if (!activePromptPath) return;
  await api("/api/file", {
    method: "POST",
    body: JSON.stringify({ path: activePromptPath, content: $("#promptEditor").value }),
  });
  await refreshState();
}

async function saveOutput() {
  if (!currentOutputPath) return;
  await api("/api/file", {
    method: "POST",
    body: JSON.stringify({ path: currentOutputPath, content: $("#outputEditor").value }),
  });
  await refreshState();
}

async function uploadPapers() {
  const files = Array.from($("#paperUpload").files || []);
  for (const file of files) {
    await api("/api/upload", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, content: await file.text() }),
    });
  }
  $("#paperUpload").value = "";
  await refreshState();
}

async function createProject() {
  const name = $("#newProjectName").value.trim();
  if (!name) return;
  await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ action: "create", name }),
  });
  activeStepId = "inventory";
  currentOutputPath = "";
  $("#newProjectName").value = "";
  await refreshState();
}

async function selectProject() {
  await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ action: "select", project_id: $("#projectSelect").value }),
  });
  activeStepId = "inventory";
  currentOutputPath = "";
  await refreshState();
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

async function showCardProgress() {
  const progress = await api("/api/card-progress");
  $("#progressSummary").textContent = `总计 ${progress.counts.total} 篇；成功 ${progress.counts.success}，失败 ${progress.counts.failed}，未开始 ${progress.counts.pending}，已生成提示词 ${progress.counts.prompted}。`;
  $("#progressTable").innerHTML = `
    <table>
      <thead><tr><th>文献</th><th>状态</th><th>卡片</th><th>错误</th></tr></thead>
      <tbody>
        ${progress.papers
          .map(
            (paper) => `
              <tr>
                <td>${escapeHtml(paper.paper_id)}</td>
                <td><span class="mini-status ${paper.status}">${statusLabel(paper.status)}</span></td>
                <td>${paper.card_path ? `<button data-open-card="${escapeHtml(paper.card_path)}">打开</button>` : ""}</td>
                <td>${escapeHtml(paper.error || "")}</td>
              </tr>
            `,
          )
          .join("")}
      </tbody>
    </table>
  `;
  $("#progressTable").querySelectorAll("[data-open-card]").forEach((button) => {
    button.addEventListener("click", async () => {
      $("#progressDialog").close();
      activeStepId = "cards";
      await openOutput(button.dataset.openCard);
      renderStepDetail();
    });
  });
  $("#progressDialog").showModal();
}

async function refreshJob() {
  const job = await api("/api/job");
  $("#jobLog").textContent = job.log || "";
  $("#jobLog").scrollTop = $("#jobLog").scrollHeight;
  $("#jobReturnCode").textContent =
    job.returncode === null || job.returncode === undefined ? "" : `退出码：${job.returncode}`;
  if (job.running) {
    $("#jobBadge").textContent = "运行中";
    $("#jobBadge").className = "status-badge running";
  }
}

$("#refreshBtn").addEventListener("click", refreshState);
$("#createProjectBtn").addEventListener("click", createProject);
$("#projectSelect").addEventListener("change", selectProject);
$("#saveBriefBtn").addEventListener("click", saveBrief);
$("#settingsToggleBtn").addEventListener("click", () => $("#settingsBox").classList.toggle("hidden"));
$("#saveSettingsBtn").addEventListener("click", saveSettings);
$("#uploadBtn").addEventListener("click", uploadPapers);
$("#runBtn").addEventListener("click", () => runStep(false));
$("#rerunBtn").addEventListener("click", () => runStep(true));
$("#rollbackBtn").addEventListener("click", rollbackStep);
$("#progressBtn").addEventListener("click", showCardProgress);
$("#savePromptBtn").addEventListener("click", savePrompt);
$("#saveOutputBtn").addEventListener("click", saveOutput);
$("#promptSelect").addEventListener("change", () => {
  activePromptPath = $("#promptSelect").value;
  renderPromptPanel(selectedStep());
});
$("#closeProgressBtn").addEventListener("click", () => $("#progressDialog").close());

setInterval(async () => {
  await refreshJob();
  if (appState?.job?.running) await refreshState();
}, 1500);

refreshState();

