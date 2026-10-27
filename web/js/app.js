import { Viewer, rampCss } from "./viewer.js";
import { ResidualChart } from "./charts.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const STEP_META = {
  geometry: { n: 1, title: "Geometría", sub: "Define el dominio de cálculo y revisa los patches." },
  mesh: { n: 2, title: "Mallado", sub: "Elige la resolución y genera la malla del volumen." },
  physics: { n: 3, title: "Física", sub: "Configura el solver, el fluido y las condiciones de contorno." },
  run: { n: 4, title: "Simulación", sub: "Lanza OpenFOAM y sigue la convergencia en directo." },
  results: { n: 5, title: "Resultados", sub: "Explora campos, cortes y la evolución temporal." }
};

const PRESET_ICONS = { cavity: "cube", duct: "layers", cylinder: "grid", stl: "upload" };
const FIELD_OPTIONS = [
  { id: "p", label: "Presión" },
  { id: "U_mag", label: "|U|" },
  { id: "U_x", label: "Ux" },
  { id: "U_y", label: "Uy" }
];

const state = {
  data: null,
  step: "geometry",
  preview: null,
  meshPreview: null,
  geomSig: "",
  meshSig: "",
  job: null,
  jobCursor: 0,
  lastJobLine: "",
  pollTimer: null,
  chart: null,
  viewer: null,
  resultSeq: 0,
  result: { field: "U_mag", mode: "slice", axis: "z", position: null, time: null, colormap: "turbo" },
  resultPayload: null,
  playing: false,
  playTimer: null,
  meshTimer: null,
  physicsTimer: null,
  modalOpen: false,
  busy: false
};

/* ------------------------------------------------------------------ utilities */

function project() {
  return state.data?.project || null;
}

function presetMeta(id) {
  return (state.data?.presets || []).find((p) => p.id === id) || null;
}

function solverLabel(solver) {
  return solver === "simpleFoam" ? "simpleFoam · estacionario" : "icoFoam · transitorio";
}

function fmt(value, digits = 3) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs >= 100000 || abs < 0.0005)) return n.toExponential(2);
  return Number(n.toPrecision(digits)).toString();
}

function fmtInt(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("es-ES");
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function icon(name) {
  return `<svg class="icon"><use href="#i-${name}"></use></svg>`;
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function toast(message, type = "info", title = "") {
  const root = $("#toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icons = { ok: "check", warn: "warning", err: "warning", info: "info" };
  el.innerHTML = `${icon(icons[type] || "info")}<div>${title ? `<strong>${esc(title)}</strong><br>` : ""}${esc(message)}</div>`;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add("hide");
    setTimeout(() => el.remove(), 260);
  }, type === "err" ? 7000 : 4300);
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(body?.error || body || `Error HTTP ${res.status}`);
  }
  return body;
}

function markSaving() {
  const el = $("#saved-indicator");
  el.textContent = "guardando…";
  el.classList.add("saving");
  clearTimeout(markSaving._t);
  markSaving._t = setTimeout(() => {
    el.textContent = "guardado";
    el.classList.remove("saving");
  }, 900);
}

function runtimeAvailable() {
  return !!state.data?.runtime?.selected?.available;
}

function currentRuntime() {
  return state.data?.runtime?.selected || { available: false, label: "Sin motor", version: "" };
}

/* ------------------------------------------------------------------ boot */

async function init() {
  state.viewer = new Viewer($("#viewer-canvas"), $("#viewport"), $("#viewer-labels"));
  state.chart = new ResidualChart($("#residual-chart"), $("#chart-empty"));
  bindGlobal();
  try {
    await refreshState();
    if (!project()) {
      hideBoot();
      openNewProject();
      return;
    }
    const stage = ["geometry", "mesh", "physics", "run", "results"].includes(project().stage) ? project().stage : "geometry";
    state.step = stage === "results" && !project().has_results ? "geometry" : stage;
    await loadGeometryPreview();
    renderChrome();
    await selectStep(state.step, { persist: false });
    await resumeRunningJob();
    hideBoot();
  } catch (exc) {
    hideBoot();
    toast(exc.message || String(exc), "err", "No se pudo iniciar");
    console.error(exc);
  }
}

function hideBoot() {
  $("#boot").classList.add("done");
  $("#app").classList.remove("is-hidden");
  setTimeout(() => $("#boot").remove(), 600);
}

async function refreshState() {
  state.data = await api("/api/state");
  renderChrome();
}

/* ------------------------------------------------------------------ chrome */

function renderChrome() {
  renderTopbar();
  renderSteps();
  renderStatus();
  renderHud();
  renderInspector();
  updateDock();
  const lastRun = project()?.last_run;
  const series = lastRun?.series?.length ? lastRun.series : state.job?.status === "running" ? state.job.residuals || [] : [];
  state.chart.setData(series);
}

function renderHud() {
  const p = project();
  const kicker = $("#hud-kicker");
  const title = $("#hud-title");
  const sub = $("#hud-sub");
  const badges = $("#hud-badges");
  if (!p) {
    kicker.textContent = "BANCO DE TRABAJO";
    title.textContent = "FileGenFOAM Studio";
    sub.textContent = "Crea un proyecto para comenzar";
    badges.innerHTML = "";
    return;
  }
  const dims = `${fmt(p.geometry.length, 3)} × ${fmt(p.geometry.height, 3)} × ${fmt(p.geometry.depth, 3)} m`;
  const cells = p.mesh?.cell_count;
  const rt = currentRuntime();
  if (state.step === "results" && p.has_results) {
    const payload = state.resultPayload;
    kicker.textContent = "RESULTADOS";
    title.textContent = payload?.field_label || "Resultados";
    sub.textContent = payload
      ? `t = ${fmt(payload.time, 5)} s · ${state.result.mode === "slice" ? `corte ${state.result.axis.toUpperCase()}` : "superficie exterior"} · ${fmtInt(payload.point_count)} puntos`
      : "Cargando campo…";
    badges.innerHTML = `
      <span class="hud-badge ok">${icon("chart")} ${esc(p.physics.solver)}</span>
      <span class="hud-badge">${icon("grid")} ${cells ? fmtInt(cells) : "—"} celdas</span>`;
  } else if (state.step === "run") {
    kicker.textContent = "SIMULACIÓN";
    title.textContent = state.job?.status === "running" ? "Solver en marcha" : "Listo para ejecutar";
    sub.textContent = `${solverLabel(p.physics.solver)} · ${cells ? fmtInt(cells) : "sin malla"} celdas · ${rt.available ? rt.label : "sin motor"}`;
    badges.innerHTML = `
      <span class="hud-badge ${rt.available ? "ok" : "warn"}">${icon("terminal")} ${esc(rt.available ? rt.version || rt.label : "runtime pendiente")}</span>
      <span class="hud-badge">${icon("grid")} ${cells ? fmtInt(cells) : "—"} celdas</span>`;
  } else if (state.step === "physics") {
    kicker.textContent = "FÍSICA";
    const fluidLabel = state.data?.fluids?.[p.physics.fluid]?.label || p.physics.fluid;
    title.textContent = `${p.physics.solver} · ${fluidLabel}`;
    const re = reynolds(p);
    sub.textContent = `ν = ${fmt(p.physics.nu, 4)} m²/s${re ? ` · Re ≈ ${fmtInt(re)}` : ""} · ${p.physics.boundaries.length} patches`;
    badges.innerHTML = `
      <span class="hud-badge">${icon("sliders")} ${p.physics.solver === "simpleFoam" ? "estacionario" : "transitorio"}</span>
      <span class="hud-badge">${icon("layers")} laminar</span>`;
  } else if (state.step === "mesh") {
    kicker.textContent = "MALLADO";
    title.textContent = cells ? `${fmtInt(cells)} celdas · ${p.mesh_method}` : `${p.mesh_method} · malla pendiente`;
    sub.textContent = `${dims} · tamaño base ${fmt(p.mesh.base_size, 4)} m · ${p.mesh.patches?.length || p.physics.boundaries.length} patches`;
    badges.innerHTML = `
      <span class="hud-badge ${p.mesh?.quality?.ok ? "ok" : ""}">${icon("grid")} ${p.mesh?.quality?.ok ? "Mesh OK" : "sin verificar"}</span>
      <span class="hud-badge">${icon("layers")} ${p.mesh_method === "blockMesh" ? "hexaedros" : "gmsh + foam"}</span>`;
  } else {
    kicker.textContent = "GEOMETRÍA";
    title.textContent = p.name;
    sub.textContent = `${dims} · ${p.physics.boundaries.length} patches · ${p.preset}`;
    const is2d = p.physics.boundaries.some((b) => b.kind === "empty");
    badges.innerHTML = `
      <span class="hud-badge">${icon("cube")} ${is2d ? "caso 2D" : "caso 3D"}</span>
      <span class="hud-badge">${icon("grid")} ${cells ? fmtInt(cells) : "sin malla"}</span>`;
  }
  renderViewerMode();
}

function reynolds(p) {
  const nu = Number(p.physics.nu);
  if (!Number.isFinite(nu) || nu <= 0) return null;
  const inlet = p.physics.boundaries?.find((b) => b.kind === "inlet");
  const moving = p.physics.boundaries?.find((b) => b.kind === "movingWall");
  const inletSpeed = inlet ? Math.hypot(...(inlet.velocity || [0, 0, 0])) : 0;
  const movingSpeed = Math.abs(Number(moving?.velocity?.[0] || 0));
  const speed = inletSpeed || movingSpeed || Number(p.physics.inlet_speed || 0) || 1;
  const length = p.geometry.kind === "cylinder" ? p.geometry.diameter : p.geometry.height || p.geometry.length;
  return (speed * length) / nu;
}

