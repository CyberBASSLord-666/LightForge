import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("locked_benchmark_runner", ROOT / "tools/locked_benchmark_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
contract = runner.contract


def sha(char):
    return char * 64


def manifest():
    return {
        "schema_version": 1,
        "corpus_id": "lightforge-test-locked-corpus",
        "release_ready": True,
        "tracks": [
            {
                "track_id": "electronic-drop",
                "audio": {"content_sha256": sha("a"), "duration_seconds": 121.5},
                "tags": ["edm", "drop", "instrumental"],
                "golden_artifacts": {"semantic_timeline_sha256": sha("c")},
            },
            {
                "track_id": "vocal-rock",
                "audio": {"content_sha256": sha("b"), "duration_seconds": 183.0},
                "tags": ["rock", "lead-vocal"],
                "golden_artifacts": {"semantic_timeline_sha256": sha("d")},
            },
        ],
    }


def provenance(corpus, audio_sha, duration, *, backend="onnxruntime-android-cpu"):
    return {
        "workload": {
            "corpus_id": corpus["corpus_id"],
            "corpus_manifest_sha256": contract.corpus_manifest_sha256(corpus),
            "audio": {
                "content_sha256": audio_sha,
                "duration_seconds": duration,
                "canonical_sample_rate": 44100,
                "channels": 2,
            },
            "analysis_configuration": {"meter_mode": "auto", "quality": "studio"},
        },
        "implementation": {
            "pipeline_version": "7.1.0-candidate",
            "preprocessing_version": "pcm-44100-v2",
            "model_versions": {"deux": "pinned-sha", "game": "1.0.3"},
        },
        "environment": {
            "hardware_fingerprint": "locked-pixel-test-device",
            "runtime_backend": backend,
            "runtime_version": "1.20.1",
            "accelerator": {"provider": "cpu", "threads": 4},
            "random_seed": 42,
            "thermal_profile": "controlled-cold",
        },
    }


def diagnostic(corpus, track, run_number, *, backend="onnxruntime-android-cpu"):
    recorder = contract.AnalysisRunRecorder(
        track["track_id"],
        provenance(corpus, track["audio"]["content_sha256"], track["audio"]["duration_seconds"], backend=backend),
        run_id=f"{track['track_id']}-run-{run_number}",
    )
    cache_key = contract.content_address("source_separation", {"track": track["track_id"], "run": run_number})
    with recorder.stage("source_separation", cache_status="miss", cache_key=cache_key) as stage:
        stage.timing("model_initialization_seconds", 0.0)
        stage.timing("inference_seconds", 0.0)
        stage.checkpoint("written", cache_key)
    return recorder.finalize(
        metrics={
            "performance": {"total_wall_clock_seconds": 100.0 - run_number},
            "quality": {"beat_f1": 0.97, "vocal_alignment_f1": 0.96},
        },
        outputs={"semantic_timeline_sha256": track["golden_artifacts"]["semantic_timeline_sha256"]},
    )


def write_json(path, value):
    contract.atomic_write_json(path, value)


def gate_policy():
    return {
        "required_tracks": ["electronic-drop", "vocal-rock"],
        "minimum_pairs_per_track": 3,
        "bootstrap": {
            "method": "paired-percentile-v1",
            "confidence": 0.99,
            "resamples": 256,
            "seed": "locked-benchmark-test",
        },
        "metrics": {
            "performance.total_wall_clock_seconds": {
                "direction": "lower",
                "critical": False,
                "equivalence_tolerance": 0.0,
                "pair_hard_regression": 0.0,
            },
            "quality.beat_f1": {
                "direction": "higher",
                "critical": True,
                "equivalence_tolerance": 0.0,
                "pair_hard_regression": 0.0,
                "bounds": [0.0, 1.0],
            },
        },
        "runtime_target": {
            "metric": "performance.total_wall_clock_seconds",
            "target_reduction_percent": 75.0,
            "scope": "each_required_track",
        },
    }


class LockedBenchmarkRunnerTest(unittest.TestCase):
    def write_fixture_set(self, directory, corpus, *, runs=3, mismatch_backend=False):
        manifest_path = directory / "manifest.json"
        write_json(manifest_path, corpus)
        report_dir = directory / "reports"
        report_dir.mkdir()
        for track in corpus["tracks"]:
            for run_number in range(1, runs + 1):
                backend = "other-backend" if mismatch_backend and track["track_id"] == "vocal-rock" and run_number == runs else "onnxruntime-android-cpu"
                write_json(
                    report_dir / f"{track['track_id']}-{run_number}.json",
                    diagnostic(corpus, track, run_number, backend=backend),
                )
        return manifest_path, report_dir

    def test_aggregate_is_deterministic_and_accepted_by_the_quality_gate_shape(self):
        corpus = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            loaded = runner.load_manifest(manifest_path)
            policy = gate_policy()
            aggregate = runner.aggregate_diagnostics(
                loaded,
                [reports],
                policy=policy,
                protocol_id="locked-benchmark-test-v1",
                cache_mode="cold",
                minimum_runs_per_track=3,
            )
            reversed_inputs = sorted(reports.glob("*.json"), reverse=True)
            aggregate_again = runner.aggregate_diagnostics(
                loaded,
                reversed_inputs,
                policy=policy,
                protocol_id="locked-benchmark-test-v1",
                cache_mode="cold",
                minimum_runs_per_track=3,
            )

            self.assertEqual(contract.canonical_json(aggregate), contract.canonical_json(aggregate_again))
            self.assertEqual({"electronic-drop": 3, "vocal-rock": 3}, aggregate["run_counts"])
            self.assertEqual(
                ["electronic-drop", "electronic-drop", "electronic-drop", "vocal-rock", "vocal-rock", "vocal-rock"],
                [run["track_id"] for run in aggregate["runs"]],
            )
            self.assertEqual("locked-pixel-test-device", aggregate["environment"]["hardware"]["fingerprint"])
            self.assertTrue(aggregate["corpus"]["complete"])
            self.assertIn("source_separation", aggregate["diagnostic_statistics"]["by_track"]["vocal-rock"]["stage_timings"])
            self.assertEqual("electronic-drop-run-1", aggregate["runs"][0]["pair_id"])
            self.assertEqual("cold", aggregate["runs"][0]["condition"]["cache_mode"])

            gate_spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/performance_quality_gate.py")
            gate = importlib.util.module_from_spec(gate_spec)
            gate_spec.loader.exec_module(gate)
            gate_result = gate.compare(aggregate, aggregate, policy)
            self.assertEqual("PASS_PARTIAL", gate_result["status"])
            self.assertEqual([], gate_result["blockers"])

    def test_missing_track_or_insufficient_repeats_cannot_create_a_gate_input(self):
        corpus = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus, runs=2)
            loaded = runner.load_manifest(manifest_path)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "at least 3 runs"):
                runner.aggregate_diagnostics(
                    loaded,
                    [reports],
                    policy=gate_policy(),
                    protocol_id="locked-benchmark-test-v1",
                    cache_mode="cold",
                    minimum_runs_per_track=3,
                )

            for path in reports.glob("electronic-drop-*.json"):
                path.unlink()
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "missing locked corpus tracks"):
                runner.load_diagnostics(loaded, [reports])

    def test_mixed_backend_and_duplicate_run_identity_are_rejected(self):
        corpus = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus, mismatch_backend=True)
            loaded = runner.load_manifest(manifest_path)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "do not share one controlled"):
                runner.load_diagnostics(loaded, [reports])

            second_root = root / "duplicate"
            second_root.mkdir()
            manifest_path, reports = self.write_fixture_set(second_root, corpus)
            duplicate = diagnostic(corpus, corpus["tracks"][0], 1)
            write_json(reports / "duplicate.json", duplicate)
            loaded = runner.load_manifest(manifest_path)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "duplicate diagnostic run identity"):
                runner.load_diagnostics(loaded, [reports])

    def test_gate_policy_and_metric_preflight_are_fail_closed(self):
        corpus = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            loaded = runner.load_manifest(manifest_path)
            incompatible_policy = gate_policy()
            incompatible_policy["required_tracks"] = ["vocal-rock"]
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "required_tracks must exactly match"):
                runner.aggregate_diagnostics(
                    loaded,
                    [reports],
                    policy=incompatible_policy,
                    protocol_id="locked-benchmark-test-v1",
                    cache_mode="cold",
                )

            broken_path = reports / "vocal-rock-1.json"
            broken = json.loads(broken_path.read_text(encoding="utf-8"))
            broken["metrics"]["quality"].pop("beat_f1")
            write_json(broken_path, broken)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "missing_metric"):
                runner.aggregate_diagnostics(
                    loaded,
                    [reports],
                    policy=gate_policy(),
                    protocol_id="locked-benchmark-test-v1",
                    cache_mode="cold",
                )

    def test_pairing_sidecar_and_uuid_like_run_identifiers_are_supported(self):
        self.assertEqual(
            "9f74a0c3-0d4d-4d19-8d2f-d6a2a855e9bc",
            runner._resolve_pair_ids(
                [{"track_id": "vocal-rock", "run_id": "9f74a0c3-0d4d-4d19-8d2f-d6a2a855e9bc"}],
                None,
            )[("vocal-rock", "9f74a0c3-0d4d-4d19-8d2f-d6a2a855e9bc")],
        )
        corpus = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            loaded = runner.load_manifest(manifest_path)
            diagnostics = runner.load_diagnostics(loaded, [reports])
            pairing = {
                (diagnostic["track_id"], diagnostic["run_id"]): f"{diagnostic['track_id']}-pair-{index:03d}"
                for index, diagnostic in enumerate(diagnostics)
            }
            aggregate = runner.aggregate_diagnostics(
                loaded,
                [reports],
                policy=gate_policy(),
                protocol_id="locked-benchmark-test-v1",
                cache_mode="cold",
                pairing=pairing,
            )
            self.assertEqual("electronic-drop-pair-000", aggregate["runs"][0]["pair_id"])

    def test_template_manifest_can_be_inspected_but_never_used_for_release_aggregation(self):
        corpus = manifest()
        corpus["template"] = True
        corpus["release_ready"] = False
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "template.json"
            write_json(path, corpus)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "template manifest"):
                runner.load_manifest(path)
            loaded = runner.load_manifest(path, allow_template=True)
            self.assertTrue(loaded["template"])
            self.assertEqual(0, runner.main(["validate-manifest", "--manifest", str(path), "--allow-template"]))

    def test_candidate_change_and_blinded_review_are_preserved_for_the_gate(self):
        corpus = manifest()
        review = {
            "schema_version": 1,
            "protocol": "blinded-ab-v1",
            "status": "pass",
            "review_id": "review-001",
            "reviewers": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            loaded = runner.load_manifest(manifest_path)
            aggregate = runner.aggregate_diagnostics(
                loaded,
                [reports],
                policy=gate_policy(),
                protocol_id="locked-benchmark-test-v1",
                cache_mode="cold",
                change={"classification": "major", "change_id": "semantic-pipeline-rework"},
                human_perceptual_review=review,
            )
            self.assertEqual(
                {"classification": "major", "change_id": "semantic-pipeline-rework"},
                aggregate["change"],
            )
            self.assertEqual(review, aggregate["human_perceptual_review"])
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "requires an explicit candidate"):
                runner.aggregate_diagnostics(
                    loaded,
                    [reports],
                    policy=gate_policy(),
                    protocol_id="locked-benchmark-test-v1",
                    cache_mode="cold",
                    human_perceptual_review=review,
                )

    def test_release_profile_must_pin_the_same_manifest_before_aggregation(self):
        corpus = manifest()
        release_policy = {
            "schema_version": 3,
            "required_tracks": ["electronic-drop", "vocal-rock"],
            "minimum_pairs_per_track": 5,
            "bootstrap": {"method": "paired-percentile-v1", "seed": "release", "confidence": 0.99, "resamples": 20000},
            "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"},
            "release_profile": {
                "mode": "release",
                "metric_contract": runner.quality_gate.RELEASE_METRIC_CONTRACT_VERSION,
                "locked_corpus": {"corpus_id": "wrong-corpus", "manifest_sha256": "0123456789abcdef" * 4},
                "locked_runtime_profile": {
                    "runtime_profile_id": "release-host",
                    "hardware_fingerprint": "locked-pixel-test-device",
                    "runtime_backend": "onnxruntime-android-cpu",
                    "runtime_version": "1.20.1",
                    "thermal_profile": "controlled-cold",
                    "random_seed": 42,
                    "accelerator": {
                        "available": True,
                        "fingerprint_sha256": runner.quality_gate._accelerator_fingerprint({"provider": "cpu", "threads": 4}),
                    },
                },
                "human_perceptual_review": {
                    "required_for_every_release_candidate": True,
                    "minimum_reviewers": 3,
                    "required_attributes": list(runner.quality_gate.HUMAN_REVIEW_ATTRIBUTES),
                    "attestation": {
                        "protocol": runner.quality_gate.REVIEW_ATTESTATION_PROTOCOL,
                        "verifier_id": "blind-review-service",
                        "verification_key_sha256": "fedcba9876543210" * 4,
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            loaded = runner.load_manifest(manifest_path)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "locked_corpus does not exactly match"):
                runner.aggregate_diagnostics(
                    loaded,
                    [reports],
                    policy=release_policy,
                    protocol_id="locked-benchmark-test-v1",
                    cache_mode="cold",
                )

    def test_release_aggregate_revalidates_coverage_and_requires_an_explicit_side(self):
        corpus = manifest()
        policy = {
            "schema_version": 3,
            "required_tracks": ["electronic-drop", "vocal-rock"],
            "minimum_pairs_per_track": 5,
            "bootstrap": {"method": "paired-percentile-v1", "seed": "release", "confidence": 0.99, "resamples": 20000},
            "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"},
            "release_profile": {
                "mode": "release",
                "metric_contract": runner.quality_gate.RELEASE_METRIC_CONTRACT_VERSION,
                "locked_corpus": {
                    "corpus_id": corpus["corpus_id"],
                    "manifest_sha256": contract.corpus_manifest_sha256(corpus),
                },
                "locked_runtime_profile": {
                    "runtime_profile_id": "release-host",
                    "hardware_fingerprint": "locked-pixel-test-device",
                    "runtime_backend": "onnxruntime-android-cpu",
                    "runtime_version": "1.20.1",
                    "thermal_profile": "controlled-cold",
                    "random_seed": 42,
                    "accelerator": {
                        "available": True,
                        "fingerprint_sha256": runner.quality_gate._accelerator_fingerprint({"provider": "cpu", "threads": 4}),
                    },
                },
                "human_perceptual_review": {
                    "required_for_every_release_candidate": True,
                    "minimum_reviewers": 3,
                    "required_attributes": list(runner.quality_gate.HUMAN_REVIEW_ATTRIBUTES),
                    "attestation": {
                        "protocol": runner.quality_gate.REVIEW_ATTESTATION_PROTOCOL,
                        "verifier_id": "blind-review-service",
                        "verification_key_sha256": "abcdef0123456789" * 4,
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            loaded = runner.load_manifest(manifest_path)
            with self.assertRaisesRegex(runner.LockedBenchmarkError, "release corpus contract is invalid"):
                runner.aggregate_diagnostics(
                    loaded,
                    [reports],
                    policy=policy,
                    protocol_id="locked-benchmark-test-v1",
                    cache_mode="cold",
                    report_side="baseline",
                )

    def test_cli_writes_atomic_gate_input(self):
        corpus = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, reports = self.write_fixture_set(root, corpus)
            output = root / "aggregate.json"
            policy_path = root / "policy.json"
            write_json(policy_path, gate_policy())
            result = runner.main(
                [
                    "aggregate",
                    "--manifest",
                    str(manifest_path),
                    "--reports",
                    str(reports),
                    "--policy",
                    str(policy_path),
                    "--protocol-id",
                    "locked-benchmark-test-v1",
                    "--cache-mode",
                    "cold",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(0, result)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("lightforge.locked-benchmark-runs.v2", saved["format"])
            self.assertEqual(6, len(saved["runs"]))


if __name__ == "__main__":
    unittest.main()
