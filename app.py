from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
DB_PATH = DATA_DIR / "observatory.sqlite3"
for directory in (DATA_DIR, RUNS_DIR, WEB_DIR):
    directory.mkdir(parents=True, exist_ok=True)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_HOST.startswith(("http://", "https://")):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
REQUEST_TIMEOUT = 5

app = FastAPI(title="LLM Observatory", version="2.0.0")
app.mount("/assets", StaticFiles(directory=str(WEB_DIR)), name="assets")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def db_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db_connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                progress REAL NOT NULL DEFAULT 0,
                config_json TEXT NOT NULL,
                result_json TEXT,
                error TEXT
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_experiments_created ON experiments(created_at DESC)")


init_db()


def db_update(experiment_id: str, **values: Any) -> None:
    if not values:
        return
    allowed = {"status", "started_at", "finished_at", "progress", "result_json", "error"}
    fields = {key: value for key, value in values.items() if key in allowed}
    if not fields:
        return
    assignments = ", ".join(key + " = ?" for key in fields)
    with db_connect() as db:
        db.execute(
            "UPDATE experiments SET " + assignments + " WHERE id = ?",
            [*fields.values(), experiment_id],
        )


def db_create(experiment_id: str, kind: str, config: dict[str, Any]) -> None:
    with db_connect() as db:
        db.execute(
            "INSERT INTO experiments (id, kind, status, created_at, progress, config_json) VALUES (?, ?, ?, ?, ?, ?)",
            (experiment_id, kind, "queued", now_iso(), 0, json.dumps(config)),
        )


def db_get(experiment_id: str) -> dict[str, Any] | None:
    with db_connect() as db:
        row = db.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
    return row_to_dict(row) if row else None


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key in ("config_json", "result_json"):
        raw = item.pop(key, None)
        try:
            item["config" if key == "config_json" else "result"] = json.loads(raw) if raw else None
        except (TypeError, json.JSONDecodeError):
            item["config" if key == "config_json" else "result"] = None
    return item


def db_list(limit: int = 100) -> list[dict[str, Any]]:
    with db_connect() as db:
        rows = db.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(row) for row in rows]


