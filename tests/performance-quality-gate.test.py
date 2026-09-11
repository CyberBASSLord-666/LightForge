import copy
import base64
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/performance_quality_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


_TEST_REVIEW_PRIVATE_KEY_PEM = None
_TEST_REVIEW_PUBLIC_KEY = None


def review_test_public_key():
    """Generate one ephemeral Ed25519 verifier key; no signing secret is checked in."""
    global _TEST_REVIEW_PRIVATE_KEY_PEM, _TEST_REVIEW_PUBLIC_KEY
    if _TEST_REVIEW_PUBLIC_KEY is not None:
        return _TEST_REVIEW_PUBLIC_KEY
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        private_path = root / "review-test-private-key.pem"
        public_der_path = root / "review-test-public-key.der"
        generated = subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        extracted = subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private_path),
                "-pubout",
                "-outform",
                "DER",
                "-out",
                str(public_der_path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if generated.returncode or extracted.returncode:
            raise RuntimeError("OpenSSL could not create the ephemeral test Ed25519 key")
        public_der = public_der_path.read_bytes()
        prefix = bytes.fromhex("302a300506032b6570032100")
        if not public_der.startswith(prefix) or len(public_der) != len(prefix) + 32:
            raise RuntimeError("OpenSSL emitted an unexpected Ed25519 public key")
        _TEST_REVIEW_PRIVATE_KEY_PEM = private_path.read_bytes()
        _TEST_REVIEW_PUBLIC_KEY = public_der[len(prefix):]
    return _TEST_REVIEW_PUBLIC_KEY


def sign_review_attestation(payload):
    """Sign an ephemeral test review with OpenSSL's Ed25519 implementation."""
    review_test_public_key()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        key_path = root / "review-test-private-key.pem"
        payload_path = root / "payload.json"
        signature_path = root / "signature.bin"
        key_path.write_bytes(_TEST_REVIEW_PRIVATE_KEY_PEM)
        payload_path.write_bytes(gate.canonical_json(payload).encode("utf-8"))
        completed = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(key_path),
                "-rawin",
                "-in",
                str(payload_path),
                "-out",
                str(signature_path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode:
            raise RuntimeError("OpenSSL could not create the test Ed25519 attestation")
        return base64.b64encode(signature_path.read_bytes()).decode("ascii")


def policy_test_authority():
    """Install an ephemeral *source-side* authority only for this test module.

    Production source intentionally ships with no configured policy authority.
    Tests simulate the separately reviewed source deployment by replacing the
    module registry, never by embedding a private key in policy or corpus
    evidence.  The private half exists only in this process's temporary test
    fixture.
    """
    public_key = review_test_public_key()
    authority = {
        "authority_id": "test-release-policy-authority",
        "protocol": gate.RELEASE_POLICY_AUTHORITY_PROTOCOL,
        "algorithm": gate.RELEASE_POLICY_AUTHORITY_ALGORITHM,
        "verification_key_sha256": sha_bytes(public_key),
    }
    gate.RELEASE_POLICY_AUTHORITY_KEYS = MappingProxyType(
        {
            authority["authority_id"]: {
                "protocol": authority["protocol"],
                "algorithm": authority["algorithm"],
                "verification_key_base64": base64.b64encode(public_key).decode("ascii"),
                "verification_key_sha256": authority["verification_key_sha256"],
            }
        }
    )
    return authority


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
    authority = policy_test_authority()
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
            "policy_authority": authority,
            "human_perceptual_review": {
                "required_for_every_release_candidate": True,
                "minimum_reviewers": 3,
                "required_attributes": list(gate.HUMAN_REVIEW_ATTRIBUTES),
                "attestation": {
                    "protocol": gate.REVIEW_ATTESTATION_PROTOCOL,
                    "verifier_id": "blind-review-service",
                    "algorithm": gate.REVIEW_ATTESTATION_ALGORITHM,
                    "verification_key_base64": base64.b64encode(review_test_public_key()).decode("ascii"),
                    "verification_key_sha256": sha_bytes(review_test_public_key()),
                },
            },
        },
    }


