from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psutil
import requests
import streamlit as st

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
REQUEST_TIMEOUT = 3

st.set_page_config(
    page_title="Ollama Observatory",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.3rem; }
      [data-testid="stMetricValue"] { font-size: 1.55rem; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("🔬 Ollama Observatory")
st.caption("Local LLM experimentation · hardware telemetry · model inspection")


def ollama_get(path: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(f"{DEFAULT_HOST}{path}", params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def ollama_post(path: str, payload: dict[str, Any], stream: bool = False):
    return requests.post(
        f"{DEFAULT_HOST}{path}", json=payload, timeout=(REQUEST_TIMEOUT, None), stream=stream
    )


def run_command(args: list[str], timeout: int = 5) -> str | None:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def gpu_snapshot() -> dict[str, Any] | None:
    query = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
        "--format=csv,noheader,nounits",
    ]
    output = run_command(query, timeout=3)
    if not output:
        return None
    line = output.splitlines()[0]
    fields = [part.strip() for part in line.split(",")]
    if len(fields) < 7:
        return None

    def to_float(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "name": fields[0],
        "gpu_util_pct": to_float(fields[1]),
        "vram_used_mb": to_float(fields[2]),
        "vram_total_mb": to_float(fields[3]),
        "gpu_temp_c": to_float(fields[4]),
        "gpu_power_w": to_float(fields[5]),
        "gpu_power_limit_w": to_float(fields[6]),
    }


def collect_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=None)
    ollama_process_mb = 0.0
    ollama_process_cpu_pct = 0.0
    for proc in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "ollama" in name:
                info = proc.info.get("memory_info")
                if info:
                    ollama_process_mb += info.rss / (1024**2)
                ollama_process_cpu_pct += float(proc.info.get("cpu_percent") or 0.0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    gpu = gpu_snapshot()
    loaded = None
    try:
        loaded = ollama_get("/api/ps")
    except requests.RequestException:
        pass
    models = (loaded or {}).get("models", [])
    allocated = sum(float(m.get("size", 0) or 0) for m in models)
    vram_allocated = sum(float(m.get("size_vram", 0) or 0) for m in models)
    placement = []
    for model in models:
        size = float(model.get("size", 0) or 0)
        vram = float(model.get("size_vram", 0) or 0)
        cpu_size = max(size - vram, 0)
        if size > 0:
            placement.append({
                "name": model.get("name") or model.get("model") or "unknown",
                "size_gb": size / (1024**3),
                "vram_gb": vram / (1024**3),
                "cpu_side_gb_estimate": cpu_size / (1024**3),
                "expires_at": model.get("expires_at", ""),
            })
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "cpu_util_pct": cpu_percent,
        "ram_used_gb": vm.used / (1024**3),
        "ram_total_gb": vm.total / (1024**3),
        "ram_pct": vm.percent,
        "ollama_process_mb": ollama_process_mb,
        "ollama_process_cpu_pct": ollama_process_cpu_pct,
        "ollama_allocated_gb": allocated / (1024**3),
        "ollama_vram_allocated_gb": vram_allocated / (1024**3),
        "gpu": gpu or {},
        "loaded_models": placement,
    }


def bytes_text(value: Any) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def format_seconds_ns(ns: Any) -> str:
    try:
        return f"{float(ns) / 1e9:.3f} s"
    except (TypeError, ValueError):
        return "—"


def get_tags() -> list[dict[str, Any]]:
    try:
        return ollama_get("/api/tags").get("models", [])
    except requests.RequestException as exc:
        st.error(f"Cannot reach Ollama at {DEFAULT_HOST}: {exc}")
        return []


def get_show(model: str) -> dict[str, Any]:
    try:
        response = ollama_post("/api/show", {"model": model, "verbose": True})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.warning(f"Ollama could not return model details: {exc}")
        return {}


# Sidebar controls
st.sidebar.header("Connection & experiment")
st.sidebar.caption(f"Ollama endpoint: {DEFAULT_HOST}")
st.sidebar.markdown("Model tags and settings are read from your local Ollama service.")

try:
    tags = get_tags()
except Exception:
    tags = []
model_names = [m.get("name") or m.get("model") for m in tags if m.get("name") or m.get("model")]
if not model_names:
    st.warning("No Ollama models found. Start Ollama and pull a model, e.g. `ollama pull qwen2.5:1.5b-instruct-q4_K_M`.")
    st.stop()

default_model = next((n for n in model_names if "qwen2.5:1.5b-instruct-q4_K_M" in n), model_names[0])
selected_model = st.sidebar.selectbox("Model", model_names, index=model_names.index(default_model))
system_prompt = st.sidebar.text_area(
    "System prompt",
    value="You are a helpful assistant. Answer clearly and accurately.",
    height=110,
)
temperature = st.sidebar.slider("Temperature", 0.0, 2.0, 0.2, 0.1)
context_length = st.sidebar.select_slider("Context length", options=[512, 1024, 2048, 4096, 8192, 16384], value=2048)
max_tokens = st.sidebar.select_slider("Maximum output tokens", options=[32, 64, 128, 256, 512, 1024], value=256)
st.sidebar.caption("Context options depend on model/runtime support and available memory.")

# Persistent app state
if "telemetry" not in st.session_state:
    st.session_state.telemetry = []
if "chat" not in st.session_state:
    st.session_state.chat = []
if "request_metrics" not in st.session_state:
    st.session_state.request_metrics = []

# Tabs
tab_live, tab_chat, tab_model, tab_files = st.tabs(["Live telemetry", "Chat & experiments", "Model inspector", "Files & logs"])

with tab_live:
    st.subheader("Live hardware and Ollama state")
    poll_seconds = st.slider("Refresh interval (seconds)", 1, 5, 1, key="poll_seconds")
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=poll_seconds * 1000, key="telemetry_refresh")
    except ImportError:
        st.info("Auto-refresh component not installed. Restart or interact with the dashboard to refresh; install streamlit-autorefresh for periodic refresh.")
    snapshot = collect_snapshot()
    st.session_state.telemetry.append(snapshot)
    st.session_state.telemetry = st.session_state.telemetry[-300:]
    gpu = snapshot.get("gpu", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("CPU utilization", f"{snapshot['cpu_util_pct']:.1f}%")
    m2.metric("System RAM", f"{snapshot['ram_used_gb']:.2f} / {snapshot['ram_total_gb']:.2f} GB", f"{snapshot['ram_pct']:.1f}% used")
    m3.metric("GPU utilization", f"{gpu.get('gpu_util_pct'):.0f}%" if gpu.get("gpu_util_pct") is not None else "Unavailable")
    m4.metric("VRAM", f"{gpu.get('vram_used_mb', 0)/1024:.2f} / {gpu.get('vram_total_mb', 0)/1024:.2f} GB" if gpu.get("vram_total_mb") is not None else "Unavailable")
    m5, m6, m7, m8 = st.columns(4)
    m5.metric("GPU temperature", f"{gpu['gpu_temp_c']:.0f} °C" if gpu.get("gpu_temp_c") is not None else "Unavailable")
    m6.metric("GPU power", f"{gpu['gpu_power_w']:.1f} W" if gpu.get("gpu_power_w") is not None else "Unavailable")
    m7.metric("Ollama processes RSS", f"{snapshot['ollama_process_mb']:.0f} MB")
    m8.metric("Ollama-reported VRAM", f"{snapshot['ollama_vram_allocated_gb']:.2f} GB")
    st.caption("GPU readings are device-wide and may include other applications. Process RSS is not equal to model weights or GPU memory.")
    if snapshot["loaded_models"]:
        st.markdown("**Loaded model placement reported by Ollama**")
        st.dataframe(pd.DataFrame(snapshot["loaded_models"]), use_container_width=True, hide_index=True)
    else:
        st.info("Ollama reports no currently loaded model. Open the Chat tab and send a prompt, or run a model in another terminal.")
    history = pd.json_normalize(st.session_state.telemetry, sep=".")
    if not history.empty:
        history["timestamp"] = pd.to_datetime(history["timestamp"])
        st.markdown("**Recent telemetry history**")
        chart_cols = [c for c in ["cpu_util_pct", "ram_pct", "gpu.gpu_util_pct"] if c in history.columns]
        if chart_cols:
            st.line_chart(history.set_index("timestamp")[chart_cols], height=230)
        if "gpu.vram_used_mb" in history.columns:
            st.line_chart(history.set_index("timestamp")[["gpu.vram_used_mb"]], height=180)
    st.download_button("Download current telemetry history (CSV)", history.to_csv(index=False), "telemetry-history.csv", "text/csv")

with tab_chat:
    st.subheader("Chat with the selected local model")
    st.caption("Requests stream through Ollama's local API. Response statistics are shown when returned by Ollama.")
    for message in st.session_state.chat:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    user_prompt = st.chat_input("Ask your model something…")
    if user_prompt:
        st.session_state.chat.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": item["role"], "content": item["content"]} for item in st.session_state.chat[-12:])
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": context_length, "num_predict": max_tokens},
            "keep_alive": "10m",
        }
        response_text = ""
        latest_record: dict[str, Any] = {}
        started = time.perf_counter()
        with st.chat_message("assistant"):
            live_text = st.empty()
            try:
                with ollama_post("/api/chat", payload, stream=True) as response:
                    response.raise_for_status()
                    for raw_line in response.iter_lines(decode_unicode=True):
                        if not raw_line:
                            continue
                        event = json.loads(raw_line)
                        response_text += event.get("message", {}).get("content", "")
                        if response_text:
                            live_text.markdown(response_text + "▌")
                        if event.get("done"):
                            latest_record = event
                live_text.markdown(response_text or "*(No text returned.)*")
            except requests.RequestException as exc:
                response_text = f"Ollama request failed: {exc}"
                live_text.error(response_text)
        elapsed_s = time.perf_counter() - started
        if not response_text.startswith("Ollama request failed:"):
            st.session_state.chat.append({"role": "assistant", "content": response_text})
            prompt_n = latest_record.get("prompt_eval_count")
            eval_n = latest_record.get("eval_count")
            eval_duration = latest_record.get("eval_duration")
            prompt_duration = latest_record.get("prompt_eval_duration")
            metrics = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "model": selected_model,
                "temperature": temperature,
                "context_length": context_length,
                "max_output_tokens": max_tokens,
                "prompt_tokens": prompt_n,
                "generated_tokens": eval_n,
                "prompt_tokens_per_second": (prompt_n / (prompt_duration / 1e9)) if prompt_n and prompt_duration else None,
                "generation_tokens_per_second": (eval_n / (eval_duration / 1e9)) if eval_n and eval_duration else None,
                "prompt_eval_duration_s": prompt_duration / 1e9 if prompt_duration else None,
                "generation_duration_s": eval_duration / 1e9 if eval_duration else None,
                "total_duration_s": latest_record.get("total_duration", 0) / 1e9 if latest_record.get("total_duration") else elapsed_s,
                "model_load_duration_s": latest_record.get("load_duration", 0) / 1e9 if latest_record.get("load_duration") else None,
            }
            st.session_state.request_metrics.append(metrics)
            st.markdown("**Request metrics**")
            a, b, c, d = st.columns(4)
            a.metric("Prompt tokens", str(prompt_n) if prompt_n is not None else "—")
            b.metric("Output tokens", str(eval_n) if eval_n is not None else "—")
            bps = metrics["generation_tokens_per_second"]
            c.metric("Generation speed", f"{bps:.2f} tok/s" if bps is not None else "—")
            d.metric("Total duration", f"{metrics['total_duration_s']:.2f} s")
            with st.expander("Full request metrics (JSON)"):
                st.json(metrics)
    if st.session_state.request_metrics:
        st.markdown("**Requests in this session**")
        metric_df = pd.DataFrame(st.session_state.request_metrics)
        st.dataframe(metric_df, use_container_width=True, hide_index=True)
        st.download_button("Download request metrics (CSV)", metric_df.to_csv(index=False), "request-metrics.csv", "text/csv")

