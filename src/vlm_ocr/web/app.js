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
  focusedList: null,
  zoom: 1,
  llmJob: null,
  llmController: null,
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
const COLUMN_TYPES = ["text", "number", "integer", "date"];

function schemaTypeForColumn(type) {
  if (type === "number") {
    return ["number", "null"];
  }
  if (type === "integer") {
    return ["integer", "null"];
  }
  return ["string", "null"];
}
let locale = {};
let resizeObserver = null;
let pageViewObserver = null;

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
  applyLayout();
  refreshProposeButton();
  renderTemplates(templatesCache);
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

function listRegion(field) {
  if (!state.document || !(field.startLabels || []).length) {
    return null;
  }
  const rows = documentRows(state.document.blocks);
  const dataRows = [];
  let counting = false;
  for (const row of rows) {
    if (!counting) {
      if (labelHit(row.blocks, field.startLabels)) {
        counting = true;
      }
      continue;
    }
    if (labelHit(row.blocks, field.stopLabels)) {
      break;
    }
    if (row.blocks.some((block) => (block.text || "").trim())) {
      dataRows.push(row);
    }
  }
  const blocks = dataRows
    .flatMap((row) => row.blocks)
    .filter((block) => block.box[2] > block.box[0]);
  if (!blocks.length) {
    return null;
  }
  const x0 = Math.min(...blocks.map((block) => block.box[0]));
  const x1 = Math.max(...blocks.map((block) => block.box[2]));
  const width = x1 - x0;
  if (width <= 0) {
    return null;
  }
  return { x0, x1, width, dataRows };
}

function previewColumns(field) {
  const empty = { items: [], noPrice: 0, merged: false, aborted: false };
  if (!state.document || !field.columns?.length) {
    return empty;
  }
  const region = listRegion(field);
  if (!region) {
    return empty;
  }
  const { x0, width, dataRows } = region;
  const items = [];
  for (const row of dataRows) {
    const cells = row.blocks.filter(
      (block) => (block.text || "").trim() && block.box[2] > block.box[0]
    );
    if (!cells.length) {
      continue;
    }
    const item = {};
    for (const column of field.columns) {
      const picked = cells
        .filter((block) => {
          const ratio = ((block.box[0] + block.box[2]) / 2 - x0) / width;
          return column.x0 <= ratio && ratio <= column.x1;
        })
        .sort((left, right) => left.box[0] - right.box[0]);
      const text = picked.map((block) => block.text.trim()).join(" ").trim();
      item[column.name] = text || null;
    }
    items.push(item);
  }
  return { items, noPrice: 0, merged: false, aborted: false };
}

function previewItems(field) {
  if (field.mode === "columns") {
    return previewColumns(field);
  }
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
  if (!image || !image.naturalWidth) {
    return;
  }
  const imageRect = image.getBoundingClientRect();
  const wrapRect = $("page-wrap").getBoundingClientRect();
  for (const id of ["boxes", "columns"]) {
    const overlay = $(id);
    if (!overlay) {
      continue;
    }
    overlay.style.left = `${imageRect.left - wrapRect.left}px`;
    overlay.style.top = `${imageRect.top - wrapRect.top}px`;
    overlay.style.width = `${imageRect.width}px`;
    overlay.style.height = `${imageRect.height}px`;
  }
}

function applyZoom() {
  const view = document.querySelector(".page-view");
  const image = $("page-image");
  if (!view || !image) {
    return;
  }
  const base = Math.max(200, view.getBoundingClientRect().width - 32);
  const width = Math.max(100, Math.round(base * state.zoom));
  image.style.width = `${width}px`;
  image.style.maxWidth = "none";
  const label = $("zoom-label");
  if (label) {
    label.textContent = `${Math.round(state.zoom * 100)}%`;
  }
  syncOverlay();
}

function setZoom(value) {
  state.zoom = Math.min(4, Math.max(0.25, Math.round(value * 4) / 4));
  applyZoom();
}

function observePageView() {
  const view = document.querySelector(".page-view");
  if (!view || !window.ResizeObserver) {
    return;
  }
  if (!pageViewObserver) {
    pageViewObserver = new ResizeObserver(() => applyZoom());
  }
  pageViewObserver.disconnect();
  pageViewObserver.observe(view);
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
  const focused =
    state.focusedList !== null ? state.fields[state.focusedList] : null;
  const list =
    focused && focused.kind === "list" ? listBlockIndices(focused) : null;
  const blocks = pageBlocks(state.document.pages[state.page]);
  for (const [index, element] of state.boxes.entries()) {
    const block = blocks[index];
    if (!block) {
      continue;
    }
    const reasons = assigned.get(normLabel(block.text));
    element.classList.toggle("selected", state.selected === index);
    element.classList.toggle("assigned", Boolean(reasons));
    element.classList.toggle("in-list", Boolean(list && list.items.has(block)));
    element.classList.toggle(
      "list-anchor",
      Boolean(list && list.anchors.has(block))
    );
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
    item.classList.toggle("in-list", Boolean(list && list.items.has(block)));
    item.classList.toggle(
      "list-anchor",
      Boolean(list && list.anchors.has(block))
    );
  }
  updateColumnsOverlay();
}