function renderViewerMode() {
  const p = project();
  const el = $("#viewer-mode");
  if (!el || !p) return;
  if (state.job?.status === "running") {
    const last = state.job.residuals?.slice(-1)[0];
    const time = last?.time != null ? ` · t = ${fmt(last.time, 4)}` : "";
    el.textContent = `${state.job.label} · ${Math.round((state.job.progress || 0) * 100)}%${time}`;
  } else if (state.step === "results" && state.resultPayload) {
    el.textContent = `${state.resultPayload.field_label} · ${state.result.mode === "slice" ? `corte ${state.result.axis.toUpperCase()}` : "superficie"} · t = ${fmt(state.resultPayload.time, 5)} s`;
  } else if (state.step === "mesh" && p.has_mesh) {
    el.textContent = `Malla ${p.mesh_method} · ${fmtInt(p.mesh.cell_count)} celdas`;
  } else if (["physics", "run"].includes(state.step) && p.has_mesh) {
    el.textContent = `Geometría + malla · ${fmtInt(p.mesh.cell_count)} celdas`;
  } else {
    el.textContent = "Previsualización de geometría";
  }
}

function renderTopbar() {
  const p = project();
  const rt = currentRuntime();
  if (p) {
    $("#project-name").textContent = p.name;
    const preset = presetMeta(p.preset);
    const bits = [preset?.short || p.preset, solverLabel(p.physics.solver)];
    if (p.mesh?.cell_count) bits.push(`${fmtInt(p.mesh.cell_count)} celdas`);
    $("#project-sub").textContent = bits.join(" · ");
    $("#saved-indicator").textContent = "guardado";
    $("#saved-indicator").classList.remove("saving");
  } else {
    $("#project-name").textContent = "Sin proyecto";
    $("#project-sub").textContent = "Crea uno para comenzar";
  }
  $("#runtime-pill").classList.toggle("missing", !rt.available);
  $("#runtime-pill-text").textContent = rt.available ? `${rt.label}${rt.version ? " · " + rt.version : ""}` : "Configurar motor";
  $("#runtime-label").textContent = rt.available ? rt.label : "Sin motor CFD";
  $("#runtime-detail").textContent = rt.available ? rt.detail : "Instala BlueCFD-Core o configura WSL";
  $("#runtime-version").textContent = rt.available ? `OpenFOAM ${rt.version || "?"}` : "no detectado";
  $("#runtime-dot").className = `status-dot ${rt.available ? "" : "error"}`;
  const quick = $("#quick-run");
  const running = state.job?.status === "running";
  quick.innerHTML = running
    ? `${icon("stop")}<span>Detener simulación</span>`
    : `${icon("play")}<span>Ejecutar simulación</span>`;
  quick.classList.toggle("btn-danger", running);
  quick.classList.toggle("btn-primary", !running);
  quick.disabled = !running && (!p || !rt.available);
}

function renderSteps() {
  const p = project();
  const done = {
    geometry: !!p,
    mesh: !!p?.has_mesh,
    physics: !!p,
    run: p?.last_run?.status === "completed",
    results: !!p?.has_results
  };
  let completed = 0;
  $$(".step").forEach((el) => {
    const step = el.dataset.step;
    el.classList.toggle("active", step === state.step);
    el.classList.toggle("completed", !!done[step] && step !== state.step);
    if (done[step]) completed += 1;
  });
  $("#workflow-progress").textContent = `${completed} / 5`;
  if (p?.has_mesh) {
    $("#step-mesh-sub").textContent = `${fmtInt(p.mesh.cell_count || 0)} celdas · lista`;
  } else if (p) {
    $("#step-mesh-sub").textContent = p.mesh_method === "blockMesh" ? "blockMesh estructurado" : "gmsh no estructurado";
  }
}

function renderStatus() {
  const p = project();
  const rt = currentRuntime();
  $("#status-runtime").textContent = rt.available ? `${rt.label} ${rt.version || ""}`.trim() : "Sin motor CFD";
  $("#status-cells").textContent = p?.has_mesh ? `${fmtInt(p.mesh.cell_count)} celdas` : "Sin malla";
  $("#status-case").textContent = p?.case_path || "—";
  $("#status-message").textContent = state.job?.status === "running" ? state.job.label : "Listo";
  $("#status-case").title = p?.case_path || "";
}

/* ------------------------------------------------------------------ navigation */

