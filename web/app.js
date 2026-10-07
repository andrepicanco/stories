import { createEditor } from "/static/editor.js";

const $ = (sel) => document.querySelector(sel);

const DEFAULT_TITLE = "Nova História";

const STATUS_LABELS = {
  azure_openai: "Azure OpenAI",
  azure_devops_rest: "Azure DevOps API",
  azure_devops_mcp: "Azure DevOps MCP",
  notion_mcp: "Notion MCP",
};

const app = {
  settings: null, story: null, saveTimer: null,
  chat: [],              // conversa com o agente: [{role: "assistant" | "user", content}]
  titleEdited: false,    // o agente só preenche o título se o usuário ainda não mexeu nele
  memoryNote: "",
  running: false,
  // Feedback humano sobre a última resposta do agente: undefined = ainda não houve resposta;
  // null = aguardando avaliação; "good" | "neutral" | "bad" = avaliada.
  rating: undefined,
};
const editors = {};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Erro ${res.status}`);
  }
  return res.json();
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/* ---------- Tema ---------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#toggle-theme").textContent = theme === "dark" ? "☀️" : "🌙";
  try { localStorage.setItem("stories-theme", theme); } catch { /* sem storage */ }
}

function initTheme(fallback) {
  let theme = fallback;
  try { theme = localStorage.getItem("stories-theme") || fallback; } catch { /* sem storage */ }
  applyTheme(theme);
}

/* ---------- Épicos e relacionados ---------- */
const epicState = { items: [], children: [], relatedSelected: new Set() };

async function loadEpics() {
  try {
    epicState.items = await api("/api/epics");
  } catch (err) {
    epicState.items = [];
    showToast(escapeHtml(err.message), true);
  }
  renderEpicOptions($("#f-epic").value);
}

function renderEpicOptions(selectedId = "") {
  const known = epicState.items.some((e) => String(e.id) === String(selectedId));
  const options = ['<option value="">Selecione um épico</option>']
    .concat(epicState.items.map((e) => `<option value="${e.id}">${escapeHtml(e.title)}</option>`));
  // Épico salvo que não está mais nas colunas ativas continua selecionável.
  if (selectedId && !known) options.push(`<option value="${escapeHtml(selectedId)}">Épico ${escapeHtml(selectedId)}</option>`);
  $("#f-epic").innerHTML = options.join("");
  $("#f-epic").value = selectedId || "";
}

// Ícones de "Relacionados": tipo do card e fase (estado do Azure). Desconhecidos caem no padrão.
const TYPE_ICONS = { "user story": "📖", "technical story": "🔧", "spike": "🔬", "design story": "🎨", "bug": "🐞" };
const STATE_ICONS = {
  "new": "⚪", "to do": "⚪",                                     // a fazer
  "refining": "🟡", "tech refining": "🟡",                       // refinamento
  "in progress": "🔵", "active": "🔵",                           // em andamento
  "waiting validation qa": "🟣", "validating qa": "🟣", "user acceptance testing": "🟣",   // validação
  "package integration": "🟠", "waiting deploy": "🟠", "validating prod": "🟠",   // entrega
  "done": "✅", "closed": "✅",
  "discontinued": "⛔", "removed": "⛔",
};
const typeIcon = (type) => TYPE_ICONS[(type || "").toLowerCase()] || "📄";
const stateIcon = (state) => STATE_ICONS[(state || "").toLowerCase()] || "⚪";

function relatedItem(c) {
  const tip = `#${c.id} · ${c.title}\n${c.type} · ${c.state}`;
  return `<li>
    <input type="checkbox" data-id="${c.id}" ${epicState.relatedSelected.has(c.id) ? "checked" : ""}>
    <a href="${escapeHtml(c.url)}" target="_blank" rel="noopener" title="${escapeHtml(tip)}">${c.id} ${escapeHtml(c.title)}</a>
    <span class="icons" title="${escapeHtml(`${c.type} · ${c.state}`)}">${typeIcon(c.type)}${stateIcon(c.state)}</span>
  </li>`;
}

