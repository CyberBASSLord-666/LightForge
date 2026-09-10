import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("contract", ROOT / "tools/analysis_benchmark_contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


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
            "performance": {"source_separation_seconds": 12.0},
        },
        outputs={"semantic_timeline_sha256": OTHER_SHA},
    )


class AnalysisBenchmarkContractTest(unittest.TestCase):
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
        stage = report["stages"][0]
        self.assertEqual("miss", stage["cache"]["status"])
        self.assertEqual("written", stage["checkpoint"]["status"])
        self.assertGreaterEqual(stage["timings"]["wall_clock_seconds"], 0.0)

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


if __name__ == "__main__":
    unittest.main()

