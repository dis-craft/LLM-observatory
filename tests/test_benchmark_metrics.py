import time
import unittest

from unittest.mock import patch

from app import (
    NativeEvaluationRequest,
    PerformanceRequest,
    add_baseline_comparisons,
    PromptfooCase,
    estimate_gpu_energy_joules,
    native_quality_worker,
    normalize_answer,
    performance_worker,
    reference_assertion_passes,
    start_native_evaluation,
    summarize_quality_trials,
    summarize_trials,
)


def power_point(t, watts):
    return {"monotonic_s": t, "gpu": {"power_w": watts}}


class ReferenceAssertionTests(unittest.TestCase):
    def test_normalization_ignores_case_punctuation_and_extra_spaces(self):
        self.assertEqual(normalize_answer("  Tokyo!!!  "), normalize_answer("tokyo"))

    def test_contains_assertion_is_case_insensitive(self):
        self.assertTrue(reference_assertion_passes("The answer is TOKYO.", "Tokyo", "contains"))
        self.assertFalse(reference_assertion_passes("The capital is Kyoto.", "Tokyo", "contains"))

    def test_equals_assertion_uses_normalized_text(self):
        self.assertTrue(reference_assertion_passes("  Forty-two! ", "forty two", "equals"))
        self.assertFalse(reference_assertion_passes("The answer is forty two", "forty two", "equals"))

    def test_not_contains_assertion(self):
        self.assertTrue(reference_assertion_passes("The answer is 42.", "39", "not-contains"))
        self.assertFalse(reference_assertion_passes("The answer is 39.", "39", "not-contains"))


class SampledEnergyTests(unittest.TestCase):
    def test_trapezoidal_energy_integration_for_constant_power(self):
        result = estimate_gpu_energy_joules(
            [power_point(0.0, 20), power_point(1.0, 20), power_point(2.0, 20), power_point(3.0, 20)],
            start_monotonic=0.5,
            end_monotonic=2.5,
            max_gap_s=1.1,
        )
        self.assertAlmostEqual(result["energy_j"], 40.0)
        self.assertAlmostEqual(result["coverage_fraction"], 1.0)
        self.assertEqual(result["sample_count"], 2)

    def test_energy_is_not_reported_when_sampling_has_a_large_gap(self):
        result = estimate_gpu_energy_joules(
            [power_point(0.0, 20), power_point(4.0, 20)],
            start_monotonic=0.5,
            end_monotonic=3.5,
            max_gap_s=1.5,
        )
        self.assertIsNone(result["energy_j"])
        self.assertLess(result["coverage_fraction"], 0.8)

    def test_energy_requires_two_samples_inside_request(self):
        result = estimate_gpu_energy_joules(
            [power_point(0.0, 20), power_point(1.0, 20), power_point(3.0, 20)],
            start_monotonic=0.1,
            end_monotonic=0.9,
            max_gap_s=2.0,
        )
        self.assertIsNone(result["energy_j"])
        self.assertEqual(result["sample_count"], 0)


class PerformanceSummaryTests(unittest.TestCase):
    def test_reports_spread_actual_failures_and_token_statistics(self):
        trials = [
            {"status": "completed", "client_latency_s": 1.0, "time_to_first_token_s": 0.2,
             "generation_tokens_per_second": 10.0, "prompt_tokens_per_second": 40.0,
             "prompt_tokens": 100, "output_tokens": 20, "peak_sampled_vram_mb": 600,
             "peak_sampled_ram_bytes": 2_000, "gpu_energy_j_estimate": 4.0},
            {"status": "completed", "client_latency_s": 3.0, "time_to_first_token_s": 0.4,
             "generation_tokens_per_second": 20.0, "prompt_tokens_per_second": 60.0,
             "prompt_tokens": 120, "output_tokens": 30, "peak_sampled_vram_mb": 700,
             "peak_sampled_ram_bytes": 3_000, "gpu_energy_j_estimate": None},
            {"status": "failed", "error": "synthetic failure"},
        ]
        result = summarize_trials(trials)
        self.assertEqual(result["attempted_trials"], 3)
        self.assertEqual(result["completed_trials"], 2)
        self.assertEqual(result["failed_trials"], 1)
        self.assertEqual(result["latency_median_s"], 2.0)
        self.assertEqual(result["latency_stddev_s"], 1.0)
        self.assertEqual(result["generation_tokens_per_second_stddev"], 5.0)
        self.assertEqual(result["peak_sampled_vram_mb"], 700)
        self.assertEqual(result["peak_sampled_system_ram_bytes"], 3000)
        self.assertEqual(result["gpu_energy_j_median_estimate"], 4.0)

    def test_single_trial_does_not_claim_variability(self):
        result = summarize_trials([{ "status": "completed", "client_latency_s": 0.2,
                                     "generation_tokens_per_second": 25.0 }])
        self.assertIsNone(result["latency_stddev_s"])
        self.assertIsNone(result["generation_tokens_per_second_stddev"])

