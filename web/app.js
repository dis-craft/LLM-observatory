"use strict";

(function () {
  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
  const state = {
    models: [],
    health: null,
    telemetry: null,
    history: [],
    experiments: [],
    integrations: null,
    activeJobs: {},
    currentPage: "overview",
    lastRenderAt: null
  };

  async function api(path, options) {
    const response = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, options || {}));
    let body = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      body = await response.json();
    } else {
      body = { detail: await response.text() };
    }
    if (!response.ok) {
      const error = body && (body.detail || body.error);
      throw new Error(typeof error === "string" ? error : "Request failed (" + response.status + ")");
    }
    return body;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function fmtBytes(bytes, decimals) {
    if (bytes === null || bytes === undefined || !Number.isFinite(Number(bytes))) return "—";
    const value = Number(bytes);
    if (value === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const position = Math.min(Math.floor(Math.log(Math.abs(value)) / Math.log(1024)), units.length - 1);
    return (value / Math.pow(1024, position)).toFixed(decimals == null ? (position > 1 ? 2 : 0) : decimals) + " " + units[position];
  }

  function fmtNumber(value, digits) {
    return value === null || value === undefined || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits == null ? 1 : digits);
  }

  function fmtDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function shortModel(name) {
    if (!name) return "Unknown model";
    return String(name).replace(/^.*[\\/]/, "");
  }

  function quantOf(model) {
    return model && model.quantization_level ? model.quantization_level : "Not reported";
  }

  function showToast(message, kind) {
    const region = $("#toast-region");
    const toast = document.createElement("div");
    toast.className = "toast" + (kind === "error" ? " error" : "");
    toast.textContent = message;
    region.appendChild(toast);
    window.setTimeout(function () { toast.remove(); }, 5200);
  }

  function showAlert(message) {
    const alert = $("#global-alert");
    alert.textContent = message;
    alert.classList.remove("hidden");
  }

  function clearAlert() {
    $("#global-alert").classList.add("hidden");
  }

  function setPage(pageName) {
    const valid = $("#page-" + pageName);
    if (!valid) return;
    state.currentPage = pageName;
    $$(".page").forEach(function (page) { page.classList.toggle("active", page.id === "page-" + pageName); });
    $$(".nav-item[data-page]").forEach(function (item) { item.classList.toggle("active", item.dataset.page === pageName); });
    $("#current-breadcrumb").textContent = valid.dataset.title || pageName;
    document.title = (valid.dataset.title || "Observatory") + " — LLM Observatory";
    if (pageName === "hardware") drawHardwareCharts();
    if (pageName === "results") renderExperiments();
    if (pageName === "integrations") renderIntegrations();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  $$(".nav-item[data-page]").forEach(function (button) {
    button.addEventListener("click", function () { setPage(button.dataset.page); });
  });
  $$("[data-go]").forEach(function (button) {
    button.addEventListener("click", function () { setPage(button.dataset.go); });
  });

  function setConnection(health) {
    state.health = health;
    const ollama = health && health.ollama;
    const online = Boolean(ollama && ollama.available);
    $("#sidebar-ollama-dot").classList.toggle("offline", !online);
    $("#sidebar-ollama-status").textContent = online ? "Ollama connected" : "Ollama unavailable";
    $("#sidebar-ollama-host").textContent = ollama && ollama.host ? ollama.host : "127.0.0.1:11434";
    $("#runtime-version").textContent = online ? "Ollama " + (ollama.version || "") : "Ollama · offline";
    $("#runtime-model-count").textContent = state.models.length ? String(state.models.length) + " installed" : "None detected";
    $("#overview-status-pulse").classList.toggle("offline", !online);
    $("#overview-status-title").textContent = online ? "Local inference runtime connected" : "Waiting for Ollama";
    $("#overview-status-copy").textContent = online ? "Model requests stay on the configured local Ollama service" : "Start Ollama and refresh the connection";
    if (!online) {
      showAlert("Ollama is not reachable at " + (ollama && ollama.host ? ollama.host : "the configured endpoint") + ". Start Ollama, then use Refresh data.");
    } else {
      clearAlert();
    }
    const node = health && health.tools && health.tools.node && health.tools.node.available;
    if (!node && health && health.tools) {
      $("#promptfoo-chip").classList.add("unavailable");
    }
  }

  async function refreshHealth() {
    try {
      const result = await api("/api/health");
      setConnection(result);
      renderIntegrations(result.tools);
    } catch (error) {
      setConnection({ ollama: { available: false, host: "127.0.0.1:11434", error: error.message } });
    }
  }

  function quantShort(model) {
    const value = quantOf(model);
    return value === "Not reported" ? value : value.toUpperCase().replace("_", " ");
  }

  async function reloadModels() {
    try {
      const result = await api("/api/models");
      state.models = result.models || [];
      $("#models-total").textContent = state.models.length;
      $("#models-quants").textContent = new Set(state.models.map(quantOf).filter((x) => x !== "Not reported")).size;
      $("#models-runtime").textContent = state.health && state.health.ollama && state.health.ollama.version ? "Ollama " + state.health.ollama.version : "Ollama";
      renderModelTable();
      renderModelsGrid();
      renderModelOptions("performance-models", ["q2", "q4"]);
      renderModelOptions("quality-models", ["q2", "q4"]);
      updateModelSelect("lm-eval-model");
    updateModelSelect("quality-baseline");
      $("#runtime-model-count").textContent = state.models.length ? String(state.models.length) + " installed" : "None detected";
    } catch (error) {
      state.models = [];
      $("#overview-models").innerHTML = '<tr><td colspan="6" class="empty-state">Cannot retrieve models. Start Ollama and refresh.</td></tr>';
      $("#models-grid").innerHTML = '<div class="panel empty-state">Ollama is unavailable. Start the runtime and refresh the registry.</div>';
      $("#performance-models").innerHTML = '<div class="empty-state">No models available.</div>';
      $("#quality-models").innerHTML = '<div class="empty-state">No models available.</div>';
      showToast(error.message, "error");
    }
  }

  function loadedSet() {
    const models = state.telemetry && state.telemetry.loaded_models || [];
    return new Set(models.map((model) => model.name));
  }

  function renderModelTable() {
    const loaded = loadedSet();
    const body = $("#overview-models");
    if (!state.models.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty-state">No installed models found.</td></tr>';
      return;
    }
    body.innerHTML = state.models.slice(0, 8).map(function (model) {
      const active = loaded.has(model.name);
      return '<tr><td><div class="table-model"><span class="model-mark">M</span><div><strong>' + escapeHtml(shortModel(model.name)) + '</strong><small>' + escapeHtml(model.family || "Local Ollama model") + '</small></div></div></td><td>' + escapeHtml(model.parameter_size || "—") + '</td><td><span class="quant-chip">' + escapeHtml(quantShort(model)) + '</span></td><td class="file-size">' + escapeHtml(fmtBytes(model.size_bytes)) + '</td><td>' + escapeHtml(fmtDate(model.modified_at)) + '</td><td><span class="table-status"><span class="status-dot ' + (active ? "" : "status-muted") + '"></span>' + (active ? "Loaded" : "Installed") + '</span></td></tr>';
    }).join("");
  }

  function renderModelsGrid() {
    const grid = $("#models-grid");
    if (!state.models.length) {
      grid.innerHTML = '<div class="panel empty-state">No installed models found in Ollama.</div>';
      return;
    }
    const loaded = loadedSet();
    grid.innerHTML = state.models.map(function (model) {
      const active = loaded.has(model.name);
      return '<article class="model-card"><div class="model-card-head"><span class="model-mark">M</span><div><h3>' + escapeHtml(model.name) + '</h3><p>' + escapeHtml([model.family, model.format].filter(Boolean).join(" · ") || "Local model") + '</p></div></div><div class="model-card-meta"><div><span>PARAMETERS</span><strong>' + escapeHtml(model.parameter_size || "—") + '</strong></div><div><span>QUANTIZATION</span><strong>' + escapeHtml(quantShort(model)) + '</strong></div><div><span>FILE SIZE</span><strong>' + escapeHtml(fmtBytes(model.size_bytes)) + '</strong></div></div><div class="model-card-foot"><span class="table-status"><span class="status-dot ' + (active ? "" : "status-muted") + '"></span>' + (active ? "Currently loaded" : "Available locally") + '</span><small>' + escapeHtml(fmtDate(model.modified_at)) + '</small></div></article>';
    }).join("");
  }

  function autoSelectModels(preferences) {
    if (!state.models.length) return [];
    const lower = state.models.map((m) => ({ name: m.name, lower: m.name.toLowerCase() }));
    let selection = [];
    if (preferences && preferences.includes("q2")) {
      const match = lower.find((m) => m.lower.includes("q2_k") || /q2\b/.test(m.lower));
      if (match) selection.push(match.name);
    }
    if (preferences && preferences.includes("q4")) {
      const match = lower.find((m) => m.lower.includes("q4_k") || /q4\b/.test(m.lower));
      if (match && !selection.includes(match.name)) selection.push(match.name);
    }
    if (!selection.length) selection.push(state.models[0].name);
    return selection;
  }

  function renderModelOptions(elementId, preferred) {
    const container = $("#" + elementId);
    if (!container) return;
    const existing = new Set($$("input[type=checkbox]:checked", container).map((el) => el.value));
    const selected = existing.size ? Array.from(existing) : autoSelectModels(preferred);
    if (!state.models.length) {
      container.innerHTML = '<div class="empty-state">Install a model with Ollama first.</div>';
      return;
    }
    container.innerHTML = state.models.map(function (model, index) {
      const checked = selected.includes(model.name);
      return '<label class="model-choice"><input type="checkbox" value="' + escapeHtml(model.name) + '" ' + (checked ? "checked" : "") + '><span class="model-mark">' + String(index + 1).padStart(2, "0") + '</span><span class="model-choice-copy"><strong>' + escapeHtml(model.name) + '</strong><span>' + escapeHtml(model.parameter_size || "Size not reported") + ' · ' + escapeHtml(model.family || "Local model") + '</span></span><span class="model-choice-meta">' + escapeHtml(quantShort(model)) + '</span></label>';
    }).join("");
  }

  function updateModelSelect(elementId) {
    const select = $("#" + elementId);
    if (!select) return;
    const previous = select.value;
    select.innerHTML = state.models.map((model) => '<option value="' + escapeHtml(model.name) + '">' + escapeHtml(model.name) + '</option>').join("");
    if (state.models.some((model) => model.name === previous)) select.value = previous;
    else {
      const first = state.models.find((model) => model.name.toLowerCase().includes("q4_k"));
      if (first) select.value = first.name;
    }
  }

  function getSelectedModels(containerId) {
    return $$('input[type="checkbox"]:checked', $("#" + containerId)).map((input) => input.value);
  }

  function updateTelemetry(data) {
    state.telemetry = data;
    state.lastRenderAt = new Date();
    state.history.push(data);
    if (state.history.length > 90) state.history.shift();
    const gpu = data.gpu || {};
    const ramUsed = Number(data.ram_used_bytes || 0);
    const ramTotal = Number(data.ram_total_bytes || 0);
    const ramPct = Number(data.ram_utilization_pct || 0);
    const vramUsed = Number(gpu.memory_used_mb || 0);
    const vramTotal = Number(gpu.memory_total_mb || 0);
    const vramPct = vramTotal ? vramUsed / vramTotal * 100 : null;

    $("#metric-ram").textContent = (ramUsed / 1073741824).toFixed(1);
    $("#metric-ram-detail").textContent = fmtBytes(ramUsed) + " used of " + fmtBytes(ramTotal);
    $("#metric-ram-pct").textContent = fmtNumber(ramPct, 0) + "%";
    $("#ram-progress").style.width = Math.max(0, Math.min(100, ramPct)) + "%";
    $("#metric-vram").textContent = gpu.memory_total_mb != null ? (vramUsed / 1024).toFixed(1) : "—";
    $("#metric-vram-detail").textContent = gpu.memory_total_mb != null ? (vramTotal / 1024).toFixed(1) + " GB total" : "NVIDIA telemetry unavailable";
    $("#metric-vram-pct").textContent = vramPct == null ? "—" : fmtNumber(vramPct, 0) + "%";
    $("#vram-progress").style.width = Math.max(0, Math.min(100, vramPct || 0)) + "%";
    $("#metric-gpu-util").textContent = fmtNumber(gpu.utilization_pct, 0);
    $("#metric-gpu-name").textContent = gpu.name || "GPU telemetry unavailable";
    $("#metric-gpu-temp").textContent = gpu.temperature_c == null ? "— °C" : fmtNumber(gpu.temperature_c, 0) + " °C";
    $("#metric-ollama-rss").textContent = fmtNumber(Number(data.ollama_process_rss_bytes || 0) / 1048576, 0);
    $("#metric-ollama-cpu").textContent = "Process CPU " + fmtNumber(data.ollama_process_cpu_pct, 0) + "%";
    const loaded = data.loaded_models || [];
    $("#metric-loaded-models").textContent = loaded.length ? loaded.map((m) => shortModel(m.name)).join(", ") : "No loaded model reported";
    $("#metric-process-count").textContent = String(data.ollama_process_count || 0) + " processes";
    $("#chart-cpu-current").textContent = fmtNumber(data.cpu_utilization_pct, 0) + "%";
    $("#chart-gpu-current").textContent = fmtNumber(gpu.utilization_pct, 0) + "%";
    $("#last-updated").textContent = "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    $("#hardware-cpu").textContent = fmtNumber(data.cpu_utilization_pct, 0);
    $("#hardware-ram").textContent = (ramUsed / 1073741824).toFixed(1);
    $("#hardware-ram-sub").textContent = fmtBytes(ramUsed) + " / " + fmtBytes(ramTotal) + " · " + fmtNumber(ramPct, 0) + "%";
    $("#hardware-gpu").textContent = fmtNumber(gpu.utilization_pct, 0);
    $("#hardware-gpu-sub").textContent = gpu.name || "No supported GPU telemetry";
    $("#hardware-power").textContent = fmtNumber(gpu.power_w, 1);
    $("#hardware-power-sub").textContent = gpu.power_limit_w == null ? "Instantaneous GPU power" : "Reported limit " + fmtNumber(gpu.power_limit_w, 0) + " W";
    drawResourceChart();
    drawHardwareCharts();
    drawSparkline();
    renderModelTable();
  }

  function drawLineChart(canvasId, series, options) {
    const canvas = $("#" + canvasId);
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.floor(rect.width * ratio);
    canvas.height = Math.floor(rect.height * ratio);
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    const width = rect.width;
    const height = rect.height;
    const opts = options || {};
    const pad = { top: 12, right: 8, bottom: 14, left: 8 };
    const plotW = Math.max(1, width - pad.left - pad.right);
    const plotH = Math.max(1, height - pad.top - pad.bottom);
    const maxValue = opts.maxValue || 100;
    ctx.clearRect(0, 0, width, height);
    ctx.font = "9px system-ui, sans-serif";
    ctx.strokeStyle = "#2a342d";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + plotH * i / 4;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
      if (opts.labels) {
        ctx.fillStyle = "#748277";
        ctx.fillText(String(Math.round(maxValue * (1 - i / 4))), 1, y - 3);
      }
    }
    series.forEach(function (line) {
      const values = line.values || [];
      if (!values.length) return;
      const valid = values.map((v) => v == null || !Number.isFinite(Number(v)) ? null : Math.max(0, Math.min(maxValue, Number(v))));
      ctx.beginPath();
      let started = false;
      valid.forEach(function (value, index) {
        if (value == null) { started = false; return; }
        const x = pad.left + (valid.length <= 1 ? 0 : index / (valid.length - 1)) * plotW;
        const y = pad.top + (1 - value / maxValue) * plotH;
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = line.color;
      ctx.lineWidth = 1.7;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();
    });
  }

  function drawResourceChart() {
    const history = state.history;
    drawLineChart("resourceChart", [
      { values: history.map((item) => item.cpu_utilization_pct), color: "#c8f169" },
      { values: history.map((item) => item.gpu ? item.gpu.utilization_pct : null), color: "#bda8fa" }
    ], { maxValue: 100 });
  }

  function drawSparkline() {
    drawLineChart("gpuSparkline", [{ values: state.history.map((item) => item.gpu ? item.gpu.utilization_pct : null), color: "#bda8fa" }], { maxValue: 100 });
  }

  function drawHardwareCharts() {
    const history = state.history;
    drawLineChart("hardware-resource-chart", [
      { values: history.map((item) => item.cpu_utilization_pct), color: "#c8f169" },
      { values: history.map((item) => item.gpu ? item.gpu.utilization_pct : null), color: "#bda8fa" }
    ], { maxValue: 100, labels: true });
    drawLineChart("memory-chart", [
      { values: history.map((item) => {
        const total = item.ram_total_bytes || 0;
        return total ? (item.ram_used_bytes || 0) / total * 100 : null;
      }), color: "#c8f169" },
      { values: history.map((item) => {
        const gpu = item.gpu || {};
        return gpu.memory_total_mb ? gpu.memory_used_mb / gpu.memory_total_mb * 100 : null;
      }), color: "#82b9f8" }
    ], { maxValue: 100, labels: true });
  }

  async function refreshTelemetry() {
    try {
      const data = await api("/api/telemetry");
      updateTelemetry(data);
    } catch (error) {
      $("#last-updated").textContent = "Telemetry unavailable";
    }
  }

  function kindLabel(kind) {
    return ({
      performance: "Performance benchmark",
      native_quality: "Quality benchmark",
      promptfoo: "Promptfoo quality",
      lm_eval: "LM Evaluation",
      imported_benchmark: "Imported result"
    })[kind] || kind || "Experiment";
  }

  function statusClass(status) {
    if (status === "completed") return "completed";
    if (status === "failed") return "failed";
    if (status === "running") return "running";
    return "queued";
  }

  function resultSummary(experiment) {
    const result = experiment.result || {};
    if (experiment.kind === "performance" && result.summary_by_model) {
      const firstModel = Object.keys(result.summary_by_model)[0];
      const summary = firstModel ? result.summary_by_model[firstModel] : {};
      return (summary.generation_tokens_per_second_median != null ? fmtNumber(summary.generation_tokens_per_second_median, 2) + " tok/s median" : "Performance run");
    }
    if (experiment.kind === "native_quality" && result.summary_by_model) {
      const firstModel = Object.keys(result.summary_by_model)[0];
      const summary = firstModel ? result.summary_by_model[firstModel] : {};
      return summary.assertion_pass_rate == null ? "Quality run" : fmtNumber(summary.assertion_pass_rate * 100, 1) + "% reference pass";
    }
    if (experiment.kind === "promptfoo") {
      return result.report_available ? "Report saved" : (experiment.status === "completed" ? "Evaluator completed" : "Quality checks");
    }
    if (experiment.kind === "imported_benchmark") return "External file";
    if (experiment.kind === "lm_eval") return result.return_code === 0 ? "Task completed" : "Standard task";
    return experiment.error || "—";
  }

  async function refreshExperiments() {
    try {
      const result = await api("/api/experiments?limit=100");
      state.experiments = result.experiments || [];
      renderExperiments();
    } catch (error) {
      showToast("Could not load saved results: " + error.message, "error");
    }
  }

  function renderExperiments() {
    const rows = state.experiments || [];
    const completed = rows.filter((item) => item.status === "completed").length;
    const failed = rows.filter((item) => item.status === "failed").length;
    $("#results-summary").innerHTML = '<div class="summary-tile"><span>SAVED RUNS</span><strong>' + rows.length + '</strong></div><div class="summary-tile"><span>COMPLETED</span><strong>' + completed + '</strong></div><div class="summary-tile"><span>FAILED</span><strong>' + failed + '</strong></div>';
    const tbody = $("#results-table");
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No experiments saved yet. Run a performance experiment or quality evaluation to start building your history.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(function (row) {
      const conf = row.config || {};
      const labels = conf.models ? conf.models.map(shortModel).join(", ") : (conf.model || conf.filename || "—");
      return '<tr><td><div class="table-model"><span class="model-mark">' + escapeHtml(String(row.kind || "E").slice(0, 1).toUpperCase()) + '</span><div><strong>' + escapeHtml(row.id) + '</strong><small>' + escapeHtml(labels) + '</small></div></div></td><td>' + escapeHtml(kindLabel(row.kind)) + '</td><td>' + escapeHtml(fmtDate(row.created_at)) + '</td><td><span class="status-pill ' + statusClass(row.status) + '">' + escapeHtml(row.status) + '</span></td><td><div class="progress-track" style="width:90px;margin:0"><span class="progress-fill fill-green" style="width:' + Math.max(0, Math.min(100, Number(row.progress || 0))) + '%"></span></div><small>' + fmtNumber(row.progress || 0, 0) + '%</small></td><td><button class="text-link" data-detail="' + escapeHtml(row.id) + '">Details ↗</button></td></tr>';
    }).join("");
    $$("[data-detail]", tbody).forEach(function (button) {
      button.addEventListener("click", function () { showExperimentDetail(button.dataset.detail); });
    });
  }

  function showExperimentDetail(id) {
    const experiment = state.experiments.find((item) => item.id === id);
    if (!experiment) return;
    $("#result-detail").classList.remove("hidden");
    $("#result-detail-title").textContent = kindLabel(experiment.kind) + " · " + experiment.id;
    $("#result-detail-subtitle").textContent = experiment.status + " · Created " + fmtDate(experiment.created_at);
    $("#result-detail-content").innerHTML = '<div class="result-kpis"><div class="result-kpi"><span>STATUS</span><strong>' + escapeHtml(experiment.status) + '</strong></div><div class="result-kpi"><span>PROGRESS</span><strong>' + fmtNumber(experiment.progress, 0) + '%</strong></div><div class="result-kpi"><span>TYPE</span><strong>' + escapeHtml(kindLabel(experiment.kind)) + '</strong></div></div><h4 style="font-size:10px;margin:16px 0 8px;color:#b8c7b5">CONFIGURATION</h4><pre>' + escapeHtml(JSON.stringify(experiment.config, null, 2)) + '</pre><h4 style="font-size:10px;margin:16px 0 8px;color:#b8c7b5">RESULT / RAW METRICS</h4><pre>' + escapeHtml(JSON.stringify(experiment.result || { error: experiment.error }, null, 2)) + '</pre>';
    $("#result-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  $("#close-result-detail").addEventListener("click", function () { $("#result-detail").classList.add("hidden"); });

  function renderIntegrations(tools) {
    const data = tools || state.health && state.health.tools;
    if (!data) return;
    state.integrations = data;
    const integrationInfo = [
      { key: "ollama", title: "Ollama runtime", purpose: "Serves local models and returns prompt/generation timing plus model allocation.", install: "Install and start Ollama; pull at least one model.", group: "CORE" },
      { key: "nvidia_smi", title: "NVIDIA telemetry", purpose: "Reports device-wide GPU utilization, VRAM, temperature, clocks and instantaneous power when supported.", install: "Install a supported NVIDIA driver and confirm nvidia-smi works in PowerShell.", group: "CORE" },
      { key: "promptfoo", title: "Promptfoo", purpose: "Runs repeatable output assertions over identical questions for selected model variants.", install: "npm install -g promptfoo", group: "QUALITY" },
      { key: "lm_eval", title: "LM Evaluation Harness", purpose: "Runs standardized evaluation tasks through compatible local OpenAI-style APIs. Task compatibility varies.", install: "python -m pip install 'lm_eval[api]'", group: "QUALITY" },
      { key: "llama_bench", title: "llama-bench", purpose: "Benchmarks GGUF models through llama.cpp. Its measurements must be labeled separately from Ollama.", install: "Build llama.cpp and put llama-bench on PATH; import its CSV/JSON results.", group: "PERFORMANCE" },
      { key: "nsight_systems", title: "NVIDIA Nsight Systems", purpose: "Provides advanced CPU/GPU timeline diagnostics; it is not run automatically during measurements.", install: "Install NVIDIA Nsight Systems, then use its profiler according to the official documentation.", group: "DIAGNOSTICS" }
    ];
    $("#integrations-grid").innerHTML = integrationInfo.map(function (info) {
      const status = data[info.key] || { available: false };
      const available = Boolean(status.available);
      return '<article class="panel integration-feature"><div class="integration-feature-top"><span class="integration-logo">' + escapeHtml(info.group.slice(0, 2)) + '</span><span class="availability-chip ' + (available ? "available" : "unavailable") + '">' + (available ? "AVAILABLE" : "NOT DETECTED") + '</span></div><h3>' + escapeHtml(info.title) + '</h3><p>' + escapeHtml(info.purpose) + '</p><div class="inline-tool-note">' + (available ? "Detected on this machine." : "Setup: " + escapeHtml(status.install || info.install)) + '</div></article>';
    }).join("");
    const qualityChip = $("#promptfoo-chip");
    if (qualityChip) {
      qualityChip.textContent = "BUILT-IN EVALUATOR";
      qualityChip.classList.add("available");
      qualityChip.classList.remove("unavailable");
    }
    const lmEval = data.lm_eval || {};
    $("#lm-eval-status").textContent = lmEval.available ? "Available" : "Not installed";
    $("#lm-eval-status").classList.toggle("available", Boolean(lmEval.available));
    $("#lm-eval-status").classList.toggle("unavailable", !lmEval.available);
    $("#lm-eval-help").textContent = lmEval.available ? "CLI detected. Task execution is run in a separate process and may take several minutes." : "Install in the same Python environment used by this server: " + (lmEval.install || "python -m pip install 'lm_eval[api]'");
    $("#nsys-status").textContent = data.nsight_systems && data.nsight_systems.available ? "Available" : "Optional";
    $("#nsys-status").classList.toggle("available", Boolean(data.nsight_systems && data.nsight_systems.available));
    $("#nsys-help").textContent = data.nsight_systems && data.nsight_systems.available ? "CLI detected. Profile selected runs separately; tracing may affect performance." : "Optional diagnostic tool. It is not required for ordinary benchmarks.";
  }

  function bindTemperature() {
    const input = $("#performance-temperature");
    if (!input) return;
    input.addEventListener("input", function () { $("#temperature-value").textContent = Number(input.value).toFixed(1); });
  }

  function showJob(prefix, title, subtitle, id) {
    const card = $("#" + prefix + "-job");
    card.classList.remove("hidden");
    $("#" + prefix + "-job-title").textContent = title;
    $("#" + prefix + "-job-subtitle").textContent = subtitle;
    $("#" + prefix + "-job-state").textContent = "QUEUED";
    $("#" + prefix + "-job-state").classList.remove("failed");
    $("#" + prefix + "-job-progress").style.width = "0%";
    $("#" + prefix + "-job-progress-label").textContent = "Queued";
    $("#" + prefix + "-job-id").textContent = "ID " + id;
    $("#" + prefix + "-job-result").classList.add("hidden");
    $("#" + prefix + "-job-result").innerHTML = "";
    if (prefix === "lm-eval") {
      $("#" + prefix + "-job-progress-label").textContent = "Running in a background process";
    }
    state.activeJobs[id] = prefix;
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderJobResult(prefix, experiment) {
    const target = $("#" + prefix + "-job-result");
    target.classList.remove("hidden");
    const result = experiment.result || {};
    let body = "";
    if (experiment.kind === "native_quality" && result.summary_by_model) {
      body += '<p class="inline-tool-note">Baseline: ' + escapeHtml(shortModel(result.baseline_model || "")) + '. Exact agreement compares normalized text, not meaning. Reference pass rate is only as strong as the assertions and dataset.</p><div class="result-kpis">';
      Object.keys(result.summary_by_model).forEach(function (model) {
        const m = result.summary_by_model[model];
        const pct = (value) => value == null ? "—" : fmtNumber(value * 100, 1) + "%";
        body += '<div class="result-kpi"><span>' + escapeHtml(shortModel(model)) + '</span><strong>' + pct(m.assertion_pass_rate) + ' pass</strong><span>Exact reference match ' + pct(m.reference_exact_match_rate) + '</span><span>Baseline agreement ' + pct(m.baseline_exact_agreement_rate) + '</span><span>Repeat consistency ' + pct(m.repeat_consistency_rate) + '</span><span>Failed requests ' + (m.failed_trials == null ? "—" : m.failed_trials) + '</span></div>';
      });
      body += '</div><p class="inline-tool-note">' + (result.trials ? result.trials.length : 0) + ' quality trial(s). Repeat consistency is unavailable for single-run tests. Run quality and performance benchmarks separately.</p>';
      if (result.trials) body += '<details class="job-log"><summary>View answer-by-answer results</summary><pre>' + escapeHtml(JSON.stringify(result.trials, null, 2)) + '</pre></details>';
    } else if (experiment.kind === "performance" && result.summary_by_model) {
      body += '<div class="result-kpis">';
      Object.keys(result.summary_by_model).forEach(function (model) {
        const metrics = result.summary_by_model[model];
        body += '<div class="result-kpi"><span>' + escapeHtml(shortModel(model)) + ' · MEDIAN GENERATION</span><strong>' + (metrics.generation_tokens_per_second_median == null ? "—" : fmtNumber(metrics.generation_tokens_per_second_median, 2) + " tok/s") + '</strong><span>Median latency ' + (metrics.latency_median_s == null ? "—" : fmtNumber(metrics.latency_median_s, 2) + " s") + '</span><span>TTFT ' + (metrics.ttft_median_s == null ? "—" : fmtNumber(metrics.ttft_median_s, 2) + " s") + '</span><span>Estimated GPU energy ' + (metrics.gpu_energy_j_median_estimate == null ? "Not enough samples" : fmtNumber(metrics.gpu_energy_j_median_estimate, 2) + " J") + '</span><span>Energy sample coverage: ' + escapeHtml(metrics.gpu_energy_estimated_trials == null ? "—" : metrics.gpu_energy_estimated_trials + " trial(s)") + '</span></div>';
      });
      body += '</div><p class="inline-tool-note">' + (result.trials ? result.trials.length : 0) + ' measured request(s). RAM/VRAM are sampled and shared-device. GPU energy is an estimate shown only when sample coverage is sufficient; it is not model-isolated or whole-laptop energy.</p>'; 
      if (result.errors && result.errors.length) body += '<pre>' + escapeHtml(JSON.stringify(result.errors, null, 2)) + '</pre>';
    } else if (experiment.kind === "promptfoo") {
      body += '<p class="inline-tool-note">' + (result.report_available ? "Promptfoo produced a report." : "Promptfoo ran without a parseable JSON report.") + ' Inspect the saved experiment for CLI logs and raw evaluation data.</p>';
      if (result.report && result.report.results && result.report.results.stats) {
        const stats = result.report.results.stats;
        body += '<div class="result-kpis"><div class="result-kpi"><span>PASS</span><strong>' + escapeHtml(stats.successes == null ? "—" : stats.successes) + '</strong></div><div class="result-kpi"><span>FAIL</span><strong>' + escapeHtml(stats.failures == null ? "—" : stats.failures) + '</strong></div><div class="result-kpi"><span>ERROR</span><strong>' + escapeHtml(stats.errors == null ? "—" : stats.errors) + '</strong></div></div>';
      }
      if (result.stderr_tail) body += '<details class="job-log"><summary>Evaluator logs</summary><pre>' + escapeHtml(result.stderr_tail + "\n" + (result.stdout_tail || "")) + '</pre></details>';
    } else if (experiment.kind === "lm_eval") {
      body += '<p class="inline-tool-note">Standard evaluation process finished. Open Results to inspect saved output and artifact metadata.</p>';
      if (result.stdout_tail) body += '<pre>' + escapeHtml(result.stdout_tail) + '</pre>';
      if (result.stderr_tail) body += '<details class="job-log"><summary>Standard benchmark stderr</summary><pre>' + escapeHtml(result.stderr_tail) + '</pre></details>';
    } else {
      body += '<p class="inline-tool-note">Run saved. Open Results to inspect full configuration and metrics.</p>';
    }
    target.innerHTML = body;
  }

  async function watchJob(id, prefix) {
    let previousStatus = "";
    const started = Date.now();
    while (Date.now() - started < 2 * 60 * 60 * 1000) {
      try {
        const response = await api("/api/experiments/" + encodeURIComponent(id));
        const experiment = response.experiment;
        const status = experiment.status || "queued";
        $("#" + prefix + "-job-state").textContent = status.toUpperCase();
        $("#" + prefix + "-job-state").classList.toggle("failed", status === "failed");
        $("#" + prefix + "-job-progress").style.width = Math.max(0, Math.min(100, Number(experiment.progress || 0))) + "%";
        $("#" + prefix + "-job-progress-label").textContent = Math.round(Number(experiment.progress || 0)) + "% complete";
        if (status === "running" && previousStatus !== "running") $("#" + prefix + "-job-subtitle").textContent = "Running locally; this may take some time";
        previousStatus = status;
        if (status === "completed" || status === "failed") {
          $("#" + prefix + "-job-subtitle").textContent = status === "completed" ? "Run finished and saved locally" : (experiment.error || "Run failed");
          if (status === "failed") {
            $("#" + prefix + "-job-state").classList.add("failed");
            showToast(experiment.error || "Experiment failed", "error");
          } else {
            showToast("Experiment " + id + " saved", "success");
          }
          renderJobResult(prefix, experiment);
          await refreshExperiments();
          return;
        }
      } catch (error) {
        $("#" + prefix + "-job-subtitle").textContent = "Status check failed: " + error.message;
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1250));
    }
    $("#" + prefix + "-job-subtitle").textContent = "Still running. Track it in Results.";
  }

  function setSubmitState(button, disabled, label) {
    button.disabled = disabled;
    if (label) button.dataset.defaultLabel = label;
    if (disabled) {
      button.dataset.originalText = button.textContent;
      button.textContent = "Starting…";
    } else {
      button.textContent = button.dataset.defaultLabel || button.dataset.originalText || "Run";
    }
  }

  $("#performance-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    clearAlert();
    const button = $("#start-performance");
    const models = getSelectedModels("performance-models");
    const prompts = $("#performance-prompts").value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    if (!models.length) { showToast("Select at least one model variant.", "error"); return; }
    if (!prompts.length) { showToast("Enter at least one prompt.", "error"); return; }
    const repetitions = Number($("#performance-repetitions").value);
    if (models.length * prompts.length * repetitions > 1000) {
      showToast("The run is too large. Reduce models, prompts or repetitions to stay under 1,000 measured requests.", "error"); return;
    }
    setSubmitState(button, true, "▶ Run performance experiment");
    try {
      const response = await api("/api/experiments/performance", {
        method: "POST",
        body: JSON.stringify({
          models: models, prompts: prompts,
          repetitions: repetitions,
          warmups: Number($("#performance-warmups").value),
          temperature: Number($("#performance-temperature").value),
          context_length: Number($("#performance-context").value),
          max_tokens: Number($("#performance-output").value),
          system_prompt: $("#performance-system").value,
          sample_interval_s: 1.0
        })
      });
      showJob("performance", "Performance experiment", "Queued on this machine", response.experiment_id);
      watchJob(response.experiment_id, "performance");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setSubmitState(button, false);
    }
  });

  function parseQualityCases() {
    const lines = $("#quality-cases").value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    const output = [];
    for (let index = 0; index < lines.length; index++) {
      const pieces = lines[index].split("||");
      if (pieces.length < 2 || !pieces[0].trim() || !pieces.slice(1).join("||").trim()) {
        throw new Error("Line " + (index + 1) + " must use: question || expected phrase");
      }
      output.push({ question: pieces[0].trim(), expected: pieces.slice(1).join("||").trim(), assertion: $("#quality-assertion").value });
    }
    return output;
  }

  $("#quality-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    const button = $("#start-quality");
    const models = getSelectedModels("quality-models");
    if (!models.length) { showToast("Select at least one model variant.", "error"); return; }
    const baselineModel = $("#quality-baseline").value;
    if (!models.includes(baselineModel)) { showToast("Check the reference baseline in the selected variants list.", "error"); return; }
    let cases;
    try { cases = parseQualityCases(); } catch (error) { showToast(error.message, "error"); return; }
    setSubmitState(button, true, "✓ Run quality benchmark");
    try {
      const repetitions = Number($("#quality-repetitions").value);
      if (models.length * cases.length * repetitions > 500) {
        showToast("This run would exceed 500 requests. Reduce models, cases or repetitions.", "error");
        return;
      }
      const response = await api("/api/evaluations/native", {
        method: "POST",
        body: JSON.stringify({
          models: models, baseline_model: baselineModel, cases: cases, repetitions: repetitions,
          temperature: Number($("#quality-temperature").value),
          context_length: Number($("#quality-context").value), max_tokens: Number($("#quality-output").value)
        })
      });
      showJob("quality", "Quality benchmark", cases.length + " cases × " + repetitions + " repetitions across " + models.length + " model(s)", response.experiment_id);
      watchJob(response.experiment_id, "quality");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setSubmitState(button, false);
    }
  });

  $("#lm-eval-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    const button = $("#start-lm-eval");
    const model = $("#lm-eval-model").value;
    if (!model) { showToast("No installed models available.", "error"); return; }
    setSubmitState(button, true, "Run selected task");
    try {
      const response = await api("/api/evaluations/lm-eval", {
        method: "POST",
        body: JSON.stringify({ model: model, task: $("#lm-eval-task").value, limit: Number($("#lm-eval-limit").value) })
      });
      showJob("lm-eval", "LM Evaluation Harness", "Task: " + $("#lm-eval-task").value + " · Model: " + model, response.experiment_id);
      watchJob(response.experiment_id, "lm-eval");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setSubmitState(button, false);
    }
  });

  async function refreshIntegrations() {
    try {
      const health = await api("/api/health");
      state.health = health;
      setConnection(health);
      renderIntegrations(health.tools);
    } catch (error) {
      showToast("Could not inspect local integrations: " + error.message, "error");
    }
  }

  $("#refresh-integrations").addEventListener("click", refreshIntegrations);
  $("#reload-models").addEventListener("click", async function () {
    await reloadModels();
    await refreshTelemetry();
    showToast("Model registry refreshed.");
  });
  $("#sidebar-refresh").addEventListener("click", refreshHealth);
  $("#refresh-all").addEventListener("click", async function () {
    await Promise.all([refreshHealth(), reloadModels(), refreshTelemetry(), refreshExperiments()]);
    showToast("Workspace data refreshed.");
  });
  $("#refresh-results").addEventListener("click", refreshExperiments);

  $("#export-results").addEventListener("click", async function () {
    try {
      const result = await api("/api/experiments-export");
      downloadBlob(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }), "llm-observatory-results.json");
    } catch (error) { showToast(error.message, "error"); }
  });

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1200);
  }

  $("#import-results").addEventListener("click", async function () {
    const file = $("#import-file").files && $("#import-file").files[0];
    if (!file) { showToast("Select a CSV or JSON result file first.", "error"); return; }
    if (file.size > 5_000_000) { showToast("Choose a file smaller than 5 MB.", "error"); return; }
    const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : file.name.toLowerCase().endsWith(".json") ? "json" : null;
    if (!format) { showToast("Only CSV and JSON files are supported.", "error"); return; }
    const status = $("#import-status");
    status.textContent = "Reading " + file.name + "…";
    try {
      const content = await file.text();
      const response = await api("/api/results/import", {
        method: "POST", body: JSON.stringify({ filename: file.name, file_format: format, content: content })
      });
      status.textContent = "Imported and saved as " + response.experiment_id + ". Results remain labeled as an external benchmark.";
      await refreshExperiments();
      showToast("External benchmark imported.");
    } catch (error) {
      status.textContent = error.message;
      showToast(error.message, "error");
    }
  });

  $("#modal-close").addEventListener("click", function () { $("#confirm-modal").classList.add("hidden"); });
  $("#confirm-modal").addEventListener("click", function (event) {
    if (event.target === $("#confirm-modal")) $("#confirm-modal").classList.add("hidden");
  });

  function maybeShowQualityAvailability() {
    const tools = state.health && state.health.tools;
    if (!tools || !tools.promptfoo) return;
    const available = tools.promptfoo.available || tools.promptfoo.npx_available;
    $("#start-quality").disabled = !available;
    if (!available) $("#start-quality").title = "Install Node.js and Promptfoo to enable quality runs.";
  }

  async function init() {
    bindTemperature();
    $("#footer-clock").textContent = "LOCAL SESSION · " + new Date().getFullYear();
    await refreshHealth();
    await reloadModels();
    maybeShowQualityAvailability();
    await refreshTelemetry();
    await refreshExperiments();
    await refreshIntegrations();
    maybeShowQualityAvailability();
    window.setInterval(refreshTelemetry, 2000);
    window.setInterval(refreshExperiments, 12000);
    window.setInterval(async function () {
      await refreshHealth();
      maybeShowQualityAvailability();
    }, 30000);
    window.addEventListener("resize", function () {
      drawResourceChart();
      drawHardwareCharts();
      drawSparkline();
    });
  }

  init().catch(function (error) {
    showToast("Startup error: " + error.message, "error");
  });
})();