async function selectStep(step, options = {}) {
  if (!project() || !STEP_META[step]) return;
  if (state.playing && step !== "results") {
    state.playing = false;
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
  state.step = step;
  if (step !== "results") {
    $("#colorbar").classList.add("is-hidden");
    state.viewer?.clearResults();
  }
  renderSteps();
  renderHud();
  renderInspector();
  await updateViewerForStep();
  if (options.persist !== false) {
    api("/api/project/update", { method: "POST", body: { stage: step } }).then(markSaving).catch(() => {});
  }
}

async function updateViewerForStep() {
  const p = project();
  if (!state.viewer || !p) return;
  if (!state.preview) await loadGeometryPreview();
  const sig = JSON.stringify(p.geometry);
  if (sig !== state.geomSig || !state.viewer.geometryLoaded) {
    state.viewer.setGeometry(state.preview);
    state.geomSig = sig;
  }
  if (stepUsesMesh() && p.has_mesh) {
    await ensureMeshPreview(p);
    state.viewer.setMesh(state.meshPreview);
  } else {
    state.viewer.setMesh(null);
  }
  if (state.step === "results" && p.has_results) {
    state.viewer.setMode("results");
    await loadResults({ resetTime: state.result.time == null });
  } else {
    state.viewer.clearResults();
    state.viewer.setMode(state.step === "geometry" ? "geometry" : "mesh");
  }
}

function stepUsesMesh() {
  return ["mesh", "physics", "run"].includes(state.step);
}

async function loadGeometryPreview() {
  const data = await api("/api/geometry/preview");
  state.preview = data;
  return data;
}

async function ensureMeshPreview(p = project()) {
  if (!p?.has_mesh) {
    state.meshPreview = null;
    state.meshSig = "";
    return null;
  }
  const sig = JSON.stringify([p.geometry, p.mesh.base_size, p.mesh.generated_at]);
  if (state.meshPreview && sig === state.meshSig) return state.meshPreview;
  const data = await api("/api/geometry/preview?mesh=1");
  state.meshPreview = data;
  state.meshSig = sig;
  return data;
}

/* ------------------------------------------------------------------ inspector dispatch */

function renderInspector() {
  const p = project();
  const meta = STEP_META[state.step];
  $("#inspector-kicker").textContent = `PASO ${meta.n} DE 5`;
  $("#inspector-title").textContent = meta.title;
  $("#inspector-sub").textContent = meta.sub;
  const body = $("#inspector-body");
  const foot = $("#inspector-foot");
  if (!p) {
    body.innerHTML = `<div class="empty-state">${icon("cube")}<strong>Sin proyecto</strong><p>Crea un proyecto guiado para empezar.</p><button class="btn btn-primary" data-action="new-project">Nuevo proyecto</button></div>`;
    foot.innerHTML = "";
    bindInspector();
    return;
  }
  if (state.step === "geometry") {
    body.innerHTML = geometryHtml(p);
    foot.innerHTML = `<button class="btn btn-primary btn-wide btn-lg" data-action="next-mesh">Continuar al mallado ${icon("chevron")}</button>`;
  } else if (state.step === "mesh") {
    body.innerHTML = meshHtml(p);
    foot.innerHTML = `
      <button class="btn btn-secondary btn-sm" data-action="next-physics" ${p.has_mesh ? "" : "disabled"}>Continuar</button>
      <button class="btn btn-primary btn-wide btn-lg" data-action="generate-mesh">${icon("grid")} Generar malla</button>`;
    foot.style.display = "grid";
    foot.style.gridTemplateColumns = "auto 1fr";
    foot.style.gap = "8px";
  } else if (state.step === "physics") {
    body.innerHTML = physicsHtml(p);
    foot.innerHTML = `<button class="btn btn-primary btn-wide btn-lg" data-action="next-run">Continuar a simulación ${icon("chevron")}</button>`;
  } else if (state.step === "run") {
    body.innerHTML = runHtml(p);
    foot.innerHTML = runFooterHtml(p);
    foot.style.display = "grid";
    foot.style.gridTemplateColumns = "1fr 1fr";
    foot.style.gap = "8px";
  } else {
    body.innerHTML = resultsHtml(p);
    foot.innerHTML = `
      <button class="btn btn-secondary btn-sm" data-action="open-case">${icon("folder")} Abrir caso</button>
      <button class="btn btn-primary btn-wide" data-action="export-png" ${p.has_results ? "" : "disabled"}>${icon("download")} Exportar PNG</button>`;
    foot.style.display = "grid";
    foot.style.gridTemplateColumns = "auto 1fr";
    foot.style.gap = "8px";
  }
  if (state.step !== "mesh" && state.step !== "run" && state.step !== "results") {
    foot.style.display = "";
    foot.style.gridTemplateColumns = "";
  }
  bindInspector();
}

/* ------------------------------------------------------------------ geometry panel */

function geometryHtml(p) {
  const g = p.geometry;
  const preset = presetMeta(p.preset);
  const isStl = g.kind === "stl";
  const dimFields = [
    ["length", "Longitud X", g.length],
    ["height", "Altura Y", g.height],
    ["depth", "Profundidad Z", g.depth]
  ];
  return `
    <div class="section">
      <div class="section-title">Plantilla <span>modelo base</span></div>
      <div class="preset-row active">
        <span class="preset-icon">${icon(PRESET_ICONS[p.preset] || "cube")}</span>
        <span class="preset-copy"><strong>${esc(preset?.label || p.preset)}</strong><small>${esc(preset?.description || "")}</small></span>
      </div>
      <button class="btn btn-secondary btn-sm btn-wide" style="margin-top:7px" data-action="change-preset">${icon("refresh")} Cambiar plantilla</button>
    </div>

    <div class="section">
      <div class="section-title">Dimensiones <span>metros</span></div>
      <div class="grid-3">
        ${dimFields.map(([key, label, value]) => `
          <div class="field"><label>${label}</label>
            <input class="input" type="number" min="0.0001" step="0.01" value="${fmt(value, 6)}" data-geom="${key}">
          </div>`).join("")}
      </div>
      ${g.kind === "cylinder" ? `
        <div class="grid-3" style="margin-top:9px">
          <div class="field"><label>Diámetro</label><input class="input" type="number" min="0.001" step="0.005" value="${fmt(g.diameter, 6)}" data-geom="diameter"></div>
          <div class="field"><label>Centro X</label><input class="input" type="number" step="0.01" value="${fmt(g.center_x, 6)}" data-geom="center_x"></div>
          <div class="field"><label>Centro Y</label><input class="input" type="number" step="0.01" value="${fmt(g.center_y, 6)}" data-geom="center_y"></div>
        </div>` : ""}
      ${isStl ? stlHtml(p) : ""}
      <p class="inline-note">La geometría se aplica al cambiar un valor. Si ya existe una malla, se eliminará junto con los resultados para evitar casos inconsistentes.</p>
    </div>

    <div class="section">
      <div class="section-title">Patches <span>${p.physics.boundaries.length} superficies</span></div>
      <div class="patch-list">
        ${p.physics.boundaries.map((b) => `
          <div class="patch-row">
            <span class="patch-dot" style="background:${patchColor(b.kind)}"></span>
            <span class="patch-name">${esc(b.name)}</span>
            <span class="patch-kind">${esc(kindLabel(b.kind))}</span>
          </div>`).join("")}
      </div>
    </div>

    <div class="section">
      <div class="callout">${icon("info")}<div><strong>Flujo de trabajo:</strong> revisa las dimensiones y los patches antes de mallar. Los nombres de patch se usan en las condiciones de contorno y en los resultados.</div></div>
    </div>`;
}

function stlHtml(p) {
  const file = p.geometry.stl_file ? p.geometry.stl_file.split("/").pop() : null;
  return `
    <div class="field" style="margin-top:10px">
      <label>Modelo STL</label>
      <div class="file-drop" id="stl-drop">
        ${icon("upload")}
        <strong>${file ? esc(file) : "Arrastra un STL o haz clic"}</strong>
        <small>${file ? "Haz clic para reemplazarlo" : "ASCII o binario · hasta 80 MB"}</small>
        <input type="file" id="stl-input" accept=".stl" hidden>
      </div>
      <p class="inline-note">El mallado de STL es experimental en esta versión; la previsualización 3D ya está disponible.</p>
    </div>`;
}

function patchColor(kind) {
  return { inlet: "#4cc9f0", outlet: "#f4a261", movingWall: "#7bdcb5", wall: "#96a7bd", empty: "#5d6b82", symmetry: "#b39ddb" }[kind] || "#96a7bd";
}

function kindLabel(kind) {
  return { inlet: "inlet", outlet: "outlet", wall: "wall", movingWall: "moving wall", empty: "empty", symmetry: "symmetry" }[kind] || kind;
}

/* ------------------------------------------------------------------ mesh panel */

function meshHtml(p) {
  const method = p.mesh_method === "blockMesh" ? "blockMesh" : "gmsh";
  const quality = p.mesh?.quality || {};
  const hasMesh = p.has_mesh;
  const sizes = meshSizes(p);
  const base = p.mesh.base_size;
  const closest = sizes.reduce((acc, cur, i) => (Math.abs(cur - base) < Math.abs(sizes[acc] - base) ? i : acc), 0);
  const estimate = estimateCells(p, base);
  return `
    <div class="section">
      <div class="section-title">Mallador <span>automático</span></div>
      <div class="card">
        <div class="card-head">
          <div><strong>${method === "blockMesh" ? "blockMesh estructurado" : "gmsh no estructurado"}</strong>
          <small>${method === "blockMesh" ? "Hexaedros alineados · rápido y robusto para dominios rectangulares." : "Hexaedros con refinamiento local alrededor del obstáculo; conversión con gmshToFoam."}</small></div>
          <span class="chip ${hasMesh ? "ok" : ""}">${hasMesh ? "malla lista" : "pendiente"}</span>
        </div>
        <div class="stat-grid" style="margin-top:9px">
          <div class="stat"><small>Celdas estimadas</small><strong>${fmtInt(estimate)}</strong></div>
          <div class="stat"><small>Tamaño base</small><strong>${fmt(base, 4)} <em>m</em></strong></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Resolución <span>tamaño de elemento</span></div>
      <div class="segmented tight" style="margin-bottom:9px">
        ${["Gruesa", "Media", "Fina"].map((label, i) => `<button class="${i === closest ? "active" : ""}" data-mesh-preset="${i}">${label}</button>`).join("")}
      </div>
      <div class="field">
        <label>Tamaño base <em>metros</em></label>
        <div class="input-group"><input class="input" id="mesh-base" type="number" min="0.0005" step="0.0005" value="${fmt(base, 5)}"><span class="suffix">m</span></div>
      </div>
      ${p.geometry.kind === "cylinder" ? `
        <div class="field"><label>Refinamiento junto al cilindro <em>×</em></label>
          <input class="input" id="mesh-refine" type="number" min="1" max="6" step="0.1" value="${fmt(p.mesh.refine_obstacle, 2)}"></div>` : ""}
      <p class="inline-note">La malla actual tiene ${hasMesh ? `${fmtInt(p.mesh.cell_count)} celdas` : "todavía no se ha generado"}. La generación reemplaza la malla y borra resultados anteriores.</p>
    </div>

    ${hasMesh ? `
    <div class="section">
      <div class="section-title">Calidad <span>checkMesh</span></div>
      <div class="stat-grid">
        <div class="stat"><small>Celdas</small><strong>${fmtInt(p.mesh.cell_count)}</strong></div>
        <div class="stat"><small>Nodos</small><strong>${fmtInt(p.mesh.nodes)}</strong></div>
        <div class="stat"><small>Aspect ratio</small><strong>${quality.max_aspect_ratio != null ? fmt(quality.max_aspect_ratio, 2) : "—"}</strong></div>
        <div class="stat"><small>Skewness</small><strong>${quality.max_skewness != null ? fmt(quality.max_skewness, 2) : "—"}</strong></div>
      </div>
      <div class="chip-row" style="margin-top:8px">
        <span class="chip ${quality.ok ? "ok" : "warn"}">${quality.ok ? "Mesh OK" : "revisar calidad"}</span>
        ${(p.patches || []).map((patch) => `<span class="chip">${esc(patch.name)} · ${patch.type}</span>`).join("")}
      </div>
    </div>` : ""}

    <div class="section">
      <div class="callout">${icon("info")}<div>${method === "blockMesh" ? "blockMesh genera una malla estructurada de hexaedros. Para cavidad y conducto es la opción más robusta." : "gmsh construye el contorno, refina cerca del cilindro y gmshToFoam lo convierte a OpenFOAM. La malla es hexaédrica en este caso."}</div></div>
    </div>
    ${jobCardHtml("mesh")}`;
}

function meshSizes(p) {
  const g = p.geometry;
  const area = g.kind === "cylinder"
    ? Math.max(1e-6, g.length * g.height - Math.PI * Math.pow(g.diameter / 2, 2))
    : Math.max(1e-6, g.length * g.height);
  return [Math.sqrt(area / 2500), Math.sqrt(area / 10000), Math.sqrt(area / 40000)];
}

function estimateCells(p, base) {
  const g = p.geometry;
  if (p.mesh_method === "blockMesh") {
    const nx = Math.max(2, Math.round(g.length / base));
    const ny = Math.max(2, Math.round(g.height / base));
    return nx * ny;
  }
  const area = Math.max(1e-6, g.length * g.height - Math.PI * Math.pow(g.diameter / 2, 2));
  return Math.round(area / (base * base));
}

/* ------------------------------------------------------------------ physics panel */

function physicsHtml(p) {
  const fluid = p.physics.fluid;
  const isSteady = p.physics.solver === "simpleFoam";
  return `
    <div class="section">
      <div class="section-title">Régimen</div>
      <div class="segmented" data-solver-group>
        <button class="${!isSteady ? "active" : ""}" data-solver="icoFoam">Transitorio</button>
        <button class="${isSteady ? "active" : ""}" data-solver="simpleFoam">Estacionario</button>
      </div>
      <p class="inline-note">${!isSteady ? "icoFoam resuelve el flujo transitorio con PISO. Adecuado para cavidades y estelas." : "simpleFoam busca el régimen permanente con SIMPLE. Adecuado para conductos y flujos internos."}</p>
    </div>

    <div class="section">
      <div class="section-title">Fluido <span>incompresible</span></div>
      <div class="field"><label>Material</label>
        <select class="select" id="fluid-select">
          ${Object.entries(state.data.fluids).map(([id, f]) => `<option value="${id}" ${id === fluid ? "selected" : ""}>${esc(f.label)}</option>`).join("")}
        </select>
      </div>
      <div class="grid-2">
        <div class="field"><label>Densidad</label><div class="input-group"><input class="input" id="physics-density" type="number" step="1" value="${fmt(p.physics.density, 6)}"><span class="suffix">kg/m³</span></div></div>
        <div class="field"><label>Viscosidad ν</label><div class="input-group"><input class="input" id="physics-nu" type="number" step="0.000001" value="${fmt(p.physics.nu, 6)}"><span class="suffix">m²/s</span></div></div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Condiciones de contorno <span>${p.physics.boundaries.length} patches</span></div>
      <div class="patch-list">
        ${p.physics.boundaries.map((b) => boundaryHtml(b)).join("")}
      </div>
      <p class="inline-note">Los cambios se guardan automáticamente. Los patches <code>empty</code> definen el caso 2D.</p>
    </div>

    <div class="section">
      <div class="card">
        <div class="card-head"><div><strong>Turbulencia</strong><small>El MVP resuelve flujo laminar. k-ω SST llegará en la siguiente iteración.</small></div><span class="chip">laminar</span></div>
      </div>
    </div>
    ${jobCardHtml("run")}`;
}

function boundaryHtml(b) {
  const showVelocity = ["inlet", "movingWall"].includes(b.kind);
  const showPressure = b.kind === "outlet";
  return `
    <div class="patch-row" data-boundary="${esc(b.name)}">
      <span class="patch-dot" style="background:${patchColor(b.kind)}"></span>
      <div style="min-width:0">
        <div class="patch-name">${esc(b.name)}</div>
        <select class="bc-kind" data-bc-kind="${esc(b.name)}" style="margin-top:3px">
          ${["inlet", "outlet", "wall", "movingWall", "empty", "symmetry"].map((k) => `<option value="${k}" ${k === b.kind ? "selected" : ""}>${kindLabel(k)}</option>`).join("")}
        </select>
      </div>
      <div class="patch-values">
        ${showVelocity ? `
          <input type="number" step="any" title="Ux" data-bc-vel="${esc(b.name)}" data-axis="0" value="${fmt(b.velocity?.[0] ?? 0, 5)}">
          <input type="number" step="any" title="Uy" data-bc-vel="${esc(b.name)}" data-axis="1" value="${fmt(b.velocity?.[1] ?? 0, 5)}">
          <input type="number" step="any" title="Uz" data-bc-vel="${esc(b.name)}" data-axis="2" value="${fmt(b.velocity?.[2] ?? 0, 5)}">` : ""}
        ${showPressure ? `<input type="number" step="any" title="p" data-bc-p="${esc(b.name)}" value="${fmt(b.pressure ?? 0, 5)}">` : ""}
        ${!showVelocity && !showPressure ? `<span class="patch-kind" style="padding-right:3px">sin valores</span>` : ""}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ run panel */

function runHtml(p) {
  const rt = currentRuntime();
  const isSteady = p.physics.solver === "simpleFoam";
  const running = state.job?.status === "running";
  const last = p.last_run || {};
  const hasResults = p.has_results;
  return `
    <div class="section">
      <div class="section-title">Motor CFD</div>
      <div class="card">
        <div class="card-head">
          <div><strong>${esc(rt.label || "Sin motor")}</strong><small>${esc(rt.detail || "Configura BlueCFD-Core o WSL en Ajustes.")}</small></div>
          <span class="chip ${rt.available ? "ok" : "warn"}">${rt.available ? "conectado" : "no disponible"}</span>
        </div>
        ${!rt.available ? `<button class="btn btn-secondary btn-sm" style="margin-top:8px" data-action="open-settings">${icon("settings")} Configurar runtime</button>` : ""}
      </div>
      ${rt.uses_foam_run ? `<div class="callout warn" style="margin-top:7px">${icon("warning")}<div><strong>OpenFOAM 12 detectado.</strong> Los casos estacionarios se ejecutan con <code>foamRun</code>. Si encuentras algún problema de compatibilidad, usa BlueCFD-Core 2020-1 (OpenFOAM 8).</div></div>` : ""}
    </div>

    <div class="section">
      <div class="section-title">Caso <span>${esc(solverLabel(p.physics.solver))}</span></div>
      <div class="card">
        <div class="run-meta"><span>Solver</span><strong>${p.physics.solver}${rt.uses_foam_run && p.physics.solver === "simpleFoam" ? " → foamRun" : ""}</strong></div>
        <div class="run-meta"><span>Celdas</span><strong>${p.mesh.cell_count ? fmtInt(p.mesh.cell_count) : "sin malla"}</strong></div>
        <div class="run-meta"><span>Patches</span><strong>${p.physics.boundaries.length}</strong></div>
        <div class="run-meta"><span>Almacenamiento</span><strong>ASCII · ${p.run.write_format}</strong></div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Controles del solver</div>
      <div class="grid-2">
        <div class="field"><label>${isSteady ? "Iteraciones" : "Tiempo final"} <em>${isSteady ? "iter" : "s"}</em></label>
          <input class="input" id="run-end" type="number" min="0.0001" step="${isSteady ? "10" : "0.01"}" value="${fmt(p.run.end_time, 6)}"></div>
        <div class="field"><label>Intervalo escritura <em>${isSteady ? "iter" : "s"}</em></label>
          <input class="input" id="run-write" type="number" min="0.0001" step="${isSteady ? "10" : "0.01"}" value="${fmt(p.run.write_interval, 6)}"></div>
      </div>
      ${!isSteady ? `<div class="field"><label>Paso de tiempo Δt <em>s</em></label><input class="input" id="run-dt" type="number" min="0.000001" step="0.001" value="${fmt(p.run.delta_t, 6)}"></div>` : ""}
      <div class="field"><label>Criterio de convergencia <em>residual</em></label><input class="input" id="run-conv" type="number" min="0.000000000001" step="0.00001" value="${fmt(p.run.convergence, 4)}"></div>
      <label class="chip ${hasResults ? "active" : ""}" style="cursor:pointer;width:max-content" id="clean-label">
        <input type="checkbox" id="run-clean" ${hasResults ? "checked" : ""} style="margin:0 2px 0 0;accent-color:var(--accent)"> Borrar resultados anteriores
      </label>
    </div>

    ${!p.has_mesh ? `<div class="section"><div class="callout warn">${icon("warning")}<div><strong>Falta la malla.</strong> Genera la malla antes de ejecutar el solver.<br><button class="btn btn-secondary btn-sm" data-action="goto-mesh" style="margin-top:6px">Ir al mallado</button></div></div></div>` : ""}
    ${running ? liveJobHtml() : ""}
    ${!running && last.status === "completed" ? `
      <div class="section">
        <div class="section-title">Última ejecución</div>
        <div class="stat-grid">
          <div class="stat"><small>Estado</small><strong>completada</strong></div>
          <div class="stat"><small>Último tiempo</small><strong>${fmt(last.last_time, 5)}</strong></div>
          <div class="stat"><small>Muestras</small><strong>${fmtInt(last.times)}</strong></div>
          <div class="stat"><small>Residual Ux</small><strong>${fmt(last.residuals?.Ux, 3)}</strong></div>
        </div>
        ${hasResults ? `<button class="btn btn-secondary btn-sm btn-wide" style="margin-top:8px" data-action="goto-results">${icon("chart")} Ver resultados</button>` : ""}
      </div>` : ""}
    ${!running && last.status === "failed" ? `<div class="section"><div class="callout err">${icon("warning")}<div><strong>La última ejecución falló.</strong><br>${esc(last.error || "Revisa la consola del solver.")}</div></div></div>` : ""}
  `;
}

function runFooterHtml(p) {
  const running = state.job?.status === "running" && state.job?.kind === "run";
  if (running) {
    return `<button class="btn btn-danger btn-wide btn-lg" data-action="stop-job">${icon("stop")} Detener</button>
            <button class="btn btn-secondary btn-wide btn-lg" data-action="open-case">${icon("folder")} Abrir caso</button>`;
  }
  return `<button class="btn btn-secondary btn-wide btn-lg" data-action="check-mesh">${icon("check")} Verificar malla</button>
          <button class="btn btn-primary btn-wide btn-lg" data-action="run-sim" ${!p.has_mesh || !runtimeAvailable() ? "disabled" : ""}>${icon("play")} Ejecutar</button>`;
}

function jobCardHtml(kind) {
  const job = state.job;
  if (!job || job.kind !== kind || job.status !== "running") return "";
  return `<div class="section">
    <div class="section-title">En curso <span>${esc(job.label)}</span></div>
    <div class="card">
      <div class="card-row"><span style="font-size:9.5px;color:var(--muted)">${esc(job.status)}</span><strong style="font-size:11px" class="job-live-percent">${Math.round(job.progress * 100)}%</strong></div>
      <div class="progress-track" style="margin-top:6px"><i class="job-live-bar" style="width:${Math.round(job.progress * 100)}%"></i></div>
      <div class="inline-note job-live-last">${esc(state.lastJobLine || "Iniciando…")}</div>
    </div>
  </div>`;
}

function liveJobHtml() {
  const job = state.job;
  if (!job) return "";
  return `<div class="section">
    <div class="section-title">Simulación en directo <span class="job-live-percent">${Math.round(job.progress * 100)}%</span></div>
    <div class="card">
      <div class="progress-track"><i class="job-live-bar" style="width:${Math.round(job.progress * 100)}%"></i></div>
      <div class="inline-note job-live-last" style="margin-top:7px">${esc(state.lastJobLine || "Iniciando solver…")}</div>
      <button class="btn btn-danger btn-sm btn-wide" style="margin-top:8px" data-action="stop-job">${icon("stop")} Detener simulación</button>
    </div>
  </div>`;
}

/* ------------------------------------------------------------------ results panel */

function resultsHtml(p) {
  if (!p.has_results) {
    return `<div class="empty-state">${icon("chart")}<strong>Sin resultados todavía</strong><p>Ejecuta una simulación para explorar presión y velocidad en el visor 3D.</p>
      <button class="btn btn-primary btn-wide" data-action="goto-run">${icon("play")} Ir a simulación</button></div>`;
  }
  const times = p.times || [];
  const result = state.result;
  if (result.time == null || !times.some((t) => t.value === result.time)) {
    result.time = times.length ? times[times.length - 1].value : null;
  }
  const idx = Math.max(0, times.findIndex((t) => t.value === result.time));
  const meshBounds = state.meshPreview?.dimensions ? [0, state.meshPreview.dimensions.x, 0, state.meshPreview.dimensions.y, 0, state.meshPreview.dimensions.z] : p.geometry;
  const axisIndex = { x: 0, y: 1, z: 2 }[result.axis];
  const lo = axisIndex === 0 ? 0 : axisIndex === 1 ? 0 : 0;
  const hi = axisIndex === 0 ? p.geometry.length : axisIndex === 1 ? p.geometry.height : p.geometry.depth;
  if (result.position == null) result.position = (lo + hi) / 2;
  return `
    <div class="section">
      <div class="section-title">Campo <span>escalar</span></div>
      <div class="segmented tight">
        ${FIELD_OPTIONS.map((f) => `<button class="${result.field === f.id ? "active" : ""}" data-result-field="${f.id}">${f.label}</button>`).join("")}
      </div>
    </div>

    <div class="section">
      <div class="section-title">Vista</div>
      <div class="segmented tight" style="margin-bottom:8px">
        <button class="${result.mode === "slice" ? "active" : ""}" data-result-mode="slice">Corte</button>
        <button class="${result.mode === "surface" ? "active" : ""}" data-result-mode="surface">Superficie</button>
      </div>
      ${result.mode === "slice" ? `
        <div class="grid-2">
          <div class="field"><label>Eje del corte</label>
            <select class="select" id="result-axis">
              <option value="x" ${result.axis === "x" ? "selected" : ""}>X</option>
              <option value="y" ${result.axis === "y" ? "selected" : ""}>Y</option>
              <option value="z" ${result.axis === "z" ? "selected" : ""}>Z</option>
            </select>
          </div>
          <div class="field"><label>Posición <em>m</em></label><input class="input" id="result-pos" type="number" min="${lo}" max="${hi}" step="0.001" value="${fmt(result.position, 5)}"></div>
        </div>` : `<p class="inline-note">La superficie exterior del dominio se colorea con el campo elegido.</p>`}
    </div>

    <div class="section">
      <div class="section-title">Tiempo <span>${times.length} muestras</span></div>
      <div class="time-row">
        <button class="btn-icon-play" data-action="toggle-play" title="Reproducir">${icon(state.playing ? "stop" : "play")}</button>
        <input type="range" id="result-time" min="0" max="${Math.max(0, times.length - 1)}" step="1" value="${idx}">
        <span class="time-label">t = ${fmt(result.time, 5)} s</span>
      </div>
      <p class="inline-note">Desliza o pulsa reproducir para animar la solución en el visor.</p>
    </div>

    <div class="section">
      <div class="section-title">Escala de color</div>
      <div class="chip-row">
        ${["turbo", "viridis", "plasma", "coolwarm"].map((c) => `<button class="chip ${result.colormap === c ? "active" : ""}" data-colormap="${c}" style="text-transform:capitalize">${c}</button>`).join("")}
      </div>
      <div class="chip-row" style="margin-top:9px">
        <label class="chip active" style="cursor:pointer" data-action="toggle-result-bounds">
          <input type="checkbox" checked style="accent-color:var(--accent);margin:0 3px 0 0"> Dominio
        </label>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Resumen</div>
      <div class="stat-grid" id="result-stats">
        ${resultStatsHtml(state.resultPayload)}
      </div>
    </div>

    <div class="section">
      <div class="callout">${icon("info")}<div>Los campos son datos de celda interpolados al corte. La escala se ajusta a los percentiles 2–98 para evitar valores extremos.</div></div>
    </div>`;
}

function resultStatsHtml(payload) {
  if (!payload) {
    return `<div class="stat"><small>Corte</small><strong>cargando…</strong></div>
            <div class="stat"><small>Triángulos</small><strong>—</strong></div>
            <div class="stat"><small>Mínimo</small><strong>—</strong></div>
            <div class="stat"><small>Máximo</small><strong>—</strong></div>`;
  }
  return `<div class="stat"><small>Puntos</small><strong>${fmtInt(payload.point_count)}</strong></div>
          <div class="stat"><small>Triángulos</small><strong>${fmtInt(payload.triangle_count)}</strong></div>
          <div class="stat"><small>Mínimo</small><strong>${fmt(payload.range_focus?.[0] ?? payload.range?.[0])}</strong></div>
          <div class="stat"><small>Máximo</small><strong>${fmt(payload.range_focus?.[1] ?? payload.range?.[1])}</strong></div>`;
}

/* ------------------------------------------------------------------ inspector bindings */

function bindInspector() {
  const body = $("#inspector-body");
  const foot = $("#inspector-foot");

  $$("[data-action]", body).concat($$("[data-action]", foot)).forEach((el) => {
    el.addEventListener("click", (ev) => {
      if (el.tagName === "SELECT" || el.tagName === "INPUT") return;
      ev.preventDefault();
      handleAction(el.dataset.action);
    });
  });

  if (state.step === "geometry") {
    $$("[data-geom]", body).forEach((input) => input.addEventListener("change", applyGeometry));
    const drop = $("#stl-drop");
    const fileInput = $("#stl-input");
    if (drop && fileInput) {
      drop.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", () => uploadStl(fileInput.files?.[0]));
      drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("drag"); });
      drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
      drop.addEventListener("drop", (ev) => {
        ev.preventDefault();
        drop.classList.remove("drag");
        uploadStl(ev.dataTransfer?.files?.[0]);
      });
    }
  }

  if (state.step === "mesh") {
    $$("[data-mesh-preset]", body).forEach((btn) => {
      btn.addEventListener("click", () => setMeshPreset(Number(btn.dataset.meshPreset)));
    });
    const base = $("#mesh-base");
    if (base) base.addEventListener("change", () => updateMeshSettings());
    const refine = $("#mesh-refine");
    if (refine) refine.addEventListener("change", () => updateMeshSettings());
  }

  if (state.step === "physics") {
    $$("[data-solver]", body).forEach((btn) => {
      btn.addEventListener("click", () => updatePhysics({ solver: btn.dataset.solver }, true));
    });
    const fluid = $("#fluid-select");
    if (fluid) fluid.addEventListener("change", () => {
      const f = state.data.fluids[fluid.value];
      updatePhysics({ fluid: fluid.value, density: f.density, nu: f.nu }, true);
    });
    ["density", "nu"].forEach((key) => {
      const el = $(`#physics-${key}`);
      if (el) el.addEventListener("change", () => updatePhysics());
    });
    $$("[data-bc-kind]", body).forEach((el) => el.addEventListener("change", () => updatePhysics(null, true)));
    $$("[data-bc-vel]", body).forEach((el) => el.addEventListener("change", () => updatePhysics()));
    $$("[data-bc-p]", body).forEach((el) => el.addEventListener("change", () => updatePhysics()));
  }

  if (state.step === "run") {
    const bind = (id) => {
      const el = $(id);
      if (el) el.addEventListener("change", () => updateRunSettings());
    };
    ["#run-end", "#run-write", "#run-dt", "#run-conv"].forEach(bind);
    const clean = $("#run-clean");
    if (clean) clean.addEventListener("change", () => { state.clean = clean.checked; });
  }

  if (state.step === "results") {
    $$("[data-result-field]", body).forEach((btn) => btn.addEventListener("click", () => {
      state.result.field = btn.dataset.resultField;
      renderInspector();
      loadResults();
    }));
    $$("[data-result-mode]", body).forEach((btn) => btn.addEventListener("click", () => {
      state.result.mode = btn.dataset.resultMode;
      renderInspector();
      loadResults();
    }));
    $$("[data-colormap]", body).forEach((btn) => btn.addEventListener("click", () => {
      state.result.colormap = btn.dataset.colormap;
      state.viewer.setResultColormap(btn.dataset.colormap);
      updateColorbar(state.resultPayload);
      $$("[data-colormap]", body).forEach((b) => b.classList.toggle("active", b === btn));
    }));
    const axis = $("#result-axis");
    if (axis) axis.addEventListener("change", () => {
      state.result.axis = axis.value;
      state.result.position = null;
      renderInspector();
      loadResults();
    });
    const pos = $("#result-pos");
    if (pos) pos.addEventListener("change", () => {
      state.result.position = Number(pos.value);
      loadResults();
    });
    const time = $("#result-time");
    if (time) time.addEventListener("input", () => {
      const times = project()?.times || [];
      const idx = Number(time.value);
      state.result.time = times[idx]?.value ?? null;
      const label = $(".time-label");
      if (label) label.textContent = `t = ${fmt(state.result.time, 5)} s`;
      loadResults();
    });
    const toggleBounds = $('[data-action="toggle-result-bounds"] input');
    if (toggleBounds) toggleBounds.addEventListener("change", () => {
      state.viewer.setBoundsVisible(toggleBounds.checked);
      toggleBounds.closest(".chip")?.classList.toggle("active", toggleBounds.checked);
    });
  }
}