class PairedPerformanceOrderTests(unittest.TestCase):
    def test_repetition_order_alternates_for_each_matched_prompt(self):
        calls = []
        config = {
            "models": ["model-A", "model-B"], "baseline_model": "model-A",
            "prompts": ["same prompt"], "repetitions": 2, "warmups": 0,
            "temperature": 0.0, "context_length": 512, "max_tokens": 32,
            "system_prompt": "Answer briefly.", "sample_interval_s": 0.5,
            "workload_profile": "custom",
        }

        def fake_stream(model, prompt, system_prompt, temperature, context_length, max_tokens):
            calls.append((model, prompt))
            return {"output": "ok", "prompt_tokens": 2, "output_tokens": 1,
                    "prompt_eval_duration_s": 0.1, "generation_duration_s": 0.1,
                    "model_load_duration_s": 0.0, "prompt_tokens_per_second": 20.0,
                    "generation_tokens_per_second": 10.0, "time_to_first_token_s": 0.05,
                    "client_latency_s": 0.2}

        def fake_telemetry():
            return {"timestamp": "test", "monotonic_s": time.perf_counter(),
                    "cpu_utilization_pct": 10.0, "ram_used_bytes": 1000, "gpu": None}

        with patch("app.stream_chat", side_effect=fake_stream), \\
             patch("app.collect_telemetry", side_effect=fake_telemetry), \\
             patch("app.benchmark_environment", return_value={"models": [], "gpu_snapshot": None}), \\
             patch("app.db_update"):
            result = performance_worker("test-run", config)

        self.assertEqual(calls, [
            ("model-A", "same prompt"), ("model-B", "same prompt"),
            ("model-B", "same prompt"), ("model-A", "same prompt"),
        ])
        self.assertEqual(result["summary_by_model"]["model-A"]["completed_trials"], 2)
        self.assertEqual(result["baseline_model"], "model-A")
class PerformanceBaselineComparisonTests(unittest.TestCase):
    def test_percent_changes_use_baseline_and_keep_direction_neutral(self):
        summaries = {
            "reference": {
                "latency_median_s": 2.0,
                "ttft_median_s": 0.5,
                "generation_tokens_per_second_median": 20.0,
                "peak_sampled_vram_mb": 1000.0,
            },
            "quantized": {
                "latency_median_s": 1.5,
                "ttft_median_s": 0.4,
                "generation_tokens_per_second_median": 25.0,
                "peak_sampled_vram_mb": 750.0,
            },
        }
        result = add_baseline_comparisons(summaries, "reference")
        changes = result["quantized"]["change_percent_vs_baseline"]
        self.assertAlmostEqual(changes["latency_median_s"], -25.0)
        self.assertAlmostEqual(changes["ttft_median_s"], -20.0)
        self.assertAlmostEqual(changes["generation_tokens_per_second_median"], 25.0)
        self.assertAlmostEqual(changes["peak_sampled_vram_mb"], -25.0)
        self.assertAlmostEqual(result["reference"]["change_percent_vs_baseline"]["latency_median_s"], 0.0)

    def test_percentage_is_unavailable_if_baseline_is_zero_or_metric_missing(self):
        summaries = {
            "reference": {"latency_median_s": 0.0},
            "quantized": {"latency_median_s": 1.0},
        }
        result = add_baseline_comparisons(summaries, "reference")
        self.assertIsNone(result["quantized"]["change_percent_vs_baseline"]["latency_median_s"])
        self.assertIsNone(result["quantized"]["change_percent_vs_baseline"]["generation_tokens_per_second_median"])


