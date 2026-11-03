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
  stopSuggestions: [],
};

const $ = (id) => document.getElementById(id);
const SUPPORTED_LANGS = ["es", "en"];
const SOURCE_OPTIONS = [
  "unidades",
  "importe",
  "devengado",
  "a_deducir",
  "base",
  "porcentaje",
  "cuota",
];
const ROLE_ORDER = ["text", "quantity", "number_right", "observation"];
const ROLE_TYPES = {
  text: { type: "string", required: true },
  quantity: { type: ["integer", "null"], required: false },
  number_right: { type: ["number", "null"], required: true },
  observation: { type: ["string", "null"], required: false },
};
const FIELD_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
let locale = {};
let resizeObserver = null;

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
  updateSelection();
  applyTextCollapsed();
  refreshProposeButton();
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

const STOP_KEYWORDS = [
  "total",
  "subtotal",
  "total a pagar",
  "importe total",
  "suma",
  "iva",
  "impuesto",
  "impuestos",
  "tax",
  "amount due",
  "tender",
  "change",
  "cambio",
  "pagado",
  "pago",
  "efectivo",
  "base imponible",
  "propina",
  "servicio",
];

function normLabel(text) {
  return text
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function looksLikeNumber(text) {
  const cleaned = text.replace(/[$\u20ac\u00a3\u00a5]/g, "").replace(/\s/g, "");
  return /^[-+]?\d+([.,]\d+)*[.,]?\d*$/.test(cleaned) && /\d/.test(cleaned);
}

function labelHit(blocks, labels) {
  const wanted = (labels || []).map(normLabel).filter(Boolean);
  if (!wanted.length) {
    return false;
  }
  return blocks.some((block) => {
    const normalized = normLabel(block.text || "");
    return wanted.some(
      (want) => normalized === want || normalized.startsWith(`${want} `)
    );
  });
}

function suggestStops(blocks) {
  const seen = new Set();
  const found = [];
  for (const block of blocks || []) {
    const normalized = normLabel(block.text || "");
    if (!normalized) {
      continue;
    }
    const matched = STOP_KEYWORDS.some((keyword) => {
      const want = normLabel(keyword);
      return normalized === want || normalized.startsWith(`${want} `);
    });
    if (!matched) {
      continue;
    }
    const candidate = (block.text || "").trim().slice(0, 24);
    const key = normLabel(candidate);
    if (!seen.has(key)) {
      seen.add(key);
      found.push(candidate);
    }
    if (found.length >= 6) {
      break;
    }
  }
  return found;
}

function documentRows(blocks) {
  const rows = [];
  const byPage = new Map();
  for (const block of blocks || []) {
    if (!block.box || block.box[3] <= block.box[1]) {
      continue;
    }
    const list = byPage.get(block.page) || [];
    list.push(block);
    byPage.set(block.page, list);
  }
  for (const pageBlocks of byPage.values()) {
    const sorted = [...pageBlocks].sort(
      (left, right) =>
        (left.box[1] + left.box[3]) / 2 - (right.box[1] + right.box[3]) / 2
    );
    for (const block of sorted) {
      const center = (block.box[1] + block.box[3]) / 2;
      const height = block.box[3] - block.box[1];
      const row = rows.find(
        (item) => Math.abs(item.center - center) <= Math.max(6, height * 0.6)
      );
      if (row) {
        row.blocks.push(block);
      } else {
        rows.push({ center, blocks: [block] });
      }
    }
  }
  return rows;
}

function parseListRow(row, quantityDeclared) {
  const cells = row.blocks.filter((block) => (block.text || "").trim());
  const texts = cells.filter((block) => !looksLikeNumber(block.text));
  const numbers = cells.filter((block) => looksLikeNumber(block.text));
  if (!texts.length) {
    return { kind: "skip" };
  }
  let priceCell = null;
  if (numbers.length) {
    priceCell = numbers.reduce((left, right) =>
      right.box[0] > left.box[0] ? right : left
    );
    const leftEdge = Math.max(...texts.map((block) => block.box[2]));
    if (priceCell.box[0] < leftEdge - 2) {
      priceCell = null;
    }
  }
  if (priceCell) {
    const left = texts.filter(
      (block) => block.box[2] <= priceCell.box[0] + 2
    );
    let product = left
      .map((block) => block.text.trim())
      .join(" ")
      .trim();
    if (!product) {
      return { kind: "skip" };
    }
    let quantity = null;
    if (quantityDeclared) {
      const match = product.match(/^(\d+)\s+(.+)$/);
      if (match) {
        quantity = Number(match[1]);
        product = match[2].trim();
      }
    }
    return { kind: "item", text: product, quantity, price: priceCell.text };
  }
  const joined = texts
    .map((block) => block.text.trim())
    .join(" ")
    .trim();
  if (!joined) {
    return { kind: "skip" };
  }
  if (/^\d+\s+.+\s\d+[.,]\d{2}$/.test(joined)) {
    return { kind: "merged", text: joined };
  }
  if (quantityDeclared) {
    const match = joined.match(/^(\d+)\s+(.+)$/);
    if (match) {
      return {
        kind: "item",
        text: match[2].trim(),
        quantity: Number(match[1]),
        price: null,
      };
    }
  }
  return { kind: "extra", text: joined };
}

function previewItems(field) {
  if (!state.document) {
    return { items: [], noPrice: 0, merged: false, aborted: false };
  }
  const rows = documentRows(state.document.blocks);
  const quantityDeclared = Boolean((field.roles || {}).quantity);
  const observationDeclared = Boolean((field.roles || {}).observation);
  const hasStart = (field.startLabels || []).length > 0;
  const items = [];
  let counting = false;
  let noPrice = 0;
  let merged = false;
  let aborted = false;
  for (const row of rows) {
    if (!counting) {
      if (hasStart) {
        if (labelHit(row.blocks, field.startLabels)) {
          counting = true;
        }
        continue;
      }
      const parsed = parseListRow(row, quantityDeclared);
      if (parsed.kind === "item") {
        counting = true;
        if (parsed.price === null) {
          noPrice += 1;
        }
        items.push(parsed);
      }
      continue;
    }
    if (labelHit(row.blocks, field.stopLabels)) {
      break;
    }
    const parsed = parseListRow(row, quantityDeclared);
    if (parsed.kind === "skip") {
      continue;
    }
    if (parsed.kind === "merged") {
      merged = true;
      break;
    }
    if (parsed.kind === "item") {
      if (parsed.price === null) {
        noPrice += 1;
      }
      items.push(parsed);
      continue;
    }
    if (observationDeclared && items.length) {
      const previous = items[items.length - 1];
      previous.observation = previous.observation
        ? `${previous.observation} \n${parsed.text}`
        : parsed.text;
      continue;
    }
    aborted = true;
    break;
  }
  return { items, noPrice, merged, aborted };
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

function syncOverlay() {
  const image = $("page-image");
  const overlay = $("boxes");
  if (!image || !overlay || !image.naturalWidth) {
    return;
  }
  const imageRect = image.getBoundingClientRect();
  const wrapRect = $("page-wrap").getBoundingClientRect();
  overlay.style.left = `${imageRect.left - wrapRect.left}px`;
  overlay.style.top = `${imageRect.top - wrapRect.top}px`;
  overlay.style.width = `${imageRect.width}px`;
  overlay.style.height = `${imageRect.height}px`;
}

function observePage() {
  const image = $("page-image");
  if (!window.ResizeObserver) {
    return;
  }
  if (!resizeObserver) {
    resizeObserver = new ResizeObserver(() => syncOverlay());
  }
  resizeObserver.disconnect();
  resizeObserver.observe(image);
}

function listIndices() {
  const indices = [];
  state.fields.forEach((field, index) => {
    if (field.kind === "list") {
      indices.push(index);
    }
  });
  return indices;
}

function targetListIndex() {
  const indices = listIndices();
  if (!indices.length) {
    return null;
  }
  if (indices.length === 1) {
    return indices[0];
  }
  const target = $("action-list-target");
  if (target && target.value !== "") {
    const value = Number(target.value);
    if (indices.includes(value)) {
      return value;
    }
  }
  return indices[0];
}

function updateSelection() {
  const text = $("selection-text");
  if (!text) {
    return;
  }
  const has = Boolean(state.selectedBlock);
  text.textContent = has
    ? t("field.selected", { text: state.selectedBlock.text })
    : t("field.noSelection");
  const newField = $("action-new-field");
  const start = $("action-list-start");
  const stop = $("action-list-stop");
  const clear = $("action-clear");
  const target = $("action-list-target");
  const indices = listIndices();
  if (newField) {
    newField.disabled = !has;
  }
  if (target) {
    if (indices.length > 1) {
      target.hidden = false;
      const previous = target.value;
      target.innerHTML = "";
      for (const index of indices) {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = state.fields[index].name;
        target.appendChild(option);
      }
      target.value = indices.includes(Number(previous))
        ? previous
        : String(indices[0]);
    } else {
      target.hidden = true;
    }
  }
  const listReady = indices.length > 0;
  if (start) {
    start.disabled = !has || !listReady;
  }
  if (stop) {
    stop.disabled = !has || !listReady;
  }
  if (clear) {
    clear.disabled = !has;
  }
  const addFromBlock = $("add-field-block");
  if (addFromBlock) {
    addFromBlock.disabled = !state.selectedBlock;
  }
}

function clearSelection() {
  state.selected = null;
  state.selectedBlock = null;
  updateSelection();
  renderFields();
}

function assignedMap() {
  const assigned = new Map();
  const add = (label, reason) => {
    const key = normLabel(label || "");
    if (!key) {
      return;
    }
    const reasons = assigned.get(key) || new Set();
    reasons.add(reason);
    assigned.set(key, reasons);
  };
  for (const field of state.fields) {
    if (field.kind === "list") {
      for (const label of field.startLabels || []) {
        add(label, t("assign.listStart", { name: field.name }));
      }
      for (const label of field.stopLabels || []) {
        add(label, t("assign.listStop", { name: field.name }));
      }
    } else {
      for (const label of field.labels || []) {
        add(label, t("assign.scalar", { name: field.name }));
      }
    }
  }
  return assigned;
}

function updateBlockStates() {
  if (!state.document) {
    return;
  }
  const assigned = assignedMap();
  const blocks = pageBlocks(state.document.pages[state.page]);
  for (const [index, element] of state.boxes.entries()) {
    const block = blocks[index];
    if (!block) {
      continue;
    }
    const reasons = assigned.get(normLabel(block.text));
    element.classList.toggle("selected", state.selected === index);
    element.classList.toggle("assigned", Boolean(reasons));
    element.title = reasons
      ? `${block.text} · ${[...reasons].join(", ")}`
      : block.text;
  }
  for (const item of $("text-panel").children) {
    const index = Number(item.dataset.index);
    const block = blocks[index];
    if (!block) {
      continue;
    }
    const reasons = assigned.get(normLabel(block.text));
    item.classList.toggle("selected", state.selected === index);
    item.classList.toggle("assigned", Boolean(reasons));
  }
}

function applyTextCollapsed() {
  const collapsed = localStorage.getItem("vlm-text-collapsed") === "1";
  $("work").classList.toggle("text-collapsed", collapsed);
  const button = $("toggle-text");
  if (button) {
    button.textContent = t(collapsed ? "viewer.showText" : "viewer.hideText");
  }
}

function toggleText() {
  const collapsed = localStorage.getItem("vlm-text-collapsed") === "1";
  localStorage.setItem("vlm-text-collapsed", collapsed ? "0" : "1");
  applyTextCollapsed();
  syncOverlay();
}

function updateCoach() {
  const node = $("coach");
  if (!node) {
    return;
  }
  if (!state.document || $("viewer").hidden) {
    node.hidden = true;
    return;
  }
  const lists = state.fields.filter((field) => field.kind === "list");
  const scalars = state.fields.filter((field) => field.kind === "scalar");
  let key;
  if (!state.fields.length) {
    key = "coach.start";
  } else if (lists.some((field) => !(field.stopLabels || []).length)) {
    key = "coach.stop";
  } else if (scalars.some((field) => !(field.labels || []).length)) {
    key = "coach.labels";
  } else if (!state.extraction) {
    key = "coach.extract";
  } else if (state.extraction.pending.length || state.extraction.unmatched.length) {
    key = "coach.review";
  } else {
    key = "coach.done";
  }
  node.hidden = false;
  node.textContent = t(key);
}

function pageBlocks(page) {
  return state.document.blocks.filter((block) => block.page === page.index);
}

function drawBoxes(page) {
  syncOverlay();
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
  updateBlockStates();
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
  updateBlockStates();
}

function selectBlock(index) {
  state.selected = index;
  state.selectedBlock = pageBlocks(state.document.pages[state.page])[index] || null;
  updateBlockStates();
  const box = state.boxes.get(index);
  if (box) {
    box.scrollIntoView({ block: "nearest", inline: "nearest" });
  } else {
    const item = $("text-panel").querySelector(`[data-index="${index}"]`);
    if (item) {
      item.scrollIntoView({ block: "nearest" });
    }
  }
  updateSelection();
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
    syncOverlay();
    drawBoxes(page);
  };
  image.src = await loadPageImage(page);
  observePage();
  syncOverlay();
  drawBoxes(page);
  renderText(page);
  renderFields();
  updateSelection();
}

function showViewer() {
  $("home").hidden = true;
  $("viewer").hidden = false;
  applyTextCollapsed();
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
    state.stopSuggestions = suggestStops(payload.document.blocks);
    $("extract-summary").textContent = "";
    $("propose-status").textContent = "";
    showResult(null);
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
    state.stopSuggestions = suggestStops(state.document.blocks);
    $("propose-status").textContent = "";
    showResult(null);
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
    state.fields = parseSchema(schema);
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
    showResult(state.extraction);
  } catch (error) {
    state.extraction = null;
    showResult(null);
  }
}