function updateColumnsOverlay() {
  const overlay = $("columns");
  if (!overlay) {
    return;
  }
  overlay.innerHTML = "";
  const focused =
    state.focusedList !== null ? state.fields[state.focusedList] : null;
  if (
    !focused ||
    focused.kind !== "list" ||
    focused.mode !== "columns" ||
    !state.document
  ) {
    return;
  }
  const region = listRegion(focused);
  const page = state.document.pages[state.page];
  if (!region || !page || !page.width || !page.height) {
    return;
  }
  const blocks = region.dataRows
    .flatMap((row) => row.blocks)
    .filter((block) => block.page === state.page && block.box[2] > block.box[0]);
  if (!blocks.length) {
    return;
  }
  const top = Math.min(...blocks.map((block) => block.box[1]));
  const bottom = Math.max(...blocks.map((block) => block.box[3]));
  for (const column of focused.columns || []) {
    const band = document.createElement("div");
    band.className = "column-band";
    const left = region.x0 + column.x0 * region.width;
    const right = region.x0 + column.x1 * region.width;
    band.style.left = `${(left / page.width) * 100}%`;
    band.style.width = `${((right - left) / page.width) * 100}%`;
    band.style.top = `${(top / page.height) * 100}%`;
    band.style.height = `${((bottom - top) / page.height) * 100}%`;
    const label = document.createElement("span");
    label.textContent = column.name;
    band.appendChild(label);
    overlay.appendChild(band);
  }
}

function storedPx(key, fallback) {
  const value = Number(localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function applyLayout() {
  const work = $("work");
  if (!work) {
    return;
  }
  const left = storedPx("vlm-left-w", 0);
  if (left > 0) {
    work.style.setProperty("--left-w", `${left}px`);
  } else {
    work.style.removeProperty("--left-w");
  }
  const textCollapsed = localStorage.getItem("vlm-text-collapsed") === "1";
  const pageCollapsed = localStorage.getItem("vlm-page-collapsed") === "1";
  work.classList.toggle("text-collapsed", textCollapsed);
  work.classList.toggle("page-collapsed", pageCollapsed);
  const textButton = $("toggle-text");
  if (textButton) {
    textButton.textContent = t(
      textCollapsed ? "viewer.showText" : "viewer.hideText"
    );
  }
  const pageButton = $("toggle-page");
  if (pageButton) {
    pageButton.textContent = t(
      pageCollapsed ? "viewer.showDocument" : "viewer.hideDocument"
    );
  }
}

const MIN_LEFT = 320;
const MIN_OPS = 360;

function startResize(event) {
  if (event.button !== undefined && event.button !== 0) {
    return;
  }
  event.preventDefault();
  const work = $("work");
  const move = (moveEvent) => {
    const rect = work.getBoundingClientRect();
    const max = Math.max(MIN_LEFT, rect.width - MIN_OPS - 5);
    const width = Math.min(
      max,
      Math.max(MIN_LEFT, moveEvent.clientX - rect.left)
    );
    work.style.setProperty("--left-w", `${Math.round(width)}px`);
    applyZoom();
  };
  const stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    localStorage.setItem("vlm-left-w", work.style.getPropertyValue("--left-w"));
    applyZoom();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop, { once: true });
}

function togglePage() {
  const collapsed = localStorage.getItem("vlm-page-collapsed") === "1";
  localStorage.setItem("vlm-page-collapsed", collapsed ? "0" : "1");
  applyLayout();
  applyZoom();
}

function toggleText() {
  const collapsed = localStorage.getItem("vlm-text-collapsed") === "1";
  localStorage.setItem("vlm-text-collapsed", collapsed ? "0" : "1");
  applyLayout();
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
  observePageView();
  applyZoom();
  syncOverlay();
  drawBoxes(page);
  renderText(page);
  renderFields();
  updateSelection();
}

function showViewer() {
  $("home").hidden = true;
  $("viewer").hidden = false;
  applyLayout();
  observePageView();
  setTimeout(applyZoom, 0);
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
    state.focusedList = null;
    state.extraction = null;
    state.zoom = 1;
    state.stopSuggestions = suggestStops(payload.document.blocks);
    $("extract-summary").textContent = "";
    $("llm-status").textContent = "";
    clearPrompt();
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
    state.focusedList = null;
    state.extraction = null;
    state.zoom = 1;
    state.stopSuggestions = suggestStops(state.document.blocks);
    $("llm-status").textContent = "";
    clearPrompt();
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
    state.focusedList = null;
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
let templatesCache = [];

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
    for (const model of modelsCache) {
      const option = document.createElement("option");
      option.value = model.alias;
      let text = `${model.alias} — ${model.label}`;
      if (model.remote) {
        text += ` (${t("llm.remote")})`;
      }
      if (!model.available) {
        text +=
          model.requires_key && model.key_env
            ? ` · ${t("llm.needsKey", { env: model.key_env })}`
            : ` · ${t("llm.unavailable")}`;
      }
      option.textContent = text;
      option.disabled = !model.available;
      select.appendChild(option);
    }
    if (!modelsCache.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = t("propose.noModels");
      select.appendChild(option);
    } else {
      const preferred =
        modelsCache.find((model) => model.default && model.available) ||
        modelsCache.find(
          (model) => model.alias === "llama32-3b" && model.available
        ) ||
        modelsCache.find((model) => model.available) ||
        modelsCache[0];
      select.value = preferred.alias;
    }
    refreshProposeButton();
    updateModelWarning();
  } catch (error) {
    // sin token o servidor no disponible: el health ya lo indica
  }
}