async function loadChildren(epicId) {
  const list = $("#related");
  epicState.children = [];
  if (!epicId) { list.innerHTML = ""; return; }
  list.innerHTML = '<li class="muted">Carregando...</li>';
  try {
    const children = await api(`/api/epics/${epicId}/children`);
    epicState.children = children;
    list.innerHTML = children.length
      ? children.map(relatedItem).join("")
      : '<li class="muted">Este épico não tem cards filhos.</li>';
  } catch (err) {
    list.innerHTML = `<li class="muted">${escapeHtml(err.message)}</li>`;
  }
}

/* ---------- Estado da página ---------- */
function collectState() {
  return {
    type: $("#f-type").value,
    epic: $("#f-epic").value,
    related: [...epicState.relatedSelected],
    tools: { notion: $("#t-notion").checked, azure: $("#t-azure").checked, obsidian: $("#t-obsidian").checked },
    brief: editors.brief.getHTML(),
    comment: $("#llm-comment").textContent,
    reply: editors.reply.getHTML(),
    text: editors.text.getHTML(),
    resources: editors.resources.getHTML(),
    criteria: editors.criteria.getHTML(),
    chat: app.chat,
    rating: app.rating,
    titleEdited: app.titleEdited,
    memoryNote: app.memoryNote,
    collapsed: [...document.querySelectorAll(".card.collapsed")].map((el) => el.id),
  };
}

function applyState(state = {}) {
  $("#f-type").value = state.type || "User Story";
  epicState.relatedSelected = new Set(state.related || []);
  renderEpicOptions(state.epic || "");
  loadChildren(state.epic || "");
  const tools = state.tools || { notion: true, azure: true, obsidian: false };
  $("#t-notion").checked = !!tools.notion;
  $("#t-azure").checked = !!tools.azure;
  $("#t-obsidian").checked = !!tools.obsidian;
  editors.brief.setHTML(state.brief);
  editors.reply.setHTML(state.reply);
  editors.text.setHTML(state.text);
  editors.resources.setHTML(state.resources);
  editors.criteria.setHTML(state.criteria);
  $("#llm-comment").textContent = state.comment || "";
  app.chat = state.chat || [];
  app.rating = state.rating;
  app.titleEdited = !!state.titleEdited;
  setMemoryNote(state.memoryNote || "");
  document.querySelectorAll(".card.collapsible").forEach((el) => {
    el.classList.toggle("collapsed", (state.collapsed || []).includes(el.id));
  });
}

function isLocked() { return !!app.story && app.story.status === "created"; }

/** Habilita ou bloqueia a edição: bloqueada em histórias já criadas e enquanto o agente trabalha. */
function refreshEditable() {
  const locked = isLocked();
  const editable = !locked && !app.running;
  Object.values(editors).forEach((ed) => ed.setEditable(editable));
  $(".columns").classList.toggle("locked", locked);
  $("#story-title").disabled = locked || app.running;
  $("#btn-generate").disabled = locked || app.running;
  $("#btn-reply").disabled = locked || app.running || replyBlocked();
  $("#btn-create").disabled = locked || app.running;
  $("#btn-clear").disabled = locked || app.running;
  renderRating();
}

function clearCard() {
  if (!confirm("Limpar o texto do card, os recursos impactados e os critérios de aceite?\n\nO título e os demais campos são mantidos.")) return;
  editors.text.setHTML("");
  editors.resources.setHTML("");
  editors.criteria.setHTML("");
  alignCriteria();
  scheduleSave();
}

/* ---------- Feedback humano sobre a resposta do agente (eval) ---------- */
function feedbackRequired() {
  const evals = (app.settings && app.settings.evals) || {};
  return evals.require_human_feedback !== false;
}

/** Responder fica indisponível enquanto a última resposta do agente não foi avaliada. */
function replyBlocked() { return feedbackRequired() && app.rating === null; }

function renderRating() {
  $("#rating").hidden = app.rating === undefined;
  document.querySelectorAll("#rating .rate").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.rating === app.rating));
    btn.disabled = isLocked() || app.running;
  });
  $("#rating-hint").hidden = !(replyBlocked() && !isLocked());
}

async function rateResponse(rating) {
  if (!app.story || isLocked() || app.running || app.rating === undefined) return;
  const storyId = app.story.id;
  try {
    await api(`/api/history/${storyId}/rating`, { method: "PUT", body: { rating } });
    if (!app.story || app.story.id !== storyId) return;   // trocou de história durante a gravação
    app.rating = rating;
    refreshEditable();
    scheduleSave();
  } catch (err) {
    showToast(escapeHtml(err.message), true);
  }
}

