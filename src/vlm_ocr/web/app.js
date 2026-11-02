const state = {
  workspace: null,
  document: null,
  page: 0,
  pageUrls: new Map(),
  boxes: new Map(),
  selected: null,
  selectedBlock: null,
  fields: [],
  extraction: null,
};

const $ = (id) => document.getElementById(id);
const SUPPORTED_LANGS = ["es", "en"];
let locale = {};

function token() {
  return sessionStorage.getItem("vlm-token") || "";
}

function t(key, params = {}) {
  let text = locale[key] ?? key;
  for (const [name, value] of Object.entries(params)) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

function detectLang() {
  const stored = localStorage.getItem("vlm-lang");
  if (stored && SUPPORTED_LANGS.includes(stored)) {
    return stored;
  }
  return (navigator.language || "es").toLowerCase().startsWith("en") ? "en" : "es";
}

async function loadLocale(lang) {
  const response = await fetch(`locales/${lang}.json`);
  locale = await response.json();
  document.documentElement.lang = lang;
  $("lang").value = lang;
  applyI18n();
}

function applyI18n() {
  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  }
  for (const node of document.querySelectorAll("[data-i18n-title]")) {
    node.setAttribute("title", t(node.dataset.i18nTitle));
  }
  renderFields();
  if (state.document) {
    renderRecentsFromState();
  }
}

function setStatus(text) {
  $("status").textContent = text;
}

function showError(error) {
  const node = $("error");
  node.hidden = false;
  node.textContent = error instanceof Error ? error.message : String(error);
}

function clearError() {
  const node = $("error");
  node.hidden = true;
  node.textContent = "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token()}`);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || body.error || detail;
    } catch (error) {
      // respuesta sin JSON
    }
    throw new Error(detail);
  }
  return response;
}

async function loadPageImage(page) {
  if (state.pageUrls.has(page.index)) {
    return state.pageUrls.get(page.index);
  }
  const response = await api(page.image_url);
  const url = URL.createObjectURL(await response.blob());
  state.pageUrls.set(page.index, url);
  return url;
}

function pageBlocks(page) {
  return state.document.blocks.filter((block) => block.page === page.index);
}

function drawBoxes(page) {
  const container = $("boxes");
  container.innerHTML = "";
  state.boxes = new Map();
  if (!page.width || !page.height) {
    return;
  }
  pageBlocks(page).forEach((block, index) => {
    const [x0, y0, x1, y1] = block.box;
    if (x1 <= x0 || y1 <= y0) {
      return;
    }
    const element = document.createElement("button");
    element.type = "button";
    element.className = "box";
    element.title = block.text;
    element.style.left = `${(x0 / page.width) * 100}%`;
    element.style.top = `${(y0 / page.height) * 100}%`;
    element.style.width = `${((x1 - x0) / page.width) * 100}%`;
    element.style.height = `${((y1 - y0) / page.height) * 100}%`;
    element.addEventListener("click", () => selectBlock(index));
    container.appendChild(element);
    state.boxes.set(index, element);
  });
}

function renderText(page) {
  const panel = $("text-panel");
  panel.innerHTML = "";
  pageBlocks(page).forEach((block, index) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "text-block";
    item.textContent = block.text;
    item.dataset.index = String(index);
    item.addEventListener("click", () => selectBlock(index));
    panel.appendChild(item);
  });
}

function selectBlock(index) {
  state.selected = index;
  state.selectedBlock = pageBlocks(state.document.pages[state.page])[index] || null;
  for (const [key, element] of state.boxes.entries()) {
    element.classList.toggle("selected", key === index);
  }
  for (const element of $("text-panel").children) {
    element.classList.toggle("selected", Number(element.dataset.index) === index);
  }
  const box = state.boxes.get(index);
  if (box) {
    box.scrollIntoView({ block: "nearest", inline: "nearest" });
  } else {
    const item = $("text-panel").querySelector(`[data-index="${index}"]`);
    if (item) {
      item.scrollIntoView({ block: "nearest" });
    }
  }
  renderFields();
}