function handleAction(action) {
  if (!action) return;
  if (action === "next-mesh") selectStep("mesh");
  else if (action === "next-physics") selectStep("physics");
  else if (action === "next-run") selectStep("run");
  else if (action === "goto-mesh") selectStep("mesh");
  else if (action === "goto-run") selectStep("run");
  else if (action === "goto-results") selectStep("results");
  else if (action === "change-preset") openNewProject();
  else if (action === "generate-mesh") startMesh();
  else if (action === "check-mesh") startCheck();
  else if (action === "run-sim") startRun();
  else if (action === "stop-job") stopJob();
  else if (action === "open-case") openFolder("case");
  else if (action === "open-settings") openSettings();
  else if (action === "new-project") openNewProject();
  else if (action === "export-png") exportPng();
  else if (action === "toggle-play") togglePlay();
}

/* ------------------------------------------------------------------ geometry actions */

async function applyGeometry() {
  const p = project();
  if (!p) return;
  const payload = { ...p.geometry };
  $$("[data-geom]").forEach((input) => {
    payload[input.dataset.geom] = Number(input.value);
  });
  try {
    const res = await api("/api/geometry", { method: "POST", body: payload });
    state.data.project = res.project;
    state.preview = res.preview;
    state.meshPreview = null;
    state.meshSig = "";
    state.preview && state.viewer.setGeometry(state.preview);
    state.viewer.setMesh(null);
    state.geomSig = JSON.stringify(res.project.geometry);
    renderChrome();
    markSaving();
    toast("Geometría actualizada", "ok");
  } catch (exc) {
    toast(exc.message, "err", "Geometría no válida");
  }
}

