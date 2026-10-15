# LLM Observatory

A local-first research workspace for **Performance and Reliability Analysis of Quantized Language Models on Edge Hardware**. It combines a purpose-built HTML/CSS/JavaScript interface with a small FastAPI backend for local Ollama requests, device telemetry, reproducible performance experiments, and optional external evaluation tools.

> **Status:** Research prototype. It has not been validated on every Windows/Ollama/NVIDIA configuration. Treat measurements according to the scope notes below; do not present them as model-only measurements unless they are genuinely isolated.

## Measurement reference

See [docs/measurement-guide.md](docs/measurement-guide.md) for the exact metrics, data sources, calculation formulas, attribution limits, and measurements this prototype does not yet provide.

## What it does

- **Model registry:** lists locally installed Ollama models and displays file size, family, parameter metadata and the quantization level reported by Ollama.
- **Hardware telemetry:** samples system CPU/RAM, NVIDIA GPU utilization, VRAM, temperature, clocks and instantaneous power where supported; reports Ollama process RSS/CPU and the model allocation returned by Ollama.
- **Performance benchmark:** runs serial, repeatable prompt trials against installed model variants. Records client-measured TTFT and end-to-end latency, Ollama prompt/generation token counts and durations, median/mean/p95 latency, token throughput, sampled peak memory, and a sampled GPU-device energy estimate when power-sample coverage is adequate. Energy is not model-isolated or whole-laptop energy.
- **Quality benchmark:** built-in local evaluator runs the same reference cases repeatedly across selected variants, scoring contains/equals/not-contains assertions, normalized exact-reference matches, baseline text agreement, repeated-answer consistency, and request failures. It does not claim semantic similarity or a validated hallucination rate.
- **Optional Promptfoo:** the external Promptfoo integration remains available via the API/tooling workflow for richer provider-based output assertions when Promptfoo or npx is installed.
- **Standard benchmarks:** optionally invokes the LM Evaluation Harness through Ollama's OpenAI-compatible chat endpoint for selected generation tasks where the installed task and harness support that interface.
- **External results:** imports CSV/JSON outputs, including llama-bench results. Imported results remain labeled separately because different runtimes and measurement protocols are not automatically comparable.
- **Persistent history:** saves experiment configuration, progress and results to local SQLite under data/observatory.sqlite3. Per-run files are stored under data/runs/.
- **Export:** exports the saved experiment history as JSON.

## Requirements

