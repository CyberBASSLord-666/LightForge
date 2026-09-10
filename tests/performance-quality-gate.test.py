import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/performance_quality_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def legacy_policy():
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


def release_policy(track_ids=("vocal-rock",)):
    return {
        "schema_version": 3,
        "required_tracks": list(track_ids),
        "minimum_pairs_per_track": 5,
        "bootstrap": {"method": "paired-percentile-v1", "seed": "release-test-seed", "confidence": 0.99, "resamples": 256},
        "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"},
        "release_profile": {
            "mode": "release",
            "metric_contract": gate.RELEASE_METRIC_CONTRACT_VERSION,
            "locked_corpus": {"corpus_id": "locked-release-corpus", "manifest_sha256": "a" * 64},
            "human_perceptual_review": {
                "required_for_major_pipeline_changes": True,
                "minimum_reviewers": 3,
                "required_attributes": list(gate.HUMAN_REVIEW_ATTRIBUTES),
            },
        },
    }


def provenance(pipeline="baseline", corpus_id="locked-test-corpus", manifest_sha="a" * 64):
    return {
        "workload": {"corpus_id": corpus_id, "corpus_manifest_sha256": manifest_sha, "audio": {"content_sha256": "b" * 64}, "analysis_configuration": {"quality": "precision"}},
        "implementation": {"pipeline_version": pipeline, "preprocessing_version": "pcm-44100-v2", "model_versions": {"deux": "pinned", "game": "pinned"}},
        "environment": {"hardware_fingerprint": "locked-device", "runtime_backend": "onnx-cpu", "runtime_version": "1.20.1", "accelerator": {"provider": "cpu", "threads": 4}, "random_seed": 42, "thermal_profile": "controlled-cold"},
    }


def legacy_metrics(runtime, vocal=0.95):
    return {"performance": {"total_wall_clock_seconds": runtime}, "quality": {"vocal_alignment_f1": vocal, "beat_f1": 0.96, "downbeat_f1": 0.94, "bass_event_f1": 0.92, "structural_event_recall": 0.91, "high_salience_coverage": 0.98, "perceptual_sync_p95_ms": 18, "actuator_feasibility": 1, "high_salience_collision_loss": 0}}


def set_metric(target, path, value):
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def release_metric_value(name, rule, runtime):
    if name == "performance.total_wall_clock_seconds":
        return runtime
    lower, upper = rule.get("bounds", [0, 1_000_000])
    if rule["direction"] == "higher":
        return 0.9 if upper <= 1 else min(upper, max(lower, 100.0))
    if rule["direction"] == "lower":
        if upper <= 1:
            return 0.0
        if upper <= 10_000:
            return 10.0
        return 1024.0
    if upper <= 1:
        return 0.5
    if upper <= 100:
        return 50.0
    return 1024.0


def release_metrics(runtime):
    result = {}
    for name, rule in gate.RELEASE_METRIC_RULES.items():
        set_metric(result, name, release_metric_value(name, rule, runtime))
    return result


def human_review(status="pass", *, blinded=True, baseline_preferred=False):
    rating = "baseline_preferred" if baseline_preferred else "equivalent"
    return {
        "schema_version": 1,
        "protocol": "blinded-ab-v1",
        "status": status,
        "review_id": "review-release-001",
        "reviewers": [
            {
                "reviewer_id": f"reviewer-{index}",
                "blinded": blinded,
                "ratings": {attribute: rating for attribute in gate.HUMAN_REVIEW_ATTRIBUTES},
            }
            for index in range(3)
        ],
    }


def legacy_report(runtime, vocal=0.95, count=5, pipeline="baseline", selected_policy=None):
    selected_policy = selected_policy or legacy_policy()
    return {
        "schema_version": 3,
        "suite": {"corpus_id": "locked-test-corpus", "corpus_manifest_sha256": "a" * 64, "protocol_id": "performance-quality-v3", "policy_sha256": gate.policy_sha256(selected_policy)},
        "runs": [{"track_id": "vocal-rock", "pair_id": f"cold-{index:03d}", "run_id": f"{pipeline}-{index:03d}", "metrics": legacy_metrics(runtime, vocal), "provenance": provenance(pipeline), "condition": {"cache_mode": "cold", "pair_order": "baseline-first"}} for index in range(count)],
    }


def release_report(runtime, selected_policy, *, candidate=False, review=None, tracks=None):
    tracks = tracks or selected_policy["required_tracks"]
    result = {
        "schema_version": 3,
        "suite": {
            "corpus_id": "locked-release-corpus",
            "corpus_manifest_sha256": "a" * 64,
            "protocol_id": "performance-quality-release-v1",
            "policy_sha256": gate.policy_sha256(selected_policy),
        },
        "runs": [],
    }
    for track in tracks:
        for index in range(5):
            item = {
                "track_id": track,
                "pair_id": f"{track}-cold-{index:03d}",
                "run_id": f"{'candidate' if candidate else 'baseline'}-{track}-{index:03d}",
                "metrics": release_metrics(runtime),
                "provenance": provenance("candidate" if candidate else "baseline", "locked-release-corpus", "a" * 64),
                "condition": {"cache_mode": "cold", "pair_order": "baseline-first"},
            }
            result["runs"].append(item)
    if candidate:
        result["change"] = {"classification": "major", "change_id": "semantic-pipeline-rework"}
        result["human_perceptual_review"] = human_review() if review is None else review
    return result