async function uploadStl(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api("/api/geometry/upload", { method: "POST", body: form });
    state.data.project = res.project;
    state.preview = res.preview;
    state.meshPreview = null;
    state.viewer.setGeometry(state.preview);
    state.geomSig = JSON.stringify(res.project.geometry);
    renderChrome();
    toast(`STL cargado: ${file.name}`, "ok");
  } catch (exc) {
    toast(exc.message, "err", "No se pudo cargar el STL");
  }
}

async function setMeshPreset(index) {
  const p = project();
  const sizes = meshSizes(p);
  const base = sizes[index];
  $("#mesh-base").value = fmt(base, 5);
  await updateMeshSettings(base);
  renderInspector();
  toast(`Resolución ${["gruesa", "media", "fina"][index]} seleccionada`, "info");
}

async function updateMeshSettings(baseSize) {
  const p = project();
  if (!p) return;
  const base = baseSize ?? Number($("#mesh-base")?.value);
  const refine = Number($("#mesh-refine")?.value || p.mesh.refine_obstacle);
  if (!Number.isFinite(base) || base <= 0) return;
  try {
    const res = await api("/api/mesh/settings", { method: "POST", body: { base_size: base, refine_obstacle: refine } });
    state.data.project = res.project;
    markSaving();
    renderSteps();
    const est = $("#mesh-base")?.closest(".section")?.querySelector(".stat strong");
    if (est) est.textContent = fmtInt(estimateCells(res.project, base));
  } catch (exc) {
    toast(exc.message, "err", "Malla no válida");
  }
}

