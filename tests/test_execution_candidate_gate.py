import json
import subprocess
import sys
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
            benchmark_value = benchmark() if benchmark_value is None else benchmark_value
            benchmark_path.write_text(json.dumps(benchmark_value))
            quality_value = quality_factory(gate.benchmark_evidence_sha256(benchmark_value))
            quality_path.write_text(json.dumps(quality_value))
            return gate.evaluate(candidate_path, benchmark_path, quality_path)

    def test_fabricated_pass_target_only_passes_declaration_lint(self):
        # This deliberately fabricated report must NEVER become an admission.
        report = self.evaluate(candidate())
        self.assertEqual(report["schema"], "lightforge.execution-evidence-lint.v1")
        self.assertEqual(report["status"], "LINT_PASS")
        self.assertIs(report["releaseAuthorized"], False)
        self.assertIs(report["authorityVerified"], False)
        self.assertEqual(report["evidenceTrust"], "caller-supplied-unverified")
        self.assertAlmostEqual(report["performanceDeclarations"]["declaredMinimumMedianReductionPercent"], 80)
        self.assertFalse(report["candidate"]["sourceAudioLeavesDevice"])
        self.assertNotIn("production_ready", report)

    def test_lints_remote_declarations_without_inventing_product_policy(self):
        value = candidate("remote", True)
        value["fallback"] = {"devicePathAvailable": False, "preservesCompletedWork": False}
        value["privacy"].update(explicitPerAnalysisConsent=False, transport="tls-1.2",
                                maximumRetentionHours=48)
        value["operations"].update(boundedRequestBytes=False, idempotentRetry=False)
        report = self.evaluate(value, lambda sha: quality(sha, 12))
        self.assertEqual(report["candidate"]["placement"], "remote")
        self.assertIs(report["releaseAuthorized"], False)
        self.assertIs(report["authorityVerified"], False)

    def test_remote_feature_execution_need_not_transfer_source_audio(self):
        report = self.evaluate(candidate("remote", False))
        self.assertFalse(report["candidate"]["sourceAudioLeavesDevice"])

    def test_device_placement_cannot_declare_source_audio_upload(self):
        with self.assertRaisesRegex(ValueError, "Device placement"):
            self.evaluate(candidate("device", True))

    def test_fallback_is_optional_for_research(self):
        value = candidate()
        del value["fallback"]
        self.assertEqual(self.evaluate(value)["status"], "LINT_PASS")

    def test_unqualified_results_are_not_hidden_by_the_linter(self):
        def unqualified(sha):
            value = quality(sha)
            value["status"] = "FAIL"
            value["production_ready"] = False
            value["human_perceptual_review"]["externally_attested"] = False
            return value
        report = self.evaluate(candidate(), unqualified)
        self.assertEqual(report["performanceDeclarations"]["declaredStatus"], "FAIL")
        self.assertFalse(report["performanceDeclarations"]["declaredProductionReady"])
        self.assertFalse(report["releaseAuthorized"])

    def test_rejects_unbound_quality_report(self):
        def unbound(_sha):
            return quality("b" * 64)
        with self.assertRaisesRegex(ValueError, "exact candidate benchmark"):
            self.evaluate(candidate(), unbound)

    def test_reduction_goal_is_not_a_new_publication_prerequisite(self):
        for reduction in (74.99, 0, -12.5):
            with self.subTest(reduction=reduction):
                report = self.evaluate(candidate(), lambda sha: quality(sha, reduction))
                self.assertEqual(report["performanceDeclarations"]["declaredMinimumMedianReductionPercent"],
                                 reduction)
                self.assertFalse(report["releaseAuthorized"])

    def test_unmeasured_runtime_stays_unmeasured(self):
        def unmeasured(sha):
            value = quality(sha)
            value["runtime"][0]["paired_reduction_percent"] = None
            return value
        report = self.evaluate(candidate(), unmeasured)
        declarations = report["performanceDeclarations"]
        self.assertEqual(declarations["declaredMeasuredTrackCount"], 0)
        self.assertIsNone(declarations["declaredMinimumMedianReductionPercent"])
        self.assertIsNone(declarations["declaredMaximumMedianReductionPercent"])

    def test_all_benchmark_runs_must_bind_source_pipeline_and_models(self):
        for field, replacement in (("source_sha256", "b" * 64),
                                   ("pipeline_version", "different"),
                                   ("model_versions", {"deux": "changed"})):
            with self.subTest(field=field):
                value = benchmark()
                second = benchmark()["runs"][0]
                second["provenance"]["implementation"][field] = replacement
                value["runs"].append(second)
                with self.assertRaisesRegex(ValueError, "run 1 does not bind"):
                    self.evaluate(candidate(), benchmark_value=value)

    def test_nested_input_types_fail_with_explicit_errors(self):
        for run in (None, [], {"provenance": None}, {"provenance": {"implementation": []}}):
            with self.subTest(run=run):
                with self.assertRaises(ValueError):
                    self.evaluate(candidate(), benchmark_value={"schema_version": 4, "runs": [run]})

    def test_declaration_booleans_are_not_truthy_strings(self):
        for section, field in (("fallback", "devicePathAvailable"),
                               ("privacy", "sourceAudioLeavesDevice"),
                               ("privacy", "explicitPerAnalysisConsent"),
                               ("operations", "idempotentRetry")):
            with self.subTest(field=field):
                value = candidate()
                value[section][field] = "true"
                with self.assertRaisesRegex(ValueError, "boolean"):
                    self.evaluate(value)

    def test_canonical_digest_is_deterministic_but_not_an_attestation(self):
        first, second = self.evaluate(candidate()), self.evaluate(candidate())
        self.assertEqual(first, second)
        claimed = first.pop("reportSha256")
        self.assertEqual(claimed, gate.sha256(gate.canonical(first)))
        self.assertFalse(first["authorityVerified"])

    def test_rejects_duplicate_keys_at_every_depth(self):
        for raw in ('{"schema":1,"schema":2}',
                    '{"unused":{"a":1,"a":2}}',
                    '{"unused":[{"a":1,"a":2}]}',
                    '{"a":1,"\\u0061":2}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "input.json"
                path.write_text(raw)
                with self.assertRaisesRegex(ValueError, "Duplicate JSON object key"):
                    gate.read_json(path)

    def test_rejects_non_finite_constants_and_overflow_in_unknown_fields(self):
        for literal in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            with self.subTest(literal=literal), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "input.json"
                path.write_text('{"unused":[{"nested":' + literal + '}]}')
                with self.assertRaises(ValueError):
                    gate.read_json(path)

    def test_canonicalization_rejects_non_finite_values(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    gate.canonical({"unknown": [value]})

    def test_rejects_json_non_object_roots(self):
        for raw in ("[]", "null", "true", "42"):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "input.json"
                path.write_text(raw)
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    gate.read_json(path)

    def test_cli_failure_has_no_authority_and_does_not_overwrite_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.json"
            source.write_text('{"duplicate":1,"duplicate":2}')
            output = root / "receipt.json"
            command = [sys.executable, str(Path(gate.__file__)), "--candidate", str(source),
                       "--candidate-benchmark", str(source), "--quality-report", str(source),
                       "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "LINT_FAIL")
            self.assertFalse(report["releaseAuthorized"])
            self.assertFalse(report["authorityVerified"])
            original = output.read_bytes()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    def test_cli_success_summary_does_not_present_claimed_speed_as_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / name for name in ("candidate.json", "benchmark.json", "quality.json")]
            values = [candidate(), benchmark(), quality(gate.benchmark_evidence_sha256(benchmark()))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value))
            result = subprocess.run([sys.executable, str(Path(gate.__file__)),
                                     "--candidate", str(paths[0]), "--candidate-benchmark", str(paths[1]),
                                     "--quality-report", str(paths[2]), "--output", str(root / "receipt.json")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "LINT_PASS")
            self.assertFalse(summary["releaseAuthorized"])
            self.assertFalse(summary["authorityVerified"])
            self.assertNotIn("minimumMedianReductionPercent", summary)


if __name__ == "__main__":
    unittest.main()