with tab_model:
    st.subheader("Model metadata and effective configuration")
    st.caption("Metadata shown here comes from Ollama's local API; not every field exists for every model.")
    if st.button("Refresh model details"):
        st.session_state.model_info_refresh = time.time()
    info = get_show(selected_model)
    if info:
        model_details = info.get("details", {})
        model_info = info.get("model_info", {})
        cols = st.columns(3)
        cols[0].metric("Model file size", bytes_text(next((m.get("size") for m in tags if (m.get("name") or m.get("model")) == selected_model), None)) if any((m.get("name") or m.get("model")) == selected_model for m in tags) else "—")
        cols[1].metric("Parameter size", model_details.get("parameter_size", "—"))
        cols[2].metric("Quantization", model_details.get("quantization_level", "—"))
        st.markdown("**Details**")
        st.json(model_details)
        st.markdown("**Architecture / model metadata**")
        st.json(model_info)
        for key in ("modelfile", "template", "system", "parameters", "license", "capabilities"):
            if key in info and info[key]:
                with st.expander(key.title()):
                    if isinstance(info[key], list):
                        st.code("\n".join(str(x) for x in info[key]))
                    else:
                        st.code(str(info[key]))
        with st.expander("Full /api/show response"):
            st.json(info)
    st.markdown("**Installed model tags**")
    st.dataframe(pd.DataFrame(tags), use_container_width=True, hide_index=True)

