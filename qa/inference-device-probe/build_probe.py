#!/usr/bin/env python3
"""Build an isolated, non-release device probe only with an explicit --build.

Python 3.10+ standard library; existing JDK17, Android SDK35 and pinned ORT
1.25.1 files are required. This script neither downloads nor installs anything.
It does not call the release builder, package a model, or run an inference.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "qa/inference-device-probe"
PACKAGE = "com.cyberbasslord.lightforge.inferenceprobe"
JAVA_PACKAGE = Path("com/cyberbasslord/lightforge")
RELEASE_SIGNER = "7187d6aa935d5b7d2d656cb87913af95fe1ca3a4b1653036d1d8d890e2016c6b"
RUNTIME_VERSION = "1.25.1"
FIXTURE_SOURCE = "qa/release-1.6.0/fixtures/falcon-mix.wav"
FIXTURE_SHA256 = "effbbe3e3c0df821bf3cfa6535360b18339ded8041992373b41f8344998dba99"
PCM16_SHA256 = "0d0bf21401ad0dbb8a49aae581a16f9a00cadca41e116b5a4dc27eaaa3625648"
PRODUCTION_ENTRIES = (
    "NativeDeux.java", "NativeDeuxTransform.java", "NativeInferenceProfile.java",
    "NativeExecutionPolicy.java", "NativePassagePolicy.java", "AppDiagnostics.java",
)
COMPANION_ENTRIES = ("ProbeActivity.java", "ProbeRunner.java")
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot(path: Path, target: Path) -> dict:
    """Hash the source, frozen copy and source again to reject concurrent edits."""
    require(path.is_file() and not path.is_symlink(), "Missing or linked input: " + str(path))
    before = file_digest(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    require(before == file_digest(target) == file_digest(path), "Input changed during snapshot: " + str(path))
    return {"bytes": target.stat().st_size, "sha256": before}


def check_release_signer() -> None:
    # Read the release pin without importing or executing a packaging script.
    tree = ast.parse((ROOT / "tools/package_release.py").read_text(encoding="utf-8"))
    values = [ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "SIGNING_SHA256" for t in node.targets)]
    require(values == [RELEASE_SIGNER], "Release signer pin changed; review the probe's explicit signer rejection.")


def check_manifest(path: Path) -> None:
    manifest = ET.fromstring(path.read_bytes())
    require(manifest.tag == "manifest" and manifest.get("package") == PACKAGE, "Probe package must be isolated.")
    require(not any(node.tag.rsplit("}", 1)[-1].startswith("uses-permission")
                    for node in manifest.iter()), "The probe must request no Android permissions.")
    require(not manifest.get(ANDROID_NS + "sharedUserId"), "The probe must not share an application UID.")
    activities = manifest.findall("application/activity")
    require(any(node.get(ANDROID_NS + "name") == "com.cyberbasslord.lightforge.ProbeActivity"
                for node in activities), "Manifest must declare the fully qualified ProbeActivity.")


def stage_sources(destination: Path) -> dict[Path, dict]:
    """Freeze sources; javac entry points select the compiled dependency closure."""
    inventory = {}
    for base in (ROOT / "android/src", PROBE / "src"):
        paths = sorted(base.rglob("*.java"))
        require(paths, "No Java sources found: " + str(base))
        for path in paths:
            relative = path.relative_to(base)
            require(relative not in inventory, "Companion shadows a production source: " + str(relative))
            item = snapshot(path, destination / relative)
            item["sourcePath"] = path.relative_to(ROOT).as_posix()
            inventory[relative] = item
    for name in PRODUCTION_ENTRIES + COMPANION_ENTRIES:
        require(JAVA_PACKAGE / name in inventory, "Missing Java entry point: " + name)
    return inventory


def class_source_file(path: Path) -> str:
    """Read javac's SourceFile attribute, without executing compiler output."""
    stream = io.BytesIO(path.read_bytes())

    def take(size: int) -> bytes:
        value = stream.read(size)
        require(len(value) == size, "Truncated Java class: " + str(path))
        return value

    def u2() -> int:
        return struct.unpack(">H", take(2))[0]

    def u4() -> int:
        return struct.unpack(">I", take(4))[0]

    require(u4() == 0xCAFEBABE, "Invalid Java class: " + str(path))
    take(4)  # minor and major version
    count, index, strings = u2(), 1, {}
    while index < count:
        tag = take(1)[0]
        if tag == 1:
            # Attribute names and source filenames are ASCII, even though the
            # constant pool also permits modified UTF-8 string literals.
            strings[index] = take(u2())
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            take(4)
        elif tag in (5, 6):
            take(8)
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            take(2)
        elif tag == 15:
            take(3)
        else:
            raise RuntimeError("Unsupported class constant tag: " + str(tag))
        index += 1
    take(6)  # access flags, this class, superclass
    take(2 * u2())
    for _ in range(2):  # fields and methods
        for _ in range(u2()):
            take(6)
            for _ in range(u2()):
                take(2)
                take(u4())
    source_names = []
    for _ in range(u2()):
        name, length = strings.get(u2()), u4()
        if name == b"SourceFile":
            require(length == 2, "Invalid SourceFile attribute.")
            source_names.append(strings[u2()].decode("ascii"))
        else:
            take(length)
    require(len(source_names) == 1, "Compiler output lacks unambiguous source provenance: " + str(path))
    source_name = source_names[0]
    require(Path(source_name).name == source_name and source_name.endswith(".java"), "Unsafe SourceFile name.")
    require(not stream.read(1), "Trailing Java class data: " + str(path))
    return source_name


