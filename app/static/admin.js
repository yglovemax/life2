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

const promptLabels = {
  shared_prefix: "共享静态前缀",
  module_rules: "模块专属输出规则",
  algorithm_data_template: "用户算法数据",
  user_preferences_template: "用户偏好及写作规则",
  final_request_template: "最终请求预览",
};

async function getJson(url, options) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
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
    <span>#${trace.id} · ${trace.status} · ${escapeHtml(trace.model_name)}</span>
    <pre>${escapeHtml(JSON.stringify(trace.final_json, null, 2))}</pre>
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
  document.querySelector("#knowledgeView").classList.toggle("hidden", view !== "knowledge");
  if (view === "test-center") renderTestCenter();
  if (view === "knowledge") renderKnowledgeWorkspace();
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
  return {
    test_user: document.querySelector("#testUser").value,
    date: document.querySelector("#testDate").value,
    model_id: Number(document.querySelector("#testModel").value),
    input_payload: parseJsonInput("#testPayload", {}),
  };
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

async function boot() {
  setupNavigation();
  setupKnowledgeActions();
  document.querySelector("#createModuleButton").onclick = newModuleDraft;
  await loadMetadata();
  await loadMetrics();
  await loadModules();
  renderTestCenter();
  await loadKnowledgeData();
}

boot();
