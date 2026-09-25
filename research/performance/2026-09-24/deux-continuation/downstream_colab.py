# Colab continuation after Deux has stopped: bounded downstream sensitivity only.
# No app changes, no relaxed upstream numerical gate, no timing/quality approval.
import datetime as DS_datetime
import hashlib as DS_hashlib
import json as DS_json
import os as DS_os
import platform as DS_platform
import shutil as DS_shutil
import signal as DS_signal
import subprocess as DS_subprocess
import tarfile as DS_tarfile
import time as DS_time
import urllib.request as DS_request
import uuid as DS_uuid
import zipfile as DS_zipfile
from pathlib import Path as DS_Path

DS_COMMIT = "8590ac4a67de4340857a96ffe38bae53d7d902b8"
DS_TREE = "c841bf18f91d3d04dd6daf7e886e2aa473ab8c70"
DS_NODE_VERSION = "22.19.0"
DS_NODE_NAME = "node-v22.19.0-linux-x64.tar.xz"
DS_NODE_URL = "https://nodejs.org/dist/v22.19.0/" + DS_NODE_NAME
# Pinned before execution from the official release page's SHA256 inventory:
# https://nodejs.org/en/blog/release/v22.19.0 (2025-08-28)
DS_NODE_SHA = "c0649af18e6a24f6fe5535a3e86b341dd49a8e71117c8b68bde973ef834f16f2"
DS_APK_SHA = "af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f"
DS_AUDIO_SHA = "33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650"
DS_SOURCE_HASHES = {
  "tools/compare_deux_downstream.cjs": "d1a4bf073d946d3f81d7d79e32842ec138c5c4510b809ddf6405ebc4307cb2ad",
  "qa/release-2.3.2/mdx-downstream-compare.cjs": "c17e44bcc89ca3f2e257abb1c065369a1747d8bef2541d0cd00f36bc5c284605",
  "web/analysis/ASSET_MANIFEST.json": "c0dc1d56b53cf7f316697d45f0a2cb5a63c4bf7068ba89829619cadfe46ff790",
  "web/analysis/separator-deux.js": "6a37acd3fd3923f32249d9640462cc06768c41901ee000837e17f21205d22867",
  "web/analysis/dsp.js": "f95357f71693a5df05e47c5baed5a15cca88bf5371d4b20dc51b3dbb6624fc06",
  "web/analysis/stem-cache.js": "d464a6759188c19e83e9ea7b22fdcbfcdaaca99c06fea930f2fbe9306dcdd5fd",
  "web/analysis/wav-reader.js": "6cd0a40392617cc020f2ec4f87952f165e070c8c17bc4aa3b36b212823d897d4",
  "web/analysis/vocal.js": "3f4be80b6b3747a733fcddce1257e332fe20bde70f29fa8c6be0ef076a9bf72d",
  "web/analysis/vocal-detail.js": "cd760d7a766d9a4ab0ac3a252a10f17a16a797b38e50b2d6712bc6adcd42713f",
  "web/analysis/game.js": "a4225b832bb8cee4d382b01b8753266b426d2a75be49515dc58bbb12e5a03b75",
  "web/analysis/worker.js": "0660d76f5e030e808cfafa2f987f6da4197f45e2415c3586f9a2313c5faab655",
  "web/analysis/models/features.json": "8a9fb3bc88c3e2f35934dd0024f22458aa8d357e3e3946a6e2c6230d3886e278",
  "web/analysis/models/vocal-model.json": "52093f26d0bfe3f04bbb1563b287fafe5e61aa57a61391ea643b04d97838ca7e",
  "web/analysis/models/vocal-frontend.json": "72bdffced29bfdd6d1da77a4da2a2a4af1b2f839c71131d19dc9423db3d4732f",
  "web/analysis/models/game/manifest.json": "51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97",
  "web/analysis/models/game/config.json": "4d62b6d058a820e981184ea6f04605d37659c4331ee01979eb14a14be08af890",
  "web/analysis/models/deux/manifest.json": "6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9",
  "tools/benchmark_deux_accelerator.py": "0c19caa398c6fb1e1be121d359219074e71879979105d4172fbcf360906c9f0a",
  "tools/profile_deux_operators.py": "9a4e189d899a2f5c3c0e92df64ef4e1f3316ef422d53216d92b983e221c235d6",
  "tools/benchmark_deux_execution.py": "2fdeceb1fd4fd275b31338aeff6be6a5e53afb741c15de5dc020f65cbed72f3f",
  "tests/NativeDeuxExecutionBenchmark.java": "70eab8091070904493493bd94e7a6467a031628e0feb432055942cdd1bd1b0bb",
  "android/src/com/cyberbasslord/lightforge/NativeDeux.java": "084fec27d1fad0b10db01a960c614d333bb8c049e712c3fc4524d66e6dc3dd37",
  "android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java": "991b06501cfb88b904d0b714a525c389f169f00c231248b0e961b70f257e90b5",
  "android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java": "aa1d6bd370d88a774792cb76b4a18604d3ab2bffba58ab382e9045cad071acc1",
  "android/native-runtime.json": "e3ea568b3a8485235f23a59cd787466cdcbbfcaa54ac56df3ce040d29fcb2a94"
}
DS_FALSE_FLAGS = {"qualityApproved": False, "target75Proven": False,
                  "releaseAuthorized": False, "benchmarkTimingAdmitted": False}