def stage_fixture(assets: Path) -> dict:
    original = ROOT / FIXTURE_SOURCE
    data = original.read_bytes()
    require(digest(data) == FIXTURE_SHA256, "Falcon source fixture checksum mismatch.")
    require(data[:4] == b"RIFF" and data[8:12] == b"WAVE"
            and struct.unpack_from("<I", data, 4)[0] + 8 == len(data), "Invalid Falcon WAVE container.")
    offset, fmt, samples = 12, None, None
    while offset + 8 <= len(data):
        tag, size = struct.unpack_from("<4sI", data, offset)
        offset += 8
        require(offset + size <= len(data), "Truncated Falcon WAVE chunk.")
        if tag == b"fmt ":
            require(fmt is None and size == 40, "Falcon must use its original WAVE_EXTENSIBLE format chunk.")
            fmt = data[offset:offset + size]
        elif tag == b"data":
            require(samples is None, "Duplicate Falcon audio chunk.")
            samples = data[offset:offset + size]
        offset += size + (size & 1)
    require(offset == len(data), "Invalid Falcon WAVE chunk padding.")
    expected_format = struct.pack(
        "<HHIIHHHHI16s", 65534, 2, 44100, 352800, 8, 32, 22, 32, 3,
        bytes.fromhex("0300000000001000800000aa00389b71"),
    )
    require(fmt == expected_format, "Fixture must retain the original WAVE_EXTENSIBLE Float32 stereo/44.1 kHz format, valid bits, channel mask and subformat GUID.")
    require(samples is not None and len(samples) == 300032 * 2 * 4, "Unexpected Falcon sample count.")
    pcm = bytearray()
    for (sample,) in struct.iter_unpack("<f", samples):
        pcm.extend(struct.pack("<h", max(-32768, min(32767, round(sample * 32768)))))
    target = assets / "probe/falcon-mix.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as output:
        output.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        output.writeframes(pcm)
    require(file_digest(target) == PCM16_SHA256, "Converted Falcon PCM16 checksum mismatch.")
    provenance_path = ROOT / "qa/release-1.6.0/musdb-fixture-provenance.json"
    provenance_bytes = provenance_path.read_bytes()
    provenance = json.loads(provenance_bytes)
    track = next(item for item in provenance["tracks"] if item["id"] == "falcon")
    require(track["pcmSHA256"]["falcon-mix.wav"] == FIXTURE_SHA256
            and track["license"] == "CC BY-NC-SA 3.0", "Fixture license/provenance mismatch.")
    receipt = {
        "assetPath": "probe/falcon-mix.wav", "sourcePath": FIXTURE_SOURCE,
        "sourceSha256": FIXTURE_SHA256, "pcm16Sha256": PCM16_SHA256,
        "sourceProvenancePath": provenance_path.relative_to(ROOT).as_posix(),
        "sourceProvenanceSha256": digest(provenance_bytes),
        "title": track["title"], "license": track["license"],
        "licenseUrl": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
        "datasetSource": track["source"], "archive": provenance["archive"],
        "archiveMember": track["archiveMember"], "sampleRate": 44100,
        "channels": 2, "samplesPerChannel": 300032,
        "conversion": "Float32 to PCM16: multiply by 32768 in Float64, round to nearest ties-to-even, clip [-32768,32767], interleaved little-endian stereo WAVE.",
        "scope": "Noncommercial diagnostic companion only. The 6.8-second excerpt is zero-padded by the unchanged production reader to the complete 13-second model context; it does not establish full-song quality or speed.",
    }
    write_json(assets / "probe/fixture-provenance.json", receipt)
    return receipt


