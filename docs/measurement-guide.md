# Measurement Guide

**Purpose:** define exactly what LLM Observatory records, where each value comes from, how it is calculated, and what conclusions it supports.

> **Rule:** system/device telemetry is not automatically LLM-only usage. Report measurement scope beside results.

## 1. Summary

| Metric | Exact source / calculation | Scope |
|---|---|---|
| CPU utilization (%) | psutil.cpu_percent(interval=None) | Whole system |
| System RAM used / total / % | psutil.virtual_memory() → used, total, percent | Whole system |
| Ollama process RSS (bytes) | Sum of RSS for processes whose name contains "ollama" | Ollama processes, not weights-only |
| Ollama process CPU (%) | Sum of process CPU-percent values for matching Ollama processes | Ollama processes; sampling semantics depend on OS/psutil |
| GPU utilization (%) | First GPU row from nvidia-smi → utilization.gpu | Whole GPU/device |
| VRAM used / total (MB) | nvidia-smi → memory.used, memory.total | Whole GPU/device |
| GPU temperature (°C) | nvidia-smi → temperature.gpu | Whole GPU/device |
| GPU power / power limit (W) | nvidia-smi → power.draw, power.limit | Instantaneous device power / reported limit |
| GPU SM clock (MHz) | nvidia-smi → clocks.current.sm | Whole GPU/device |
| Ollama allocation / VRAM allocation | Ollama GET /api/ps → size, size_vram | Runtime-reported loaded-model allocation |
| CPU-side allocation estimate | max(size - size_vram, 0) | Subtraction-based estimate; not a direct RAM measurement |
| Model file size | Ollama GET /api/tags → size | Stored model file |
| Quantization / parameter metadata | Ollama GET /api/tags and POST /api/show | Model metadata reported by Ollama |
| Prompt token count | Ollama final chat record → prompt_eval_count | One inference request |
| Output token count | Ollama final chat record → eval_count | One inference request |
| Prompt-processing duration | prompt_eval_duration / 1e9 | Runtime-reported seconds |
| Generation duration | eval_duration / 1e9 | Runtime-reported seconds |
| Prompt throughput | prompt_eval_count / (prompt_eval_duration / 1e9) | Prompt tokens/second |
| Generation throughput | eval_count / (eval_duration / 1e9) | Generated tokens/second |
| Model-load duration | load_duration / 1e9 | Runtime-reported seconds |
| Time to first token (TTFT) | Client time.perf_counter() at request start to first non-empty streamed content chunk | Client-observed seconds; includes local request/runtime delays |
| End-to-end stream latency | Client time.perf_counter() at request start to full stream completion | Client-observed seconds |
| Median / mean / p95 latency | Summary statistics over successful measured requests | A run's observed latency distribution |
| Median TTFT / prompt tok/s / generation tok/s | Median of valid values from successful requests | A run's observed distribution |
| Sampled peak RAM / VRAM | Maximum system RAM or device VRAM value among telemetry samples observed during that request's time window | Sampled system/device peak, not model-only peak |
| Telemetry sample count during request | Count of periodic sampler records timestamped within the request window | Indicates whether the sampling window captured any readings |
| Promptfoo assertion result | Configured contains, equals, or not-contains assertion against the expected phrase | Basic output regression check |
| LM Evaluation Harness score/artifacts | Selected task executed through the local OpenAI-compatible chat endpoint | Depends on task, harness version and adapter compatibility |
| Imported benchmark rows | Parsed CSV/JSON content saved as an external result | External data; not normalized automatically |

## 2. How a performance experiment runs

1. Select installed Ollama model tags and enter fixed prompts.
2. Configure repetitions, warm-up requests, temperature, context length, output-token limit, system prompt and telemetry sampling interval.
3. The runner processes models, prompts and repetitions **serially**. It sends each prompt as a fresh user message with the configured system prompt.
4. Warm-up requests are excluded from measured-trial summaries. With the default of one warm-up, the first request commonly warms/loads the model before measured requests.
5. For every measured request, capture a pre-request snapshot, timestamp the request, collect streamed output and Ollama's final timing/token statistics, then capture an after-request snapshot.
6. A separate telemetry sampler records system/GPU snapshots while the workload runs. The runner records the count of samples in the request window and peak sampled RAM/VRAM for that window.
7. Results and configuration are saved to SQLite. The full run contains trials, summaries, telemetry samples and interpretation notes.

