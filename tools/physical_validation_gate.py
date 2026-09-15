#!/usr/bin/env python3
"""Verify optional physical device and vehicle validation attestations.

A production release cannot infer physical Android or vehicle behavior from an
emulator receipt. This module verifies a detached Ed25519 attestation that is
bound to the exact sealed CI candidate and current source profile. Authority
keys live only in reviewed source; the repository intentionally ships with no
configured production key. Physical observations are optional for publication;
this verifier is used only when a physical validation claim is supplied.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import re
import subprocess
import tempfile
from types import MappingProxyType


PHYSICAL_VALIDATION_SCHEMA_VERSION = 1
PHYSICAL_VALIDATION_PROTOCOL = "lightforge-physical-validation-attestation-v1"
PHYSICAL_VALIDATION_ALGORITHM = "ed25519"
VERIFY_WORKFLOW = ".github/workflows/verify-v2.yml"
VEHICLE_PROFILE_SOURCE_PATH = "web/engine/vehicle-profile.js"

# Add production public keys only through a reviewed source change. A secret
# cannot introduce authority because private signing material must remain
# external and the verifier resolves this registry before accepting an
# attestation.
PHYSICAL_VALIDATION_AUTHORITY_KEYS = MappingProxyType({})

# Physical claim acceptance bounds are immutable source policy. An external signer
# can attest observed evidence, but cannot relax the evidence floor or tail
# latency limits through a secret payload.
MINIMUM_PHYSICAL_TIMING_SAMPLES = 100
COMMAND_TIMESTAMP_ERROR_LIMITS_MS = MappingProxyType({
    "p95": 50.0,
    "p99": 100.0,
    "max": 250.0,
})
PERCEPTUAL_RESPONSE_ERROR_LIMITS_MS = MappingProxyType({
    "p95": 250.0,
    "p99": 500.0,
    "max": 1000.0,
})
PHYSICAL_VALIDATION_PERCENTILE_METHOD = "linear-interpolation-n-minus-1-v1"
MINIMUM_PHYSICAL_EVENT_COVERAGE_PERCENT = MappingProxyType({
    "lighting": 95,
    "mechanical": 90,
})
# A perfect 1/1 class is not a representative physical playback claim. Keep
# independently source-pinned floors for exercised output coverage and timing.
MINIMUM_PHYSICAL_ELIGIBLE_EVENT_COUNTS = MappingProxyType({
    "lighting": 50,
    "mechanical": 50,
})
MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES = MappingProxyType({
    "lighting": 50,
    "mechanical": 50,
})
MAX_PHYSICAL_VALIDATION_OBSERVED_TO_ISSUED_AGE = timedelta(hours=24)
MAX_PHYSICAL_VALIDATION_ISSUED_TO_VERIFICATION_AGE = timedelta(hours=24)
MAX_PHYSICAL_VALIDATION_OBSERVED_TO_VERIFICATION_AGE = timedelta(hours=24)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
_RELEASE_NAME = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_PERCENTILES = ("p50", "p90", "p95", "p99", "max")
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "protocol",
    "authority_id",
    "algorithm",
    "verification_key_sha256",
    "release",
    "source",
    "candidate",
    "android_evidence",
    "private_evidence",
    "installed_apk",
    "device",
    "vehicle",
    "measurements",
    "review",
    "signed_payload_sha256",
    "signature_base64",
}


def canonical_json(value):
    """Return the exact JSON representation that is signed."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _require(value, message):
    if not value:
        raise ValueError(message)
    return value


def _mapping(value, expected, label):
    _require(isinstance(value, dict) and set(value) == set(expected), label + " fields are invalid")
    return value


def _sha256(value, label, *, reject_placeholder=False):
    _require(isinstance(value, str) and _SHA256.fullmatch(value), label + " must be a lower-case sha256")
    if reject_placeholder:
        _require(len(set(value)) != 1, label + " must not be a synthetic placeholder sha256")
    return value