async function showPage(index) {
  const page = state.document.pages[index];
  if (!page) {
    return;
  }
  state.page = index;
  state.selected = null;
  state.selectedBlock = null;
  $("page-label").textContent = `${index + 1} / ${state.document.pages.length}`;
  $("prev").disabled = index === 0;
  $("next").disabled = index === state.document.pages.length - 1;
  const image = $("page-image");
  image.onload = () => {
    if (!page.width || !page.height) {
      page.width = image.naturalWidth;
      page.height = image.naturalHeight;
    }
    drawBoxes(page);
  };
  image.src = await loadPageImage(page);
  drawBoxes(page);
  renderText(page);
  renderFields();
}

function showViewer() {
  $("dropzone").hidden = true;
  $("recents").hidden = true;
  $("viewer").hidden = false;
}

async function upload(file) {
  clearError();
  setStatus(t("status.processing"));
  const form = new FormData();
  form.append("file", file);
  try {
    const response = await api("/api/workspaces", { method: "POST", body: form });
    const payload = await response.json();
    state.workspace = payload.workspace;
    state.document = payload.document;
    state.pageUrls = new Map();
    state.fields = [];
    state.extraction = null;
    $("extract-summary").textContent = "";
    showViewer();
    await showPage(0);
    $("status").textContent = `${payload.document.filename} · ${payload.document.pages.length}`;
    await loadRecents();
  } catch (error) {
    setStatus(t("status.error"));
    showError(error);
  }
}

async function openWorkspace(workspaceId) {
  clearError();
  setStatus(t("status.opening"));
  try {
    const metaResponse = await api(`/api/workspaces/${workspaceId}`);
    const meta = (await metaResponse.json()).workspace;
    const textResponse = await api(`/api/workspaces/${workspaceId}/text`);
    const ocr = await textResponse.json();
    const pages = (ocr.pages || []).map((page) => ({
      ...page,
      image_url: `/api/workspaces/${workspaceId}/pages/${page.index}.png`,
    }));
    state.workspace = meta;
    state.document = {
      filename: meta.document.filename,
      format: meta.document.format,
      pages,
      blocks: ocr.blocks || [],
      text: ocr.text || "",
    };
    state.pageUrls = new Map();
    state.fields = [];
    state.extraction = null;
    await loadContract(workspaceId);
    showViewer();
    await showPage(0);
    $("status").textContent = `${meta.document.filename} · ${pages.length}`;
  } catch (error) {
    setStatus(t("status.error"));
    showError(error);
  }
}

function summaryText(extraction) {
  return t("summary", {
    ok: extraction.matched.length,
    pending: extraction.pending.length,
    missing: extraction.unmatched.length,
  });
}

async function loadContract(workspaceId) {
  try {
    const schemaResponse = await api(
      `/api/workspaces/${workspaceId}/export/schema`
    );
    const schema = await schemaResponse.json();
    state.fields = Object.entries(schema.properties || {}).map(
      ([name, node]) => ({
        name,
        type: Array.isArray(node.type)
          ? node.type.find((item) => item !== "null") || "text"
          : node.type || "text",
        labels: node["x-labels"] || [],
        source: node["x-source"] || "",
      })
    );
  } catch (error) {
    state.fields = [];
  }
  try {
    const resultResponse = await api(
      `/api/workspaces/${workspaceId}/export/result`
    );
    const result = await resultResponse.json();
    state.extraction = result.extraction || null;
    if (state.extraction) {
      $("extract-summary").textContent = summaryText(state.extraction);
    }
  } catch (error) {
    state.extraction = null;
  }
}

let recentsCache = [];

async function loadRecents() {
  if (!token()) {
    return;
  }
  try {
    const response = await api("/api/workspaces");
    const payload = await response.json();
    recentsCache = payload.workspaces || [];
    renderRecents(recentsCache);
  } catch (error) {
    // sin token o servidor no disponible: el health ya lo indica
  }
}

function renderRecentsFromState() {
  renderRecents(recentsCache);
}