let recentsCache = [];
let modelsCache = [];

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

async function loadModels() {
  if (!token()) {
    return;
  }
  try {
    const response = await api("/api/models");
    const payload = await response.json();
    modelsCache = payload.models || [];
    const select = $("propose-model");
    select.innerHTML = "";
    const present = modelsCache.filter((model) => model.present);
    for (const model of present) {
      const option = document.createElement("option");
      option.value = model.alias;
      option.textContent = `${model.alias} — ${model.label}`;
      select.appendChild(option);
    }
    if (!present.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = t("propose.noModels");
      select.appendChild(option);
    } else {
      const preferred =
        present.find((model) => model.default) ||
        present.find((model) => model.alias === "llama32-3b") ||
        present[0];
      select.value = preferred.alias;
    }
    refreshProposeButton();
  } catch (error) {
    // sin token o servidor no disponible: el health ya lo indica
  }
}

function refreshProposeButton() {
  const button = $("propose");
  if (!button) {
    return;
  }
  const present = modelsCache.filter((model) => model.present).length;
  button.disabled = present === 0;
  button.title = present ? t("propose.hint") : t("propose.noModels");
}

async function proposeContract() {
  clearError();
  if (!state.workspace) {
    return;
  }
  if (state.fields.length && !window.confirm(t("propose.replaceConfirm"))) {
    return;
  }
  const model = $("propose-model").value;
  if (!model) {
    showError(t("propose.noModels"));
    return;
  }
  const button = $("propose");
  button.disabled = true;
  button.textContent = t("propose.loading");
  $("propose-status").textContent = t("propose.loading");
  setStatus(t("propose.loading"));
  try {
    const response = await api(
      `/api/workspaces/${state.workspace.id}/propose`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      }
    );
    const payload = await response.json();
    state.fields = payload.fields || [];
    state.extraction = null;
    showResult(null);
    $("extract-summary").textContent = "";
    renderFields();
    $("propose-status").textContent = t("propose.done", { model: payload.model });
    setStatus(t("propose.done", { model: payload.model }));
  } catch (error) {
    setStatus(t("status.error"));
    showError(error);
    $("propose-status").textContent = "";
  } finally {
    button.textContent = t("propose.button");
    refreshProposeButton();
  }
}