/* ------------------------------------------------------------------ physics actions */

function collectBoundaries() {
  const p = project();
  return p.physics.boundaries.map((b) => {
    const kindEl = $(`[data-bc-kind="${CSS.escape(b.name)}"]`);
    const kind = kindEl ? kindEl.value : b.kind;
    const velocity = [0, 0, 0];
    [0, 1, 2].forEach((axis) => {
      const el = $(`[data-bc-vel="${CSS.escape(b.name)}"][data-axis="${axis}"]`);
      if (el) velocity[axis] = Number(el.value) || 0;
    });
    const pressureEl = $(`[data-bc-p="${CSS.escape(b.name)}"]`);
    return {
      ...b,
      kind,
      velocity,
      pressure: pressureEl ? Number(pressureEl.value) || 0 : b.pressure || 0
    };
  });
}

function schedulePhysics(payload, rerender = false) {
  clearTimeout(state.physicsTimer);
  state.physicsTimer = setTimeout(() => updatePhysics(payload, rerender), 240);
}

async function updatePhysics(extra = null, rerender = false) {
  const p = project();
  if (!p) return;
  const payload = {
    solver: extra?.solver ?? p.physics.solver,
    fluid: extra?.fluid ?? p.physics.fluid,
    density: extra?.density ?? Number($("#physics-density")?.value || p.physics.density),
    nu: extra?.nu ?? Number($("#physics-nu")?.value || p.physics.nu),
    inlet_speed: p.physics.inlet_speed,
    turbulence: "laminar",
    boundaries: collectBoundaries()
  };
  try {
    const res = await api("/api/physics", { method: "POST", body: payload });
    state.data = res;
    renderTopbar();
    renderSteps();
    renderHud();
    markSaving();
    if (rerender) renderInspector();
    else toast("Física actualizada", "ok");
  } catch (exc) {
    toast(exc.message, "err", "Física no válida");
  }
}

/* ------------------------------------------------------------------ run actions */

async function updateRunSettings() {
  const p = project();
  if (!p) return;
  const payload = {
    end_time: Number($("#run-end")?.value),
    write_interval: Number($("#run-write")?.value),
    convergence: Number($("#run-conv")?.value)
  };
  const dt = $("#run-dt");
  if (dt) payload.delta_t = Number(dt.value);
  Object.keys(payload).forEach((k) => {
    if (!Number.isFinite(payload[k]) || payload[k] <= 0) delete payload[k];
  });
  try {
    const res = await api("/api/run/settings", { method: "POST", body: payload });
    state.data = res;
    markSaving();
  } catch (exc) {
    toast(exc.message, "err", "Parámetros no válidos");
  }
}

async function startMesh() {
  if (state.busy) return;
  if (!runtimeAvailable()) {
    toast("Configura BlueCFD-Core o WSL para mallar.", "warn", "Sin motor CFD");
    openSettings();
    return;
  }
  const p = project();
  if (p.mesh_method === "gmsh" && p.geometry.kind === "stl") {
    toast("El mallado de STL es experimental. Prueba cavidad, conducto o cilindro.", "warn");
    return;
  }
  await updateMeshSettings();
  state.busy = true;
  try {
    const res = await api("/api/mesh", { method: "POST" });
    watchJob(res.job);
    toast("Generando malla…", "info", "Mallado");
  } catch (exc) {
    toast(exc.message, "err", "No se pudo mallar");
  } finally {
    state.busy = false;
  }
}

async function startCheck() {
  if (state.busy) return;
  state.busy = true;
  try {
    const res = await api("/api/run/check", { method: "POST" });
    watchJob(res.job);
    toast("Verificando la malla…", "info", "checkMesh");
  } catch (exc) {
    toast(exc.message, "err", "checkMesh no disponible");
  } finally {
    state.busy = false;
  }
}

async function startRun() {
  if (state.busy) return;
  const p = project();
  if (!p?.has_mesh) {
    toast("Primero genera la malla.", "warn", "Falta la malla");
    selectStep("mesh");
    return;
  }
  if (!runtimeAvailable()) {
    toast("Configura el motor CFD en Ajustes.", "warn");
    openSettings();
    return;
  }
  await updateRunSettings();
  state.busy = true;
  try {
    const res = await api("/api/run", { method: "POST", body: { clean: $("#run-clean")?.checked ?? true } });
    watchJob(res.job);
    state.step = "run";
    renderChrome();
  } catch (exc) {
    toast(exc.message, "err", "No se pudo iniciar");
  } finally {
    state.busy = false;
  }
}

async function stopJob() {
  if (!state.job || state.job.status !== "running") return;
  try {
    await api(`/api/jobs/${state.job.id}/stop`, { method: "POST" });
    toast("Deteniendo el solver…", "warn");
  } catch (exc) {
    toast(exc.message, "err", "No se pudo detener");
  }
}

/* ------------------------------------------------------------------ job polling */

function watchJob(job) {
  state.job = job;
  state.jobCursor = job.cursor || 0;
  state.lastJobLine = (job.log || []).slice(-1)[0] || "";
  clearInterval(state.pollTimer);
  switchDock("console");
  appendLog(job.log || []);
  updateDock();
  if (job.residuals?.length) state.chart.setData(job.residuals);
  renderInspector();
  state.pollTimer = setInterval(pollJob, 850);
}

async function resumeRunningJob() {
  try {
    const data = await api("/api/jobs/latest");
    if (data.job && data.job.status === "running") {
      watchJob(data.job);
      toast("Reanudando el seguimiento de un trabajo en curso.", "info");
    }
  } catch {
    /* server may have restarted */
  }
}

async function pollJob() {
  if (!state.job) return;
  try {
    const data = await api(`/api/jobs/${state.job.id}?after=${state.jobCursor}`);
    const job = data.job;
    const newLines = job.log || [];
    state.job = job;
    state.jobCursor = job.cursor;
    appendLog(newLines);
    updateDock();
    if (job.residuals?.length) state.chart.setData(job.residuals);
    updateRunLive(job);
    if (job.status !== "running") {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      await finishJob(job);
    }
  } catch (exc) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    toast(exc.message, "err", "Se perdió el trabajo");
  }
}

async function finishJob(job) {
  const ok = job.status === "completed";
  updateDock();
  if (!ok) {
    appendLog([`— ${job.status === "cancelled" ? "Cancelado por el usuario" : "Trabajo fallido"} —`]);
    switchDock("console");
    toast(job.errors?.slice(-1)[0] || "El trabajo no terminó correctamente.", "err", "Error de OpenFOAM");
    await refreshState();
    renderInspector();
    return;
  }
  await refreshState();
  if (job.kind === "mesh") {
    state.meshPreview = null;
    state.meshSig = "";
    await ensureMeshPreview();
    if (state.step === "mesh") {
      renderInspector();
      state.viewer.setMesh(state.meshPreview);
    }
    toast(`Malla lista: ${fmtInt(project()?.mesh?.cell_count)} celdas.`, "ok", "Mallado completado");
  } else if (job.kind === "check") {
    toast("checkMesh terminado. Revisa la calidad en el panel.", "ok");
    renderInspector();
  } else if (job.kind === "run") {
    toast("Simulación completada. Abriendo resultados…", "ok", "Solver finalizado");
    state.result.time = null;
    state.result.position = null;
    await selectStep("results", { persist: false });
  }
  renderChrome();
}

function appendLog(lines) {
  if (!lines || !lines.length) return;
  state.lastJobLine = lines[lines.length - 1] || state.lastJobLine;
  const consoleEl = $("#console");
  if (consoleEl.querySelector(".muted") && !consoleEl.querySelector(".console-line:not(.muted)")) {
    consoleEl.innerHTML = "";
  }
  const nearBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 45;
  const frag = document.createDocumentFragment();
  lines.forEach((line) => {
    const div = document.createElement("div");
    div.className = `console-line ${classifyLog(line)}`;
    div.textContent = line;
    frag.appendChild(div);
  });
  consoleEl.appendChild(frag);
  while (consoleEl.children.length > 900) consoleEl.removeChild(consoleEl.firstChild);
  if (nearBottom) consoleEl.scrollTop = consoleEl.scrollHeight;
}

