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
import stat
import statistics
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "research/inference-device-regression-20260928/"
LIMIT = 2 * 1024 * 1024
STARTS = (-66150, 0, 22050, 44100, 88200)
OUTPUT_BYTES = 4586400
PACKAGE = "com.cyberbasslord.lightforge.inferenceprobe"
FIXTURE_SHA = "0d0bf21401ad0dbb8a49aae581a16f9a00cadca41e116b5a4dc27eaaa3625648"
# Explicitly reviewed durable audit from commit 6a91949a060f7bb8543266242ca01f4d2904c069.
# This allowlist is not populated from the APK, command line, or exported phone report.
# A later artifact requires another independently reviewed audit before admission here.
RETAINED_APK_AUDITS = {
    "a8efbf9e208b022760878062bed8efc3559e1b61e7c0baee563a18ba1b83666b": {
        "commit": "6a91949a060f7bb8543266242ca01f4d2904c069",
        "apk_sha256": "79dba57cc55d0fc61e42aa245f0f94c7a1d826aa184bb6be08026ff931712429",
        "apk_bytes": 113915300,
        "source_sha256": "b9b5991ab8746e96ef28675f23d6309ce5f985003df4d6f12ee4d5360d52d83b",
        "build_sha256": "2ec9d88783e89aa147540837fbf7d6624133e6c64c1af497d1e090a20f5c309d",
    },
}
APK_LIMIT = 256 * 1024 * 1024
APK_EXPANDED_LIMIT = 128 * 1024 * 1024
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


def bound_qualification_schedules(policy_path):
    """Recognize reviewed schedules in the hash-bound frozen policy only."""
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
        return [0, spacing, 2 * spacing], None
    # Four workers start at ordinal one only after an exact first eight-worker
    # pair loses. The seed validator must bind that shifted series too.
    if "intdue=qualificationOrigin+qualificationCount;" in compact:
        require(all(anchor in compact for anchor in (
            "ordinal!=qualificationOrigin||remainingUseful<24",
            "pair.ordinal!=qualificationOrigin+qualificationCount||",
            "rejected=pair;workers=alternateWorkers;alternateWorkers=0;qualificationOrigin=1;",
            "if(origin!=0&&(origin!=1||seed.workers!=4))returnfalse;",
            "p.ordinal!=origin+i||p.candidateFirst!=((i&1)!=0)",
        )), "Frozen alternate qualification schedule checks disagree")
        return [0, 1, 2], [1, 2, 3]
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
    ordinals, alternate_ordinals = bound_qualification_schedules(
        safe_file(frozen, "java-src/com/cyberbasslord/lightforge/NativePassagePolicy.java"))

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
            "qualification_ordinals": ordinals, "alternate_qualification_ordinals": alternate_ordinals,
            "model_manifest_sha256": source["modelManifestSha256"],
            "declared_model_bytes": sum(sizes), "fixture_pcm16_sha256": FIXTURE_SHA,
            "scope": "frozen-artifact-and-build-receipt-binding-not-device-attestation"}


def _apk_json(raw):
    require(len(raw) <= LIMIT, "APK JSON exceeds 2 MiB")
    def invalid_constant(_):
        raise ValueError("Non-finite APK JSON number")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid bounded APK JSON") from error
    require(isinstance(value, dict), "APK JSON must be an object")
    return value


def _apk_directory_bound(stream, size):
    """Bound central-directory allocation before ZipFile parses any entries.

    The reviewed APK is a single-disk, non-ZIP64 archive with no ZIP comment.
    Signature blocks are inside the whole-file hash, outside ZIP member content.
    """
    require(22 <= size <= APK_LIMIT, "Retained APK size exceeds bounds")
    stream.seek(size - 22)
    end = stream.read(22)
    signature, disk, directory_disk, entries_disk, entries, directory_size, offset, comment = struct.unpack("<4s4H2IH", end)
    require(signature == b"PK\x05\x06" and disk == directory_disk == comment == 0
            and entries_disk == entries and 0 < entries <= 64
            and directory_size <= 128 * 1024 and offset + directory_size == size - 22,
            "Unsupported or oversized APK central directory")
    stream.seek(0)
    return entries


