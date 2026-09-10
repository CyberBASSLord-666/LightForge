import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/performance_quality_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def legacy_policy():
    return {
        "required_tracks": ["vocal-rock"],
        "minimum_pairs_per_track": 3,
        "bootstrap": {"method": "paired-percentile-v1", "seed": "legacy", "confidence": 0.99, "resamples": 256},
        "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"},
        "metrics": {
            "performance.total_wall_clock_seconds": {"direction": "lower", "critical": False},
            "quality.vocal_alignment_f1": {"direction": "higher", "critical": True, "bounds": [0, 1]},
        },
    }


def legacy_report(runtime, policy, pipeline="baseline"):
    return {
        "schema_version": 3,
        "suite": {
            "corpus_id": "legacy-corpus",
            "corpus_manifest_sha256": sha("legacy-manifest"),
            "protocol_id": "legacy-v1",
            "policy_sha256": gate.policy_sha256(policy),
        },
        "runs": [
            {
                "track_id": "vocal-rock",
                "pair_id": f"pair-{index}",
                "run_id": f"{pipeline}-{index}",
                "metrics": {"performance": {"total_wall_clock_seconds": runtime}, "quality": {"vocal_alignment_f1": 0.95}},
                "provenance": {
                    "workload": {
                        "corpus_id": "legacy-corpus",
                        "corpus_manifest_sha256": sha("legacy-manifest"),
                        "audio": {"content_sha256": sha("legacy-audio")},
                        "analysis_configuration": {"quality": "precision"},
                    },
                    "implementation": {"pipeline_version": pipeline, "preprocessing_version": "pcm-v1", "model_versions": {"model": "pinned"}},
                    "environment": {"hardware_fingerprint": "legacy-host", "runtime_backend": "cpu", "runtime_version": "1", "accelerator": {"provider": "cpu"}, "random_seed": 42, "thermal_profile": "cold"},
                },
                "condition": {"cache_mode": "cold"},
            }
            for index in range(3)
        ],
    }


TRACK_SPECS = (
    ("lead-pop", ("lead-vocal", "pop", "dynamic-master")),
    ("layered-voice", ("lead-vocal", "backing-vocal", "harmony", "dense-mix")),
    ("rap-spoken", ("rap", "spoken-vocal", "hip-hop")),
    ("vocal-chops", ("vocal-chops", "processed-vocal", "edm")),
    ("acoustic-instrumental", ("instrumental", "acoustic", "sparse-mix")),
    ("rock-chorus", ("rock", "repeated-chorus", "drums")),
    ("metal-punk", ("metal", "punk", "complex-percussion", "fills")),
    ("edm-drop", ("edm", "heavy-sub-bass", "repeated-motif")),
    ("trance-house-techno", ("trance", "house", "techno", "long-track")),
    ("country", ("country", "acoustic", "lead-vocal")),
    ("cinematic-orchestral", ("cinematic", "orchestral", "tempo-change")),
    ("half-double", ("half-time", "double-time", "downbeat-ambiguity")),
    ("irregular-meter", ("irregular-meter", "structurally-irregular", "instrumental")),
    ("difficult-source", ("short-track", "noisy-source", "compressed-master")),
    ("percussion-fill", ("complex-percussion", "fills", "dense-mix")),
    ("subbass-rap", ("hip-hop", "heavy-sub-bass", "rap")),
)


def release_manifest():
    return {
        "schema_version": 1,
        "corpus_id": "locked-release-corpus",
        "template": False,
        "release_ready": True,
        "coverage_requirements": list(gate.RELEASE_COVERAGE_REQUIREMENTS),
        "release_evidence_requirements": gate._release_evidence_requirements(),
        "golden_artifact_requirements": list(gate.RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS),
        "tracks": [
            {
                "track_id": track_id,
                "audio": {"content_sha256": sha(f"audio:{track_id}"), "duration_seconds": 120 + index},
                "tags": list(tags),
                "golden_artifacts": {
                    artifact: sha(f"golden:{track_id}:{artifact}")
                    for artifact in gate.RELEASE_GOLDEN_ARTIFACT_REQUIREMENTS
                },
            }
            for index, (track_id, tags) in enumerate(TRACK_SPECS)
        ],
    }


