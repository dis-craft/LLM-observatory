# LLM Observatory

A local observability and experimentation dashboard for language models served by [Ollama](https://ollama.com/). The project is intended as a learning and prototyping tool for **Performance and Reliability Analysis of Quantized Language Models on Edge Hardware**.

It brings live system telemetry, local-model chat, inference statistics, model metadata, and local Ollama configuration inspection into one browser-based interface.

> **Status:** Research prototype. It has not yet been validated against every Windows, Ollama, or NVIDIA driver configuration. Treat telemetry as observational and verify important measurements independently.

## Features

### Live telemetry
- CPU utilization and system RAM usage.
- NVIDIA GPU utilization, VRAM usage, temperature, and power draw when reported by the installed driver.
- Ollama process/model allocation information where available.
- Periodically refreshed charts for exploring resource changes while a model is loaded or generating.

### Chat and inference experiments
- Chat with models already installed in Ollama.
- Configure the system prompt and inference options exposed by the app, such as temperature, context length, and output-token limit.
- View per-request timing and token statistics returned by Ollama, where available, including prompt processing and generation throughput.

### Model inspector
- Inspect model tags, architecture and parameter metadata, quantization information, and the model's effective Modelfile/template where exposed by Ollama.

### Files and logs
- Inspect selected Ollama model/configuration metadata and relevant logs in standard locations.
- File visibility depends on the current Windows user permissions and the installed Ollama version.

## How this helps the research

A quantized-LLM study needs to relate the numerical representation of a model to both runtime efficiency and output quality. LLM Observatory helps with the exploratory stage:

1. Load different quantized variants of the same base model.
2. Run comparable prompts and workloads.
3. Observe memory, utilization, and response timing while the requests execute.
4. Inspect model metadata to verify which variant is loaded.
5. Use observations to identify follow-up experiments and hypotheses.

The dashboard is an **instrumentation and exploration tool**, not by itself a complete benchmark suite or a hallucination evaluator.

## Requirements

- Windows 10/11.
- Python 3.10 or newer.
- [Ollama for Windows](https://ollama.com/download/windows), running locally.
- An Ollama model already downloaded (for example, `qwen2.5:1.5b-instruct-q4_K_M`).
- NVIDIA driver and `nvidia-smi` for NVIDIA GPU telemetry. Without it, GPU-specific readings may be unavailable.
- Internet access for the first Python dependency installation if packages are not cached.

## Quick start (Windows)

1. Install and start Ollama from the official download page.
2. Download a model in PowerShell, for example:

   ```powershell
   ollama pull qwen2.5:1.5b-instruct-q4_K_M
   ```

3. Download or clone this repository.
4. Extract it, if downloaded as a ZIP.
5. Double-click `start_dashboard.bat`. The launcher creates a local Python virtual environment, installs the requirements, and starts the dashboard.
6. Open [http://localhost:8501](http://localhost:8501) if your browser does not open automatically.

If Windows blocks the batch file, open PowerShell in the project directory and run:

```powershell
py -3 --version
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

If the `py` launcher is unavailable, install Python from [python.org](https://www.python.org/downloads/windows/) and ensure it is available on your PATH.

## Verify local services

In PowerShell:

```powershell
ollama --version
ollama list
ollama ps
nvidia-smi
```

Ollama commonly serves its local API at `http://localhost:11434`. The dashboard needs the local Ollama service to be reachable. Do not expose the Ollama API or the Streamlit dashboard to an untrusted network.

## Research workflow suggestions

For a controlled exploratory comparison:

- Keep the base model, prompt set, context length, output limit, runtime, hardware, and sampling settings constant where possible.
- Compare the same model at multiple available quantization formats, such as Q2_K, Q4_K_M, Q8_0, and F16 when supported.
- Repeat each run and note warm-up conditions.
- Distinguish prompt-processing throughput from token-generation throughput.
- Record both model-file size and runtime RAM/VRAM; these are not the same measurement.
- Treat GPU utilization and power as device-level observations. Background applications can affect them.
- Validate any important results with a controlled benchmark or vendor profiling tools.

## Current limitations

- Device telemetry is sampled periodically; short bursts may occur between samples.
- GPU metrics depend on NVIDIA driver/tool support and are not guaranteed on every device.
- Device-wide GPU readings can include activity from applications other than Ollama.
- Ollama-reported allocation and processor-split details are estimates/status information, not a per-layer memory breakdown.
- System power or GPU power readings alone are not energy-per-inference measurements. A defensible energy measurement needs a defined measurement window and methodology.
- The app does not trace individual GPU kernels or every internal tensor allocation. Use NVIDIA Nsight Systems/Compute when kernel-level profiling is needed.
- The app does not provide a validated automatic factuality or hallucination benchmark; output-quality evaluation must be designed separately.
- Configuration/log paths and available metadata may differ by Ollama version, operating system and installation mode.

## Troubleshooting

**Ollama is unavailable**
- Start Ollama and retry.
- Run `ollama list` to confirm a model is installed.
- Verify that the local Ollama API endpoint is reachable.

**GPU readings are missing**
- Run `nvidia-smi` in PowerShell.
- Update/install the appropriate NVIDIA driver if necessary.
- Some telemetry fields may be unavailable on particular laptop GPUs or driver modes.

**A model is not fully on the GPU**
- Run `ollama ps` and inspect the processor allocation.
- The RTX 4050 Laptop GPU has limited VRAM; context/KV-cache and runtime overhead also consume memory.
- Partial CPU/GPU placement can be expected for models or configurations that exceed available VRAM.

**Installation fails**
- Confirm Python 3.10+ is installed.
- Re-run the launcher's dependency installation step and inspect the terminal output.

## Project layout

The main files are:

- `app.py` — Streamlit dashboard.
- `requirements.txt` — Python dependencies.
- `start_dashboard.bat` — Windows setup and launch helper.
- `README.md` — documentation.

## Privacy and security

The app is intended for local use. Prompts sent through the dashboard are passed to the configured local Ollama service. Keep the dashboard bound to localhost unless you understand and configure the access controls appropriate for your environment. Inspect local logs and configuration before sharing them; they may contain paths or other environment details.

## License

No license is implied by this README. Add an explicit `LICENSE` file if you intend to permit reuse or redistribution.
