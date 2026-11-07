"use strict";

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const number = (value) => value == null ? "—" : Number(value).toLocaleString("zh-CN");
const compact = (value) => value == null ? "—" : Intl.NumberFormat("en", {notation:"compact", maximumFractionDigits:1}).format(value);
const bytes = (value) => value == null ? "—" : value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${(value / 1024 ** 2).toFixed(0)} MB`;
const dateTime = (value, short = false) => {
  if (!value) return "尚无记录";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (Number.isNaN(date.valueOf())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", ...(short ? {} : {second:"2-digit"}), hour12:false}).format(date);
};
const titles = {overview:["运行总览","把资料、索引与运行状态放在同一个视野里。"], projects:["项目与资料","检查原文新鲜度，回看白名单、证据日期和索引快照。"], tasks:["任务记录","按项目追踪资料导入与后台处理的真实结果。"], models:["模型与用量","查看本地向量模型、摘要服务和服务端用量记录。"], search:["检索验证","选定项目，查找相关资料并回读来源。"], events:["服务事件","定位近期告警与错误，保留事件发生时的上下文。"]};
const syncLabels = {unchanged:"无变更",complete:"已同步",running:"同步中",failed:"同步失败",partial:"部分完成"};
const taskLabels = {pending:["等待中","warning"],running:["执行中","active"],cancelling:["取消中","warning"],completed:["已完成","good"],failed:["失败","bad"],cancelled:["已取消","neutral"]};
const roles = {"source-map":"来源导航","current-status":"当前状态","historical-completed-evidence":"历史证据",contract:"接口契约",operations:"运维说明",entrypoints:"使用入口",provenance:"来源记录","worker-contract":"Worker 契约","privacy-contract":"隐私契约","registry-contract":"注册契约"};
let data = null;
let currentView = "overview";
let selected = "all";
let refreshing = false;
let toastTimer;
let taskGeneration = 0;
let tokenGeneration = 0;
let tokenScope = "";
let taskScope = "";
let searchGeneration = 0;
let taskRows = [];
let taskPages = {};
let taskHistoryLoaded = false;
let taskLoading = false;
let searchHits = [];
let nextRead = null;
let dialogGeneration = 0;

async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {cache:"no-store", signal:AbortSignal.timeout(35000), ...options}); }
  catch (error) { throw new Error(error.name === "TimeoutError" ? "读取超时，请稍后刷新" : "本地看板连接已中断"); }
  const result = await response.json().catch(() => { throw new Error("本地看板返回了无效数据，请稍后刷新"); });
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `请求未完成（HTTP ${response.status}）`);
  return result;
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.remove("hidden");
  toastTimer = setTimeout(() => $("#toast").classList.add("hidden"), 3000);
}

function projects(includeValidation = $("#show-validation").checked) {
  return (data?.projects ?? []).filter((project) => (includeValidation || !project.validation) && (selected === "all" || selected === project.code));
}

function badge(text, kind = "neutral") { return `<span class="badge ${kind}">${esc(text)}</span>`; }
function taskBadge(status) { const [label, kind] = taskLabels[status] || [status || "未知", "neutral"]; return badge(label, kind); }
function available(result) { return result?.available && result.data?.enabled !== false; }
function projectName(code) { return data?.projects.find((project) => project.code === code)?.name || code; }
function projectIdentity(project) {
  const mark = project.validation ? "验" : [...project.code].slice(0, 2).join("").toUpperCase();
  const color = ["", "eval", "manage"][[...project.code].reduce((sum, char) => sum + char.codePointAt(0), 0) % 3];
  return `<div class="project-name"><span class="project-mark ${color}">${esc(mark)}</span><span><strong>${esc(project.name)}</strong><small class="subtext">${esc(project.code)}</small></span></div>`;
}

function freshness(project) {
  if (project.source_error) return badge("状态不可读", "bad");
  if (project.connection && !project.connection.available) return badge("账号连接待检查", "warning");
  if (project.index_error) return badge("索引需检查", "bad");
  if (project.reference_changed_count) return badge("实现引用已变", "warning");
  if (project.changed_count) return badge(`${project.changed_count} 份待同步`, "warning");
  if (project.configuration_changed) return badge("配置待同步", "warning");
  if (!project.snapshot_id) return badge("尚未入库", "neutral");
  if (project.last_sync?.status === "running") return badge("同步中", "active");
  return badge("与原文一致", "good");
}

function renderOptions() {
  const items = (data?.projects ?? []).filter((project) => !project.validation || $("#show-validation").checked);
  const filter = $("#project-filter");
  const prior = selected;
  const filterOptions = `<option value="all">${$("#show-validation").checked ? "全部项目（含验收）" : "全部业务项目"}</option>` + items.map((project) => `<option value="${esc(project.code)}">${esc(project.name)}</option>`).join("");
  if (filter.innerHTML !== filterOptions) filter.innerHTML = filterOptions;
  selected = items.some((project) => project.code === prior) ? prior : "all";
  filter.value = selected;
  const search = $("#search-project");
  const searchPrior = search.value;
  const searchOptions = items.map((project) => `<option value="${esc(project.code)}">${esc(project.name)}</option>`).join("");
  if (search.innerHTML !== searchOptions) search.innerHTML = searchOptions;
  if (items.some((project) => project.code === searchPrior)) search.value = searchPrior;
  if (search.value !== searchPrior) clearSearch();
}

function renderOverview() {
  $("#classic-studio").href = `${data.service_url}/studio/home?view=classic`;
  $("#classic-studio").classList.remove("hidden");
  const items = projects();
  const ready = data.ready.available && data.ready.data.status === "ready";
  const identity = data.service.available && data.service.data.role;
  const connection = $("#connection");
  connection.classList.toggle("offline", !ready || !identity);
  connection.innerHTML = `<span class="status-dot"></span>${ready && identity ? "本机连接已确认" : "服务连接需检查"}`;
  const issues = items.filter((project) => !project.connection.available || project.changed_count || project.source_error || project.index_error || project.configuration_changed || project.reference_changed_count || ["failed","partial"].includes(project.last_sync?.status));
  const attention = $("#attention");
  attention.classList.toggle("hidden", !issues.length && ready && identity);
  if (!ready) {
    attention.innerHTML = "<strong>OpenViking 暂未就绪。</strong> 项目资料状态仍可查看，检索和实时统计将在服务恢复后更新。";
  } else if (!identity) {
    attention.innerHTML = "<strong>监控管理连接的身份尚未确认。</strong> 请检查本机服务地址与管理凭据配置。";
  } else {
    attention.innerHTML = `<strong>${issues.length} 个项目需要关注。</strong> ${issues.map((project) => `${esc(project.name)} ${project.changed_count ? `${project.changed_count} 份原文发生变化` : esc(project.source_error || project.index_error || (!project.connection.available ? "项目账号暂不可用" : project.configuration_changed ? "资料规则发生变化" : project.reference_changed_count ? "实现引用发生变化" : syncLabels[project.last_sync?.status]))}`).join("；")}<button class="text-button" data-go="projects">检查资料</button>`;
  }
  const sourceKnown = items.every((project) => project.source_count != null);
  const vectorsKnown = items.every((project) => available(project.vectors));
  const usageKnown = items.every((project) => available(project.usage));
  const activityKnown = items.every((project) => project.activity?.available);
  const total = (getter) => items.reduce((sum, project) => sum + (getter(project) || 0), 0);
  const metrics = [
    ["项目资料源", sourceKnown ? number(total((project) => project.source_count)) : "—", "份", `${items.length} 个项目 · ${number(total((project) => project.indexed_files))} 份索引原文（含规则）`],
    ["向量条目", vectorsKnown ? number(total((project) => project.vectors.data.status?.vector_count)) : "—", "条", vectorsKnown ? "按项目账号汇总" : "部分项目统计暂不可用"],
    ["活动任务", activityKnown ? `${number(total((project) => project.activity.count))}${items.some((project) => project.activity?.has_more) ? "+" : ""}` : "—", "个", "包含等待、执行与取消中的任务"],
    ["今日 Token", usageKnown ? compact(total((project) => project.usage.data.today_tokens?.total)) : "—", "", usageKnown ? "服务端记录 · 北京时间" : "部分项目用量暂不可用"],
  ];
  $("#metrics").innerHTML = metrics.map(([label,value,unit,note]) => `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}<small>${unit}</small></div><div class="metric-note">${note}</div></div>`).join("");
  $("#overview-projects").innerHTML = items.map((project) => `<tr><td>${projectIdentity(project)}</td><td class="number">${number(project.source_count)}<small class="subtext">索引原文 ${number(project.indexed_files)}</small></td><td>${freshness(project)}</td><td>${esc(syncLabels[project.last_sync?.status] || "尚无记录")}<small class="subtext">${dateTime(project.last_sync?.finished_at || project.last_sync?.started_at, true)}</small></td><td>${badge(project.mcp_verified ? "协议通过" : "需复验", project.mcp_verified ? "good" : "neutral")}</td><td><button class="text-button" data-sources="${esc(project.code)}">资料</button><button class="text-button" data-preview="${esc(project.code)}">同步预检</button></td></tr>`).join("");
  const queueData = data.queue.available ? data.queue.data.status : null;
  const queues = queueData?.queues || [];
  const queueNames = {Embedding:"向量处理",Semantic:"摘要处理",AddResource:"资料导入","Semantic-Nodes":"摘要子任务"};
  const activeQueues = queues.filter((queue) => queue.in_progress || queue.pending).length;
  $("#queue-status").innerHTML = queueData ? badge(activeQueues ? `${activeQueues} 个活动队列` : "当前空闲", activeQueues ? "active" : "good") : badge("暂不可用", "warning");
  $("#queue-caption").textContent = "全服务实时队列，数值为执行中 / 等待。";
  $("#queues").innerHTML = queueData ? queues.filter((queue) => queueNames[queue.queue]).map((queue) => `<div class="queue-row"><span>${queueNames[queue.queue]}</span><progress max="${Math.max(10, queue.pending + queue.in_progress)}" value="${queue.pending + queue.in_progress}" aria-label="${queueNames[queue.queue]}活动数量"></progress><span class="queue-values">${queue.in_progress} / ${queue.pending}</span></div>`).join("") : '<p class="empty">服务队列暂不可用，恢复连接后自动更新。</p>';
  const recent = items.flatMap((project) => project.tasks?.available ? project.tasks.data.items : []).sort((a,b) => b.created_at-a.created_at).slice(0,5);
  $("#recent-tasks").innerHTML = recent.length ? recent.map((task) => `<div class="task-item">${taskBadge(task.status)}<div class="task-item-main"><button class="task-item-title" data-task="${esc(task.task_id)}" data-project="${esc(task.project)}">${esc(projectName(task.project))} · ${esc(task.task_type === "add_resource" ? "资料导入" : task.task_type)}</button><small class="subtext">${esc(task.task_id.slice(0,8))}</small></div><time>${dateTime(task.created_at,true)}</time></div>`).join("") : '<p class="empty">所选项目暂无可见任务记录。</p>';
  const process = data.machine.process;
  $("#system").innerHTML = [["服务地址",data.service_url],["服务版本",data.service.available ? `OpenViking ${data.service.data.version}` : "暂不可用"],["进程内存 / PID",process ? `${bytes(process.memory_bytes)} / ${process.pid}` : "进程信息不可用"],["空闲磁盘",bytes(data.machine.disk_free_bytes)]].map(([key,value]) => `<dl><dt>${key}</dt><dd>${esc(value)}</dd></dl>`).join("");
  $("#nav-projects").textContent = (data.projects || []).filter((project) => !project.validation || $("#show-validation").checked).length;
  const active = total((project) => project.activity?.count);
  $("#nav-active").textContent = activityKnown && active ? active : "";
  $("#updated-at").textContent = `更新于 ${dateTime(data.checked_at)} · 北京时间`;
  $("#footer-scope").textContent = `${data.service_url} · 数据以本次快照为准`;
}

function sourceRows(project) {
  return project.sources.map((source) => {
    const state = {current:["原文一致","good"],changed:["待同步","warning"],missing:["文件缺失","bad"],blocked:["路径异常","bad"]}[source.status] || [source.status,"neutral"];
    return `<div class="source-row"><span class="source-path">${esc(source.path)}<small class="subtext">${esc(roles[source.role] || source.role)}</small></span><span class="source-date">${esc(source.evidence_date || "日期未标注")}</span><span class="source-state">${badge(...state)}</span><button class="text-button source-open" data-source="${esc(source.id)}" data-project="${esc(project.code)}">查看选区</button></div>`;
  }).join("");
}

function renderProjects() {
  const items = projects($("#show-validation").checked);
  $("#project-cards").innerHTML = items.map((project) => `<article class="project-block"><div class="project-block-head">${projectIdentity(project)}<button class="button" data-preview="${esc(project.code)}">同步预检</button></div><p>${esc(project.workspace || "工作区状态不可读")}<br>账号 ${esc(project.account || "未知")} · ${freshness(project)} · ${project.mcp_verified ? "MCP 协议已验收" : "MCP 需复验"}</p>${project.source_error || project.index_error ? `<div class="notice danger">${esc(project.source_error || project.index_error)}</div>` : sourceRows(project)}<p>快照 ${esc(project.snapshot_id?.slice(0,16) || "未建立")} · Git ${esc(project.git_head?.slice(0,10) || "未记录")} · 原生 Codex 会话${project.native_codex_verified ? "已验证" : "待验证"}</p></article>`).join("") || '<p class="empty">当前筛选下没有项目。</p>';
}

function renderModels() {
  const embedding = data.models.embedding;
  const summary = data.models.summary;
  $("#model-configuration").innerHTML = `<section class="panel model-config"><span class="badge good">本地向量模型</span><h3>${esc(embedding.model)}</h3><p>${esc(embedding.provider)} · ${number(embedding.dimension)} 维<br>${esc(embedding.api_base)}</p></section><section class="panel model-config"><span class="badge active">摘要服务</span><h3>${esc(summary.model)}</h3><p>${esc(summary.provider)} · 已配置并发 ${number(summary.max_concurrent)}<br>${esc(summary.api_base)}</p></section>`;
  const rows = [];
  for (const project of projects()) {
    if (!available(project.models)) { rows.push(`<tr><td>${esc(project.name)}</td><td colspan="4">模型统计暂不可用</td></tr>`); continue; }
    const models = project.models.data.status;
    for (const model of [...(models?.vlm || []),...(models?.embedding || [])]) {
      rows.push(`<tr><td>${esc(project.name)}</td><td>${esc(model.Model)}</td><td>${number(model.Calls)}</td><td>${number(model.Prompt)}</td><td>${number(model.Completion)}</td></tr>`);
    }
  }
  $("#model-calls").innerHTML = rows.join("");
}

async function refresh(manual = false) {
  if (refreshing) return;
  refreshing = true;
  $("#refresh").disabled = true;
  try {
    data = await api("/api/overview");
    $("#failure-banner").classList.add("hidden");
    renderOptions();
    renderOverview();
    renderProjects();
    renderModels();
    $("#initial-loading").classList.add("hidden");
    $(`#${currentView}-view`).classList.remove("hidden");
    if (currentView === "tasks" && !taskLoading && (manual || (!taskHistoryLoaded && document.activeElement !== $("#task-query")))) await loadTasks();
    if (currentView === "models") await loadTokens();
    if (currentView === "events") await loadEvents();
    if (manual) toast("已更新本地状态");
  } catch (error) {
    const banner = $("#failure-banner");
    banner.textContent = `${error.message}。${data ? "当前保留上次成功读取的内容。" : "请检查本地看板进程。"}`;
    banner.classList.remove("hidden");
    $("#initial-loading").classList.add("hidden");
    $("#connection").classList.add("offline");
    $("#connection").innerHTML = '<span class="status-dot"></span>看板连接中断';
  } finally { refreshing = false; $("#refresh").disabled = false; }
}