def policy_authority_attestation(policy):
    authority = policy["release_profile"]["policy_authority"]
    payload = gate._policy_authority_attestation_payload(
        profile_authority=authority,
        policy_sha256=gate.policy_sha256(policy),
        corpus_manifest_sha256=policy["release_profile"]["locked_corpus"]["manifest_sha256"],
    )
    return {
        "schema_version": gate.RELEASE_POLICY_AUTHORITY_SCHEMA_VERSION,
        "protocol": authority["protocol"],
        "authority_id": authority["authority_id"],
        "algorithm": authority["algorithm"],
        "verification_key_sha256": authority["verification_key_sha256"],
        "policy_sha256": gate.policy_sha256(policy),
        "corpus_manifest_sha256": policy["release_profile"]["locked_corpus"]["manifest_sha256"],
        "signed_payload_sha256": sha(gate.canonical_json(payload)),
        "signature_base64": sign_review_attestation(payload),
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


def review(
    policy,
    identity,
    *,
    baseline,
    candidate,
    status="pass",
    rating="equivalent",
    blinded=True,
):
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
    signed_payload = gate._review_attestation_payload(
        profile_attestation=attestation,
        review_sha256=payload_sha,
        candidate_identity_sha256=sha(gate.canonical_json(identity)),
        policy_sha256=gate.policy_sha256(policy),
        corpus_manifest_sha256=policy["release_profile"]["locked_corpus"]["manifest_sha256"],
        baseline_benchmark_sha256=gate.benchmark_evidence_sha256(baseline),
        candidate_benchmark_sha256=gate.benchmark_evidence_sha256(
            {
                **candidate,
                "human_perceptual_review": result,
            }
        ),
    )
    result["attestation"] = {
        "schema_version": gate.REVIEW_ATTESTATION_SCHEMA_VERSION,
        "protocol": gate.REVIEW_ATTESTATION_PROTOCOL,
        "verifier_id": attestation["verifier_id"],
        "algorithm": attestation["algorithm"],
        "verification_key_sha256": attestation["verification_key_sha256"],
        "review_sha256": payload_sha,
        "candidate_identity_sha256": sha(gate.canonical_json(identity)),
        "policy_sha256": gate.policy_sha256(policy),
        "corpus_manifest_sha256": policy["release_profile"]["locked_corpus"]["manifest_sha256"],
        "baseline_benchmark_sha256": gate.benchmark_evidence_sha256(baseline),
        "candidate_benchmark_sha256": gate.benchmark_evidence_sha256(
            {
                **candidate,
                "human_perceptual_review": result,
            }
        ),
        "signed_payload_sha256": sha(gate.canonical_json(signed_payload)),
        "signature_base64": sign_review_attestation(signed_payload),
    }
    return result


def release_report(runtime, policy, manifest, *, candidate=False, review_value=False, classification="major"):
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
        if review_value not in (False, None):
            report["human_perceptual_review"] = review_value
    return report


def release_candidate(
    runtime,
    policy,
    manifest,
    baseline,
    *,
    review_value=None,
    classification="major",
):
    """Create candidate evidence and then sign the exact finalized report."""
    candidate = release_report(
        runtime,
        policy,
        manifest,
        candidate=True,
        review_value=False,
        classification=classification,
    )
    if review_value is not False:
        candidate["human_perceptual_review"] = (
            review(
                policy,
                candidate_identity(),
                baseline=baseline,
                candidate=candidate,
            )
            if review_value is None
            else review_value
        )
    return candidate


def attest_candidate_review(candidate, baseline, policy, *, status="pass", rating="equivalent", blinded=True):
    """Refresh review evidence only after both benchmark reports are final."""
    candidate["human_perceptual_review"] = review(
        policy,
        candidate_identity(),
        baseline=baseline,
        candidate=candidate,
        status=status,
        rating=rating,
        blinded=blinded,
    )
    return candidate


def inputs():
    manifest = release_manifest()
    policy = release_policy(manifest)
    baseline = release_report(100.0, policy, manifest)
    return (
        manifest,
        policy,
        baseline,
        release_candidate(24.0, policy, manifest, baseline),
    )


def compare_release(baseline, candidate, policy, manifest):
    return gate.compare(
        baseline,
        candidate,
        policy,
        locked_corpus_manifest=manifest,
        release_policy_attestation=policy_authority_attestation(policy),
    )


def blocker_reasons(result):
    return {blocker["reason"] for blocker in result["blockers"]}


class QualityGateTest(unittest.TestCase):
    def test_legacy_remains_nonproduction(self):
        policy = legacy_policy()
        result = gate.compare(legacy_report(100, policy), legacy_report(24, policy, "candidate"), policy)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertFalse(result["production_ready"])

    def test_checked_in_template_policy_cannot_claim_production_readiness(self):
        policy=json.loads((ROOT/"qa/performance-gate-policy.json").read_text(encoding="utf-8"))
        result=gate.compare(
            legacy_report(100.0,policy),
            legacy_report(24.0,policy,"candidate"),
            policy,
        )
        self.assertEqual("FAIL",result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("unconfigured_locked_corpus",blocker_reasons(result))

    def test_nonfinite_metric_leaves_are_rejected_before_aggregation(self):
        metric=next(iter(gate.RELEASE_METRIC_RULES))
        for value in (float("nan"),float("inf"),-float("inf")):
            with self.subTest(value=value):
                manifest,policy,baseline,candidate=inputs()
                set_metric(candidate["runs"][0]["metrics"],metric,value)
                with self.assertRaisesRegex(ValueError,"finite"):
                    compare_release(baseline,candidate,policy,manifest)

    def test_missing_required_metric_in_one_pair_blocks_release(self):
        manifest,policy,baseline,candidate=inputs()
        metric=next(name for name,rule in gate.RELEASE_METRIC_RULES.items() if rule.get("required",True))
        target=candidate["runs"][0]["metrics"]
        parts=metric.split(".")
        for part in parts[:-1]:
            target=target[part]
        del target[parts[-1]]
        result=compare_release(baseline,candidate,policy,manifest)
        self.assertEqual("FAIL",result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("missing_metric",blocker_reasons(result))

    def test_release_pass_uses_locked_corpus_and_external_attestation(self):
        manifest, policy, baseline, candidate = inputs()
        result = compare_release(baseline, candidate, policy, manifest)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertTrue(result["production_ready"])
        self.assertTrue(result["locked_corpus"]["valid"])
        self.assertTrue(result["human_perceptual_review"]["externally_attested"])
        self.assertTrue(result["release_policy_authority"]["verified"])
        self.assertEqual(16, result["locked_corpus"]["track_count"])

    def test_cli_verified_source_authority_can_produce_release(self):
        manifest, policy, baseline, candidate = inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in (
                ("baseline.json", baseline),
                ("candidate.json", candidate),
                ("policy.json", policy),
                ("manifest.json", manifest),
                ("policy-authority-attestation.json", policy_authority_attestation(policy)),
            ):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            output = root / "result.json"
            code = gate.main(
                [
                    "--baseline", str(root / "baseline.json"),
                    "--candidate", str(root / "candidate.json"),
                    "--policy", str(root / "policy.json"),
                    "--locked-corpus-manifest", str(root / "manifest.json"),
                    "--release-policy-attestation", str(root / "policy-authority-attestation.json"),
                    "--output", str(output),
                ]
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(0, code)
        self.assertEqual("PASS_TARGET", result["status"])
        self.assertTrue(result["production_ready"])
        self.assertTrue(result["release_policy_authority"]["verified"])

    def test_candidate_policy_digest_is_not_a_trust_anchor(self):
        manifest, policy, baseline, candidate = inputs()
        result = gate.compare(
            baseline,
            candidate,
            policy,
            locked_corpus_manifest=manifest,
            # This is the exact formerly passing bypass: the candidate computes
            # a correct policy hash and supplies it as its own trust root.
            trusted_release_policy_sha256=gate.policy_sha256(policy),
        )
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("release_policy_authority_attestation_required", blocker_reasons(result))
        self.assertEqual("ignored_untrusted_hint", result["trusted_release_policy"]["status"])
        self.assertFalse(result["release_policy_authority"]["verified"])
        mismatched = gate.compare(
            baseline,
            candidate,
            policy,
            locked_corpus_manifest=manifest,
            trusted_release_policy_sha256=sha("different-trusted-policy"),
        )
        self.assertEqual("FAIL", mismatched["status"])
        self.assertIn("release_policy_authority_attestation_required", blocker_reasons(mismatched))

    def test_candidate_owned_authority_name_and_receipt_are_not_trusted(self):
        """A policy cannot add an authority ID/key digest and sign itself."""
        manifest = release_manifest()
        policy = release_policy(manifest)
        policy["release_profile"]["policy_authority"] = {
            "authority_id": "candidate-owned-policy-authority",
            "protocol": gate.RELEASE_POLICY_AUTHORITY_PROTOCOL,
            "algorithm": gate.RELEASE_POLICY_AUTHORITY_ALGORITHM,
            # A valid-looking digest is still not a source-pinned public key.
            "verification_key_sha256": sha("candidate-owned-public-key"),
        }
        baseline = release_report(100.0, policy, manifest)
        candidate = release_candidate(24.0, policy, manifest, baseline)
        result = gate.compare(
            baseline,
            candidate,
            policy,
            locked_corpus_manifest=manifest,
            trusted_release_policy_sha256=gate.policy_sha256(policy),
            # The candidate can form a coherent receipt, but its authority ID
            # does not exist in the source-pinned registry.
            release_policy_attestation=policy_authority_attestation(policy),
        )
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn(
            "release_policy_authority_unknown_or_misconfigured",
            blocker_reasons(result),
        )

    def test_unconfigured_source_policy_authority_fails_closed(self):
        manifest, policy, baseline, candidate = inputs()
        previous = gate.RELEASE_POLICY_AUTHORITY_KEYS
        gate.RELEASE_POLICY_AUTHORITY_KEYS = MappingProxyType({})
        try:
            result = compare_release(baseline, candidate, policy, manifest)
        finally:
            gate.RELEASE_POLICY_AUTHORITY_KEYS = previous
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("release_policy_authority_unconfigured", blocker_reasons(result))

    def test_policy_authority_receipt_cannot_be_replayed_after_binding_changes(self):
        manifest, policy, _, _ = inputs()
        receipt = policy_authority_attestation(policy)

        modified_policy = copy.deepcopy(policy)
        modified_policy["release_profile"]["locked_corpus"]["manifest_sha256"] = sha("different-corpus")
        modified_profile = gate._validate_policy(modified_policy)[-1]
        _, policy_blockers = gate._release_policy_authority_diagnostics(
            modified_profile,
            gate.policy_sha256(modified_policy),
            receipt,
        )
        self.assertIn(
            "release_policy_authority_attestation_binding_mismatch",
            {blocker["reason"] for blocker in policy_blockers},
        )

        changed_key_policy = copy.deepcopy(policy)
        changed_key_policy["release_profile"]["policy_authority"]["verification_key_sha256"] = sha(
            "candidate-substituted-authority-key"
        )
        changed_key_profile = gate._validate_policy(changed_key_policy)[-1]
        _, key_blockers = gate._release_policy_authority_diagnostics(
            changed_key_profile,
            gate.policy_sha256(changed_key_policy),
            receipt,
        )
        self.assertIn(
            "release_policy_authority_profile_binding_mismatch",
            {blocker["reason"] for blocker in key_blockers},
        )

    def test_review_attestation_binds_baseline_and_candidate_benchmark_evidence(self):
        """A post-review metric edit cannot manufacture a faster release."""
        manifest, policy, baseline, candidate = inputs()
        mutated_candidate = copy.deepcopy(candidate)
        mutated_candidate["runs"][0]["metrics"]["performance"]["total_wall_clock_seconds"] = 0.01
        candidate_result = compare_release(baseline, mutated_candidate, policy, manifest)
        self.assertEqual("FAIL", candidate_result["status"])
        self.assertFalse(candidate_result["production_ready"])
        self.assertIn(
            "external_review_attestation_binding_mismatch",
            blocker_reasons(candidate_result),
        )

        mutated_baseline = copy.deepcopy(baseline)
        mutated_baseline["runs"][0]["metrics"]["performance"]["total_wall_clock_seconds"] = 1.0
        baseline_result = compare_release(mutated_baseline, candidate, policy, manifest)
        self.assertEqual("FAIL", baseline_result["status"])
        self.assertFalse(baseline_result["production_ready"])
        self.assertIn(
            "external_review_attestation_binding_mismatch",
            blocker_reasons(baseline_result),
        )

    def test_cli_self_supplied_policy_corpus_key_and_signature_fail_closed(self):
        """Even a coherent candidate-owned bundle lacks protected policy authority."""
        manifest, policy, baseline, candidate = inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in (
                ("baseline.json", baseline),
                ("candidate.json", candidate),
                ("candidate-policy.json", policy),
                ("candidate-manifest.json", manifest),
            ):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            output = root / "result.json"
            code = gate.main(
                [
                    "--baseline", str(root / "baseline.json"),
                    "--candidate", str(root / "candidate.json"),
                    "--policy", str(root / "candidate-policy.json"),
                    "--locked-corpus-manifest", str(root / "candidate-manifest.json"),
                    # Candidate-provided hash is deliberately insufficient.
                    "--trusted-release-policy-sha256", gate.policy_sha256(policy),
                    "--output", str(output),
                ]
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(1, code)
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("release_policy_authority_attestation_required", blocker_reasons(result))

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
        minor = release_candidate(
            24,
            policy,
            manifest,
            baseline,
            classification="minor",
            review_value=False,
        )
        minor_result = compare_release(baseline, minor, policy, manifest)
        self.assertEqual("FAIL", minor_result["status"])
        self.assertIn("missing_human_perceptual_review", blocker_reasons(minor_result))

        forged = release_candidate(24, policy, manifest, baseline)
        forged["human_perceptual_review"].pop("attestation")
        forged_result = compare_release(baseline, forged, policy, manifest)
        self.assertEqual("FAIL", forged_result["status"])
        self.assertIn("missing_or_invalid_external_review_attestation", blocker_reasons(forged_result))

    def test_forged_external_review_receipt_fails_full_cli_pipeline(self):
        """A self-computed binding hash and arbitrary signature cannot release."""
        manifest, policy, baseline, candidate = inputs()
        candidate["human_perceptual_review"]["attestation"]["signature_base64"] = (
            base64.b64encode(b"forged-review-receipt".ljust(64, b"!")).decode("ascii")
        )
        forged_policy_authority = policy_authority_attestation(policy)
        forged_policy_authority["signature_base64"] = (
            base64.b64encode(b"forged-policy-receipt".ljust(64, b"!")).decode("ascii")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in (
                ("baseline.json", baseline),
                ("candidate.json", candidate),
                ("policy.json", policy),
                ("manifest.json", manifest),
                ("policy-authority-attestation.json", forged_policy_authority),
            ):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            output = root / "result.json"
            code = gate.main(
                [
                    "--baseline", str(root / "baseline.json"),
                    "--candidate", str(root / "candidate.json"),
                    "--policy", str(root / "policy.json"),
                    "--locked-corpus-manifest", str(root / "manifest.json"),
                    "--release-policy-attestation", str(root / "policy-authority-attestation.json"),
                    "--output", str(output),
                ]
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(1, code)
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("external_review_attestation_signature_invalid", blocker_reasons(result))
        self.assertIn("release_policy_authority_attestation_signature_invalid", blocker_reasons(result))

    def test_malformed_reviewer_id_returns_structured_fail(self):
        manifest, policy, baseline, candidate = inputs()
        candidate["human_perceptual_review"]["reviewers"][0]["reviewer_id"] = []
        result = compare_release(baseline, candidate, policy, manifest)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("incomplete_human_perceptual_review", blocker_reasons(result))

    def test_unavailable_signature_backend_is_fail_closed(self):
        manifest, policy, baseline, candidate = inputs()
        verifier = gate._verify_ed25519_attestation_signature
        gate._verify_ed25519_attestation_signature = lambda *_: None
        try:
            result = compare_release(baseline, candidate, policy, manifest)
        finally:
            gate._verify_ed25519_attestation_signature = verifier
        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["production_ready"])
        self.assertIn("human_review_external_verification_unavailable", blocker_reasons(result))

    def test_inconclusive_or_single_baseline_preference_is_rejected(self):
        manifest, policy, baseline, candidate = inputs()
        inconclusive = release_candidate(
            24,
            policy,
            manifest,
            baseline,
            review_value=False,
        )
        inconclusive["human_perceptual_review"] = review(
            policy,
            candidate_identity(),
            baseline=baseline,
            candidate=inconclusive,
            rating="inconclusive",
        )
        result = compare_release(baseline, inconclusive, policy, manifest)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("human_perceptual_review_inconclusive_rating", blocker_reasons(result))

        split = review(
            policy,
            candidate_identity(),
            baseline=baseline,
            candidate=candidate,
        )
        split["reviewers"][0]["ratings"]["vocal_synchronization"] = "baseline_preferred"
        # Mutating ratings invalidates the attested digest too; both blockers are
        # expected and a top-level pass still cannot conceal the vote.
        split_candidate = release_candidate(
            24,
            policy,
            manifest,
            baseline,
            review_value=split,
        )
        split_result = compare_release(baseline, split_candidate, policy, manifest)
        self.assertEqual("FAIL", split_result["status"])
        self.assertIn("human_perceptual_review_baseline_preferred", blocker_reasons(split_result))

    def test_unbound_not_applicable_evidence_and_forged_runtime_exception_fail(self):
        manifest, policy, baseline, candidate = inputs()
        evidence = {"status": "not_applicable", "reason": "self asserted", "evidence_id": "self-asserted"}
        for report in (baseline, candidate):
            for run in report["runs"]:
                if run["track_id"] == "lead-pop":
                    run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = copy.deepcopy(evidence)
        unbound = compare_release(baseline, candidate, policy, manifest)
        self.assertEqual("FAIL", unbound["status"])
        self.assertIn("release_metric_not_applicable_unbound", blocker_reasons(unbound))

        manifest = release_manifest()
        policy = release_policy(manifest, accelerator_available=False)
        baseline = release_report(100, policy, manifest)
        candidate = release_candidate(24, policy, manifest, baseline)
        for report in (baseline, candidate):
            for run in report["runs"]:
                for metric in gate._ACCELERATOR_NOT_APPLICABLE_METRICS:
                    root, leaf = metric.split(".")
                    run["metrics"][root][leaf] = {
                        "status": "not_applicable",
                        "reason": "forged",
                        "evidence_id": "forged",
                    }
        forged = compare_release(baseline, candidate, policy, manifest)
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
        candidate = release_candidate(24, policy, manifest, baseline)
        annotation = {"status": "not_applicable", "reason": "no licensed backing-role annotation", "evidence_id": "annotation-no-backing"}
        accelerator = {"status": "not_applicable", "reason": "locked CPU-only host", "evidence_id": "runtime-no-accelerator"}
        for report in (baseline, candidate):
            for run in report["runs"]:
                if run["track_id"] == "lead-pop":
                    run["metrics"]["quality"]["vocal_lead_backing_role_accuracy"] = copy.deepcopy(annotation)
                for metric in gate._ACCELERATOR_NOT_APPLICABLE_METRICS:
                    root, leaf = metric.split(".")
                    run["metrics"][root][leaf] = copy.deepcopy(accelerator)
        # The locked annotations are part of the final benchmark evidence, so
        # review must be signed after they are written, not before.
        attest_candidate_review(candidate, baseline, policy)
        result = compare_release(baseline, candidate, policy, manifest)
        self.assertEqual("PASS_TARGET", result["status"])

    def test_one_track_missing_coverage_or_golden_artifact_cannot_pass(self):
        manifest = release_manifest()
        manifest["tracks"] = manifest["tracks"][:1]
        policy = release_policy(manifest)
        baseline = release_report(100, policy, manifest)
        result = compare_release(baseline, release_candidate(24, policy, manifest, baseline), policy, manifest)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("release_locked_corpus_too_small", blocker_reasons(result))
        self.assertIn("release_locked_corpus_coverage_missing", blocker_reasons(result))

        manifest = release_manifest()
        manifest["tracks"][0]["golden_artifacts"].pop("drum_map_sha256")
        policy = release_policy(manifest)
        baseline = release_report(100, policy, manifest)
        result = compare_release(baseline, release_candidate(24, policy, manifest, baseline), policy, manifest)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("release_locked_corpus_golden_artifacts_invalid", blocker_reasons(result))

    def test_per_run_audio_and_runtime_profile_are_bound(self):
        manifest, policy, baseline, candidate = inputs()
        candidate["runs"][0]["provenance"]["workload"]["audio"]["content_sha256"] = sha("wrong-audio")
        candidate["runs"][1]["provenance"]["environment"]["runtime_backend"] = "other"
        result = compare_release(baseline, candidate, policy, manifest)
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
            compare_release(baseline, candidate, policy, manifest),
            compare_release(copy.deepcopy(baseline), copy.deepcopy(candidate), policy, copy.deepcopy(manifest)),
        )


if __name__ == "__main__":
    unittest.main()
