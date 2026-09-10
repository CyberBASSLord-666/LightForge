import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/performance_quality_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def policy():
    return {
        "schema_version": 3,
        "required_tracks": ["vocal-rock"],
        "minimum_pairs_per_track": 5,
        "bootstrap": {"method": "paired-percentile-v1", "seed": "test-seed", "confidence": 0.99, "resamples": 256},
        "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"},
        "metrics": {
            "performance.total_wall_clock_seconds": {"required": True, "critical": False, "direction": "lower", "equivalence_tolerance": 0},
            "quality.vocal_alignment_f1": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0.002, "pair_hard_regression": 0.002},
            "quality.beat_f1": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0.002},
            "quality.downbeat_f1": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0.002},
            "quality.bass_event_f1": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0.002},
            "quality.structural_event_recall": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0.002},
            "quality.high_salience_coverage": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0.002},
            "quality.perceptual_sync_p95_ms": {"required": True, "critical": True, "direction": "lower", "bounds": [0, 10000], "equivalence_tolerance": 1},
            "quality.actuator_feasibility": {"required": True, "critical": True, "direction": "higher", "bounds": [0, 1], "equivalence_tolerance": 0},
            "quality.high_salience_collision_loss": {"required": True, "critical": True, "direction": "lower", "bounds": [0, 1], "equivalence_tolerance": 0},
        },
    }


def provenance(pipeline="baseline"):
    return {
        "workload": {"corpus_id": "locked-test-corpus", "corpus_manifest_sha256": "a" * 64, "audio": {"content_sha256": "b" * 64}, "analysis_configuration": {"quality": "precision"}},
        "implementation": {"pipeline_version": pipeline, "preprocessing_version": "pcm-44100-v2", "model_versions": {"deux": "pinned", "game": "pinned"}},
        "environment": {"hardware_fingerprint": "locked-device", "runtime_backend": "onnx-cpu", "runtime_version": "1.20.1", "accelerator": {"provider": "cpu", "threads": 4}, "random_seed": 42, "thermal_profile": "controlled-cold"},
    }


def metrics(runtime, vocal=0.95):
    return {"performance": {"total_wall_clock_seconds": runtime}, "quality": {"vocal_alignment_f1": vocal, "beat_f1": 0.96, "downbeat_f1": 0.94, "bass_event_f1": 0.92, "structural_event_recall": 0.91, "high_salience_coverage": 0.98, "perceptual_sync_p95_ms": 18, "actuator_feasibility": 1, "high_salience_collision_loss": 0}}


def report(runtime, vocal=0.95, count=5, pipeline="baseline", selected_policy=None):
    selected_policy = selected_policy or policy()
    return {
        "schema_version": 3,
        "suite": {"corpus_id": "locked-test-corpus", "corpus_manifest_sha256": "a" * 64, "protocol_id": "performance-quality-v3", "policy_sha256": gate.policy_sha256(selected_policy)},
        "runs": [{"track_id": "vocal-rock", "pair_id": f"cold-{index:03d}", "run_id": f"{pipeline}-{index:03d}", "metrics": metrics(runtime, vocal), "provenance": provenance(pipeline), "condition": {"cache_mode": "cold", "pair_order": "baseline-first"}} for index in range(count)],
    }


class GateTest(unittest.TestCase):
    def setUp(self):
        self.policy = policy()

    def test_target_pass_is_paired_and_per_track(self):
        result = gate.compare(report(100, selected_policy=self.policy), report(24, pipeline="candidate", selected_policy=self.policy), self.policy)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertTrue(result["production_ready"])
        self.assertFalse(result["quality_regressions_detected"])

    def test_partial_is_honest_when_speed_target_is_not_confidently_met(self):
        result = gate.compare(report(100, selected_policy=self.policy), report(60, pipeline="candidate", selected_policy=self.policy), self.policy)
        self.assertEqual("PASS_PARTIAL", result["status"])
        self.assertFalse(result["production_ready"])

    def test_one_severe_vocal_regression_cannot_hide_in_the_median(self):
        baseline = report(100, selected_policy=self.policy)
        candidate = report(20, pipeline="candidate", selected_policy=self.policy)
        candidate["runs"][-1]["metrics"]["quality"]["vocal_alignment_f1"] = 0.80
        result = gate.compare(baseline, candidate, self.policy)
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(result["quality_regressions_detected"])

    def test_missing_pair_and_too_few_pairs_block_release(self):
        baseline = report(100, count=3, selected_policy=self.policy)
        candidate = report(20, count=3, pipeline="candidate", selected_policy=self.policy)
        candidate["runs"][0]["pair_id"] = "different-pair"
        result = gate.compare(baseline, candidate, self.policy)
        reasons = {row["reason"] for row in result["blockers"]}
        self.assertEqual("FAIL", result["status"])
        self.assertIn("unpaired_run", reasons)
        self.assertIn("insufficient_paired_runs", reasons)

    def test_missing_metric_and_duplicate_run_id_block_release(self):
        baseline = report(100, selected_policy=self.policy)
        candidate = report(20, pipeline="candidate", selected_policy=self.policy)
        candidate["runs"][1]["metrics"]["quality"].pop("beat_f1")
        candidate["runs"][2]["run_id"] = candidate["runs"][1]["run_id"]
        result = gate.compare(baseline, candidate, self.policy)
        reasons = {row["reason"] for row in result["blockers"]}
        self.assertEqual("FAIL", result["status"])
        self.assertIn("missing_metric", reasons)
        self.assertIn("duplicate_run_id", reasons)

    def test_incomparable_audio_or_hardware_blocks_but_pipeline_change_is_allowed(self):
        baseline = report(100, selected_policy=self.policy)
        candidate = report(20, pipeline="candidate", selected_policy=self.policy)
        self.assertEqual("PASS_TARGET", gate.compare(baseline, candidate, self.policy)["status"])
        candidate["runs"][0]["provenance"]["environment"]["hardware_fingerprint"] = "other-device"
        result = gate.compare(baseline, candidate, self.policy)
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any(row["reason"] == "incomparable_pair_provenance" for row in result["blockers"]))

    def test_non_finite_or_out_of_range_metrics_are_rejected(self):
        candidate = report(20, pipeline="candidate", selected_policy=self.policy)
        candidate["runs"][0]["metrics"]["quality"]["beat_f1"] = float("nan")
        with self.assertRaises(ValueError):
            gate.compare(report(100, selected_policy=self.policy), candidate, self.policy)
        candidate = report(20, pipeline="candidate", selected_policy=self.policy)
        candidate["runs"][0]["metrics"]["quality"]["beat_f1"] = 1.1
        self.assertEqual("FAIL", gate.compare(report(100, selected_policy=self.policy), candidate, self.policy)["status"])

    def test_policy_digest_and_output_are_deterministic(self):
        baseline = report(100, selected_policy=self.policy)
        candidate = report(24, pipeline="candidate", selected_policy=self.policy)
        first = gate.compare(baseline, candidate, self.policy)
        second = gate.compare(copy.deepcopy(baseline), copy.deepcopy(candidate), self.policy)
        self.assertEqual(first, second)
        candidate["suite"]["policy_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            gate.compare(baseline, candidate, self.policy)


if __name__ == "__main__":
    unittest.main()