function classifyLog(line) {
  const l = line.toLowerCase();
  if (line.startsWith("$") || line.startsWith("Solver:") || line.startsWith("Mallador")) return "cmd";
  if (l.includes("fatal") || l.includes("error") || l.includes("exiting") || l.includes("segmentation")) return "err";
  if (l.includes("warning") || l.includes("---")) return "warn";
  if (l.includes("mesh ok") || l.trim() === "end" || l.includes("simulación completada")) return "ok";
  if (l.includes("exec") || l.includes("build") || l.includes("case:") || l.includes("host") || l.includes("date") || l.includes("time   ")) return "dim";
  return "";
}

function updateDock() {
  const job = state.job;
  const statusText = $("#dock-status-text");
  const dot = $("#dock-status .status-dot");
  const bar = $("#dock-progress-bar");
  const pct = $("#dock-progress-text");
  const stop = $("#btn-stop");
  if (!job) {
    statusText.textContent = "Listo";
    dot.className = "status-dot idle";
    bar.style.width = "0%";
    pct.textContent = "0%";
    stop.classList.add("is-hidden");
    return;
  }
  const statusMap = { running: "En curso", completed: "Completado", failed: "Fallido", cancelled: "Cancelado" };
  statusText.textContent = `${statusMap[job.status] || job.status} · ${job.label}`;
  dot.className = `status-dot ${job.status === "running" ? "running" : job.status === "completed" ? "done" : job.status === "failed" ? "error" : "idle"}`;
  const p = Math.round((job.progress || 0) * 100);
  bar.style.width = `${p}%`;
  pct.textContent = `${p}%`;
  stop.classList.toggle("is-hidden", job.status !== "running");
}

function updateRunLive(job) {
  if (!job) return;
  const pct = Math.round((job.progress || 0) * 100);
  $$(".job-live-percent").forEach((el) => { el.textContent = `${pct}%`; });
  $$(".job-live-bar").forEach((el) => { el.style.width = `${pct}%`; });
  const lastLine = (job.log || []).slice(-1)[0];
  if (lastLine) state.lastJobLine = lastLine;
  if (state.lastJobLine) {
    $$(".job-live-last").forEach((el) => { el.textContent = state.lastJobLine; });
  }
  renderViewerMode();
}

/* ------------------------------------------------------------------ results loading */

async function loadResults(options = {}) {
  const p = project();
  if (!p?.has_results) return;
  const times = p.times || [];
  if (!times.length) return;
  if (options.resetTime || state.result.time == null) {
    state.result.time = times[times.length - 1].value;
  }
  if (state.result.position == null) {
    const axis = state.result.axis;
    state.result.position = axis === "x" ? p.geometry.length / 2 : axis === "y" ? p.geometry.height / 2 : p.geometry.depth / 2;
  }
  const seq = ++state.resultSeq;
  const loader = $("#viewer-loader");
  loader.classList.remove("is-hidden");
  $("#viewer-loader-text").textContent = `Leyendo ${state.result.field === "p" ? "presión" : "velocidad"} · t = ${fmt(state.result.time, 5)} s`;
  try {
    const query = new URLSearchParams({
      time: String(state.result.time),
      field: state.result.field,
      mode: state.result.mode,
      axis: state.result.axis,
      position: String(state.result.position)
    });
    const payload = await api(`/api/results/field?${query.toString()}`);
    if (seq !== state.resultSeq) return;
    state.resultPayload = payload;
    state.result.time = payload.time;
    state.viewer.setResultColormap(state.result.colormap);
    state.viewer.setResults(payload, state.result.colormap);
    updateColorbar(payload);
    renderHud();
    const stats = $("#result-stats");
    if (stats) stats.innerHTML = resultStatsHtml(payload);
    const timeLabel = $(".time-label");
    if (timeLabel) timeLabel.textContent = `t = ${fmt(payload.time, 5)} s`;
    $("#viewer-mode").textContent = `${payload.field_label} · ${state.result.mode === "slice" ? `corte ${state.result.axis.toUpperCase()}` : "superficie"} · t = ${fmt(payload.time, 5)} s`;
  } catch (exc) {
    if (seq === state.resultSeq) {
      toast(exc.message, "warn", "No se pudo leer el campo");
      state.viewer.clearResults();
    }
  } finally {
    if (seq === state.resultSeq) loader.classList.add("is-hidden");
  }
}

function updateColorbar(payload) {
  const bar = $("#colorbar");
  if (!payload) {
    bar.classList.add("is-hidden");
    return;
  }
  bar.classList.remove("is-hidden");
  const [lo, hi] = payload.range_focus || payload.range || [0, 1];
  $("#colorbar-title").textContent = payload.field_label || "Campo";
  $("#colorbar-ramp").style.background = rampCss(state.result.colormap);
  $("#colorbar-ticks").innerHTML = Array.from({ length: 5 }, (_, i) => {
    const v = hi - ((hi - lo) * i) / 4;
    return `<span>${fmt(v, 3)}</span>`;
  }).join("");
  const isPressure = payload.field === "p";
  $("#colorbar-unit").textContent = isPressure ? "p/ρ · m²/s²" : "U · m/s";
}

function togglePlay() {
  if (state.playing) {
    state.playing = false;
    clearInterval(state.playTimer);
    state.playTimer = null;
    renderInspector();
    return;
  }
  const times = project()?.times || [];
  if (times.length < 2) return;
  state.playing = true;
  renderInspector();
  state.playTimer = setInterval(() => {
    const current = project()?.times || [];
    let idx = current.findIndex((t) => t.value === state.result.time);
    idx = (idx + 1) % current.length;
    state.result.time = current[idx].value;
    const slider = $("#result-time");
    if (slider) slider.value = String(idx);
    const label = $(".time-label");
    if (label) label.textContent = `t = ${fmt(state.result.time, 5)} s`;
    loadResults();
  }, 900);
}

/* ------------------------------------------------------------------ dock & viewer controls */