function switchView(view, historyMode = "push") {
  if (!titles[view]) view = "overview";
  currentView = view;
  for (const item of document.querySelectorAll(".view")) item.classList.add("hidden");
  if (data) $(`#${view}-view`).classList.remove("hidden");
  document.querySelectorAll(".nav").forEach((button) => { button.classList.toggle("active", button.dataset.view === view); button.setAttribute("aria-current", button.dataset.view === view ? "page" : "false"); });
  $("#page-title").textContent = titles[view][0];
  $("#breadcrumb").textContent = titles[view][0];
  $("#page-description").textContent = titles[view][1];
  if (location.hash !== `#${view}`) {
    if (historyMode === "push") history.pushState(null, "", `#${view}`);
    else history.replaceState(null, "", `#${view}`);
  }
  const globalView = view === "events";
  $("#project-filter").classList.toggle("hidden", globalView);
  $("#project-filter-label").classList.toggle("hidden", globalView);
  $("#global-scope").classList.toggle("hidden", !globalView);
  if (view === "tasks") loadTasks();
  if (view === "models") loadTokens();
  if (view === "events") loadEvents();
  window.scrollTo({top:0,behavior:"auto"});
}

async function loadTasks(append = false) {
  if (!data) return;
  if (append && taskLoading) return;
  taskLoading = true;
  const generation = ++taskGeneration;
  const query = $("#task-query").value.trim();
  const status = $("#task-status").value;
  const codes = projects($("#show-validation").checked).map((project) => project.code);
  const scope = JSON.stringify([codes, query, status]);
  if (!append && scope !== taskScope) {
    taskRows = [];
    taskPages = {};
    taskHistoryLoaded = false;
    $("#tasks-table").innerHTML = '<tr><td colspan="6"><p class="empty">正在读取所选任务…</p></td></tr>';
    $("#tasks-pagination").innerHTML = "";
    taskScope = scope;
  }
  const targets = append ? codes.filter((code) => taskPages[code]?.has_more) : codes;
  $("#tasks-count").textContent = "正在读取任务记录…";
  try {
    const results = await Promise.all(targets.map(async (code) => {
      const params = new URLSearchParams({q:query,status});
      if (append) params.set("cursor", taskPages[code].next_cursor);
      return [code,await api(`/api/projects/${encodeURIComponent(code)}/tasks?${params}`)];
    }));
    if (generation !== taskGeneration) return;
    if (!append) { taskRows = []; taskPages = {}; taskHistoryLoaded = false; }
    if (append) taskHistoryLoaded = true;
    const errors = [];
    for (const [code,result] of results) {
      if (!result.available) { errors.push(projectName(code)); continue; }
      taskRows.push(...result.data.items);
      taskPages[code] = result.data;
    }
    taskRows = [...new Map(taskRows.map((task) => [`${task.project}/${task.task_id}`,task])).values()].sort((a,b) => b.created_at-a.created_at);
    $("#tasks-table").innerHTML = taskRows.length ? taskRows.map((task) => `<tr><td>${esc(projectName(task.project))}</td><td><strong>${esc(task.task_type === "add_resource" ? "资料导入" : task.task_type)}</strong><small class="subtext resource-path" title="${esc(task.resource_id)}">${esc(task.resource_id || task.task_id)}</small></td><td>${taskBadge(task.status)}</td><td class="number">${dateTime(task.created_at)}</td><td class="number">${task.processing_seconds == null ? "—" : `${Number(task.processing_seconds).toFixed(1)} 秒`}</td><td><button class="text-button" data-task="${esc(task.task_id)}" data-project="${esc(task.project)}">详情</button></td></tr>`).join("") : `<tr><td colspan="6"><p class="empty">${errors.length ? "项目任务暂不可用，请检查连接。" : "没有符合筛选条件的任务。"}</p></td></tr>`;
    $("#tasks-count").textContent = `已载入 ${taskRows.length} 条${errors.length ? ` · ${errors.join("、")} 暂不可用` : ""}`;
    const more = Object.values(taskPages).some((page) => page.has_more);
    $("#tasks-pagination").innerHTML = (more ? '<button id="more-tasks" class="text-button">加载更多记录</button>' : errors.length ? "部分项目记录暂不可用，可点击刷新重试" : "已载入所选项目的全部匹配记录") + (taskHistoryLoaded ? " · 已载入的历史分页将保留，可点击刷新更新列表" : "");
  } catch (error) {
    if (generation === taskGeneration) {
      $("#tasks-count").textContent = error.message + (taskRows.length ? "，当前保留已载入的记录。" : "，可点击刷新重试。");
      if (!taskRows.length) $("#tasks-table").innerHTML = '<tr><td colspan="6"><p class="empty">暂时无法读取所选任务。</p></td></tr>';
    }
  }
  finally { if (generation === taskGeneration) taskLoading = false; }
}