function selectedModel() {
  return modelsCache.find((model) => model.alias === $("propose-model").value);
}

function refreshProposeButton() {
  const button = $("propose");
  if (!button) {
    return;
  }
  const model = selectedModel();
  const usable = Boolean(model && model.available);
  button.disabled = !usable;
  button.title = usable ? t("propose.hint") : t("propose.noModels");
  const prompt = $("prompt-run");
  if (prompt) {
    prompt.disabled = !usable;
  }
}

function updateModelWarning() {
  const warning = $("model-warning");
  if (!warning) {
    return;
  }
  const model = selectedModel();
  if (model && model.remote) {
    warning.hidden = false;
    warning.textContent = t("llm.warningRemote", { model: model.alias });
  } else {
    warning.hidden = true;
    warning.textContent = "";
  }
}

function formatSeconds(ms) {
  return `${(ms / 1000).toFixed(1)} s`;
}

function usageParts(usage, label) {
  if (!usage) {
    return [];
  }
  const parts = [];
  if (usage.time_ms != null) {
    parts.push(`${label}: ${formatSeconds(usage.time_ms)}`);
  }
  if (usage.load_time_ms != null) {
    parts.push(`${t("llm.load")}: ${formatSeconds(usage.load_time_ms)}`);
  }
  if (usage.total_tokens != null) {
    parts.push(`${usage.total_tokens} tok`);
  }
  if (usage.tokens_per_second != null) {
    parts.push(`${usage.tokens_per_second} tok/s`);
  }
  return parts;
}

function showMetrics(parts) {
  const node = $("llm-metrics");
  if (!node) {
    return;
  }
  if (!parts || !parts.length) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.textContent = parts.join(" · ");
}

function setLlmBusy(busy) {
  for (const id of ["propose", "propose-analyze", "prompt-run"]) {
    const node = $(id);
    if (node) {
      node.disabled = busy;
    }
  }
  const spinner = $("llm-spinner");
  if (spinner) {
    spinner.hidden = !busy;
  }
  const cancel = $("llm-cancel");
  if (cancel) {
    cancel.hidden = !busy;
  }
  if (!busy) {
    state.llmJob = null;
    state.llmController = null;
    refreshProposeButton();
  }
}

function newJobId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isAbortError(error) {
  return Boolean(
    error &&
      (error.name === "AbortError" || String(error).toLowerCase().includes("abort"))
  );
}

async function cancelLlm() {
  const job = state.llmJob;
  if (!job) {
    return;
  }
  state.llmController?.abort();
  try {
    await api("/api/llm/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: job }),
    });
  } catch (error) {
    // La petición en curso puede haberse abortado ya.
  }
  $("llm-status").textContent = t("llm.cancelled");
  setStatus(t("llm.cancelled"));
  showMetrics([]);
  setLlmBusy(false);
}

async function requestPrompt(prompt, model) {
  const jobId = newJobId();
  const controller = new AbortController();
  state.llmJob = jobId;
  state.llmController = controller;
  const started = performance.now();
  const response = await api(`/api/workspaces/${state.workspace.id}/prompt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, model, job_id: jobId }),
    signal: controller.signal,
  });
  const payload = await response.json();
  payload.elapsed_ms = Math.round(performance.now() - started);
  return payload;
}

async function requestPropose(instructions, model) {
  const jobId = newJobId();
  const controller = new AbortController();
  state.llmJob = jobId;
  state.llmController = controller;
  const body = { model, job_id: jobId };
  if (instructions && instructions.trim()) {
    body.instructions = instructions.trim();
  }
  const started = performance.now();
  const response = await api(`/api/workspaces/${state.workspace.id}/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  });
  const payload = await response.json();
  payload.elapsed_ms = Math.round(performance.now() - started);
  return payload;
}

function applyProposal(payload) {
  state.fields = payload.fields || [];
  state.focusedList = null;
  state.extraction = null;
  showResult(null);
  $("extract-summary").textContent = "";
  showTemplateUsed(null);
  renderFields();
}

function showAnswer(text) {
  const answer = $("prompt-answer");
  if (!answer) {
    return;
  }
  answer.hidden = false;
  answer.textContent = text;
  const use = $("prompt-use");
  if (use) {
    use.hidden = false;
  }
}

async function proposeContract(extraInstructions = "") {
  const extra =
    typeof extraInstructions === "string" ? extraInstructions.trim() : "";
  clearError();
  if (!state.workspace) {
    return;
  }
  if (state.fields.length && !window.confirm(t("propose.replaceConfirm"))) {
    return;
  }
  const model = selectedModel();
  if (!model || !model.available) {
    showError(t("propose.noModels"));
    return;
  }
  setLlmBusy(true);
  $("llm-status").textContent = t("propose.loading");
  showMetrics([]);
  setStatus(t("propose.loading"));
  try {
    const payload = await requestPropose(extra, model.alias);
    applyProposal(payload);
    $("llm-status").textContent = t("propose.done", { model: payload.model });
    setStatus(t("propose.done", { model: payload.model }));
    showMetrics(usageParts(payload.usage, t("llm.time")));
  } catch (error) {
    if (isAbortError(error)) {
      $("llm-status").textContent = t("llm.cancelled");
      return;
    }
    setStatus(t("status.error"));
    showError(error);
    $("llm-status").textContent = "";
  } finally {
    setLlmBusy(false);
  }
}