function renderRecents(rows) {
  const section = $("recents");
  const list = $("recents-list");
  list.innerHTML = "";
  if (!rows.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "recent";

    const open = document.createElement("button");
    open.type = "button";
    open.className = "recent-open";
    open.textContent = row.name || row.document.filename;
    open.title = `${row.document.filename} · ${row.updated_at}`;
    open.addEventListener("click", () => openWorkspace(row.id));
    item.appendChild(open);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "×";
    remove.title = t("recents.delete");
    remove.addEventListener("click", () => deleteWorkspace(row.id));
    item.appendChild(remove);

    list.appendChild(item);
  }
}

async function deleteWorkspace(workspaceId) {
  if (!window.confirm(t("confirm.delete"))) {
    return;
  }
  try {
    await api(`/api/workspaces/${workspaceId}`, { method: "DELETE" });
    await loadRecents();
    setStatus(t("status.workspaceDeleted"));
  } catch (error) {
    showError(error);
  }
}

function addField() {
  const index = state.fields.length + 1;
  state.fields.push({
    name: `campo_${index}`,
    type: "text",
    labels: [],
    source: "",
  });
  renderFields();
}

function fieldStatus(field) {
  const result = state.extraction;
  if (!result) {
    return null;
  }
  if (result.matched.includes(field.name)) {
    return { kind: "ok", text: String(result.data[field.name] ?? "") };
  }
  if (result.pending.includes(field.name)) {
    return { kind: "pending", text: t("status.pending") };
  }
  return { kind: "missing", text: t("status.missing") };
}

function renderFields() {
  const container = $("fields");
  if (!container) {
    return;
  }
  container.innerHTML = "";
  if (!state.fields.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = t("contract.empty");
    container.appendChild(empty);
    return;
  }
  state.fields.forEach((field, index) => {
    const row = document.createElement("div");
    row.className = "field-row";

    const name = document.createElement("input");
    name.value = field.name;
    name.placeholder = t("field.name");
    name.addEventListener("input", () => {
      field.name = name.value;
    });
    row.appendChild(name);

    const type = document.createElement("select");
    for (const option of ["text", "number", "integer", "date"]) {
      const node = document.createElement("option");
      node.value = option;
      node.textContent = t(`type.${option}`);
      node.selected = field.type === option;
      type.appendChild(node);
    }
    type.addEventListener("change", () => {
      field.type = type.value;
    });
    row.appendChild(type);

    const labels = document.createElement("input");
    labels.value = field.labels.join(", ");
    labels.placeholder = t("field.labels");
    labels.addEventListener("input", () => {
      field.labels = labels.value
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    });
    row.appendChild(labels);

    const source = document.createElement("input");
    source.value = field.source;
    source.placeholder = t("field.source");
    source.setAttribute("list", "sources");
    source.addEventListener("input", () => {
      field.source = source.value.trim();
    });
    row.appendChild(source);

    const assign = document.createElement("button");
    assign.type = "button";
    assign.textContent = t("field.assign");
    assign.disabled = !state.selectedBlock;
    assign.addEventListener("click", () => {
      if (!state.selectedBlock) {
        return;
      }
      if (!field.labels.includes(state.selectedBlock.text)) {
        field.labels.push(state.selectedBlock.text);
        labels.value = field.labels.join(", ");
      }
    });
    row.appendChild(assign);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "×";
    remove.title = t("field.remove");
    remove.addEventListener("click", () => {
      state.fields.splice(index, 1);
      renderFields();
    });
    row.appendChild(remove);

    const status = fieldStatus(field);
    if (status) {
      const node = document.createElement("span");
      node.className = `field-status ${status.kind}`;
      node.textContent = status.text;
      row.appendChild(node);
    }

    container.appendChild(row);
  });
}

