let modules = [];
let pages = [];
let modelConfigs = [];
let testUsers = [];
let knowledgeSources = [];
let knowledgeChunks = [];
let selectedModuleId = null;
let currentDetail = null;
let draftFields = [];
let latestTestResults = [];
let costSummaryData = null;
let fallbackAlerts = [];
let releaseVersions = [];
let latestAppApiResult = null;
let securityStatus = null;
let appKeys = [];
let auditEvents = [];
let issueItems = [];
let issueSummaryItems = [];
let modelProviderKeys = [];
let outputPolicies = [];
let latestRouterPreview = null;
let createdAppToken = "";
let adminToken = localStorage.getItem("nexa_admin_token") || "";
let adminUser = null;
let consoleInitialized = false;

const promptLabels = {
  shared_prefix: "共享静态前缀",
  module_rules: "模块专属输出规则",
  algorithm_data_template: "用户算法数据",
  user_preferences_template: "用户偏好及写作规则",
  final_request_template: "最终请求预览",
};

async function getJson(url, options) {
  const headers = { "Content-Type": "application/json", ...(options?.headers || {}) };
  if (adminToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${adminToken}`;
  }
  const response = await fetch(url, {
    ...options,
    headers,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function statusLabel(status) {
  const labels = {
    draft: "草稿",
    pending_test: "待测试",
    test_passed: "测试通过",
    pending_approval: "待审批",
    gray: "灰度中",
    live: "已上线",
    rolled_back: "已回滚",
    disabled: "已停用",
  };
  return labels[status] || status;
}

function issueStatusLabel(status) {
  const labels = {
    open: "待处理",
    in_progress: "处理中",
    resolved: "已解决",
  };
  return labels[status] || status;
}

function formatCents(cents) {
  return `$${(Number(cents || 0) / 100).toFixed(2)}`;
}

function formatDateTime(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return value;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeJson(value) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function parseJsonInput(selector, fallback) {
  const raw = document.querySelector(selector).value.trim();
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("算法字段必须是合法 JSON");
  }
}

function parseTags(selector) {
  return document
    .querySelector(selector)
    .value.split(/[,，\n]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function setupAuthActions() {
  document.querySelector("#loginButton").onclick = loginToConsole;
  document.querySelector("#logoutButton").onclick = logoutConsole;
  document.querySelector("#loginPassword").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loginToConsole();
  });
}

function showLogin(message = "") {
  document.body.classList.add("auth-locked");
  document.querySelector("#loginNotice").innerHTML = message ? `<div class="danger">${escapeHtml(message)}</div>` : "";
  document.querySelector("#loginPassword").focus();
}

function showConsole() {
  document.body.classList.remove("auth-locked");
  document.querySelector("#adminIdentity").textContent = adminUser ? `${adminUser.username} · ${adminUser.role}` : "管理员";
}

async function loginToConsole() {
  const notice = document.querySelector("#loginNotice");
  try {
    const username = document.querySelector("#loginUsername").value.trim();
    const password = document.querySelector("#loginPassword").value;
    if (!username || !password) throw new Error("请输入管理员账号和密码");
    const result = await getJson("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    adminToken = result.token;
    adminUser = result.user;
    localStorage.setItem("nexa_admin_token", adminToken);
    document.querySelector("#loginPassword").value = "";
    showConsole();
    await initializeConsole();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function logoutConsole() {
  try {
    await getJson("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
  } catch {
    // Local session cleanup should still happen if the server token is already invalid.
  }
  adminToken = "";
  adminUser = null;
  localStorage.removeItem("nexa_admin_token");
  showLogin("已退出，请重新登录");
}

async function loadMetrics() {
  const data = await getJson("/api/metrics");
  const cards = [
    ["模块", data.modules],
    ["字段契约", data.field_contracts],
    ["调用追踪", data.call_traces],
    ["Fallback", data.fallback_triggers],
  ];
  document.querySelector("#metrics").innerHTML = cards
    .map(([label, value]) => `<article class="metric-card"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
}

async function loadMetadata() {
  const [pageData, modelData, testUserData] = await Promise.all([getJson("/api/pages"), getJson("/api/models"), getJson("/api/test-users")]);
  pages = pageData.items;
  modelConfigs = modelData.items;
  testUsers = testUserData.items;
}

async function loadModules() {
  const data = await getJson("/api/modules");
  modules = data.items;
  renderPageFilter();
  renderRows();
}

function renderPageFilter() {
  const select = document.querySelector("#pageFilter");
  const selected = select.value;
  const pageNames = [...new Set(modules.map((item) => item.page_name))];
  select.innerHTML = `<option value="">全部页面</option>${pageNames
    .map((page) => `<option value="${escapeHtml(page)}">${escapeHtml(page)}</option>`)
    .join("")}`;
  select.value = selected;
  select.onchange = renderRows;
}

function renderRows() {
  const pageFilter = document.querySelector("#pageFilter").value;
  const rows = modules.filter((item) => !pageFilter || item.page_name === pageFilter);
  document.querySelector("#moduleRows").innerHTML = rows
    .map(
      (item) => `<tr class="${item.id === selectedModuleId ? "selected" : ""}" data-id="${item.id}">
        <td><strong>${escapeHtml(item.name)}</strong><br><small>${escapeHtml(item.slug)}</small></td>
        <td>${escapeHtml(item.page_name)}</td>
        <td>${escapeHtml(item.owner)}</td>
        <td>${escapeHtml(item.model)}</td>
        <td><span class="status">${statusLabel(item.status)}</span></td>
        <td>${item.today_calls}</td>
        <td>${item.fallback_count}</td>
      </tr>`
    )
    .join("");
  document.querySelectorAll("#moduleRows tr").forEach((row) => {
    row.onclick = () => selectModule(Number(row.dataset.id));
  });
}

async function selectModule(id) {
  selectedModuleId = id;
  renderRows();
  currentDetail = await getJson(`/api/modules/${id}`);
  draftFields = currentDetail.fields.map((field) => ({ ...field }));
  renderEditor(currentDetail);
}

function newModuleDraft() {
  selectedModuleId = null;
  currentDetail = {
    id: null,
    page_id: pages[0]?.id,
    model_id: modelConfigs[0]?.id,
    slug: "",
    name: "",
    owner: "未分配",
    status: "draft",
    fallback_content: "",
    algorithm_fields: { required: [] },
    knowledge_tags: [],
    prompt: {
      shared_prefix: "你是 Nexa 占卜 APP 的 AI 内容模块。保持温暖、清晰、克制，不做医疗、法律、投资等高风险承诺。",
      module_rules: "",
      algorithm_data_template: "",
      user_preferences_template: "",
      final_request_template: "请输出合法 JSON，不要 Markdown，不要额外解释。",
    },
    fields: [
      {
        field_name: "summary",
        purpose: "模块核心内容",
        display_position: "",
        example: "",
        source: "ai",
        is_ai_generated: true,
        is_required: true,
        owner: "Prompt",
        status: "draft",
        change_log: "初始创建",
      },
    ],
  };
  draftFields = currentDetail.fields.map((field) => ({ ...field }));
  renderRows();
  renderEditor(currentDetail, true);
}

function renderEditor(detail, isCreate = false) {
  document.querySelector("#detailPanel").innerHTML = `<div class="panel-head">
    <div>
      <p>${isCreate ? "New Module" : "Module Workspace"}</p>
      <h2>${isCreate ? "新增模块" : escapeHtml(detail.name)}</h2>
      <div class="kv">
        <span class="tag">${isCreate ? "草稿创建" : escapeHtml(detail.page_name)}</span>
        <span class="tag">${statusLabel(detail.status)}</span>
      </div>
    </div>
    <div class="actions">
      ${detail.id ? '<button class="secondary" onclick="copyRequestPreview()">复制请求</button><button class="secondary" onclick="runTest(currentDetail.id)">测试模块</button>' : ""}
      <button class="primary" onclick="saveModule()">${isCreate ? "创建草稿" : "保存草稿"}</button>
    </div>
  </div>
  <div class="detail-body">
    <div id="saveNotice"></div>
    <section>
      <h3>模块基础信息</h3>
      <div class="form-grid">
        <label>所属页面
          <select id="modulePage">${pages
            .map((page) => `<option value="${page.id}" ${page.name === detail.page_name || page.id === detail.page_id ? "selected" : ""}>${escapeHtml(page.name)}</option>`)
            .join("")}</select>
        </label>
        <label>默认模型
          <select id="moduleModel">${modelConfigs
            .map((model) => `<option value="${model.id}" ${model.display_name === detail.model || model.id === detail.model_id ? "selected" : ""}>${escapeHtml(model.display_name)}</option>`)
            .join("")}</select>
        </label>
        <label>模块名称
          <input id="moduleName" value="${escapeHtml(detail.name)}" placeholder="例如：事业运势" />
        </label>
        <label>模块标识
          <input id="moduleSlug" value="${escapeHtml(detail.slug)}" placeholder="daily-career" />
        </label>
        <label>负责人
          <input id="moduleOwner" value="${escapeHtml(detail.owner)}" />
        </label>
        <label>状态
          <select id="moduleStatus">${statusOptions(detail.status)}</select>
        </label>
        <label class="wide">Fallback 内容
          <textarea id="moduleFallback">${escapeHtml(detail.fallback_content)}</textarea>
        </label>
        <label class="wide">算法字段 JSON
          <textarea id="moduleAlgorithm">${escapeHtml(safeJson(detail.algorithm_fields))}</textarea>
        </label>
        <label class="wide">知识库标签（逗号或换行分隔）
          <textarea id="moduleTags">${escapeHtml((detail.knowledge_tags || []).join(", "))}</textarea>
        </label>
      </div>
    </section>

    <section class="section">
      <h3>Prompt 五段式</h3>
      <div class="prompt-grid">${Object.entries(promptLabels).map(([key, label]) => promptInput(key, label, detail.prompt[key])).join("")}</div>
    </section>

    <section class="section">
      <div class="panel-head inline-head">
        <div><p>Field Contract</p><h3>字段契约</h3></div>
        <button class="secondary compact" onclick="addField()">新增字段</button>
      </div>
      <div class="field-editor" id="fieldEditor">${draftFields.map(fieldInput).join("")}</div>
    </section>

    ${detail.id ? moduleIssueSection(detail) : ""}

    ${
      detail.id
        ? `<section class="section">
            <h3>最近调用追踪</h3>
            ${detail.recent_calls.length ? detail.recent_calls.map(traceCard).join("") : '<p class="empty">暂无调用记录。</p>'}
          </section>`
        : ""
    }
  </div>`;
}

function moduleIssueSection(detail) {
  return `<section class="section">
    <div class="panel-head inline-head">
      <div><p>Issue Tracker</p><h3>当前待处理问题</h3></div>
      <button class="secondary compact" onclick="createModuleIssue()">记录问题</button>
    </div>
    <div id="issueCreateNotice"></div>
    <div class="form-grid">
      <label>问题标题
        <input id="moduleIssueTitle" placeholder="例如：summary 内容太空 / 字段缺失" />
      </label>
      <label>问题类型
        <select id="moduleIssueType">
          <option value="content_quality">内容质量</option>
          <option value="field_contract">字段契约</option>
          <option value="fallback">Fallback</option>
          <option value="model_error">模型异常</option>
          <option value="algorithm_data">算法数据</option>
        </select>
      </label>
      <label>负责人
        <input id="moduleIssueOwner" placeholder="Prompt / QA / 产品 / 后端" />
      </label>
      <label class="wide">问题备注
        <textarea id="moduleIssueNotes" placeholder="记录复现样本、期望结果和当前问题。"></textarea>
      </label>
    </div>
    <div class="trace-list issue-list">
      ${(detail.issues || []).length ? detail.issues.map((issue) => issueCard(issue, "module")).join("") : '<p class="empty">暂无待处理问题。</p>'}
    </div>
  </section>`;
}

function statusOptions(selected) {
  return ["draft", "pending_test", "test_passed", "pending_approval", "gray", "live", "rolled_back", "disabled"]
    .map((status) => `<option value="${status}" ${status === selected ? "selected" : ""}>${statusLabel(status)}</option>`)
    .join("");
}

function promptInput(key, label, value) {
  return `<label class="prompt-card"><span>${label}</span><textarea id="prompt_${key}">${escapeHtml(value)}</textarea></label>`;
}

function fieldInput(field, index) {
  return `<article class="field-row" data-index="${index}">
    <div class="field-row-grid">
      <label>字段名<input data-field-key="field_name" value="${escapeHtml(field.field_name)}" /></label>
      <label>来源
        <select data-field-key="source">
          ${["ai", "algorithm", "fixed_config", "knowledge_base", "user_preference", "frontend_asset"]
            .map((source) => `<option value="${source}" ${source === field.source ? "selected" : ""}>${source}</option>`)
            .join("")}
        </select>
      </label>
      <label>用途<input data-field-key="purpose" value="${escapeHtml(field.purpose)}" /></label>
      <label>展示位置<input data-field-key="display_position" value="${escapeHtml(field.display_position)}" /></label>
      <label>示例<input data-field-key="example" value="${escapeHtml(field.example)}" /></label>
      <label>负责人<input data-field-key="owner" value="${escapeHtml(field.owner)}" /></label>
    </div>
    <div class="checks">
      <label><input type="checkbox" data-field-key="is_ai_generated" ${field.is_ai_generated ? "checked" : ""} /> AI 生成</label>
      <label><input type="checkbox" data-field-key="is_required" ${field.is_required ? "checked" : ""} /> 必填</label>
      <button class="danger compact" onclick="removeField(${index})">删除字段</button>
    </div>
    <label>修改记录<input data-field-key="change_log" value="${escapeHtml(field.change_log)}" /></label>
  </article>`;
}

function collectFields() {
  return [...document.querySelectorAll(".field-row")].map((row) => {
    const field = {};
    row.querySelectorAll("[data-field-key]").forEach((input) => {
      const key = input.dataset.fieldKey;
      field[key] = input.type === "checkbox" ? input.checked : input.value.trim();
    });
    field.status = "draft";
    return field;
  });
}

function collectPayload() {
  const prompt = {};
  Object.keys(promptLabels).forEach((key) => {
    prompt[key] = document.querySelector(`#prompt_${key}`).value;
  });
  return {
    page_id: Number(document.querySelector("#modulePage").value),
    model_id: Number(document.querySelector("#moduleModel").value),
    slug: document.querySelector("#moduleSlug").value.trim(),
    name: document.querySelector("#moduleName").value.trim(),
    owner: document.querySelector("#moduleOwner").value.trim() || "未分配",
    status: document.querySelector("#moduleStatus").value,
    fallback_content: document.querySelector("#moduleFallback").value,
    algorithm_fields: parseJsonInput("#moduleAlgorithm", {}),
    knowledge_tags: parseTags("#moduleTags"),
    prompt,
    fields: collectFields(),
  };
}

function validatePayload(payload) {
  if (!payload.name) throw new Error("模块名称不能为空");
  if (!payload.slug) throw new Error("模块标识不能为空");
  if (!payload.fields.length) throw new Error("至少需要一个字段契约");
  if (payload.fields.some((field) => !field.field_name)) throw new Error("字段名不能为空");
}

async function saveModule() {
  const notice = document.querySelector("#saveNotice");
  try {
    const payload = collectPayload();
    validatePayload(payload);
    const isCreate = !currentDetail?.id;
    const saved = await getJson(isCreate ? "/api/modules" : `/api/modules/${currentDetail.id}`, {
      method: isCreate ? "POST" : "PUT",
      body: JSON.stringify(payload),
    });
    notice.innerHTML = `<div class="notice">${isCreate ? "模块草稿已创建" : "模块草稿已保存"}</div>`;
    await loadMetrics();
    await loadModules();
    await selectModule(saved.id);
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function addField() {
  draftFields = collectFields();
  draftFields.push({
    field_name: "",
    purpose: "",
    display_position: "",
    example: "",
    source: "ai",
    is_ai_generated: true,
    is_required: true,
    owner: "未分配",
    status: "draft",
    change_log: "",
  });
  document.querySelector("#fieldEditor").innerHTML = draftFields.map(fieldInput).join("");
}

function removeField(index) {
  draftFields = collectFields().filter((_, fieldIndex) => fieldIndex !== index);
  document.querySelector("#fieldEditor").innerHTML = draftFields.map(fieldInput).join("");
}

function traceCard(trace) {
  return `<article class="trace-card">
    <span>#${trace.id} · ${trace.status} · ${escapeHtml(trace.model_name)} · ${formatCents(trace.estimated_cost_cents)}</span>
    ${
      trace.fallback_triggered
        ? `<p class="warning-line">Fallback：${escapeHtml(trace.fallback_reason || "未记录原因")}</p>`
        : ""
    }
    <pre>${escapeHtml(JSON.stringify(trace.final_json, null, 2))}</pre>
    <details class="trace-details">
      <summary>原始响应 / 模型请求</summary>
      <small>Model Raw Response</small>
      <pre>${escapeHtml(trace.model_raw_response || "")}</pre>
      <small>Model Request</small>
      <pre>${escapeHtml(trace.model_request || "")}</pre>
    </details>
    <div class="score-row">
      <input id="score_${trace.id}" type="number" min="1" max="5" value="${trace.manual_score || ""}" placeholder="1-5 分" />
      <input id="notes_${trace.id}" value="${escapeHtml(trace.reviewer_notes || "")}" placeholder="人工评分备注" />
      <button class="secondary compact" onclick="scoreTrace(${trace.id})">保存评分</button>
    </div>
  </article>`;
}

async function runTest(moduleId) {
  await getJson(`/api/modules/${moduleId}/test-run`, {
    method: "POST",
    body: JSON.stringify({
      test_user: "demo_user_001",
      date: new Date().toISOString().slice(0, 10),
      input_payload: {
        nickname: "测试用户",
        sun_sign: "白羊座",
        moon_sign: "处女座",
        source: "admin_console",
      },
    }),
  });
  await loadMetrics();
  await selectModule(moduleId);
}

function copyRequestPreview() {
  const text = Object.keys(promptLabels)
    .map((key) => document.querySelector(`#prompt_${key}`).value)
    .join("\n\n");
  navigator.clipboard.writeText(text);
}

function setupNavigation() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.onclick = () => showView(button.dataset.view);
  });
}