def DS_digest(DS_path):
    with DS_Path(DS_path).open("rb") as DS_stream:
        return DS_hashlib.file_digest(DS_stream, "sha256").hexdigest()


def DS_write_json(DS_path, DS_value):
    with DS_Path(DS_path).open("x") as DS_stream:
        DS_stream.write(DS_json.dumps(DS_value, indent=2, allow_nan=False) + "\n")


def DS_canonical(DS_name):
    DS_path = DS_Path(DS_name)
    assert isinstance(DS_name, str) and DS_name and not DS_path.is_absolute()
    assert str(DS_path) == DS_name and ".." not in DS_path.parts
    return DS_path


def DS_file_pin(DS_path):
    assert DS_path.is_file() and not DS_path.is_symlink()
    return {"bytes": DS_path.stat().st_size, "sha256": DS_digest(DS_path)}


def DS_git(*DS_args):
    return DS_subprocess.run(["git", "-C", str(DS_ORIGINAL_REPO), *DS_args],
        check=True, capture_output=True, timeout=60).stdout


def DS_verify_capture():
    DS_receipt_path = DS_EVIDENCE / "receipt.json"
    DS_receipt = DS_json.loads(DS_receipt_path.read_text())
    assert DS_receipt["schema"] == "lightforge.deux-accelerator-experiment.v1"
    assert DS_receipt["status"] == "NUMERICAL_EQUIVALENCE_UNPROVEN"
    assert DS_receipt["inputsRecheckedAfterQualification"] is True
    assert DS_receipt["startSample"] == -66150 and DS_receipt["samplesPerStem"] == 573300
    assert DS_receipt["audioFrames"] == 2822400 and DS_receipt["audioSha256"] == DS_AUDIO_SHA
    assert DS_digest(DS_AUDIO) == DS_AUDIO_SHA
    for DS_key in ("qualityApproved", "target75Proven", "releaseAuthorized", "measured"):
        assert DS_receipt.get(DS_key) is False, "Unexpected upstream approval/timing: " + DS_key
    assert DS_receipt["sourceHashes"] == DX_SOURCE_HASHES
    assert all(DS_SOURCE_HASHES.get(DS_name) == DS_sha for DS_name, DS_sha in DX_SOURCE_HASHES.items())
    DS_outputs = {}
    for DS_variant in ("cpu_all", "cuda_basic"):
        DS_rows = [DS_row for DS_row in DS_receipt["runs"] if DS_row["variant"] == DS_variant
                   and DS_row["phase"] == "qualification" and DS_row["round"] == 0]
        assert len(DS_rows) == 1 and DS_rows[0]["outputBytes"] == 4586400
        DS_output = DS_EVIDENCE / DS_variant / "qualification-0.f32"
        DS_pin = DS_file_pin(DS_output)
        assert DS_pin == {"bytes": 4586400, "sha256": DS_rows[0]["outputSha256"]}
        DS_observers = [DS_item for DS_item in DS_receipt["comparisons"]
                        if DS_item["reference"] == DS_variant and DS_item["candidate"] == DS_variant + "_profiled"]
        assert len(DS_observers) == 1 and DS_observers[0]["byteIdentical"] is True
        assert DS_observers[0]["referenceSha256"] == DS_pin["sha256"] == DS_observers[0]["candidateSha256"]
        DS_profiled = DS_EVIDENCE / (DS_variant + "_profiled") / "diagnostic-0.f32"
        assert DS_file_pin(DS_profiled) == DS_pin, "Profiled bytes contradict observer receipt."
        DS_outputs[DS_variant] = DS_pin
    return {"receipt": DS_file_pin(DS_receipt_path), "outputs": DS_outputs,
            "audio": DS_file_pin(DS_AUDIO), "upstreamSetup": DS_file_pin(DS_Path(DX_RUN) / "setup-receipt.json"),
            "upstreamProcess": DS_file_pin(DS_Path(DX_RUN) / "qualification-process.json")}