function addField() {
  const index = state.fields.length + 1;
  state.fields.push({
    kind: "scalar",
    name: `campo_${index}`,
    type: "text",
    labels: [],
    source: "",
  });
  renderFields();
}

function addFieldFromBlock() {
  if (!state.selectedBlock) {
    return;
  }
  const index = state.fields.length + 1;
  state.fields.push({
    kind: "scalar",
    name: `campo_${index}`,
    type: "text",
    labels: [state.selectedBlock.text],
    source: "",
  });
  renderFields();
}

function addList() {
  const index = state.fields.length + 1;
  state.fields.push({
    kind: "list",
    name: `pedido_${index}`,
    roles: {
      text: "producto",
      quantity: "cantidad",
      number_right: "precio",
      observation: "",
    },
    startLabels: [],
    stopLabels: [],
  });
  renderFields();
}

function fieldStatus(field) {
  const result = state.extraction;
  if (!result) {
    return null;
  }
  if (result.matched.includes(field.name)) {
    if (field.kind === "list") {
      const items = Array.isArray(result.data[field.name])
        ? result.data[field.name]
        : [];
      return {
        kind: "ok",
        text: items.length
          ? t("list.count", { count: items.length })
          : t("list.empty"),
      };
    }
    const value = result.data[field.name];
    return { kind: "ok", text: value === null ? "ok" : String(value) };
  }
  if (result.pending.includes(field.name)) {
    return { kind: "pending", text: t("status.pending") };
  }
  return { kind: "missing", text: t("status.missing") };
}