async function loadTokens() {
  const generation = ++tokenGeneration;
  const includeValidation = $("#show-validation").checked;
  const scope = JSON.stringify([selected, includeValidation]);
  if (scope !== tokenScope) {
    $("#token-chart").innerHTML = '<p class="empty">正在读取所选项目用量…</p>';
    $("#token-table").innerHTML = "";
  }
  try {
    const result = await api(`/api/tokens?project_code=${encodeURIComponent(selected)}&include_validation=${includeValidation}`);
    if (generation !== tokenGeneration) return;
    tokenScope = scope;
    const rows = result.items;
    if (!rows.length) { $("#token-chart").innerHTML = '<p class="empty">用量记录暂不可用，连接恢复后可重新读取。</p>'; $("#token-table").innerHTML = ""; return; }
    const maximum = Math.max(1,...rows.map((row) => row.vlm_input+row.vlm_output+row.embedding_input));
    const width = 900, height = 220, left = 58, bottom = 185, top = 15;
    const step = (width-left-20)/rows.length;
    const plotHeight = bottom-top;
    let drawing = "";
    for (let tick=0;tick<=3;tick++) { const y=bottom-tick*plotHeight/3; drawing += `<line x1="${left}" y1="${y}" x2="880" y2="${y}" stroke="#e7ecf3"/><text x="46" y="${y+4}" text-anchor="end">${compact(maximum*tick/3)}</text>`; }
    rows.forEach((row,index) => {
      let y = bottom;
      for (const [key,color] of [["embedding_input","#3d9e96"],["vlm_output","#8ca7ed"],["vlm_input","#2357d7"]]) {
        const barHeight = row[key]/maximum*plotHeight;
        y -= barHeight;
        drawing += `<rect x="${left+index*step+step*.24}" y="${y}" width="${step*.52}" height="${barHeight}" fill="${color}" rx="2"><title>${esc(row.date)} ${key} ${number(row[key])}</title></rect>`;
      }
      drawing += `<text x="${left+(index+.5)*step}" y="210" text-anchor="middle">${esc(row.date.slice(5).replace("-","/"))}</text>`;
    });
    $("#token-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="最近七天各类 Token 用量，下方表格提供完整数值">${drawing}</svg>${result.unavailable_projects.length ? '<p class="form-note">部分项目记录暂不可用，图表仅汇总已读取的数据。</p>' : ""}`;
    $("#token-table").innerHTML = `<table><thead><tr><th>北京时间</th><th>摘要输入</th><th>摘要输出</th><th>向量输入</th><th>合计</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${esc(row.date)}</td><td>${number(row.vlm_input)}</td><td>${number(row.vlm_output)}</td><td>${number(row.embedding_input)}</td><td>${number(row.vlm_input+row.vlm_output+row.embedding_input)}</td></tr>`).join("")}</tbody></table>`;
  } catch (error) {
    if (generation === tokenGeneration) {
      $("#token-chart").innerHTML = `<p class="empty">${esc(error.message)}</p>`;
      $("#token-table").innerHTML = "";
    }
  }
}

async function loadEvents() {
  try {
    const result = await api("/api/events");
    $("#events-list").innerHTML = result.items.length ? result.items.map((item) => `<div class="event-item">${badge(item.level === "error" ? "错误" : "告警",item.level === "error" ? "bad" : "warning")}<pre>${esc(item.message)}</pre></div>`).join("") : '<p class="empty">最近日志中没有错误或告警记录。</p>';
  } catch (error) { $("#events-list").innerHTML = `<p class="empty">${esc(error.message)}</p>`; }
}

function openDialog(title, subtitle, html) {
  dialogGeneration++;
  $("#detail-title").textContent = title;
  $("#detail-subtitle").textContent = subtitle || "";
  $("#detail-body").innerHTML = html;
  nextRead = null;
  if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
  return dialogGeneration;
}

async function viewSource(code, id) {
  const generation = openDialog("资料选区", "正在读取白名单原文", '<p class="empty">读取中…</p>');
  try {
    const result = await api(`/api/projects/${encodeURIComponent(code)}/source/${encodeURIComponent(id)}`);
    if (generation !== dialogGeneration || !$("#detail-dialog").open) return;
    $("#detail-title").textContent = result.source.path.split("/").at(-1);
    $("#detail-subtitle").textContent = `${projectName(code)} · 本地选区 · 证据日期 ${result.source.evidence_date || "未标注"} · 原文行 ${result.line_ranges.map((range) => range.join("–")).join("、")}`;
    $("#detail-body").innerHTML = `${result.source.status !== "current" ? '<div class="notice">本地原文已变化。当前展示本地选区，索引仍需同步。</div>' : ""}<pre class="source-preview">${esc(result.content)}</pre>`;
  } catch (error) { if (generation === dialogGeneration && $("#detail-dialog").open) $("#detail-body").innerHTML = `<div class="notice danger">${esc(error.message)}</div>`; }
}

async function previewSync(code) {
  const generation = openDialog(`${projectName(code)} 同步预检`, "预检不调用摘要或向量模型", '<p class="empty">正在检查白名单与索引差异…</p>');
  try {
    const result = await api(`/api/projects/${encodeURIComponent(code)}/preview`);
    if (generation !== dialogGeneration || !$("#detail-dialog").open) return;
    const changed = result.changed || [];
    const removed = result.removed || [];
    $("#detail-body").innerHTML = `<div class="notice ${changed.length || removed.length ? "" : "hidden"}">${changed.length} 份变更，${removed.length} 份移除。实际同步请在本机使用项目管理命令执行。</div><dl class="detail-grid"><div><dt>预检结果</dt><dd>${changed.length || removed.length ? "有待同步内容" : "与当前索引一致"}</dd></div><div><dt>模型调用</dt><dd>${number(result.model_calls)} 次</dd></div><div><dt>变更文件</dt><dd>${changed.map(esc).join("<br>") || "无"}</dd></div><div><dt>移除文件</dt><dd>${removed.map(esc).join("<br>") || "无"}</dd></div></dl>`;
  } catch (error) { if (generation === dialogGeneration && $("#detail-dialog").open) $("#detail-body").innerHTML = `<div class="notice danger">${esc(error.message)}</div>`; }
}

async function readHit(index) {
  const hit = searchHits[index];
  if (!hit) return;
  const code = hit.project_code;
  openDialog("索引原文", hit.uri, '<p class="empty">正在回读原文…</p>');
  await readPage({project_code:code,uri:hit.uri,snapshot_id:hit.snapshot_id}, false);
}

async function readPage(payload, append) {
  const generation = dialogGeneration;
  try {
    const result = await api("/api/read", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if (generation !== dialogGeneration || !$("#detail-dialog").open) return;
    if (!append) $("#detail-body").innerHTML = '<pre class="source-preview" id="indexed-content"></pre><div class="dialog-actions" id="read-actions"></div>';
    $("#indexed-content").textContent += result.content;
    nextRead = result.has_more ? {...payload,snapshot_id:result.snapshot_id,offset:result.next_offset,char_offset:result.next_char_offset} : null;
    $("#read-actions").innerHTML = nextRead ? '<button id="read-more" class="button">继续读取</button>' : '<span class="subtext">已完整回读本份索引原文</span>';
  } catch (error) {
    if (generation !== dialogGeneration || !$("#detail-dialog").open) return;
    if (!append) $("#detail-body").innerHTML = `<div class="notice danger">${esc(error.message)}</div>`;
    else {
      toast(error.message);
      const retry = $("#read-more");
      if (retry) retry.disabled = false;
    }
  }
}

function clearSearch() {
  searchGeneration++;
  searchHits = [];
  $("#search-results").innerHTML = "";
  $("#search-status").textContent = "";
  $("#search-submit").disabled = false;
}

$("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("#search-query").value.trim();
  if (!query) {
    $("#search-query").setCustomValidity("请输入需要检索的问题");
    $("#search-query").reportValidity();
    return;
  }
  const generation = ++searchGeneration;
  $("#search-submit").disabled = true;
  $("#search-status").textContent = "正在检索所选项目…";
  $("#search-results").innerHTML = "";
  const code = $("#search-project").value;
  try {
    const result = await api("/api/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project_code:code,query})});
    if (generation !== searchGeneration) return;
    searchHits = (result.sources || []).map((hit) => ({...hit,project_code:code}));
    $("#search-status").textContent = searchHits.length ? `${projectName(code)} 找到 ${searchHits.length} 条资料线索，请回读原文确认。` : "没有找到相关资料，可调整问题中的项目术语。";
    $("#search-results").innerHTML = searchHits.map((hit,index) => `<article class="search-result"><h3>${esc(hit.source_path?.split("/").at(-1) || hit.uri.split("/").at(-1))}</h3><small>${esc(hit.uri)} · 证据日期 ${esc(hit.evidence_date || "未标注")}</small><p>${esc(hit.generated_summary || "资料已命中，点击回读查看内容。")}</p><button class="text-button" data-read-hit="${index}">回读原文</button></article>`).join("");
  } catch (error) { if (generation === searchGeneration) $("#search-status").textContent = error.message; }
  finally { if (generation === searchGeneration) $("#search-submit").disabled = false; }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.view || button.dataset.go) switchView(button.dataset.view || button.dataset.go);
  if (button.dataset.sources) { selected = button.dataset.sources; $("#project-filter").value = selected; renderOverview(); renderProjects(); switchView("projects"); }
  if (button.dataset.source) viewSource(button.dataset.project, button.dataset.source);
  if (button.dataset.preview) previewSync(button.dataset.preview);
  if (button.dataset.task) {
    const task = [...taskRows,...(data?.projects || []).flatMap((project) => project.tasks?.data?.items || [])].find((task) => task.task_id === button.dataset.task && task.project === button.dataset.project);
    if (task) openDialog("任务详情", `${projectName(task.project)} · ${task.task_id}`, `<dl class="detail-grid">${[["状态",taskLabels[task.status]?.[0] || task.status],["创建时间",dateTime(task.created_at)],["处理阶段",task.stage || "—"],["处理用时",task.processing_seconds == null ? "—" : `${Number(task.processing_seconds).toFixed(1)} 秒`],["资源",task.resource_id || "—"],["错误",task.error ? JSON.stringify(task.error) : "未记录错误"]].map(([key,value]) => `<div><dt>${key}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>`);
  }
  if (button.dataset.readHit !== undefined) readHit(Number(button.dataset.readHit));
  if (button.id === "more-tasks") loadTasks(true);
  if (button.id === "read-more" && nextRead) { button.disabled = true; await readPage(nextRead,true); }
});