async function runPrompt() {
  clearError();
  if (!state.workspace) {
    return;
  }
  const prompt = $("prompt-text").value.trim();
  if (!prompt) {
    showError(t("prompt.empty"));
    return;
  }
  const model = selectedModel();
  if (!model || !model.available) {
    showError(t("propose.noModels"));
    return;
  }
  setLlmBusy(true);
  $("llm-status").textContent = t("prompt.loading");
  $("prompt-answer").hidden = true;
  const use = $("prompt-use");
  if (use) {
    use.hidden = true;
  }
  showMetrics([]);
  setStatus(t("prompt.loading"));
  try {
    const payload = await requestPrompt(prompt, model.alias);
    showAnswer(payload.answer);
    $("llm-status").textContent = t("prompt.done", { model: payload.model });
    setStatus(t("prompt.done", { model: payload.model }));
    showMetrics(usageParts(payload.usage, t("llm.time")));
  } catch (error) {
    if (isAbortError(error)) {
      $("llm-status").textContent = t("llm.cancelled");
      return;
    }
    setStatus(t("status.error"));
    showError(error);
    $("llm-status").textContent = "";
  } finally {
    setLlmBusy(false);
  }
}

async function proposeWithAnalysis() {
  clearError();
  if (!state.workspace) {
    return;
  }
  if (state.fields.length && !window.confirm(t("propose.replaceConfirm"))) {
    return;
  }
  const model = selectedModel();
  if (!model || !model.available) {
    showError(t("propose.noModels"));
    return;
  }
  const user = $("prompt-text").value.trim();
  setLlmBusy(true);
  $("llm-status").textContent = t("llm.analysisLoading");
  $("prompt-answer").hidden = true;
  const use = $("prompt-use");
  if (use) {
    use.hidden = true;
  }
  showMetrics([]);
  setStatus(t("llm.analysisLoading"));
  try {
    const analysis = await requestPrompt(t("llm.analysisPrompt"), model.alias);
    showAnswer(analysis.answer);
    $("llm-status").textContent = t("llm.proposingAfterAnalysis");
    setStatus(t("llm.proposingAfterAnalysis"));
    const instructions = `${t("llm.analysisPrefix")}\n${analysis.answer}\n\n${user}`;
    const proposal = await requestPropose(instructions, model.alias);
    applyProposal(proposal);
    $("llm-status").textContent = t("propose.done", { model: proposal.model });
    setStatus(t("propose.done", { model: proposal.model }));
    showMetrics([
      ...usageParts(analysis.usage, t("llm.analysisTime")),
      ...usageParts(proposal.usage, t("llm.proposeTime")),
    ]);
  } catch (error) {
    if (isAbortError(error)) {
      $("llm-status").textContent = t("llm.cancelled");
      return;
    }
    setStatus(t("status.error"));
    showError(error);
    $("llm-status").textContent = "";
  } finally {
    setLlmBusy(false);
  }
}

function useAnswerAsInstructions() {
  const answer = $("prompt-answer");
  const text = $("prompt-text");
  if (!answer || !text) {
    return;
  }
  text.value = answer.textContent || "";
  text.focus();
}

function clearPrompt() {
  const text = $("prompt-text");
  if (text) {
    text.value = "";
  }
  const answer = $("prompt-answer");
  if (answer) {
    answer.hidden = true;
    answer.textContent = "";
  }
  const use = $("prompt-use");
  if (use) {
    use.hidden = true;
  }
  const status = $("llm-status");
  if (status) {
    status.textContent = "";
  }
  showMetrics([]);
}

function removeField(index) {
  if (state.focusedList === index) {
    state.focusedList = null;
  } else if (state.focusedList !== null && state.focusedList > index) {
    state.focusedList -= 1;
  }
  state.fields.splice(index, 1);
  renderFields();
}

function listBlockIndices(field) {
  const items = new Set();
  const anchors = new Set();
  if (!state.document) {
    return { items, anchors };
  }
  const rows = documentRows(state.document.blocks);
  const hasStart = (field.startLabels || []).length > 0;
  let counting = false;
  for (const row of rows) {
    if (!counting) {
      if (hasStart) {
        if (labelHit(row.blocks, field.startLabels)) {
          counting = true;
          for (const block of row.blocks) {
            anchors.add(block);
          }
        }
        continue;
      }
      const parsed = parseListRow(row, Boolean(field.roles?.quantity));
      if (parsed.kind === "item") {
        counting = true;
        for (const block of row.blocks) {
          items.add(block);
        }
      }
      continue;
    }
    if (labelHit(row.blocks, field.stopLabels)) {
      for (const block of row.blocks) {
        anchors.add(block);
      }
      break;
    }
    for (const block of row.blocks) {
      items.add(block);
    }
  }
  return { items, anchors };
}

function firstListPage(field) {
  const { items, anchors } = listBlockIndices(field);
  const pages = [...items, ...anchors].map((block) => block.page);
  return pages.length ? Math.min(...pages) : null;
}