- Windows 10/11
- Python 3.10 or newer available through the Windows py launcher
- [Ollama for Windows](https://ollama.com/download/windows), running locally, with at least one model installed
- NVIDIA driver and nvidia-smi for NVIDIA telemetry (CPU/RAM features still work without NVIDIA telemetry)
- Node.js/npm for Promptfoo (optional)
- LM Evaluation Harness (optional; has additional dependencies)
- llama-bench and NVIDIA Nsight Systems (optional external tools)

## Start the dashboard

1. Start Ollama and verify it is working in PowerShell using the command: ollama list.
2. Clone/download this repository and open the project folder.
3. Double-click start_dashboard.bat. The launcher creates .venv, installs the dashboard dependencies and starts the local web server.
4. Open http://127.0.0.1:8501 if your browser does not open automatically.

Manual setup from PowerShell:

    py -3 --version
    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    .venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8501

The server binds to loopback (127.0.0.1) by default. Do not bind it to all network interfaces unless you have intentionally configured appropriate access controls. OLLAMA_HOST can override the local Ollama endpoint, for example http://127.0.0.1:11434.

## Run the first controlled comparison

1. In Ollama, install the quantized variants you intend to compare. For example, test Qwen2.5-1.5B-Instruct Q2_K and Q4_K_M.
2. Open **Performance lab** and select those installed variants.
3. Use the same fixed prompts, system prompt, temperature, context length and output-token cap.
4. Keep trials serial, leave warm-up requests out of the measured trials, and repeat each condition.
5. Save the run and inspect its result record. Review the interpretation notes before using numbers in a report.
6. Open **Quality checks** and run the same fixed reference cases separately from performance tests. Set at least 3 repetitions for a first reliability screen; choose the reference baseline explicitly; baseline agreement uses normalized text.

The built-in pilot prompts are examples, not a validated research dataset. Replace them with documented tasks and a reference-backed scoring protocol before making claims about factual reliability or hallucinations.

## Optional tools

### Optional Promptfoo quality checks

The built-in quality benchmark does not require Promptfoo. For the optional Promptfoo workflow/API integration, install Node.js, then install Promptfoo (or let the application use npx if it is available):

    npm install -g promptfoo
    promptfoo --version

Open **Quality evaluation** to choose installed Ollama model tags and define cases as one per line:

    What is the capital of Japan? || Tokyo
    How many sides does a triangle have? || three
    What is 7 multiplied by 8? || 56

Choose contains, equals, or not-contains. These assertions are useful for basic regression checks, but they are **not a validated hallucination metric**. Phrase matching can reject a correct paraphrase or pass an answer that contains the expected words plus incorrect claims. Use a broader fixed evaluation set and validate factuality scoring against trusted references or human review.

### LM Evaluation Harness

Install into the same Python environment in which the dashboard server runs:

    .venv\Scripts\python.exe -m pip install "lm_eval[api]"

Availability and dependency compatibility vary by version. The app uses the OpenAI-compatible chat-completions API. That adapter is generation-oriented and does not provide likelihood/log-probability scoring for every task. Check the chosen task's output type and the harness documentation before interpreting results. Large evaluation suites can take a long time; start with a low limit.

### llama-bench

llama-bench is an independent llama.cpp benchmark. It needs a compatible GGUF file and a llama.cpp build. Its metrics can be imported from CSV/JSON under **Results & reports**. Label these results with the backend and build options. Do not treat llama.cpp measurements as directly equivalent to Ollama measurements without controlling the runtime and configuration differences.

Documentation: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench

### NVIDIA Nsight Systems

Nsight Systems is an optional advanced profiler for investigating CPU/GPU execution timelines and potential bottlenecks. The dashboard detects whether nsys is on PATH but does not automatically launch a profiler session. Profiling can alter performance and should normally be conducted separately from clean benchmark trials.

Documentation: https://developer.nvidia.com/nsight-systems

## Measurement definitions and limitations

- **Time to first token (TTFT):** client-side elapsed time from initiating the local streaming request until the first non-empty content chunk arrives. It includes local HTTP/runtime scheduling and, when applicable, model loading. It is not a kernel-only measurement.
- **End-to-end request latency:** client-side time from sending the local streaming request until the stream is fully received.
- **Prompt/generation throughput and durations:** derived from token counts and nanosecond duration fields returned by Ollama. These are runtime-reported timings; they are kept distinct from client-observed latency.
- **CPU and RAM:** system-wide readings. Ollama-process CPU/RSS are process-level diagnostics, not clean per-model attribution.
- **GPU utilization, VRAM, power and temperature:** readings from nvidia-smi; they are device-wide and can include Chrome, the desktop compositor and other GPU processes.
- **Ollama model allocation:** the /api/ps size and size_vram fields are runtime-reported. The CPU-side value is a subtraction-based estimate, not a measured per-layer or weight-only allocation.
- **Peak sampled memory:** the sampler can miss brief peaks, especially for short requests. The number of samples that fell inside a request is recorded.
- **Energy:** performance trials now estimate GPU-device joules by trapezoidally integrating timestamped `nvidia-smi` power samples. An estimate is emitted only when at least two samples fall inside a request and at least 80% of the request window is covered by usable sample intervals. This is approximate device-wide energy, not isolated model energy or whole-laptop energy. Short requests may have no estimate. Use a suitable external meter for whole-laptop energy claims.
- **Memory bandwidth, GPU kernel time and isolated process GPU power:** not measured directly by this dashboard.
- **Reliability:** the native quality benchmark reports reference-assertion pass rate, normalized exact text match, normalized exact agreement with the first selected baseline model, repeat consistency and request failure rate. These are transparent screening metrics; they do not score semantic equivalence or determine a general hallucination rate.
- **Instrumentation overhead:** telemetry sampling and the dashboard consume some resources; its sampling interval and observer overhead should be documented.
- **Background activity:** minimize unrelated workloads and record their presence. A device-wide GPU increase cannot automatically be attributed exclusively to the LLM.

## Data and privacy

Prompts are sent to the configured local Ollama endpoint. Experiment records and generated artifacts are saved locally under data/. Review files before sharing them: prompts, outputs, model names and local filesystem paths may be research-sensitive. The server binds to loopback by default and does not include authentication intended for network exposure.

## Project layout

- app.py — local FastAPI API, Ollama integration, telemetry collection, experiment execution and SQLite persistence
- web/index.html — page structure
- web/styles.css — responsive UI design system
- web/app.js — navigation, charts, forms, polling and experiment result views
- requirements.txt — Python dependencies
- start_dashboard.bat — Windows launcher
- data/ — local SQLite database and run artifacts (ignored by Git)

## Research principle

The purpose of this tool is to make controlled comparisons easier, not to claim that lower quantization is always faster, lower-power or less reliable. Keep the base model, prompt dataset, runtime, context length, sampling settings, output budget and measurement method controlled; repeat trials; report variation; and describe the limits of each metric.