with tab_files:
    st.subheader("Selected local Ollama files and logs")
    st.warning("This tab reads selected files for inspection. Do not share logs or environment dumps without checking them for private paths or other sensitive details.")
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    candidate_dirs = [
        appdata / "Ollama",
        localappdata / "Ollama",
        home / ".ollama",
        Path(os.environ.get("OLLAMA_MODELS", home / ".ollama" / "models")),
    ]
    env_keys = ["OLLAMA_HOST", "OLLAMA_MODELS", "OLLAMA_ORIGINS", "CUDA_VISIBLE_DEVICES"]
    st.markdown("**Relevant environment variables**")
    env_values = {key: os.environ.get(key, "(not set in dashboard process)") for key in env_keys}
    st.json(env_values)
    st.markdown("**Known local directories**")
    st.dataframe(pd.DataFrame([{"path": str(p), "exists": p.exists(), "directory": p.is_dir()} for p in candidate_dirs]), use_container_width=True, hide_index=True)
    files_found = []
    for base in candidate_dirs:
        if base.is_dir():
            try:
                for path in list(base.rglob("*"))[:300]:
                    if path.is_file() and (path.suffix.lower() in {".log", ".txt", ".json", ".yaml", ".yml", ".ini", ".toml"} or path.name.lower() in {"modelfile", "config"}):
                        try:
                            if path.stat().st_size <= 1_000_000:
                                files_found.append(path)
                        except OSError:
                            pass
            except OSError:
                pass
    files_found = list(dict.fromkeys(files_found))[:200]
    if files_found:
        labels = [str(p) for p in files_found]
        choice = st.selectbox("Select a file to inspect", labels)
        selected_path = Path(choice)
        try:
            content = selected_path.read_text(encoding="utf-8", errors="replace")
            st.caption(f"{selected_path.stat().st_size:,} bytes · {selected_path}")
            st.code(content[-30000:] if len(content) > 30000 else content, language="text")
        except OSError as exc:
            st.error(f"Could not read this file: {exc}")
    else:
        st.info("No readable text configuration/log files were found in the standard locations scanned. Ollama's model blobs are binary and are not displayed as text.")
    st.markdown("**Process and installation information**")
    st.code(json.dumps({"python": os.sys.version, "platform": os.name, "ollama_host": DEFAULT_HOST, "nvidia_smi_path": run_command(["where", "nvidia-smi"])}, indent=2))

st.divider()
st.caption("Observatory is a local research prototype. Device telemetry is sampled, GPU metrics may be device-wide, and per-layer/kernel tracing requires dedicated profiling tools.")