function setMemoryNote(text) {
  app.memoryNote = text;
  $("#memory-note").textContent = text;
  $("#memory-note").hidden = !text;
}

async function saveDraftNow() {
  await api(`/api/drafts/${app.story.id}`, {
    method: "PUT",
    body: { title: $("#story-title").value, state: collectState() },
  });
  refreshRecent();
}

function scheduleSave() {
  if (!app.story || app.story.status === "created") return;
  clearTimeout(app.saveTimer);
  app.saveTimer = setTimeout(async () => {
    try {
      await saveDraftNow();
    } catch (err) {
      showToast(escapeHtml(err.message), true);
    }
  }, 600);
}

/** Grava já o que está na tela, cancelando o autosave pendente (antes de criar o card). */
async function flushSave() {
  clearTimeout(app.saveTimer);
  await saveDraftNow();
}

/* ---------- Histórias ---------- */
async function openStory(id) {
  const story = await api(`/api/history/${id}`);
  app.story = story;
  $("#story-title").value = story.title;
  applyState(story.state);
  refreshEditable();
  if (story.status === "created" && story.card_url) {
    showCreatedToast(story.card_id, story.card_url, story.title);
  } else {
    hideToast();
  }
  applyChrome();
  alignCriteria();
  refreshRecent();
}

async function newStory() {
  const story = await api("/api/history", { method: "POST" });
  await openStory(story.id);
}