def ollama_get(path: str, timeout: float = REQUEST_TIMEOUT) -> Any:
    try:
        response = requests.get(OLLAMA_HOST + path, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Cannot reach Ollama at " + OLLAMA_HOST + ". Start Ollama and try again. " + str(exc))


def list_model_tags() -> list[dict[str, Any]]:
    data = ollama_get("/api/tags")
    items = []
    for model in data.get("models", []):
        details = model.get("details") or {}
        items.append({
            "name": model.get("name") or model.get("model") or "unknown",
            "digest": model.get("digest", ""),
            "size_bytes": model.get("size"),
            "modified_at": model.get("modified_at"),
            "family": details.get("family"),
            "families": details.get("families") or [],
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "format": details.get("format"),
        })
    return items


def gpu_snapshot() -> dict[str, Any] | None:
    command = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,clocks.current.sm",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        row = next(csv.reader([completed.stdout.strip().splitlines()[0]], skipinitialspace=True))
    except (csv.Error, IndexError):
        return None
    while len(row) < 8:
        row.append("N/A")

    def number(value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (ValueError, TypeError):
            return None

    return {
        "name": row[0].strip(),
        "utilization_pct": number(row[1]),
        "memory_used_mb": number(row[2]),
        "memory_total_mb": number(row[3]),
        "temperature_c": number(row[4]),
        "power_w": number(row[5]),
        "power_limit_w": number(row[6]),
        "sm_clock_mhz": number(row[7]),
        "scope": "device-wide; may include other applications",
    }


def collect_telemetry() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=None)
    ollama_rss = 0
    ollama_cpu = 0.0
    process_count = 0
    for proc in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "ollama" in name:
                process_count += 1
                info = proc.info.get("memory_info")
                if info:
                    ollama_rss += info.rss
                ollama_cpu += float(proc.info.get("cpu_percent") or 0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    loaded_models = []
    total_allocated = 0
    total_vram_allocated = 0
    try:
        response = requests.get(OLLAMA_HOST + "/api/ps", timeout=2)
        response.raise_for_status()
        loaded = response.json().get("models", [])
        for model in loaded:
            size = int(model.get("size") or 0)
            vram = int(model.get("size_vram") or 0)
            total_allocated += size
            total_vram_allocated += vram
            loaded_models.append({
                "name": model.get("name") or model.get("model") or "unknown",
                "size_bytes": size,
                "vram_bytes": vram,
                "cpu_side_estimate_bytes": max(size - vram, 0),
                "scope": "runtime-reported allocation; CPU-side figure is an estimate",
            })
    except requests.RequestException:
        pass

    return {
        "timestamp": now_iso(),
        "monotonic_s": time.perf_counter(),
        "cpu_utilization_pct": cpu_pct,
        "ram_used_bytes": vm.used,
        "ram_total_bytes": vm.total,
        "ram_utilization_pct": vm.percent,
        "ollama_process_rss_bytes": ollama_rss,
        "ollama_process_cpu_pct": ollama_cpu,
        "ollama_process_count": process_count,
        "ollama_allocated_bytes": total_allocated,
        "ollama_vram_allocated_bytes": total_vram_allocated,
        "loaded_models": loaded_models,
        "gpu": gpu_snapshot(),
        "measurement_notes": [
            "CPU, RAM and NVIDIA GPU readings are sampled device/system values, not isolated per-request consumption.",
            "Ollama process RSS includes runtime overhead and is not equal to model-weight memory.",
            "Ollama allocation values are reported by the runtime and are not a per-layer trace.",
            "GPU power is instantaneous power; this app does not infer joules per request from a single reading.",
        ],
    }


def tool_status() -> dict[str, Any]:
    promptfoo = shutil.which("promptfoo")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    lm_eval = shutil.which("lm_eval") or shutil.which("lm_eval.exe")
    llama_bench = shutil.which("llama-bench") or shutil.which("llama-bench.exe")
    nsys = shutil.which("nsys") or shutil.which("nsys.exe")
    node = shutil.which("node") or shutil.which("node.exe")
    try:
        requests.get(OLLAMA_HOST + "/api/version", timeout=2).raise_for_status()
        ollama_ok = True
        version_data = requests.get(OLLAMA_HOST + "/api/version", timeout=2).json()
        ollama_version = version_data.get("version")
    except requests.RequestException:
        ollama_ok = False
        ollama_version = None
    try:
        model_count = len(list_model_tags()) if ollama_ok else 0
    except HTTPException:
        model_count = 0
    return {
        "ollama": {"available": ollama_ok, "version": ollama_version, "host": OLLAMA_HOST, "models": model_count},
        "nvidia_smi": {"available": gpu_snapshot() is not None},
        "node": {"available": bool(node)},
        "promptfoo": {"available": bool(promptfoo), "command": promptfoo, "npx_available": bool(npx), "install": "npm install -g promptfoo"},
        "lm_eval": {"available": bool(lm_eval), "command": lm_eval, "install": "python -m pip install 'lm_eval[api]'"},
        "llama_bench": {"available": bool(llama_bench), "command": llama_bench, "install": "Build llama.cpp or install a compatible llama-bench binary"},
        "nsight_systems": {"available": bool(nsys), "command": nsys, "install": "Install NVIDIA Nsight Systems for Windows"},
    }


def normalize_answer(value: str) -> str:
    """Normalize casing, punctuation and whitespace for exact-text comparisons."""
    return " ".join(re.sub(r"[^\w\s]", " ", (value or "").casefold()).split())


def reference_assertion_passes(output: str, expected: str, assertion: str) -> bool:
    actual_norm = normalize_answer(output)
    expected_norm = normalize_answer(expected)
    if not expected_norm:
        return False
    if assertion == "contains":
        return expected_norm in actual_norm
    if assertion == "equals":
        return actual_norm == expected_norm
    if assertion == "not-contains":
        return expected_norm not in actual_norm
    raise ValueError("Unsupported assertion: " + assertion)


def estimate_gpu_energy_joules(
    points: list[dict[str, Any]],
    start_monotonic: float,
    end_monotonic: float,
    max_gap_s: float,
) -> dict[str, Any]:
    """Estimate device-wide GPU energy by integrating sampled power over a request window.

    This is an estimate from nvidia-smi samples, not model-isolated energy. It is
    returned only when at least two samples fall inside the request and at least
    80% of the interval can be interpolated across sufficiently close samples.
    """
    duration = end_monotonic - start_monotonic
    if duration <= 0:
        return {"energy_j": None, "coverage_fraction": 0.0, "sample_count": 0}

    readings: dict[float, float] = {}
    for point in points:
        timestamp = point.get("monotonic_s")
        gpu = point.get("gpu") or {}
        power = gpu.get("power_w")
        if isinstance(timestamp, (int, float)) and isinstance(power, (int, float)) and math.isfinite(power):
            readings[float(timestamp)] = float(power)
    ordered = sorted(readings.items())
    inside_count = sum(start_monotonic <= timestamp <= end_monotonic for timestamp, _ in ordered)
    energy = 0.0
    covered = 0.0

    for (t0, p0), (t1, p1) in zip(ordered, ordered[1:]):
        gap = t1 - t0
        left = max(start_monotonic, t0)
        right = min(end_monotonic, t1)
        if right <= left or gap <= 0 or gap > max_gap_s:
            continue
        power_left = p0 + (p1 - p0) * ((left - t0) / gap)
        power_right = p0 + (p1 - p0) * ((right - t0) / gap)
        energy += (power_left + power_right) * 0.5 * (right - left)
        covered += right - left

    coverage = min(1.0, covered / duration)
    valid = inside_count >= 2 and coverage >= 0.8
    return {
        "energy_j": energy if valid else None,
        "coverage_fraction": coverage,
        "sample_count": inside_count,
        "method": "trapezoidal integration of device-wide nvidia-smi power samples",
        "scope": "GPU device-wide estimate; not model-isolated or whole-laptop energy",
    }


def summarize_quality_trials(
    trials: list[dict[str, Any]],
    models: list[str],
    case_count: int,
    repetitions: int,
    baseline_model: str | None = None,
) -> dict[str, Any]:
    baseline = baseline_model if baseline_model in models else (models[0] if models else None)
    baseline_outputs = {
        (row["case_index"], row["repetition"]): normalize_answer(row.get("output", ""))
        for row in trials
        if row.get("model") == baseline and row.get("status") == "completed"
    }
    summaries: dict[str, Any] = {}
    for model in models:
        subset = [row for row in trials if row.get("model") == model]
        completed = [row for row in subset if row.get("status") == "completed"]
        baseline_pairs = [
            row for row in completed
            if (row.get("case_index"), row.get("repetition")) in baseline_outputs
        ]
        consistency_values = []
        if repetitions > 1:
            for case_index in range(case_count):
                answers = [
                    normalize_answer(row.get("output", ""))
                    for row in completed if row.get("case_index") == case_index
                ]
                if len(answers) >= 2:
                    counts: dict[str, int] = {}
                    for answer in answers:
                        counts[answer] = counts.get(answer, 0) + 1
                    consistency_values.append(max(counts.values()) / len(answers))
        summaries[model] = {
            "total_trials": len(subset),
            "completed_trials": len(completed),
            "failed_trials": len(subset) - len(completed),
            "failure_rate": (len(subset) - len(completed)) / len(subset) if subset else None,
            "assertion_pass_rate": sum(row.get("passed") is True for row in subset) / len(subset) if subset else None,
            "reference_exact_match_rate": (
                sum(row.get("reference_exact_match") is True for row in completed) / len(completed)
                if completed else None
            ),
            "baseline_exact_agreement_rate": (
                sum(normalize_answer(row.get("output", "")) == baseline_outputs[(row["case_index"], row["repetition"])]
                    for row in baseline_pairs) / len(baseline_pairs)
                if baseline_pairs else None
            ),
            "repeat_consistency_rate": statistics.mean(consistency_values) if consistency_values else None,
            "repeat_consistency_cases": len(consistency_values),
            "baseline_model": baseline,
        }
    return summaries


def quantile(values: list[float], q: float) -> float | None:
    valid = sorted(v for v in values if math.isfinite(v))
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    pos = (len(valid) - 1) * q
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return valid[low]
    return valid[low] * (high - pos) + valid[high] * (pos - low)


def summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    def vals(key: str) -> list[float]:
        return [float(row[key]) for row in trials if isinstance(row.get(key), (int, float)) and math.isfinite(float(row[key]))]
    latencies = vals("client_latency_s")
    generation_speed = vals("generation_tokens_per_second")
    prompt_speed = vals("prompt_tokens_per_second")
    ttft = vals("time_to_first_token_s")
    prompt_counts = vals("prompt_tokens")
    output_counts = vals("output_tokens")
    prompt_durations = vals("prompt_eval_duration_s")
    generation_durations = vals("generation_duration_s")
    load_durations = vals("model_load_duration_s")
    sampled_vram = vals("peak_sampled_vram_mb")
    sampled_ram = vals("peak_sampled_ram_bytes")
    gpu_energy = vals("gpu_energy_j_estimate")
    return {
        "completed_trials": len(trials),
        "latency_median_s": statistics.median(latencies) if latencies else None,
        "latency_p95_s": quantile(latencies, 0.95),
        "latency_mean_s": statistics.mean(latencies) if latencies else None,
        "ttft_median_s": statistics.median(ttft) if ttft else None,
        "generation_tokens_per_second_median": statistics.median(generation_speed) if generation_speed else None,
        "prompt_tokens_per_second_median": statistics.median(prompt_speed) if prompt_speed else None,
        "generation_tokens_per_second_mean": statistics.mean(generation_speed) if generation_speed else None,
        "prompt_tokens_median": statistics.median(prompt_counts) if prompt_counts else None,
        "output_tokens_median": statistics.median(output_counts) if output_counts else None,
        "prompt_processing_duration_median_s": statistics.median(prompt_durations) if prompt_durations else None,
        "generation_duration_median_s": statistics.median(generation_durations) if generation_durations else None,
        "model_load_duration_median_s": statistics.median(load_durations) if load_durations else None,
        "peak_sampled_vram_mb": max(sampled_vram) if sampled_vram else None,
        "peak_sampled_system_ram_bytes": max(sampled_ram) if sampled_ram else None,
        "gpu_energy_j_median_estimate": statistics.median(gpu_energy) if gpu_energy else None,
        "gpu_energy_j_mean_estimate": statistics.mean(gpu_energy) if gpu_energy else None,
        "gpu_energy_estimated_trials": len(gpu_energy),
        "gpu_energy_total_completed_trials": len(trials),
    }


def stream_chat(model: str, prompt: str, system_prompt: str, temperature: float, context_length: int, max_tokens: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "keep_alive": "10m",
        "options": {"temperature": temperature, "num_ctx": context_length, "num_predict": max_tokens},
    }
    start = time.perf_counter()
    first_token_at: float | None = None
    output = ""
    final: dict[str, Any] = {}
    with requests.post(OLLAMA_HOST + "/api/chat", json=payload, stream=True, timeout=(5, 300)) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            event = json.loads(line)
            chunk = (event.get("message") or {}).get("content") or ""
            if chunk:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                output += chunk
            if event.get("done"):
                final = event
    end = time.perf_counter()
    eval_count = final.get("eval_count")
    eval_duration = final.get("eval_duration")
    prompt_count = final.get("prompt_eval_count")
    prompt_duration = final.get("prompt_eval_duration")
    return {
        "output": output,
        "prompt_tokens": prompt_count,
        "output_tokens": eval_count,
        "prompt_eval_duration_s": (prompt_duration / 1e9) if isinstance(prompt_duration, (float, int)) else None,
        "generation_duration_s": (eval_duration / 1e9) if isinstance(eval_duration, (float, int)) else None,
        "server_total_duration_s": (final.get("total_duration") / 1e9) if isinstance(final.get("total_duration"), (float, int)) else None,
        "model_load_duration_s": (final.get("load_duration") / 1e9) if isinstance(final.get("load_duration"), (float, int)) else None,
        "prompt_tokens_per_second": (prompt_count / (prompt_duration / 1e9)) if prompt_count and prompt_duration else None,
        "generation_tokens_per_second": (eval_count / (eval_duration / 1e9)) if eval_count and eval_duration else None,
        "time_to_first_token_s": (first_token_at - start) if first_token_at is not None else None,
        "client_latency_s": end - start,
        "done_reason": final.get("done_reason"),
    }


class PerformanceRequest(BaseModel):
    models: list[str] = Field(min_length=1, max_length=8)
    prompts: list[str] = Field(min_length=1, max_length=30)
    repetitions: int = Field(default=5, ge=1, le=50)
    warmups: int = Field(default=1, ge=0, le=3)
    temperature: float = Field(default=0.0, ge=0, le=2)
    context_length: int = Field(default=2048, ge=512, le=16384)
    max_tokens: int = Field(default=128, ge=16, le=2048)
    system_prompt: str = "You are a helpful assistant. Answer the prompt clearly and accurately."
    sample_interval_s: float = Field(default=1.0, ge=0.5, le=5.0)


class PromptfooCase(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    expected: str = Field(min_length=1, max_length=2000)
    assertion: str = "contains"


class PromptfooRequest(BaseModel):
    models: list[str] = Field(min_length=1, max_length=8)
    cases: list[PromptfooCase] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.0, ge=0, le=2)
    context_length: int = Field(default=2048, ge=512, le=16384)
    max_tokens: int = Field(default=128, ge=16, le=2048)


class LMEvalRequest(BaseModel):
    model: str
    task: str = "gsm8k"
    limit: int = Field(default=25, ge=1, le=500)


class NativeEvaluationRequest(BaseModel):
    models: list[str] = Field(min_length=1, max_length=8)
    baseline_model: str
    cases: list[PromptfooCase] = Field(min_length=1, max_length=100)
    repetitions: int = Field(default=3, ge=1, le=10)
    temperature: float = Field(default=0.0, ge=0, le=2)
    context_length: int = Field(default=2048, ge=512, le=16384)
    max_tokens: int = Field(default=128, ge=16, le=2048)
    system_prompt: str = "You are a helpful assistant. Answer the prompt clearly and accurately."


class ImportRequest(BaseModel):
    filename: str
    content: str = Field(max_length=5_000_000)
    file_format: str = "json"


def ensure_valid_models(names: list[str]) -> None:
    available = {item["name"] for item in list_model_tags()}
    missing = [name for name in names if name not in available]
    if missing:
        raise HTTPException(status_code=400, detail="Models not installed in Ollama: " + ", ".join(missing))


def begin_job(kind: str, config: dict[str, Any], worker) -> str:
    experiment_id = uuid.uuid4().hex[:12]
    db_create(experiment_id, kind, config)

    def execute() -> None:
        db_update(experiment_id, status="running", started_at=now_iso(), progress=0)
        try:
            result = worker(experiment_id, config)
            db_update(experiment_id, status="completed", finished_at=now_iso(), progress=100,
                      result_json=json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            db_update(experiment_id, status="failed", finished_at=now_iso(), error=str(exc),
                      result_json=json.dumps({"error": str(exc)}))

    thread = threading.Thread(target=execute, name="observatory-" + kind, daemon=True)
    thread.start()
    return experiment_id


def performance_worker(experiment_id: str, config: dict[str, Any]) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    telemetry_samples: list[dict[str, Any]] = []
    stop_sampling = threading.Event()
    sample_lock = threading.Lock()
    total_units = len(config["models"]) * (config["warmups"] + len(config["prompts"]) * config["repetitions"])
    completed_units = 0

    def sampler() -> None:
        while not stop_sampling.is_set():
            try:
                sample = collect_telemetry()
                with sample_lock:
                    telemetry_samples.append(sample)
                    if len(telemetry_samples) > 2500:
                        del telemetry_samples[:500]
            except Exception:
                pass
            stop_sampling.wait(config["sample_interval_s"])

    sampler_thread = threading.Thread(target=sampler, name="observatory-telemetry", daemon=True)
    sampler_thread.start()
    errors: list[dict[str, Any]] = []
    try:
        for model in config["models"]:
            if config["warmups"] and config["prompts"]:
                for warm_idx in range(config["warmups"]):
                    try:
                        stream_chat(model, config["prompts"][0], config["system_prompt"], config["temperature"],
                                    config["context_length"], config["max_tokens"])
                    except Exception as exc:
                        errors.append({"model": model, "phase": "warmup", "error": str(exc)})
                    completed_units += 1
                    db_update(experiment_id, progress=min(95, completed_units / max(total_units, 1) * 100))
            for prompt_idx, prompt in enumerate(config["prompts"]):
                for repetition in range(config["repetitions"]):
                    before = collect_telemetry()
                    started_at = now_iso()
                    started_clock = time.perf_counter()
                    try:
                        metrics = stream_chat(model, prompt, config["system_prompt"], config["temperature"],
                                              config["context_length"], config["max_tokens"])
                        outcome = "completed"
                        error = None
                    except Exception as exc:
                        metrics = {}
                        outcome = "failed"
                        error = str(exc)
                        errors.append({"model": model, "prompt_index": prompt_idx, "repetition": repetition + 1, "error": error})
                    request_end_clock = time.perf_counter()
                    elapsed = request_end_clock - started_clock
                    after = collect_telemetry()
                    with sample_lock:
                        relevant = [
                            item for item in telemetry_samples
                            if isinstance(item.get("monotonic_s"), (int, float))
                            and started_clock <= item["monotonic_s"] <= request_end_clock
                        ]
                    energy = estimate_gpu_energy_joules(
                        [before, *relevant, after],
                        started_clock,
                        request_end_clock,
                        max(1.0, config["sample_interval_s"] * 2.0),
                    )
                    trial = {
                        "model": model,
                        "prompt_index": prompt_idx,
                        "prompt": prompt,
                        "repetition": repetition + 1,
                        "status": outcome,
                        "started_at": started_at,
                        "elapsed_wall_s": elapsed,
                        "before": before,
                        "after": after,
                        "sample_count_during_request": len(relevant),
                        "peak_sampled_vram_mb": max((s.get("gpu", {}).get("memory_used_mb") for s in relevant if s.get("gpu") and isinstance(s["gpu"].get("memory_used_mb"), (int, float))), default=None),
                        "peak_sampled_ram_bytes": max((s.get("ram_used_bytes") for s in relevant if isinstance(s.get("ram_used_bytes"), (int, float))), default=None),
                        "gpu_energy_j_estimate": energy["energy_j"],
                        "gpu_energy_coverage_fraction": energy["coverage_fraction"],
                        "gpu_energy_sample_count": energy["sample_count"],
                        "gpu_energy_scope": energy.get("scope"),
                        **metrics,
                    }
                    if error:
                        trial["error"] = error
                    trials.append(trial)
                    completed_units += 1
                    # Avoid serializing and writing the growing result set for every trial; this reduces observer overhead.
                    db_update(experiment_id, progress=min(99, completed_units / max(total_units, 1) * 100))
    finally:
        stop_sampling.set()
        sampler_thread.join(timeout=3)

    by_model = {}
    for model in config["models"]:
        subset = [row for row in trials if row["model"] == model and row["status"] == "completed"]
        by_model[model] = summarize_trials(subset)
    return {
        "config": config,
        "summary_by_model": by_model,
        "trials": trials,
        "errors": errors,
        "telemetry_samples": telemetry_samples,
        "interpretation_notes": [
            "Latency and token timing come from the Ollama response stream and response statistics.",
            "System and GPU telemetry are shared-device readings; they are not isolated to the model.",
            "The observer samples resources during the experiment and can introduce small measurement overhead.",
            "Estimated GPU-device energy is reported only when sampled power covers at least 80% of the request window and at least two samples fall inside it; it is not model-isolated or whole-laptop energy.",
            "Short requests may finish between telemetry samples; peak sampled memory can therefore miss brief spikes.",
            "Quality is not inferred from performance measurements. Run a quality evaluation separately.",
        ],
    }


def native_quality_worker(experiment_id: str, config: dict[str, Any]) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    total = len(config["models"]) * len(config["cases"]) * config["repetitions"]
    for model in config["models"]:
        for case_index, case in enumerate(config["cases"]):
            for repetition in range(1, config["repetitions"] + 1):
                row: dict[str, Any] = {
                    "model": model,
                    "case_index": case_index,
                    "repetition": repetition,
                    "question": case["question"],
                    "expected": case["expected"],
                    "assertion": case["assertion"],
                    "status": "failed",
                    "output": "",
                    "passed": False,
                    "reference_exact_match": False,
                }
                try:
                    metrics = stream_chat(
                        model, case["question"], config["system_prompt"], config["temperature"],
                        config["context_length"], config["max_tokens"],
                    )
                    output = metrics["output"]
                    if not output.strip():
                        raise RuntimeError("Model returned an empty answer")
                    row.update({
                        "status": "completed",
                        "output": output,
                        "passed": reference_assertion_passes(output, case["expected"], case["assertion"]),
                        "reference_exact_match": normalize_answer(output) == normalize_answer(case["expected"]),
                        "output_tokens": metrics.get("output_tokens"),
                        "time_to_first_token_s": metrics.get("time_to_first_token_s"),
                        "client_latency_s": metrics.get("client_latency_s"),
                        "generation_tokens_per_second": metrics.get("generation_tokens_per_second"),
                    })
                except Exception as exc:
                    row["error"] = str(exc)
                trials.append(row)
                db_update(experiment_id, progress=min(99, len(trials) / max(total, 1) * 100))
    return {
        "config": config,
        "baseline_model": config["baseline_model"],
        "summary_by_model": summarize_quality_trials(
            trials, config["models"], len(config["cases"]), config["repetitions"], config["baseline_model"]
        ),
        "trials": trials,
        "notes": [
            "Assertion pass rate measures only the chosen rule against each reference; it is not a general factuality or hallucination score.",
            "Exact reference match is normalized text equality (case, punctuation and whitespace normalized), not semantic equivalence.",
            "Baseline agreement is normalized exact-text agreement with the explicitly configured baseline model, not proof that either answer is correct.",
            "Repeat consistency is the share of a case's repeated completed answers matching its modal normalized answer. Use repetitions greater than one.",
            "Run quality evaluation separately from performance measurement to avoid resource contention.",
        ],
    }


def promptfoo_worker(experiment_id: str, config: dict[str, Any]) -> dict[str, Any]:
    run_dir = RUNS_DIR / experiment_id
    run_dir.mkdir(parents=True, exist_ok=True)
    promptfoo_config = {
        "description": "LLM Observatory quality evaluation " + experiment_id,
        "prompts": ["{{question}}"],
        "providers": [
            {
                "id": "ollama:chat:" + model,
                "config": {
                    "temperature": config["temperature"],
                    "num_ctx": config["context_length"],
                    "num_predict": config["max_tokens"],
                    "keep_alive": "10m",
                },
            }
            for model in config["models"]
        ],
        "tests": [
            {
                "vars": {"question": case["question"]},
                "assert": [{"type": case["assertion"], "value": case["expected"]}],
            }
            for case in config["cases"]
        ],
        "evaluateOptions": {"maxConcurrency": 1},
    }
    config_path = run_dir / "promptfooconfig.yaml"
    report_path = run_dir / "promptfoo-results.json"
    config_path.write_text(json.dumps(promptfoo_config, ensure_ascii=False, indent=2), encoding="utf-8")
    promptfoo = shutil.which("promptfoo")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if promptfoo:
        command = [promptfoo, "eval", "-c", str(config_path), "-o", str(report_path), "--no-progress-bar", "-j", "1"]
    elif npx:
        command = [npx, "--yes", "promptfoo", "eval", "-c", str(config_path), "-o", str(report_path), "--no-progress-bar", "-j", "1"]
    else:
        raise RuntimeError("Promptfoo is not installed and npx was not found. Install Node.js, then run: npm install -g promptfoo")
    env = os.environ.copy()
    env.setdefault("OLLAMA_BASE_URL", OLLAMA_HOST)
    completed = subprocess.run(command, cwd=str(run_dir), capture_output=True, text=True, timeout=1800,
                               env=env, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    parsed_report = None
    if report_path.exists():
        try:
            parsed_report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed_report = None
    result = {
        "config": config,
        "command_name": "promptfoo eval",
        "return_code": completed.returncode,
        "stdout_tail": completed.stdout[-12000:],
        "stderr_tail": completed.stderr[-12000:],
        "report_available": parsed_report is not None,
        "report_path": str(report_path) if report_path.exists() else None,
        "report": parsed_report,
        "notes": [
            "Assertions measure the checks defined in this evaluation, not a universal hallucination rate.",
            "A contains assertion is only a basic regression check. Use reference-backed tasks and human-validated judging for factuality claims.",
            "Keep quality grading separate from hardware performance runs to avoid resource contention.",
        ],
    }
    if completed.returncode != 0:
        raise RuntimeError("Promptfoo exited with code " + str(completed.returncode) + ". See experiment result output for the CLI logs. " + completed.stderr[-1500:])
    return result


def lm_eval_worker(experiment_id: str, config: dict[str, Any]) -> dict[str, Any]:
    executable = shutil.which("lm_eval") or shutil.which("lm_eval.exe")
    if not executable:
        raise RuntimeError("LM Evaluation Harness CLI was not found. Install with: python -m pip install 'lm_eval[api]'")
    output_dir = RUNS_DIR / experiment_id / "lm_eval"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        executable, "run",
        "--model", "local-chat-completions",
        "--model_args", "model=" + config["model"] + ",base_url=" + OLLAMA_HOST + "/v1,num_concurrent=1,max_retries=2",
        "--tasks", config["task"],
        "--limit", str(config["limit"]),
        "--output_path", str(output_dir),
        "--log_samples",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0:
        raise RuntimeError("lm_eval exited with code " + str(completed.returncode) + ". " + completed.stderr[-3000:])
    files = []
    for path in output_dir.rglob("*"):
        if path.is_file():
            files.append({"name": path.name, "size_bytes": path.stat().st_size})
    return {
        "config": config,
        "return_code": completed.returncode,
        "stdout_tail": completed.stdout[-12000:],
        "stderr_tail": completed.stderr[-12000:],
        "artifacts": files,
        "output_dir": str(output_dir),
        "notes": [
            "The OpenAI-compatible chat API path supports generation-style tasks, not likelihood-based metrics requiring logits or logprobs.",
            "Verify the selected task's output type and scoring protocol before interpreting its score.",
            "Run this benchmark separately from hardware performance trials to avoid contention.",
        ],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        response = requests.get(OLLAMA_HOST + "/api/version", timeout=2)
        response.raise_for_status()
        ollama = {"available": True, "version": response.json().get("version"), "host": OLLAMA_HOST}
    except requests.RequestException as exc:
        ollama = {"available": False, "version": None, "host": OLLAMA_HOST, "error": str(exc)}
    return {
        "app": {"name": "LLM Observatory", "version": app.version, "storage": "SQLite"},
        "ollama": ollama,
        "tools": tool_status(),
    }


@app.get("/api/models")
def models() -> dict[str, Any]:
    return {"models": list_model_tags()}


@app.get("/api/telemetry")
def telemetry() -> dict[str, Any]:
    return collect_telemetry()


@app.post("/api/chat")
def chat(body: dict[str, Any]) -> dict[str, Any]:
    model = str(body.get("model", "")).strip()
    if not model:
        raise HTTPException(status_code=400, detail="Select a model first.")
    ensure_valid_models([model])
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Enter a prompt.")
    try:
        result = stream_chat(
            model,
            prompt,
            str(body.get("system_prompt") or "You are a helpful assistant."),
            float(body.get("temperature", 0.0)),
            int(body.get("context_length", 2048)),
            int(body.get("max_tokens", 256)),
        )
        return {"model": model, **result}
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Ollama inference failed: " + str(exc))


@app.post("/api/experiments/performance")
def start_performance(body: PerformanceRequest) -> dict[str, Any]:
    ensure_valid_models(body.models)
    prompts = [prompt.strip() for prompt in body.prompts if prompt.strip()]
    if not prompts:
        raise HTTPException(status_code=400, detail="Add at least one non-empty prompt.")
    if len(body.models) * len(prompts) * body.repetitions > 1000:
        raise HTTPException(status_code=400, detail="This run would exceed 1,000 measured requests. Reduce models, prompts or repetitions.")
    config = body.model_dump()
    config["prompts"] = prompts
    experiment_id = begin_job("performance", config, performance_worker)
    return {"experiment_id": experiment_id, "status": "queued"}


@app.post("/api/evaluations/native")
def start_native_evaluation(body: NativeEvaluationRequest) -> dict[str, Any]:
    ensure_valid_models(body.models)
    if any(case.assertion not in {"contains", "equals", "not-contains"} for case in body.cases):
        raise HTTPException(status_code=400, detail="Supported reference checks: contains, equals, not-contains.")
    if any(not normalize_answer(case.expected) for case in body.cases):
        raise HTTPException(status_code=400, detail="Every expected answer must contain at least one letter or number.")
    if body.baseline_model not in body.models:
        raise HTTPException(status_code=400, detail="The baseline model must also be selected for the benchmark.")
    if len(body.models) * len(body.cases) * body.repetitions > 500:
        raise HTTPException(status_code=400, detail="This quality run would exceed 500 requests. Reduce models, cases or repetitions.")
    config = body.model_dump()
    experiment_id = begin_job("native_quality", config, native_quality_worker)
    return {"experiment_id": experiment_id, "status": "queued"}


@app.post("/api/evaluations/promptfoo")
def start_promptfoo(body: PromptfooRequest) -> dict[str, Any]:
    ensure_valid_models(body.models)
    if any(case.assertion not in {"contains", "equals", "not-contains"} for case in body.cases):
        raise HTTPException(status_code=400, detail="Supported basic assertions: contains, equals, not-contains.")
    status = tool_status()["promptfoo"]
    if not status["available"] and not status["npx_available"]:
        raise HTTPException(status_code=400, detail="Promptfoo is unavailable. Install Node.js, then run npm install -g promptfoo.")
    config = body.model_dump()
    experiment_id = begin_job("promptfoo", config, promptfoo_worker)
    return {"experiment_id": experiment_id, "status": "queued"}


@app.post("/api/evaluations/lm-eval")
def start_lm_eval(body: LMEvalRequest) -> dict[str, Any]:
    ensure_valid_models([body.model])
    if body.task not in {"gsm8k", "truthfulqa_gen", "ifeval"}:
        raise HTTPException(status_code=400, detail="Choose a supported generation-style task: gsm8k, truthfulqa_gen or ifeval.")
    if not (shutil.which("lm_eval") or shutil.which("lm_eval.exe")):
        raise HTTPException(status_code=400, detail="LM Evaluation Harness is not installed. Install with: python -m pip install 'lm_eval[api]'")
    config = body.model_dump()
    experiment_id = begin_job("lm_eval", config, lm_eval_worker)
    return {"experiment_id": experiment_id, "status": "queued"}


@app.post("/api/results/import")
def import_results(body: ImportRequest) -> dict[str, Any]:
    filename = Path(body.filename).name[:200]
    if body.file_format not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="Only CSV and JSON result files are supported.")
    if body.file_format == "json":
        try:
            parsed = json.loads(body.content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON: " + str(exc))
    else:
        try:
            parsed = list(csv.DictReader(body.content.splitlines()))
        except csv.Error as exc:
            raise HTTPException(status_code=400, detail="Invalid CSV: " + str(exc))
    experiment_id = uuid.uuid4().hex[:12]
    config = {"filename": filename, "format": body.file_format, "source": "imported external benchmark"}
    result = {"imported_data": parsed, "notes": ["Imported external result. Backend, model, measurement conditions and units may differ; do not merge with native Ollama results without checking comparability."]}
    db_create(experiment_id, "imported_benchmark", config)
    db_update(experiment_id, status="completed", started_at=now_iso(), finished_at=now_iso(),
              progress=100, result_json=json.dumps(result, ensure_ascii=False))
    return {"experiment_id": experiment_id, "status": "completed"}


@app.get("/api/experiments")
def experiments(limit: int = 100) -> dict[str, Any]:
    return {"experiments": db_list(max(1, min(limit, 250)))}


@app.get("/api/experiments/{experiment_id}")
def experiment(experiment_id: str) -> dict[str, Any]:
    item = db_get(experiment_id)
    if not item:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return {"experiment": item}


@app.get("/api/experiments-export")
def experiments_export() -> dict[str, Any]:
    return {"generated_at": now_iso(), "experiments": db_list(250)}


if WEB_DIR.exists() and (WEB_DIR / "index.html").exists() is False:
    pass