def runtime_profile(*, accelerator_available=True):
    accelerator = {"provider": "cpu", "threads": 4}
    profile = {
        "runtime_profile_id": "locked-cpu-profile-001",
        "hardware_fingerprint": "locked-host",
        "runtime_backend": "onnx-cpu",
        "runtime_version": "1.20.1",
        "thermal_profile": "controlled-cold",
        "random_seed": 42,
        "accelerator": {
            "available": accelerator_available,
            "fingerprint_sha256": sha(gate.canonical_json(accelerator)),
        },
    }
    if not accelerator_available:
        profile["accelerator"].update({"reason": "locked CPU-only host", "evidence_id": "runtime-no-accelerator"})
    return profile


def release_policy(manifest, *, accelerator_available=True):
    return {
        "schema_version": 3,
        "required_tracks": [track["track_id"] for track in manifest["tracks"]],
        "minimum_pairs_per_track": 5,
        "bootstrap": {"method": "paired-percentile-v1", "seed": "release", "confidence": 0.99, "resamples": 20000},
        "runtime_target": {"metric": gate.RELEASE_RUNTIME_METRIC, "target_reduction_percent": 75, "scope": "each_required_track"},
        "release_profile": {
            "mode": "release",
            "metric_contract": gate.RELEASE_METRIC_CONTRACT_VERSION,
            "locked_corpus": {
                "corpus_id": manifest["corpus_id"],
                "manifest_sha256": gate.locked_corpus_manifest_sha256(manifest),
            },
            "locked_runtime_profile": runtime_profile(accelerator_available=accelerator_available),
            "human_perceptual_review": {
                "required_for_every_release_candidate": True,
                "minimum_reviewers": 3,
                "required_attributes": list(gate.HUMAN_REVIEW_ATTRIBUTES),
                "attestation": {
                    "protocol": gate.REVIEW_ATTESTATION_PROTOCOL,
                    "verifier_id": "blind-review-service",
                    "verification_key_sha256": sha("review-verifier-key"),
                },
            },
        },
    }


def set_metric(metrics, name, value):
    parts = name.split(".")
    for part in parts[:-1]:
        metrics = metrics.setdefault(part, {})
    metrics[parts[-1]] = value


def release_metrics(runtime):
    metrics = {}
    for name, rule in gate.RELEASE_METRIC_RULES.items():
        if name == gate.RELEASE_RUNTIME_METRIC:
            value = runtime
        elif rule["direction"] == "higher":
            value = 0.9
        elif rule["direction"] == "lower":
            value = 0.0 if rule["bounds"][1] <= 1 else (10.0 if rule["bounds"][1] <= 10_000 else 1024.0)
        else:
            value = 0.5 if rule["bounds"][1] <= 1 else (50.0 if rule["bounds"][1] <= 100 else 1024.0)
        set_metric(metrics, name, value)
    return metrics


def candidate_identity():
    return {"source_sha256": sha("candidate-source"), "pipeline_version": "candidate-pipeline-v2"}


def review(policy, identity, *, status="pass", rating="equivalent", blinded=True):
    result = {
        "schema_version": gate.HUMAN_REVIEW_SCHEMA_VERSION,
        "protocol": "blinded-ab-v1",
        "status": status,
        "review_id": "review-001",
        "reviewers": [
            {
                "reviewer_id": f"reviewer-{index}",
                "blinded": blinded,
                "ratings": {attribute: rating for attribute in gate.HUMAN_REVIEW_ATTRIBUTES},
            }
            for index in range(3)
        ],
    }
    payload_sha = sha(gate.canonical_json(result))
    attestation = policy["release_profile"]["human_perceptual_review"]["attestation"]
    result["attestation"] = {
        "schema_version": gate.REVIEW_ATTESTATION_SCHEMA_VERSION,
        "protocol": gate.REVIEW_ATTESTATION_PROTOCOL,
        "verifier_id": attestation["verifier_id"],
        "verification_key_sha256": attestation["verification_key_sha256"],
        "review_sha256": payload_sha,
        "candidate_identity_sha256": sha(gate.canonical_json(identity)),
        "policy_sha256": gate.policy_sha256(policy),
        "corpus_manifest_sha256": policy["release_profile"]["locked_corpus"]["manifest_sha256"],
        "external_receipt_sha256": sha("external-review-receipt-001"),
    }
    return result


