"use strict";

(function () {
  const $ = (selector, root) => (root || document).querySelector(selector);
  const state = {
    models: [],
    selected: new Set(),
    baseline: "",
    busy: false,
    latestPerformance: null,
    latestQuality: null,
    experiments: [],
    health: null,
    telemetry: null
  };

  async function api(path, options) {
    const response = await fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" }
    }, options || {}));
    const type = response.headers.get("content-type") || "";
    const body = type.includes("application/json") ? await response.json() : { detail: await response.text() };
    if (!response.ok) {
      const reason = body && (body.detail || body.error);
      throw new Error(typeof reason === "string" ? reason : "Request failed (" + response.status + ")");
    }
    return body;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function number(value, digits) {
    return value === null || value === undefined || !Number.isFinite(Number(value))
      ? "—" : Number(value).toFixed(digits == null ? 1 : digits);
  }

  function pct(value) {
    return value === null || value === undefined || !Number.isFinite(Number(value))
      ? "—" : number(Number(value) * 100, 1) + "%";
  }

  function signedPct(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return (Number(value) > 0 ? "+" : "") + number(value, 1) + "%";
  }

  function bytes(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let n = Number(value), i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return number(n, i > 1 ? 2 : 0) + " " + units[i];
  }

  function dateLabel(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) :
      date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function toast(message, error) {
    const region = $("#toast-region");
    const item = document.createElement("div");
    item.className = "toast" + (error ? " toast-error" : "");
    item.textContent = message;
    region.appendChild(item);
    window.setTimeout(() => item.remove(), 6000);
  }

  const baseQuestions = [
    "Explain why the sky appears blue in two sentences.",
    "What is the difference between RAM and VRAM?",
    "Solve step by step: if 3x + 5 = 20, what is x? Explain briefly."
  ];

  function createLogContext(task) {
    const places = [
      "Amber", "Birch", "Cedar", "Dawn", "Elm", "Fern", "Grove", "Harbor",
      "Indigo", "Juniper", "Kite", "Lake", "Maple", "North", "Orchid", "Pine",
      "Quartz", "River", "Stone", "Timber", "Umber", "Vale", "Willow", "Xenon",
      "Yarrow", "Zephyr", "Atlas", "Brook", "Clover", "Drift", "Ember", "Flint",
      "Glimmer", "Haven", "Iris", "Jasper", "Knoll", "Lantern", "Meadow", "Nectar",
      "Opal", "Prairie", "Quest", "Ripple", "Summit", "Thistle", "Unity", "Vista",
      "Wren", "Xylem", "Yonder", "Zenith", "Aspen", "Boulder", "Coral", "Delta",
      "Evergreen", "Frost", "Glacier", "Horizon", "Mariner", "Orbit", "Praxis", "Solstice"
    ];
    const logs = Array.from({ length: 96 }, (_, i) => {
      const name = places[i % places.length];
      const value = 18 + ((i * 17) % 83);
      const zone = String.fromCharCode(65 + (i % 6));
      return "Record " + String(i + 1).padStart(3, "0") + ": Station " + name +
        " reported zone " + zone + ", sensor value " + value +
        ", inspection status " + (i % 5 === 0 ? "review required" : "normal") +
        ", shift " + (1 + (i % 3)) + ".";
    });
    logs.push("Verified calibration note: Beacon Station's reference code is K7-MARIGOLD-29.");
    if (task === "retrieval") {
      return "Read the operational records. Do not guess from a pattern. Use the explicit calibration note. " +
        logs.join(" ") + " Question: What is the exact reference code for Beacon Station? Return only the code.";
    }
    return logs.join(" ");
  }

  const profiles = {
    balanced: {
      prompts: baseQuestions,
      context: "2048", output: "128",
      description: "Three short, mixed prompts for a quick edge-device profile. Token counts come from the runtime."
    },
    prefill: {
      prompts: ["Read the following operational report. Summarize its overall patterns in two short sentences. Do not invent facts. " + createLogContext("prefill")],
      context: "4096", output: "32",
      description: "Long input with a short output cap. Focus: prompt-processing behaviour. Actual token length depends on the model tokenizer."
    },
    decode: {
      prompts: ["Write a detailed but factual guide to running language models on edge devices. Use eight clearly named sections covering quantization, memory, latency, throughput, reliability, power, thermal limits, and deployment trade-offs. Include examples and a final checklist. Do not claim measurements you have not performed."],
      context: "2048", output: "512",
      description: "Short instruction with a higher output cap. Focus: generation. A model may stop before reaching the cap."
    },
    retrieval: {
      prompts: [createLogContext("retrieval")],
      context: "4096", output: "32",
      description: "Long input with a known lookup answer. Use Quality checks to score correctness separately."
    },
    long: {
      prompts: ["Using the operational records below, write a structured report with sections for observed patterns, anomalies, limits of the evidence, and recommendations. Reference the records rather than making up measurements. " + createLogContext("long")],
      context: "4096", output: "512",
      description: "Long input plus a longer answer. This combines prompt processing and sustained generation; review the actual token counts."
    }
  };

  function applyProfile(name) {
    const profile = profiles[name];
    if (!profile) {
      $("#workload-description").textContent = "Custom prompts are used exactly as entered; change context and output caps explicitly if needed.";
      return;
    }
    $("#performance-prompts").value = profile.prompts.join("\n");
    $("#performance-context").value = profile.context;
    $("#performance-output").value = profile.output;
    $("#workload-description").textContent = profile.description;
  }

  $("#workload-profile").addEventListener("change", () => applyProfile($("#workload-profile").value));
  $("#performance-prompts").addEventListener("input", () => {
    if ($("#workload-profile").value !== "custom") $("#workload-profile").value = "custom";
    $("#workload-description").textContent = "Custom prompts are used exactly as entered; change context and output caps explicitly if needed.";
  });

  function selectedModels() {
    return state.models.filter((model) => state.selected.has(model.name)).map((model) => model.name);
  }

  function renderModels() {
    const host = $("#model-choices");
    const select = $("#baseline-model");
    host.replaceChildren();
    if (!state.models.length) {
      host.innerHTML = '<p class="empty">No Ollama models found. Start Ollama and install at least one model, then refresh.</p>';
      select.replaceChildren(new Option("No models available", ""));
      return;
    }
    state.models.forEach((model) => {
      const label = document.createElement("label");
      label.className = "model-option";
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = state.selected.has(model.name);
      check.setAttribute("aria-label", "Select " + model.name);
      const copy = document.createElement("span");
      copy.className = "model-copy";
      const strong = document.createElement("strong");
      strong.textContent = model.name;
      const small = document.createElement("small");
      small.textContent = [model.parameter_size || "parameter size not reported", model.quantization_level || "quantization not reported", bytes(model.size_bytes)].join(" · ");
      copy.append(strong, small);
      const marker = document.createElement("span");
      marker.className = "model-check";
      marker.textContent = "Select";
      label.append(check, copy, marker);
      check.addEventListener("change", () => {
        if (check.checked) state.selected.add(model.name);
        else state.selected.delete(model.name);
        marker.textContent = check.checked ? "Selected" : "Select";
        label.classList.toggle("chosen", check.checked);
      });
      if (check.checked) { label.classList.add("chosen"); marker.textContent = "Selected"; }
      host.appendChild(label);
    });

    const previous = state.baseline;
    select.replaceChildren();
    state.models.forEach((model) => select.add(new Option(model.name, model.name)));
    state.baseline = state.models.some((model) => model.name === previous) ? previous : state.models[0].name;
    select.value = state.baseline;
    if (!state.selected.size) state.selected.add(state.baseline);
    if (!state.selected.has(state.baseline)) state.selected.add(state.baseline);
    // Re-render after baseline is made part of the selected model set.
    if (!$('input[type="checkbox"]:checked', host)) {
      const firstCheck = $('input[type="checkbox"]', host);
      if (firstCheck) { firstCheck.checked = true; firstCheck.closest("label").classList.add("chosen"); firstCheck.closest("label").querySelector(".model-check").textContent = "Selected"; }
    }
  }

  $("#baseline-model").addEventListener("change", () => {
    state.baseline = $("#baseline-model").value;
    state.selected.add(state.baseline);
    renderModels();
  });

  async function refreshHealth() {
    try {
      const health = await api("/api/health");
      state.health = health;
      const ollama = health.ollama || {};
      const online = Boolean(ollama.available);
      $("#runtime-state").classList.toggle("offline", !online);
      $("#runtime-state").innerHTML = '<span class="dot"></span>' + (online ? "Ollama connected" : "Ollama unavailable");
      $("#runtime-version").textContent = online ? "Ollama " + (ollama.version || "version unknown") : "Unavailable";
      const gpu = health.tools && health.tools.nvidia_smi && health.tools.nvidia_smi.available;
      $("#gpu-status").textContent = gpu ? "NVIDIA telemetry detected" : "Not detected";
      $("#gpu-status").className = gpu ? "status-good" : "status-muted";
      $("#connection-note").className = "notice " + (online ? "notice-good" : "notice-warn");
      $("#connection-note").textContent = online
        ? "Connected to " + (ollama.host || "local Ollama") + ". Requests are sent to this configured runtime."
        : "Ollama is unavailable at " + (ollama.host || "the configured endpoint") + ". Start Ollama and refresh; no benchmark can run until models are reachable.";
    } catch (error) {
      $("#runtime-state").className = "connection-pill offline";
      $("#runtime-state").textContent = "Dashboard API unavailable";
      $("#connection-note").className = "notice notice-warn";
      $("#connection-note").textContent = "Could not reach the Observatory backend: " + error.message;
    }
  }

  async function refreshModels() {
    const previousSelection = new Set(state.selected);
    try {
      const result = await api("/api/models");
      state.models = result.models || [];
      state.selected = new Set(state.models.filter((model) => previousSelection.has(model.name)).map((model) => model.name));
      $("#model-count").textContent = String(state.models.length);
      renderModels();
    } catch (error) {
      state.models = [];
      state.selected.clear();
      $("#model-count").textContent = "Unavailable";
      renderModels();
      toast("Could not load models: " + error.message, true);
    }
  }

  async function refreshTelemetry() {
    try {
      const data = await api("/api/telemetry");
      state.telemetry = data;
      const gpu = data.gpu;
      if (gpu && gpu.name) {
        $("#gpu-status").textContent = gpu.name + " · " + (gpu.utilization_pct == null ? "utilization unavailable" : number(gpu.utilization_pct, 0) + "%");
        $("#gpu-status").className = "status-good";
      }
    } catch (_) {
      $("#gpu-status").textContent = "Telemetry unavailable";
      $("#gpu-status").className = "status-muted";
    }
  }

  function lockActions(locked) {
    state.busy = locked;
    $("#start-performance").disabled = locked;
    $("#start-quality").disabled = locked;
    $("#refresh-all").disabled = locked;
    $("#job-card").classList.toggle("hidden", !locked);
  }

  function setJob(kind, id, message) {
    $("#job-title").textContent = kind === "performance" ? "Performance benchmark" : "Quality benchmark";
    $("#job-message").textContent = message;
    $("#job-status").textContent = "QUEUED";
    $("#job-status").className = "job-status";
    $("#job-progress").style.width = "0%";
    $("#job-progress-label").textContent = "0% complete";
    $("#job-id").textContent = "Run " + id;
  }

  async function waitForJob(id, kind) {
    let last;
    while (true) {
      const response = await api("/api/experiments/" + encodeURIComponent(id));
      last = response.experiment;
      $("#job-status").textContent = String(last.status || "queued").toUpperCase();
      $("#job-status").className = "job-status " + (last.status === "failed" ? "failed" : "");
      const progress = Math.max(0, Math.min(100, Number(last.progress || 0)));
      $("#job-progress").style.width = progress + "%";
      $("#job-progress-label").textContent = Math.round(progress) + "% complete";
      if (last.status === "running") {
        $("#job-message").textContent = "Running on the configured local runtime. Keep this dashboard open.";
      }
      if (last.status === "completed" || last.status === "failed") break;
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
    if (last.status === "failed") {
      const reason = last.error || (last.result && last.result.error) || "The run failed. Inspect the saved run for details.";
      $("#job-message").textContent = reason;
      toast(reason, true);
    } else {
      $("#job-message").textContent = "Finished. Measurements and configuration have been saved locally.";
      toast("Benchmark run completed and saved.");
      if (kind === "performance") {
        state.latestPerformance = last;
        renderPerformance(last);
      } else {
        state.latestQuality = last;
        renderQuality(last);
      }
    }
    await refreshHistory();
    return last;
  }

  async function executeRun(kind, endpoint, payload, message) {
    if (state.busy) return;
    lockActions(true);
    try {
      const response = await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
      setJob(kind, response.experiment_id, message);
      const result = await waitForJob(response.experiment_id, kind);
      if (result.status !== "completed") {
        throw new Error(result.error || (result.result && result.result.error) || "Benchmark failed.");
      }
    } catch (error) {
      $("#job-message").textContent = error.message;
      $("#job-status").textContent = "ERROR";
      $("#job-status").classList.add("failed");
      $("#job-card").classList.remove("hidden");
      toast(error.message, true);
    } finally {
      lockActions(false);
    }
  }

  function commonConfig() {
    return {
      models: selectedModels(),
      baseline_model: state.baseline,
      temperature: Number($("#performance-temperature").value),
      context_length: Number($("#performance-context").value),
      max_tokens: Number($("#performance-output").value),
      system_prompt: $("#performance-system").value
    };
  }

  function runPerformance() {
    if (state.busy) return;
    const config = commonConfig();
    const prompts = $("#performance-prompts").value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
    const repetitions = Number($("#performance-repetitions").value);
    const warmups = Number($("#performance-warmups").value);
    if (!config.models.length) { toast("Select at least one model.", true); return; }
    if (!config.models.includes(config.baseline_model)) { toast("Select the reference baseline in the model list.", true); return; }
    if (!prompts.length) { toast("Add at least one prompt.", true); return; }
    if (config.models.length * prompts.length * repetitions > 1000) { toast("This run exceeds 1,000 measured requests. Reduce models, prompts or repetitions.", true); return; }
    const profile = $("#workload-profile").value;
    executeRun(
      "performance", "/api/experiments/performance",
      Object.assign({}, config, {
        workload_profile: profile, prompts, repetitions, warmups,
        sample_interval_s: Number($("#sample-interval").value)
      }),
      config.models.length + " model(s) · " + prompts.length + " prompt(s) · " + repetitions + " repetitions"
    );
  }

  function parseQualityCases() {
    const assertion = $("#quality-assertion").value;
    const lines = $("#quality-cases").value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
    return lines.map((line, i) => {
      const parts = line.split("||");
      if (parts.length < 2 || !parts[0].trim() || !parts.slice(1).join("||").trim()) {
        throw new Error("Reference case line " + (i + 1) + " must be: question || expected answer or phrase");
      }
      return {
        question: parts[0].trim(),
        expected: parts.slice(1).join("||").trim(),
        assertion
      };
    });
  }

  function runQuality() {
    if (state.busy) return;
    const config = commonConfig();
    if (!config.models.length) { toast("Select at least one model.", true); return; }
    if (!config.models.includes(config.baseline_model)) { toast("Select the reference baseline in the model list.", true); return; }
    let cases;
    try { cases = parseQualityCases(); } catch (error) { toast(error.message, true); return; }
    if (!cases.length) { toast("Add at least one reference case.", true); return; }
    const repetitions = Number($("#performance-repetitions").value);
    if (config.models.length * cases.length * repetitions > 500) {
      toast("This quality run exceeds 500 requests. Reduce models, cases or repetitions.", true);
      return;
    }
    executeRun(
      "quality", "/api/evaluations/native",
      Object.assign({}, config, { cases, repetitions }),
      config.models.length + " model(s) · " + cases.length + " reference case(s) · " + repetitions + " repetitions"
    );
  }

  function relativeChange(summary, key) {
    const changes = summary.change_percent_vs_baseline || {};
    return signedPct(changes[key]);
  }

  function renderPerformance(experiment) {
    const result = experiment.result || {};
    const summaries = result.summary_by_model;
    if (!summaries || !Object.keys(summaries).length) {
      $("#performance-summary-note").textContent = "Run completed, but no summary metrics were returned.";
      $("#performance-results").innerHTML = '<p class="empty">No summary metrics returned. Inspect the saved raw run.</p>';
      return;
    }
    const baseline = result.baseline_model || experiment.config && experiment.config.baseline_model || "";
    const env = result.environment || {};
    const gpu = env.gpu_snapshot || {};
    const config = experiment.config || result.config || {};
    $("#performance-summary-note").textContent =
      "Baseline: " + baseline + " · " + (result.trials || []).length + " measured requests · " +
      (config.repetitions || "—") + " repetitions per prompt/model · " +
      (config.warmups == null ? "—" : config.warmups) + " warm-up(s) per model. " +
      (env.ollama_version ? "Ollama " + env.ollama_version + ". " : "") +
      (gpu.name ? "GPU: " + gpu.name + ". " : "NVIDIA power telemetry may be unavailable. ") +
      "Run order is serial; repeated runs can still be affected by temperature and background activity.";

    const models = env.models || [];
    const modelInfo = Object.fromEntries(models.map((m) => [m.name, m]));
    const rows = Object.keys(summaries).map((model) => {
      const m = summaries[model];
      const info = modelInfo[model] || {};
      const base = model === baseline;
      return '<tr' + (base ? ' class="baseline-row"' : '') + '>' +
        '<td><strong>' + escapeHtml(model) + '</strong><small>' + escapeHtml(info.quantization_level || "Quantization not reported") + (base ? " · BASELINE" : "") + '</small></td>' +
        '<td><strong>' + number(m.generation_tokens_per_second_median, 2) + ' tok/s</strong><small>' + (m.generation_tokens_per_second_stddev == null ? "SD unavailable" : "SD " + number(m.generation_tokens_per_second_stddev, 2)) + ' · ' + relativeChange(m, "generation_tokens_per_second_median") + ' vs baseline</small></td>' +
        '<td><strong>' + number(m.prompt_tokens_per_second_median, 2) + ' tok/s</strong><small>' + relativeChange(m, "prompt_tokens_per_second_median") + ' vs baseline</small></td>' +
        '<td><strong>' + number(m.latency_median_s, 3) + ' s</strong><small>SD ' + number(m.latency_stddev_s, 3) + ' · ' + relativeChange(m, "latency_median_s") + '</small><small>p95 ' + number(m.latency_p95_s, 3) + ' s</small></td>' +
        '<td><strong>' + number(m.ttft_median_s, 3) + ' s</strong><small>SD ' + number(m.ttft_stddev_s, 3) + ' · ' + relativeChange(m, "ttft_median_s") + '</small></td>' +
        '<td><strong>' + number(m.prompt_tokens_median, 0) + ' / ' + number(m.output_tokens_median, 0) + '</strong><small>input / output tokens</small></td>' +
        '<td><strong>' + (m.peak_sampled_vram_mb == null ? "—" : number(m.peak_sampled_vram_mb, 0) + " MB") + '</strong><small>' + relativeChange(m, "peak_sampled_vram_mb") + ' vs baseline</small></td>' +
        '<td><strong>' + bytes(m.peak_sampled_system_ram_bytes) + '</strong><small>system-wide peak · ' + relativeChange(m, "peak_sampled_system_ram_bytes") + '</small></td>' +
        '<td><strong>' + number(m.peak_sampled_gpu_utilization_pct, 0) + '%</strong><small>peak sampled</small><small>' + number(m.peak_sampled_gpu_power_w, 1) + ' W · ' + number(m.peak_sampled_gpu_temperature_c, 0) + ' °C</small></td>' +
        '<td><strong>' + (m.gpu_energy_j_median_estimate == null ? "Unavailable" : number(m.gpu_energy_j_median_estimate, 2) + " J") + '</strong><small>' + (m.gpu_energy_estimated_trials == null ? "0" : m.gpu_energy_estimated_trials) + "/" + (m.gpu_energy_total_completed_trials == null ? "0" : m.gpu_energy_total_completed_trials) + " trials with estimate</small><small>' + relativeChange(m, "gpu_energy_j_median_estimate") + ' vs baseline</small></td>' +
        '<td><strong>' + number(m.completed_trials, 0) + '/' + number(m.attempted_trials, 0) + '</strong><small>' + number(m.failed_trials, 0) + ' failed</small><small>Load median ' + number(m.model_load_duration_median_s, 3) + ' s</small></td>' +
        '</tr>';
    }).join("");

    $("#performance-results").innerHTML =
      '<div class="table-scroll"><table class="results-table"><thead><tr><th>Model</th><th>Generation</th><th>Prompt processing</th><th>End-to-end latency</th><th>TTFT</th><th>Median tokens</th><th>Sampled VRAM peak</th><th>Sampled RAM peak</th><th>Sampled GPU peak</th><th>GPU energy estimate</th><th>Trials / loading</th></tr></thead><tbody>' +
      rows + '</tbody></table></div>' +
      '<p class="result-note">Percentage changes are raw numerical changes from the selected baseline. Negative latency change is usually better; positive tokens/s change is usually better. RAM/VRAM and GPU readings are sampled system/device measurements; energy is a device-wide estimate only where sample coverage passes the threshold.</p>' +
      '<details class="raw-details"><summary>Protocol, environment and raw trial data</summary><pre>' + escapeHtml(JSON.stringify({
        configuration: config,
        environment: env,
        interpretation_notes: result.interpretation_notes,
        errors: result.errors,
        telemetry_sample_count: (result.telemetry_samples || []).length,
        trials: result.trials
      }, null, 2)) + '</pre></details>';
  }

  function renderQuality(experiment) {
    const result = experiment.result || {};
    const summaries = result.summary_by_model;
    if (!summaries || !Object.keys(summaries).length) {
      $("#quality-summary-note").textContent = "Run completed, but no quality summary metrics were returned.";
      $("#quality-results").innerHTML = '<p class="empty">No quality summary returned. Inspect the saved raw run.</p>';
      return;
    }
    const baseline = result.baseline_model || "";
    $("#quality-summary-note").textContent =
      "Baseline: " + baseline + " · " + (result.trials || []).length + " attempted quality trials. Normalized text checks ignore casing and punctuation but do not assess semantic equivalence.";
    const rows = Object.keys(summaries).map((model) => {
      const m = summaries[model];
      return '<tr' + (model === baseline ? ' class="baseline-row"' : '') + '>' +
        '<td><strong>' + escapeHtml(model) + '</strong>' + (model === baseline ? '<small>BASELINE</small>' : '') + '</td>' +
        '<td><strong>' + pct(m.assertion_pass_rate) + '</strong></td>' +
        '<td><strong>' + pct(m.reference_exact_match_rate) + '</strong></td>' +
        '<td><strong>' + pct(m.baseline_exact_agreement_rate) + '</strong></td>' +
        '<td><strong>' + pct(m.repeat_consistency_rate) + '</strong><small>' + number(m.repeat_consistency_cases, 0) + ' case(s)</small></td>' +
        '<td><strong>' + number(m.failed_trials, 0) + ' / ' + number(m.total_trials, 0) + '</strong><small>' + pct(m.failure_rate) + ' request failures</small></td>' +
        '</tr>';
    }).join("");
    $("#quality-results").innerHTML =
      '<div class="table-scroll"><table class="results-table"><thead><tr><th>Model</th><th>Reference pass rate</th><th>Exact reference text</th><th>Baseline text agreement</th><th>Repeat consistency</th><th>Failed requests</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<p class="result-note">Reference pass rate depends on the chosen assertion and test set. Exact text agreement is not semantic similarity; request failure is not the same thing as an incorrect answer.</p>' +
      '<details class="raw-details"><summary>Reference cases and answer-by-answer results</summary><pre>' + escapeHtml(JSON.stringify({
        configuration: result.config || experiment.config,
        environment: result.environment,
        notes: result.notes,
        trials: result.trials
      }, null, 2)) + '</pre></details>';
  }

  function runType(kind) {
    return ({
      performance: "Performance",
      native_quality: "Quality",
      promptfoo: "Promptfoo",
      lm_eval: "LM Evaluation",
      imported_benchmark: "Imported result"
    })[kind] || kind || "Run";
  }

  async function refreshHistory() {
    try {
      const data = await api("/api/experiments?limit=100");
      state.experiments = data.experiments || [];
      renderHistory();
    } catch (error) {
      $("#history-rows").innerHTML = '<tr><td colspan="6" class="empty">Could not load saved runs: ' + escapeHtml(error.message) + '</td></tr>';
    }
  }

  function renderHistory() {
    const rows = state.experiments || [];
    if (!rows.length) {
      $("#history-rows").innerHTML = '<tr><td colspan="6" class="empty">No saved runs yet.</td></tr>';
      return;
    }
    $("#history-rows").innerHTML = rows.map((item) => {
      const config = item.config || {};
      const labels = (config.models || [config.model || config.filename || "—"]).join(", ");
      return '<tr><td><code>' + escapeHtml(item.id) + '</code></td><td>' + escapeHtml(runType(item.kind)) + '</td><td>' + escapeHtml(labels) + '</td><td><span class="state-badge ' + escapeHtml(item.status) + '">' + escapeHtml(item.status) + '</span></td><td>' + escapeHtml(dateLabel(item.created_at)) + '</td><td><button class="link-button" type="button" data-open-run="' + escapeHtml(item.id) + '">Inspect</button></td></tr>';
    }).join("");
    $("#history-rows").querySelectorAll("[data-open-run]").forEach((button) => {
      button.addEventListener("click", () => inspectRun(button.dataset.openRun));
    });
  }

  async function inspectRun(id) {
    try {
      const data = await api("/api/experiments/" + encodeURIComponent(id));
      const experiment = data.experiment;
      $("#run-detail-title").textContent = runType(experiment.kind) + " · " + experiment.id + " · " + experiment.status;
      $("#run-detail-json").textContent = JSON.stringify({
        id: experiment.id,
        kind: experiment.kind,
        status: experiment.status,
        created_at: experiment.created_at,
        started_at: experiment.started_at,
        finished_at: experiment.finished_at,
        config: experiment.config,
        error: experiment.error,
        result: experiment.result
      }, null, 2);
      $("#run-detail").classList.remove("hidden");
      $("#run-detail").open = true;
    } catch (error) {
      toast("Could not inspect run: " + error.message, true);
    }
  }

  async function exportResults() {
    try {
      const data = await api("/api/experiments-export");
      const file = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(file);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "llm-observatory-results.json";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast("Export failed: " + error.message, true);
    }
  }

  $("#start-performance").addEventListener("click", runPerformance);
  $("#start-quality").addEventListener("click", runQuality);
  $("#refresh-history").addEventListener("click", refreshHistory);
  $("#export-results").addEventListener("click", exportResults);
  $("#refresh-all").addEventListener("click", async () => {
    await Promise.all([refreshHealth(), refreshModels(), refreshTelemetry(), refreshHistory()]);
    toast("Connection, models and saved runs refreshed.");
  });

  async function init() {
    applyProfile("balanced");
    await Promise.all([refreshHealth(), refreshModels(), refreshTelemetry(), refreshHistory()]);
  }
  init();
})();
