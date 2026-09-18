import json
import tempfile
import unittest
from pathlib import Path

from tools import execution_candidate_gate as gate


SHA = "a" * 64
MODELS = {"deux": "pinned", "game": "pinned"}
MODEL_SHA = gate.sha256(gate.canonical(MODELS))


def candidate(placement="device", leaves=False):
    privacy = {"sourceAudioLeavesDevice": leaves}
    if leaves:
        privacy.update(explicitPerAnalysisConsent=True, transport="tls-1.3",
                       maximumRetentionHours=1, trainingUse=False,
                       credentialLocation="server")
    return {"schema": gate.SCHEMA, "candidateId": "native-accelerated-v1",
            "placement": placement,
            "source": {"implementationSha256": SHA, "modelSetSha256": MODEL_SHA,
                       "pipelineVersion": "candidate-v1"},
            "resultContract": "lightforge-analysis-v8",
            "fallback": {"preservesCompletedWork": True, "devicePathAvailable": True},
            "privacy": privacy,
            "operations": {"maximumCostUsdPerTrack": 0, "boundedRequestBytes": True,
                           "idempotentRetry": True}}


def benchmark():
    return {"schema_version": 4, "runs": [{"provenance": {"implementation": {
        "source_sha256": SHA, "pipeline_version": "candidate-v1", "model_versions": MODELS
    }}}]}


def quality(benchmark_sha, reduction=80):
    return {"schema_version": 4, "status": "PASS_TARGET", "production_ready": True,
            "human_perceptual_review": {"externally_attested": True,
                                        "candidate_benchmark_sha256": benchmark_sha},
            "runtime": [{"track": "locked-track", "target_met": reduction >= 75,
                         "target_reduction_percent": 75,
                         "paired_reduction_percent": {"median": reduction}}]}


class ExecutionCandidateGateTest(unittest.TestCase):
    def evaluate(self, candidate_value, quality_factory=quality, benchmark_value=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            candidate_path, benchmark_path, quality_path = (root / "candidate.json",
                                                             root / "benchmark.json",
                                                             root / "quality.json")
            candidate_path.write_text(json.dumps(candidate_value))
            benchmark_path.write_text(json.dumps(benchmark_value or benchmark()))
            quality_value = quality_factory(gate.benchmark_evidence_sha256(benchmark_value or benchmark()))
            quality_path.write_text(json.dumps(quality_value))
            return gate.evaluate(candidate_path, benchmark_path, quality_path)

    def test_admits_proven_device_candidate(self):
        report = self.evaluate(candidate())
        self.assertEqual(report["status"], "ADMIT")
        self.assertAlmostEqual(report["performance"]["minimumMedianReductionPercent"], 80)
        self.assertFalse(report["candidate"]["sourceAudioLeavesDevice"])

    def test_admits_remote_only_with_bounded_privacy_contract(self):
        report = self.evaluate(candidate("remote", True), lambda sha: quality(sha, 75))
        self.assertEqual(report["candidate"]["placement"], "remote")
        self.assertEqual(report["performance"]["minimumMedianReductionPercent"], 75)

    def test_rejects_remote_candidate_without_consent(self):
        value = candidate("remote", True)
        value["privacy"]["explicitPerAnalysisConsent"] = False
        with self.assertRaisesRegex(ValueError, "explicit per-analysis consent"):
            self.evaluate(value)

    def test_rejects_candidate_authored_or_unqualified_quality(self):
        def unqualified(sha):
            value = quality(sha)
            value["production_ready"] = False
            return value
        with self.assertRaisesRegex(ValueError, "has not admitted"):
            self.evaluate(candidate(), unqualified)

    def test_rejects_unbound_quality_report(self):
        def unbound(_sha):
            return quality("b" * 64)
        with self.assertRaisesRegex(ValueError, "exact candidate benchmark"):
            self.evaluate(candidate(), unbound)

    def test_rejects_less_than_target_reduction(self):
        with self.assertRaisesRegex(ValueError, "75%"):
            self.evaluate(candidate(), lambda sha: quality(sha, 74.99))


if __name__ == "__main__":
    unittest.main()
