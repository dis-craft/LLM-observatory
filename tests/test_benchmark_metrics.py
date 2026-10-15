import unittest

from unittest.mock import patch

from app import (
    NativeEvaluationRequest,
    PromptfooCase,
    estimate_gpu_energy_joules,
    native_quality_worker,
    normalize_answer,
    reference_assertion_passes,
    start_native_evaluation,
    summarize_quality_trials,
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

        with patch("app.stream_chat", side_effect=fake_stream_chat), patch("app.db_update"):
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