def _sha40(value, label):
    _require(isinstance(value, str) and _SHA40.fullmatch(value), label + " must be a full lower-case commit sha")
    return value


def _positive_int(value, label):
    _require(type(value) is int and value > 0, label + " must be a positive integer")
    return value


def _clean_string(value, label, *, maximum=256):
    _require(isinstance(value, str) and value and value == value.strip() and "\x00" not in value,
             label + " must be a non-empty trimmed string")
    _require(len(value) <= maximum, label + " is too long")
    return value


def _opaque_id(value, label):
    value = _clean_string(value, label)
    _require(_OPAQUE_ID.fullmatch(value), label + " must be an opaque identifier")
    return value


def _canonical_base64(value, label, *, decoded_length):
    _require(isinstance(value, str) and value, label + " must be a non-empty canonical base64 string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError(label + " must be a canonical base64 string") from error
    _require(base64.b64encode(decoded).decode("ascii") == value,
             label + " must be a canonical base64 string")
    _require(len(decoded) == decoded_length,
             label + " must decode to exactly " + str(decoded_length) + " bytes")
    return decoded


def _source_authority(authority_id):
    """Return one source-pinned Ed25519 authority or fail closed."""
    try:
        configured_count = len(PHYSICAL_VALIDATION_AUTHORITY_KEYS)
    except TypeError:
        configured_count = 0
    try:
        record = PHYSICAL_VALIDATION_AUTHORITY_KEYS.get(authority_id)
    except AttributeError:
        record = None
    if not isinstance(record, dict):
        if configured_count == 0:
            raise ValueError("Physical validation authority is unconfigured in reviewed source")
        raise ValueError("Physical validation authority is unknown or misconfigured")
    _mapping(
        record,
        {"protocol", "algorithm", "verification_key_base64", "verification_key_sha256"},
        "Source physical validation authority",
    )
    _require(record["protocol"] == PHYSICAL_VALIDATION_PROTOCOL,
             "Source physical validation authority protocol is unsupported")
    _require(record["algorithm"] == PHYSICAL_VALIDATION_ALGORITHM,
             "Source physical validation authority algorithm is unsupported")
    key = _canonical_base64(
        record["verification_key_base64"],
        "Source physical validation authority verification_key_base64",
        decoded_length=32,
    )
    key_sha256 = _sha256(
        record["verification_key_sha256"],
        "Source physical validation authority verification_key_sha256",
        reject_placeholder=True,
    )
    _require(hashlib.sha256(key).hexdigest() == key_sha256,
             "Source physical validation authority key digest differs")
    return {
        "authority_id": authority_id,
        "protocol": PHYSICAL_VALIDATION_PROTOCOL,
        "algorithm": PHYSICAL_VALIDATION_ALGORITHM,
        "verification_key_base64": record["verification_key_base64"],
        "verification_key_sha256": key_sha256,
    }


def _verify_ed25519_signature(public_key, payload, signature):
    """Verify detached Ed25519 evidence without any hash-only fallback."""
    payload_bytes = canonical_json(payload).encode("utf-8")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        pass
    else:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload_bytes)
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True

    # RFC 8410 SubjectPublicKeyInfo prefix for a raw 32-byte Ed25519 key.
    public_key_der = bytes.fromhex("302a300506032b6570032100") + public_key
    public_key_pem = (
        b"-----BEGIN PUBLIC KEY-----\n"
        + base64.encodebytes(public_key_der)
        + b"-----END PUBLIC KEY-----\n"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="lightforge-physical-attestation-") as temporary:
            root = Path(temporary)
            key_path = root / "public-key.pem"
            payload_path = root / "payload.json"
            signature_path = root / "signature.bin"
            key_path.write_bytes(public_key_pem)
            payload_path.write_bytes(payload_bytes)
            signature_path.write_bytes(signature)
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(key_path),
                    "-rawin",
                    "-in",
                    str(payload_path),
                    "-sigfile",
                    str(signature_path),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def _release(value, label):
    _mapping(value, {"name", "code"}, label)
    _require(isinstance(value["name"], str) and _RELEASE_NAME.fullmatch(value["name"]),
             label + ".name must be a stable semantic version")
    _positive_int(value["code"], label + ".code")
    return value