### Performance formulas

All Ollama duration fields are reported in nanoseconds; the app converts to seconds by dividing by 1e9.

- **Prompt tokens/second** = prompt_eval_count / (prompt_eval_duration / 1e9)
- **Generation tokens/second** = eval_count / (eval_duration / 1e9)
- **TTFT** = first-content-chunk time − request-start time
- **Client latency** = stream-end time − request-start time
- Per-model summaries include completed trial count, median/mean/p95 client latency, median TTFT, and median/mean prompt and generation throughput where values are available.

Runtime-reported total_duration and client-observed client_latency_s are kept as separate fields because their start/end boundaries differ.

## 3. What the results mean — and do not mean

- **CPU/RAM are system-wide.** They include Windows, the browser, this dashboard and other processes. Ollama process RSS/CPU are closer to runtime attribution but include runtime overhead and may include more than one Ollama process.
- **GPU utilization, VRAM, temperature, power and clock are device-wide.** Browser acceleration, desktop composition and other GPU work can affect them. The current collector reads the first GPU row returned by nvidia-smi.
- **Ollama allocation is runtime-reported.** size and size_vram are useful allocation indicators, not a per-layer tensor trace. The CPU-side estimate is not proof of actual CPU RAM used exclusively by weights.
- **Sampled peaks can miss short spikes.** Sampling at one second is not a guarantee of observing the true maximum. Short requests may have zero telemetry samples inside their measured window.
- **TTFT is client-observed.** It includes local HTTP setup, queueing/scheduling, model-loading time if incurred, and runtime delay. It is not GPU-kernel start time.
- **Warm-up and model residency matter.** Ollama can keep models loaded. Control cold/warm conditions explicitly, check ollama ps, and avoid interpreting a warm run as a cold-start measurement. The current runner does not force a clean unload between variants.
- **Other applications can contaminate the result.** Minimize background work; record system state; repeat runs. A before/after difference is an observed association, not exact model-only attribution.
- **Observer overhead exists.** The telemetry sampler runs during the workload and consumes some resources.
- **Different runtimes are not interchangeable.** llama-bench measures llama.cpp, not the exact Ollama backend. Keep backend, version, GPU-offload and build settings with any imported result.

## 4. Not measured by this build

| Research variable | Status / next step |
|---|---|
| Energy per request / per token | **Not measured.** Integrate power over a defined request window and document baseline treatment. For whole-laptop energy, use a suitable external meter. |
| Total system energy | **Not measured.** Device GPU power is not wall power or whole-laptop energy. |
| Isolated LLM GPU utilization / power | **Not guaranteed.** Device-wide readings do not isolate Ollama; process-level GPU capability depends on driver/platform. |
| Exact peak model-weight memory / per-layer allocation | **Not measured.** Requires deeper runtime instrumentation/profiling. |
| Memory bandwidth / per-kernel timing | **Not measured.** Use compatible profiling tools where possible. |
| Separate first-token timestamp at the inference runtime | **Not measured.** Current TTFT is client-observed only. |
| Validated hallucination rate / factual reliability | **Not measured.** Promptfoo phrase assertions are not a general hallucination metric. Use a fixed reference-backed test set and validated scoring. |
| Statistical significance / confidence intervals | **Not calculated automatically.** Increase repeated trials and analyze variability/uncertainty. |
| Model-only RAM/VRAM contribution after idle subtraction | **Not claimed.** Baselines are diagnostic, not perfect attribution. |

## 5. Minimum protocol for a defensible quantization comparison

- Keep the base model family, prompt set, runtime, system prompt, context length, temperature, output-token cap and backend fixed wherever possible.
- Record exact model tags, quantization metadata, runtime/driver versions, hardware, settings, date, cold/warm state and background activity.
- Use the same prompts and sufficient repetitions for each variant. Report median and spread; do not rely on one run.
- Run quality evaluation separately from performance measurement so a grader does not compete for GPU/CPU resources.
- Use actual output quality scores alongside throughput, latency and memory; fewer bits do not automatically mean faster inference, lower energy or worse answers.
- Explicitly label every figure as **system-wide**, **device-wide**, **Ollama-process**, **runtime-reported**, **client-measured**, **derived estimate**, or **not measured**.
