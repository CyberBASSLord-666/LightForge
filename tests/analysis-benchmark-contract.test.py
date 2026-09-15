import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("contract", ROOT / "tools/analysis_benchmark_contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
gate_spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/performance_quality_gate.py")
gate = importlib.util.module_from_spec(gate_spec)
gate_spec.loader.exec_module(gate)


AUDIO_SHA = "a" * 64
OTHER_SHA = "b" * 64


def manifest():
    return {
        "schema_version": 1,
        "corpus_id": "lightforge-locked-reference-2026q3",
        "tracks": [
            {
                "track_id": "vocal-rock",
                "audio": {"content_sha256": AUDIO_SHA, "duration_seconds": 180.0},
                "tags": ["lead-vocal", "rock"],
                "golden_artifacts": {"semantic_timeline_sha256": OTHER_SHA},
            }
        ],
    }


def provenance(corpus=None):
    corpus = corpus or manifest()
    return {
        "workload": {
            "corpus_id": corpus["corpus_id"],
            "corpus_manifest_sha256": contract.corpus_manifest_sha256(corpus),
            "audio": {
                "content_sha256": AUDIO_SHA,
                "duration_seconds": 180.0,
                "canonical_sample_rate": 44100,
                "channels": 2,
            },
            "analysis_configuration": {"quality": "studio", "meter_mode": "auto"},
        },
        "implementation": {
            "pipeline_version": "7.0.0-candidate",
            "preprocessing_version": "pcm-44100-v2",
            "model_versions": {"deux": "pinned-sha", "game": "1.0.3"},
        },
        "environment": {
            "hardware_fingerprint": "pixel-test-device-a",
            "runtime_backend": "onnxruntime-android-cpu",
            "runtime_version": "1.20.1",
            "accelerator": {"provider": "cpu", "threads": 4},
            "random_seed": 42,
            "thermal_profile": "controlled-cold",
        },
    }


def diagnostic():
    recorder = contract.AnalysisRunRecorder("vocal-rock", provenance(), run_id="baseline-run-1")
    cache_key = contract.content_address(
        "stems",
        contract.analysis_cache_identity(
            audio_sha256=AUDIO_SHA,
            model_versions={"game": "1.0.3", "deux": "pinned-sha"},
            analysis_configuration={"meter_mode": "auto", "quality": "studio"},
            preprocessing_version="pcm-44100-v2",
            pipeline_version="7.0.0-candidate",
        ),
    )
    with recorder.stage("source_separation", cache_status="miss", cache_key=cache_key) as stage:
        stage.timing("model_initialization_seconds", 0.0)
        stage.timing("inference_seconds", 0.0)
        stage.resource("read_bytes", 4096)
        stage.checkpoint("written", cache_key)
        stage.metadata(model="Deux", source_clock="44100hz")
    return recorder.finalize(
        metrics={
            "quality": {"vocal_alignment_f1": 0.96, "beat_f1": 0.97},
        },
        outputs={"semantic_timeline_sha256": OTHER_SHA},
    )


def counter_diagnostic():
    """Synthetic raw observations for contract tests, never release evidence."""
    report = diagnostic()
    report["execution"] = {
        "wall_clock_seconds": 10.0,
        "cpu_seconds": 8.0,
        "resource_counters": {
            "schema_version": 1,
            "protocol": contract.RESOURCE_COUNTER_PROTOCOL,
            "elapsed_seconds": 10.0,
            "cpu": {"logical_cpu_count": 4},
            "energy": {"counter_id": "package-energy-0", "start_microjoules": 1000000, "end_microjoules": 4500000},
            "thermal": {"sensor_id": "package-temperature-0", "samples": [
                {"elapsed_seconds": 0, "celsius": 40.0},
                {"elapsed_seconds": 5, "celsius": 46.5},
                {"elapsed_seconds": 10, "celsius": 42.0},
            ]},
            "accelerator": {"counter_id": "gpu-busy-0", "start_busy_nanoseconds": 100, "end_busy_nanoseconds": 2500000100},
        },
    }
    report["metrics"]["performance"]["total_wall_clock_seconds"] = 10.0
    report["metrics"]["resources"] = {
        "cpu_utilization_percent": 20.0,
        "energy_joules": 3.5,
        "thermal_delta_celsius": 6.5,
        "accelerator_utilization_percent": 25.0,
    }
    return report


class AnalysisBenchmarkContractTest(unittest.TestCase):
    def test_observed_resource_counters_reach_release_profiler_bindings(self):
        report = counter_diagnostic()
        run = contract.benchmark_run(report)
        for name, value in report["metrics"]["resources"].items():
            self.assertEqual(value, run["profiler_measurement_evidence"]["resource_bindings"]["resources." + name])
        retained = run["profiler_measurement_evidence"]["execution"]["resource_counters"]
        self.assertEqual(report["execution"]["resource_counters"], retained)
        blockers = gate._release_profiler_evidence_blockers({("vocal-rock", "pair-1"): {"run": run, "not_applicable": set()}}, "candidate")
        blocked_metrics = {row.get("metric") for row in blockers}
        self.assertFalse({"resources." + name for name in report["metrics"]["resources"]} & blocked_metrics)
        retained["energy"]["end_microjoules"] = 0
        self.assertEqual(4500000, report["execution"]["resource_counters"]["energy"]["end_microjoules"])

    def test_real_host_cpu_clock_observation_is_projectable(self):
        logical_cpu_count = os.cpu_count()
        if logical_cpu_count is None:
            self.skipTest("host does not expose logical CPU capacity")
        recorder = contract.AnalysisRunRecorder("vocal-rock", provenance(), run_id="local-cpu-unit-observation")
        with recorder.stage("source_separation"):
            sum(value * value for value in range(20000))
        report = recorder.finalize()
        report["execution"]["resource_counters"] = {
            "schema_version": 1,
            "protocol": contract.RESOURCE_COUNTER_PROTOCOL,
            "elapsed_seconds": report["execution"]["wall_clock_seconds"],
            "cpu": {"logical_cpu_count": logical_cpu_count},
        }
        evidence = contract.profiler_measurement_evidence(report)
        self.assertGreater(evidence["resource_bindings"]["resources.cpu_utilization_percent"], 0)
        self.assertLessEqual(evidence["resource_bindings"]["resources.cpu_utilization_percent"], 100)
        self.assertNotIn("resources.energy_joules", evidence["resource_bindings"])

    def test_missing_counter_domains_cannot_be_numeric_release_evidence(self):
        domains = {"cpu": "cpu_utilization_percent", "energy": "energy_joules", "thermal": "thermal_delta_celsius", "accelerator": "accelerator_utilization_percent"}
        for domain, metric in domains.items():
            with self.subTest(domain=domain):
                report = counter_diagnostic()
                del report["execution"]["resource_counters"][domain]
                with self.assertRaisesRegex(contract.ContractValidationError, "no profiler telemetry binding"):
                    contract.benchmark_run(report)
                del report["metrics"]["resources"][metric]
                run = contract.benchmark_run(report)
                self.assertNotIn("resources." + metric, run["profiler_measurement_evidence"]["resource_bindings"])
                blockers = gate._release_profiler_evidence_blockers({("vocal-rock", "pair-1"): {"run": run, "not_applicable": set()}}, "candidate")
                self.assertIn("resources." + metric, {row.get("metric") for row in blockers})

    def test_hand_entered_resource_metrics_cannot_replace_counter_deltas(self):
        for metric in counter_diagnostic()["metrics"]["resources"]:
            with self.subTest(metric=metric):
                report = counter_diagnostic()
                report["metrics"]["resources"][metric] += 0.125
                with self.assertRaisesRegex(contract.ContractValidationError, "conflicts with profiler telemetry"):
                    contract.benchmark_run(report)

    def test_observed_zeros_are_distinct_from_missing_measurements(self):
        report = counter_diagnostic()
        report["execution"]["cpu_seconds"] = 0
        counters = report["execution"]["resource_counters"]
        counters["energy"]["end_microjoules"] = counters["energy"]["start_microjoules"]
        counters["accelerator"]["end_busy_nanoseconds"] = counters["accelerator"]["start_busy_nanoseconds"]
        for sample in counters["thermal"]["samples"]:
            sample["celsius"] = 40
        report["metrics"]["resources"] = {key: 0 for key in report["metrics"]["resources"]}
        result = contract.benchmark_run(report)["profiler_measurement_evidence"]["resource_bindings"]
        self.assertTrue(all(result["resources." + name] == 0 for name in report["metrics"]["resources"]))

    def test_counter_protocol_rejects_wrong_window_shape_and_types(self):
        mutations = [
            lambda c: c.update(schema_version=True),
            lambda c: c.update(protocol="unreviewed"),
            lambda c: c.update(elapsed_seconds=9.0),
            lambda c: c.update(elapsed_seconds=0),
            lambda c: c.update(elapsed_seconds=float("nan")),
            lambda c: c.update(unrecognized={}),
            lambda c: c["cpu"].update(logical_cpu_count=True),
            lambda c: c["cpu"].update(logical_cpu_count=0),
            lambda c: c["energy"].update(end_microjoules=1),
            lambda c: c["energy"].update(end_microjoules=2**63),
            lambda c: c["energy"].update(start_microjoules=True),
            lambda c: c["energy"].update(counter_id="/sys/private-path"),
            lambda c: c["thermal"].update(samples=[]),
            lambda c: c["thermal"]["samples"][0].update(elapsed_seconds=1),
            lambda c: c["thermal"]["samples"][-1].update(elapsed_seconds=9),
            lambda c: c["thermal"]["samples"][1].update(elapsed_seconds=0),
            lambda c: c["thermal"]["samples"][1].update(celsius=float("inf")),
            lambda c: c["thermal"]["samples"][1].update(celsius=True),
            lambda c: c["thermal"]["samples"][1].update(celsius=-274),
            lambda c: c["accelerator"].update(end_busy_nanoseconds=11000000100),
            lambda c: c["accelerator"].update(end_busy_nanoseconds=1),
            lambda c: c["accelerator"].update(start_busy_nanoseconds=100.0),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(case=number):
                report = counter_diagnostic()
                mutate(report["execution"]["resource_counters"])
                with self.assertRaises(contract.ContractValidationError):
                    contract.benchmark_run(report)
        report = counter_diagnostic()
        report["execution"]["cpu_seconds"] = 41
        with self.assertRaisesRegex(contract.ContractValidationError, "exceeds the observed capacity/window"):
            contract.benchmark_run(report)

    def test_counter_delta_preserves_large_integer_precision(self):
        report = counter_diagnostic()
        report["execution"]["resource_counters"]["energy"].update(start_microjoules=2**63 - 2, end_microjoules=2**63 - 1)
        report["metrics"]["resources"]["energy_joules"] = 0.000001
        evidence = contract.benchmark_run(report)["profiler_measurement_evidence"]
        self.assertEqual(0.000001, evidence["resource_bindings"]["resources.energy_joules"])

    def test_counter_source_and_cpu_capacity_changes_are_noncomparable(self):
        for domain, field, replacement in (
            ("cpu", "logical_cpu_count", 8),
            ("energy", "counter_id", "another-energy-counter"),
            ("thermal", "sensor_id", "another-temperature-sensor"),
            ("accelerator", "counter_id", "another-busy-counter"),
        ):
            with self.subTest(domain=domain):
                baseline = counter_diagnostic()
                candidate = copy.deepcopy(baseline)
                candidate["execution"]["resource_counters"][domain][field] = replacement
                if domain == "cpu":
                    candidate["metrics"]["resources"]["cpu_utilization_percent"] = 10
                expected = "execution.resource_counters." + domain + "." + field
                self.assertIn(expected, {row["field"] for row in contract.comparability_differences(baseline, candidate)})
                differences = gate._compare_pair_provenance(contract.benchmark_run(baseline), contract.benchmark_run(candidate))
                self.assertIn("profiler_measurement_evidence." + expected, {row["field"] for row in differences})

    def test_content_address_is_canonical_and_invalidates_real_analysis_inputs(self):
        first = contract.analysis_cache_identity(
            audio_sha256=AUDIO_SHA,
            model_versions={"deux": "pinned-sha", "game": "1.0.3"},
            analysis_configuration={"quality": "studio", "meter_mode": "auto"},
            preprocessing_version="pcm-44100-v2",
            pipeline_version="7.0.0",
        )
        reordered = contract.analysis_cache_identity(
            audio_sha256=AUDIO_SHA,
            model_versions={"game": "1.0.3", "deux": "pinned-sha"},
            analysis_configuration={"meter_mode": "auto", "quality": "studio"},
            preprocessing_version="pcm-44100-v2",
            pipeline_version="7.0.0",
        )
        changed = dict(first, preprocessing_version="pcm-44100-v3")
        self.assertEqual(contract.content_address("stems", first), contract.content_address("stems", reordered))
        self.assertNotEqual(contract.content_address("stems", first), contract.content_address("stems", changed))

    def test_recorder_emits_gate_compatible_strict_diagnostic(self):
        report = diagnostic()
        contract.validate_diagnostic(report)
        contract.validate_against_corpus(report, manifest())
        run = contract.benchmark_run(report)
        self.assertEqual("vocal-rock", run["track_id"])
        self.assertIn("total_wall_clock_seconds", run["metrics"]["performance"])
        self.assertEqual(report["outputs"], run["outputs"])
        self.assertEqual(
            report["execution"]["wall_clock_seconds"],
            run["profiler_measurement_evidence"]["metric_bindings"]["performance.total_wall_clock_seconds"],
        )
        stage = report["stages"][0]
        self.assertEqual("miss", stage["cache"]["status"])
        self.assertEqual("written", stage["checkpoint"]["status"])
        self.assertGreaterEqual(stage["timings"]["wall_clock_seconds"], 0.0)

    def test_profiler_owned_metrics_cannot_be_hand_entered(self):
        recorder = contract.AnalysisRunRecorder("vocal-rock", provenance(), run_id="forged-profiler-run")
        with recorder.stage("source_separation") as stage:
            stage.timing("inference_seconds", 0.0)
        with self.assertRaises(contract.ContractValidationError):
            recorder.finalize(metrics={"performance": {"source_separation_seconds": 12.0}})

    def test_comparability_permits_pipeline_change_but_blocks_models_and_hardware(self):
        baseline = diagnostic()
        candidate = copy.deepcopy(baseline)
        candidate["run_id"] = "candidate-run-1"
        candidate["provenance"]["implementation"]["pipeline_version"] = "7.0.1-candidate"
        self.assertEqual([], contract.comparability_differences(baseline, candidate))
        candidate["provenance"]["implementation"]["model_versions"]["deux"] = "different-model"
        self.assertEqual("provenance.implementation.model_versions", contract.comparability_differences(baseline, candidate)[0]["field"])
        candidate["provenance"]["implementation"]["model_versions"]["deux"] = "pinned-sha"
        candidate["provenance"]["environment"]["hardware_fingerprint"] = "different-device"
        with self.assertRaises(contract.ContractValidationError):
            contract.ensure_comparable(baseline, candidate)

    def test_sensitive_values_and_corrupt_checkpoint_are_rejected(self):
        report = diagnostic()
        report["provenance"]["workload"]["analysis_configuration"]["api_key"] = "do-not-log"
        with self.assertRaises(contract.ContractValidationError):
            contract.validate_diagnostic(report)

        key = contract.content_address("semantic_timeline", {"audio_sha256": AUDIO_SHA})
        identity = {"audio_sha256": AUDIO_SHA, "pipeline_version": "7.0.0"}
        with tempfile.TemporaryDirectory() as directory:
            store = contract.CheckpointStore(directory)
            path = store.write(key, identity, {"stage": "complete", "events": 12})
            self.assertEqual({"stage": "complete", "events": 12}, store.read(key, expected_identity=identity))
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(contract.CacheCorruptionError):
                store.read(key, expected_identity=identity)


    def test_completed_app_run_observation_is_privacy_bounded_and_supplementary(self):
        observation = {
            "schemaVersion": 1,
            "kind": "lightforge.completed-analysis-run",
            "runKind": "fresh-completed",
            "privacy": {
                "audioContent": "excluded",
                "projectIdentity": "excluded",
                "userContent": "excluded",
            },
            "timing": {
                "analysis": {"source": "performance.now", "status": "available", "seconds": 12.5, "reason": None},
                "choreography": {"source": "performance.now", "status": "available", "seconds": 1.25, "reason": None},
                "total": {"source": "performance.now", "status": "available", "seconds": 15.0, "reason": None},
            },
            "analysis": {
                "quality": "precision",
                "implementation": {
                    "rhythmModelFamily": "beat-this-full",
                    "separationModelFamily": "deux",
                    "runtimeKind": "android-cpu-plus-web",
                },
                "stages": [
                    {
                        "stageId": "bass",
                        "restored": False,
                        "timing": {"source": "performance.now", "status": "available", "seconds": 0.5, "reason": None},
                    },
                    {
                        "stageId": "rhythm",
                        "restored": False,
                        "timing": {"source": "performance.now", "status": "available", "seconds": 1.0, "reason": None},
                    },
                    {
                        "stageId": "separation",
                        "restored": False,
                        "timing": {"source": "performance.now", "status": "available", "seconds": 10.0, "reason": None},
                    },
                    {
                        "stageId": "voice",
                        "restored": True,
                        "timing": {
                            "source": "unavailable",
                            "status": "unavailable",
                            "seconds": None,
                            "reason": "restored-stage-zero-cost",
                        },
                    },
                ],
                "cache": {
                    "restoredStageCount": 1,
                    "restoredStageNames": ["voice"],
                    "separationRestoredPassages": 2,
                },
            },
            "resources": {
                "status": "available",
                "schedulerWaitSeconds": 0.125,
                "observedStageCount": 4,
            },
        }
        contract.validate_completed_app_run_observation(observation)
        projection = contract.observed_app_run_time_projection(observation)
        self.assertTrue(projection["observed_time_available"])
        self.assertEqual("not_comparable", projection["release_eligibility"]["status"])
        self.assertEqual("unbound-completed-app-run-observation", projection["release_eligibility"]["reason"])
        self.assertEqual(12.5, projection["timing"]["analysis"]["seconds"])
        self.assertNotIn("metrics", projection)
        self.assertNotIn("runtime", projection)
        self.assertNotIn("provenance", projection)
        no_passage_counter = copy.deepcopy(observation)
        no_passage_counter["analysis"]["cache"]["separationRestoredPassages"] = None
        contract.validate_completed_app_run_observation(no_passage_counter)

        report = diagnostic()
        baseline = contract.benchmark_run(report)
        attached = contract.benchmark_run_with_observed_app_run(report, observation)
        self.assertEqual(baseline["metrics"], attached["metrics"])
        self.assertEqual(baseline["provenance"], attached["provenance"])
        self.assertEqual(baseline["diagnostic_sha256"], attached["diagnostic_sha256"])
        self.assertEqual(
            baseline,
            {key: value for key, value in attached.items() if key != "supplementary_observed_app_run"},
        )

    def test_completed_app_run_observation_rejects_identity_leaks_raw_runtime_and_false_zeroes(self):
        observation = {
            "schemaVersion": 1,
            "kind": "lightforge.completed-analysis-run",
            "runKind": "fresh-completed",
            "privacy": {
                "audioContent": "excluded",
                "projectIdentity": "excluded",
                "userContent": "excluded",
            },
            "timing": {
                "analysis": {"source": "unavailable", "status": "unavailable", "seconds": None, "reason": "clock-unavailable"},
                "choreography": {"source": "unavailable", "status": "unavailable", "seconds": None, "reason": "clock-unavailable"},
                "total": {"source": "unavailable", "status": "unavailable", "seconds": None, "reason": "clock-unavailable"},
            },
            "analysis": {
                "quality": "balanced",
                "implementation": {
                    "rhythmModelFamily": "beat-this-compact",
                    "separationModelFamily": "mdx",
                    "runtimeKind": "web-wasm",
                },
                "stages": [
                    {
                        "stageId": "rhythm",
                        "restored": True,
                        "timing": {
                            "source": "unavailable",
                            "status": "unavailable",
                            "seconds": None,
                            "reason": "restored-stage-zero-cost",
                        },
                    },
                ],
                "cache": {
                    "restoredStageCount": 1,
                    "restoredStageNames": ["rhythm"],
                    "separationRestoredPassages": 0,
                },
            },
            "resources": {
                "status": "unavailable",
                "schedulerWaitSeconds": None,
                "observedStageCount": 0,
            },
        }
        contract.validate_completed_app_run_observation(observation)
        projection = contract.observed_app_run_time_projection(observation)
        self.assertFalse(projection["observed_time_available"])
        self.assertIsNone(projection["timing"]["analysis"]["seconds"])

        leaked = copy.deepcopy(observation)
        leaked["projectId"] = "private-project"
        with self.assertRaises(contract.ContractValidationError):
            contract.validate_completed_app_run_observation(leaked)
        raw_runtime = copy.deepcopy(observation)
        raw_runtime["analysis"]["runtime"] = "private backend /device"
        with self.assertRaises(contract.ContractValidationError):
            contract.validate_completed_app_run_observation(raw_runtime)
        false_zero = copy.deepcopy(observation)
        false_zero["analysis"]["stages"][0]["timing"] = {
            "source": "performance.now",
            "status": "available",
            "seconds": 0.0,
            "reason": None,
        }
        with self.assertRaises(contract.ContractValidationError):
            contract.validate_completed_app_run_observation(false_zero)
        unbounded = copy.deepcopy(observation)
        unbounded["timing"]["analysis"] = {
            "source": "performance.now",
            "status": "available",
            "seconds": 21600.001,
            "reason": None,
        }
        with self.assertRaises(contract.ContractValidationError):
            contract.validate_completed_app_run_observation(unbounded)
        malformed = copy.deepcopy(observation)
        malformed["timing"]["analysis"]["source"] = []
        with self.assertRaises(contract.ContractValidationError):
            contract.validate_completed_app_run_observation(malformed)


if __name__ == "__main__":
    unittest.main()