def _source(value, label):
    _mapping(value, {"commit", "tree_sha"}, label)
    _sha40(value["commit"], label + ".commit")
    _sha40(value["tree_sha"], label + ".tree_sha")
    return value


def _candidate(value, label):
    _mapping(
        value,
        {
            "workflow",
            "run_id",
            "run_attempt",
            "evidence_session",
            "artifact_id",
            "artifact_digest",
            "identity_sha256",
            "apk_sha256",
        },
        label,
    )
    _require(value["workflow"] == VERIFY_WORKFLOW, label + ".workflow differs from production verification")
    _positive_int(value["run_id"], label + ".run_id")
    _positive_int(value["run_attempt"], label + ".run_attempt")
    _require(isinstance(value["evidence_session"], str) and _SHA256.fullmatch(value["evidence_session"]),
             label + ".evidence_session must be a sha256")
    _positive_int(value["artifact_id"], label + ".artifact_id")
    for field in ("artifact_digest", "identity_sha256", "apk_sha256"):
        _sha256(value[field], label + "." + field)
    return value


def _android_evidence(value, label):
    _mapping(
        value,
        {
            "workflow",
            "run_id",
            "run_attempt",
            "evidence_session",
            "artifact_id",
            "artifact_digest",
            "manifest_sha256",
            "receipt_sha256",
        },
        label,
    )
    _require(value["workflow"] == VERIFY_WORKFLOW, label + ".workflow differs from production verification")
    _positive_int(value["run_id"], label + ".run_id")
    _positive_int(value["run_attempt"], label + ".run_attempt")
    _require(isinstance(value["evidence_session"], str) and _SHA256.fullmatch(value["evidence_session"]),
             label + ".evidence_session must be a sha256")
    _positive_int(value["artifact_id"], label + ".artifact_id")
    for field in ("artifact_digest", "manifest_sha256"):
        _sha256(value[field], label + "." + field)
    receipts = _mapping(
        value["receipt_sha256"],
        {"android-background-verification.json", "android-diagnostics-verification.json"},
        label + ".receipt_sha256",
    )
    for name, receipt_sha256 in receipts.items():
        _sha256(receipt_sha256, label + ".receipt_sha256." + name)
    return value


def _package_name(value, label):
    value = _clean_string(value, label, maximum=255)
    _require(_PACKAGE.fullmatch(value), label + " must be an Android application id")
    return value


def _private_evidence(value):
    _mapping(value, {"manifest_sha256", "reference"}, "Physical private evidence")
    _sha256(value["manifest_sha256"], "Physical private evidence.manifest_sha256")
    _opaque_id(value["reference"], "Physical private evidence.reference")
    return value


def _installed_apk(value, candidate, expected_package_name, release):
    _mapping(
        value,
        {"apk_sha256", "package_name", "version_name", "version_code"},
        "Physical installed APK",
    )
    apk_sha256 = _sha256(value["apk_sha256"], "Physical installed APK.apk_sha256")
    package_name = _package_name(value["package_name"], "Physical installed APK.package_name")
    _require(
        isinstance(value["version_name"], str) and _RELEASE_NAME.fullmatch(value["version_name"]),
        "Physical installed APK.version_name must be a stable semantic version",
    )
    _positive_int(value["version_code"], "Physical installed APK.version_code")
    _require(
        apk_sha256 == candidate["apk_sha256"],
        "Physical installed APK digest differs from the sealed candidate",
    )
    _require(
        package_name == expected_package_name,
        "Physical installed APK package differs from the source package",
    )
    _require(
        value["version_name"] == release["name"] and value["version_code"] == release["code"],
        "Physical installed APK version differs from the release",
    )
    return value