class NativeWorkerTests(unittest.TestCase):
    def test_worker_compares_repeated_answers_against_explicit_baseline(self):
        config = {
            "models": ["baseline", "quant"],
            "baseline_model": "baseline",
            "cases": [{"question": "What is 6 times 7?", "expected": "42", "assertion": "contains"}],
            "repetitions": 2,
            "system_prompt": "Answer briefly.",
            "temperature": 0.0,
            "context_length": 512,
            "max_tokens": 32,
        }

        def fake_stream_chat(model, prompt, system_prompt, temperature, context_length, max_tokens):
            output = "42" if model == "baseline" else "The answer is 42"
            return {
                "output": output,
                "output_tokens": 3,
                "time_to_first_token_s": 0.05,
                "client_latency_s": 0.2,
                "generation_tokens_per_second": 15.0,
            }

        with patch("app.stream_chat", side_effect=fake_stream_chat), patch("app.db_update"), patch("app.benchmark_environment", return_value={}):
            result = native_quality_worker("unit-test", config)

        self.assertEqual(result["baseline_model"], "baseline")
        self.assertEqual(result["summary_by_model"]["baseline"]["assertion_pass_rate"], 1.0)
        self.assertEqual(result["summary_by_model"]["quant"]["assertion_pass_rate"], 1.0)
        self.assertEqual(result["summary_by_model"]["quant"]["baseline_exact_agreement_rate"], 0.0)
        self.assertEqual(result["summary_by_model"]["quant"]["repeat_consistency_rate"], 1.0)
        self.assertEqual(len(result["trials"]), 4)

    def test_api_starts_native_quality_job_without_external_evaluator(self):
        request = NativeEvaluationRequest(
            models=["baseline", "quant"],
            baseline_model="baseline",
            cases=[PromptfooCase(question="What is 6 times 7?", expected="42", assertion="contains")],
            repetitions=2,
        )
        with patch("app.ensure_valid_models"), patch("app.begin_job", return_value="test-job") as begin:
            result = start_native_evaluation(request)
        self.assertEqual(result, {"experiment_id": "test-job", "status": "queued"})
        self.assertEqual(begin.call_args.args[0], "native_quality")
        self.assertEqual(begin.call_args.args[1]["baseline_model"], "baseline")


class QualitySummaryTests(unittest.TestCase):
    def test_baseline_agreement_and_repeat_consistency_are_separate(self):
        trials = [
            {"model": "base", "case_index": 0, "repetition": 1, "status": "completed",
             "output": "Answer: 42!", "passed": True, "reference_exact_match": False},
            {"model": "base", "case_index": 0, "repetition": 2, "status": "completed",
             "output": "Answer: 42!", "passed": True, "reference_exact_match": False},
            {"model": "quant", "case_index": 0, "repetition": 1, "status": "completed",
             "output": "Answer: forty two", "passed": False, "reference_exact_match": False},
            {"model": "quant", "case_index": 0, "repetition": 2, "status": "completed",
             "output": "The result is 42", "passed": True, "reference_exact_match": False},
        ]
        summaries = summarize_quality_trials(trials, ["base", "quant"], case_count=1, repetitions=2)
        self.assertEqual(summaries["base"]["baseline_exact_agreement_rate"], 1.0)
        self.assertEqual(summaries["base"]["repeat_consistency_rate"], 1.0)
        self.assertEqual(summaries["quant"]["baseline_exact_agreement_rate"], 0.0)
        self.assertEqual(summaries["quant"]["repeat_consistency_rate"], 0.5)
        self.assertEqual(summaries["quant"]["assertion_pass_rate"], 0.5)

    def test_repeat_consistency_is_unavailable_without_repetitions(self):
        trials = [
            {"model": "base", "case_index": 0, "repetition": 1, "status": "completed",
             "output": "42", "passed": True, "reference_exact_match": True}
        ]
        result = summarize_quality_trials(trials, ["base"], case_count=1, repetitions=1)
        self.assertIsNone(result["base"]["repeat_consistency_rate"])


if __name__ == "__main__":
    unittest.main()
