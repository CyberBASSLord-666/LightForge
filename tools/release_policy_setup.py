#!/usr/bin/env python3
"""Validate or privately sign an approved release policy/corpus bundle.

This local helper never changes GitHub settings, creates keys, or attests to
benchmark results or human review. It reuses the production gate's canonical
contract and source-pinned authority registry. No input JSON or private key is
printed, including on errors.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

import performance_quality_gate as gate


MAX_SECRET_BYTES = 48 * 1024
MAX_PRIVATE_KEY_BYTES = 64 * 1024


class SetupError(ValueError):
    """An intentionally non-sensitive error code safe for terminal output."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SetupError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise SetupError("nonfinite_json_number")


def load_json(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            raise SetupError("json_exceeds_github_secret_limit")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        if not isinstance(value, dict):
            raise SetupError("json_object_required")
        return value
    except SetupError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise SetupError("json_input_unreadable_or_invalid") from None


def validate_inputs(policy, manifest):
    try:
        *_, profile = gate._validate_policy(policy)
    except (ValueError, TypeError, KeyError):
        raise SetupError("invalid_release_policy") from None
    if profile["mode"] != "release":
        raise SetupError("release_mode_required")
    try:
        corpus = gate.validate_locked_corpus_manifest(manifest, policy)
    except (ValueError, TypeError, KeyError):
        raise SetupError("invalid_locked_corpus") from None
    reference = profile["policy_authority"]
    authority = gate._source_policy_authority(reference["authority_id"])
    if authority is None:
        raise SetupError("source_policy_authority_unconfigured")
    if reference != {key: authority[key] for key in reference}:
        raise SetupError("source_policy_authority_binding_mismatch")
    return profile, {
        "policy_sha256": gate.policy_sha256(policy),
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "authority_id": reference["authority_id"],
        "verification_key_sha256": reference["verification_key_sha256"],
        "track_count": corpus["track_count"],
    }


def validate_bundle(policy, manifest, attestation):
    profile, summary = validate_inputs(policy, manifest)
    diagnostics, blockers = gate._release_policy_authority_diagnostics(
        profile, summary["policy_sha256"], attestation)
    if blockers or diagnostics.get("verified") is not True:
        raise SetupError("policy_attestation_not_verified")
    return {**summary, "policy_attestation_verified": True,
            "qualification_status": "not_evaluated"}


def _private_key_bytes(path):
    path = Path(path).absolute()
    # The policy identity is not an Android key. Neither belongs in this repo.
    repository = Path(__file__).resolve().parents[1]
    if path.resolve().is_relative_to(repository):
        raise SetupError("private_key_must_be_outside_repository")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
            raise SetupError("private_key_requires_regular_owner_only_file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            key = stream.read(MAX_PRIVATE_KEY_BYTES + 1)
        if not key or len(key) > MAX_PRIVATE_KEY_BYTES:
            raise SetupError("invalid_private_key_size")
        return key
    except SetupError:
        raise
    except OSError:
        raise SetupError("private_key_unreadable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _openssl(arguments):
    try:
        result = subprocess.run(["openssl", *arguments], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SetupError("openssl_signing_unavailable") from None
    if result.returncode:
        raise SetupError("openssl_signing_failed")
    return result.stdout


def sign_bundle(policy, manifest, private_key_path):
    profile, summary = validate_inputs(policy, manifest)
    key = _private_key_bytes(private_key_path)
    payload = gate._policy_authority_attestation_payload(
        profile_authority=profile["policy_authority"],
        policy_sha256=summary["policy_sha256"],
        corpus_manifest_sha256=summary["corpus_manifest_sha256"])
    canonical_payload = gate.canonical_json(payload).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="lightforge-private-policy-signing-") as temporary:
        root = Path(temporary)
        key_path, payload_path = root / "key.pem", root / "payload.json"
        with key_path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(key)
        payload_path.write_bytes(canonical_payload)
        public_der = _openssl(["pkey", "-in", str(key_path), "-pubout", "-outform", "DER"])
        prefix = bytes.fromhex("302a300506032b6570032100")
        if not public_der.startswith(prefix) or len(public_der) != len(prefix) + 32:
            raise SetupError("private_key_must_be_ed25519")
        if hashlib.sha256(public_der[len(prefix):]).hexdigest() != summary["verification_key_sha256"]:
            raise SetupError("private_key_does_not_match_source_authority")
        signature = _openssl(["pkeyutl", "-sign", "-rawin", "-inkey", str(key_path),
                              "-in", str(payload_path)])
    receipt = {**payload,
               "signed_payload_sha256": hashlib.sha256(canonical_payload).hexdigest(),
               "signature_base64": base64.b64encode(signature).decode("ascii")}
    validate_bundle(policy, manifest, receipt)
    return receipt


def write_new_receipt(path, receipt):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise SetupError("receipt_output_must_be_new_and_writable") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        Path(path).unlink(missing_ok=True)
        raise SetupError("receipt_output_write_failed") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("validate", "sign"):
        command = subparsers.add_parser(operation)
        command.add_argument("--policy", required=True)
        command.add_argument("--manifest", required=True)
        if operation == "validate":
            command.add_argument("--attestation", required=True)
        else:
            command.add_argument("--private-key", required=True)
            command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        policy, manifest = load_json(args.policy), load_json(args.manifest)
        if args.operation == "sign":
            receipt = sign_bundle(policy, manifest, args.private_key)
            summary = validate_bundle(policy, manifest, receipt)
            write_new_receipt(args.output, receipt)
        else:
            summary = validate_bundle(policy, manifest, load_json(args.attestation))
        print(json.dumps(summary, sort_keys=True))
        return 0
    except SetupError as error:
        print("release_policy_setup: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