def _device(value, expected_package_name):
    _mapping(value, {"fingerprint", "manufacturer", "model", "api_level", "abi", "package_name"}, "Physical device")
    for field, maximum in (("fingerprint", 512), ("manufacturer", 128), ("model", 256), ("abi", 64)):
        _clean_string(value[field], "Physical device." + field, maximum=maximum)
    _positive_int(value["api_level"], "Physical device.api_level")
    _require(value["api_level"] <= 1000, "Physical device.api_level is implausible")
    package_name = _package_name(value["package_name"], "Physical device.package_name")
    _require(package_name == expected_package_name, "Physical device package does not match the source APK package")
    return value


def _vehicle_profile(value):
    _mapping(value, {"source_path", "source_sha256", "id", "version"}, "Vehicle profile")
    _require(value["source_path"] == VEHICLE_PROFILE_SOURCE_PATH,
             "Vehicle profile source path is unsupported")
    _sha256(value["source_sha256"], "Vehicle profile.source_sha256")
    _opaque_id(value["id"], "Vehicle profile.id")
    _clean_string(value["version"], "Vehicle profile.version", maximum=128)
    return value


def _vehicle(value, expected_profile):
    _mapping(value, {"vehicle_id", "firmware_version", "profile"}, "Vehicle")
    _opaque_id(value["vehicle_id"], "Vehicle.vehicle_id")
    _clean_string(value["firmware_version"], "Vehicle.firmware_version", maximum=128)
    _vehicle_profile(value["profile"])
    _require(value["profile"] == expected_profile, "Vehicle profile differs from the source-pinned profile")
    return value


def _nonnegative_number(value, label):
    _require(type(value) in (int, float) and not isinstance(value, bool)
             and math.isfinite(value) and value >= 0,
             label + " must be a finite non-negative number")
    return value


def _timing_percentiles(value, label, limits):
    _mapping(value, set(_PERCENTILES), label)
    values = [_nonnegative_number(value[name], label + "." + name) for name in _PERCENTILES]
    _require(values == sorted(values), label + " percentiles must be ordered p50 <= p90 <= p95 <= p99 <= max")
    for percentile, maximum in limits.items():
        _require(
            value[percentile] <= maximum,
            label + "." + percentile + " exceeds source-pinned maximum "
            + str(maximum) + " ms",
        )
    return value


def _event_coverage(value):
    event_classes = set(MINIMUM_PHYSICAL_EVENT_COVERAGE_PERCENT)
    _require(
        event_classes == set(MINIMUM_PHYSICAL_ELIGIBLE_EVENT_COUNTS)
        == set(MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES),
        "Physical validation source-pinned event classes are inconsistent",
    )
    _mapping(value, event_classes, "Physical validation event coverage")
    for event_class, minimum_percent in MINIMUM_PHYSICAL_EVENT_COVERAGE_PERCENT.items():
        coverage = _mapping(
            value[event_class],
            {"eligible_events", "realized_events"},
            "Physical validation " + event_class + " coverage",
        )
        eligible = _positive_int(
            coverage["eligible_events"],
            "Physical validation " + event_class + " eligible_events",
        )
        minimum_eligible = MINIMUM_PHYSICAL_ELIGIBLE_EVENT_COUNTS[event_class]
        _require(
            eligible >= minimum_eligible,
            "Physical validation " + event_class
            + " eligible_events must be at least source-pinned minimum "
            + str(minimum_eligible),
        )
        realized = coverage["realized_events"]
        _require(
            type(realized) is int and 0 <= realized <= eligible,
            "Physical validation " + event_class
            + " realized_events must be an integer from zero through eligible_events",
        )
        _require(
            realized * 100 >= eligible * minimum_percent,
            "Physical validation " + event_class
            + " coverage is below source-pinned minimum",
        )
    return value