def stage_runtime(toolchain: Path, destination: Path) -> tuple[dict, dict]:
    manifest_path = ROOT / "android/native-runtime.json"
    frozen = destination / "native-runtime.json"
    manifest_info = snapshot(manifest_path, frozen)
    manifest = json.loads(frozen.read_text(encoding="utf-8"))
    require(manifest["version"] == RUNTIME_VERSION, "Only pinned ORT 1.25.1 is supported.")
    expected = {"classes.jar"} | {
        "jni/" + abi + "/" + name for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
        for name in ("libonnxruntime.so", "libonnxruntime4j_jni.so")
    }
    require(set(manifest["files"]) == expected, "Unexpected pinned runtime file inventory.")
    for relative, pin in manifest["files"].items():
        actual = snapshot(toolchain / "onnx" / relative, destination / relative)
        require(actual == pin, "Pinned ORT file checksum mismatch: " + relative)
    return manifest, manifest_info


def validate_apk(path: Path, assets: Path, runtime: dict) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate APK entries.")
        require(archive.testzip() is None, "APK ZIP integrity check failed.")
        require("AndroidManifest.xml" in names and "classes.dex" in names, "APK is incomplete.")
        expected_assets = {"assets/" + p.relative_to(assets).as_posix(): p for p in assets.rglob("*") if p.is_file()}
        require({name for name in names if name.startswith("assets/") and not name.endswith("/")} == set(expected_assets), "Unexpected APK asset inventory; model bundling is forbidden.")
        for name, source in expected_assets.items():
            require(digest(archive.read(name)) == file_digest(source), "APK asset differs from its source: " + name)
        expected_libs = {"lib/" + name[len("jni/"):]: pin for name, pin in runtime["files"].items() if name.startswith("jni/")}
        require({name for name in names if name.startswith("lib/") and not name.endswith("/")} == set(expected_libs), "Unexpected APK native library inventory.")
        for name, pin in expected_libs.items():
            content = archive.read(name)
            require(len(content) == pin["bytes"] and digest(content) == pin["sha256"], "APK runtime library checksum mismatch: " + name)