function showTemplateUsed(template) {
  const node = $("template-info");
  if (!node) {
    return;
  }
  if (template && template.found) {
    const digest = String(template.digest || "").slice(0, 12) || "—";
    const score =
      template.score != null ? Number(template.score).toFixed(2) : "—";
    const coverage =
      template.coverage != null
        ? `${Math.round(Number(template.coverage) * 100)}%`
        : "—";
    node.hidden = false;
    node.textContent = t("template.used", { digest, score, coverage });
  } else {
    node.hidden = true;
    node.textContent = "";
  }
}

function showTemplateSaved(digest) {
  const node = $("template-info");
  if (!node) {
    return;
  }
  const short = String(digest || "").slice(0, 12) || "—";
  node.hidden = false;
  node.textContent = t("template.saved", { digest: short });
}

async function importContract(file) {
  clearError();
  try {
    const text = await file.text();
    const schema = JSON.parse(text);
    if (
      !schema ||
      typeof schema !== "object" ||
      !schema.properties ||
      typeof schema.properties !== "object"
    ) {
      throw new Error(t("contract.importError"));
    }
    const nested = Object.values(schema.properties).some(
      (node) => node && typeof node === "object" && node.properties
    );
    if (nested) {
      throw new Error(t("contract.importNested"));
    }
    state.fields = parseSchema(schema);
    if (!state.fields.length) {
      throw new Error(t("contract.importError"));
    }
    state.focusedList = null;
    state.extraction = null;
    showResult(null);
    showTemplateUsed(null);
    $("extract-summary").textContent = "";
    renderFields();
    setStatus(t("contract.imported"));
  } catch (error) {
    showError(error);
  }
}

async function loadTemplates() {
  if (!token()) {
    return;
  }
  try {
    const response = await api("/api/templates");
    const payload = await response.json();
    templatesCache = payload.templates || [];
    renderTemplates(templatesCache);
  } catch (error) {
    // sin token o servidor no disponible
  }
}

function renderTemplates(rows) {
  const list = $("templates-list");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  if (!rows || !rows.length) {
    const empty = document.createElement("p");
    empty.className = "field-hint";
    empty.textContent = t("template.empty");
    list.appendChild(empty);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "template-row";
    const label = document.createElement("span");
    const digest = String(row.digest || "").slice(0, 12);
    label.textContent = `${digest} · v${row.version} · ${t("template.fields", {
      fields: row.fields_mapped,
      items: row.items_mapped,
    })}`;
    label.title = `contrato ${String(row.contract_hash || "").slice(0, 12)} · ${
      row.updated_at || ""
    }`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "×";
    remove.title = t("template.delete");
    remove.addEventListener("click", () => dropTemplate(row.digest));
    item.append(label, remove);
    list.appendChild(item);
  }
}