def _per_class_timing(value):
    _mapping(
        value,
        set(MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES),
        "Physical validation per-class timing",
    )
    for event_class, minimum_samples in MINIMUM_PHYSICAL_CLASS_TIMING_SAMPLES.items():
        timing = _mapping(
            value[event_class],
            {"samples", "command_timestamp_error_ms", "perceptual_response_error_ms"},
            "Physical validation " + event_class + " timing",
        )
        samples = _positive_int(
            timing["samples"],
            "Physical validation " + event_class + " timing.samples",
        )
        _require(
            samples >= minimum_samples,
            "Physical validation " + event_class
            + " timing.samples must be at least source-pinned minimum "
            + str(minimum_samples),
        )
        _timing_percentiles(
            timing["command_timestamp_error_ms"],
            "Physical validation " + event_class + " command timestamp error",
            COMMAND_TIMESTAMP_ERROR_LIMITS_MS,
        )
        _timing_percentiles(
            timing["perceptual_response_error_ms"],
            "Physical validation " + event_class + " perceptual response error",
            PERCEPTUAL_RESPONSE_ERROR_LIMITS_MS,
        )
    return value


def _measurements(value):
    _mapping(value, {"android", "vehicle", "timing", "coverage"}, "Physical validation measurements")
    android = _mapping(
        value["android"],
        {
            "installation_passed",
            "launch_passed",
            "background_analysis_passed",
            "resume_recovery_passed",
            "diagnostics_passed",
        },
        "Physical validation Android measurements",
    )
    for name, passed in android.items():
        _require(passed is True, "Physical validation Android measurement did not pass: " + name)
    vehicle = _mapping(
        value["vehicle"],
        {
            "tesla_playback_passed",
            "actuator_feasibility_passed",
            "safety_incident_count",
            "uncommanded_event_count",
        },
        "Physical validation vehicle measurements",
    )
    _require(vehicle["tesla_playback_passed"] is True,
             "Physical validation Tesla playback did not pass")
    _require(vehicle["actuator_feasibility_passed"] is True,
             "Physical validation actuator feasibility did not pass")
    for name in ("safety_incident_count", "uncommanded_event_count"):
        _require(type(vehicle[name]) is int and vehicle[name] == 0,
                 "Physical validation " + name + " must be explicitly zero")
    timing = _mapping(
        value["timing"],
        {
            "samples",
            "percentile_method",
            "command_timestamp_error_ms",
            "perceptual_response_error_ms",
            "per_class",
        },
        "Physical validation timing measurements",
    )
    _require(
        timing["percentile_method"] == PHYSICAL_VALIDATION_PERCENTILE_METHOD,
        "Physical validation timing percentile method is unsupported",
    )
    samples = _positive_int(timing["samples"], "Physical validation timing.samples")
    _require(
        samples >= MINIMUM_PHYSICAL_TIMING_SAMPLES,
        "Physical validation timing.samples must be at least "
        + str(MINIMUM_PHYSICAL_TIMING_SAMPLES),
    )
    _timing_percentiles(
        timing["command_timestamp_error_ms"],
        "Physical validation command timestamp error",
        COMMAND_TIMESTAMP_ERROR_LIMITS_MS,
    )
    _timing_percentiles(
        timing["perceptual_response_error_ms"],
        "Physical validation perceptual response error",
        PERCEPTUAL_RESPONSE_ERROR_LIMITS_MS,
    )
    _per_class_timing(timing["per_class"])
    _event_coverage(value["coverage"])
    return value


