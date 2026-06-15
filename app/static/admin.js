let modules = [];
let selectedModuleId = null;

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

async function loadModules() {
  const data = await getJson("/api/modules");
  modules = data.items;
  renderPageFilter();
  renderRows();
}

function renderPageFilter() {
  const select = document.querySelector("#pageFilter");
  const pages = [...new Set(modules.map((item) => item.page_name))];
  select.innerHTML = `<option value="">全部页面</option>${pages
    .map((page) => `<option value="${page}">${page}</option>`)
    .join("")}`;
  select.onchange = renderRows;
}

function renderRows() {
  const pageFilter = document.querySelector("#pageFilter").value;
  const rows = modules.filter((item) => !pageFilter || item.page_name === pageFilter);
  document.querySelector("#moduleRows").innerHTML = rows
    .map(
      (item) => `<tr class="${item.id === selectedModuleId ? "selected" : ""}" data-id="${item.id}">
        <td><strong>${item.name}</strong><br><small>${item.slug}</small></td>
        <td>${item.page_name}</td>
        <td>${item.owner}</td>
        <td>${item.model}</td>
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
  const detail = await getJson(`/api/modules/${id}`);
  renderDetail(detail);
}

function renderDetail(detail) {
  document.querySelector("#detailPanel").innerHTML = `<div class="panel-head">
    <div>
      <p>Module Workspace</p>
      <h2>${detail.name}</h2>
      <div class="kv">
        <span class="tag">${detail.page_name}</span>
        <span class="tag">${detail.model}</span>
        <span class="tag">${statusLabel(detail.status)}</span>
      </div>
    </div>
    <div class="actions">
      <button class="secondary" onclick="copyRequestPreview()">复制请求</button>
      <button class="primary" onclick="runTest(${detail.id})">测试模块</button>
    </div>
  </div>
  <div class="detail-body">
    <section>
      <h3>Prompt 五段式</h3>
      <div class="prompt-grid">
        ${promptCard("共享静态前缀", detail.prompt.shared_prefix)}
        ${promptCard("模块专属输出规则", detail.prompt.module_rules)}
        ${promptCard("用户算法数据", detail.prompt.algorithm_data_template)}
        ${promptCard("用户偏好及写作规则", detail.prompt.user_preferences_template)}
        ${promptCard("最终请求预览", detail.prompt.final_request_template)}
      </div>
    </section>
    <section class="section">
      <h3>字段契约</h3>
      ${detail.fields.map(fieldCard).join("")}
    </section>
    <section class="section">
      <h3>最近调用追踪</h3>
      ${detail.recent_calls.length ? detail.recent_calls.map(traceCard).join("") : '<p class="empty">暂无调用记录。</p>'}
    </section>
  </div>`;
}

function promptCard(title, body) {
  return `<article class="prompt-card"><span>${title}</span><p>${body}</p></article>`;
}

function fieldCard(field) {
  return `<article class="field-card">
    <span>${field.field_name} · ${field.source} · ${field.is_required ? "必填" : "可选"}</span>
    <p>${field.purpose}</p>
    <p>示例：${field.example}</p>
  </article>`;
}

function traceCard(trace) {
  return `<article class="trace-card">
    <span>#${trace.id} · ${trace.status} · ${trace.model_name}</span>
    <pre>${JSON.stringify(trace.final_json, null, 2)}</pre>
  </article>`;
}

async function runTest(moduleId) {
  const result = await getJson(`/api/modules/${moduleId}/test-run`, {
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
  console.log("test run", result);
}

function copyRequestPreview() {
  const text = [...document.querySelectorAll(".prompt-card p")].map((node) => node.textContent).join("\n\n");
  navigator.clipboard.writeText(text);
}

loadMetrics();
loadModules();
