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

function updateSelection() {
  const node = $("selection");
  if (!node) {
    return;
  }
  node.textContent = state.selectedBlock
    ? t("field.selected", { text: state.selectedBlock.text })
    : t("field.noSelection");
  const addFromBlock = $("add-field-block");
  if (addFromBlock) {
    addFromBlock.disabled = !state.selectedBlock;
  }
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

function labelListEditor(titleKey, hintKey, values, onChange) {
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
  return wrap;
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

  const labels = document.createElement("div");
  labels.className = "label-lists";
  labels.appendChild(
    labelListEditor("list.startLabels", "list.startHint", field.startLabels, (next) => {
      field.startLabels = next;
    })
  );
  labels.appendChild(
    labelListEditor("list.stopLabels", "list.stopHint", field.stopLabels, (next) => {
      field.stopLabels = next;
    })
  );
  if (!field.stopLabels.length) {
    const warn = document.createElement("p");
    warn.className = "field-hint warn";
    warn.textContent = t("list.stopWarning");
    labels.appendChild(warn);
  }

  const actions = document.createElement("div");
  actions.className = "field-actions";
  const status = fieldStatus(field);
  if (status) {
    const node = document.createElement("span");
    node.className = `field-status ${status.kind}`;
    node.textContent = status.text;
    actions.appendChild(node);
  }

  card.append(head, rolesTitle, roles, rolesHint, labels, actions);
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
  $("page-image").src = "";
  $("boxes").innerHTML = "";
  $("text-panel").innerHTML = "";
  $("fields").innerHTML = "";
  $("extract-summary").textContent = "";
  showResult(null);
  updateSelection();
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
  $("add-field-block").addEventListener("click", addFieldFromBlock);
  $("add-list").addEventListener("click", addList);
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

window.addEventListener("resize", syncOverlay);

wire();
loadLocale(detectLang()).then(() => {
  health();
  loadRecents();
});