def _retained_apk_members(apk, expected_sha, expected_size, source, source_sha, source_size, audit):
    """Hash every permitted member, without extraction or unbounded decompression."""
    require(apk.is_file() and not any(path.is_symlink() for path in (apk, *apk.parents)),
            "Missing or linked retained APK")
    require(apk.stat().st_size == expected_size and 0 < expected_size <= APK_LIMIT,
            "Retained APK byte count mismatch")
    runtime = source["runtime"]
    native = {"lib/" + name[len("jni/"):]: pin for name, pin in runtime["files"].items() if name.startswith("jni/")}
    fixture = source["fixture"]
    pins = {**native, **{"assets/probe/" + name: pin for name, pin in runtime["notices"].items()},
            "assets/probe/source-receipt.json": {"sha256": source_sha, "bytes": source_size},
            "assets/" + fixture["assetPath"]: {"sha256": fixture["pcm16Sha256"],
                                                "bytes": 44 + fixture["samplesPerChannel"] * fixture["channels"] * 2}}
    dex = audit["dexHashes"]
    require(isinstance(dex, dict) and set(dex) == {"classes.dex"}, "Unexpected audited DEX inventory")
    pins.update({name: {"sha256": sha} for name, sha in dex.items()})
    json_names = {"assets/probe/source-receipt.json", "assets/probe/fixture-provenance.json"}
    apk_bound_names = {"AndroidManifest.xml", "resources.arsc", "META-INF/PROBE.SF", "META-INF/PROBE.RSA", "META-INF/MANIFEST.MF"}
    expected_names = set(pins) | json_names | apk_bound_names
    require(len(expected_names) <= 64, "APK member inventory exceeds bounds")
    for pin in pins.values():
        require(isinstance(pin.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", pin["sha256"])
                and ("bytes" not in pin or type(pin["bytes"]) is int and 0 < pin["bytes"] <= 64 * 1024 * 1024),
                "Invalid APK member pin")
    observed, documents = {}, {}
    with apk.open("rb") as stream:
        def full_hash():
            stream.seek(0)
            sha, count = hashlib.sha256(), 0
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                require(count <= expected_size, "Retained APK grew during verification")
                sha.update(chunk)
            require(count == expected_size and sha.hexdigest() == expected_sha, "Retained APK hash mismatch")
        full_hash()
        entry_count = _apk_directory_bound(stream, expected_size)
        try:
            with zipfile.ZipFile(stream) as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                require(len(infos) == entry_count and len(names) == len(set(names)), "Duplicate APK entries")
                require(set(names) == expected_names, "Unexpected APK member inventory")
                require(sum(info.file_size for info in infos) <= APK_EXPANDED_LIMIT, "APK expanded size exceeds bounds")
                for info in infos:
                    name = info.filename
                    require(info.orig_filename == name and len(name) <= 512 and "\\" not in name and "\x00" not in name
                            and not name.startswith("/") and all(part not in ("", ".", "..") for part in name.split("/"))
                            and not info.is_dir(), "Unsafe APK member path")
                    require(stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                            and info.flag_bits & ~0x800 == 0
                            and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                            "Unsupported APK member type or encoding")
                    limit = 64 * 1024 * 1024 if name.startswith("lib/") else 16 * 1024 * 1024 if name.endswith(".dex") else LIMIT
                    require(0 < info.file_size <= limit and 0 < info.compress_size <= expected_size
                            and info.file_size <= info.compress_size * 200, "APK member size or compression exceeds bounds")
                    sha, count, chunks = hashlib.sha256(), 0, []
                    with archive.open(info) as member:
                        while True:
                            chunk = member.read(min(1024 * 1024, limit + 1 - count))
                            if not chunk:
                                break
                            count += len(chunk)
                            require(count <= limit and count <= info.file_size, "APK member expanded beyond its declared size")
                            sha.update(chunk)
                            if name in json_names:
                                chunks.append(chunk)
                    require(count == info.file_size, "APK member byte count mismatch")
                    actual = {"bytes": count, "sha256": sha.hexdigest()}
                    pin = pins.get(name)
                    require(pin is None or all(actual.get(key) == value for key, value in pin.items()), "APK member pin mismatch: " + name)
                    observed[name] = {**actual, "binding": "independent-member-pin-and-complete-apk" if pin else "complete-apk-hash"}
                    if name in json_names:
                        documents[name] = _apk_json(b"".join(chunks))
                require(reference_json_equal(documents["assets/probe/source-receipt.json"], source), "APK embedded source receipt mismatch")
                require(reference_json_equal(documents["assets/probe/fixture-provenance.json"], fixture), "APK fixture provenance mismatch")
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as error:
            raise ValueError("Invalid retained APK ZIP content") from error
        # Recheck the same open file after member reads, detecting concurrent changes.
        full_hash()
    return observed


def verify_retained_apk_reference(source, build, source_sha, repo, apk, audit_path):
    """Bind a recovered APK to a reviewed durable audit, never pretend to restore a build.

    Compiled classes/JAR, signature validity and manifest semantics were inspected
    by the original audit. Their original bytes/tools are not reconstituted here.
    This mode verifies APK identity/content and current source pins independently;
    it is not a release gate, reproducible build, or cryptographic device attestation.
    """
    repo, apk, audit_path = Path(repo), Path(apk), Path(audit_path)
    audit_file = safe_file(audit_path.parent, audit_path.name)
    audit, audit_sha = load(audit_file)
    require(audit_sha in RETAINED_APK_AUDITS, "Unreviewed retained APK audit")
    approved = RETAINED_APK_AUDITS[audit_sha]
    require(audit.get("schema") == "lightforge.inference-device-probe-artifact-audit.v1", "Unknown retained APK audit schema")
    archive = audit_path.parent
    archived_source = bound_file(archive, "source-receipt.json", approved["source_sha256"])
    archived_build = bound_file(archive, "build.json", approved["build_sha256"])
    original_source, _ = load(archived_source)
    original_build, _ = load(archived_build)
    require(source_sha == approved["source_sha256"] and reference_json_equal(source, original_source), "Claimed source differs from retained audit")
    require(reference_json_equal(build, original_build) and reference_json_equal(audit.get("artifact"), build), "Claimed build differs from retained audit")
    require(build.get("sha256") == approved["apk_sha256"] and type(build.get("bytes")) is int and build["bytes"] == approved["apk_bytes"]
            and build.get("sourceReceiptSha256") == source_sha, "Retained build identity mismatch")
    require(source.get("schema") == "lightforge-inference-device-probe-source-v1"
            and source.get("packageName") == build.get("packageName") == PACKAGE
            and source.get("runtimeVersion") == build.get("runtimeVersion") == "1.25.1", "Wrong retained companion identity")
    require(source.get("releaseArtifact") is False and source.get("modelGraphsBundled") is False
            and build.get("releaseArtifact") is False and build.get("updateCompatibleWithLightForge") is False
            and build.get("executionPerformed") is False, "Retained artifact is not an isolated companion")
    expected = source.get("expectedInstalledPackage", {})
    require(expected.get("packageName") == "com.cyberbasslord.lightforge" and type(expected.get("versionCode")) is int
            and expected["versionCode"] == 20401 and build.get("signerSha256") != expected.get("signerSha256"), "Wrong retained signing or asset identity")
    require(all(build.get(key) is True for key in ("signatureVerified", "alignmentVerified", "zipVerified"))
            and audit.get("phoneExecutionPerformed") is False and audit.get("productionReleaseArtifact") is False,
            "Missing original artifact inspection")
    checks = audit.get("checks", {})
    require(all(checks.get(key) is True for key in ("apkSignatureV2V3", "aligned16KiB", "compiledJarClassHashesMatch",
            "currentSourceBinding", "exactAssetInventoryAndBytes", "exactDexInventoryAndBytes", "exactPinnedNativeLibraryInventoryAndBytes",
            "noAndroidPermissions", "productionSigningIdentityExcluded")), "Original audit lacks required checks")
    archive_pins = audit.get("archiveReceipts", {})
    require(archive_pins.get("source-receipt.json") == source_sha and archive_pins.get("build.json") == approved["build_sha256"]
            and set(archive_pins) == {"AndroidManifest.xml", "build.json", "build.log", "source-receipt.json"}, "Unexpected audit receipt inventory")
    for name, sha in archive_pins.items():
        bound_file(archive, name, sha)
    sources, compiled = source.get("sourceHashes", {}), source["build"]["compiledClassHashes"]
    require(isinstance(sources, dict) and len(sources) == audit.get("compiledSourceFileCount")
            and isinstance(compiled, dict) and len(compiled) == audit.get("compiledClassCount")
            and source["build"]["compiledJarSha256"] == audit.get("compiledJarSha256"), "Original compiled closure audit mismatch")
    for path, sha in sources.items():
        require(isinstance(path, str) and re.fullmatch(r"(?:android|qa/inference-device-probe)/src/com/cyberbasslord/lightforge/[A-Za-z_$][A-Za-z0-9_$]*\.java", path)
                and isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha), "Unsafe retained source pin")
    fixture, runtime = source["fixture"], source["runtime"]
    require(fixture.get("assetPath") == "probe/falcon-mix.wav" and fixture.get("pcm16Sha256") == FIXTURE_SHA
            and all(type(fixture.get(key)) is int and fixture[key] == value for key, value in
                    (("sampleRate", 44100), ("channels", 2), ("samplesPerChannel", 300032))), "Wrong retained fixture geometry")
    native_names = {"jni/" + abi + "/" + name for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
                    for name in ("libonnxruntime.so", "libonnxruntime4j_jni.so")}
    require(set(runtime["files"]) == {"classes.jar"} | native_names
            and set(runtime["notices"]) == {"onnxruntime-native-LICENSE.txt", "onnxruntime-native-ThirdPartyNotices.txt"},
            "Wrong retained runtime inventory")
    recorded = audit.get("sourceBinding", {})
    require(recorded.get("historical_binding_passed") is True and recorded.get("current_source_binding_passed") is True
            and recorded.get("source_reference_sha256") == source_sha and recorded.get("apk_sha256") == approved["apk_sha256"]
            and recorded.get("model_manifest_sha256") == source["modelManifestSha256"]
            and recorded.get("fixture_pcm16_sha256") == FIXTURE_SHA
            and recorded.get("qualification_ordinals") == [0, 1, 2]
            and type(recorded.get("declared_model_bytes")) is int and recorded["declared_model_bytes"] > 0,
            "Original source binding audit mismatch")
    members = _retained_apk_members(apk, approved["apk_sha256"], approved["apk_bytes"], source, source_sha, archived_source.stat().st_size, audit)
    current_pins = {**sources,
        "qa/inference-device-probe/build_probe.py": source["build"]["builder"]["sha256"],
        "qa/inference-device-probe/AndroidManifest.xml": source["build"]["manifest"]["sha256"],
        "android/native-runtime.json": runtime["manifest"]["sha256"],
        "web/analysis/models/deux/manifest.json": source["modelManifestSha256"],
        fixture["sourceProvenancePath"]: fixture["sourceProvenanceSha256"], fixture["sourcePath"]: fixture["sourceSha256"],
    }
    mismatches, verified = [], 0
    for path, sha in current_pins.items():
        try:
            observed = digest(safe_file(repo, path))
            reason = "sha256-mismatch" if observed != sha else None
        except (OSError, ValueError):
            observed, reason = None, "missing-or-unsafe-reference-file"
        if reason:
            mismatches.append({"path": path, "expected_sha256": sha, "observed_sha256": observed, "reason": reason})
        elif path in sources:
            verified += 1
    return {"verification_mode": "retained-apk-and-reviewed-archive", "retained_apk_binding_passed": True,
            "source_reference_sha256": source_sha, "apk_sha256": approved["apk_sha256"],
            "audit_sha256": audit_sha, "audit_commit": approved["commit"],
            "repository_source_files_verified": verified, "current_source_binding_passed": not mismatches,
            "current_source_mismatches": mismatches, "qualification_ordinals": recorded["qualification_ordinals"],
            "model_manifest_sha256": source["modelManifestSha256"], "declared_model_bytes": recorded["declared_model_bytes"],
            "fixture_pcm16_sha256": FIXTURE_SHA, "newly_verified_apk_members": members,
            "historical_only_checks": {"scope": "recorded-by-hash-bound-original-audit-not-reperformed",
                "original_compiled_class_count": len(compiled), "original_compiled_jar_sha256": source["build"]["compiledJarSha256"],
                "runtime_java_jar_sha256": runtime["files"]["classes.jar"]["sha256"],
                "signature_and_signer": "original-v2-v3-signature-audit; complete-identical-apk-hash-verified-now",
                "alignment_and_manifest_semantics": "original-audit; packaged-bytes-bound-to-identical-apk-now"},
            "original_build_bytes_reconstructed": False, "signature_verification_performed_now": False,
            "release_qualification_performed": False,
            "scope": "retained-apk-and-reviewed-archive-binding-not-frozen-build-reconstruction-or-device-attestation"}


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
            rejected = [pair for pair in policy["pairs"] if pair["role"] == "rejected"]
            if rejected:
                check(identity.get("alternate_qualification_ordinals") == [1, 2, 3]
                      and identity.get("qualification_ordinals") == [0, 1, 2],
                      prefix + "alternate-not-supported-by-frozen-policy")
            if controller["state"] == "qualified":
                ordinals = (identity.get("alternate_qualification_ordinals") if rejected
                            else identity.get("qualification_ordinals"))
                known_schedule = (ordinals == [1, 2, 3] if rejected
                                  else ordinals in ([0, 4, 8], [0, 1, 2]))
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
                check(identity.get("qualification_ordinals") == [0, 1, 2]
                      and (not rejected or identity.get("alternate_qualification_ordinals") == [1, 2, 3]),
                      prefix + "control-not-supported-by-frozen-policy")
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
    reference_mode = parser.add_mutually_exclusive_group()
    reference_mode.add_argument("--frozen-build", type=Path, help="Frozen companion build directory whose artifacts produced the receipt")
    reference_mode.add_argument("--retained-apk", type=Path, help="Explicit recovery mode: exact retained APK bound to a reviewed durable audit; does not reconstruct original classes/JAR")
    parser.add_argument("--reference-audit", type=Path, help="Reviewed verification.json; required only with --retained-apk")
    parser.add_argument("--require-current-source", action="store_true", help="Fail the source-binding gate if reviewed current sources differ from the historical companion")
    args = parser.parse_args()
    if bool(args.retained_apk) != bool(args.reference_audit):
        parser.error("--retained-apk and --reference-audit must be supplied together")
    if args.retained_apk and (not args.reference_source or not args.reference_build):
        parser.error("Retained APK recovery requires explicit --reference-source and --reference-build")
    source, source_sha = load(args.reference_source or args.repo / (REFERENCE + "device-probe-sources.json"))
    build, _ = load(args.reference_build or args.repo / (REFERENCE + "device-probe-build.json"))
    identity = (verify_retained_apk_reference(source, build, source_sha, args.repo, args.retained_apk, args.reference_audit)
                if args.retained_apk else verify_reference(source, build, source_sha, args.repo, frozen_dir=args.frozen_build))
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