function labelNode(title, control, hint) {
  const label = document.createElement("label");
  label.className = "field-label";
  const span = document.createElement("span");
  span.textContent = title;
  const hintNode = document.createElement("span");
  hintNode.className = "field-hint";
  hintNode.textContent = hint;
  label.append(span, control, hintNode);
  return label;
}

function roleRow(role, field) {
  const row = document.createElement("div");
  row.className = "role-row";
  const required = role === "text" || role === "number_right";
  const label = document.createElement("span");
  label.className = "role-label";
  label.textContent = `${t(`role.${role}`)}${required ? " *" : ""}`;
  label.title = required ? t("list.required") : "";
  const input = document.createElement("input");
  input.value = field.roles?.[role] || "";
  input.placeholder = t("list.property");
  input.addEventListener("input", () => {
    field.roles[role] = input.value.trim();
  });
  row.append(label, input);
  return row;
}

function labelListEditor(titleKey, hintKey, values, onChange, suggestions) {
  let current = values.slice();
  const wrap = document.createElement("div");
  wrap.className = "label-list";
  const title = document.createElement("span");
  title.className = "field-label-title";
  title.textContent = t(titleKey);
  const line = document.createElement("div");
  line.className = "label-line";
  const input = document.createElement("input");
  input.value = current.join(", ");
  input.placeholder = t("field.labels");
  input.addEventListener("input", () => {
    current = input.value
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    onChange(current);
  });
  const use = document.createElement("button");
  use.type = "button";
  use.textContent = t("list.useBlock");
  use.disabled = !state.selectedBlock;
  use.title = state.selectedBlock ? "" : t("field.assignHint");
  use.addEventListener("click", () => {
    if (!state.selectedBlock) {
      return;
    }
    if (!current.includes(state.selectedBlock.text)) {
      current = [...current, state.selectedBlock.text];
      input.value = current.join(", ");
      onChange(current);
    }
  });
  line.append(input, use);
  const hint = document.createElement("span");
  hint.className = "field-hint";
  hint.textContent = t(hintKey);
  wrap.append(title, line, hint);
  if (suggestions && suggestions.length) {
    const chipsTitle = document.createElement("span");
    chipsTitle.className = "chips-title";
    chipsTitle.textContent = t("list.suggestions");
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const suggestion of suggestions.slice(0, 6)) {
      if (current.includes(suggestion)) {
        continue;
      }
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = `+ ${suggestion}`;
      chip.addEventListener("click", () => {
        if (current.includes(suggestion)) {
          return;
        }
        current = [...current, suggestion];
        input.value = current.join(", ");
        onChange(current);
      });
      chips.appendChild(chip);
    }
    if (chips.childElementCount) {
      wrap.append(chipsTitle, chips);
    }
  }
  return wrap;
}