def build(toolchain: Path) -> Path:
    check_release_signer()
    java = toolchain / "jdk17/bin"
    sdk = toolchain / "android-sdk"
    build_tools = sdk / "build-tools/35.0.0"
    android = sdk / "platforms/android-35/android.jar"
    for path in (java / "javac", java / "jar", java / "keytool", build_tools / "aapt2",
                 build_tools / "d8", build_tools / "zipalign", build_tools / "apksigner"):
        require(path.is_file() and os.access(path, os.X_OK), "Missing installed tool: " + str(path))
    require(android.is_file(), "Missing Android SDK35 platform.")
    # Separate from release build/dist paths. Every attempt uses an empty directory.
    base = ROOT / "build/inference-device-probe"
    base.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    print("Isolated probe build: " + str(output), flush=True)
    env = dict(os.environ, JAVA_HOME=str(java.parent), PATH=str(java) + os.pathsep + os.environ.get("PATH", ""))

    def run(*command: object) -> str:
        return subprocess.check_output([str(item) for item in command], env=env, text=True, stderr=subprocess.STDOUT)

    manifest = output / "AndroidManifest.xml"
    manifest_info = snapshot(PROBE / "AndroidManifest.xml", manifest)
    check_manifest(manifest)
    require(not (PROBE / "res").exists(), "This programmatic companion does not compile Android resource sources.")
    inventory = stage_sources(output / "java-src")
    runtime, runtime_info = stage_runtime(toolchain, output / "runtime")
    assets, classes, dex = output / "assets", output / "classes", output / "dex"
    for directory in (assets, classes, dex):
        directory.mkdir()
    fixture = stage_fixture(assets)
    source_entries = [output / "java-src" / JAVA_PACKAGE / name for name in PRODUCTION_ENTRIES + COMPANION_ENTRIES]
    # All dependencies resolve from frozen source. No production class directory
    # is on this classpath, and annotation processors cannot generate hidden code.
    run(java / "javac", "--release", "8", "-encoding", "UTF-8", "-g:source,lines",
        "-proc:none", "-implicit:class", "-Xprefer:source", "-classpath",
        str(android) + os.pathsep + str(output / "runtime/classes.jar"),
        "-sourcepath", output / "java-src", "-d", classes, *source_entries)
    compiled_sources = set()
    class_hashes = {}
    for path in sorted(classes.rglob("*.class")):
        relative = path.relative_to(classes)
        source = relative.parent / class_source_file(path)
        require(source in inventory, "Compiled class has no frozen source: " + str(relative))
        compiled_sources.add(source)
        class_hashes[relative.as_posix()] = file_digest(path)
    require(compiled_sources, "No companion classes compiled.")
    source_hashes = {inventory[path]["sourcePath"]: inventory[path]["sha256"] for path in sorted(compiled_sources)}
    for relative in compiled_sources:
        require(file_digest(output / "java-src" / relative) == inventory[relative]["sha256"], "Compiler source snapshot changed.")
    compiled_jar = output / "classes.jar"
    run(java / "jar", "cf", compiled_jar, "-C", classes, ".")
    model_manifest = ROOT / "web/analysis/models/deux/manifest.json"
    require(model_manifest.stat().st_size <= 262144, "Unexpected model manifest size.")
    model_info = snapshot(model_manifest, output / "model-manifest.json")
    builder_info = snapshot(Path(__file__).resolve(), output / "build_probe.py")
    receipt = {
        "schema": "lightforge-inference-device-probe-source-v1", "packageName": PACKAGE,
        "runtimeVersion": RUNTIME_VERSION,
        "expectedInstalledPackage": {"packageName": "com.cyberbasslord.lightforge", "versionCode": 20401, "signerSha256": RELEASE_SIGNER},
        "modelManifestSha256": model_info["sha256"], "sourceHashes": source_hashes,
        "fixture": fixture, "runtime": {"manifest": runtime_info, "files": runtime["files"], "source": runtime["source"], "license": runtime["license"]},
        "build": {"builder": builder_info, "manifest": manifest_info, "compileSdk": 35, "targetSdk": 35, "minSdk": 26,
                  "javacSha256": file_digest(java / "javac"), "androidJarSha256": file_digest(android),
                  "compiledJarSha256": file_digest(compiled_jar), "compiledClassHashes": class_hashes,
                  "sourceSelection": "Explicit NativeDeux/transform/profile/policies/AppDiagnostics and companion roots; javac resolved dependencies solely from the frozen source tree. sourceHashes identifies every emitted class's SourceFile."},
        "modelGraphsBundled": False, "releaseArtifact": False,
    }
    # Native runtime licenses are bundled without merging an AAR manifest.
    notices = {}
    for name in ("onnxruntime-native-LICENSE.txt", "onnxruntime-native-ThirdPartyNotices.txt"):
        notices[name] = snapshot(ROOT / "web/licenses" / name, assets / "probe" / name)
    receipt["runtime"]["notices"] = notices
    write_json(assets / "probe/source-receipt.json", receipt)
    run(build_tools / "d8", "--release", "--min-api", "26", "--lib", android,
        "--output", dex, compiled_jar, output / "runtime/classes.jar")
    unsigned = output / "unsigned.apk"
    run(build_tools / "aapt2", "link", "-o", unsigned, "-I", android, "--manifest", manifest,
        "--min-sdk-version", "26", "--target-sdk-version", "35", "--version-code", "1",
        "--version-name", "probe", "--replace-version", "-A", assets)
    with zipfile.ZipFile(unsigned, "a") as archive:
        for path in sorted(dex.glob("*.dex")):
            archive.write(path, path.name, compress_type=zipfile.ZIP_STORED)
        for relative in sorted(runtime["files"]):
            if relative.startswith("jni/"):
                archive.write(output / "runtime" / relative, "lib/" + relative[len("jni/"):], compress_type=zipfile.ZIP_STORED)
    validate_apk(unsigned, assets, runtime)
    aligned, target = output / "aligned.apk", output / "LightForge-inference-probe.apk"
    run(build_tools / "zipalign", "-P", "16", "-f", "4", unsigned, aligned)
    # No external keystore argument/environment is accepted. The key is always
    # newly generated and deleted, even if signing or validation fails.
    with tempfile.TemporaryDirectory(prefix="probe-signing-") as signing:
        signing = Path(signing)
        password, keystore = signing / "password.txt", signing / "probe.jks"
        password.write_text(secrets.token_urlsafe(36) + "\n", encoding="ascii")
        password.chmod(0o600)
        run(java / "keytool", "-genkeypair", "-keystore", keystore, "-storetype", "JKS",
            "-alias", "probe", "-keyalg", "RSA", "-keysize", "3072", "-validity", "30",
            "-storepass:file", password, "-keypass:file", password,
            "-dname", "CN=LightForge Isolated Inference Probe, OU=Temporary QA", "-noprompt")
        certificate = signing / "certificate.der"
        run(java / "keytool", "-exportcert", "-keystore", keystore,
            "-storepass:file", password, "-alias", "probe", "-file", certificate)
        certificate_hash = file_digest(certificate)
        require(certificate_hash != RELEASE_SIGNER, "Refusing to sign a probe with the release identity.")
        run(build_tools / "apksigner", "sign", "--ks", keystore, "--ks-key-alias", "probe",
            "--ks-pass", "file:" + str(password), "--v4-signing-enabled", "false", "--out", target, aligned)
    signature = run(build_tools / "apksigner", "verify", "--verbose", "--print-certs", target)
    signers = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)", signature)
    require(signers == [certificate_hash] and RELEASE_SIGNER not in signers, "Signed probe certificate verification failed.")
    run(build_tools / "zipalign", "-c", "-P", "16", "4", target)
    badging = run(build_tools / "aapt2", "dump", "badging", target)
    require("package: name='" + PACKAGE + "'" in badging, "Signed APK package mismatch.")
    require(not re.search(r"(?m)^uses-permission[^:]*:", badging), "Signed APK unexpectedly requests Android permissions.")
    validate_apk(target, assets, runtime)
    write_json(target.with_suffix(".apk.json"), {
        "apk": target.name, "sha256": file_digest(target), "bytes": target.stat().st_size,
        "packageName": PACKAGE, "signerSha256": certificate_hash, "releaseArtifact": False,
        "updateCompatibleWithLightForge": False, "runtimeVersion": RUNTIME_VERSION,
        "sourceReceiptSha256": file_digest(assets / "probe/source-receipt.json"),
        "signatureVerified": True, "alignmentVerified": True, "zipVerified": True,
        "executionPerformed": False,
    })
    target.with_suffix(".apk.sha256").write_text(file_digest(target) + "  " + target.name + "\n", encoding="ascii")
    print("Built isolated diagnostic companion; no installation or inference performed: " + str(target))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Explicitly authorize compilation and temporary signing of the isolated companion")
    parser.add_argument("--toolchain", type=Path, default=Path(os.environ.get("LIGHTFORGE_TOOLCHAIN_DIR", ROOT.parent / "toolchain")))
    args = parser.parse_args()
    if not args.build:
        parser.error("Nothing built. Compilation requires explicit --build; review the companion sources and README first.")
    try:
        build(args.toolchain.resolve())
    except subprocess.CalledProcessError as error:
        captured = error.output or "(No tool diagnostics captured.)"
        if isinstance(captured, bytes):
            captured = captured.decode("utf-8", errors="replace")
        # Preserve both the first diagnostic and the final failure summary while
        # preventing an enormous compiler/tool report from flooding the console.
        if len(captured) > 12000:
            captured = captured[:6000] + "\n[intermediate tool output omitted]\n" + captured[-6000:]
        tool = Path(str(error.cmd[0])).name if isinstance(error.cmd, (list, tuple)) else "build tool"
        raise SystemExit("Probe build failed: " + tool + " exited with status " + str(error.returncode) + "\n" + captured.rstrip()) from error
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        raise SystemExit("Probe build failed: " + str(error)) from error


if __name__ == "__main__":
    main()