function showView(view) {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelector("#moduleView").classList.toggle("hidden", view !== "modules");
  document.querySelector("#testCenterView").classList.toggle("hidden", view !== "test-center");
  document.querySelector("#issuesView").classList.toggle("hidden", view !== "issues");
  document.querySelector("#knowledgeView").classList.toggle("hidden", view !== "knowledge");
  document.querySelector("#costCenterView").classList.toggle("hidden", view !== "cost-center");
  document.querySelector("#releaseCenterView").classList.toggle("hidden", view !== "release-center");
  document.querySelector("#modelRouterView").classList.toggle("hidden", view !== "model-router");
  document.querySelector("#appApiView").classList.toggle("hidden", view !== "app-api");
  document.querySelector("#securityView").classList.toggle("hidden", view !== "security");
  if (view === "test-center") renderTestCenter();
  if (view === "issues") renderIssueWorkspace();
  if (view === "knowledge") renderKnowledgeWorkspace();
  if (view === "cost-center") renderCostCenter();
  if (view === "release-center") renderReleaseCenter();
  if (view === "model-router") renderModelRouterWorkspace();
  if (view === "app-api") renderAppApiWorkspace();
  if (view === "security") renderSecurityWorkspace();
}

function renderTestCenter() {
  renderTestControls();
  renderTestModules();
  loadRecentTraces();
}