$("#refresh").addEventListener("click",() => refresh(true));
$("#close-dialog").addEventListener("click",() => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("close",() => { dialogGeneration++; nextRead = null; });
$("#search-project").addEventListener("change", clearSearch);
$("#search-query").addEventListener("input", () => $("#search-query").setCustomValidity(""));
$("#project-filter").addEventListener("change",() => {
  selected = $("#project-filter").value;
  renderOverview();
  renderProjects();
  renderModels();
  if (selected !== "all" && $("#search-project").value !== selected) {
    $("#search-project").value = selected;
    clearSearch();
  }
  if (currentView === "tasks") loadTasks();
  if (currentView === "models") loadTokens();
});
$("#show-validation").addEventListener("change",() => { renderOptions(); renderProjects(); renderOverview(); renderModels(); });
$("#task-status").addEventListener("change",() => loadTasks());
let taskSearchTimer;
$("#task-query").addEventListener("input",() => { clearTimeout(taskSearchTimer); taskSearchTimer = setTimeout(() => loadTasks(),300); });
$("#load-events").addEventListener("click",loadEvents);
$("#load-tokens").addEventListener("click",loadTokens);
function restoreView() {
  if (location.hash !== "#main" && location.hash.slice(1) !== currentView) switchView(location.hash.slice(1), "replace");
}
window.addEventListener("hashchange", restoreView);
window.addEventListener("popstate", restoreView);
setInterval(() => { if ($("#auto-refresh").checked && !document.hidden) refresh(); },15000);
switchView(location.hash.slice(1) || "overview", "replace");
refresh();
