"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { documents: [], health: null, lessons: [], currentSources: [], answers: [], selectedDocuments: new Set(), busy: false, evaluation: null, split: "holdout", lesson: 0, deleting: null, drawerFocus: null, restoringDemo: false, auth: null, workspaceId: null, contextVersion: 0, identityRequest: 0 };
const titles = { products: "产品规格", service: "售后服务", trial: "平台试用", tickets: "工单流程", travel: "出差报销", security: "信息安全", remote: "远程办公", onboarding: "入职指南" };
const title = filename => titles[filename.replace(/\.md$/, "")] ? `${titles[filename.replace(/\.md$/, "")]} · ${filename}` : filename;
const names = { chat: "问答工作台", documents: "知识文档", evaluation: "评测实验室", learn: "面试练习" };

function permissionsFor(auth, workspaceId) {
  const personal = auth?.enabled === false;
  const signedIn = auth?.enabled === true && auth.authenticated === true && !!auth.user;
  const systemAdmin = signedIn && auth.user.is_admin === true;
  const workspace = signedIn ? (auth.workspaces || []).find(item => String(item.id) === String(workspaceId)) : null;
  const member = !!workspace && ["viewer", "editor", "admin"].includes(workspace.role);
  const canRead = personal || (signedIn && !!workspace && (systemAdmin || member));
  return { personal, signedIn, canRead, canWrite: personal || (canRead && (systemAdmin || ["editor", "admin"].includes(workspace?.role))), canConfigure: personal || systemAdmin, canEvaluate: personal || systemAdmin, canManage: systemAdmin, role: personal ? "personal" : workspace?.role || null };
}
function buildRequestHeaders(url, method, multipart, auth, workspaceId) {
  const headers = multipart ? {} : { "Content-Type": "application/json" };
  if (workspaceId && !url.startsWith("/api/auth/") && !url.startsWith("/api/admin/")) headers["X-Workspace-ID"] = String(workspaceId);
  if (auth?.enabled && auth.authenticated && auth.csrf_token && ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase())) headers["X-CSRF-Token"] = auth.csrf_token;
  return headers;
}
function permissions() { return permissionsFor(state.auth, state.workspaceId); }
function denied(message = "你没有执行此操作的权限。") { toast(message, true); }
function ignoreError(error) { return error.stale || error.status === 401; }

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}
function button(text, className, action, iconName) {
  const node = element("button", className);
  node.type = "button";
  if (iconName) node.append(icon(iconName));
  if (text) node.append(document.createTextNode(text));
  if (action) node.addEventListener("click", action);
  return node;
}
let toastTimer;
function toast(message, error = false) {
  const node = document.getElementById("toast");
  if (!node) return;
  clearTimeout(toastTimer);
  node.textContent = message;
  node.className = `toast${error ? " error" : ""}`;
  node.hidden = false;
  toastTimer = setTimeout(() => { node.hidden = true; }, 5500);
}
async function api(url, options = {}) {
  const context = state.contextVersion;
  const authRequest = url === "/api/auth/status" || url === "/api/auth/login";
  const headers = { ...options.headers, ...buildRequestHeaders(url, options.method || "GET", options.body instanceof FormData, state.auth, state.workspaceId) };
  const response = await fetch(url, { ...options, credentials: "same-origin", headers });
  let data;
  try { data = await response.json(); } catch { throw new Error("服务返回了无法读取的内容，请检查本机服务。"); }
  if (!authRequest && context !== state.contextVersion) { const error = new Error("当前身份或空间已改变。"); error.stale = true; throw error; }
  if (!response.ok) {
    const error = new Error(Array.isArray(data.detail) ? "输入不符合要求，请检查字段格式、长度和选项。" : data.detail || (response.status === 403 ? "权限不足，操作已被拒绝。" : "操作未成功，请重试。"));
    error.status = response.status;
    if (response.status === 401 && !authRequest) expireSession();
    throw error;
  }
  return data;
}
function clearSecrets() { $$("input[type='password']").forEach(node => { node.value = ""; }); }
function clearWorkspaceState() {
  state.contextVersion++;
  state.documents = []; state.health = null; state.answers = []; state.currentSources = [];
  state.selectedDocuments.clear(); state.evaluation = null; state.deleting = null; state.busy = false; state.restoringDemo = false;
  closeDrawer();
  if ($("#delete-dialog").open) $("#delete-dialog").close();
  const welcome = initialWelcome.cloneNode(true);
  $("#conversation").replaceChildren(welcome); bindWelcome(welcome);
  $("#question").value = ""; $("#document-search").value = ""; $("#file-input").value = "";
  $("#mode").value = "extractive"; $("#strategy").value = "hybrid"; $("#active-mode-label").textContent = "本地摘录";
  const llm = $('#mode option[value="llm"]'); llm.disabled = true; llm.textContent = "大模型生成 · 未配置";
  const semantic = $('#strategy option[value="semantic"]'); semantic.disabled = true; semantic.textContent = "语义检索 · 未就绪";
  $("#upload-progress").hidden = true; $("#nav-doc-count").textContent = "0"; $("#document-total").textContent = "0";
  $("#evaluation-content").replaceChildren(element("div", "empty-state", "选择工作空间后读取评测报告。"));
  renderEvidence([], false); renderDocuments(); renderScope(); renderWelcome(); clearSecrets();
}
function applyPermissions() {
  const p = permissions();
  const enterprise = state.auth?.enabled === true;
  document.title = enterprise ? "知序 · 团队知识空间" : "知序 · 我的知识空间";
  $("#runtime-mode-label").textContent = enterprise ? "团队模式" : "本机运行";
  $("#workspace-footer-label").textContent = enterprise ? "团队知识空间 · 示例内容为虚构资料" : "本地个人工作空间 · 示例内容为虚构资料";
  $("#question").disabled = !p.canRead;
  $("#send-button").disabled = !p.canRead || state.busy;
  $("#new-chat").disabled = !p.canRead || state.busy;
  ["#scope-button", "#mode", "#strategy"].forEach(selector => { $(selector).disabled = !p.canRead; });
  $("#file-input").disabled = !p.canWrite;
  $("#dropzone").setAttribute("aria-disabled", String(!p.canWrite));
  $("#dropzone").tabIndex = p.canWrite ? 0 : -1;
  $$("[data-restore-demo]").forEach(node => { node.disabled = !p.canWrite || state.restoringDemo; });
  $$("[data-welcome-action='upload']").forEach(node => { node.disabled = !p.canWrite; });
  $$(".delete-action").forEach(node => { node.disabled = !p.canWrite; });
  ["#settings-button", "#topbar-settings-button"].forEach(selector => { $(selector).disabled = !p.canConfigure; $(selector).title = p.canConfigure ? "模型配置" : "仅系统管理员可配置模型"; });
  $("#run-evaluation").disabled = !p.canEvaluate;
  $("#run-evaluation").title = p.canEvaluate ? "运行固定评测" : "仅系统管理员可运行评测";
  $("#admin-button").hidden = !p.canManage;
  $("#workspace-notice").hidden = !state.auth?.enabled || p.canRead;
  $("#workspace-notice").textContent = p.canManage ? "当前没有可用空间。请打开系统管理创建空间。" : "尚未获得工作空间授权，请等待管理员分配。";
  renderWelcome();
}
function showAuthScreen(show, message = "") {
  $("#auth-overlay").hidden = !show;
  document.body.classList.toggle("auth-locked", show);
  $$("body > .sidebar, body > main").forEach(node => { node.inert = show; if (show) node.setAttribute("aria-hidden", "true"); else node.removeAttribute("aria-hidden"); });
  if (show) {
    const login = state.auth?.enabled === true;
    $("#auth-message").textContent = message || "使用管理员分配的账号登录，访问已授权的资料空间。";
    $("#login-form").hidden = !login; $("#login-retry").hidden = login;
    if (login) $("#login-username").focus();
  }
}
function applyAuthStatus(data) {
  if (typeof data.enabled !== "boolean") throw new Error("服务返回的身份状态无效，请重试。");
  const previousRole = (state.auth?.workspaces || []).find(item => String(item.id) === state.workspaceId)?.role || "";
  const previous = `${state.auth?.enabled}:${state.auth?.user?.id || ""}:${state.auth?.user?.is_admin === true}:${state.workspaceId || ""}:${previousRole}`;
  const authenticated = data.enabled && data.authenticated === true && !!data.user;
  state.auth = { enabled: data.enabled, authenticated, user: authenticated ? data.user : null, csrf_token: authenticated ? data.csrf_token || null : null, workspaces: authenticated && Array.isArray(data.workspaces) ? data.workspaces : [] };
  const workspaces = state.auth.workspaces;
  if (!workspaces.some(item => String(item.id) === state.workspaceId)) state.workspaceId = workspaces.length ? String(workspaces[0].id) : null;
  const currentRole = workspaces.find(item => String(item.id) === state.workspaceId)?.role || "";
  const current = `${state.auth.enabled}:${state.auth.user?.id || ""}:${state.auth.user?.is_admin === true}:${state.workspaceId || ""}:${currentRole}`;
  if (previous !== current) clearWorkspaceState();
  const select = $("#workspace-select"); select.replaceChildren();
  workspaces.forEach(workspace => { const option = element("option", "", workspace.name); option.value = String(workspace.id); select.append(option); });
  select.value = state.workspaceId || ""; select.disabled = !workspaces.length;
  $("#enterprise-bar").hidden = !state.auth.enabled || !state.auth.authenticated;
  document.body.classList.toggle("enterprise-mode", state.auth.enabled);
  $("#account-name").textContent = state.auth.user?.username || "";
  const workspace = workspaces.find(item => String(item.id) === state.workspaceId);
  const role = permissions().role;
  $("#workspace-role").textContent = state.auth.user?.is_admin ? "系统管理员" : { viewer: "只读成员", editor: "编辑成员", admin: "空间管理员" }[role] || "等待授权";
  $("#space-name").textContent = workspace?.name || (state.auth.enabled ? "未分配空间" : "我的知识空间");
  $("#space-description").textContent = state.auth.enabled ? "按工作空间隔离资料" : "本地个人工作空间";
  $("#space-avatar").textContent = workspace?.name?.slice(0, 1) || (state.auth.enabled ? "空" : "我");
  showAuthScreen(state.auth.enabled && !state.auth.authenticated);
  applyPermissions();
  return previous !== current;
}
function expireSession() {
  state.identityRequest++;
  applyAuthStatus({ enabled: true, authenticated: false });
  $("#login-username").value = "";
  $("#login-error").textContent = "登录状态已失效，请重新登录。";
}
async function refreshIdentity() {
  const request = ++state.identityRequest;
  const data = await api("/api/auth/status");
  if (request !== state.identityRequest) return false;
  return applyAuthStatus(data);
}
async function loadWorkspace() {
  if (!permissions().canRead) { $("#runtime-text").textContent = "等待工作空间授权"; return; }
  await refreshDocuments();
  const active = $(".nav-item[data-view].active")?.dataset.view;
  if (active === "evaluation") await loadEvaluation();
}
async function bootstrap() {
  $("#login-error").textContent = ""; $("#login-retry").disabled = true;
  try { await refreshIdentity(); await loadWorkspace(); }
  catch (error) { if (ignoreError(error)) return; if (!state.auth) showAuthScreen(true, error.message); else toast(error.message, true); $("#runtime-dot").classList.add("offline"); $("#runtime-text").textContent = "服务连接失败"; }
  finally { $("#login-retry").disabled = false; }
}
async function login(event) {
  event.preventDefault();
  const submit = $("#login-submit"); if (submit.disabled) return;
  const body = JSON.stringify({ username: $("#login-username").value.trim(), password: $("#login-password").value });
  $("#login-password").value = ""; $("#login-error").textContent = ""; submit.disabled = true;
  try {
    const data = await api("/api/auth/login", { method: "POST", body }); state.identityRequest++; applyAuthStatus(data); await loadWorkspace();
    if (permissions().canRead) $("#question").focus(); else if (permissions().canManage) $("#admin-button").focus(); else $("#logout-button").focus();
  }
  catch (error) { if (!error.stale) $("#login-error").textContent = error.message; }
  finally { $("#login-password").value = ""; submit.disabled = false; }
}
async function logout() {
  $("#logout-button").disabled = true;
  try { await api("/api/auth/logout", { method: "POST" }); state.identityRequest++; applyAuthStatus({ enabled: true, authenticated: false }); $("#login-username").value = ""; $("#login-error").textContent = ""; }
  catch (error) { if (!ignoreError(error)) toast(error.message, true); }
  finally { clearSecrets(); $("#logout-button").disabled = false; }
}
async function changeWorkspace() {
  const selected = $("#workspace-select").value;
  if (selected === state.workspaceId || !state.auth?.workspaces.some(item => String(item.id) === selected)) return;
  state.workspaceId = selected; clearWorkspaceState(); applyAuthStatus(state.auth);
  try { await loadWorkspace(); } catch (error) { if (!ignoreError(error)) toast(error.message, true); }
}
function view(name) {
  if (!state.auth || (state.auth.enabled && !state.auth.authenticated)) return;
  $$(".view").forEach(node => { const active = node.id === `view-${name}`; node.hidden = !active; node.classList.toggle("active", active); });
  $$(".nav-item[data-view]").forEach(node => { const active = node.dataset.view === name; node.classList.toggle("active", active); if (active) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
  $("#breadcrumb-current").textContent = names[name];
  $("#scope-popover").hidden = true;
  if (name === "evaluation") loadEvaluation();
  if (name === "learn" && !state.lessons.length) loadLessons();
}
async function refreshDocuments() {
  if (!permissions().canRead) return;
  const [data, health] = await Promise.all([api("/api/documents"), api("/api/health")]);
  state.documents = data.documents;
  state.health = health;
  state.selectedDocuments = new Set([...state.selectedDocuments].filter(id => state.documents.some(d => d.id === id)));
  $("#nav-doc-count").textContent = data.documents.length;
  $("#document-total").textContent = data.documents.length;
  $("#runtime-text").textContent = `服务已连接 · ${health.document_count} 份资料`;
  $("#runtime-dot").classList.remove("offline");
  $$("[data-app-version]").forEach(node => { node.textContent = health.version ? `v${health.version}` : ""; });
  const llm = $('#mode option[value="llm"]');
  llm.disabled = !health.model.enabled;
  llm.textContent = health.model.enabled ? `大模型 · ${health.model.name}` : "大模型生成 · 未配置";
  if (!health.model.enabled && $("#mode").value === "llm") $("#mode").value = "extractive";
  $("#active-mode-label").textContent = $("#mode").value === "llm" ? "模型生成" : "本地摘录";
  const semantic = $('#strategy option[value="semantic"]');
  semantic.disabled = !health.semantic.available;
  semantic.textContent = health.semantic.available ? "语义检索 · 本机 BGE" : "语义检索 · 未就绪";
  if (!health.semantic.available && $("#strategy").value === "semantic") $("#strategy").value = "hybrid";
  renderDocuments();
  renderScope();
  renderWelcome();
  applyPermissions();
}
function renderWelcome() {
  const welcome = $("#welcome");
  if (!welcome) return;
  const count = state.documents.length;
  const p = permissions();
  $("#welcome-title", welcome).textContent = !p.canRead && state.auth?.authenticated ? "等待空间授权" : count ? "向你的资料提问" : "从第一份资料开始";
  $("#welcome-description", welcome).textContent = !p.canRead && state.auth?.authenticated ? p.canManage ? "请在系统管理中创建工作空间，再添加资料。" : "管理员尚未为你分配空间，获得授权后即可查看和提问。" : count ? `当前有 ${count} 份资料。提问后，打开引用核对原文。` : p.canWrite ? "上传 PDF、Word、Markdown 或 TXT，或导入一组虚构示例体验问答。" : "当前空间还没有资料，请联系空间编辑者添加。";
  $$(".example", welcome).forEach(node => { node.disabled = !count || state.restoringDemo; });
  $("[data-restore-demo]", welcome).disabled = !p.canWrite || state.restoringDemo;
  $("[data-welcome-action='upload']", welcome).disabled = !p.canWrite;
}
function bindWelcome(welcome) {
  $$(".example", welcome).forEach(node => node.addEventListener("click", () => { $("#question").value = node.dataset.question; ask(); }));
  $("[data-welcome-action='upload']", welcome).addEventListener("click", () => { if (!permissions().canWrite) return denied("当前账号不能上传资料。"); view("documents"); $("#file-input").click(); });
  $("[data-restore-demo]", welcome).addEventListener("click", restoreDemo);
}
async function restoreDemo() {
  if (!permissions().canWrite) return denied("当前账号不能添加示例资料。");
  if (state.restoringDemo) return;
  const context = state.contextVersion;
  state.restoringDemo = true;
  $$("[data-restore-demo]").forEach(node => { node.disabled = true; });
  try {
    await api("/api/demo/restore", { method: "POST" });
    await refreshDocuments();
    toast(`示例资料已准备好，当前共 ${state.documents.length} 份资料。重复内容自动去重。`);
  } catch (error) { if (!ignoreError(error)) toast(error.message, true); }
  finally {
    if (context !== state.contextVersion) return;
    state.restoringDemo = false;
    $$("[data-restore-demo]").forEach(node => { node.disabled = !permissions().canWrite; });
    renderWelcome();
  }
}
function renderDocuments() {
  const query = $("#document-search").value.toLocaleLowerCase();
  const docs = state.documents.filter(d => (title(d.filename)).toLocaleLowerCase().includes(query));
  const tbody = $("#document-list");
  tbody.replaceChildren();
  docs.forEach(doc => {
    const row = element("tr");
    const nameCell = element("td");
    const nameWrap = element("div", "document-name");
    const fileIcon = element("span", "document-icon"); fileIcon.append(icon("files"));
    const nameDetail = element("div");
    nameDetail.append(button(title(doc.filename), "", () => openDocument(doc.id)), element("small", "", `${formatBytes(doc.byte_size)} · 已建立检索索引`));
    nameWrap.append(fileIcon, nameDetail); nameCell.append(nameWrap);
    const actions = element("td"); const wrap = element("div", "table-actions");
    const open = button("", "icon-button", () => openDocument(doc.id), "files"); open.setAttribute("aria-label", `查看 ${doc.filename}`);
    const remove = button("", "icon-button delete-action", () => confirmDelete(doc), "trash"); remove.setAttribute("aria-label", `删除 ${doc.filename}`); remove.disabled = !permissions().canWrite;
    wrap.append(open, remove); actions.append(wrap);
    row.append(nameCell, element("td", "", (doc.kind || doc.filename.split(".").pop()).toUpperCase()), element("td", "", `${doc.chunk_count} 个片段`), element("td", "", formatDate(doc.created_at)), actions);
    tbody.append(row);
  });
  $("#document-empty").hidden = !!docs.length;
  $("#document-empty").textContent = query ? "没有找到匹配的文档。" : "还没有资料。上传一份文档，或点击“添加示例资料”体验。";
}
function formatBytes(value) { return value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${(value / 1024).toFixed(1)} KB`; }
function formatDate(value) { const date = new Date(value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
function renderScope() {
  $("#scope-label").textContent = state.selectedDocuments.size ? `已选 ${state.selectedDocuments.size} 份` : "全部文档";
  const pop = $("#scope-popover"); pop.replaceChildren(element("div", "scope-title", "选择检索范围 · 未选时检索全部"));
  if (!state.documents.length) pop.append(element("p", "muted", "请先上传资料。"));
  state.documents.forEach(doc => {
    const label = element("label"); const input = element("input"); input.type = "checkbox"; input.checked = state.selectedDocuments.has(doc.id);
    input.addEventListener("change", () => { if (input.checked) state.selectedDocuments.add(doc.id); else state.selectedDocuments.delete(doc.id); $("#scope-label").textContent = state.selectedDocuments.size ? `已选 ${state.selectedDocuments.size} 份` : "全部文档"; });
    label.append(input, document.createTextNode(title(doc.filename))); pop.append(label);
  });
  pop.append(button("清除选择，检索全部", "text-button", () => { state.selectedDocuments.clear(); renderScope(); }));
}
async function uploadFiles(files) {
  if (!permissions().canWrite) return denied("当前账号不能上传资料。");
  const context = state.contextVersion;
  const queue = [...files];
  if (!queue.length) return;
  const progress = $("#upload-progress"); progress.hidden = false;
  let success = 0; const failures = [];
  for (let i = 0; i < queue.length; i++) {
    if (context !== state.contextVersion) return;
    const file = queue[i];
    progress.textContent = `正在导入 ${i + 1}/${queue.length}：${file.name}`;
    if (file.size > 10 * 1024 * 1024) { failures.push(`${file.name}：超过 10 MB`); continue; }
    if (!/\.(pdf|docx|md|txt)$/i.test(file.name)) { failures.push(`${file.name}：仅支持 PDF、DOCX、Markdown、TXT`); continue; }
    try { const form = new FormData(); form.append("file", file); const result = await api("/api/documents", { method: "POST", body: form }); success++; if (result.existing) toast(`${file.name} 已存在，自动去重。`); }
    catch (error) { if (ignoreError(error)) return; failures.push(`${file.name}：${error.message}`); }
  }
  if (context !== state.contextVersion) return;
  progress.textContent = `导入完成：${success} 份成功${failures.length ? `，${failures.length} 份未导入。${failures.join("；")}` : "。资料已可检索。"}`;
  $("#file-input").value = "";
  try { await refreshDocuments(); } catch (error) { if (!ignoreError(error)) toast(error.message, true); }
}
function confirmDelete(doc) {
  if (!permissions().canWrite) return denied("当前账号不能删除资料。");
  state.deleting = doc;
  $("#delete-description").textContent = title(doc.filename);
  $("#delete-dialog").showModal();
}
async function deleteConfirmed() {
  if (!permissions().canWrite) return denied("当前账号不能删除资料。");
  if (!state.deleting) return;
  const doc = state.deleting;
  $("#confirm-delete").disabled = true;
  try {
    await api(`/api/documents/${encodeURIComponent(doc.id)}`, { method: "DELETE" });
    $("#delete-dialog").close();
    state.deleting = null;
    await refreshDocuments();
    if (state.currentSources.some(s => s.document_id === doc.id)) { state.currentSources = state.currentSources.filter(s => s.document_id !== doc.id); renderEvidence(state.currentSources); }
    toast("文档和检索片段已删除。历史回答保留当时快照，请重新提问。" );
  } catch (error) { if (!ignoreError(error)) toast(error.message, true); }
  finally { $("#confirm-delete").disabled = false; }
}
function roleHeader(label, avatarText, modeLabel, status) {
  const header = element("div", "message-role"); header.append(element("span", "avatar", avatarText), document.createTextNode(label));
  if (modeLabel) header.append(element("span", `answer-label${status === "insufficient" ? " insufficient" : ""}`, modeLabel));
  return header;
}
function renderCitedText(text, sources) {
  const container = element("div", "answer-text");
  const tokens = text.split(/(\[\d+\])/g);
  tokens.forEach(token => {
    const match = /^\[(\d+)\]$/.exec(token);
    const n = match && Number(match[1]);
    if (n && sources[n - 1]) { const citation = button(String(n), "citation", () => openDocument(sources[n - 1].document_id, sources[n - 1].id)); citation.setAttribute("aria-label", `查看引用 ${n}：${sources[n - 1].filename}`); container.append(citation); }
    else container.append(document.createTextNode(token));
  });
  return container;
}
function renderAnswer(answer) {
  const node = element("article", "message assistant");
  const modeLabel = answer.mode === "llm" ? "依据资料生成" : "原文摘录";
  const statusLabel = answer.status === "insufficient" ? `${modeLabel} · 资料不足` : answer.status === "conflict" ? `${modeLabel} · 需核对冲突` : modeLabel;
  node.append(roleHeader("知序", "知", statusLabel, answer.status));
  if (answer.generation_error) {
    const notice = element("div", "generation-notice");
    notice.append(element("strong", "", "生成未完成，已切换为原文摘录"), element("p", "", answer.generation_error));
    node.append(notice);
  }
  node.append(renderCitedText(answer.answer, answer.sources));
  if (answer.warning) node.append(element("p", "answer-warning", answer.warning));
  const meta = element("div", "message-meta");
  meta.append(element("span", "", `${answer.sources.length} 条来源`), element("span", "", `${Math.round(answer.metrics.total_ms)} ms`));
  meta.append(button("查看依据", "text-button", () => { renderEvidence(answer.sources); if (window.innerWidth < 961) $(".evidence-panel").scrollIntoView({ behavior: "smooth", block: "nearest" }); }, "files"));
  const copy = button("", "icon-button", () => copyAnswer(answer), "copy"); copy.setAttribute("aria-label", "复制回答与来源");
  const download = button("", "icon-button", () => downloadAnswer(answer), "download"); download.setAttribute("aria-label", "导出 Markdown 回答"); meta.append(copy, download); node.append(meta);
  if (answer.trace && answer.trace.length) {
    const details = element("details", "trace"); const summary = element("summary", "", "查看检索过程"); const steps = element("ol");
    answer.trace.forEach(step => { const li = element("li"); li.append(element("strong", "", step.label), element("span", "", step.detail)); steps.append(li); }); details.append(summary, steps); node.append(details);
  }
  $("#conversation").append(node); renderEvidence(answer.sources); return node;
}
function renderEvidence(sources, hasAsked = true) {
  state.currentSources = sources;
  $("#evidence-count").textContent = sources.length;
  const panel = $("#evidence-content"); panel.replaceChildren();
  if (!sources.length) { const empty = element("div", "evidence-empty"); empty.append(element("h3", "", hasAsked ? "本次没有可用的相关依据" : "提问后展示来源"), element("p", "", hasAsked ? "试着补充资料，或把问题描述得更具体。" : "输入问题后，相关原文与位置会显示在这里。")); panel.append(empty); return; }
  sources.forEach((source, index) => {
    const card = button("", "source-card", () => openDocument(source.document_id, source.id));
    const top = element("div", "source-top"); const label = element("div"); label.append(element("span", "source-title", title(source.filename)), element("span", "source-location", source.location)); top.append(element("span", "source-number", index + 1), label);
    const bottom = element("div", "source-bottom"); bottom.append(element("span", "", "原文片段"), element("span", "", "查看全文 ↗"));
    card.append(top, element("p", "source-snippet", source.text), bottom); panel.append(card);
  });
}
async function ask(event) {
  event?.preventDefault();
  if (!permissions().canRead) return denied("请先登录并选择已授权的工作空间。");
  if (state.busy) return;
  const context = state.contextVersion;
  const question = $("#question").value.trim();
  if (!question) { $("#question").focus(); return; }
  const requestedMode = $("#mode").value;
  const requestedStrategy = $("#strategy").value;
  state.busy = true; $("#send-button").disabled = true; $("#new-chat").disabled = true;
  $("#welcome")?.remove();
  const user = element("article", "message user"); user.append(roleHeader("你", "你"), element("p", "message-question", question)); $("#conversation").append(user);
  $("#question").value = "";
  const loading = element("div", "loading-line"); loading.append(element("span", "spinner"), element("span", "", requestedMode === "llm" ? "正在检索并根据资料生成回答…" : "正在查找相关依据…")); $("#conversation").append(loading); scrollChat();
  try {
    const result = await api("/api/ask", { method: "POST", body: JSON.stringify({ question, mode: requestedMode, strategy: requestedStrategy, document_ids: [...state.selectedDocuments], top_k: 5 }) });
    loading.remove(); state.answers.push(result); renderAnswer(result);
  } catch (error) {
    if (ignoreError(error) || context !== state.contextVersion) return;
    loading.remove(); const problem = element("div", "message"); const message = element("div", "error-message", error.message); problem.append(message, button("重试这个问题", "text-button", () => { $("#question").value = question; ask(); })); $("#conversation").append(problem);
    if (!$("#question").value) $("#question").value = question;
  } finally { if (context === state.contextVersion) { state.busy = false; applyPermissions(); scrollChat(); } }
}
function scrollChat() { const node = $("#conversation"); node.scrollTop = node.scrollHeight; }
function markdown(answer) {
  return `# ${answer.question}\n\n模式：${answer.mode === "llm" ? "模型生成" : "本地原文摘录"} · 状态：${answer.status}\n\n${answer.generation_error ? `生成失败，已显示原文：${answer.generation_error}\n\n` : ""}${answer.answer}\n\n## 来源\n\n${answer.sources.map((source, index) => `### [${index + 1}] ${source.filename} · ${source.location}\n\n${source.text}\n`).join("\n")}\n---\n耗时：${answer.metrics.total_ms} ms。${answer.warning || ""}\n此文件为当时问答快照，文档更新后请重新核对。\n`;
}
async function copyAnswer(answer) { try { await navigator.clipboard.writeText(markdown(answer)); toast("回答与原文来源已复制。" ); } catch { toast("浏览器未允许复制，请使用 Markdown 导出。", true); } }
function downloadText(text, filename) { const blob = new Blob([text], { type: "text/markdown;charset=utf-8" }); const url = URL.createObjectURL(blob); const a = element("a"); a.href = url; a.download = filename; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function downloadAnswer(answer) { downloadText(markdown(answer), `知序-问答-${answer.id.slice(0, 8)}.md`); }
let drawerRequest = 0;
function openDrawer(eyebrow) {
  drawerRequest++;
  clearSecrets();
  if ($("#drawer").hidden || !$("#drawer").contains(document.activeElement)) state.drawerFocus = document.activeElement;
  $("#drawer-eyebrow").textContent = eyebrow;
  $("#drawer-content").replaceChildren(); $("#drawer").hidden = false; $("#drawer-overlay").hidden = false; document.body.style.overflow = "hidden"; $("#drawer-close").focus();
}
function closeDrawer() { drawerRequest++; clearSecrets(); $("#drawer").hidden = true; $("#drawer-overlay").hidden = true; document.body.style.overflow = ""; if (state.drawerFocus?.isConnected) state.drawerFocus.focus(); }
async function openDocument(id, chunkId) {
  openDrawer("SOURCE DOCUMENT / 原文核对");
  const request = drawerRequest;
  $("#drawer-content").append(element("p", "muted", "正在读取资料…"));
  try {
    const doc = await api(`/api/documents/${encodeURIComponent(id)}`);
    if (request !== drawerRequest || $("#drawer").hidden) return;
    const content = $("#drawer-content"); content.replaceChildren(element("h2", "", title(doc.filename)), element("p", "subtitle", `${doc.chunk_count} 个知识片段 · ${formatBytes(doc.byte_size)} · 来源位置可逐段核对`));
    let highlight;
    doc.chunks.forEach(chunk => { const node = element("section", `original-chunk${chunk.id === chunkId ? " highlight" : ""}`); node.append(element("h3", "", chunk.location), element("p", "", chunk.text)); content.append(node); if (chunk.id === chunkId) highlight = node; });
    if (highlight) highlight.scrollIntoView({ block: "center" }); else $("#drawer").scrollTop = 0;
  } catch (error) { if (request === drawerRequest) $("#drawer-content").replaceChildren(element("p", "error-message", error.message)); }
}
function help() {
  openDrawer("QUICK START / 使用帮助");
  const content = $("#drawer-content");
  content.append(element("h2", "", "三步，让资料成为答案"));
  const blocks = [
    ["01 / 导入资料", "上传可提取文字的 PDF、Word DOCX、Markdown 或 TXT，每个文件最多 10 MB。也可点击‘体验示例资料’，导入一组明确标识的虚构内容。DOCX 提取正文段落与表格，不提供页码或 OCR。"],
    ["02 / 提问并看来源", "在问答工作台输入问题。点击答案中的引用编号，查看对应的原文片段和来源位置。可以限定文档范围。"],
    ["03 / 看效果，也看失败", "在评测实验室对固定问题运行检索比较，在面试练习中学习数据流、引用、拒答和工程取舍。指标都来自实际报告。"],
    ["快捷操作", "Ctrl + Enter 发送问题；/ 聚焦提问框；Esc 关闭抽屉。答案旁的复制和导出按钮会连同来源一起保存。会话只留在当前页面内存，刷新后清空。"],
    ["资料与模型的信任边界", state.auth?.enabled ? "当前资料按工作空间和成员权限访问。选择模型生成时，问题和检索片段会发送到管理员配置的服务。资料中的指令不授予工具权限，引用仍需人工核对；账号与空间权限不等于自动事实验证。" : "默认检索与原文摘录在本机完成。选择模型生成时，问题和检索片段会发送到已配置服务；外部服务可能收费。资料中的指令不授予工具权限，引用也不保证结论正确。当前为本机个人模式，不含 OCR 或生产部署方案。"]
  ];
  blocks.forEach(([heading, text]) => { const block = element("section", "help-block"); block.append(element("h3", "", heading), element("p", "", text)); content.append(block); });
  const settingsButton = button("打开模型配置", "button secondary", openSettings, "sliders"); settingsButton.disabled = !permissions().canConfigure; content.append(settingsButton);
}
async function openSettings() {
  if (!permissions().canConfigure) return denied("仅系统管理员可管理模型配置。");
  openDrawer("MODEL SETTINGS / 模型配置");
  const request = drawerRequest;
  $("#drawer-content").append(element("p", "muted", "正在读取已保存配置…"));
  try {
    const settings = await api("/api/settings/model");
    if (request !== drawerRequest || $("#drawer").hidden) return;
    renderModelSettings(settings, request);
  } catch (error) {
    if (request !== drawerRequest || $("#drawer").hidden) return;
    $("#drawer-content").replaceChildren(element("h2", "", "暂时无法读取模型配置"), element("p", "error-message", error.message), button("重新读取", "button secondary", openSettings));
  }
}
function adminField(parent, label, id, type = "text") {
  const wrapper = element("label", "settings-field"); wrapper.htmlFor = id;
  const input = element("input"); input.id = id; input.type = type; input.required = true; input.autocomplete = type === "password" ? "new-password" : "off";
  wrapper.append(element("span", "", label), input); parent.append(wrapper); return input;
}
function adminForm(parent, heading, id, submitLabel) {
  const section = element("section", "admin-section"); section.append(element("h3", "", heading));
  const form = element("form", "settings-form"); form.id = id; form.autocomplete = "off";
  const fields = element("fieldset"); const status = element("p", "settings-status"); status.setAttribute("role", "status");
  const submit = button(submitLabel, "button primary"); submit.type = "submit";
  form.append(fields, submit, status); section.append(form); parent.append(section);
  return { form, fields, status, submit };
}
function adminTable(parent, headings, rows) {
  const wrapper = element("div", "table-scroll admin-table"); const table = element("table", "document-table");
  const head = element("thead"); const header = element("tr"); headings.forEach(text => header.append(element("th", "", text))); head.append(header);
  const body = element("tbody");
  rows.forEach(values => { const row = element("tr"); values.forEach(value => { const cell = element("td"); if (value instanceof Node) cell.append(value); else cell.textContent = value ?? "—"; row.append(cell); }); body.append(row); });
  table.append(head, body); wrapper.append(table); parent.append(wrapper);
}
function bindAdminForm(parts, action) {
  parts.form.addEventListener("submit", async event => {
    event.preventDefault(); if (!permissions().canManage || parts.submit.disabled) return;
    const request = drawerRequest; parts.fields.disabled = true; parts.submit.disabled = true; parts.status.textContent = "正在保存…";
    try {
      const pending = action(); clearSecrets(); await pending;
      await refreshIdentity(); await loadWorkspace();
      if (permissions().canManage) await openAdmin();
      toast("管理操作已保存。");
    } catch (error) { if (!ignoreError(error) && request === drawerRequest) { parts.status.textContent = error.message; parts.status.classList.add("error"); } }
    finally { clearSecrets(); if (parts.form.isConnected) { parts.fields.disabled = false; parts.submit.disabled = false; } }
  });
}
async function openAdmin() {
  if (!permissions().canManage) return denied("仅系统管理员可打开管理界面。");
  openDrawer("ADMINISTRATION / 系统管理"); const request = drawerRequest;
  $("#drawer-content").append(element("p", "muted", "正在读取账号与审计…"));
  try {
    const [userData, auditData] = await Promise.all([api("/api/admin/users"), api("/api/admin/audit?limit=50")]);
    if (request !== drawerRequest || !permissions().canManage) return;
    const users = userData.users || []; const content = $("#drawer-content");
    content.replaceChildren(element("h2", "", "账号、空间与审计"), element("p", "subtitle", "系统管理员可管理所有账号和空间。密码只用于本次提交，不会回显。"));
    const createUser = adminForm(content, "创建账号", "admin-create-user", "创建账号");
    const username = adminField(createUser.fields, "用户名", "admin-username");
    const password = adminField(createUser.fields, "初始密码 · 至少 12 个字符", "admin-password", "password"); password.minLength = 12; password.placeholder = "由管理员设置，不提供默认密码";
    const adminLabel = element("label", "settings-checkbox"); const adminFlag = element("input"); adminFlag.id = "admin-is-admin"; adminFlag.type = "checkbox";
    adminLabel.append(adminFlag, document.createTextNode("授予系统管理员身份（可管理所有账号和空间）")); createUser.fields.append(adminLabel);
    bindAdminForm(createUser, () => api("/api/admin/users", { method: "POST", body: JSON.stringify({ username: username.value.trim(), password: password.value, is_admin: adminFlag.checked }) }));

    const accountSection = element("section", "admin-section"); accountSection.append(element("h3", "", "已有账号")); content.append(accountSection);
    adminTable(accountSection, ["用户名", "身份", "状态", "操作"], users.map(user => {
      const action = button(user.active ? "停用" : "启用", "button secondary", async () => {
        if (!permissions().canManage || action.disabled) return;
        action.disabled = true;
        try { await api(`/api/admin/users/${encodeURIComponent(user.id)}/active`, { method: "PUT", body: JSON.stringify({ active: !user.active }) }); await refreshIdentity(); if (permissions().canManage) await openAdmin(); }
        catch (error) { if (!ignoreError(error)) toast(error.message, true); }
        finally { clearSecrets(); action.disabled = false; }
      });
      return [user.username, user.is_admin ? "系统管理员" : "普通账号", user.active ? "启用" : "停用", action];
    }));

    const createWorkspace = adminForm(content, "创建工作空间", "admin-create-workspace", "创建空间");
    const spaceName = adminField(createWorkspace.fields, "空间名称", "admin-workspace-name");
    bindAdminForm(createWorkspace, () => api("/api/admin/workspaces", { method: "POST", body: JSON.stringify({ name: spaceName.value.trim() }) }));

    const membership = adminForm(content, "分配或撤销空间访问", "admin-membership", "保存授权");
    function selection(label, id, choices) {
      const wrapper = element("label", "settings-field"); wrapper.htmlFor = id;
      const select = element("select"); select.id = id; select.required = true;
      choices.forEach(([value, text]) => { const option = element("option", "", text); option.value = String(value); select.append(option); });
      wrapper.append(element("span", "", label), select); membership.fields.append(wrapper); return select;
    }
    const workspace = selection("工作空间", "admin-member-workspace", state.auth.workspaces.map(item => [item.id, item.name])); workspace.value = state.workspaceId || "";
    const member = selection("账号", "admin-member-user", users.map(user => [user.id, `${user.username}${user.active ? "" : "（停用）"}`]));
    const role = selection("空间角色", "admin-member-role", [["viewer", "只读：查看与问答"], ["editor", "编辑：上传与删除资料"], ["admin", "空间管理员：管理空间资料"]]);
    membership.fields.append(element("p", "settings-hint", "空间角色不授予系统管理、模型配置或运行评测的权限。撤销访问会移除该账号的空间授权。"));
    membership.submit.disabled = !state.auth.workspaces.length || !users.length;
    bindAdminForm(membership, () => api(`/api/admin/workspaces/${encodeURIComponent(workspace.value)}/members`, { method: "PUT", body: JSON.stringify({ user_id: member.value, role: role.value }) }));
    const revoke = button("撤销该账号的空间访问", "button secondary", async () => {
      if (!permissions().canManage || !workspace.value || !member.value || revoke.disabled) return;
      revoke.disabled = true;
      try { await api(`/api/admin/workspaces/${encodeURIComponent(workspace.value)}/members/${encodeURIComponent(member.value)}`, { method: "DELETE" }); await refreshIdentity(); await loadWorkspace(); if (permissions().canManage) await openAdmin(); }
      catch (error) { if (!ignoreError(error) && request === drawerRequest) { membership.status.textContent = error.message; membership.status.classList.add("error"); } }
      finally { clearSecrets(); revoke.disabled = false; }
    }); revoke.id = "admin-revoke-membership"; revoke.disabled = membership.submit.disabled; membership.form.append(revoke);

    const audit = element("section", "admin-section"); const heading = element("div", "admin-section-heading"); heading.append(element("h3", "", "最近 50 条审计事件"), button("刷新管理信息", "text-button", openAdmin)); audit.append(heading); content.append(audit);
    const events = auditData.events || [];
    if (!events.length) audit.append(element("p", "muted", "暂无审计事件。"));
    else {
      const userNames = new Map(users.map(user => [user.id, user.username]));
      const spaceNames = new Map(state.auth.workspaces.map(space => [space.id, space.name]));
      const identifier = (id, label) => { const node = element("span", "", label || (id ? id.slice(0, 12) : "—")); if (id) node.title = id; return node; };
      adminTable(audit, ["时间", "操作人", "操作", "空间", "对象", "结果", "请求 ID"], events.map(item => [item.created_at ? formatDate(String(item.created_at)) : "—", identifier(item.actor_id, userNames.get(item.actor_id)), item.action, identifier(item.workspace_id, spaceNames.get(item.workspace_id)), identifier(item.target_id), item.outcome, identifier(item.request_id)]));
    }
  } catch (error) { if (!ignoreError(error) && request === drawerRequest) $("#drawer-content").replaceChildren(element("h2", "", "无法读取管理信息"), element("p", "error-message", error.message), button("重试", "button secondary", openAdmin)); }
}
function openPasswordChange() {
  if (!permissions().signedIn) return;
  openDrawer("ACCOUNT SECURITY / 修改密码");
  const content = $("#drawer-content"); content.append(element("h2", "", "修改登录密码"), element("p", "subtitle", "修改成功后，当前账号的全部会话将失效，需要重新登录。"));
  const parts = adminForm(content, "验证当前密码并设置新密码", "change-password-form", "更新密码并重新登录");
  const current = adminField(parts.fields, "当前密码", "current-password", "password"); current.autocomplete = "current-password";
  const next = adminField(parts.fields, "新密码 · 至少 12 个字符", "new-password", "password"); next.minLength = 12;
  parts.form.addEventListener("submit", async event => {
    event.preventDefault(); if (!permissions().signedIn || parts.submit.disabled) return;
    const body = JSON.stringify({ current_password: current.value, new_password: next.value });
    clearSecrets(); parts.fields.disabled = true; parts.submit.disabled = true; parts.status.textContent = "正在更新密码…";
    try { await api("/api/auth/password", { method: "POST", body }); state.identityRequest++; applyAuthStatus({ enabled: true, authenticated: false }); $("#login-error").textContent = "密码已更新，请重新登录。"; }
    catch (error) { if (!ignoreError(error)) { parts.status.textContent = error.message; parts.status.classList.add("error"); } }
    finally { clearSecrets(); parts.fields.disabled = false; parts.submit.disabled = false; }
  });
}
function renderModelSettings(settings, request, savedMessage = "") {
  const content = $("#drawer-content");
  content.replaceChildren(element("h2", "", "连接你自己的模型服务"), element("p", "subtitle", "不接模型也能检索和摘录资料。保存连接后，在问答框选择“模型生成”。"));
  const sources = { default: "默认值", file: "本机保存的配置", environment: "环境变量", injected: "启动注入配置" };
  const summary = element("div", "settings-summary");
  summary.append(element("span", `soft-badge${settings.enabled ? " settings-ready" : ""}`, settings.enabled ? "已配置" : "尚未启用"), element("span", "", settings.is_local ? "本机模型服务" : "外部兼容服务"), element("span", "", `来源：${sources[settings.configured_by] || settings.configured_by}`));
  content.append(summary);
  if (!settings.editable) content.append(element("p", "settings-readonly", "此配置由环境变量或启动参数管理，页面不能覆盖。请修改对应环境或启动配置后重启服务；仍可测试当前连接。"));
  const form = element("form", "settings-form"); form.id = "model-settings-form"; form.autocomplete = "off";
  const fields = element("fieldset"); fields.disabled = !settings.editable;
  function field(label, id, type, placeholder) {
    const wrapper = element("label", "settings-field"); wrapper.htmlFor = id;
    const input = element("input"); input.id = id; input.type = type; input.placeholder = placeholder; input.spellcheck = false;
    wrapper.append(element("span", "", label), input); fields.append(wrapper); return input;
  }
  const base = field("服务地址 Base URL", "model-base-url", "url", "http://127.0.0.1:11434/v1"); base.required = true; base.value = settings.base_url || "";
  const presets = element("div", "settings-presets");
  [["Ollama 本机", "http://127.0.0.1:11434/v1"], ["LM Studio 本机", "http://127.0.0.1:1234/v1"]].forEach(([label, url]) => presets.append(button(label, "settings-preset", () => { base.value = url; key.value = ""; updateDestination(); base.focus(); })));
  fields.append(presets, element("p", "settings-hint", "预设只填写地址，不探测或下载模型。模型名请按本机已部署服务填写。外部服务须使用 HTTPS。"));
  const model = field("模型名称", "model-name", "text", "例如：qwen2.5:0.5b"); model.required = true; model.value = settings.model || "";
  const key = field("API Key · 本机服务可留空", "model-api-key", "password", settings.has_api_key ? "已保存密钥；地址不变时留空可保留" : "未保存密钥；外部服务通常需要填写"); key.autocomplete = "new-password"; key.value = "";
  const keyHint = element("p", "settings-hint"); keyHint.id = "model-key-hint"; fields.append(keyHint);
  const clearLabel = element("label", "settings-checkbox"); const clear = element("input"); clear.id = "model-clear-api-key"; clear.type = "checkbox"; clear.disabled = !settings.has_api_key;
  clearLabel.append(clear, document.createTextNode("清除已保存的 API Key")); fields.append(clearLabel);
  const destination = element("p", "settings-transmission"); destination.setAttribute("aria-live", "polite"); fields.append(destination);
  function updateDestination() {
    const changed = base.value.trim().replace(/\/+$/, "") !== (settings.base_url || "").replace(/\/+$/, "");
    keyHint.textContent = settings.has_api_key ? changed ? "地址已变更：旧密钥不会转移到新服务。需要鉴权时请重新填写。" : "留空仅在服务地址不变时保留已有密钥。密钥不回显，也不保存在浏览器本地存储。" : "密钥不会回显，也不保存在浏览器本地存储。本机服务支持不填密钥。";
    try {
      const url = new URL(base.value.trim());
      destination.textContent = `选择模型生成后，问题和检索片段将发送到 ${url.origin}。保存配置本身不会发送你的资料。`;
    } catch { destination.textContent = "请填写完整的服务地址。只有选择模型生成时，才会发送问题和检索片段。"; }
  }
  base.addEventListener("input", () => { key.value = ""; updateDestination(); });
  clear.addEventListener("change", () => { if (clear.checked) key.value = ""; key.disabled = clear.checked; });
  updateDestination();
  const actions = element("div", "settings-actions");
  const save = button("保存配置", "button primary"); save.type = "submit"; save.id = "save-model-settings"; save.disabled = !settings.editable;
  const test = button("测试已保存连接", "button secondary"); test.id = "test-model-settings"; test.disabled = !settings.enabled;
  actions.append(save, test);
  const status = element("p", "settings-status", savedMessage); status.id = "model-settings-status"; status.setAttribute("role", "status");
  form.append(fields, actions, status, element("p", "settings-hint", "连接测试仅发送固定合成文本，不包含你的文档。测试使用已保存配置；外部服务可能产生服务商费用。"));
  content.append(form);
  const boundary = element("section", "help-block"); boundary.append(element("h3", "", "你掌控资料发送到哪里"), element("p", "", "默认本地摘录不调用生成服务。使用外部模型前，请确认资料获准发送；密钥只保存在服务端配置，不会回传到页面。原文引用仍需人工核对。")); content.append(boundary);
  function busy(value) { fields.disabled = value || !settings.editable; save.disabled = value || !settings.editable; test.disabled = value || !settings.enabled; }
  function report(message, error = false) { if (request === drawerRequest && form.isConnected) { status.textContent = message; status.className = `settings-status${error ? " error" : ""}`; } }
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (!settings.editable || save.disabled) return;
    const body = { base_url: base.value.trim(), model: model.value.trim(), api_key: clear.checked ? null : key.value.trim() || null, clear_api_key: clear.checked };
    key.value = ""; busy(true); report("正在保存模型配置…"); let saved = false;
    try {
      const result = await api("/api/settings/model", { method: "PUT", body: JSON.stringify(body) }); saved = true;
      if (request === drawerRequest && !$("#drawer").hidden) renderModelSettings(result, request, "配置已保存。可测试已保存连接，再到问答框选择模型生成。");
      await refreshDocuments(); toast("模型配置已保存，回答模式状态已更新。");
    } catch (error) { const message = saved ? `配置已保存，但状态刷新失败：${error.message}` : error.message; report(message, true); toast(message, true); }
    finally { key.value = ""; busy(false); }
  });
  test.addEventListener("click", async () => {
    if (test.disabled) return;
    busy(true); report("正在用固定合成文本测试已保存连接…");
    try {
      const result = await api("/api/settings/model/test", { method: "POST" });
      const message = `${result.message || "连接测试通过"} · ${result.model} · ${Math.round(result.latency_ms)} ms`;
      report(message); toast(message);
    } catch (error) { report(error.message, true); toast(error.message, true); }
    finally { busy(false); }
  });
}
async function loadEvaluation() {
  if (!permissions().canRead) { $("#evaluation-content").replaceChildren(element("div", "empty-state", "获得工作空间授权后可查看报告。")); return; }
  try { state.evaluation = await api("/api/evaluation"); renderEvaluation(); }
  catch (error) { if (!ignoreError(error)) $("#evaluation-content").replaceChildren(element("div", "error-message", error.message)); }
}
const percent = value => value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
function renderEvaluation() {
  const content = $("#evaluation-content"); content.replaceChildren();
  if (!state.evaluation?.available) { content.append(element("div", "empty-state", state.evaluation?.message || "还没有评测报告。点击‘运行评测’生成真实结果。")); return; }
  const report = state.evaluation.report; const split = state.split; const metric = report.strategies.hybrid[split];
  const grid = element("div", "metric-grid");
  [ ["来源命中 Hit@5", percent(metric.hit_at_5), `${split === "holdout" ? "留出" : "开发"}集 · 至少命中一个预期来源`], ["完整来源@5", percent(metric.all_sources_at_5), "所有预期资料均出现在前五条"], ["无依据问题拒答率", percent(metric.refusal_rate), `${metric.unanswerable_count} 道无依据问题 · 按状态统计`], ["检索 P95 延迟", `${metric.p95_ms.toFixed(1)} ms`, "本机小资料集 · 不含生成模型调用"] ].forEach(([label, value, note]) => { const card = element("div", "metric-card"); card.append(element("small", "", label), element("div", "metric-value", value), element("p", "", note)); grid.append(card); }); content.append(grid);
  const comparison = element("section", "section-card"); const header = element("div", "section-card-header"); const heading = element("div"); heading.append(element("h2", "", "同一资料集，三种检索策略"), element("p", "", `${report.case_count} 道固定题目 · ${report.document_count} 份模拟资料 · 开发 ${report.splits.dev} / 留出 ${report.splits.holdout}`)); const tabs = element("div", "split-tabs");
  [["dev", "开发集"], ["holdout", "留出集"]].forEach(([key, label]) => { tabs.append(button(label, state.split === key ? "active" : "", () => { state.split = key; renderEvaluation(); })); }); header.append(heading, tabs); comparison.append(header);
  const scroll = element("div", "table-scroll"); const table = element("table", "document-table evaluation-table"); const thead = element("thead"); const tr = element("tr"); ["检索策略", "Hit@5", "Recall@5", "MRR", "完整来源@5", "无依据拒答", "误拒答", "P95"].forEach(text => tr.append(element("th", "", text))); thead.append(tr); table.append(thead); const tbody = element("tbody");
  [["bm25", "BM25"], ["tfidf", "TF-IDF 稀疏向量"], ["hybrid", "融合检索 · RRF"]].forEach(([key, label]) => { const m = report.strategies[key][split]; const row = element("tr", key === "hybrid" ? "featured" : ""); [label, percent(m.hit_at_5), percent(m.recall_at_5), m.mrr.toFixed(3), percent(m.all_sources_at_5), percent(m.refusal_rate), percent(m.false_refusal_rate), `${m.p95_ms.toFixed(1)} ms`].forEach(text => row.append(element("td", "", text))); tbody.append(row); }); table.append(tbody); scroll.append(table); comparison.append(scroll, element("p", "eval-note", "TF-IDF 和 BM25 主要依赖字面特征，融合不保证更好。Hit@5 衡量至少命中一个文件；Recall@5 衡量预期文件召回比例。文件命中不证明答案条件完整。同域合成问题不代表真实企业效果。")); content.append(comparison);
  if (state.evaluation.semantic_confirmation) {
    const confirmation = state.evaluation.semantic_confirmation;
    const card = element("section", "section-card"); const sh = element("div", "section-card-header");
    const st = element("div"); st.append(element("h2", "", "可选语义检索 · 新冻结确认题"), element("p", "", `${confirmation.case_count} 道题 · 与上方 64 题不同，不能跨题集比较百分比`)); sh.append(st, element("span", "outline-tag", "本机 BGE · 512 维")); card.append(sh);
    const wrapper = element("div", "table-scroll"); const comparisonTable = element("table", "document-table evaluation-table");
    const head = element("thead"); const headRow = element("tr"); ["同题策略", "Hit@5", "Recall@5", "无依据拒答", "有依据误拒答", "P95"].forEach(text => headRow.append(element("th", "", text))); head.append(headRow); comparisonTable.append(head);
    const body = element("tbody"); [["hybrid", "字面融合"], ["semantic", "BGE 语义检索"]].forEach(([key, label]) => { const m = confirmation.strategies[key].holdout; const row = element("tr"); [label, percent(m.hit_at_5), percent(m.recall_at_5), percent(m.refusal_rate), percent(m.false_refusal_rate), `${m.p95_ms.toFixed(1)} ms`].forEach(text => row.append(element("td", "", text))); body.append(row); }); comparisonTable.append(body); wrapper.append(comparisonTable); card.append(wrapper, element("p", "eval-note", "固定余弦门限 0.65 未在这组题上调参。语义检索在本组小样本中更保守，同时漏答更多，并无整体优于字面融合的证据。两种检索均保留供选择；默认仍为字面融合。模型只负责匹配原文，不生成答案。")); content.append(card);
  }
  const failures = report.results.filter(item => item.strategy === "hybrid" && item.split === split && (!item.correct_retrieval || !item.correct_refusal));
  const failureCard = element("section", "section-card"); const fh = element("div", "section-card-header"); fh.append(element("h2", "", `需要复核的问题 · ${failures.length}`), element("span", "outline-tag", "保留失败，不隐藏边界")); failureCard.append(fh);
  const list = element("div", "failure-list");
  if (!failures.length) list.append(element("p", "eval-note", "按当前自动指标未发现失败；这不等于人工核验的答案全对。请继续用真实问题测试。"));
  failures.forEach(item => { const details = element("details", "failure-item"); details.append(element("summary", "", `${item.id} · ${item.question}`), element("p", "", `参考：${item.reference_answer}`), element("p", "", `预期来源：${item.expected_sources.join("、") || "应拒答"}`), element("p", "", `实际来源：${item.retrieved_sources.join("、") || "无"}；状态：${item.status}`)); list.append(details); }); failureCard.append(list); content.append(failureCard);
  const limitations = element("section", "section-card"); const lh = element("div", "section-card-header"); lh.append(element("h2", "", "如何正确理解这份报告")); limitations.append(lh, element("p", "eval-note", report.limitations.join("\n"))); content.append(limitations);
  content.append(element("p", "report-timestamp", `生成时间：${formatDate(report.generated_at)} · 题集版本 ${report.dataset_version} · 实际模型调用：0`));
}
async function runEvaluation() {
  if (!permissions().canEvaluate) return denied("仅系统管理员可运行评测。");
  const node = $("#run-evaluation"); node.disabled = true; node.replaceChildren(element("span", "spinner"), element("span", "", "正在逐题评测…"));
  try { await api("/api/evaluation/run", { method: "POST" }); await loadEvaluation(); toast("64 题基线评测已更新。语义确认报告保持冻结结果。" ); }
  catch (error) { if (!ignoreError(error)) toast(error.message, true); }
  finally { node.disabled = !permissions().canEvaluate; node.replaceChildren(icon("chart"), element("span", "", "运行评测")); }
}
async function loadLessons() { try { const data = await api("/api/lessons"); state.lessons = data.lessons; renderLessons(); } catch (error) { if (!ignoreError(error)) toast(error.message, true); } }
function renderLessons() {
  const list = $("#lesson-list"); list.replaceChildren();
  state.lessons.forEach((lesson, index) => { const node = button("", `lesson-item${state.lesson === index ? " active" : ""}`, () => { state.lesson = index; renderLessons(); }); const words = element("span"); words.append(element("strong", "", lesson.title), element("small", "", lesson.topic)); node.append(element("span", "lesson-number", lesson.number), words); list.append(node); });
  const lesson = state.lessons[state.lesson]; if (!lesson) return;
  const detail = $("#lesson-detail"); detail.replaceChildren(element("span", "lesson-topic", `LESSON ${lesson.number} / ${lesson.topic}`), element("h2", "", lesson.title));
  const question = element("section", "lesson-section"); question.append(element("h3", "", "面试官可能这样问"), element("p", "lesson-question", lesson.question)); const answer = element("details", "lesson-answer"); answer.append(element("summary", "", "先想一想，再展开参考回答"), element("p", "", lesson.answer)); question.append(answer); detail.append(question);
  const pitfall = element("section", "lesson-section"); pitfall.append(element("h3", "", "回答时注意"), element("p", "", lesson.pitfall)); detail.append(pitfall);
  const exercise = element("section", "lesson-exercise"); exercise.append(element("h3", "", "动手练习 / 用项目验证一次"), element("p", "", lesson.exercise)); detail.append(exercise, element("p", "lesson-code", `对应实现：${lesson.file}`));
}

$$(".nav-item[data-view]").forEach(node => node.addEventListener("click", () => view(node.dataset.view)));
$("#ask-form").addEventListener("submit", ask);
$("#question").addEventListener("keydown", event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); ask(); } });
const initialWelcome = $("#welcome").cloneNode(true);
bindWelcome($("#welcome"));
renderWelcome();
$("#new-chat").addEventListener("click", () => { if (state.busy) return; state.answers = []; const welcome = initialWelcome.cloneNode(true); $("#conversation").replaceChildren(welcome); bindWelcome(welcome); renderWelcome(); $("#question").value = ""; renderEvidence([], false); $("#question").focus(); });
$("#scope-button").addEventListener("click", event => { event.stopPropagation(); $("#scope-popover").hidden = !$("#scope-popover").hidden; });
document.addEventListener("click", event => { if (!$("#scope-popover").contains(event.target) && !$("#scope-button").contains(event.target)) $("#scope-popover").hidden = true; });
$("#mode").addEventListener("change", () => { $("#active-mode-label").textContent = $("#mode").value === "llm" ? "模型生成" : "本地摘录"; });
$("#dropzone").addEventListener("click", () => { if (permissions().canWrite) $("#file-input").click(); });
$("#dropzone").addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); if (permissions().canWrite) $("#file-input").click(); } });
$("#file-input").addEventListener("change", event => uploadFiles(event.target.files));
["dragenter", "dragover"].forEach(name => $("#dropzone").addEventListener(name, event => { event.preventDefault(); $("#dropzone").classList.add("dragover"); }));
["dragleave", "drop"].forEach(name => $("#dropzone").addEventListener(name, event => { event.preventDefault(); $("#dropzone").classList.remove("dragover"); }));
$("#dropzone").addEventListener("drop", event => uploadFiles(event.dataTransfer.files));
$("#document-search").addEventListener("input", renderDocuments);
$("#cancel-delete").addEventListener("click", () => { $("#delete-dialog").close(); state.deleting = null; });
$("#confirm-delete").addEventListener("click", deleteConfirmed);
$("#restore-demo").addEventListener("click", restoreDemo);
$("#drawer-close").addEventListener("click", closeDrawer); $("#drawer-overlay").addEventListener("click", closeDrawer);
$("#help-button").addEventListener("click", help); $("#settings-button").addEventListener("click", openSettings); $("#topbar-settings-button").addEventListener("click", openSettings);
$("#run-evaluation").addEventListener("click", runEvaluation);
$("#login-form").addEventListener("submit", login);
$("#login-retry").addEventListener("click", bootstrap);
$("#workspace-select").addEventListener("change", changeWorkspace);
$("#logout-button").addEventListener("click", logout);
$("#admin-button").addEventListener("click", openAdmin);
$("#password-button").addEventListener("click", openPasswordChange);
window.addEventListener("focus", () => {
  if (!state.auth?.enabled || !state.auth.authenticated) return;
  refreshIdentity().then(changed => changed ? loadWorkspace() : undefined).catch(error => { if (!ignoreError(error)) toast(error.message, true); });
});
document.addEventListener("keydown", event => {
  if (!$("#auth-overlay").hidden) {
    if (event.key === "Tab") {
      const nodes = $$("input,button", $("#auth-overlay")).filter(node => !node.disabled && node.getClientRects().length);
      const first = nodes[0]; const last = nodes[nodes.length - 1];
      if (!first) { event.preventDefault(); $("#auth-overlay").focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    return;
  }
  if (event.key === "Escape") { closeDrawer(); $("#scope-popover").hidden = true; }
  if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) && $("#drawer").hidden && !$("#delete-dialog").open) { event.preventDefault(); view("chat"); $("#question").focus(); }
  if (event.key === "Tab" && !$("#drawer").hidden) { const focusable = $$("button,a[href],input,select,textarea,[tabindex]", $("#drawer")).filter(node => !node.matches(":disabled") && node.tabIndex >= 0 && node.getClientRects().length); const first = focusable[0]; const last = focusable[focusable.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
});
applyPermissions();
bootstrap();