def _timestamp(value, label):
    _require(isinstance(value, str) and _TIMESTAMP.fullmatch(value),
             label + " must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(label + " must be a valid UTC timestamp") from error
    return parsed


def _review(value, now):
    _mapping(value, {"reviewer_id", "observed_at", "issued_at", "expires_at", "verdict"}, "Physical validation review")
    _opaque_id(value["reviewer_id"], "Physical validation review.reviewer_id")
    _require(value["verdict"] == "pass", "Physical validation review verdict must be pass")
    observed = _timestamp(value["observed_at"], "Physical validation review.observed_at")
    issued = _timestamp(value["issued_at"], "Physical validation review.issued_at")
    expires = _timestamp(value["expires_at"], "Physical validation review.expires_at")
    _require(observed <= issued <= now, "Physical validation review timestamps are not current and ordered")
    _require(
        issued - observed <= MAX_PHYSICAL_VALIDATION_OBSERVED_TO_ISSUED_AGE,
        "Physical validation review observed evidence is older than source-pinned maximum at issue",
    )
    _require(
        now - issued <= MAX_PHYSICAL_VALIDATION_ISSUED_TO_VERIFICATION_AGE,
        "Physical validation review issuance is older than source-pinned maximum at verification",
    )
    _require(
        now - observed <= MAX_PHYSICAL_VALIDATION_OBSERVED_TO_VERIFICATION_AGE,
        "Physical validation review observation is older than source-pinned maximum at verification",
    )
    _require(expires > now, "Physical validation review has expired")
    _require(expires >= issued and expires - issued <= timedelta(days=30),
             "Physical validation review expiry must be after issue and no more than 30 days")
    return value


def signed_payload(attestation):
    """Return the exact projection an external physical authority signs."""
    _require(isinstance(attestation, dict), "Physical validation attestation must be an object")
    return {
        name: value
        for name, value in attestation.items()
        if name not in {"signed_payload_sha256", "signature_base64"}
    }


def _reject_duplicate_json_object_keys(pairs):
    value = {}
    for key, member in pairs:
        _require(key not in value, "Physical validation attestation JSON has duplicate object keys")
        value[key] = member
    return value


def load_attestation(path):
    """Load a private regular 0600 JSON file through one no-follow descriptor."""
    _require(
        hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_CLOEXEC"),
        "Physical validation attestation secure open flags are unavailable",
    )
    descriptor = None
    try:
        descriptor = os.open(
            os.fspath(path),
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as error:
        raise ValueError("Physical validation attestation file is invalid") from error
    try:
        try:
            metadata = os.fstat(descriptor)
        except OSError as error:
            raise ValueError("Physical validation attestation file is invalid") from error
        _require(
            stat.S_ISREG(metadata.st_mode),
            "Physical validation attestation file must be a regular file",
        )
        _require(
            stat.S_IMODE(metadata.st_mode) == 0o600,
            "Physical validation attestation file must have mode 0600",
        )
        try:
            stream = os.fdopen(descriptor, "r", encoding="utf-8", closefd=True)
        except OSError as error:
            raise ValueError("Physical validation attestation file is invalid") from error
        descriptor = None
        try:
            with stream:
                value = json.load(stream, object_pairs_hook=_reject_duplicate_json_object_keys)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Physical validation attestation file is invalid") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _require(isinstance(value, dict), "Physical validation attestation must be an object")
    return value


def verify_physical_validation_attestation(
    attestation,
    *,
    release,
    source,
    candidate,
    android_evidence,
    expected_package_name,
    expected_vehicle_profile,
    now=None,
):
    """Verify an authority-signed, source/candidate-bound physical validation.

    Inputs other than the attestation are derived by the protected publisher
    from sealed artifacts and source bytes. The attestation can only confirm
    those exact bindings; it cannot choose them.
    """
    _release(release, "Expected release")
    _source(source, "Expected source")
    _candidate(candidate, "Expected candidate")
    _android_evidence(android_evidence, "Expected Android evidence")
    expected_package_name = _package_name(expected_package_name, "Expected Android package")
    _vehicle_profile(expected_vehicle_profile)

    now = datetime.now(timezone.utc) if now is None else now
    _require(isinstance(now, datetime) and now.tzinfo is not None,
             "Physical validation verification clock must be timezone-aware")
    now = now.astimezone(timezone.utc)

    _mapping(attestation, _TOP_LEVEL_FIELDS, "Physical validation attestation")
    _require(attestation["schema_version"] == PHYSICAL_VALIDATION_SCHEMA_VERSION,
             "Physical validation attestation schema is unsupported")
    _require(attestation["protocol"] == PHYSICAL_VALIDATION_PROTOCOL,
             "Physical validation attestation protocol is unsupported")
    authority_id = _opaque_id(attestation["authority_id"], "Physical validation authority_id")
    _require(attestation["algorithm"] == PHYSICAL_VALIDATION_ALGORITHM,
             "Physical validation attestation algorithm is unsupported")
    authority = _source_authority(authority_id)
    _require(attestation["verification_key_sha256"] == authority["verification_key_sha256"],
             "Physical validation attestation authority key binding differs")

    _release(attestation["release"], "Physical validation attestation release")
    _source(attestation["source"], "Physical validation attestation source")
    _candidate(attestation["candidate"], "Physical validation attestation candidate")
    _android_evidence(attestation["android_evidence"], "Physical validation attestation Android evidence")
    _require(attestation["release"] == release, "Physical validation attestation release differs from publisher")
    _require(attestation["source"] == source, "Physical validation attestation source differs from publisher")
    _require(attestation["candidate"] == candidate, "Physical validation attestation candidate differs from publisher")
    _require(attestation["android_evidence"] == android_evidence,
             "Physical validation attestation Android evidence differs from publisher")

    _private_evidence(attestation["private_evidence"])
    _installed_apk(
        attestation["installed_apk"],
        candidate,
        expected_package_name,
        release,
    )
    _device(attestation["device"], expected_package_name)
    _vehicle(attestation["vehicle"], expected_vehicle_profile)
    _measurements(attestation["measurements"])
    _review(attestation["review"], now)

    payload = signed_payload(attestation)
    expected_payload_sha256 = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    _require(attestation["signed_payload_sha256"] == expected_payload_sha256,
             "Physical validation attestation signed payload digest differs")
    signature = _canonical_base64(
        attestation["signature_base64"],
        "Physical validation attestation signature_base64",
        decoded_length=64,
    )
    public_key = _canonical_base64(
        authority["verification_key_base64"],
        "Source physical validation authority verification_key_base64",
        decoded_length=32,
    )
    verified = _verify_ed25519_signature(public_key, payload, signature)
    _require(verified is not None, "Physical validation Ed25519 verification backend is unavailable")
    _require(verified is True, "Physical validation attestation signature is invalid")

    # Do not return raw device fingerprints, deterministic derivatives, or
    # other field-observation detail to public workflow logs. The signed secret
    # remains private; the receipt reports only safe immutable release bindings.
    return {
        "schema_version": PHYSICAL_VALIDATION_SCHEMA_VERSION,
        "status": "verified",
        "authority_id": authority_id,
        "verification_key_sha256": authority["verification_key_sha256"],
        # The payload digest is verified in memory but is a deterministic
        # commitment to private device, vehicle, and reference fields. Do not
        # publish it in the otherwise public release receipt.
        "release": dict(release),
        "source": dict(source),
        "candidate_identity_sha256": candidate["identity_sha256"],
        "android_evidence_manifest_sha256": android_evidence["manifest_sha256"],
        "physical_evidence_manifest_sha256": attestation["private_evidence"]["manifest_sha256"],
        "vehicle_profile": dict(expected_vehicle_profile),
        "review": {
            "reviewer_id": attestation["review"]["reviewer_id"],
            "observed_at": attestation["review"]["observed_at"],
            "issued_at": attestation["review"]["issued_at"],
            "expires_at": attestation["review"]["expires_at"],
            "verdict": "pass",
        },
    }