def release_report(runtime, policy, manifest, *, candidate=False, review_value=None, classification="major"):
    manifest_sha = gate.locked_corpus_manifest_sha256(manifest)
    identity = candidate_identity()
    report = {
        "schema_version": 3,
        "suite": {
            "corpus_id": manifest["corpus_id"],
            "corpus_manifest_sha256": manifest_sha,
            "protocol_id": "release-v2",
            "policy_sha256": gate.policy_sha256(policy),
        },
        "runs": [],
    }
    for track in manifest["tracks"]:
        for index in range(5):
            report["runs"].append(
                {
                    "track_id": track["track_id"],
                    "pair_id": f"{track['track_id']}-pair-{index}",
                    "run_id": f"{'candidate' if candidate else 'baseline'}-{track['track_id']}-{index}",
                    "metrics": release_metrics(runtime),
                    "provenance": {
                        "workload": {
                            "corpus_id": manifest["corpus_id"],
                            "corpus_manifest_sha256": manifest_sha,
                            "audio": {"content_sha256": track["audio"]["content_sha256"]},
                            "analysis_configuration": {"quality": "precision"},
                        },
                        "implementation": {
                            "pipeline_version": identity["pipeline_version"] if candidate else "baseline-pipeline",
                            "source_sha256": identity["source_sha256"] if candidate else sha("baseline-source"),
                            "preprocessing_version": "pcm-44100-v2",
                            "model_versions": {"model": "pinned"},
                        },
                        "environment": {
                            "hardware_fingerprint": "locked-host",
                            "runtime_backend": "onnx-cpu",
                            "runtime_version": "1.20.1",
                            "accelerator": {"provider": "cpu", "threads": 4},
                            "random_seed": 42,
                            "thermal_profile": "controlled-cold",
                        },
                    },
                    "condition": {"cache_mode": "cold"},
                }
            )
    if candidate:
        report["candidate_identity"] = identity
        report["change"] = {"classification": classification, "change_id": "candidate-change-001"}
        if review_value is not False:
            report["human_perceptual_review"] = review(policy, identity) if review_value is None else review_value
    return report


def inputs():
    manifest = release_manifest()
    policy = release_policy(manifest)
    return (
        manifest,
        policy,
        release_report(100.0, policy, manifest),
        release_report(24.0, policy, manifest, candidate=True),
    )


def blocker_reasons(result):
    return {blocker["reason"] for blocker in result["blockers"]}


