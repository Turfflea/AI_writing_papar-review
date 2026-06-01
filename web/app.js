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

function isAgentStep(step) {
  return Boolean(step?.agent_step);
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
  renderDimensions();
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

function renderDimensions() {
  const box = $("#dimensionList");
  const dimensions = appState.dimensions || { available_dimensions: [], selected_dimensions: [] };
  const selected = new Set(dimensions.selected_dimensions || []);
  box.innerHTML = (dimensions.available_dimensions || [])
    .map(
      (dimension) => `
        <label class="dimension-option">
          <input type="checkbox" value="${escapeHtml(dimension)}" ${selected.has(dimension) ? "checked" : ""} />
          <span>${escapeHtml(dimension)}</span>
        </label>
      `,
    )
    .join("");
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
          <span class="paper-name" title="${escapeHtml(paper.display_name || paper.paper_id)}">${escapeHtml(paper.display_name || paper.paper_id)}</span>
          <span class="mini-status ${paper.library_status || "imported"}">${statusLabel(paper.library_status || "imported")}</span>
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
    submitted: "已提交",
    done: "已完成",
    partial: "部分完成",
    imported: "已导入",
    inventoried: "已扫描",
    card_only: "仅有卡片",
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
  $("#runBtn").textContent = isAgentStep(step) ? "准备工作区并打开终端" : "执行本步";
  $("#rerunBtn").textContent = isAgentStep(step) ? "重建本步工作区" : "重新生成本步";
  $("#rerunBtn").title = isAgentStep(step)
    ? "覆盖重建本步骤 prompt.md 和 input 输入材料"
    : "覆盖并重新生成本步骤产出";
  $("#progressBtn").classList.toggle("hidden", step.id !== "cards");
  renderStepOptions(step);
  renderScreeningPanel(step);
  renderPromptPanel(step);
  renderOutputPanel(step);
}

function renderStepOptions(step) {
  if (step.id === "cards") {
    $("#stepOptions").innerHTML = `
      <label>单篇卡片生成并发数
        <input id="cardConcurrency" type="number" min="1" max="20" value="3" />
      </label>
      <p class="muted">并发数越高越快，但也更容易触发 API 限流。建议先用 2-5。</p>
    `;
  } else if (step.id === "screening") {
    $("#stepOptions").innerHTML = `
      <label>核心文献筛选批大小
        <input id="batchSize" type="number" min="2" max="50" value="10" />
      </label>
      <label>初筛批次并发数
        <input id="screeningConcurrency" type="number" min="1" max="20" value="2" />
      </label>
      <p class="muted">这个数字决定每次给 AI 多少张文献卡片。文献多、卡片长时可调小；想减少 API 调用次数可调大。</p>
    `;
  } else if (isAgentStep(step)) {
    $("#stepOptions").innerHTML = `
      <label>终端 Agent
        <select id="agentTool">
          <option value="codex">Codex</option>
          <option value="claude">Claude Code</option>
        </select>
      </label>
      <p class="muted">本步不会调用 DeepSeek API。系统只准备本步骤输出文件夹并打开终端；进入终端后先启动所选 Agent。如果没有新的想法，直接输入“按照项目中的.md 输出内容”。</p>
    `;
  } else {
    $("#stepOptions").innerHTML = "";
  }
}

function renderScreeningPanel(step) {
  const panel = $("#screeningPanel");
  if (step.id !== "screening") {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const groups = appState.screening_results || { core: [], supporting: [], peripheral: [] };
  const config = [
    ["core", "核心文献", "core_reason"],
    ["supporting", "辅助文献", "supporting_reason"],
    ["peripheral", "边缘文献", "reason"],
  ];
  $("#screeningGroups").innerHTML = config
    .map(([key, title, reasonKey]) => {
      const rows = groups[key] || [];
      return `
        <section class="screening-group">
          <h4>${title} <span>${rows.length}</span></h4>
          ${
            rows.length
              ? rows
                  .map(
                    (row) => `
                      <article class="screening-item">
                        <strong>${escapeHtml(row.paper_id || "")}</strong>
                        <p>${escapeHtml(row[reasonKey] || row.reason || "")}</p>
                      </article>
                    `,
                  )
                  .join("")
              : `<p class="muted">暂无结果</p>`
          }
        </section>
      `;
    })
    .join("");
}

function renderPromptPanel(step) {
  const panel = $("#promptPanel");
  if (!stepIdsWithPrompt.has(step.id) || !step.prompt_info.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  $("#promptHelp").textContent = "执行本步骤前，请确认这里的提示词和 AI 生成模板符合本项目目标。";
  if (step.prompt_info.length > 1) {
    $("#promptHelp").textContent = `本步骤有 ${step.prompt_info.length} 个提示词模板，请在右侧下拉菜单中逐个检查并保存。`;
  }
  if (isAgentStep(step)) {
    $("#promptHelp").textContent = "这里编辑的是生成 Agent 工作区 prompt.md 的原始模板。执行本步后，可在“本步骤产出”中打开并继续修改渲染后的 prompt.md。";
  }
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
    : `<p class="muted">${isAgentStep(step) ? "执行本步后，这里会显示 prompt.md、README.md 和 input/ 输入材料。" : "执行本步骤后，这里会显示本步骤相关产出。"}</p>`;
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
  if (activeStepId === "cards") {
    const value = $("#cardConcurrency")?.value || "1";
    args.push("--concurrency", value);
  }
  if (activeStepId === "screening") {
    const value = $("#batchSize")?.value || "10";
    args.push("--batch-size", value);
    const concurrency = $("#screeningConcurrency")?.value || "1";
    args.push("--concurrency", concurrency);
  }
  if (isAgentStep(selectedStep())) {
    const agent = $("#agentTool")?.value || "codex";
    args.push("--agent", agent);
  }
  return args;
}

async function runStep(force = false) {
  const args = runArgs(force);
  if (stepIdsWithPrompt.has(activeStepId)) {
    await savePrompt();
  }
  await api("/api/run", {
    method: "POST",
    body: JSON.stringify({ step_id: activeStepId, args }),
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

async function saveDimensions() {
  const selected = Array.from($("#dimensionList").querySelectorAll("input:checked")).map((input) => input.value);
  await api("/api/dimensions", {
    method: "POST",
    body: JSON.stringify({ selected_dimensions: selected }),
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
  $("#progressSummary").textContent = `总计 ${progress.counts.total} 篇；成功 ${progress.counts.success}，失败 ${progress.counts.failed}，已提交 ${progress.counts.submitted || 0}，未开始 ${progress.counts.pending}。`;
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
$("#saveDimensionsBtn").addEventListener("click", saveDimensions);
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