class GateTest(unittest.TestCase):
    def test_release_contract_covers_required_metric_families_and_is_auditable(self):
        names = set(gate.RELEASE_METRIC_RULES)
        required = {
            # Rhythm, meter, bars, and phrase timing.
            "quality.tempo_accuracy",
            "quality.meter_accuracy",
            "quality.bar_boundary_accuracy",
            "quality.phrase_boundary_accuracy",
            "quality.beat_position_error_ms",
            "quality.downbeat_position_error_ms",
            # Vocal regions, singing/speech, pitch, and acoustic syllable timing.
            "quality.vocal_region_precision",
            "quality.singing_speech_classification_accuracy",
            "quality.vocal_pitch_accuracy",
            "quality.vocal_syllable_articulation_alignment_error_ms",
            # Per-class drum precision/recall/F1 and bass timing/pitch/duration.
            "quality.drum_kick_precision",
            "quality.drum_kick_recall",
            "quality.drum_kick_f1",
            "quality.drum_onset_timing_error_ms",
            "quality.bass_note_onset_precision",
            "quality.bass_note_onset_recall",
            "quality.bass_pitch_accuracy",
            "quality.bass_duration_accuracy",
            "quality.kick_bass_coincidence_accuracy",
            # Structure, recurrence, choreography composition, and entropy.
            "quality.section_boundary_accuracy",
            "quality.recurrence_precision",
            "quality.motif_identity_consistency",
            "quality.dynamic_contrast",
            "quality.negative_space_usage",
            "quality.choreography_entropy",
            "quality.choreography_redundancy_score",
            # Command and predicted perceptual timing stay distinct.
            "quality.sync.command.vocals.p99_ms",
            "quality.sync.perceptual.mechanical_actuator.p95_ms",
            "quality.sync.perceptual.lighting_output.max_ms",
            # Resource, cache, and recovery evidence.
            "performance.cache_hit_rate",
            "performance.cache_miss_cost_seconds",
            "performance.checkpoint_resume_overhead_seconds",
            "resources.peak_ram_bytes",
            "resources.total_disk_io_bytes",
            "resources.temporary_storage_bytes",
        }
        self.assertTrue(required.issubset(names))
        contract = gate.release_metric_contract()
        self.assertEqual(gate.RELEASE_METRIC_CONTRACT_VERSION, contract["version"])
        self.assertEqual(names, set(contract["rules"]))
        self.assertEqual(64, len(contract["sha256"]))

    def test_legacy_policy_remains_comparable_but_cannot_claim_release_readiness(self):
        policy = legacy_policy()
        result = gate.compare(legacy_report(100, selected_policy=policy), legacy_report(24, pipeline="candidate", selected_policy=policy), policy)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertEqual("legacy", result["release_profile"]["mode"])

    def test_release_profile_requires_complete_metric_contract_and_blinded_review(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        candidate = release_report(24, policy, candidate=True)
        result = gate.compare(baseline, candidate, policy)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertTrue(result["production_ready"])
        self.assertFalse(result["quality_regressions_detected"])
        self.assertEqual("pass", result["human_perceptual_review"]["status"])
        self.assertIn("quality.sync.perceptual.vocals.p99_ms", result["metric_applicability"])

    def test_release_profile_missing_any_required_family_measurement_fails_closed(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        candidate = release_report(24, policy, candidate=True)
        candidate["runs"][0]["metrics"]["quality"].pop("drum_kick_f1")
        result = gate.compare(baseline, candidate, policy)
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any(item["reason"] == "missing_metric" and item["metric"] == "quality.drum_kick_f1" for item in result["blockers"]))

    def test_not_applicable_requires_evidence_and_locked_corpus_coverage(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        candidate = release_report(24, policy, candidate=True)
        evidence = {"status": "not_applicable", "reason": "no annotated backing-vocal role", "evidence_id": "ground-truth-no-backing-role"}
        for report in (baseline, candidate):
            for run in report["runs"]:
                run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = copy.deepcopy(evidence)
        result = gate.compare(baseline, candidate, policy)
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any(item["reason"] == "insufficient_metric_applicability_coverage" and item["metric"] == "quality.vocal_lead_backing_role_accuracy" for item in result["blockers"]))

        missing_evidence = release_report(24, policy, candidate=True)
        for run in missing_evidence["runs"]:
            run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = {"status": "not_applicable", "reason": "missing proof"}
        with self.assertRaises(ValueError):
            gate.compare(release_report(100, policy), missing_evidence, policy)

    def test_not_applicable_evidence_is_a_stable_corpus_claim_not_candidate_metadata(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        candidate = release_report(24, policy, candidate=True)
        for report, evidence_id in ((baseline, "no-backing-role-baseline"), (candidate, "no-backing-role-candidate")):
            for run in report["runs"]:
                run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = {
                    "status": "not_applicable",
                    "reason": "no annotated backing-vocal role",
                    "evidence_id": evidence_id,
                }
        result = gate.compare(baseline, candidate, policy)
        self.assertIn(
            "not_applicable_evidence_changed",
            {item["reason"] for item in result["blockers"]},
        )

    def test_major_pipeline_change_human_review_is_required_blinded_and_decisive(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        missing = release_report(24, policy, candidate=True)
        missing.pop("human_perceptual_review")
        self.assertIn("missing_human_perceptual_review", {item["reason"] for item in gate.compare(baseline, missing, policy)["blockers"]})

        inconclusive = release_report(24, policy, candidate=True, review=human_review("inconclusive"))
        self.assertIn("human_perceptual_review_inconclusive", {item["reason"] for item in gate.compare(baseline, inconclusive, policy)["blockers"]})

        unblinded = release_report(24, policy, candidate=True, review=human_review(blinded=False))
        self.assertIn("unblinded_human_perceptual_review", {item["reason"] for item in gate.compare(baseline, unblinded, policy)["blockers"]})

        baseline_preferred = release_report(24, policy, candidate=True, review=human_review(baseline_preferred=True))
        self.assertIn("human_perceptual_review_baseline_preferred", {item["reason"] for item in gate.compare(baseline, baseline_preferred, policy)["blockers"]})

        failed = release_report(24, policy, candidate=True, review=human_review("fail"))
        failed_result = gate.compare(baseline, failed, policy)
        self.assertIn("human_perceptual_review_fail", {item["reason"] for item in failed_result["blockers"]})
        self.assertTrue(failed_result["quality_regressions_detected"])

    def test_release_corpus_identity_is_bound_to_policy(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        candidate = release_report(24, policy, candidate=True)
        candidate["suite"]["corpus_manifest_sha256"] = "b" * 64
        result = gate.compare(baseline, candidate, policy)
        self.assertIn("release_policy_corpus_mismatch", {item["reason"] for item in result["blockers"]})

    def test_one_severe_vocal_regression_cannot_hide_in_the_median(self):
        policy = legacy_policy()
        baseline = legacy_report(100, selected_policy=policy)
        candidate = legacy_report(20, pipeline="candidate", selected_policy=policy)
        candidate["runs"][-1]["metrics"]["quality"]["vocal_alignment_f1"] = 0.80
        result = gate.compare(baseline, candidate, policy)
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(result["quality_regressions_detected"])

    def test_missing_pair_and_too_few_pairs_block_release(self):
        policy = legacy_policy()
        baseline = legacy_report(100, count=3, selected_policy=policy)
        candidate = legacy_report(20, count=3, pipeline="candidate", selected_policy=policy)
        candidate["runs"][0]["pair_id"] = "different-pair"
        result = gate.compare(baseline, candidate, policy)
        reasons = {row["reason"] for row in result["blockers"]}
        self.assertEqual("FAIL", result["status"])
        self.assertIn("unpaired_run", reasons)
        self.assertIn("insufficient_paired_runs", reasons)

    def test_policy_digest_and_output_are_deterministic(self):
        policy = release_policy()
        baseline = release_report(100, policy)
        candidate = release_report(24, policy, candidate=True)
        first = gate.compare(baseline, candidate, policy)
        second = gate.compare(copy.deepcopy(baseline), copy.deepcopy(candidate), policy)
        self.assertEqual(first, second)
        candidate["suite"]["policy_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            gate.compare(baseline, candidate, policy)

    def test_template_mode_is_explicitly_unconfigured_without_needing_release_metrics(self):
        policy = {
            "required_tracks": ["__configure_locked_corpus__"],
            "minimum_pairs_per_track": 3,
            "release_profile": {"mode": "template"},
            "bootstrap": {"method": "paired-percentile-v1", "seed": "template", "confidence": 0.99, "resamples": 256},
            "runtime_target": {"metric": "performance.total_wall_clock_seconds", "target_reduction_percent": 75, "scope": "each_required_track"},
            "metrics": {"performance.total_wall_clock_seconds": {"required": True, "critical": False, "direction": "lower", "equivalence_tolerance": 0}},
        }
        report = legacy_report(100, count=3, selected_policy=policy)
        for index, run in enumerate(report["runs"]):
            run["track_id"] = "__configure_locked_corpus__"
            run["pair_id"] = f"pair-{index}"
        candidate = copy.deepcopy(report)
        candidate["runs"] = [dict(run, run_id=f"candidate-{index}", metrics=legacy_metrics(20)) for index, run in enumerate(candidate["runs"])]
        result = gate.compare(report, candidate, policy)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("unconfigured_locked_corpus", {item["reason"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