async function refreshRecent() {
  const items = await api("/api/history");
  $("#recent").innerHTML = items
    .map((s) => `<div class="item"><a data-id="${s.id}" class="${app.story && app.story.id === s.id ? "active" : ""}" title="${s.status === "created" ? `Criado no Azure DevOps (#${s.card_id})` : "Rascunho"}">${s.status === "created" ? "✅ " : ""}${escapeHtml(s.title)}</a><button class="del" data-del="${s.id}" title="Remover da lista" aria-label="Remover da lista">✕</button></div>`)
    .join("");
}

/** Remove só da lista local; o card no Azure DevOps (se existir) não é afetado. */
async function deleteStory(id) {
  if (!confirm("Remover esta história da lista de recentes?\n\nO card no Azure DevOps, se já criado, não é afetado.")) return;
  const wasOpen = app.story && app.story.id === id;
  if (wasOpen) clearTimeout(app.saveTimer);   // um autosave pendente não deve recriar a história removida
  await api(`/api/history/${id}`, { method: "DELETE" });
  if (!wasOpen) { refreshRecent(); return; }
  const rest = await api("/api/history");
  if (rest.length) await openStory(rest[0].id); else await newStory();
}

/* ---------- Status e settings ---------- */
async function refreshStatus() {
  const status = await api("/api/status");
  $("#status").innerHTML = Object.entries(STATUS_LABELS)
    .map(([key, label]) => {
      const s = status[key];
      const connect = key === "notion_mcp" && s.state === "unauthorized"
        ? ' <a class="connect" href="/api/oauth/notion/start">conectar</a>' : "";
      return `<li title="${escapeHtml(s.detail || "")}"><span class="dot ${s.ok ? "ok" : s.state === "connecting" ? "wait" : ""}"></span>${label}${connect}</li>`;
    })
    .join("");
  // Conexões MCP sobem em segundo plano: reconsulta enquanto alguma ainda está conectando.
  if (Object.values(status).some((s) => s.state === "connecting")) {
    clearTimeout(app.statusTimer);
    app.statusTimer = setTimeout(refreshStatus, 2000);
  }
}

/* ---------- Colunas ativas de Épicos (dropdown de checkboxes) ---------- */
const epicColumns = { selected: new Set(), available: [], loadedFor: null };

function renderEpicColumns(message = "") {
  const list = $("#epic-columns-list");
  if (message) {
    list.innerHTML = `<div class="multi-empty">${escapeHtml(message)}</div>`;
  } else {
    // Colunas já salvas que não existem mais no board continuam visíveis, para o usuário poder desmarcá-las.
    const names = epicColumns.available.map((c) => c.name);
    const orphans = [...epicColumns.selected].filter((n) => !names.includes(n));
    list.innerHTML = [...names, ...orphans]
      .map((name) => `<label><input type="checkbox" value="${escapeHtml(name)}" ${epicColumns.selected.has(name) ? "checked" : ""}> ${escapeHtml(name)}${orphans.includes(name) ? " (não existe mais)" : ""}</label>`)
      .join("");
  }
  const count = epicColumns.selected.size;
  $("#epic-columns-summary").textContent = count ? `${count} selecionada${count > 1 ? "s" : ""}: ${[...epicColumns.selected].join(", ")}` : "Selecione";
}

async function loadEpicColumns() {
  const url = $("#settings-form").elements.board_url.value.trim();
  if (!url) { renderEpicColumns("Informe a URL do Board para listar as colunas."); return; }
  if (epicColumns.loadedFor === url) { renderEpicColumns(); return; }
  renderEpicColumns("Carregando colunas...");
  try {
    epicColumns.available = await api(`/api/azure/epic-columns?board_url=${encodeURIComponent(url)}`);
    epicColumns.loadedFor = url;
    renderEpicColumns();
  } catch (err) {
    epicColumns.loadedFor = null;
    renderEpicColumns(err.message);
  }
}

function fillSettingsForm() {
  const s = app.settings;
  const f = $("#settings-form").elements;
  f.user_name.value = s.user_name;
  f.board_url.value = s.azure.board_url;
  showBoardInfo();
  epicColumns.selected = new Set(s.azure.epic_active_columns);
  epicColumns.loadedFor = null;
  loadEpicColumns();
  f.azure_mcp_dll.value = (s.azure_mcp.args || [])[0] || "";
  f.wiki_url.value = s.azure.wiki_url || "";
  f.require_feedback.checked = (s.evals || {}).require_human_feedback !== false;
  f.obsidian_root.value = s.obsidian.root_dir;
  f.notion_root.value = s.notion.root_page;
  f.skills_dir.value = s.agent.skills_dir;
  f.tools_dir.value = s.agent.tools_dir;
  f.system_prompt.value = s.agent.system_prompt || app.defaults.system_prompt;
}

async function saveSettings(event) {
  event.preventDefault();
  const f = $("#settings-form").elements;
  const patch = {
    user_name: f.user_name.value.trim(),
    azure: {
      board_url: f.board_url.value.trim(),
      wiki_url: f.wiki_url.value.trim(),
      epic_active_columns: [...epicColumns.selected],
    },
    azure_mcp: { args: f.azure_mcp_dll.value.trim() ? [f.azure_mcp_dll.value.trim()] : [] },
    obsidian: { root_dir: f.obsidian_root.value.trim() },
    notion: { root_page: f.notion_root.value.trim() },
    evals: { require_human_feedback: f.require_feedback.checked },
    agent: {
      skills_dir: f.skills_dir.value.trim(),
      tools_dir: f.tools_dir.value.trim(),
      // Texto igual ao padrão não é gravado: assim o padrão pode evoluir sem ficar congelado.
      system_prompt: f.system_prompt.value.trim() === app.defaults.system_prompt ? "" : f.system_prompt.value,
    },
  };
  const error = $("#settings-error");
  try {
    const data = await api("/api/settings", { method: "PUT", body: patch });
    app.settings = data.settings;
    app.board = data.board;
    app.defaults = data.defaults;
    applyChrome();
    showBoardInfo();
    refreshEditable();     // o switch de feedback obrigatório vale já
    loadEpics();
    error.hidden = true;
    $("#settings-dialog").close();
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  }
}

function applyChrome() {
  $("#user-name").textContent = app.settings.user_name || "Usuário";
  $("#f-board").value = app.board ? app.board.team : "";
}

function showBoardInfo() {
  const b = app.board;
  $("#board-info").textContent = b
    ? `Reconhecido: organização ${b.organization} · projeto ${b.project} · time ${b.team} · nível ${b.backlog_level}`
    : "";
}

/* ---------- Toast ---------- */
function showToast(html, isError = false) {
  const el = $("#toast");
  $("#toast-body").innerHTML = html;
  el.classList.toggle("error", isError);
  el.hidden = false;
  // O alerta fica no topo, e botões como "Criar card" ficam no fim da página: leva o usuário até ele.
  $(".main").scrollTo({ top: 0, behavior: "smooth" });
}
function hideToast() { $("#toast").hidden = true; }

/** Alerta de sucesso: o nome do card é um link para ele no Azure DevOps. */
function showCreatedToast(cardId, url, title, warnings = []) {
  const extra = warnings.length ? `<br><small>${warnings.map(escapeHtml).join("<br>")}</small>` : "";
  showToast(`✅ Card criado com sucesso: <a href="${escapeHtml(url)}" target="_blank" rel="noopener">#${cardId} — ${escapeHtml(title)}</a>${extra}`);
}

/* ---------- Layout: Critérios de Aceite acompanha "Texto do card" no eixo y ---------- */
function alignCriteria() {
  const criteria = $("#sec-criteria");
  criteria.style.marginTop = "0px";
  if (window.matchMedia("(max-width: 900px)").matches) return;
  // O flex gap já separa de "Recursos impactados"; margin >= 0 impede que suba acima dele.
  const offset = $("#sec-text").getBoundingClientRect().top - criteria.getBoundingClientRect().top;
  criteria.style.marginTop = `${Math.max(0, offset)}px`;
}

/* ---------- Agente: Gerar e Responder ---------- */
const STEP_SOURCES = [
  ["notion__", "Notion"], ["azure_boards__", "Azure DevOps"], ["azure_", "Azure DevOps"],
  ["obsidian_", "Obsidian"], ["load_skill", "Skill"],
];

function describeStep(step) {
  const [, source] = STEP_SOURCES.find(([prefix]) => step.tool.startsWith(prefix)) || [null, "Ferramenta"];
  const name = step.tool.replace(/^(notion__notion-|azure_boards__|azure_|obsidian_)/, "").replace(/_/g, " ").replace(/-/g, " ");
  return `${source}: ${name}`;
}

function setRunStatus(text) {
  const el = $("#run-status");
  el.textContent = text;
  el.hidden = !text;
}

function isEmptyHtml(html) { return !html || !html.replace(/<[^>]*>/g, "").trim(); }

function buildRunBody(kind) {
  const selected = epicState.children.filter((c) => epicState.relatedSelected.has(c.id));
  const epicSelect = $("#f-epic");
  const epicId = Number(epicSelect.value) || null;
  const body = {
    story_id: app.story.id,
    card_type: $("#f-type").value,
    epic_id: epicId,
    epic_title: epicId ? epicSelect.selectedOptions[0].textContent : "",
    related: selected.map((c) => ({ id: c.id, title: c.title })),
    brief: editors.brief.getHTML(),
    tools: { notion: $("#t-notion").checked, azure: $("#t-azure").checked, obsidian: $("#t-obsidian").checked },
    title: $("#story-title").value,
    card_html: "", resources_html: "", criteria_html: "", chat: [], reply: "",
  };
  if (kind === "reply") {
    // Responder reenvia os três textos (com as edições do usuário), a conversa e a resposta.
    body.card_html = editors.text.getHTML();
    body.resources_html = editors.resources.getHTML();
    body.criteria_html = editors.criteria.getHTML();
    body.chat = app.chat;
    body.reply = editors.reply.getHTML();
  }
  return body;
}

async function pollJob(jobId) {
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    const last = job.steps[job.steps.length - 1];
    setRunStatus(last ? `⏳ ${describeStep(last)} · ${job.steps.length} consulta${job.steps.length > 1 ? "s" : ""}` : "⏳ Preparando…");
    if (job.status === "done") return job.result;
    if (job.status === "error") throw new Error(job.error);
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

function applyResult(result, replyText) {
  let comment = result.comment || "";
  if (result.hit_step_limit) {
    comment += "\n\n⚠️ Limite de consultas atingido: o texto foi montado com o contexto reunido até aqui.";
  }
  if (replyText) app.chat.push({ role: "user", content: replyText });
  app.chat.push({ role: "assistant", content: comment });

  if (result.mode === "draft") {
    editors.text.setHTML(result.card_html);
    editors.resources.setHTML(result.resources_html);
    editors.criteria.setHTML(result.criteria_html);
    if (result.title && !app.titleEdited) $("#story-title").value = result.title;
  }
  $("#llm-comment").textContent = comment;
  app.rating = null;                       // nova resposta: aguarda a avaliação humana
  editors.reply.setHTML("");
  setMemoryNote(result.learnings_saved.length ? `🧠 Memória atualizada: ${result.learnings_saved.join(" · ")}` : "");
  $("#sec-iter").classList.remove("collapsed");   // o comentário precisa estar visível
}

async function runAgent(kind) {
  if (app.running || !app.story || isLocked()) return;
  hideToast();
  const body = buildRunBody(kind);
  const replyText = kind === "reply" ? body.reply : "";

  if (isEmptyHtml(body.brief)) { showToast("Descreva o objetivo do card em “Descrição breve”.", true); return; }
  if (kind === "reply") {
    if (replyBlocked()) { showToast("Avalie a resposta (👍 ◽ 👎) antes de responder.", true); return; }   // vale também para o Ctrl+Enter
    if (isEmptyHtml(body.reply)) { showToast("Digite uma resposta para enviar ao agente.", true); return; }
    if (!app.chat.length && isEmptyHtml(body.card_html)) { showToast("Clique em Gerar antes de responder.", true); return; }
  } else if (!isEmptyHtml(editors.text.getHTML()) &&
             !window.confirm("Gerar novamente substitui o texto, os recursos e os critérios atuais. Continuar?")) {
    return;
  }

  app.running = true;
  refreshEditable();
  setRunStatus("⏳ Iniciando…");
  try {
    const job = await api(kind === "reply" ? "/api/reply" : "/api/generate", { method: "POST", body });
    const result = await pollJob(job.id);
    applyResult(result, replyText);
    alignCriteria();
    scheduleSave();
  } catch (err) {
    showToast(escapeHtml(err.message || "Falha ao executar o agente."), true);
  } finally {
    app.running = false;
    setRunStatus("");
    refreshEditable();
  }
}

/* ---------- Criar card ---------- */
async function createCard() {
  if (app.running || !app.story || isLocked()) return;
  hideToast();
  const title = $("#story-title").value.trim();
  const epicId = Number($("#f-epic").value) || null;
  const textHtml = editors.text.getHTML();

  if (!title || title === DEFAULT_TITLE) { showToast("Defina o título do card antes de criar.", true); return; }
  if (isEmptyHtml(textHtml)) { showToast("O “Texto do card” está vazio.", true); return; }
  if (!epicId) { showToast("Selecione o Épico: o card é criado como filho dele.", true); return; }

  const related = [...epicState.relatedSelected];
  const epicTitle = $("#f-epic").selectedOptions[0].textContent;
  const summary = `Criar este card no Azure DevOps?\n\nTipo: ${$("#f-type").value}\nTítulo: ${title}\nÉpico: ${epicTitle}\nRelacionados: ${related.length || "nenhum"}\n\nDepois de criado, esta história fica bloqueada para edição.`;
  if (!window.confirm(summary)) return;

  app.running = true;                       // bloqueia botões e editores durante o envio
  refreshEditable();
  setRunStatus("⏳ Criando card…");
  try {
    await flushSave();                      // garante que o estado final está no histórico
    const result = await api("/api/cards", {
      method: "POST",
      body: {
        story_id: app.story.id, card_type: $("#f-type").value, epic_id: epicId, related, title,
        card_html: textHtml, resources_html: editors.resources.getHTML(), criteria_html: editors.criteria.getHTML(),
      },
    });
    app.story = await api(`/api/history/${app.story.id}`);
    $("#story-title").value = app.story.title;
    showCreatedToast(result.id, result.url, result.title, result.warnings);
    refreshRecent();
  } catch (err) {
    showToast(escapeHtml(err.message || "Não foi possível criar o card."), true);
  } finally {
    app.running = false;
    setRunStatus("");
    refreshEditable();                      // se criou, isLocked() agora é verdadeiro e mantém tudo bloqueado
  }
}

/* ---------- Eventos ---------- */
function setupEditors() {
  const onChange = () => { alignCriteria(); scheduleSave(); };
  editors.brief = createEditor($("#f-brief"), { placeholder: "Descreva o objetivo do card em linguagem simples.", onChange });
  editors.reply = createEditor($("#f-reply"), {
    placeholder: "Prompt de iteração com LLM.. (Ctrl+Enter envia)", onChange, onSubmit: () => runAgent("reply"),
  });
  editors.text = createEditor($("#f-text"), { placeholder: "A IA irá preencher este campo após a geração.", onChange });
  editors.resources = createEditor($("#f-resources"), { placeholder: "Um recurso por linha", onChange });
  editors.criteria = createEditor($("#f-criteria"), { placeholder: "Um critério por linha.", onChange });
}

function bindEvents() {
  $("#btn-generate").addEventListener("click", () => runAgent("generate"));
  $("#btn-reply").addEventListener("click", () => runAgent("reply"));
  $("#btn-create").addEventListener("click", createCard);
  $("#new-story").addEventListener("click", newStory);
  $("#btn-clear").addEventListener("click", clearCard);
  $("#toast-close").addEventListener("click", hideToast);
  $("#rating").addEventListener("click", (e) => {
    const btn = e.target.closest(".rate");
    if (btn) rateResponse(btn.dataset.rating);
  });
  $("#recent").addEventListener("click", (e) => {
    const del = e.target.closest("button[data-del]");
    if (del) {
      deleteStory(del.dataset.del).catch((err) => showToast(escapeHtml(err.message), true));
      return;
    }
    const link = e.target.closest("a[data-id]");
    if (link) openStory(link.dataset.id);
  });
  $("#toggle-theme").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  $("#open-settings").addEventListener("click", () => { fillSettingsForm(); $("#settings-dialog").showModal(); });
  $("#settings-cancel").addEventListener("click", () => $("#settings-dialog").close());
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#settings-form").elements.board_url.addEventListener("change", loadEpicColumns);
  $("#epic-columns-list").addEventListener("change", (e) => {
    if (e.target.type !== "checkbox") return;
    e.target.checked ? epicColumns.selected.add(e.target.value) : epicColumns.selected.delete(e.target.value);
    renderEpicColumns();
    $("#epic-columns").open = true;
  });

  // Qualquer ponto do cabeçalho recolhe/expande a seção (o botão ⌄ está dentro dele).
  document.querySelectorAll(".card.collapsible > .card-head").forEach((head) => {
    const toggle = () => {
      head.parentElement.classList.toggle("collapsed");
      alignCriteria();
      scheduleSave();
    };
    head.addEventListener("click", toggle);
    head.addEventListener("keydown", (e) => {
      if (e.target === head && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(); }
    });
  });

  document.querySelectorAll("#f-type, #f-epic, #t-notion, #t-azure, #t-obsidian")
    .forEach((el) => el.addEventListener("input", () => { alignCriteria(); scheduleSave(); }));
  $("#f-epic").addEventListener("change", () => {
    epicState.relatedSelected = new Set(); // filhos de outro épico não se aplicam
    loadChildren($("#f-epic").value);
    scheduleSave();
  });
  $("#related").addEventListener("change", (e) => {
    const id = Number(e.target.dataset.id);
    if (!id) return;
    e.target.checked ? epicState.relatedSelected.add(id) : epicState.relatedSelected.delete(id);
    scheduleSave();
  });
  $("#story-title").addEventListener("input", () => {
    // Só conta como "editado" se sobrar texto: título vazio devolve ao agente o direito de preencher.
    app.titleEdited = $("#story-title").value.trim() !== "";
    scheduleSave();
  });
  window.addEventListener("resize", alignCriteria);
  new ResizeObserver(alignCriteria).observe($("#sec-text"));
}

async function init() {
  const boot = await api("/api/bootstrap");
  app.settings = boot.settings;
  app.board = boot.board;
  app.defaults = boot.defaults;
  initTheme(app.settings.theme);
  applyChrome();
  setupEditors();
  // Bloqueados até a história abrir: o estado salvo é aplicado ali e apagaria o que fosse digitado antes.
  Object.values(editors).forEach((ed) => ed.setEditable(false));
  bindEvents();
  refreshStatus();
  if (app.board) loadEpics();       // em paralelo: a lista de épicos (Azure) não deve atrasar a abertura
  if (boot.recent.length) {
    await openStory(boot.recent[0].id);
  } else {
    await newStory();
  }
  if (!app.board) {
    fillSettingsForm();
    $("#settings-dialog").showModal();
  }
}

init().catch((err) => {
  console.error(err);
  showToast(escapeHtml(err.message || "Erro inesperado ao iniciar a ferramenta."), true);
});