function previewTable(field, items) {
  const columns = [];
  if (field.roles?.text) {
    columns.push({ key: "text", label: t("role.text") });
  }
  if (field.roles?.quantity) {
    columns.push({ key: "quantity", label: t("role.quantity") });
  }
  if (field.roles?.number_right) {
    columns.push({ key: "price", label: t("role.number_right") });
  }
  if (field.roles?.observation) {
    columns.push({ key: "observation", label: t("role.observation") });
  }
  const wrapper = document.createElement("div");
  wrapper.className = "list-table-wrap";
  const table = document.createElement("table");
  table.className = "list-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const column of columns) {
    const th = document.createElement("th");
    th.textContent = column.label;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const item of items.slice(0, 8)) {
    const tr = document.createElement("tr");
    for (const column of columns) {
      const td = document.createElement("td");
      const value = item[column.key];
      td.textContent =
        value === null || value === undefined ? "—" : String(value);
      if (column.key === "price" && value === null) {
        td.className = "missing-price";
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrapper.appendChild(table);
  if (items.length > 8) {
    const more = document.createElement("p");
    more.className = "field-hint";
    more.textContent = t("list.previewMore", { count: items.length - 8 });
    wrapper.appendChild(more);
  }
  return wrapper;
}

function listTable(field) {
  const data = state.extraction?.data?.[field.name];
  if (!Array.isArray(data) || !data.length) {
    return null;
  }
  const columns = ROLE_ORDER.map((role) => ({
    role,
    prop: field.roles?.[role] || "",
  })).filter(({ prop }) => prop);
  const wrapper = document.createElement("div");
  wrapper.className = "list-table-wrap";
  const table = document.createElement("table");
  table.className = "list-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const { role } of columns) {
    const th = document.createElement("th");
    th.textContent = t(`role.${role}`);
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const item of data) {
    const tr = document.createElement("tr");
    for (const { prop } of columns) {
      const td = document.createElement("td");
      const value = item?.[prop];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrapper.appendChild(table);
  return wrapper;
}

function listCard(field, index) {
  const card = document.createElement("div");
  card.className = "field-card list-card";

  const head = document.createElement("div");
  head.className = "field-head";
  const name = document.createElement("input");
  name.value = field.name;
  name.placeholder = t("field.name");
  name.addEventListener("input", () => {
    field.name = name.value;
  });
  head.appendChild(labelNode(t("list.title"), name, t("list.nameHint")));
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = t("list.badge");
  head.appendChild(badge);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "danger";
  remove.textContent = "×";
  remove.title = t("list.remove");
  remove.addEventListener("click", () => {
    state.fields.splice(index, 1);
    renderFields();
  });
  head.appendChild(remove);

  const rolesTitle = document.createElement("p");
  rolesTitle.className = "field-label-title";
  rolesTitle.textContent = t("list.roles");
  const roles = document.createElement("div");
  roles.className = "role-grid";
  for (const role of ROLE_ORDER) {
    roles.appendChild(roleRow(role, field));
  }
  const rolesHint = document.createElement("p");
  rolesHint.className = "field-hint";
  rolesHint.textContent = t("list.rolesHint");

  const preview = document.createElement("div");
  preview.className = "list-preview-wrap";
  const refreshPreview = () => {
    preview.innerHTML = "";
    const result = previewItems(field);
    const count = result.items.length;
    const head = document.createElement("p");
    head.className = count > 0 ? "list-preview ok" : "list-preview";
    head.textContent =
      count > 0 ? t("list.preview", { count }) : t("list.previewNone");
    preview.appendChild(head);
    const hasResult =
      state.extraction && state.extraction.matched.includes(field.name);
    if (result.merged) {
      const warn = document.createElement("p");
      warn.className = "field-hint warn";
      warn.textContent = t("list.previewMerged");
      preview.appendChild(warn);
    } else if (result.aborted) {
      const warn = document.createElement("p");
      warn.className = "field-hint warn";
      warn.textContent = t("list.previewPending");
      preview.appendChild(warn);
    } else if (result.noPrice > 0) {
      const warn = document.createElement("p");
      warn.className = "field-hint warn";
      warn.textContent = t("list.previewNoPrice", { count: result.noPrice });
      preview.appendChild(warn);
    }
    if (count && !hasResult) {
      preview.appendChild(previewTable(field, result.items));
    }
  };

  const labels = document.createElement("div");
  labels.className = "label-lists";
  labels.appendChild(
    labelListEditor(
      "list.startLabels",
      "list.startHint",
      field.startLabels,
      (next) => {
        field.startLabels = next;
        refreshPreview();
        updateCoach();
        updateBlockStates();
      }
    )
  );
  const suggestions = (state.stopSuggestions || []).filter(
    (suggestion) => !(field.stopLabels || []).includes(suggestion)
  );
  labels.appendChild(
    labelListEditor(
      "list.stopLabels",
      "list.stopHint",
      field.stopLabels,
      (next) => {
        field.stopLabels = next;
        refreshPreview();
        updateCoach();
        updateBlockStates();
      },
      suggestions
    )
  );
  if (!field.stopLabels.length) {
    const warn = document.createElement("p");
    warn.className = "field-hint warn";
    warn.textContent = t("list.stopWarning");
    labels.appendChild(warn);
  }
  refreshPreview();

  const actions = document.createElement("div");
  actions.className = "field-actions";
  const status = fieldStatus(field);
  if (status) {
    const node = document.createElement("span");
    node.className = `field-status ${status.kind}`;
    node.textContent = status.text;
    actions.appendChild(node);
  }

  card.append(head, rolesTitle, roles, rolesHint, labels, preview, actions);
  const table = listTable(field);
  if (table) {
    card.appendChild(table);
  }
  return card;
}

function fieldCard(field, index) {
  const card = document.createElement("div");
  card.className = "field-card";

  const head = document.createElement("div");
  head.className = "field-head";

  const name = document.createElement("input");
  name.value = field.name;
  name.placeholder = t("field.name");
  name.addEventListener("input", () => {
    field.name = name.value;
  });
  head.appendChild(labelNode(t("field.nameLabel"), name, t("field.nameHint")));

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
  head.appendChild(labelNode(t("field.typeLabel"), type, t("field.typeHint")));

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "danger";
  remove.textContent = "×";
  remove.title = t("field.remove");
  remove.addEventListener("click", () => {
    state.fields.splice(index, 1);
    renderFields();
  });
  head.appendChild(remove);

  const body = document.createElement("div");
  body.className = "field-body";

  const labels = document.createElement("input");
  labels.value = field.labels.join(", ");
  labels.placeholder = t("field.labels");
  labels.addEventListener("input", () => {
    field.labels = labels.value
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    updateCoach();
    updateBlockStates();
  });
  body.appendChild(
    labelNode(t("field.labelsLabel"), labels, t("field.labelsHint"))
  );

  const sourceWrap = document.createElement("span");
  sourceWrap.className = "source-wrap";
  const source = document.createElement("select");
  const none = document.createElement("option");
  none.value = "";
  none.textContent = t("field.sourceNone");
  source.appendChild(none);
  for (const option of SOURCE_OPTIONS) {
    const node = document.createElement("option");
    node.value = option;
    node.textContent = t(`source.${option}`);
    source.appendChild(node);
  }
  const customOption = document.createElement("option");
  customOption.value = "__custom__";
  customOption.textContent = t("field.sourceCustom");
  source.appendChild(customOption);

  const known = SOURCE_OPTIONS.includes(field.source);
  source.value = field.source ? (known ? field.source : "__custom__") : "";
  const custom = document.createElement("input");
  custom.placeholder = t("field.customColumn");
  custom.value = known || !field.source ? "" : field.source;
  custom.disabled = source.value !== "__custom__";
  source.addEventListener("change", () => {
    if (source.value === "__custom__") {
      custom.disabled = false;
      field.source = custom.value.trim();
      custom.focus();
    } else {
      custom.disabled = true;
      custom.value = "";
      field.source = source.value;
    }
  });
  custom.addEventListener("input", () => {
    field.source = custom.value.trim();
  });
  sourceWrap.append(source, custom);
  body.appendChild(
    labelNode(t("field.sourceLabel"), sourceWrap, t("field.sourceHint"))
  );

  const actions = document.createElement("div");
  actions.className = "field-actions";

  const assign = document.createElement("button");
  assign.type = "button";
  assign.textContent = t("field.assign");
  assign.disabled = !state.selectedBlock;
  assign.title = state.selectedBlock ? "" : t("field.assignHint");
  assign.addEventListener("click", () => {
    if (!state.selectedBlock) {
      return;
    }
    if (!field.labels.includes(state.selectedBlock.text)) {
      field.labels.push(state.selectedBlock.text);
      labels.value = field.labels.join(", ");
    }
  });
  actions.appendChild(assign);

  const status = fieldStatus(field);
  if (status) {
    const node = document.createElement("span");
    node.className = `field-status ${status.kind}`;
    node.textContent = status.text;
    actions.appendChild(node);
  }

  card.append(head, body, actions);
  return card;
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
    container.appendChild(
      field.kind === "list" ? listCard(field, index) : fieldCard(field, index)
    );
  });
  updateSelection();
  updateCoach();
  updateBlockStates();
}

function parseSchema(schema) {
  const fields = [];
  for (const [name, node] of Object.entries(schema.properties || {})) {
    const declared = Array.isArray(node.type) ? node.type : [node.type];
    if (declared.includes("array") && node["x-item-columns"]) {
      const roles = { text: "", quantity: "", number_right: "", observation: "" };
      for (const [prop, role] of Object.entries(node["x-item-columns"])) {
        if (role in roles) {
          roles[role] = prop;
        }
      }
      fields.push({
        kind: "list",
        name,
        roles,
        startLabels: node["x-item-labels"] || [],
        stopLabels: node["x-stop-labels"] || [],
      });
    } else {
      const raw = Array.isArray(node.type)
        ? node.type.find((item) => item !== "null")
        : node.type;
      fields.push({
        kind: "scalar",
        name,
        type: !raw || raw === "string" ? "text" : raw,
        labels: node["x-labels"] || [],
        source: node["x-source"] || "",
      });
    }
  }
  return fields;
}

function buildSchema() {
  const properties = {};
  const names = new Set();
  for (const field of state.fields) {
    const name = field.name.trim();
    if (!name) {
      throw new Error(t("error.noName"));
    }
    if (!FIELD_NAME.test(name)) {
      throw new Error(t("error.invalidName"));
    }
    if (names.has(name)) {
      throw new Error(t("error.duplicate", { name }));
    }
    names.add(name);
    if (field.kind === "list") {
      const columns = {};
      const itemProperties = {};
      const required = [];
      const used = new Set();
      for (const role of ROLE_ORDER) {
        const prop = (field.roles?.[role] || "").trim();
        if (!prop) {
          if (ROLE_TYPES[role].required) {
            throw new Error(
              t("error.listRequiredRole", { role: t(`role.${role}`) })
            );
          }
          continue;
        }
        if (!FIELD_NAME.test(prop)) {
          throw new Error(t("error.invalidName"));
        }
        if (used.has(prop)) {
          throw new Error(t("error.listDuplicate", { name: prop }));
        }
        used.add(prop);
        columns[prop] = role;
        itemProperties[prop] = { type: ROLE_TYPES[role].type };
        if (ROLE_TYPES[role].required) {
          required.push(prop);
        }
      }
      if (required.length < 2) {
        throw new Error(t("error.listEmpty"));
      }
      properties[name] = {
        type: ["array", "null"],
        "x-item-columns": columns,
        "x-item-labels": field.startLabels || [],
        "x-stop-labels": field.stopLabels || [],
        items: {
          type: "object",
          required,
          properties: itemProperties,
          additionalProperties: false,
        },
      };
    } else {
      const type =
        field.type === "text" || field.type === "date" ? "string" : field.type;
      const node = { type: [type, "null"], "x-labels": field.labels || [] };
      if (field.source) {
        node["x-source"] = field.source;
      }
      properties[name] = node;
    }
  }
  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    properties,
  };
}

