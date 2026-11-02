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

function token() {
  return sessionStorage.getItem("vlm-token") || "";
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
  $("page-image").src = await loadPageImage(page);
  drawBoxes(page);
  renderText(page);
  renderFields();
}

async function upload(file) {
  clearError();
  setStatus("procesando…");
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
    $("dropzone").hidden = true;
    $("viewer").hidden = false;
    await showPage(0);
    setStatus(`${payload.document.filename} · ${payload.document.pages.length} pág.`);
  } catch (error) {
    setStatus("error");
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
    return { kind: "pending", text: "pendiente" };
  }
  return { kind: "missing", text: "sin localizar" };
}

function renderFields() {
  const container = $("fields");
  container.innerHTML = "";
  if (!state.fields.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Añade un campo y asigna bloques de texto.";
    container.appendChild(empty);
    return;
  }
  state.fields.forEach((field, index) => {
    const row = document.createElement("div");
    row.className = "field-row";

    const name = document.createElement("input");
    name.value = field.name;
    name.placeholder = "nombre";
    name.addEventListener("input", () => {
      field.name = name.value;
    });
    row.appendChild(name);

    const type = document.createElement("select");
    for (const option of ["text", "number", "integer", "date"]) {
      const node = document.createElement("option");
      node.value = option;
      node.textContent = option;
      node.selected = field.type === option;
      type.appendChild(node);
    }
    type.addEventListener("change", () => {
      field.type = type.value;
    });
    row.appendChild(type);

    const labels = document.createElement("input");
    labels.value = field.labels.join(", ");
    labels.placeholder = "etiquetas (separadas por coma)";
    labels.addEventListener("input", () => {
      field.labels = labels.value
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    });
    row.appendChild(labels);

    const source = document.createElement("input");
    source.value = field.source;
    source.placeholder = "columna (opcional)";
    source.setAttribute("list", "sources");
    source.addEventListener("input", () => {
      field.source = source.value.trim();
    });
    row.appendChild(source);

    const assign = document.createElement("button");
    assign.type = "button";
    assign.textContent = "Asignar bloque";
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
    remove.title = "Eliminar campo";
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
      throw new Error("hay un campo sin nombre");
    }
    if (properties[name]) {
      throw new Error(`campo duplicado: ${name}`);
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
    showError("añade al menos un campo");
    return;
  }
  setStatus("extrayendo…");
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
    const { matched, pending, unmatched } = payload.extraction;
    $("extract-summary").textContent =
      `${matched.length} ok · ${pending.length} pendientes · ` +
      `${unmatched.length} sin localizar`;
    setStatus("extracción lista");
  } catch (error) {
    setStatus("error");
    showError(error);
  }
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
  setStatus("listo");
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
    setStatus("sin conexión");
  }
}

const fragment = new URLSearchParams(location.hash.slice(1));
const initialToken = fragment.get("token");
if (initialToken) {
  sessionStorage.setItem("vlm-token", initialToken);
  history.replaceState(null, "", location.pathname);
}

wire();
health();
