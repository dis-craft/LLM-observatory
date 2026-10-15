# Benchmark Protocol

This protocol defines what a result from LLM Observatory means. It is a controlled local experiment, not an MLPerf-compliant submission.

## Research question

For the same base language model, what changes when the weights are represented using different quantization formats? Compare quality and deployment cost separately. Do not assume smaller quantized files are automatically faster, more accurate, or more energy efficient.

## Basis of comparison

Each comparison needs four explicit pieces:

1. **Reference:** select the baseline model in the UI. Quantized model results show percentage changes against this baseline.
2. **Workload:** use the same prompts and workload profile for every selected model.
3. **Controls:** keep hardware, runtime, system prompt, context limit, output cap, temperature and warm-up/repetition settings fixed. Record model tags and quantization metadata.
4. **Repetition:** run several measured repetitions. Report distributions, not a single best run. The runner warms each selected model, then pairs models on each prompt and repetition, alternating model order on successive repetitions. This reduces simple order bias but cannot remove thermal drift or background interference; repeat important comparisons with a different model-selection order.

## Included workload profiles

- **Balanced edge workload:** three short, mixed questions; a quick general-purpose snapshot.
- **Prompt processing:** longer synthetic log context, short output cap; useful for examining prompt-prefill behaviour. This is a generated test workload, not a real external dataset.
- **Generation:** short instruction, higher output-token cap; useful for examining decode behaviour. The model may stop early, so use the actual output-token count.
- **Long-context retrieval:** a longer context with a known lookup answer; useful for prompt-length and retrieval experiments. Score correctness separately in Quality checks.
- **Custom prompts:** the researcher's own fixed workload.

The text-based presets are reproducible prompts, **not exact token-length guarantees**. Prefill, retrieval and long-synthesis presets use synthetic log records; they are not real or externally sourced operational data. Token counts vary by tokenizer and include the actual request formatting. Review recorded prompt/output token counts before interpreting one run as a particular token-length class.

## Performance metrics and calculations

- **TTFT:** client time from request start until the first non-empty output chunk arrives.
- **End-to-end latency:** client time from request start until the full response stream finishes.
- **Prompt throughput:** runtime-reported prompt tokens divided by runtime-reported prompt-evaluation duration.
- **Generation throughput:** runtime-reported generated tokens divided by runtime-reported generation duration.
- **Model load duration:** load duration reported by Ollama; the runner does not force an unload before every trial.
- **Memory:** model file size is read from Ollama; current and peak sampled RAM/VRAM are whole-system/device samples. Ollama runtime allocation is also recorded separately when available.
- **GPU energy estimate:** trapezoidal integration of device-wide `nvidia-smi` power readings. An estimate is displayed only if at least two readings are inside the request window and usable intervals cover at least 80% of the request duration. It is not isolated model energy or whole-laptop energy; concurrent GPU work and sampling gaps can affect it.
- **Baseline change:** `(model metric - baseline metric) / abs(baseline metric) × 100%`. Negative latency change means less latency; positive tokens/second change means higher throughput. The sign is the raw numerical change, so interpret it with the direction of each metric.
- **Variability:** report median, mean and p95 client latency, median TTFT, standard deviation across all successful trials, and average within-prompt standard deviation where at least two repetitions exist. Overall standard deviation mixes prompt difficulty with run-to-run variation; within-prompt standard deviation better isolates observed repetition spread. Confidence intervals and statistical significance are not calculated automatically.

## Quality and reliability

Use the separate Quality checks page with the exact same reference cases and settings across variants. It reports assertion pass rate, normalized exact-text match, agreement with the explicitly selected baseline, repeat consistency, and request failure rate.

These are deliberately named text/reference metrics. They are not semantic similarity scores and do not constitute a validated hallucination rate. A contains assertion can miss a wrong answer that happens to mention the reference phrase, or reject a valid paraphrase. Use a curated dataset, suitable scoring and manual review of a sample before making research claims.

For broader evaluations, the optional [LM Evaluation Harness](https://github.com/EleutherAI/lm-evaluation-harness) supports multiple task datasets, but every task/backend combination must be checked for scoring compatibility. [MLPerf Inference Edge](https://mlcommons.org/benchmarks/inference-edge/) provides scenario-specific datasets, quality targets and measurement rules for standard comparisons. [llama-bench](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench) is useful for separating prompt processing from generation on llama.cpp, but its numbers must not be silently mixed with Ollama results because the runtime differs.

## What this tool does not establish

- It does not isolate GPU activity or power to the LLM process.
- It does not measure whole-laptop energy without an external power measurement.
- It does not measure semantic equivalence or a general hallucination rate.
- It does not automatically randomize request order, unload/reload every model, or compute confidence intervals.
- It does not provide concurrent-server throughput testing; the built-in runner is serial and primarily represents single-request/edge use.

## Minimum defensible procedure

1. Verify model family, parameter count, quantization format, runtime version and device.
2. Select the full-precision/higher-precision reference available to you and the quantized variants derived from the same base model.
3. Choose one profile and keep it fixed; use matched generation settings.
4. Run at least one warm-up and at least 5 measured repetitions per prompt/model for initial analysis; increase trials if variability is high.
5. Run quality evaluations separately from performance trials to avoid grading workloads interfering with timings.
6. Review actual input/output token counts, sample count, errors, memory scope and energy coverage.
7. Report values and deltas against the selected baseline, and disclose missing/low-coverage measurements.
8. Repeat in reversed model selection order to see whether ordering and thermal drift change the conclusion.

## References

- [MLPerf Inference Edge](https://mlcommons.org/benchmarks/inference-edge/)
- [llama-bench documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench)
- [LM Evaluation Harness](https://github.com/EleutherAI/lm-evaluation-harness)