function showResult(extraction) {
  const panel = $("result-panel");
  const pre = $("result-json");
  if (!panel || !pre) {
    return;
  }
  if (!extraction) {
    panel.hidden = true;
    panel.open = false;
    pre.textContent = "";
    return;
  }
  panel.hidden = false;
  panel.open = true;
  pre.textContent = JSON.stringify(extraction.data, null, 2);
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
    showResult(payload.extraction);
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
  state.stopSuggestions = [];
  $("coach").hidden = true;
  $("page-image").src = "";
  $("boxes").innerHTML = "";
  $("text-panel").innerHTML = "";
  $("fields").innerHTML = "";
  $("extract-summary").textContent = "";
  $("propose-status").textContent = "";
  showResult(null);
  updateSelection();
  $("viewer").hidden = true;
  $("home").hidden = false;
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
  $("toggle-text").addEventListener("click", toggleText);
  $("add-field").addEventListener("click", addField);
  $("add-field-block").addEventListener("click", addFieldFromBlock);
  $("add-list").addEventListener("click", addList);
  $("action-new-field").addEventListener("click", () => {
    if (state.selectedBlock) {
      addFieldFromBlock();
    }
  });
  $("action-list-start").addEventListener("click", () => {
    const index = targetListIndex();
    if (index === null || !state.selectedBlock) {
      return;
    }
    const field = state.fields[index];
    field.startLabels = field.startLabels || [];
    if (!field.startLabels.includes(state.selectedBlock.text)) {
      field.startLabels.push(state.selectedBlock.text);
      renderFields();
    }
  });
  $("action-list-stop").addEventListener("click", () => {
    const index = targetListIndex();
    if (index === null || !state.selectedBlock) {
      return;
    }
    const field = state.fields[index];
    field.stopLabels = field.stopLabels || [];
    if (!field.stopLabels.includes(state.selectedBlock.text)) {
      field.stopLabels.push(state.selectedBlock.text);
      renderFields();
    }
  });
  $("action-clear").addEventListener("click", clearSelection);
  $("extract").addEventListener("click", extract);
  $("homologate").addEventListener("click", homologate);
  $("propose").addEventListener("click", proposeContract);
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

window.addEventListener("resize", syncOverlay);

wire();
loadLocale(detectLang()).then(() => {
  health();
  loadRecents();
  loadModels();
});