async function dropTemplate(digest) {
  if (!window.confirm(t("template.deleteConfirm"))) {
    return;
  }
  try {
    await api(`/api/templates/${digest}`, { method: "DELETE" });
    await loadTemplates();
    setStatus(t("template.delete"));
  } catch (error) {
    showError(error);
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
    mode: "roles",
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
  if (field.mode === "columns") {
    for (const column of field.columns || []) {
      columns.push({ key: column.name, label: column.name });
    }
  } else if (field.roles?.text) {
    columns.push({ key: "text", label: t("role.text") });
  }
  if (field.mode !== "columns" && field.roles?.quantity) {
    columns.push({ key: "quantity", label: t("role.quantity") });
  }
  if (field.mode !== "columns" && field.roles?.number_right) {
    columns.push({ key: "price", label: t("role.number_right") });
  }
  if (field.mode !== "columns" && field.roles?.observation) {
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
  const columns =
    field.mode === "columns"
      ? (field.columns || []).map((column) => ({
          key: column.name,
          label: column.name,
        }))
      : ROLE_ORDER.map((role) => ({
          key: field.roles?.[role] || "",
          label: t(`role.${role}`),
        })).filter(({ key }) => key);
  const wrapper = document.createElement("div");
  wrapper.className = "list-table-wrap";
  const table = document.createElement("table");
  table.className = "list-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const { label } of columns) {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const item of data) {
    const tr = document.createElement("tr");
    for (const { key } of columns) {
      const td = document.createElement("td");
      const value = item?.[key];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrapper.appendChild(table);
  return wrapper;
}

function slugifyColumn(text) {
  return (text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
}

function parseColumnNumber(text) {
  const cleaned = (text || "").replace(/[$€£¥]/g, "").replace(/\s/g, "");
  if (!/^[-+]?\d+([.,]\d+)*[.,]?\d*$/.test(cleaned) || !/\d/.test(cleaned)) {
    return null;
  }
  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");
  let normalized = cleaned;
  if (lastComma > lastDot) {
    normalized = cleaned.replace(/\./g, "").replace(",", ".");
  } else {
    normalized = cleaned.replace(/,/g, "");
  }
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

function looksLikeDate(text) {
  return /^\d{1,4}[\/.\-]\d{1,2}[\/.\-]\d{1,4}$/.test((text || "").trim());
}

function inferColumnType(dataRows, x0, width, left, right) {
  const values = [];
  for (const row of dataRows) {
    for (const block of row.blocks) {
      if (!block.text.trim() || block.box[2] <= block.box[0]) {
        continue;
      }
      const ratio = ((block.box[0] + block.box[2]) / 2 - x0) / width;
      if (left <= ratio && ratio <= right) {
        values.push(block.text.trim());
      }
    }
  }
  if (!values.length) {
    return "text";
  }
  const numbers = values.map(parseColumnNumber);
  if (numbers.every((value) => value !== null && Number.isFinite(value))) {
    return numbers.every((value) => Number.isInteger(value)) ? "integer" : "number";
  }
  if (values.every(looksLikeDate)) {
    return "date";
  }
  return "text";
}

function detectColumnsFromDocument(field) {
  if (!state.document) {
    return null;
  }
  const rows = documentRows(state.document.blocks);
  let search = 0;
  if ((field.startLabels || []).length) {
    const index = rows.findIndex((row) => labelHit(row.blocks, field.startLabels));
    if (index < 0) {
      return null;
    }
    search = index + 1;
  }
  let firstData = -1;
  for (let index = search; index < rows.length; index++) {
    if (labelHit(rows[index].blocks, field.stopLabels)) {
      break;
    }
    const cells = rows[index].blocks.filter((block) => block.text.trim());
    if (
      cells.length >= 2 &&
      cells.some((block) => looksLikeNumber(block.text)) &&
      cells.some((block) => !looksLikeNumber(block.text))
    ) {
      firstData = index;
      break;
    }
  }
  if (firstData < 0) {
    return null;
  }
  let headerIndex = -1;
  let best = 0;
  for (let index = search; index < firstData; index++) {
    const cells = rows[index].blocks.filter((block) => block.text.trim());
    if (cells.length > best) {
      best = cells.length;
      headerIndex = index;
    }
  }
  if (headerIndex < 0 && firstData > 0) {
    headerIndex = firstData - 1;
  }
  if (headerIndex < 0) {
    return null;
  }
  const headerCells = rows[headerIndex].blocks
    .filter((block) => block.text.trim() && block.box[2] > block.box[0])
    .sort((left, right) => left.box[0] - right.box[0]);
  if (headerCells.length < 2) {
    return null;
  }
  const dataRows = [];
  for (let index = firstData; index < rows.length; index++) {
    if (labelHit(rows[index].blocks, field.stopLabels)) {
      break;
    }
    if (rows[index].blocks.some((block) => block.text.trim())) {
      dataRows.push(rows[index]);
    }
  }
  if (!dataRows.length) {
    return null;
  }
  const region = dataRows
    .flatMap((row) => row.blocks)
    .filter((block) => block.box[2] > block.box[0]);
  if (!region.length) {
    return null;
  }
  const x0 = Math.min(...region.map((block) => block.box[0]));
  const x1 = Math.max(...region.map((block) => block.box[2]));
  const width = x1 - x0;
  if (width <= 0) {
    return null;
  }
  const columns = headerCells
    .map((cell, index) => {
      const left = Math.max(0, Math.min(1, (cell.box[0] - x0) / width));
      const right = Math.max(0, Math.min(1, (cell.box[2] - x0) / width));
      const start = Math.min(left, right);
      const finish = Math.max(left, right);
      const name = slugifyColumn(cell.text) || `columna_${index + 1}`;
      return {
        name,
        x0: Number(start.toFixed(4)),
        x1: Number(finish.toFixed(4)),
        type: inferColumnType(dataRows, x0, width, start, finish),
        required: true,
      };
    })
    .filter((column) => column.x1 > column.x0);
  if (!columns.length) {
    return null;
  }
  return {
    columns,
    startLabels: [headerCells[0].text.trim()],
  };
}

function addColumnFromBlock(field) {
  const block = state.selectedBlock;
  if (!block) {
    showError(t("list.columnPickBlock"));
    return;
  }
  const region = listRegion(field);
  if (!region) {
    showError(t("list.columnsNeedRegion"));
    return;
  }
  const left = Math.max(
    0,
    Math.min(1, (block.box[0] - region.x0) / region.width)
  );
  const right = Math.max(
    0,
    Math.min(1, (block.box[2] - region.x0) / region.width)
  );
  const x0 = Math.min(left, right);
  const x1 = Math.max(left, right);
  field.columns = field.columns || [];
  field.columns.push({
    name: slugifyColumn(block.text) || `columna_${field.columns.length + 1}`,
    x0: Number(x0.toFixed(4)),
    x1: Number(x1.toFixed(4)),
    type: inferColumnType(region.dataRows, region.x0, region.width, x0, x1),
    required: true,
  });
  renderFields();
}

function columnsEditor(field, refreshPreview) {
  const wrap = document.createElement("div");
  wrap.className = "columns-editor";
  if (!field.columns || !field.columns.length) {
    const empty = document.createElement("p");
    empty.className = "field-hint warn";
    empty.textContent = t("list.columnsEmpty");
    wrap.appendChild(empty);
  }
  (field.columns || []).forEach((column, columnIndex) => {
    const row = document.createElement("div");
    row.className = "column-row";

    const name = document.createElement("input");
    name.value = column.name;
    name.placeholder = t("list.columnName");
    name.addEventListener("input", () => {
      column.name = name.value;
    });
    name.addEventListener("change", () => {
      refreshPreview();
      updateBlockStates();
    });
    row.appendChild(name);

    const type = document.createElement("select");
    for (const option of COLUMN_TYPES) {
      const node = document.createElement("option");
      node.value = option;
      node.textContent = t(`type.${option}`);
      node.selected = column.type === option;
      type.appendChild(node);
    }
    type.addEventListener("change", () => {
      column.type = type.value;
      refreshPreview();
    });
    row.appendChild(type);

    const x0 = document.createElement("input");
    x0.type = "number";
    x0.step = "0.01";
    x0.min = "0";
    x0.max = "1";
    x0.value = String(column.x0);
    x0.title = "x0";
    const x1 = document.createElement("input");
    x1.type = "number";
    x1.step = "0.01";
    x1.min = "0";
    x1.max = "1";
    x1.value = String(column.x1);
    x1.title = "x1";
    for (const input of [x0, x1]) {
      input.addEventListener("change", () => {
        column.x0 = Number(x0.value);
        column.x1 = Number(x1.value);
        refreshPreview();
        updateBlockStates();
      });
    }
    const range = document.createElement("span");
    range.className = "column-range";
    range.append(x0, document.createTextNode("–"), x1);
    row.appendChild(range);

    const required = document.createElement("label");
    required.className = "column-check";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = column.required !== false;
    check.addEventListener("change", () => {
      column.required = check.checked;
    });
    required.append(check, document.createTextNode(t("list.columnRequired")));
    row.appendChild(required);

    const useBlock = document.createElement("button");
    useBlock.type = "button";
    useBlock.textContent = t("list.columnUseBlock");
    useBlock.disabled = !state.selectedBlock;
    useBlock.title = state.selectedBlock ? "" : t("list.columnPickBlock");
    useBlock.addEventListener("click", () => {
      const block = state.selectedBlock;
      const region = listRegion(field);
      if (!block || !region) {
        return;
      }
      const left = Math.max(
        0,
        Math.min(1, (block.box[0] - region.x0) / region.width)
      );
      const right = Math.max(
        0,
        Math.min(1, (block.box[2] - region.x0) / region.width)
      );
      column.x0 = Number(Math.min(left, right).toFixed(4));
      column.x1 = Number(Math.max(left, right).toFixed(4));
      refreshPreview();
      renderFields();
    });
    row.appendChild(useBlock);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "×";
    remove.title = t("list.removeColumn");
    remove.addEventListener("click", () => {
      field.columns.splice(columnIndex, 1);
      renderFields();
    });
    row.appendChild(remove);

    wrap.appendChild(row);
  });
  const fromBlock = document.createElement("button");
  fromBlock.type = "button";
  fromBlock.textContent = t("list.columnFromBlock");
  fromBlock.disabled = !state.selectedBlock;
  fromBlock.title = state.selectedBlock ? "" : t("list.columnPickBlock");
  fromBlock.addEventListener("click", () => addColumnFromBlock(field));
  wrap.appendChild(fromBlock);

  const add = document.createElement("button");
  add.type = "button";
  add.textContent = t("list.addColumn");
  add.addEventListener("click", () => {
    field.columns = field.columns || [];
    const last = field.columns[field.columns.length - 1];
    const start = last ? Math.min(0.99, Number(last.x1)) : 0;
    let end = Math.min(1, Number((start + 0.2).toFixed(2)));
    if (end <= start) {
      end = Math.min(1, start + 0.05);
    }
    field.columns.push({
      name: `columna_${field.columns.length + 1}`,
      x0: start,
      x1: end,
      type: "text",
      required: true,
    });
    renderFields();
  });
  wrap.appendChild(add);
  return wrap;
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
    removeField(index);
  });
  head.appendChild(remove);

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

  const isColumns = field.mode === "columns";
  let modeNodes;
  if (isColumns) {
    const title = document.createElement("p");
    title.className = "field-label-title";
    title.textContent = t("list.columnsTitle");
    const hint = document.createElement("p");
    hint.className = "field-hint";
    hint.textContent = t("list.columnsHint");
    modeNodes = [title, columnsEditor(field, refreshPreview), hint];
  } else {
    const title = document.createElement("p");
    title.className = "field-label-title";
    title.textContent = t("list.roles");
    const roles = document.createElement("div");
    roles.className = "role-grid";
    for (const role of ROLE_ORDER) {
      roles.appendChild(roleRow(role, field));
    }
    const hint = document.createElement("p");
    hint.className = "field-hint";
    hint.textContent = t("list.rolesHint");
    modeNodes = [title, roles, hint];
  }

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
  const focus = document.createElement("button");
  focus.type = "button";
  focus.textContent = t(
    state.focusedList === index ? "list.hideInPhoto" : "list.showInPhoto"
  );
  focus.addEventListener("click", () => {
    if (state.focusedList === index) {
      state.focusedList = null;
      updateBlockStates();
      renderFields();
      return;
    }
    state.focusedList = index;
    const page = firstListPage(field);
    if (page !== null && page !== state.page) {
      showPage(page);
    } else {
      updateBlockStates();
      renderFields();
    }
  });
  actions.appendChild(focus);

  const modeButton = document.createElement("button");
  modeButton.type = "button";
  modeButton.textContent = t(
    isColumns ? "list.useRoles" : "list.detectColumns"
  );
  modeButton.addEventListener("click", () => {
    if (isColumns) {
      field.mode = "roles";
      field.roles = {
        text: "producto",
        quantity: "cantidad",
        number_right: "precio",
        observation: "",
      };
      renderFields();
      return;
    }
    const detected = detectColumnsFromDocument(field);
    field.mode = "columns";
    if (detected) {
      field.columns = detected.columns;
      field.startLabels = detected.startLabels;
    } else {
      field.columns = field.columns || [];
      showError(t("list.detectColumnsError"));
    }
    renderFields();
  });
  actions.appendChild(modeButton);

  const status = fieldStatus(field);
  if (status) {
    const node = document.createElement("span");
    node.className = `field-status ${status.kind}`;
    node.textContent = status.text;
    actions.appendChild(node);
  }

  card.append(head, ...modeNodes, labels, preview, actions);
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
    removeField(index);
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
      const entries = Object.entries(node["x-item-columns"]);
      const specs = entries.filter(
        ([, value]) => value && typeof value === "object"
      );
      if (specs.length) {
        const columns = specs
          .map(([prop, value]) => ({
            name: prop,
            x0: Number(value.x0 ?? 0),
            x1: Number(value.x1 ?? 1),
            type: COLUMN_TYPES.includes(value.type) ? value.type : "text",
            required: value.required !== false,
          }))
          .sort((left, right) => left.x0 - right.x0);
        fields.push({
          kind: "list",
          mode: "columns",
          name,
          columns,
          startLabels: node["x-item-labels"] || [],
          stopLabels: node["x-stop-labels"] || [],
        });
      } else {
        const roles = {
          text: "",
          quantity: "",
          number_right: "",
          observation: "",
        };
        for (const [prop, role] of entries) {
          if (role in roles) {
            roles[role] = prop;
          }
        }
        fields.push({
          kind: "list",
          mode: "roles",
          name,
          roles,
          startLabels: node["x-item-labels"] || [],
          stopLabels: node["x-stop-labels"] || [],
        });
      }
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
      if (field.mode === "columns") {
        if (!(field.startLabels || []).length) {
          throw new Error(t("error.listColumnsStart"));
        }
        const columns = {};
        const itemProperties = {};
        const required = [];
        const used = new Set();
        for (const column of field.columns || []) {
          const prop = (column.name || "").trim();
          if (!prop) {
            throw new Error(t("error.noName"));
          }
          if (!FIELD_NAME.test(prop)) {
            throw new Error(t("error.invalidName"));
          }
          if (used.has(prop)) {
            throw new Error(t("error.listDuplicate", { name: prop }));
          }
          used.add(prop);
          const x0 = Number(column.x0);
          const x1 = Number(column.x1);
          if (
            !Number.isFinite(x0) ||
            !Number.isFinite(x1) ||
            x0 < 0 ||
            x1 > 1 ||
            x0 >= x1
          ) {
            throw new Error(t("error.columnRange", { name: prop }));
          }
          const type = COLUMN_TYPES.includes(column.type)
            ? column.type
            : "text";
          columns[prop] = {
            x0: Number(x0.toFixed(4)),
            x1: Number(x1.toFixed(4)),
            type,
            required: column.required !== false,
          };
          itemProperties[prop] = { type: schemaTypeForColumn(type) };
          if (column.required !== false) {
            required.push(prop);
          }
        }
        if (!Object.keys(columns).length) {
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
        continue;
      }
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
    showTemplateUsed(payload.template);
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
      const digest = String(payload.digest || "").slice(0, 12) || "—";
      setStatus(t("template.saved", { digest }));
      showTemplateSaved(payload.digest);
      const panel = $("templates-panel");
      if (panel) {
        panel.open = true;
      }
      await loadTemplates();
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
  state.focusedList = null;
  state.extraction = null;
  state.zoom = 1;
  state.stopSuggestions = [];
  $("coach").hidden = true;
  $("page-image").src = "";
  $("boxes").innerHTML = "";
  $("text-panel").innerHTML = "";
  $("fields").innerHTML = "";
  $("extract-summary").textContent = "";
  $("llm-status").textContent = "";
  clearPrompt();
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
  $("toggle-page").addEventListener("click", togglePage);
  $("toggle-text").addEventListener("click", toggleText);
  $("prompt-run").addEventListener("click", runPrompt);
  $("prompt-use").addEventListener("click", useAnswerAsInstructions);
  $("propose-analyze").addEventListener("click", proposeWithAnalysis);
  $("llm-cancel").addEventListener("click", cancelLlm);
  $("propose-model").addEventListener("change", () => {
    refreshProposeButton();
    updateModelWarning();
  });
  const resizer = $("resize-page-ops");
  resizer.addEventListener("pointerdown", (event) => startResize(event));
  resizer.addEventListener("dblclick", () => {
    localStorage.removeItem("vlm-left-w");
    applyLayout();
    applyZoom();
  });
  $("zoom-out").addEventListener("click", () => setZoom(state.zoom - 0.25));
  $("zoom-in").addEventListener("click", () => setZoom(state.zoom + 0.25));
  $("zoom-reset").addEventListener("click", () => setZoom(1));
  $("add-field").addEventListener("click", addField);
  $("add-field-block").addEventListener("click", addFieldFromBlock);
  $("add-list").addEventListener("click", addList);
  $("import-contract").addEventListener("click", () =>
    $("contract-file").click()
  );
  $("contract-file").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (file) {
      importContract(file);
    }
    event.target.value = "";
  });
  $("templates-refresh").addEventListener("click", loadTemplates);
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
  $("propose").addEventListener("click", () =>
    proposeContract($("prompt-text").value)
  );
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
  loadTemplates();
});