function buildSchema() {
  const properties = {};
  for (const field of state.fields) {
    const name = field.name.trim();
    if (!name) {
      throw new Error(t("error.noName"));
    }
    if (properties[name]) {
      throw new Error(t("error.duplicate", { name }));
    }
    const type = field.type === "date" ? "string" : field.type;
    const node = { type: [type, "null"], "x-labels": field.labels };
    if (field.source) {
      node["x-source"] = field.source;
    }
    properties[name] = node;
  }
  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    properties,
  };
}

async function extract() {
  clearError();
  if (!state.workspace) {
    return;
  }
  if (!state.fields.length) {
    showError(t("error.noFields"));
    return;
  }
  setStatus(t("status.extracting"));
  try {
    const schema = buildSchema();
    const response = await api(
      `/api/workspaces/${state.workspace.id}/contract`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schema }),
      }
    );
    const payload = await response.json();
    state.extraction = payload.extraction;
    renderFields();
    $("extract-summary").textContent = summaryText(payload.extraction);
    setStatus(t("status.extractionReady"));
  } catch (error) {
    setStatus(t("status.error"));
    showError(error);
  }
}

async function homologate() {
  clearError();
  if (!state.workspace) {
    return;
  }
  try {
    const schema = buildSchema();
    const response = await api(
      `/api/workspaces/${state.workspace.id}/homologate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schema }),
      }
    );
    const payload = await response.json();
    if (payload.template_saved) {
      setStatus(t("status.templateSaved"));
    } else {
      const fields = (payload.unlocated || []).join(", ");
      showError(t("error.noHomologate", { fields: fields ? `: ${fields}` : "" }));
    }
  } catch (error) {
    showError(error);
  }
}

async function download(path, filename) {
  clearError();
  try {
    const response = await api(path);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    showError(error);
  }
}

function exportCurrent(kind) {
  if (!state.workspace) {
    return;
  }
  const names = {
    schema: "contract.schema.json",
    result: "result.json",
    text: "text.md",
  };
  download(
    `/api/workspaces/${state.workspace.id}/export/${kind}`,
    names[kind]
  );
}

function reset() {
  for (const url of state.pageUrls.values()) {
    URL.revokeObjectURL(url);
  }
  state.workspace = null;
  state.document = null;
  state.pageUrls = new Map();
  state.boxes = new Map();
  state.selected = null;
  state.selectedBlock = null;
  state.fields = [];
  state.extraction = null;
  $("page-image").src = "";
  $("boxes").innerHTML = "";
  $("text-panel").innerHTML = "";
  $("fields").innerHTML = "";
  $("extract-summary").textContent = "";
  $("viewer").hidden = true;
  $("dropzone").hidden = false;
  $("file").value = "";
  setStatus(t("status.ready"));
  loadRecents();
}

function wire() {
  const dropzone = $("dropzone");
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("over");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("over"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("over");
    const file = event.dataTransfer.files[0];
    if (file) {
      upload(file);
    }
  });
  $("file").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (file) {
      upload(file);
    }
  });
  $("prev").addEventListener("click", () => showPage(state.page - 1));
  $("next").addEventListener("click", () => showPage(state.page + 1));
  $("new").addEventListener("click", reset);
  $("add-field").addEventListener("click", addField);
  $("extract").addEventListener("click", extract);
  $("homologate").addEventListener("click", homologate);
  $("export-schema").addEventListener("click", () => exportCurrent("schema"));
  $("export-result").addEventListener("click", () => exportCurrent("result"));
  $("export-text").addEventListener("click", () => exportCurrent("text"));
  $("lang").addEventListener("change", async (event) => {
    const lang = event.target.value;
    localStorage.setItem("vlm-lang", lang);
    await loadLocale(lang);
  });
}

async function health() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    const payload = await response.json();
    setStatus(`v${payload.version}`);
  } catch (error) {
    setStatus(t("status.noConnection"));
  }
}

const fragment = new URLSearchParams(location.hash.slice(1));
const initialToken = fragment.get("token");
if (initialToken) {
  sessionStorage.setItem("vlm-token", initialToken);
  history.replaceState(null, "", location.pathname);
}

wire();
loadLocale(detectLang()).then(() => {
  health();
  loadRecents();
});