function switchDock(tab) {
  $$("#dock-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.dock === tab));
  $$(".dock-pane").forEach((p) => p.classList.toggle("active", p.id === `dock-${tab}`));
}

function renderRuntimeList() {
  const rt = state.data?.runtime;
  if (!rt) return "";
  const items = rt.available || [];
  return `
    <div class="runtime-list">
      <div class="runtime-item ${(rt.preference || "auto") === "auto" ? "active" : ""}" data-runtime-id="auto">
        <span class="status-dot"></span>
        <div><strong>Detección automática</strong><small>Usa BlueCFD-Core primero y WSL como respaldo.</small></div>
        <span class="radio"></span>
      </div>
      ${items.map((r) => `
        <div class="runtime-item ${(rt.preference || "auto") === r.id ? "active" : ""}" data-runtime-id="${esc(r.id)}">
          <span class="status-dot"></span>
          <div><strong>${esc(r.label)}</strong><small>${esc(r.detail)}</small></div>
          <span class="radio"></span>
        </div>`).join("")}
      ${items.length === 0 ? `<div class="callout warn" style="margin-top:4px">${icon("warning")}<div><strong>No se detectó OpenFOAM.</strong> Instala blueCFD-Core 2020-1 o 2024-1 en una ruta sin espacios, o usa WSL. Puedes indicar la ruta manualmente abajo.</div></div>` : ""}
    </div>`;
}

function openSettings() {
  const rt = state.data?.runtime || { selected: {}, available: [] };
  const selected = rt.selected || {};
  if (!state.runtimeChoice) state.runtimeChoice = rt.preference || "auto";
  const html = `
    <div class="modal-header">
      <div><span class="modal-kicker">CONFIGURACIÓN</span><h2>Motor CFD</h2><p>FileGenFOAM ejecuta OpenFOAM mediante BlueCFD-Core en Windows o WSL. La detección se realiza al abrir la aplicación.</p></div>
      <button class="modal-close" data-close>${icon("plus")}</button>
    </div>
    <div class="modal-body">
      <div class="section">
        <div class="section-title">Runtimes detectados</div>
        ${renderRuntimeList()}
      </div>
      <div class="section">
        <div class="section-title">BlueCFD-Core</div>
        <div class="field"><label>Ruta de instalación o bash.exe</label>
          <input class="input" id="settings-bluecfd" placeholder="C:\\blueCFD-Core\\2020-1" value="${esc(state.data?.runtime?.selected?.kind === "bluecfd" ? "" : "")}">
          <p class="field-help">Recomendado: BlueCFD-Core 2020-1 (OpenFOAM 8). Evita rutas con espacios en 2024-1.</p>
        </div>
      </div>
      <div class="section">
        <div class="section-title">WSL</div>
        <div class="grid-2">
          <div class="field"><label>Entorno OpenFOAM</label><input class="input" id="settings-wsl-env" placeholder="~/foamenv"></div>
          <div class="field"><label>micromamba</label><input class="input" id="settings-micromamba" placeholder="~/bin/bin/micromamba"></div>
        </div>
      </div>
      <div class="callout">${icon("info")}<div>Para BlueCFD-Core 2024-1, los casos estacionarios se ejecutan con <code>foamRun</code>; los transitorios usan <code>icoFoam</code>. Consulta <code>docs/BLUECFD.md</code> para la instalación recomendada.</div></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" data-action="rescan-settings">${icon("refresh")} Volver a detectar</button>
      <span class="left"></span>
      <button class="btn" data-close>Cancelar</button>
      <button class="btn btn-primary" data-action="save-settings">Guardar</button>
    </div>`;
  showModal(html, (root) => {
    $$("[data-close]", root).forEach((b) => b.addEventListener("click", closeModal));
    $$("[data-runtime-id]", root).forEach((item) => item.addEventListener("click", () => {
      $$("[data-runtime-id]", root).forEach((i) => i.classList.toggle("active", i === item));
      state.runtimeChoice = item.dataset.runtimeId;
    }));
    $('[data-action="rescan-settings"]', root)?.addEventListener("click", async () => {
      const res = await api("/api/runtime/rescan", { method: "POST" });
      state.data.runtime = res.runtime;
      toast("Detección completada", "ok");
      openSettings();
    });
    $('[data-action="save-settings"]', root)?.addEventListener("click", async () => {
      const payload = {
        bluecfd_path: $("#settings-bluecfd", root).value || null,
        wsl_env: $("#settings-wsl-env", root).value || "~/foamenv",
        micromamba: $("#settings-micromamba", root).value || null,
        runtime_id: state.runtimeChoice || "auto"
      };
      try {
        const res = await api("/api/settings", { method: "POST", body: payload });
        state.data = res;
        closeModal();
        renderChrome();
        toast("Configuración guardada", "ok");
      } catch (exc) {
        toast(exc.message, "err", "No se pudo guardar");
      }
    });
  }, true);
}

/* ------------------------------------------------------------------ new project modal */

function openNewProject() {
  const presets = state.data?.presets || [];
  let selected = state.newPreset || presets[0]?.id || "cavity";
  const recent = state.data?.recent || [];
  const html = `
    <div class="modal-header">
      <div><span class="modal-kicker">NUEVO PROYECTO</span><h2>Elige un punto de partida</h2><p>Cada plantilla crea un caso OpenFOAM completo con geometría, malla, física y condiciones de contorno editables.</p></div>
      <button class="modal-close" data-close>${icon("plus")}</button>
    </div>
    <div class="modal-body">
      <div class="preset-grid">
        ${presets.map((pre) => `
          <button class="preset-card ${pre.id === selected ? "active" : ""}" data-preset="${pre.id}">
            <span class="tag">${esc(pre.tag)}</span>
            <div class="preset-card-top">
              <span class="preset-icon">${icon(PRESET_ICONS[pre.id] || "cube")}</span>
              <strong>${esc(pre.label)}</strong>
            </div>
            <p>${esc(pre.description)}</p>
            <div class="solver">${esc(pre.solver)}</div>
          </button>`).join("")}
      </div>
      <div class="field" style="margin-top:16px"><label>Nombre del proyecto</label><input class="input" id="new-name" value="${esc(presets.find((p) => p.id === selected)?.label || "Mi caso CFD")}"></div>
      ${state.data?.app?.demo_available ? `<div class="callout" style="margin-top:4px">${icon("layers")}<div><strong>¿Quieres ver algo ya calculado?</strong> Abre el caso demo de cavidad con resultados incluidos.<br><button class="btn btn-secondary btn-sm" data-action="load-demo" style="margin-top:6px">${icon("play")} Cargar demo</button></div></div>` : ""}
      ${recent.length ? `<div class="divider-label">Recientes</div><div class="preset-list">${recent.map((r) => `<div class="preset-row" data-open-project="${esc(r.path)}"><span class="preset-icon">${icon("folder")}</span><span class="preset-copy"><strong>${esc(r.name)}</strong><small>${esc(r.preset || "")} · ${esc(r.updated_at || "")}</small></span>${icon("chevron")}</div>`).join("")}</div>` : ""}
    </div>
    <div class="modal-footer">
      <span class="left">El proyecto se guarda en Documentos/FileGenFOAM.</span>
      <button class="btn" data-close>Cancelar</button>
      <button class="btn btn-primary" data-action="create-project">${icon("plus")} Crear proyecto</button>
    </div>`;
  showModal(html, (root) => {
    $$("[data-close]", root).forEach((b) => b.addEventListener("click", closeModal));
    $$("[data-preset]", root).forEach((card) => card.addEventListener("click", () => {
      selected = card.dataset.preset;
      state.newPreset = selected;
      $$("[data-preset]", root).forEach((c) => c.classList.toggle("active", c === card));
      $("#new-name", root).value = presets.find((p) => p.id === selected)?.label || "Mi caso CFD";
    }));
    $$("[data-open-project]", root).forEach((row) => row.addEventListener("click", async () => {
      try {
        const res = await api("/api/project/open", { method: "POST", body: { path: row.dataset.openProject } });
        state.data = res;
        closeModal();
        await afterProjectLoaded();
      } catch (exc) { toast(exc.message, "err", "No se pudo abrir"); }
    }));
    $('[data-action="load-demo"]', root)?.addEventListener("click", async () => {
      try {
        const res = await api("/api/project/demo", { method: "POST" });
        state.data = res;
        closeModal();
        await afterProjectLoaded();
      } catch (exc) { toast(exc.message, "err", "Demo no disponible"); }
    });
    $('[data-action="create-project"]', root)?.addEventListener("click", async () => {
      const name = $("#new-name", root).value.trim() || "Mi caso CFD";
      try {
        const res = await api("/api/project/new", { method: "POST", body: { preset: selected, name } });
        state.data = res;
        closeModal();
        await afterProjectLoaded();
      } catch (exc) { toast(exc.message, "err", "No se pudo crear"); }
    });
  }, false);
}

async function afterProjectLoaded() {
  state.playing = false;
  clearInterval(state.playTimer);
  state.playTimer = null;
  state.preview = null;
  state.meshPreview = null;
  state.geomSig = "";
  state.meshSig = "";
  state.result = { field: "U_mag", mode: "slice", axis: "z", position: null, time: null, colormap: "turbo" };
  state.resultPayload = null;
  state.step = "geometry";
  await loadGeometryPreview();
  renderChrome();
  await selectStep("geometry", { persist: false });
  toast(`Proyecto «${project()?.name}» abierto`, "ok");
}

/* ------------------------------------------------------------------ modal plumbing */

function showModal(html, binder, wide = true) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal" style="${wide ? "width:min(780px,100%)" : ""}">${html}</div></div>`;
  state.modalOpen = true;
  const backdrop = $(".modal-backdrop", root);
  backdrop.addEventListener("mousedown", (ev) => {
    if (ev.target === backdrop) closeModal();
  });
  binder?.(root);
  setTimeout(() => $("input,button", root)?.focus(), 60);
}

function closeModal() {
  $("#modal-root").innerHTML = "";
  state.modalOpen = false;
}

/* ------------------------------------------------------------------ misc actions */

async function openFolder(which = "case") {
  try {
    const res = await api("/api/open-folder", { method: "POST", body: { which } });
    toast(res.path, "info", "Carpeta abierta");
  } catch (exc) {
    toast(exc.message, "err");
  }
}

function exportPng() {
  if (!state.viewer) return;
  try {
    const url = state.viewer.screenshot();
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project()?.name || "filegenfoam"}-${state.result.field}-t${state.result.time}.png`;
    a.click();
    toast("Imagen PNG descargada", "ok");
  } catch (exc) {
    toast(String(exc), "err");
  }
}

function bindGlobal() {
  $$(".step").forEach((el) => el.addEventListener("click", () => selectStep(el.dataset.step)));
  $("#btn-new").addEventListener("click", openNewProject);
  $("#btn-settings").addEventListener("click", openSettings);
  $("#runtime-pill").addEventListener("click", openSettings);
  $("#btn-rescan").addEventListener("click", async () => {
    const res = await api("/api/runtime/rescan", { method: "POST" });
    state.data.runtime = res.runtime;
    renderChrome();
    toast("Detección de runtime actualizada", "info");
  });
  $("#btn-open-folder").addEventListener("click", () => openFolder("case"));
  $("#btn-empty-new").addEventListener("click", openNewProject);
  $("#quick-run").addEventListener("click", () => {
    if (state.job?.status === "running") stopJob();
    else {
      if (!project()?.has_mesh) { selectStep("mesh"); toast("Genera una malla antes de ejecutar.", "warn"); }
      else selectStep("run");
    }
  });
  $$("#view-toolbar [data-view]").forEach((btn) => btn.addEventListener("click", () => {
    state.viewer.setView(btn.dataset.view);
    $$("#view-toolbar [data-view]").forEach((b) => b.classList.toggle("active", b === btn));
  }));
  $("#btn-fit").addEventListener("click", () => state.viewer.fit());
  $("#toggle-mesh").addEventListener("click", () => {
    const visible = !state.viewer.meshVisible;
    state.viewer.setMeshVisible(visible);
    $("#toggle-mesh").classList.toggle("active", visible);
  });
  $("#toggle-wire").addEventListener("click", (ev) => {
    const visible = !ev.currentTarget.classList.contains("active");
    ev.currentTarget.classList.toggle("active", visible);
    state.viewer.setBoundsVisible(visible);
  });
  $("#btn-shot").addEventListener("click", exportPng);
  $("#compass").addEventListener("click", () => state.viewer.setView("iso"));
  $$("#dock-tabs button").forEach((btn) => btn.addEventListener("click", () => switchDock(btn.dataset.dock)));
  $("#btn-dock-toggle").addEventListener("click", () => {
    $("#dock").classList.toggle("collapsed");
    setTimeout(() => state.viewer.resize(), 260);
  });
  $("#btn-stop").addEventListener("click", stopJob);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && state.modalOpen) closeModal();
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
      ev.preventDefault();
      api("/api/project/save", { method: "POST" }).then(() => {
        markSaving();
        toast("Proyecto guardado", "ok");
      }).catch((e) => toast(e.message, "err"));
    }
  });
  // Compass rotation follows the camera.
  setInterval(() => {
    const angle = state.viewer?.compassAngle?.() || 0;
    const needle = $("#compass-needle");
    if (needle) needle.style.transform = `rotate(${-angle}rad)`;
  }, 120);
}

/* start */
init();