class QualityGateTest(unittest.TestCase):
    def test_legacy_remains_nonproduction(self):
        policy = legacy_policy()
        result = gate.compare(legacy_report(100, policy), legacy_report(24, policy, "candidate"), policy)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertFalse(result["production_ready"])

    def test_release_pass_uses_locked_corpus_and_external_attestation(self):
        manifest, policy, baseline, candidate = inputs()
        result = gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertTrue(result["production_ready"])
        self.assertTrue(result["locked_corpus"]["valid"])
        self.assertTrue(result["human_perceptual_review"]["externally_attested"])
        self.assertEqual(16, result["locked_corpus"]["track_count"])

    def test_exact_old_false_pass_vector_fails_before_a_result_can_be_claimed(self):
        manifest, policy, baseline, candidate = inputs()
        policy["minimum_pairs_per_track"] = 3
        policy["bootstrap"].update({"confidence": 0.51, "resamples": 256})
        policy["runtime_target"] = {
            "metric": "performance.source_separation_seconds",
            "target_reduction_percent": 0,
            "scope": "each_required_track",
        }
        for report in (baseline, candidate):
            report["suite"]["policy_sha256"] = gate.policy_sha256(policy)
        with self.assertRaisesRegex(ValueError, "minimum_pairs_per_track"):
            gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)

    def test_each_release_floor_is_fail_closed_in_full_compare(self):
        mutations = (
            (lambda p: p.update(minimum_pairs_per_track=4), "minimum_pairs_per_track"),
            (lambda p: p["bootstrap"].update(confidence=0.98), "bootstrap.confidence"),
            (lambda p: p["bootstrap"].update(resamples=19_999), "bootstrap.resamples"),
            (lambda p: p["runtime_target"].update(metric="performance.source_separation_seconds"), "runtime_target.metric"),
            (lambda p: p["runtime_target"].update(target_reduction_percent=74.9), "target_reduction_percent"),
        )
        for mutate, message in mutations:
            manifest, policy, baseline, candidate = inputs()
            mutate(policy)
            for report in (baseline, candidate):
                report["suite"]["policy_sha256"] = gate.policy_sha256(policy)
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)

    def test_minor_or_boolean_only_review_cannot_bypass_release_review(self):
        manifest, policy, baseline, _ = inputs()
        minor = release_report(24, policy, manifest, candidate=True, classification="minor", review_value=False)
        minor_result = gate.compare(baseline, minor, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", minor_result["status"])
        self.assertIn("missing_human_perceptual_review", blocker_reasons(minor_result))

        forged = release_report(24, policy, manifest, candidate=True)
        forged["human_perceptual_review"].pop("attestation")
        forged_result = gate.compare(baseline, forged, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", forged_result["status"])
        self.assertIn("missing_or_invalid_external_review_attestation", blocker_reasons(forged_result))

    def test_inconclusive_or_single_baseline_preference_is_rejected(self):
        manifest, policy, baseline, candidate = inputs()
        inconclusive = release_report(
            24,
            policy,
            manifest,
            candidate=True,
            review_value=review(policy, candidate_identity(), rating="inconclusive"),
        )
        result = gate.compare(baseline, inconclusive, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("human_perceptual_review_inconclusive_rating", blocker_reasons(result))

        split = review(policy, candidate_identity())
        split["reviewers"][0]["ratings"]["vocal_synchronization"] = "baseline_preferred"
        # Mutating ratings invalidates the attested digest too; both blockers are
        # expected and a top-level pass still cannot conceal the vote.
        split_candidate = release_report(24, policy, manifest, candidate=True, review_value=split)
        split_result = gate.compare(baseline, split_candidate, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", split_result["status"])
        self.assertIn("human_perceptual_review_baseline_preferred", blocker_reasons(split_result))

    def test_unbound_not_applicable_evidence_and_forged_runtime_exception_fail(self):
        manifest, policy, baseline, candidate = inputs()
        evidence = {"status": "not_applicable", "reason": "self asserted", "evidence_id": "self-asserted"}
        for report in (baseline, candidate):
            for run in report["runs"]:
                if run["track_id"] == "lead-pop":
                    run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = copy.deepcopy(evidence)
        unbound = gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", unbound["status"])
        self.assertIn("release_metric_not_applicable_unbound", blocker_reasons(unbound))

        manifest = release_manifest()
        policy = release_policy(manifest, accelerator_available=False)
        baseline = release_report(100, policy, manifest)
        candidate = release_report(24, policy, manifest, candidate=True)
        for report in (baseline, candidate):
            for run in report["runs"]:
                for metric in gate._ACCELERATOR_NOT_APPLICABLE_METRICS:
                    root, leaf = metric.split(".")
                    run["metrics"][root][leaf] = {
                        "status": "not_applicable",
                        "reason": "forged",
                        "evidence_id": "forged",
                    }
        forged = gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", forged["status"])
        self.assertIn("release_accelerator_not_applicable_unbound", blocker_reasons(forged))

    def test_bound_annotation_and_accelerator_evidence_can_pass(self):
        manifest = release_manifest()
        manifest["tracks"][0]["metric_applicability"] = {
            "quality.vocal_lead_backing_role_accuracy": {
                "status": "not_applicable",
                "reason": "no licensed backing-role annotation",
                "evidence_id": "annotation-no-backing",
                "annotation_sha256": sha("annotation-no-backing"),
            }
        }
        policy = release_policy(manifest, accelerator_available=False)
        baseline = release_report(100, policy, manifest)
        candidate = release_report(24, policy, manifest, candidate=True)
        annotation = {"status": "not_applicable", "reason": "no licensed backing-role annotation", "evidence_id": "annotation-no-backing"}
        accelerator = {"status": "not_applicable", "reason": "locked CPU-only host", "evidence_id": "runtime-no-accelerator"}
        for report in (baseline, candidate):
            for run in report["runs"]:
                if run["track_id"] == "lead-pop":
                    run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = copy.deepcopy(annotation)
                for metric in gate._ACCELERATOR_NOT_APPLICABLE_METRICS:
                    root, leaf = metric.split(".")
                    run["metrics"][root][leaf] = copy.deepcopy(accelerator)
        result = gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)
        self.assertEqual("PASS_TARGET", result["status"])

    def test_one_track_missing_coverage_or_golden_artifact_cannot_pass(self):
        manifest = release_manifest()
        manifest["tracks"] = manifest["tracks"][:1]
        policy = release_policy(manifest)
        result = gate.compare(
            release_report(100, policy, manifest),
            release_report(24, policy, manifest, candidate=True),
            policy,
            locked_corpus_manifest=manifest,
        )
        self.assertEqual("FAIL", result["status"])
        self.assertIn("release_locked_corpus_too_small", blocker_reasons(result))
        self.assertIn("release_locked_corpus_coverage_missing", blocker_reasons(result))

        manifest = release_manifest()
        manifest["tracks"][0]["golden_artifacts"].pop("drum_map_sha256")
        policy = release_policy(manifest)
        result = gate.compare(
            release_report(100, policy, manifest),
            release_report(24, policy, manifest, candidate=True),
            policy,
            locked_corpus_manifest=manifest,
        )
        self.assertEqual("FAIL", result["status"])
        self.assertIn("release_locked_corpus_golden_artifacts_invalid", blocker_reasons(result))

    def test_per_run_audio_and_runtime_profile_are_bound(self):
        manifest, policy, baseline, candidate = inputs()
        candidate["runs"][0]["provenance"]["workload"]["audio"]["content_sha256"] = sha("wrong-audio")
        candidate["runs"][1]["provenance"]["environment"]["runtime_backend"] = "other"
        result = gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("release_policy_run_audio_mismatch", blocker_reasons(result))
        self.assertIn("release_locked_runtime_profile_mismatch", blocker_reasons(result))

    def test_cli_missing_manifest_writes_fail_not_production(self):
        manifest, policy, baseline, candidate = inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in (("baseline.json", baseline), ("candidate.json", candidate), ("policy.json", policy)):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            output = root / "result.json"
            code = gate.main([
                "--baseline", str(root / "baseline.json"),
                "--candidate", str(root / "candidate.json"),
                "--policy", str(root / "policy.json"),
                "--output", str(output),
            ])
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, code)
            self.assertEqual("FAIL", result["status"])
            self.assertFalse(result["production_ready"])

    def test_output_is_deterministic(self):
        manifest, policy, baseline, candidate = inputs()
        self.assertEqual(
            gate.compare(baseline, candidate, policy, locked_corpus_manifest=manifest),
            gate.compare(copy.deepcopy(baseline), copy.deepcopy(candidate), policy, locked_corpus_manifest=copy.deepcopy(manifest)),
        )


if __name__ == "__main__":
    unittest.main()