def DS_main():
    assert DS_platform.system() == "Linux" and DS_platform.machine() == "x86_64"
    assert DS_git("rev-parse", "HEAD").decode().strip() == DS_COMMIT
    assert DS_git("rev-parse", "HEAD^{tree}").decode().strip() == DS_TREE
    assert not DS_git("status", "--porcelain", "--untracked-files=no").strip(), "Tracked source changed."
    DS_process_record = DS_json.loads((DS_Path(DX_RUN) / "qualification-process.json").read_text())
    assert DS_process_record["status"] == "PROCESS_EXITED" and DS_process_record["returnCode"] == 1
    assert DS_process_record["receiptStatus"] == "NUMERICAL_EQUIVALENCE_UNPROVEN"
    assert DS_shutil.disk_usage(DS_Path(WORK)).free >= 2 * 1024**3, "Need 2 GiB free for isolated source/assets/evidence."
    DS_before = DS_verify_capture()
    DS_apk_pin = DS_file_pin(DS_APK)
    assert DS_apk_pin == {"bytes": 1205116958, "sha256": DS_APK_SHA}
    DS_setup = DS_json.loads((DS_Path(DX_RUN) / "setup-receipt.json").read_text())
    assert DS_setup["sourceCommit"] == DS_COMMIT and DS_setup["sourceTree"] == DS_TREE
    assert DS_setup["sourceHashes"] == DX_SOURCE_HASHES
    DS_write_json(DS_RUN / "parent-binding.json", DS_before)
    # Copy small input evidence. Original DX evidence remains unchanged.
    for DS_relative in ["receipt.json", "cpu_all/qualification-0.f32", "cuda_basic/qualification-0.f32",
                        "cpu_all_profiled/diagnostic-0.f32", "cuda_basic_profiled/diagnostic-0.f32"]:
        DS_destination = DS_RUN / "captured-inputs" / DS_relative
        DS_destination.parent.mkdir(parents=True, exist_ok=True)
        DS_shutil.copyfile(DS_EVIDENCE / DS_relative, DS_destination)
        assert DS_file_pin(DS_destination) == DS_file_pin(DS_EVIDENCE / DS_relative)
    DS_shutil.copyfile(DS_Path(DX_RUN) / "setup-receipt.json", DS_RUN / "parent-setup-receipt.json")
    DS_shutil.copyfile(DS_Path(DX_RUN) / "qualification-process.json", DS_RUN / "parent-qualification-process.json")
    # A separate immutable source snapshot resolves sparse-checkout omissions.
    # All source bytes come from exact Git objects; HG_REPO and its manifests are not changed.
    DS_SNAPSHOT.mkdir(exist_ok=False)
    for DS_relative, DS_sha in DS_SOURCE_HASHES.items():
        DS_canonical(DS_relative)
        DS_bytes = DS_git("show", DS_COMMIT + ":" + DS_relative)
        assert DS_hashlib.sha256(DS_bytes).hexdigest() == DS_sha
        for DS_base in (DS_SNAPSHOT, DS_RUN / "bound-source"):
            DS_destination = DS_base / DS_relative
            DS_destination.parent.mkdir(parents=True, exist_ok=True)
            with DS_destination.open("xb") as DS_stream:
                DS_stream.write(DS_bytes)
    DS_inventory = DS_json.loads((DS_SNAPSHOT / "web/analysis/ASSET_MANIFEST.json").read_text())
    DS_game = DS_json.loads((DS_SNAPSHOT / "web/analysis/models/game/manifest.json").read_text())
    DS_vocal = DS_json.loads((DS_SNAPSHOT / "web/analysis/models/vocal-model.json").read_text())
    assert DS_game["id"] == "game-large-1.0.3-lightforge-1" and DS_game["steps"] == 8
    DS_asset_names = ["models/game/" + DS_name for DS_name in DS_game["files"]] + [
        "models/" + DS_vocal["file"], "vendor/ort.wasm.min.js",
        "vendor/ort-wasm-simd-threaded.wasm", "vendor/ort-wasm-simd-threaded.mjs"]
    DS_assets = {}
    with DS_zipfile.ZipFile(DS_APK) as DS_archive:
        DS_members = DS_archive.namelist()
        assert len(DS_members) == len(set(DS_members)), "Duplicate APK member."
        for DS_name in DS_asset_names:
            DS_canonical(DS_name)
            DS_pin = DS_inventory[DS_name]
            if DS_name.startswith("models/game/"):
                assert DS_pin == DS_game["files"][DS_Path(DS_name).name]
            if DS_name == "models/" + DS_vocal["file"]:
                assert DS_pin == {"bytes": DS_vocal["bytes"], "sha256": DS_vocal["sha256"]}
            DS_destination = DS_SNAPSHOT / "web/analysis" / DS_name
            DS_member = "assets/analysis/" + DS_name
            assert DS_archive.getinfo(DS_member).file_size == DS_pin["bytes"]
            if not DS_destination.exists():
                DS_destination.parent.mkdir(parents=True, exist_ok=True)
                with DS_archive.open(DS_member) as DS_source, DS_destination.open("xb") as DS_target:
                    DS_shutil.copyfileobj(DS_source, DS_target, length=1024 * 1024)
            assert DS_file_pin(DS_destination) == DS_pin
            DS_assets["web/analysis/" + DS_name] = DS_pin
    # Also bind all copied application modules/configurations to the frozen inventory.
    for DS_relative, DS_sha in DS_SOURCE_HASHES.items():
        if DS_relative.startswith("web/analysis/") and not DS_relative.endswith("ASSET_MANIFEST.json"):
            assert DS_file_pin(DS_SNAPSHOT / DS_relative) == DS_inventory[DS_relative[len("web/analysis/"):]]
    print("Bound original GAME/Frame-MN10 graphs and WASM assets to frozen source; no npm install.", flush=True)
    DS_node_dir = DS_Path(TOOLCHAIN) / ("deux-downstream-node-" + DS_ID)
    DS_node_dir.mkdir(exist_ok=False)
    DS_node_archive = DS_node_dir / DS_NODE_NAME
    with DS_request.urlopen(DS_NODE_URL, timeout=60) as DS_response, DS_node_archive.open("xb") as DS_target:
        assert DS_response.geturl() == DS_NODE_URL, "Unexpected Node download redirect."
        DS_shutil.copyfileobj(DS_response, DS_target, length=1024 * 1024)
    assert DS_digest(DS_node_archive) == DS_NODE_SHA, "Official Node archive checksum differs."
    DS_node = DS_node_dir / "node"
    with DS_tarfile.open(DS_node_archive, "r:xz") as DS_tar:
        DS_member = DS_tar.getmember("node-v22.19.0-linux-x64/bin/node")
        assert DS_member.isfile() and not DS_member.issym() and not DS_member.islnk()
        with DS_tar.extractfile(DS_member) as DS_source, DS_node.open("xb") as DS_target:
            DS_shutil.copyfileobj(DS_source, DS_target, length=1024 * 1024)
    DS_node.chmod(0o700)
    DS_env = dict(DS_os.environ)
    assert not DS_env.get("NODE_OPTIONS") and not DS_env.get("NODE_PATH"), "Unexpected Node instrumentation."
    DS_env["PATH"] = str(DS_node_dir) + DS_os.pathsep + DS_env.get("PATH", "")
    DS_version = DS_subprocess.run([str(DS_node), "--version"], check=True,
        capture_output=True, text=True, env=DS_env, timeout=30).stdout.strip()
    assert DS_version == "v" + DS_NODE_VERSION
    DS_before["sourceSnapshot"] = DS_SOURCE_HASHES
    DS_before["assets"] = DS_assets
    DS_before["node"] = DS_file_pin(DS_node)
    DS_before["nodeArchive"] = {"sha256": DS_NODE_SHA, "url": DS_NODE_URL,
        "checksumSource": "https://nodejs.org/en/blog/release/v22.19.0", "version": DS_version}
    DS_write_json(DS_RUN / "setup-receipt.json", {"schema": "lightforge.deux-downstream-setup.v1",
        "sourceCommit": DS_COMMIT, "sourceTree": DS_TREE, "bindings": DS_before,
        "immutableSnapshotPath": str(DS_SNAPSHOT), "originalSourceUntouched": True,
        "thresholdSource": "qa/release-2.3.2/mdx-downstream-compare.cjs", **DS_FALSE_FLAGS})
    DS_command = [str(DS_node), str(DS_SNAPSHOT / "tools/compare_deux_downstream.cjs"),
        "--evidence", str(DS_EVIDENCE), "--audio", str(DS_AUDIO), "--output", str(DS_RUN / "comparison")]
    DS_write_json(DS_RUN / "command.json", DS_command)
    print("Running unchanged five-second consumer sensitivity comparator with Node", DS_version, flush=True)
    with (DS_RUN / "driver.log").open("x") as DS_log:
        DS_process = DS_subprocess.Popen(DS_command, cwd=DS_SNAPSHOT, env=DS_env,
            stdin=DS_subprocess.DEVNULL, stdout=DS_log, stderr=DS_subprocess.STDOUT, start_new_session=True)
        DS_started, DS_last_print = DS_time.monotonic(), DS_time.monotonic()
        try:
            while DS_process.poll() is None:
                try:
                    DS_process.wait(timeout=20)
                except DS_subprocess.TimeoutExpired:
                    assert DS_time.monotonic() - DS_started < 2700, "Downstream comparison exceeded 45-minute bound."
                    if DS_time.monotonic() - DS_last_print >= 60:
                        DS_completed = [DS_variant for DS_variant in ("cpu_all", "cuda_basic")
                            if (DS_RUN / "comparison" / DS_variant / "downstream.json").is_file()]
                        print("Downstream sensitivity running; completed arms:", DS_completed, flush=True)
                        DS_last_print = DS_time.monotonic()
        finally:
            # Retire this private process group even if parent Node exited before a worker.
            try:
                DS_os.killpg(DS_process.pid, DS_signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                DS_process.wait(timeout=10)
            except DS_subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    DS_os.killpg(DS_process.pid, DS_signal.SIGKILL)
                except ProcessLookupError:
                    pass
                DS_process.wait(timeout=10)
    DS_result = DS_json.loads((DS_RUN / "comparison/receipt.json").read_text())
    assert DS_result["schema"] == "lightforge.deux-downstream-sensitivity.v1"
    assert all(DS_result.get(DS_key) is False for DS_key in DS_FALSE_FLAGS)
    DS_after = DS_verify_capture()
    assert all(DS_after[DS_key] == DS_before[DS_key] for DS_key in DS_after)
    assert DS_file_pin(DS_RUN / "parent-setup-receipt.json") == DS_before["upstreamSetup"]
    assert DS_file_pin(DS_RUN / "parent-qualification-process.json") == DS_before["upstreamProcess"]
    assert DS_file_pin(DS_RUN / "captured-inputs/receipt.json") == DS_before["receipt"]
    for DS_variant, DS_pin in DS_before["outputs"].items():
        assert DS_file_pin(DS_RUN / "captured-inputs" / DS_variant / "qualification-0.f32") == DS_pin
        assert DS_file_pin(DS_RUN / "captured-inputs" / (DS_variant + "_profiled") / "diagnostic-0.f32") == DS_pin
    assert all(DS_digest(DS_SNAPSHOT / DS_name) == DS_sha for DS_name, DS_sha in DS_SOURCE_HASHES.items())
    assert all(DS_file_pin(DS_SNAPSHOT / DS_name) == DS_pin for DS_name, DS_pin in DS_assets.items())
    assert DS_file_pin(DS_node) == DS_before["node"]
    assert DS_git("rev-parse", "HEAD").decode().strip() == DS_COMMIT
    assert DS_git("rev-parse", "HEAD^{tree}").decode().strip() == DS_TREE
    assert not DS_git("status", "--porcelain", "--untracked-files=no").strip()
    DS_SUMMARY.update(comparatorStatus=DS_result["status"], returnCode=DS_process.returncode,
        comparatorReceipt=DS_file_pin(DS_RUN / "comparison/receipt.json"),
        inputsRecheckedAfterComparison=True, driverLog=DS_file_pin(DS_RUN / "driver.log"),
        sensitivityPassed=DS_result.get("sensitivityPassed") is True)
    if DS_result["status"] in ("EXCERPT_SENSITIVITY_PASS", "EXCERPT_SENSITIVITY_FAILED"):
        assert DS_result["inputsRecheckedAfterComparison"] is True
        assert DS_process.returncode == (0 if DS_result["sensitivityPassed"] else 2)
        DS_SUMMARY["status"] = "DIAGNOSTIC_COMPLETED"
    else:
        DS_SUMMARY["status"] = "DIAGNOSTIC_REJECTED"
    print(DS_json.dumps({DS_key: DS_result.get(DS_key) for DS_key in
        ("status", "sensitivityPassed", "qualityApproved", "target75Proven", "errors")}, indent=2), flush=True)
    print("This excerpt cannot admit upstream benchmark ratios, full-song quality, or the 75% target.", flush=True)


# New evidence and snapshot paths on every execution; never overwrite a prior attempt.
assert all(DS_name in globals() for DS_name in ("DX_RUN", "DX_REPO", "DX_APK", "DX_AUDIO", "DX_SOURCE_HASHES", "WORK", "TOOLCHAIN")), "Complete the Deux continuation first."
DS_ORIGINAL_REPO, DS_APK, DS_AUDIO = DS_Path(DX_REPO), DS_Path(DX_APK), DS_Path(DX_AUDIO)
DS_EVIDENCE = DS_Path(DX_RUN) / "qualification"
DS_ID = DS_datetime.datetime.now(DS_datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-deux-downstream-" + DS_uuid.uuid4().hex[:8]
DS_RUN = DS_Path(WORK) / "evidence" / DS_ID
DS_SNAPSHOT = DS_Path(WORK) / ("source-" + DS_ID)
DS_RUN.mkdir(parents=True, exist_ok=False)
DS_SUMMARY = {"schema": "lightforge.deux-downstream-driver.v1", "status": "BLOCKED_OR_INTERRUPTED",
    "upstreamEvidencePath": str(DS_EVIDENCE), "createdUtc": DS_datetime.datetime.now(DS_datetime.timezone.utc).isoformat(),
    "sensitivityPassed": False, "inputsRecheckedAfterComparison": False, "errors": [], **DS_FALSE_FLAGS}
print("Fresh downstream evidence:", DS_RUN, flush=True)
try:
    DS_main()
except BaseException as DS_error:
    DS_SUMMARY["errors"].append(type(DS_error).__name__ + ": " + str(DS_error))
    raise
finally:
    DS_SUMMARY["completedUtc"] = DS_datetime.datetime.now(DS_datetime.timezone.utc).isoformat()
    DS_SUMMARY["artifactHashes"] = {str(DS_path.relative_to(DS_RUN)): DS_file_pin(DS_path)
        for DS_path in sorted(DS_RUN.rglob("*")) if DS_path.is_file()}
    DS_write_json(DS_RUN / "driver-receipt.json", DS_SUMMARY)
    # Closed, complete files only. No model weights, APK, Node binary, or credentials.
    DS_archive_path = DS_RUN.with_suffix(".zip")
    with DS_zipfile.ZipFile(DS_archive_path, "x", compression=DS_zipfile.ZIP_DEFLATED, compresslevel=1) as DS_archive:
        for DS_path in sorted(DS_RUN.rglob("*")):
            assert not DS_path.is_symlink(), "Unexpected evidence symlink."
            if DS_path.is_file():
                DS_archive.write(DS_path, arcname=str(DS_path.relative_to(DS_RUN.parent)))
    DS_archive_sha256 = DS_digest(DS_archive_path)
    print("Evidence:", DS_archive_path.name, "bytes:", DS_archive_path.stat().st_size, flush=True)
    print("SHA-256:", DS_archive_sha256, flush=True)
    print("Use the separate downstream export cell to download the immutable evidence archive.", flush=True)