function renderTestControls() {
  const pageSelect = document.querySelector("#testPage");
  const selectedPage = pageSelect.value || String(pages[0]?.id || "");
  pageSelect.innerHTML = pages.map((page) => `<option value="${page.id}">${escapeHtml(page.name)}</option>`).join("");
  pageSelect.value = selectedPage;
  pageSelect.onchange = renderTestModules;

  const modelSelect = document.querySelector("#testModel");
  const selectedModel = modelSelect.value || String(modelConfigs[0]?.id || "");
  modelSelect.innerHTML = modelConfigs.map((model) => `<option value="${model.id}">${escapeHtml(model.display_name)}</option>`).join("");
  modelSelect.value = selectedModel;

  const userSelect = document.querySelector("#testUser");
  const selectedUser = userSelect.value || testUsers[0]?.id || "";
  userSelect.innerHTML = testUsers.map((user) => `<option value="${user.id}">${escapeHtml(user.name)}</option>`).join("");
  userSelect.value = selectedUser;
  userSelect.onchange = fillTestPayloadFromUser;

  const dateInput = document.querySelector("#testDate");
  if (!dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);
  if (!document.querySelector("#testPayload").value.trim()) fillTestPayloadFromUser();

  document.querySelector("#runSingleButton").onclick = () => runTestCenter("single");
  document.querySelector("#runBatchButton").onclick = () => runTestCenter("batch");
  document.querySelector("#refreshTracesButton").onclick = loadRecentTraces;
}

function fillTestPayloadFromUser() {
  const user = testUsers.find((item) => item.id === document.querySelector("#testUser").value) || testUsers[0];
  document.querySelector("#testPayload").value = safeJson({
    ...(user?.birth_profile || {}),
    preferences: user?.preferences || {},
    source: "test_center",
  });
}

function renderTestModules() {
  const pageId = Number(document.querySelector("#testPage").value || pages[0]?.id);
  const page = pages.find((item) => item.id === pageId);
  const rows = modules.filter((module) => !page || module.page_name === page.name);
  document.querySelector("#testModuleChecks").innerHTML = rows
    .map(
      (module, index) => `<label class="module-check">
        <input type="checkbox" value="${module.id}" ${index === 0 ? "checked" : ""} />
        <span><strong>${escapeHtml(module.name)}</strong><br><small>${escapeHtml(module.slug)} · ${escapeHtml(module.model)}</small></span>
      </label>`
    )
    .join("");
}

function selectedTestModuleIds() {
  return [...document.querySelectorAll("#testModuleChecks input:checked")].map((input) => Number(input.value));
}

function testPayloadBase() {
  const payload = {
    test_user: document.querySelector("#testUser").value,
    date: document.querySelector("#testDate").value,
    model_id: Number(document.querySelector("#testModel").value),
    input_payload: parseJsonInput("#testPayload", {}),
  };
  const mockModelResponse = document.querySelector("#testMockModelResponse").value.trim();
  if (mockModelResponse) {
    payload.simulate_model_response = mockModelResponse;
  }
  return payload;
}

