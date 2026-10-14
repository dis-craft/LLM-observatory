# Ollama Observatory (Windows starter)

A local Streamlit dashboard for exploring Ollama-served language models while observing system and NVIDIA GPU telemetry. It is intended as a learning and prototyping tool for **Performance and Reliability Analysis of Quantized Language Models on Edge Hardware**.

> **Status:** Research prototype. It has not been validated against every Windows/Ollama/NVIDIA driver combination. Verify important measurements independently.

## Features

- **Live telemetry:** CPU and RAM usage; NVIDIA GPU utilization, VRAM, temperature and power when supported; Ollama-reported model allocation and processor placement.
- **Chat and experiments:** stream responses from Ollama; adjust the system prompt, temperature, context length and output-token limit; inspect prompt/generation speed and request metrics returned by Ollama.
- **Model inspector:** inspect model family, parameter metadata, quantization level, architecture metadata, Modelfile, template and available defaults.
- **Files and logs:** inspect selected readable configuration/log files and relevant environment values in standard Ollama locations.
- **Export:** download telemetry history and per-request metric tables as CSV.

## How it supports the research

Use one model at multiple quantization levels, keep prompts and runtime settings controlled, and observe how model size, memory, inference timing and output behaviour change. Observatory helps explore and debug the system; it is not itself a complete benchmark or a validated hallucination evaluator.

## Requirements

- Windows 10/11
- Python 3.10+ available through the Windows `py` launcher
- [Ollama for Windows](https://ollama.com/download/windows), running locally
- At least one Ollama model installed
- NVIDIA driver and `nvidia-smi` for NVIDIA telemetry (CPU/RAM views can work without it)
- Internet access for first-time Python dependency installation if packages are not cached

## Quick start

1. Install and launch Ollama.
2. In PowerShell, pull a model, for example:

   ```powershell
   ollama pull qwen2.5:1.5b-instruct-q4_K_M
   ollama list
   ollama ps
   nvidia-smi
   ```

3. Clone/download this repository and open its folder.
4. Double-click `start_dashboard.bat`.
5. If a browser does not open, visit [http://localhost:8501](http://localhost:8501).

The launcher creates `.venv`, installs `requirements.txt`, and starts Streamlit. Manual setup from PowerShell:

```powershell
py -3 --version
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

If `py` is unavailable, install Python from [python.org](https://www.python.org/downloads/windows/) and enable the launcher/PATH options.

## Suggested first experiment

1. Load a quantized Qwen model and view the Live telemetry tab.
2. Send a short prompt and then a longer prompt; observe resource changes.
3. Compare Q2_K and Q4_K_M variants using the same prompt, context length, output-token limit and temperature.
4. Inspect the per-request metrics and export the CSV.
5. Repeat trials and note warm-up conditions before drawing conclusions.

Keep base model, prompt, tokenizer, runtime, hardware, context, output length and sampling settings constant wherever possible. Model-file size is not the same as runtime RAM/VRAM. Repeat experiments and report variability.

## Important limitations

- Telemetry is sampled periodically; short bursts may be missed.
- GPU metrics are device-wide and can include other applications. Fields depend on driver/GPU support.
- Ollama-reported placement/allocation is not a per-layer memory trace.
- GPU power draw is not energy per inference. Energy requires a defined measurement interval/method, ideally including a stated idle-power treatment.
- The app does not trace individual GPU kernels or tensor allocations. Use NVIDIA Nsight Systems/Compute for deeper profiling.
- The app does not implement a validated hallucination/quality benchmark. Design a separate fixed evaluation set and scoring methodology.
- The telemetry chart and request metrics are session-oriented; they are not yet a full persistent experiment database.
- Ollama paths and available metadata differ across versions and installation modes. File inspection is limited to selected text/config/log files and may not include all installation files.

## Troubleshooting

**Ollama unavailable:** start Ollama and try `ollama list`. The default API endpoint is `http://127.0.0.1:11434`; `OLLAMA_HOST` can override it.

**GPU metrics unavailable:** run `nvidia-smi` in PowerShell and confirm the NVIDIA driver is installed. Some laptop telemetry fields may be unavailable.

**Model not fully on GPU:** check `ollama ps`. Available VRAM must accommodate model allocation, cache and runtime overhead; partial CPU/GPU placement can be normal on memory-constrained devices.

**Dependency/startup failure:** check Python 3.10+ and inspect the console output from `start_dashboard.bat`.

## Privacy and security

Designed for local use. Chat prompts are sent to the configured local Ollama service. Keep Streamlit bound to localhost unless you have deliberately configured secure access. Review logs/environment data before sharing them because they may contain local paths or other environment information.

## Project layout

- `app.py` — Streamlit dashboard
- `requirements.txt` — Python dependencies
- `start_dashboard.bat` — Windows setup/launcher
- `README.md` — this guide

## License

No license is implied. Add an explicit `LICENSE` file if reuse/redistribution should be permitted.
