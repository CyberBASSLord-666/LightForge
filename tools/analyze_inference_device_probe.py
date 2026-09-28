#!/usr/bin/env python3
"""Validate and summarize an exported isolated device probe; never qualify a release.

Standard library only. Reads receipts and source files, never installs, builds,
connects to a device, or executes inference. JSON output is created exclusively.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "research/inference-device-regression-20260928/"
LIMIT = 2 * 1024 * 1024
STARTS = (-66150, 0, 22050, 44100, 88200)
OUTPUT_BYTES = 4586400
PACKAGE = "com.cyberbasslord.lightforge.inferenceprobe"
FIXTURE_SHA = "0d0bf21401ad0dbb8a49aae581a16f9a00cadca41e116b5a4dc27eaaa3625648"
SPEC = importlib.util.spec_from_file_location("probe_diagnostic_evidence", Path(__file__).with_name("diagnostic_evidence.py"))
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def load(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    require(len(raw) <= LIMIT, "Receipt exceeds 2 MiB")
    def invalid_constant(_):
        raise ValueError("Non-finite JSON number")
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    require(isinstance(value, dict), "Receipt must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_file(root, relative):
    require(isinstance(relative, str), "Invalid reference path")
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and ".." not in parts.parts and "\\" not in relative, "Unsafe reference path")
    path = root.joinpath(*parts.parts)
    require(root.resolve() in path.resolve().parents and path.is_file(), "Missing reference file")
    require(not any(root.joinpath(*parts.parts[:index]).is_symlink() for index in range(1, len(parts.parts)+1)), "Linked reference file")
    return path


def reference_json_equal(left, right):
    """Compare JSON identities without treating booleans or floats as integers."""
    return json.dumps(left, sort_keys=True, allow_nan=False, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, allow_nan=False, separators=(",", ":"))


def bound_file(root, relative, sha, size=None):
    require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha), "Invalid reference digest")
    path = safe_file(root, relative)
    require(size is None or (type(size) is int and size >= 0 and path.stat().st_size == size),
            "Frozen file size mismatch: " + relative)
    require(digest(path) == sha, "Frozen file hash mismatch: " + relative)
    return path


def bound_qualification_ordinals(policy_path):
    """Recognize reviewed schedule forms in the hash-bound frozen policy only."""
    policy = policy_path.read_text(encoding="utf-8")
    policy = re.sub(r"/\*.*?\*/|//[^\n]*", "", policy, flags=re.S)
    compact = re.sub(r"\s+", "", policy)
    # Historical device probe: the plan and pair acceptance both use count * 4.
    # A contiguous policy may use count directly. Reject unrecognized schedules.
    match = re.search(r"intdue=qualificationCount(?:\*([1-9][0-9]*))?;", compact)
    if match:
        spacing = int(match.group(1) or 1)
        expression = "qualificationCount" + ("*" + match.group(1) if match.group(1) else "")
        require(spacing <= 16 and "pair.ordinal!=" + expression + "||" in compact,
                "Frozen qualification schedule checks disagree")
        return [0, spacing, 2 * spacing]
    raise ValueError("Unrecognized frozen qualification schedule")


def verify_reference(source, build, source_sha, repo, frozen_dir=None):
    """Bind historical evidence to frozen files; report current source drift separately.

    This checks retained bytes against reviewed receipts, not build reproducibility,
    APK signature verification performed now, or attestation of a running device.
    """
    repo = Path(repo)
    frozen = Path(frozen_dir) if frozen_dir is not None else repo / "build/inference-device-probe/run-w6e3elh2"
    require(frozen.is_dir() and not frozen.is_symlink(), "Missing or linked frozen build directory")
    require(source.get("schema") == "lightforge-inference-device-probe-source-v1", "Unknown source receipt schema")
    require(source.get("packageName") == build.get("packageName") == PACKAGE, "Wrong companion package")
    require(source.get("runtimeVersion") == build.get("runtimeVersion") == "1.25.1", "Wrong runtime")
    require(build.get("sourceReceiptSha256") == source_sha, "Source receipt byte identity differs from build receipt")
    require(source.get("releaseArtifact") is False and source.get("modelGraphsBundled") is False
            and build.get("releaseArtifact") is False and build.get("updateCompatibleWithLightForge") is False,
            "Reference is not an isolated companion")
    require(all(build.get(key) is True for key in ("signatureVerified", "alignmentVerified", "zipVerified")), "Unverified reference build")
    expected = source.get("expectedInstalledPackage", {})
    require(expected.get("packageName") == "com.cyberbasslord.lightforge" and type(expected.get("versionCode")) is int
            and expected["versionCode"] == 20401, "Wrong installed asset package reference")
    require(build.get("signerSha256") != expected.get("signerSha256"), "Companion uses production signing identity")
    frozen_source, frozen_source_sha = load(safe_file(frozen, "assets/probe/source-receipt.json"))
    require(frozen_source_sha == source_sha and reference_json_equal(frozen_source, source), "Frozen source receipt identity mismatch")
    require(build.get("apk") == "LightForge-inference-probe.apk", "Unexpected companion APK filename")
    frozen_build, _ = load(safe_file(frozen, "LightForge-inference-probe.apk.json"))
    require(reference_json_equal(frozen_build, build), "Frozen build receipt identity mismatch")

    sources = source.get("sourceHashes", {})
    required = {"android/src/com/cyberbasslord/lightforge/" + name + ".java" for name in
                ("NativeDeux", "NativeDeuxTransform", "NativeExecutionPolicy", "NativePassagePolicy", "NativeInferenceProfile")}
    required.add("qa/inference-device-probe/src/com/cyberbasslord/lightforge/ProbeRunner.java")
    require(isinstance(sources, dict) and required <= sources.keys(), "Missing source closure")
    staged_sources = set()
    for path, sha in sources.items():
        require(isinstance(path, str) and re.fullmatch(
            r"(?:android|qa/inference-device-probe)/src/(com/cyberbasslord/lightforge/[A-Za-z_$][A-Za-z0-9_$]*\.java)", path),
            "Unsafe or unexpected source closure path")
        staged = "java-src/" + path.split("/src/", 1)[1]
        require(staged not in staged_sources, "Shadowed frozen source")
        staged_sources.add(staged)
        bound_file(frozen, staged, sha)
    build_source = source["build"]
    bound_file(frozen, "build_probe.py", build_source["builder"]["sha256"], build_source["builder"]["bytes"])
    bound_file(frozen, "AndroidManifest.xml", build_source["manifest"]["sha256"], build_source["manifest"]["bytes"])
    bound_file(frozen, "classes.jar", build_source["compiledJarSha256"])
    compiled = build_source["compiledClassHashes"]
    require(isinstance(compiled, dict) and compiled, "Missing compiled class closure")
    for path, sha in compiled.items():
        require(isinstance(path, str) and re.fullmatch(r"com/cyberbasslord/lightforge/[A-Za-z_$][A-Za-z0-9_$]*\.class", path),
                "Unsafe or unexpected compiled class path")
        bound_file(frozen, "classes/" + path, sha)
    actual_classes = {str(path.relative_to(frozen / "classes")) for path in (frozen / "classes").rglob("*.class")}
    require(actual_classes == set(compiled), "Frozen compiled class inventory mismatch")
    runtime_info = source["runtime"]
    bound_file(frozen, "runtime/native-runtime.json", runtime_info["manifest"]["sha256"], runtime_info["manifest"]["bytes"])
    runtime, _ = load(safe_file(frozen, "runtime/native-runtime.json"))
    require(reference_json_equal(runtime["files"], runtime_info["files"]), "Runtime file inventory mismatch")
    for path, pin in runtime_info["files"].items():
        bound_file(frozen, "runtime/" + path, pin["sha256"], pin["bytes"])
    for path, pin in runtime_info["notices"].items():
        bound_file(frozen, "assets/probe/" + path, pin["sha256"], pin["bytes"])
    fixture = source["fixture"]
    require(fixture.get("pcm16Sha256") == FIXTURE_SHA and type(fixture.get("sampleRate")) is int and fixture["sampleRate"] == 44100
            and type(fixture.get("channels")) is int and fixture["channels"] == 2
            and type(fixture.get("samplesPerChannel")) is int and fixture["samplesPerChannel"] == 300032,
            "Unexpected fixture identity or geometry")
    require(fixture.get("assetPath") == "probe/falcon-mix.wav", "Unexpected fixture asset path")
    bound_file(frozen, "assets/" + fixture["assetPath"], fixture["pcm16Sha256"])
    frozen_fixture, _ = load(safe_file(frozen, "assets/probe/fixture-provenance.json"))
    require(reference_json_equal(frozen_fixture, fixture), "Frozen fixture provenance mismatch")
    bound_file(frozen, "model-manifest.json", source["modelManifestSha256"])
    manifest, _ = load(safe_file(frozen, "model-manifest.json"))
    sizes = [row["bytes"] for row in manifest["files"].values()]
    require(sizes and all(type(size) is int and size > 0 for size in sizes), "Invalid model byte inventory")
    bound_file(frozen, build["apk"], build["sha256"], build["bytes"])
    ordinals = bound_qualification_ordinals(safe_file(frozen, "java-src/com/cyberbasslord/lightforge/NativePassagePolicy.java"))

    pins = {
        "qa/inference-device-probe/build_probe.py": build_source["builder"]["sha256"],
        "qa/inference-device-probe/AndroidManifest.xml": build_source["manifest"]["sha256"],
        "android/native-runtime.json": runtime_info["manifest"]["sha256"],
        "web/analysis/models/deux/manifest.json": source["modelManifestSha256"],
        fixture["sourceProvenancePath"]: fixture["sourceProvenanceSha256"],
        fixture["sourcePath"]: fixture["sourceSha256"],
    }
    current_mismatches = []
    verified_sources = 0
    for path, sha in {**sources, **pins}.items():
        try:
            current = safe_file(repo, path)
            observed = digest(current)
            reason = "sha256-mismatch" if observed != sha else None
        except (OSError, ValueError):
            observed, reason = None, "missing-or-unsafe-reference-file"
        if reason:
            current_mismatches.append({"path": path, "expected_sha256": sha, "observed_sha256": observed, "reason": reason})
        elif path in sources:
            verified_sources += 1
    return {"source_reference_sha256": source_sha, "apk_sha256": build["sha256"],
            "historical_binding_passed": True, "historical_source_files_verified": len(sources),
            "historical_compiled_classes_verified": len(compiled),
            "repository_source_files_verified": verified_sources,
            "current_source_binding_passed": not current_mismatches, "current_source_mismatches": current_mismatches,
            "qualification_ordinals": ordinals, "model_manifest_sha256": source["modelManifestSha256"],
            "declared_model_bytes": sum(sizes), "fixture_pcm16_sha256": FIXTURE_SHA,
            "scope": "frozen-artifact-and-build-receipt-binding-not-device-attestation"}


def integer(value, minimum=0):
    return value if type(value) is int and minimum <= value <= 2**63-1 else None


def boolean(value):
    return value if type(value) is bool else None


def failure_class(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]{0,80}", value) else None


def stats(values):
    observed = [value for value in values if value is not None]
    return {"observed_count": len(observed), "population_count": len(values),
            "observed_sum": sum(observed) if observed else None,
            "median": statistics.median(observed) if observed else None,
            "min": min(observed) if observed else None, "max": max(observed) if observed else None}


def profile_records(records, check, prefix, maximum=80):
    valid = (isinstance(records, list) and len(records) <= maximum
             and all(isinstance(item, str) and len(item) <= 16384 for item in records))
    check(valid, prefix + "invalid-profile-record-list")
    if not valid:
        records = []
    fields = []
    for record in records:
        pairs = EVIDENCE.FIELD.findall(record)
        check(len(dict(pairs)) == len(pairs), prefix + "duplicate-profile-field")
        fields.append(dict(pairs))
    summaries = [item for item in fields if item.get("schema") == "native-inference-profile-v2"]
    summary = summaries[0] if len(summaries) == 1 else {}
    return records, fields, {"line": None, "fields": summary,
                             "stages": [item for item in fields if item.get("schema") == "native-inference-stage-v1"],
                             "graphs": [item for item in fields if item.get("schema") == "native-inference-graph-v2"]}


def profile_geometry(profile, check, prefix, *, complete):
    summary = profile["fields"]
    temporal = {key: EVIDENCE._integer(summary, key) for key in EVIDENCE.TEMPORAL_SESSION_METRICS}
    frequency = {key: EVIDENCE._integer(summary, key) for key in EVIDENCE.FREQUENCY_SESSION_METRICS}
    has_frequency = any(key in summary for key in (*EVIDENCE.FREQUENCY_SESSION_METRICS, "frequencyConfigCountScope"))
    if not complete:
        return temporal, frequency
    check(EVIDENCE._profile_complete(profile) and {item.get("graph") for item in profile["graphs"]} == EVIDENCE.NATIVE_GRAPHS,
          prefix + "incomplete-production-graph-profile")
    time_counts = [EVIDENCE._integer(row, "runCount") for row in profile["graphs"] if row.get("graph", "").endswith("-time")]
    frequency_counts = [EVIDENCE._integer(row, "runCount") for row in profile["graphs"] if row.get("graph", "").endswith("-frequency")]
    check(len(time_counts) == len(frequency_counts) == 12 and all(count in (15, 60) for count in time_counts)
          and all(count in (11, 82) for count in frequency_counts), prefix + "invalid-graph-family-geometry")
    for row in profile["graphs"]:
        if row.get("graph") in ("front", "head-0", "head-1"):
            check(EVIDENCE._integer(row, "runCount") == (1 if row["graph"] == "front" else 11), prefix + "invalid-front-or-head-geometry")
    time_parallel = time_counts.count(60)
    frequency_parallel = frequency_counts.count(82)
    if all(value is not None for value in temporal.values()):
        check(sum(temporal.values()) == 12 and temporal["temporalUnobservedSessionCount"] == 0,
              prefix + "temporal-session-attempt-count")
        check(temporal["temporalBaselineSessionCount"] == time_counts.count(15)
              and temporal["temporalFourWorkerSessionCount"] + temporal["temporalEightWorkerSessionCount"] == time_parallel,
              prefix + "temporal-session-graph-distribution-mismatch")
    else:
        check(False, prefix + "missing-temporal-session-counts")
    if has_frequency:
        check(all(value is not None for value in frequency.values()), prefix + "missing-frequency-session-counts")
        if all(value is not None for value in frequency.values()):
            check(sum(frequency.values()) == 12 and frequency["frequencyUnobservedSessionCount"] == 0,
                  prefix + "frequency-session-attempt-count")
            check(frequency["frequencyBaselineSessionCount"] == frequency_counts.count(11)
                  and frequency["frequencyFourWorkerSessionCount"] + frequency["frequencyEightWorkerSessionCount"] == frequency_parallel,
                  prefix + "frequency-session-graph-distribution-mismatch")
        check(summary.get("frequencyConfigCountScope") == "session-init-attempts", prefix + "invalid-frequency-count-scope")
        config = EVIDENCE._scheduler_configuration(summary.get("frequencyConfig"), temporal=False)
        check(config is not None, prefix + "invalid-frequency-configuration")
        if config is not None and all(value is not None for value in frequency.values()):
            key = "frequencyFourWorkerSessionCount" if "-w4-" in config else "frequencyEightWorkerSessionCount" if "-w8-" in config else "frequencyBaselineSessionCount"
            check(frequency[key] > 0, prefix + "frequency-last-configuration-not-observed")
        # The private slot count leaves an independent per-graph binding count:
        # temporal B1 binds 4/8 slots; frequency B16 binds those slots plus one tail.
        observed_workers = {"temporal": {4: 0, 8: 0}, "frequency": {4: 0, 8: 0}}
        for graph in profile["graphs"]:
            name, count = graph.get("graph", ""), EVIDENCE._integer(graph, "runCount")
            bound = EVIDENCE._integer(graph, "tensorBindCount")
            check(EVIDENCE._integer(graph, "sessionInitCount") == 1, prefix + "graph-session-count-mismatch")
            family = "temporal" if name.endswith("-time") else "frequency" if name.endswith("-frequency") else None
            if family is not None and count == (60 if family == "temporal" else 82):
                workers = bound if family == "temporal" else bound - 1 if bound is not None else None
                check(workers in (4, 8), prefix + "graph-private-binding-count-mismatch")
                if workers in (4, 8):
                    observed_workers[family][workers] += 1
            else:
                check(bound == count and bound is not None, prefix + "graph-baseline-binding-count-mismatch")
        for family, counts in (("temporal", temporal), ("frequency", frequency)):
            for workers, label in ((4, "Four"), (8, "Eight")):
                check(observed_workers[family][workers] == counts[family + label + "WorkerSessionCount"],
                      prefix + family + "-worker-binding-distribution-mismatch")
    else:
        # Older receipts did not export frequency session counts. Preserve that
        # absence; it is not evidence for zero sessions or for a new B16 path.
        check(frequency_parallel == 0, prefix + "parallel-frequency-without-session-evidence")
    config = EVIDENCE._scheduler_configuration(summary.get("temporalConfig"), temporal=True)
    check(config is not None, prefix + "invalid-temporal-configuration")
    if config is not None and all(value is not None for value in temporal.values()):
        key = "temporalFourWorkerSessionCount" if "-w4-" in config else "temporalEightWorkerSessionCount" if "-w8-" in config else "temporalBaselineSessionCount"
        check(temporal[key] > 0, prefix + "temporal-last-configuration-not-observed")
    calls = EVIDENCE._integer(summary, "inferenceCount")
    check(calls == 335 + 45*time_parallel + 71*frequency_parallel, prefix + "graph-call-geometry-mismatch")
    check(EVIDENCE._integer(summary, "sessionInitCount") == 27, prefix + "session-count-mismatch")
    graph_calls = [EVIDENCE._integer(graph, "runCount") for graph in profile["graphs"]]
    check(all(count is not None for count in graph_calls) and sum(count or 0 for count in graph_calls) == calls,
          prefix + "graph-detail-count-mismatch")
    return temporal, frequency


AUXILIARY_SCOPES = {
    "profileWallScope": "collector-lifetime-not-arm-clock",
    "comparisonScope": "same-input-paired-attempts",
    "modelSetupScope": "observed-file-preparation-not-os-cache-equivalence",
}
MODEL_SETUP_FIELDS = ("verifiedModelsBefore", "verifiedModelsAfter", "extractionAttempts", "extractionBytesRead",
                      "existingFileChecksumAttempts", "existingFileChecksumBytesRead")


def candidate_evidence(raw, ordinal, pair, check, prefix):
    """Auxiliary attempt profiles never contribute production totals or create paired proof."""
    result = {"status": "unavailable", "scope": "auxiliary-candidate-profile-excluded-from-production-totals",
              "qualification_status": "not-evaluated", "paired_record_binding": "unavailable"}
    if raw is None:
        return result
    valid = True
    def verify(condition, code):
        nonlocal valid
        if not condition:
            valid = False
        check(condition, prefix + "candidate-evidence:" + code)
    if not isinstance(raw, dict):
        verify(False, "invalid-object")
        return {**result, "status": "invalid"}
    expected = {"schema", "ordinal", "workers", "candidateFirst", "commonPreflightVerifiedModelCount", "baseline", "candidate", "profile", *AUXILIARY_SCOPES}
    verify(set(raw) == expected and raw.get("schema") == "native-passage-candidate-evidence-v1", "invalid-schema-or-fields")
    verify(integer(raw.get("ordinal")) == ordinal, "ordinal-mismatch")
    verify(type(raw.get("workers")) is int and raw["workers"] in (4, 8), "invalid-workers")
    verify(type(raw.get("candidateFirst")) is bool, "invalid-order")
    common = integer(raw.get("commonPreflightVerifiedModelCount"))
    verify(common is not None and common <= 27, "invalid-common-preflight-count")
    for key, value in AUXILIARY_SCOPES.items():
        verify(raw.get(key) == value, "invalid-" + key)
    arms = {}
    for name in ("baseline", "candidate"):
        arm = raw.get(name)
        if name == "baseline" and arm is None:
            arms[name] = None
            continue
        if not isinstance(arm, dict):
            verify(False, "invalid-" + name + "-arm")
            arms[name] = None
            continue
        verify(set(arm) == {"outcome", "armWallNanos", "modelSetup"}, name + "-fields")
        outcome = arm.get("outcome")
        verify(outcome in ("completed", "failed", "cancelled"), name + "-outcome")
        wall = integer(arm.get("armWallNanos"), 1)
        verify(wall is not None if outcome == "completed" else arm.get("armWallNanos") is None, name + "-clock")
        setup = arm.get("modelSetup")
        setup = setup if isinstance(setup, dict) else {}
        verify(set(setup) == set(MODEL_SETUP_FIELDS), name + "-model-setup-fields")
        parsed = {key: integer(setup.get(key)) for key in MODEL_SETUP_FIELDS}
        verify(all(value is not None for value in parsed.values()), name + "-model-setup-values")
        for key in ("verifiedModelsBefore", "verifiedModelsAfter"):
            verify(parsed[key] is not None and parsed[key] <= 27, name + "-" + key)
        arms[name] = {"outcome": outcome if outcome in ("completed", "failed", "cancelled") else None,
                      "arm_wall_nanos": wall if outcome == "completed" else None, "model_setup": parsed}
    records, fields, profile = profile_records(raw.get("profile"), verify, "", maximum=52)
    verify(all(len(record) <= 8192 for record in records), "profile-record-too-long")
    verify(all(item.get("schema") in ("native-inference-profile-v2", "native-inference-stage-v1", "native-inference-graph-v2") for item in fields),
           "profile-has-non-profile-records")
    verify(EVIDENCE._profile_complete(profile), "incomplete-profile-record-set")
    candidate = arms.get("candidate")
    candidate_complete = candidate is not None and candidate["outcome"] == "completed"
    verify(candidate is not None and profile["fields"].get("outcome") == candidate["outcome"], "profile-outcome-mismatch")
    temporal, frequency = profile_geometry(profile, verify, "", complete=candidate_complete)
    if candidate_complete and raw.get("workers") in (4, 8):
        key = "temporalFourWorkerSessionCount" if raw["workers"] == 4 else "temporalEightWorkerSessionCount"
        verify(temporal.get(key) == 12, "candidate-worker-geometry-mismatch")
        if any(frequency.get(key) for key in EVIDENCE.FREQUENCY_SESSION_METRICS[1:3]):
            key = "frequencyFourWorkerSessionCount" if raw["workers"] == 4 else "frequencyEightWorkerSessionCount"
            verify(frequency.get(key) == 12, "candidate-frequency-worker-geometry-mismatch")
    if pair is not None:
        bound = (raw.get("workers") == int(pair["workers"]) and raw.get("candidateFirst") is pair["candidateFirst"]
                 and all(arms.get(name) is not None and arms[name]["outcome"] == "completed"
                         and arms[name]["arm_wall_nanos"] == pair[name + "Nanos"]["value"] for name in ("baseline", "candidate")))
        verify(bound, "paired-clock-or-order-mismatch")
        result["paired_record_binding"] = "matched-recorded-pair" if bound else "mismatch"
    elif raw.get("baseline") is None:
        verify(raw.get("candidateFirst") is True, "missing-baseline-for-baseline-first-attempt")
    preparation = [arm["model_setup"] for arm in arms.values() if arm is not None]
    matched_setup = (len(preparation) == 2 and common == 27 and all(
        setup["verifiedModelsBefore"] == setup["verifiedModelsAfter"] == 27 and
        all(setup[key] == 0 for key in MODEL_SETUP_FIELDS[2:]) for setup in preparation))
    result.update(status="observed" if valid else "invalid", ordinal=ordinal,
                  workers=raw.get("workers") if type(raw.get("workers")) is int and raw["workers"] in (4, 8) else None,
                  candidate_first=boolean(raw.get("candidateFirst")), common_preflight_verified_model_count=common,
                  arms=arms, profile_wall_scope=AUXILIARY_SCOPES["profileWallScope"],
                  candidate_profile=EVIDENCE._profile_totals([profile]),
                  temporal_session_attempt_counts=temporal, frequency_session_attempt_counts=frequency,
                  preparation_fairness={"matched_common_preflight_without_arm_file_preparation": matched_setup if valid else None,
                                        "scope": AUXILIARY_SCOPES["modelSetupScope"], "os_cache_equivalence": "not-established"})
    return result


def analyze(report, source, identity):
    require(report.get("schema") == "lightforge.inference-device-probe.v1", "Unknown device probe schema")
    passages = report.get("passages")
    require(isinstance(passages, list) and len(passages) <= 35 and all(isinstance(row, dict) for row in passages), "Invalid passage list")
    errors, warnings, rendered, unique_pairs, unique_controls, output_groups = [], [], [], {}, {}, defaultdict(list)
    def check(condition, code):
        if not condition:
            errors.append(code)
    check(json.dumps(report.get("source"), sort_keys=True) == json.dumps(source, sort_keys=True), "embedded-source-differs-from-independent-reference")
    check(integer(report.get("plannedPassages")) == 35, "wrong-planned-passage-count")
    check(report.get("freshPolicyCache") is True, "fresh-policy-cache-not-established")
    completed = [row for row in passages if row.get("outcome") == "completed"]
    check(integer(report.get("completedPassages", len(completed))) == len(completed), "completed-passage-count-mismatch")
    if passages:
        expected = source["expectedInstalledPackage"]
        installed = report.get("installedAssetPackage", {})
        installed = installed if isinstance(installed, dict) else {}
        check(all(installed.get(key) == value for key, value in expected.items()), "installed-asset-package-mismatch")
        check(report.get("modelManifestSha256") == source["modelManifestSha256"], "model-manifest-mismatch")
        check(report.get("declaredModelBytes") == identity["declared_model_bytes"], "model-byte-count-mismatch")
    finished = report.get("outcome") == "completed"
    if finished:
        check(len(completed) == len(passages) == 35, "incomplete-success-claim")
        for key in ("terminal", "inferenceCoordinatorFinished", "engineCloseReturned", "nativeResourceCleanupConfirmed", "temporaryCacheRemoved"):
            check(report.get(key) is True, "success-missing-" + key)
        check(report.get("cancelReason") == "", "success-with-cancellation")
    previous_extra, previous_projection, candidate_evidence_count = 0, 0, 0
    for index, row in enumerate(passages):
        prefix = "passage-" + str(index) + ":"
        check(integer(row.get("ordinal")) == index and integer(row.get("remainingUseful")) == 35-index, prefix + "ordinal-or-budget-mismatch")
        check(type(row.get("startSample")) is int and row.get("startSample") == STARTS[index % 5], prefix + "fixture-start-mismatch")
        records, fields, profile = profile_records(row.get("profile", []), check, prefix)
        summary = profile["fields"]
        policy = EVIDENCE._passage_policy([item for item, parsed in zip(records, fields) if parsed.get("schema") in EVIDENCE.POLICY_SCHEMAS],
                                          summary.get("passagePolicy"), source="device-passage")
        is_complete = row.get("outcome") == "completed"
        if is_complete:
            check(summary.get("outcome") == "completed", prefix + "profile-outcome-mismatch")
            output = row.get("output", {})
            output = output if isinstance(output, dict) else {}
            valid_output = (integer(output.get("bytes")) == OUTPUT_BYTES and integer(output.get("floatCount")) == OUTPUT_BYTES//4
                            and output.get("finite") is True and isinstance(output.get("sha256"), str)
                            and re.fullmatch(r"[a-f0-9]{64}", output["sha256"]) is not None
                            and type(output.get("maxAbs")) in (int, float) and math.isfinite(output["maxAbs"]) and output["maxAbs"] >= 0)
            check(valid_output, prefix + "invalid-complete-output-receipt")
            if valid_output and type(row.get("startSample")) is int:
                output_groups[row["startSample"]].append((index, output["sha256"]))
            check(integer(row.get("predictWallNanos"), 1) is not None, prefix + "invalid-prediction-wall-time")
            check(integer(row.get("predictProcessCpuMillis")) is not None, prefix + "invalid-process-cpu-time")
            check(policy["status"] == "observed", prefix + "missing-or-invalid-policy-snapshot")
        temporal, frequency = profile_geometry(profile, check, prefix, complete=is_complete)
        auxiliary_raw = row.get("candidateEvidence")
        candidate_evidence_count += "candidateEvidence" in row
        if "candidateEvidence" in row:
            check(auxiliary_raw is not None, prefix + "null-candidate-evidence")
        current_pair = next((pair for pair in policy.get("pairs", []) if pair["ordinal"]["value"] == index), None) if policy["status"] == "observed" else None
        auxiliary = candidate_evidence(auxiliary_raw, index, current_pair, check, prefix)
        controller = policy.get("controller")
        if controller and policy["status"] == "observed":
            extra, projection = controller["extraNanos"]["value"], controller["projectedAccruedSavingsNanos"]["value"]
            check(controller["seeded"] is False, prefix + "unexpected-seeded-policy")
            check(extra >= previous_extra and projection >= previous_projection, prefix + "policy-cumulative-counter-regressed")
            previous_extra, previous_projection = extra, projection
            if extra > controller["extraCapNanos"]["value"]:
                warnings.append(prefix + "observed-extra-cost-exceeds-budget")
            qualification = [pair for pair in policy["pairs"] if pair["role"] == "qualification"]
            if controller["state"] == "qualified":
                ordinals = identity.get("qualification_ordinals")
                known_schedule = ordinals in ([0, 4, 8], [0, 1, 2])
                check(known_schedule, prefix + "unknown-frozen-qualification-schedule")
                check(len(qualification) == 3 and all(
                    known_schedule and pair["ordinal"]["value"] == ordinals[number] and pair["candidateFirst"] == (number % 2 == 1)
                    and pair["workers"] == controller["workers"]
                    and all(pair[flag] for flag in ("finite", "exact", "fullGeometry", "coldSessions"))
                    and pair["baselineNanos"]["value"] > 0
                    and pair["candidateNanos"]["value"]*100 <= pair["baselineNanos"]["value"]*95
                    for number, pair in enumerate(qualification)), prefix + "qualified-state-lacks-three-valid-pairs")
                if len(qualification) == 3:
                    check(statistics.median(pair["candidateNanos"]["value"] for pair in qualification)*100 <=
                          statistics.median(pair["baselineNanos"]["value"] for pair in qualification)*85,
                          prefix + "qualified-state-misses-median-reduction")
            for pair in policy["pairs"]:
                ordinal = pair["ordinal"]["value"]
                check(ordinal <= index and ordinal < len(passages), prefix + "pair-from-unobserved-passage")
                key = ordinal
                if key in unique_pairs:
                    check(unique_pairs[key]["record"] == pair, prefix + "conflicting-repeated-pair")
                    continue
                pair_output = passages[ordinal].get("output", {}) if ordinal < len(passages) else {}
                pair_output = pair_output if isinstance(pair_output, dict) else {}
                check(pair.get("outputSha256") == pair_output.get("sha256"), prefix + "paired-baseline-output-not-bound-to-passage")
                baseline, candidate = pair["baselineNanos"]["value"], pair["candidateNanos"]["value"]
                flags = all(pair.get(flag) is True for flag in ("finite", "exact", "fullGeometry", "coldSessions"))
                check(0 < baseline <= 3_600_000_000_000 and 0 < candidate <= 3_600_000_000_000
                      and min(baseline, candidate) <= pair["extraNanos"]["value"] <= 360_000_000_000,
                      prefix + "invalid-recorded-pair-timing")
                unique_pairs[key] = {"record": pair, "first_observed_after_passage": index,
                                     "comparison_scope": "same-input-complete-passage-arms-not-whole-job-savings",
                                     "pair_checks_reported_passed": flags,
                                     "observed_arm_wall_reduction_percent": 100*(baseline-candidate)/baseline if flags and baseline > 0 else None}
            for control in policy.get("controls", []):
                ordinal = control["ordinal"]["value"]
                check(identity.get("qualification_ordinals") == [0, 1, 2], prefix + "control-not-supported-by-frozen-policy")
                check(ordinal <= index and ordinal < len(passages), prefix + "control-from-unobserved-passage")
                if ordinal in unique_controls:
                    check(unique_controls[ordinal]["record"] == control, prefix + "conflicting-repeated-control")
                    continue
                baseline = control["baselineNanos"]["value"]
                previous = control["previousBaselineNanos"]["value"]
                candidate = control["candidateMaxNanos"]["value"]
                check(control["accepted"] == (candidate*100 <= min(baseline, previous)*95), prefix + "control-decision-mismatch")
                observed = passages[ordinal] if ordinal < len(passages) else {}
                check(observed.get("outcome") == "completed", prefix + "control-not-completed-useful-work")
                wall = integer(observed.get("predictWallNanos"))
                check(wall is not None and baseline <= wall, prefix + "control-timing-exceeds-prediction-wall")
                rows = observed.get("profile", [])
                rows = rows if isinstance(rows, list) else []
                control_summary = next((dict(EVIDENCE.FIELD.findall(item)) for item in rows
                                        if isinstance(item, str) and item.startswith("schema=native-inference-profile-v2 ")), {})
                check(EVIDENCE._integer(control_summary, "temporalBaselineSessionCount") == 12 and
                      all(EVIDENCE._integer(control_summary, key) == 0 for key in
                          ("temporalFourWorkerSessionCount", "temporalEightWorkerSessionCount", "temporalUnobservedSessionCount")),
                      prefix + "control-not-observed-complete-baseline-configuration")
                if any(key in control_summary for key in EVIDENCE.FREQUENCY_SESSION_METRICS):
                    check(EVIDENCE._integer(control_summary, "frequencyBaselineSessionCount") == 12 and
                          all(EVIDENCE._integer(control_summary, key) == 0 for key in EVIDENCE.FREQUENCY_SESSION_METRICS[1:]),
                          prefix + "control-not-observed-complete-baseline-frequency-configuration")
                unique_controls[ordinal] = {"record": control, "first_observed_after_passage": index,
                                            "comparison_scope": "unmatched-input-timing-guard-not-same-input-speed-or-equality-proof",
                                            "work_scope": "one-useful-baseline-output-no-candidate-replay",
                                            "extra_probe_nanos": 0,
                                            "foregone_acceleration_nanos": None,
                                            "foregone_acceleration_scope": "unmeasured-no-same-input-candidate-counterfactual"}
        rendered.append({"ordinal": index, "start_sample": row.get("startSample"), "outcome": row.get("outcome") if row.get("outcome") in ("completed", "running", "cancelled", "failed") else "unknown",
                         "failure_class": failure_class(row.get("failureClass")),
                         "predict_wall_nanos": integer(row.get("predictWallNanos")), "predict_process_cpu_millis": integer(row.get("predictProcessCpuMillis")),
                         "temporal_session_attempt_counts": temporal, "last_temporal_configuration": EVIDENCE._scheduler_configuration(summary.get("temporalConfig"), temporal=True),
                         "frequency_session_attempt_counts": frequency, "last_frequency_configuration": EVIDENCE._scheduler_configuration(summary.get("frequencyConfig"), temporal=False),
                         "production_inference_wall_millis": EVIDENCE._integer(summary, "inferenceWallMs"),
                         "reported_calibration_wall_millis": EVIDENCE._integer(summary, "schedulerCalibrationWallMs"),
                         "policy_snapshot": policy, "candidate_evidence": auxiliary})
    check(candidate_evidence_count <= 3, "too-many-candidate-evidence-records")
    groups = []
    for start, outputs in sorted(output_groups.items()):
        hashes = sorted({sha for _, sha in outputs})
        check(len(hashes) == 1, "repeated-input-output-mismatch:" + str(start))
        groups.append({"start_sample": start, "passage_ordinals": [index for index, _ in outputs], "sha256": hashes,
                       "comparison": "consistent-repeated-input" if len(outputs) > 1 and len(hashes) == 1 else "mismatch" if len(hashes) > 1 else "single-observation"})
    observations = [("run-before", report.get("before"))]
    observations += [(f"passage-{index}-{boundary}", row.get(boundary)) for index, row in enumerate(passages) for boundary in ("before", "after")]
    observations.append(("run-after", report.get("after")))
    boundary_fields = ("elapsedRealtimeMillis", "processCpuMillis", "availableProcessors", "availableMemoryBytes", "memoryThresholdBytes",
                       "processPeakRssBytes", "javaHeapUsedBytes", "nativeHeapAllocatedBytes", "thermalStatus", "batteryTemperatureTenthsC", "batteryLevel", "batteryScale", "plugged")
    boundaries, previous_clock = [], None
    for location, observation in observations:
        observation = observation if isinstance(observation, dict) else {}
        item = {"location": location, **{key: integer(observation.get(key)) for key in boundary_fields}}
        for key in ("lowMemory", "interactive", "powerSave", "deviceIdle"):
            item[key] = observation.get(key) if type(observation.get(key)) is bool else None
        boundaries.append(item)
        clock = item["elapsedRealtimeMillis"]
        if clock is not None:
            check(previous_clock is None or clock >= previous_clock, location + ":monotonic-boundary-clock-regressed")
            previous_clock = clock
        if item["thermalStatus"] is not None and item["thermalStatus"] >= 3:
            warnings.append(location + ":severe-or-higher-thermal-boundary")
    total_predict = sum(row["predict_wall_nanos"] or 0 for row in rendered)
    if integer(report.get("elapsedMillis")) is not None:
        check(total_predict <= (report["elapsedMillis"] + 2)*1_000_000, "prediction-times-exceed-entire-run")
    latest_extra = previous_extra if rendered and rendered[-1]["policy_snapshot"]["status"] == "observed" else None
    pair_extra = sum(pair["record"]["extraNanos"]["value"] for pair in unique_pairs.values())
    if latest_extra is not None:
        check(pair_extra <= latest_extra, "observed-pair-extra-exceeds-total-charged-extra")
    return {"schema": "lightforge.inference-device-probe-analysis.v1", "qualification_status": "not-evaluated",
            "integrity": {"passed": not errors, "errors": errors, "warnings": warnings, "reference": identity},
            "run": {"outcome": report.get("outcome") if report.get("outcome") in ("completed", "running", "cancelled", "failed") else "unknown",
                    "completed_passages": len(completed), "observed_passages": len(passages), "complete_35_passage_run": finished and not errors,
                    "elapsed_millis": integer(report.get("elapsedMillis")), "process_cpu_millis": integer(report.get("processCpuMillis")),
                    "failure_class": failure_class(report.get("failureClass")),
                    "cancel_reason": report.get("cancelReason") if report.get("cancelReason") in ("", "user-cancelled", "activity-not-visible", "time-budget", "thermal-severe", "guard-observation-failed") else None,
                    "terminal": boolean(report.get("terminal")), "coordinator_finished": boolean(report.get("inferenceCoordinatorFinished")),
                    "engine_close_returned": boolean(report.get("engineCloseReturned")),
                    "cleanup_confirmed": boolean(report.get("nativeResourceCleanupConfirmed")), "temporary_cache_removed": boolean(report.get("temporaryCacheRemoved"))},
            "passages": rendered, "same_input_output_groups": groups, "unique_observed_pairs": list(unique_pairs.values()),
            "unique_observed_controls": list(unique_controls.values()),
            "predict_wall_nanos": {"scope": "all-observed-attempts-including-probes-and-cancelled-partial-work", **stats([row["predict_wall_nanos"] for row in rendered])},
            "prediction_wall_by_outcome_nanos": {outcome: stats([row["predict_wall_nanos"] for row in rendered if row["outcome"] == outcome])
                                                  for outcome in sorted({row["outcome"] for row in rendered})},
            "policy_overhead": {"latest_cumulative_extra_nanos": latest_extra,
                                "unique_recorded_pair_extra_nanos": pair_extra,
                                "other_charged_extra_nanos": latest_extra-pair_extra if latest_extra is not None and latest_extra >= pair_extra else None,
                                "other_cost_scope": "screening-or-unrecorded-probe-cost-not-independent-proof-of-its-cause",
                                "latest_projected_accrued_savings_nanos": previous_projection if rendered and rendered[-1]["policy_snapshot"]["status"] == "observed" else None,
                                "savings_scope": "projected-not-measured", "extra_cost_already_in_prediction_wall": True},
            "boundary_observations": boundaries,
            "whole_job_speedup": {"status": "unavailable", "reason": "no-controlled-all-baseline-counterfactual-run"},
            "host_output_comparison": {"status": "not-comparable", "reason": "retained-host-integration-start-661500-differs-from-five-device-starts-and-runtime-platform"},
            "limitations": ["Receipt assertions are source-bound observations, not cryptographic device attestation.",
                            "The five repeated short-fixture inputs are not 35 independent songs or full-song quality evidence.",
                            "Pair snapshots repeat history; unique pair timings exclude ordinary-passage counterfactuals and cannot establish whole-job savings.",
                            "Controls advance useful baseline work using unmatched inputs; they add no candidate replay but forgo unmeasured acceleration and cannot establish same-input speed or equality.",
                            "Cold sessions do not establish cold filesystem or runtime caches; a single baseline-first pair is not a repeated alternating-order qualification.",
                            "Prediction wall includes policy overhead; do not add calibration or cumulative extra cost again.",
                            "Candidate profiles are auxiliary attempt diagnostics excluded from production totals; their collector lifetime is not an arm clock and they cannot independently establish paired or whole-job improvement.",
                            "Matched model-file preparation counters do not establish equivalent operating-system or runtime cache state.",
                            "Thermal and memory values are boundary snapshots, not continuous maxima; battery temperature is not CPU temperature.",
                            "Process CPU includes every companion process thread; this is not installed-LightForge lifecycle or release qualification."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--reference-source", type=Path)
    parser.add_argument("--reference-build", type=Path)
    parser.add_argument("--frozen-build", type=Path, help="Frozen companion build directory whose artifacts produced the receipt")
    parser.add_argument("--require-current-source", action="store_true", help="Fail the source-binding gate if reviewed current sources differ from the historical companion")
    args = parser.parse_args()
    source, source_sha = load(args.reference_source or args.repo / (REFERENCE + "device-probe-sources.json"))
    build, _ = load(args.reference_build or args.repo / (REFERENCE + "device-probe-build.json"))
    identity = verify_reference(source, build, source_sha, args.repo, frozen_dir=args.frozen_build)
    report, report_sha = load(args.report)
    result = analyze(report, source, identity)
    result["current_source_gate"] = {"required": args.require_current_source,
                                     "passed": identity["current_source_binding_passed"],
                                     "scope": "source-binding-only-not-release-qualification"}
    result["input_sha256"] = report_sha
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"integrity_passed": result["integrity"]["passed"], "outcome": result["run"]["outcome"],
                      "completed_passages": result["run"]["completed_passages"], "whole_job_speedup": "unavailable",
                      "current_source_binding_passed": identity["current_source_binding_passed"]}))
    return 0 if result["integrity"]["passed"] and (not args.require_current_source or identity["current_source_binding_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