async function runTestCenter(mode) {
  const notice = document.querySelector("#testNotice");
  try {
    const moduleIds = selectedTestModuleIds();
    if (!moduleIds.length) throw new Error("请至少选择一个模块");
    const payload = { ...testPayloadBase(), module_ids: mode === "single" ? [moduleIds[0]] : moduleIds };
    const response = await getJson("/api/test-runs/batch", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    latestTestResults = response.items;
    notice.innerHTML = `<div class="notice">已生成 ${latestTestResults.length} 条测试结果</div>`;
    renderTestResults();
    await loadMetrics();
    await loadModules();
    await loadRecentTraces();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderTestResults() {
  const container = document.querySelector("#testResults");
  if (!latestTestResults.length) {
    container.innerHTML = '<p class="empty">还没有测试结果。</p>';
    return;
  }
  container.innerHTML = `${comparisonPanel(latestTestResults)}${latestTestResults.map(traceCard).join("")}`;
}

function comparisonPanel(results) {
  if (results.length < 2) return "";
  const left = results[0];
  const right = results[1];
  return `<article class="trace-card">
    <span>结果对比 · #${left.id} / #${right.id}</span>
    <div class="compare-grid">
      <pre>${escapeHtml(JSON.stringify(left.final_json, null, 2))}</pre>
      <pre>${escapeHtml(JSON.stringify(right.final_json, null, 2))}</pre>
    </div>
  </article>`;
}

async function loadRecentTraces() {
  const data = await getJson("/api/call-traces");
  document.querySelector("#recentTraceList").innerHTML = data.items.length ? data.items.map(traceCard).join("") : '<p class="empty">暂无调用记录。</p>';
}

async function scoreTrace(traceId) {
  const score = document.querySelector(`#score_${traceId}`).value;
  const notes = document.querySelector(`#notes_${traceId}`).value;
  const saved = await getJson(`/api/call-traces/${traceId}/score`, {
    method: "PUT",
    body: JSON.stringify({
      manual_score: score ? Number(score) : null,
      reviewer_notes: notes,
    }),
  });
  document.querySelector("#testNotice").innerHTML = `<div class="notice">#${saved.id} 评分已保存</div>`;
  latestTestResults = latestTestResults.map((trace) => (trace.id === saved.id ? saved : trace));
  renderTestResults();
  await loadRecentTraces();
}

function setupIssueActions() {
  document.querySelector("#refreshIssuesButton").onclick = renderIssueWorkspace;
  document.querySelector("#issueStatusFilter").onchange = renderIssueWorkspace;
  document.querySelector("#issueOwnerFilter").addEventListener("keydown", (event) => {
    if (event.key === "Enter") renderIssueWorkspace();
  });
}

async function renderIssueWorkspace() {
  await loadIssueData();
  renderIssueSummary();
  renderIssueList();
}

async function loadIssueData() {
  const params = new URLSearchParams();
  const status = document.querySelector("#issueStatusFilter").value;
  const owner = document.querySelector("#issueOwnerFilter").value.trim();
  if (status) params.set("status", status);
  if (owner) params.set("owner", owner);
  const query = params.toString();
  const [summaryData, issueData] = await Promise.all([
    getJson("/api/issues"),
    getJson(`/api/issues${query ? `?${query}` : ""}`),
  ]);
  issueSummaryItems = summaryData.items;
  issueItems = issueData.items;
}

function renderIssueSummary() {
  const counts = {
    open: issueSummaryItems.filter((issue) => issue.status === "open").length,
    in_progress: issueSummaryItems.filter((issue) => issue.status === "in_progress").length,
    resolved: issueSummaryItems.filter((issue) => issue.status === "resolved").length,
  };
  const cards = [
    ["待处理", counts.open],
    ["处理中", counts.in_progress],
    ["已解决", counts.resolved],
    ["全部问题", issueSummaryItems.length],
  ];
  document.querySelector("#issueSummaryCards").innerHTML = cards
    .map(([label, value]) => `<article class="mini-card"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
}

function renderIssueList() {
  document.querySelector("#issueList").innerHTML = issueItems.length
    ? issueItems.map((issue) => issueCard(issue, "center")).join("")
    : '<p class="empty">当前筛选下没有问题。</p>';
}

function issueCard(issue, context) {
  const inputId = (key) => `issue_${key}_${context}_${issue.id}`;
  return `<article class="trace-card issue-card">
    <span>#${issue.id} · ${escapeHtml(issue.page_name || "未分组")} / ${escapeHtml(issue.module_name || `模块 ${issue.module_id}`)} · ${issueStatusLabel(issue.status)}</span>
    <p><strong>${escapeHtml(issue.title)}</strong></p>
    <div class="form-grid compact-grid">
      <label>状态
        <select id="${inputId("status")}">
          ${["open", "in_progress", "resolved"].map((status) => `<option value="${status}" ${issue.status === status ? "selected" : ""}>${issueStatusLabel(status)}</option>`).join("")}
        </select>
      </label>
      <label>负责人
        <input id="${inputId("owner")}" value="${escapeHtml(issue.owner)}" />
      </label>
      <label class="wide">备注
        <textarea id="${inputId("notes")}">${escapeHtml(issue.notes || "")}</textarea>
      </label>
    </div>
    <div class="actions">
      <button class="secondary compact" onclick="updateIssue(${issue.id}, '${context}')">保存进度</button>
    </div>
  </article>`;
}

async function createModuleIssue() {
  const notice = document.querySelector("#issueCreateNotice");
  try {
    if (!currentDetail?.id) throw new Error("请先选择一个模块");
    const payload = {
      title: document.querySelector("#moduleIssueTitle").value.trim(),
      issue_type: document.querySelector("#moduleIssueType").value,
      owner: document.querySelector("#moduleIssueOwner").value.trim() || "未分配",
      notes: document.querySelector("#moduleIssueNotes").value,
    };
    if (!payload.title) throw new Error("问题标题不能为空");
    const issue = await getJson(`/api/modules/${currentDetail.id}/issues`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    document.querySelector("#moduleIssueTitle").value = "";
    document.querySelector("#moduleIssueOwner").value = "";
    document.querySelector("#moduleIssueNotes").value = "";
    await loadModules();
    await selectModule(currentDetail.id);
    document.querySelector("#issueCreateNotice").innerHTML = `<div class="notice">问题 #${issue.id} 已记录</div>`;
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function updateIssue(issueId, context) {
  const notice = document.querySelector(context === "center" ? "#issueNotice" : "#issueCreateNotice");
  const valueFor = (key) => document.querySelector(`#issue_${key}_${context}_${issueId}`).value;
  try {
    const saved = await getJson(`/api/issues/${issueId}`, {
      method: "PUT",
      body: JSON.stringify({
        status: valueFor("status"),
        owner: valueFor("owner").trim() || "未分配",
        notes: valueFor("notes"),
      }),
    });
    const message = `<div class="notice">问题 #${saved.id} 已更新为 ${issueStatusLabel(saved.status)}</div>`;
    await loadModules();
    if (currentDetail?.id === saved.module_id) {
      await selectModule(saved.module_id);
    }
    if (context === "center") {
      await renderIssueWorkspace();
    }
    const refreshedNotice = document.querySelector(context === "center" ? "#issueNotice" : "#issueCreateNotice");
    if (refreshedNotice) refreshedNotice.innerHTML = message;
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function setupKnowledgeActions() {
  document.querySelector("#saveMarkdownButton").onclick = saveMarkdownKnowledge;
  document.querySelector("#saveManualKnowledgeButton").onclick = saveManualKnowledge;
  document.querySelector("#searchKnowledgeButton").onclick = searchKnowledge;
  document.querySelector("#refreshKnowledgeButton").onclick = renderKnowledgeWorkspace;
}

async function renderKnowledgeWorkspace() {
  await loadKnowledgeData();
  renderKnowledgeSources();
  renderKnowledgeChunks();
}

async function loadKnowledgeData() {
  const [sourcesData, chunksData] = await Promise.all([getJson("/api/knowledge-sources"), getJson("/api/knowledge-chunks")]);
  knowledgeSources = sourcesData.items;
  knowledgeChunks = chunksData.items;
}

async function saveMarkdownKnowledge() {
  const notice = document.querySelector("#knowledgeNotice");
  try {
    const payload = {
      title: document.querySelector("#knowledgeTitle").value.trim() || "未命名 Markdown 资料",
      source_type: "markdown",
      content: document.querySelector("#knowledgeContent").value,
      tags: parseTags("#knowledgeTags"),
    };
    if (!payload.content.trim()) throw new Error("Markdown 内容不能为空");
    const saved = await getJson("/api/knowledge-sources", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    notice.innerHTML = `<div class="notice">已上传「${escapeHtml(saved.title)}」，生成 ${saved.chunk_count} 个知识片段</div>`;
    document.querySelector("#knowledgeTitle").value = "";
    document.querySelector("#knowledgeContent").value = "";
    await renderKnowledgeWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function saveManualKnowledge() {
  const notice = document.querySelector("#knowledgeNotice");
  try {
    const payload = {
      title: document.querySelector("#manualKnowledgeTitle").value.trim() || "人工知识条目",
      content: document.querySelector("#manualKnowledgeContent").value,
      tags: parseTags("#manualKnowledgeTags"),
    };
    if (!payload.content.trim()) throw new Error("条目内容不能为空");
    const saved = await getJson("/api/knowledge-entries", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    notice.innerHTML = `<div class="notice">人工条目「${escapeHtml(saved.title)}」已入库</div>`;
    document.querySelector("#manualKnowledgeTitle").value = "";
    document.querySelector("#manualKnowledgeContent").value = "";
    await renderKnowledgeWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function searchKnowledge() {
  const notice = document.querySelector("#knowledgeNotice");
  try {
    const data = await getJson("/api/knowledge/search", {
      method: "POST",
      body: JSON.stringify({
        query: document.querySelector("#knowledgeQuery").value,
        tags: parseTags("#knowledgeSearchTags"),
        limit: 8,
      }),
    });
    document.querySelector("#knowledgeSearchResults").innerHTML = data.items.length
      ? data.items.map(knowledgeChunkCard).join("")
      : '<p class="empty">没有检索到知识片段。</p>';
    notice.innerHTML = `<div class="notice">检索完成，命中 ${data.items.length} 条</div>`;
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderKnowledgeSources() {
  document.querySelector("#knowledgeSources").innerHTML = knowledgeSources.length
    ? knowledgeSources.map(knowledgeSourceCard).join("")
    : '<p class="empty">还没有资料来源。</p>';
}

function renderKnowledgeChunks() {
  document.querySelector("#knowledgeChunks").innerHTML = knowledgeChunks.length
    ? knowledgeChunks.slice(0, 20).map(knowledgeChunkCard).join("")
    : '<p class="empty">还没有知识片段。</p>';
}

function knowledgeSourceCard(source) {
  return `<article class="trace-card">
    <span>#${source.id} · ${escapeHtml(source.source_type)} · ${escapeHtml(source.status)}</span>
    <p><strong>${escapeHtml(source.title)}</strong></p>
    <p>标签：${escapeHtml((source.tags || []).join(", "))}</p>
    <p>知识片段：${source.chunk_count}</p>
  </article>`;
}

function knowledgeChunkCard(chunk) {
  return `<article class="trace-card">
    <span>#${chunk.id} · source ${chunk.source_id} · ${escapeHtml((chunk.tags || []).join(", "))}</span>
    <p><strong>${escapeHtml(chunk.title)}</strong></p>
    <p>${escapeHtml(chunk.content)}</p>
  </article>`;
}

function setupCostActions() {
  document.querySelector("#refreshCostsButton").onclick = renderCostCenter;
}

async function renderCostCenter() {
  const notice = document.querySelector("#costNotice");
  try {
    const [costData, alertData] = await Promise.all([getJson("/api/costs/summary"), getJson("/api/fallback-alerts")]);
    costSummaryData = costData;
    fallbackAlerts = alertData.items;
    renderCostSummary();
    notice.innerHTML = `<div class="notice">成本与 Fallback 已刷新</div>`;
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderCostSummary() {
  if (!costSummaryData) return;
  const cards = [
    ["总调用", costSummaryData.total_calls],
    ["总成本", formatCents(costSummaryData.total_cost_cents)],
    ["Fallback", costSummaryData.fallback_calls],
    ["平均成本", formatCents(costSummaryData.total_calls ? costSummaryData.total_cost_cents / costSummaryData.total_calls : 0)],
  ];
  document.querySelector("#costSummaryCards").innerHTML = cards
    .map(([label, value]) => `<article class="mini-card"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
  document.querySelector("#costByPage").innerHTML = costSummaryData.by_page.length
    ? costSummaryData.by_page.map((item) => costRow(item.page_name, item.calls, item.cost_cents, item.fallback_count)).join("")
    : '<p class="empty">还没有调用成本。</p>';
  document.querySelector("#costByModel").innerHTML = costSummaryData.by_model.length
    ? costSummaryData.by_model.map((item) => costRow(item.model_name, item.calls, item.cost_cents, item.fallback_count)).join("")
    : '<p class="empty">还没有模型成本。</p>';
  document.querySelector("#costByModule").innerHTML = costSummaryData.by_module.length
    ? costSummaryData.by_module.slice(0, 12).map((item) => costRow(item.module_name, item.calls, item.cost_cents, item.fallback_count, item.page_name)).join("")
    : '<p class="empty">还没有模块成本。</p>';
  document.querySelector("#fallbackAlerts").innerHTML = fallbackAlerts.length
    ? fallbackAlerts.map(fallbackAlertCard).join("")
    : '<p class="empty">暂无 Fallback 告警。</p>';
}

function costRow(title, calls, costCents, fallbackCount, subtitle = "") {
  return `<article class="stat-row">
    <div>
      <strong>${escapeHtml(title)}</strong>
      ${subtitle ? `<small>${escapeHtml(subtitle)}</small>` : ""}
    </div>
    <div class="stat-values">
      <span>${calls} 次</span>
      <span>${formatCents(costCents)}</span>
      <span>${fallbackCount} Fallback</span>
    </div>
  </article>`;
}

function fallbackAlertCard(alert) {
  return `<article class="trace-card alert-card">
    <span>#${alert.trace_id} · ${escapeHtml(alert.page_name)} · ${formatDateTime(alert.created_at)}</span>
    <p><strong>${escapeHtml(alert.module_name)}</strong></p>
    <p>原因：${escapeHtml(alert.reason || "未记录原因")}</p>
    <pre>${escapeHtml(JSON.stringify(alert.final_json, null, 2))}</pre>
  </article>`;
}

function setupReleaseActions() {
  document.querySelector("#refreshReleaseButton").onclick = renderReleaseCenter;
  document.querySelector("#publishModuleButton").onclick = publishSelectedModule;
  document.querySelector("#rollbackModuleButton").onclick = rollbackSelectedModule;
}

async function renderReleaseCenter() {
  renderReleaseControls();
  await loadModuleVersions();
}

function renderReleaseControls() {
  const moduleSelect = document.querySelector("#releaseModule");
  const selected = moduleSelect.value || String(selectedModuleId || modules[0]?.id || "");
  moduleSelect.innerHTML = modules
    .map((module) => `<option value="${module.id}">${escapeHtml(module.page_name)} / ${escapeHtml(module.name)} · ${statusLabel(module.status)}</option>`)
    .join("");
  moduleSelect.value = selected && modules.some((module) => String(module.id) === String(selected)) ? selected : String(modules[0]?.id || "");
  moduleSelect.onchange = loadModuleVersions;

  document.querySelector("#releaseStatus").innerHTML = ["pending_test", "test_passed", "pending_approval", "gray", "live", "disabled"]
    .map((status) => `<option value="${status}">${statusLabel(status)}</option>`)
    .join("");
}

async function loadModuleVersions() {
  const moduleId = Number(document.querySelector("#releaseModule").value);
  const summary = document.querySelector("#releaseModuleSummary");
  const versionList = document.querySelector("#releaseVersionList");
  const module = modules.find((item) => item.id === moduleId);
  if (!module) {
    summary.innerHTML = '<p class="empty">还没有模块。</p>';
    versionList.innerHTML = '<p class="empty">还没有版本记录。</p>';
    return;
  }
  summary.innerHTML = releaseModuleCard(module);
  const data = await getJson(`/api/modules/${moduleId}/versions`);
  releaseVersions = data.items;
  versionList.innerHTML = releaseVersions.length ? releaseVersions.map(versionCard).join("") : '<p class="empty">还没有发布版本。</p>';
}

function releaseModuleCard(module) {
  return `<article class="trace-card">
    <span>${escapeHtml(module.page_name)} · v${module.version} · ${statusLabel(module.status)}</span>
    <p><strong>${escapeHtml(module.name)}</strong></p>
    <p>负责人：${escapeHtml(module.owner)} · 模型：${escapeHtml(module.model)}</p>
    <p>调用：${module.today_calls} · Fallback：${module.fallback_count} · 成本：${formatCents(module.today_cost_cents)}</p>
  </article>`;
}

function versionCard(version) {
  const snapshot = version.snapshot || {};
  return `<article class="trace-card version-card">
    <span>v${version.version} · ${statusLabel(version.status)} · ${formatDateTime(version.created_at)}</span>
    <p><strong>${escapeHtml(snapshot.action === "rollback" ? "回滚快照" : "发布快照")}</strong></p>
    <p>操作人：${escapeHtml(snapshot.operator || "admin")}</p>
    ${snapshot.notes ? `<p>备注：${escapeHtml(snapshot.notes)}</p>` : ""}
    ${snapshot.reason ? `<p>原因：${escapeHtml(snapshot.reason)}</p>` : ""}
  </article>`;
}

async function publishSelectedModule() {
  const notice = document.querySelector("#releaseNotice");
  try {
    const moduleId = Number(document.querySelector("#releaseModule").value);
    const saved = await getJson(`/api/modules/${moduleId}/publish`, {
      method: "POST",
      body: JSON.stringify({
        status: document.querySelector("#releaseStatus").value,
        operator: document.querySelector("#releaseOperator").value.trim() || "admin",
        notes: document.querySelector("#releaseNotes").value,
      }),
    });
    notice.innerHTML = `<div class="notice">${escapeHtml(saved.name)} 已推进到 ${statusLabel(saved.status)}，版本 v${saved.version}</div>`;
    await loadMetrics();
    await loadModules();
    document.querySelector("#releaseModule").value = String(saved.id);
    renderReleaseControls();
    document.querySelector("#releaseModule").value = String(saved.id);
    await loadModuleVersions();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function rollbackSelectedModule() {
  const notice = document.querySelector("#releaseNotice");
  try {
    const moduleId = Number(document.querySelector("#releaseModule").value);
    const saved = await getJson(`/api/modules/${moduleId}/rollback`, {
      method: "POST",
      body: JSON.stringify({
        operator: document.querySelector("#releaseOperator").value.trim() || "admin",
        reason: document.querySelector("#releaseNotes").value || "后台人工回滚",
      }),
    });
    notice.innerHTML = `<div class="notice">${escapeHtml(saved.name)} 已回滚，版本 v${saved.version}</div>`;
    await loadMetrics();
    await loadModules();
    document.querySelector("#releaseModule").value = String(saved.id);
    renderReleaseControls();
    document.querySelector("#releaseModule").value = String(saved.id);
    await loadModuleVersions();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function setupModelRouterActions() {
  document.querySelector("#refreshModelRouterButton").onclick = renderModelRouterWorkspace;
  document.querySelector("#createModelKeyButton").onclick = createModelProviderKey;
  document.querySelector("#createOutputPolicyButton").onclick = createOutputPolicy;
  document.querySelector("#previewRouterButton").onclick = previewModelRouter;
}

async function renderModelRouterWorkspace() {
  await loadModelRouterData();
  renderModelRouterControls();
  renderModelProviderKeys();
  renderOutputPolicies();
  renderRouterPreviewResult();
}

async function loadModelRouterData() {
  const [keyData, policyData] = await Promise.all([
    getJson("/api/model-provider-keys"),
    getJson("/api/output-policies"),
  ]);
  modelProviderKeys = keyData.items;
  outputPolicies = policyData.items;
}

function renderModelRouterControls() {
  const modelOptions = `<option value="">自动选择</option>${modelConfigs
    .map((model) => `<option value="${model.id}">${escapeHtml(model.display_name)} · ${escapeHtml(model.quality_tier)}</option>`)
    .join("")}`;
  document.querySelector("#policyPrimaryModel").innerHTML = modelOptions;
  document.querySelector("#policyFallbackModel").innerHTML = modelOptions;

  const moduleSelect = document.querySelector("#routerPreviewModule");
  const selectedModule = moduleSelect.value || String(modules[0]?.id || "");
  moduleSelect.innerHTML = modules
    .map((module) => `<option value="${module.id}">${escapeHtml(module.page_name)} / ${escapeHtml(module.name)}</option>`)
    .join("");
  moduleSelect.value = selectedModule && modules.some((module) => String(module.id) === String(selectedModule)) ? selectedModule : String(modules[0]?.id || "");

  const policySelect = document.querySelector("#routerPreviewPolicy");
  const selectedPolicy = policySelect.value || String(outputPolicies[0]?.id || "");
  policySelect.innerHTML = outputPolicies.length
    ? outputPolicies.map((policy) => `<option value="${policy.id}">${escapeHtml(policy.name)}${policy.is_default ? " · 默认" : ""}</option>`).join("")
    : '<option value="">临时策略</option>';
  policySelect.value = selectedPolicy && outputPolicies.some((policy) => String(policy.id) === String(selectedPolicy)) ? selectedPolicy : String(outputPolicies[0]?.id || "");
}

async function createModelProviderKey() {
  const notice = document.querySelector("#modelRouterNotice");
  try {
    const name = document.querySelector("#modelKeyName").value.trim();
    const provider = document.querySelector("#modelKeyProvider").value.trim() || "openai";
    const apiKey = document.querySelector("#modelKeyValue").value.trim();
    if (!name) throw new Error("Key 名称不能为空");
    if (!apiKey) throw new Error("API Key 不能为空");
    const created = await getJson("/api/model-provider-keys", {
      method: "POST",
      body: JSON.stringify({
        name,
        provider,
        api_key: apiKey,
        operator: adminUser?.username || "admin",
      }),
    });
    document.querySelector("#createdModelKeyBox").innerHTML = `<article class="token-box">
      <span>只显示一次</span>
      <strong>${escapeHtml(created.key.name)}</strong>
      <code>${escapeHtml(created.api_key)}</code>
    </article>`;
    notice.innerHTML = `<div class="notice">模型 Key 已保存，请立即转存明文。</div>`;
    document.querySelector("#modelKeyName").value = "";
    document.querySelector("#modelKeyValue").value = "";
    await renderModelRouterWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function createOutputPolicy() {
  const notice = document.querySelector("#modelRouterNotice");
  try {
    const name = document.querySelector("#policyName").value.trim();
    if (!name) throw new Error("策略名称不能为空");
    const policy = await getJson("/api/output-policies", {
      method: "POST",
      body: JSON.stringify({
        name,
        quality_tier: document.querySelector("#policyQuality").value,
        primary_model_id: document.querySelector("#policyPrimaryModel").value || null,
        fallback_model_id: document.querySelector("#policyFallbackModel").value || null,
        max_output_tokens: Number(document.querySelector("#policyMaxTokens").value || 680),
        temperature_x100: Number(document.querySelector("#policyTemperature").value || 65),
        response_format: document.querySelector("#policyResponseFormat").value,
        safety_rules: document.querySelector("#policySafetyRules").value,
        is_default: document.querySelector("#policyIsDefault").value === "true",
      }),
    });
    notice.innerHTML = `<div class="notice">输出策略「${escapeHtml(policy.name)}」已保存</div>`;
    document.querySelector("#policyName").value = "";
    await renderModelRouterWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

async function previewModelRouter() {
  const notice = document.querySelector("#modelRouterNotice");
  try {
    latestRouterPreview = await getJson("/api/model-router/preview", {
      method: "POST",
      body: JSON.stringify({
        module_id: Number(document.querySelector("#routerPreviewModule").value || 0),
        policy_id: document.querySelector("#routerPreviewPolicy").value || null,
        input_payload: { source: "admin_model_router_preview" },
      }),
    });
    notice.innerHTML = `<div class="notice">路由预览已生成</div>`;
    renderRouterPreviewResult();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderRouterPreviewResult() {
  const container = document.querySelector("#routerPreviewResult");
  if (!container) return;
  if (!latestRouterPreview) {
    container.innerHTML = '<p class="empty">还没有预览路由。</p>';
    return;
  }
  container.innerHTML = `<article class="trace-card">
    <span>${escapeHtml(latestRouterPreview.policy?.name || "临时策略")} · ${escapeHtml(latestRouterPreview.orchestration.response_format)}</span>
    <p><strong>主模型：${escapeHtml(latestRouterPreview.selected_model?.display_name || "未配置")}</strong></p>
    <p>备用模型：${escapeHtml(latestRouterPreview.fallback_model?.display_name || "未配置")}</p>
    <p>最大输出：${latestRouterPreview.orchestration.max_output_tokens} tokens · 温度：${latestRouterPreview.orchestration.temperature_x100}</p>
    <pre>${escapeHtml(JSON.stringify(latestRouterPreview.orchestration, null, 2))}</pre>
  </article>`;
}

function renderModelProviderKeys() {
  document.querySelector("#modelProviderKeyList").innerHTML = modelProviderKeys.length
    ? modelProviderKeys.map(modelProviderKeyCard).join("")
    : '<p class="empty">还没有模型供应商 Key。</p>';
}

function modelProviderKeyCard(key) {
  return `<article class="trace-card">
    <span>#${key.id} · ${escapeHtml(key.provider)} · ${escapeHtml(key.status)} · ${escapeHtml(key.token_prefix)}***</span>
    <p><strong>${escapeHtml(key.name)}</strong></p>
    <p>创建：${formatDateTime(key.created_at)}${key.revoked_at ? ` · 撤销：${formatDateTime(key.revoked_at)}` : ""}</p>
    ${key.status === "active" ? `<button class="danger compact" onclick="revokeModelProviderKey(${key.id})">撤销 Key</button>` : ""}
  </article>`;
}

async function revokeModelProviderKey(keyId) {
  const notice = document.querySelector("#modelRouterNotice");
  try {
    const revoked = await getJson(`/api/model-provider-keys/${keyId}/revoke`, {
      method: "POST",
      body: JSON.stringify({ operator: adminUser?.username || "admin" }),
    });
    notice.innerHTML = `<div class="notice">${escapeHtml(revoked.name)} 已撤销</div>`;
    await renderModelRouterWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderOutputPolicies() {
  document.querySelector("#outputPolicyList").innerHTML = outputPolicies.length
    ? outputPolicies.map(outputPolicyCard).join("")
    : '<p class="empty">还没有输出策略。</p>';
}

function outputPolicyCard(policy) {
  return `<article class="trace-card">
    <span>#${policy.id} · ${escapeHtml(policy.quality_tier)}${policy.is_default ? " · 默认" : ""}</span>
    <p><strong>${escapeHtml(policy.name)}</strong></p>
    <p>主模型：${escapeHtml(policy.primary_model?.display_name || "自动选择")} · 备用：${escapeHtml(policy.fallback_model?.display_name || "自动选择")}</p>
    <p>最大输出：${policy.max_output_tokens} tokens · 温度：${policy.temperature_x100} · 格式：${escapeHtml(policy.response_format)}</p>
  </article>`;
}

function setupAppApiActions() {
  document.querySelector("#refreshAppApiButton").onclick = renderAppApiWorkspace;
  document.querySelector("#callAppPageButton").onclick = () => callAppApi("page");
  document.querySelector("#callAppModuleButton").onclick = () => callAppApi("module");
}

async function renderAppApiWorkspace() {
  renderAppApiControls();
  renderAppApiEndpoints();
  await loadOfficialTraces();
}

function renderAppApiControls() {
  const pageSelect = document.querySelector("#appApiPage");
  const selectedPage = pageSelect.value || pages[0]?.slug || "";
  pageSelect.innerHTML = pages.map((page) => `<option value="${escapeHtml(page.slug)}">${escapeHtml(page.name)} · ${escapeHtml(page.slug)}</option>`).join("");
  pageSelect.value = selectedPage;
  pageSelect.onchange = renderAppApiEndpoints;

  const moduleSelect = document.querySelector("#appApiModule");
  const selectedModule = moduleSelect.value || modules[0]?.slug || "";
  moduleSelect.innerHTML = modules
    .map((module) => `<option value="${escapeHtml(module.slug)}">${escapeHtml(module.name)} · ${escapeHtml(module.slug)} · ${statusLabel(module.status)}</option>`)
    .join("");
  moduleSelect.value = selectedModule;
  moduleSelect.onchange = renderAppApiEndpoints;

  if (!document.querySelector("#appApiPayload").value.trim()) {
    document.querySelector("#appApiPayload").value = safeJson({
      user_id: "app_user_001",
      date: new Date().toISOString().slice(0, 10),
      input_payload: {
        nickname: "max",
        sun_sign: "白羊座",
        moon_sign: "处女座",
      },
    });
  }
}

function renderAppApiEndpoints() {
  const pageSlug = document.querySelector("#appApiPage").value || pages[0]?.slug || "";
  const moduleSlug = document.querySelector("#appApiModule").value || modules[0]?.slug || "";
  const endpoints = [
    ["页面级 JSON API", "POST", `/api/app/pages/${pageSlug}/render`],
    ["模块级 JSON API", "POST", `/api/app/modules/${moduleSlug}/render`],
  ];
  document.querySelector("#appApiEndpoints").innerHTML = endpoints
    .map(
      ([title, method, path]) => `<article class="endpoint-card">
        <span>${method}</span>
        <strong>${escapeHtml(title)}</strong>
        <code>${escapeHtml(path)}</code>
      </article>`
    )
    .join("");
}

async function callAppApi(kind) {
  const notice = document.querySelector("#appApiNotice");
  try {
    const token = document.querySelector("#appApiToken").value.trim();
    if (!token) throw new Error("App Token 不能为空");
    const payload = parseJsonInput("#appApiPayload", {});
    const pageSlug = document.querySelector("#appApiPage").value;
    const moduleSlug = document.querySelector("#appApiModule").value;
    const url = kind === "page" ? `/api/app/pages/${pageSlug}/render` : `/api/app/modules/${moduleSlug}/render`;
    latestAppApiResult = await getJson(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload),
    });
    notice.innerHTML = `<div class="notice">${kind === "page" ? "页面" : "模块"}接口调用完成，request_id: ${escapeHtml(latestAppApiResult.request_id)}</div>`;
    renderAppApiResult();
    await loadMetrics();
    await loadModules();
    await loadOfficialTraces();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderAppApiResult() {
  const container = document.querySelector("#appApiResult");
  if (!latestAppApiResult) {
    container.innerHTML = '<p class="empty">还没有发起 App 接口测试。</p>';
    return;
  }
  container.innerHTML = `<article class="trace-card">
    <span>${escapeHtml(latestAppApiResult.request_id)} · trace ${escapeHtml(latestAppApiResult.trace_id || "page")}</span>
    <pre>${escapeHtml(JSON.stringify(latestAppApiResult, null, 2))}</pre>
  </article>`;
}

async function loadOfficialTraces() {
  const data = await getJson("/api/call-traces?request_type=official");
  document.querySelector("#officialTraceList").innerHTML = data.items.length ? data.items.map(traceCard).join("") : '<p class="empty">暂无正式调用。</p>';
}

function setupSecurityActions() {
  document.querySelector("#refreshSecurityButton").onclick = renderSecurityWorkspace;
  document.querySelector("#createAppKeyButton").onclick = createAppKey;
}

async function renderSecurityWorkspace() {
  await loadSecurityData();
  renderSecurityStatus();
  renderAppKeys();
  renderAuditEvents();
}

async function loadSecurityData() {
  const [statusData, keyData, eventData] = await Promise.all([
    getJson("/api/security/status"),
    getJson("/api/security/app-keys"),
    getJson("/api/security/audit-events"),
  ]);
  securityStatus = statusData;
  appKeys = keyData.items;
  auditEvents = eventData.items;
}

function renderSecurityStatus() {
  if (!securityStatus) return;
  const cards = [
    ["管理员", securityStatus.admin_auth?.users || 0],
    ["后台会话", securityStatus.admin_auth?.active_sessions || 0],
    ["活跃 Key", securityStatus.app_keys.active],
    ["已撤销 Key", securityStatus.app_keys.revoked],
    ["审计事件", securityStatus.audit_events.total],
    ["鉴权失败", securityStatus.audit_events.failed_auth],
  ];
  document.querySelector("#securitySummaryCards").innerHTML = cards
    .map(([label, value]) => `<article class="mini-card"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
  const notice = securityStatus.token_policy.using_default_dev_token
    ? "当前仍启用本地默认 dev token，生产环境需要换成独立 token 或托管 App Key。"
    : "当前默认 token 已由环境变量覆盖。";
  document.querySelector("#securityNotice").innerHTML = `<div class="${securityStatus.token_policy.using_default_dev_token ? "danger" : "notice"}">${escapeHtml(notice)}</div>`;
}

async function createAppKey() {
  const notice = document.querySelector("#securityNotice");
  try {
    const name = document.querySelector("#securityKeyName").value.trim();
    if (!name) throw new Error("Key 名称不能为空");
    const created = await getJson("/api/security/app-keys", {
      method: "POST",
      body: JSON.stringify({
        name,
        scopes: document.querySelector("#securityKeyScopes").value.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean),
        operator: "admin",
      }),
    });
    createdAppToken = created.token;
    document.querySelector("#createdAppKeyBox").innerHTML = `<article class="token-box">
      <span>只显示一次</span>
      <strong>${escapeHtml(created.key.name)}</strong>
      <code>${escapeHtml(created.token)}</code>
    </article>`;
    notice.innerHTML = `<div class="notice">App Key 已创建，请立即保存 token。</div>`;
    document.querySelector("#securityKeyName").value = "";
    await renderSecurityWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderAppKeys() {
  document.querySelector("#securityKeyList").innerHTML = appKeys.length
    ? appKeys.map(appKeyCard).join("")
    : '<p class="empty">还没有托管 App Key。</p>';
}

function appKeyCard(key) {
  return `<article class="trace-card">
    <span>#${key.id} · ${escapeHtml(key.status)} · ${escapeHtml(key.token_prefix)}***</span>
    <p><strong>${escapeHtml(key.name)}</strong></p>
    <p>权限：${escapeHtml((key.scopes || []).join(", "))}</p>
    <p>创建：${formatDateTime(key.created_at)}${key.last_used_at ? ` · 最近使用：${formatDateTime(key.last_used_at)}` : ""}</p>
    ${key.status === "active" ? `<button class="danger compact" onclick="revokeAppKey(${key.id})">撤销 Key</button>` : ""}
  </article>`;
}

async function revokeAppKey(keyId) {
  const notice = document.querySelector("#securityNotice");
  try {
    const revoked = await getJson(`/api/security/app-keys/${keyId}/revoke`, {
      method: "POST",
      body: JSON.stringify({ operator: "admin" }),
    });
    notice.innerHTML = `<div class="notice">${escapeHtml(revoked.name)} 已撤销</div>`;
    await renderSecurityWorkspace();
  } catch (error) {
    notice.innerHTML = `<div class="danger">${escapeHtml(error.message)}</div>`;
  }
}

function renderAuditEvents() {
  document.querySelector("#auditEventList").innerHTML = auditEvents.length
    ? auditEvents.map(auditEventCard).join("")
    : '<p class="empty">暂无审计事件。</p>';
}

function auditEventCard(event) {
  return `<article class="trace-card ${event.severity === "warning" ? "alert-card" : ""}">
    <span>#${event.id} · ${escapeHtml(event.event_type)} · ${escapeHtml(event.severity)} · ${formatDateTime(event.created_at)}</span>
    <p><strong>${escapeHtml(event.actor)}</strong></p>
    <p>对象：${escapeHtml(event.target_type || "-")} ${escapeHtml(event.target_id || "")}</p>
    <pre>${escapeHtml(JSON.stringify(event.details || {}, null, 2))}</pre>
  </article>`;
}

async function initializeConsole() {
  if (consoleInitialized) {
    showConsole();
    return;
  }
  consoleInitialized = true;
  setupNavigation();
  setupIssueActions();
  setupKnowledgeActions();
  setupCostActions();
  setupReleaseActions();
  setupModelRouterActions();
  setupAppApiActions();
  setupSecurityActions();
  document.querySelector("#createModuleButton").onclick = newModuleDraft;
  await loadMetadata();
  await loadMetrics();
  await loadModules();
  renderTestCenter();
  await loadKnowledgeData();
}

async function boot() {
  setupAuthActions();
  if (!adminToken) {
    showLogin();
    return;
  }
  try {
    adminUser = await getJson("/api/auth/me");
    showConsole();
    await initializeConsole();
  } catch {
    adminToken = "";
    adminUser = null;
    localStorage.removeItem("nexa_admin_token");
    showLogin("登录已失效，请重新登录");
  }
}

boot();
