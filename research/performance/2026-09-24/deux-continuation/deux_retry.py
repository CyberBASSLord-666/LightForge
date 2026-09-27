# Colab continuation: run after the GAME process has stopped.
# Uses the verified GAME setup; leaves its globals, source, assets and evidence intact.
import datetime as DX_datetime
import hashlib as DX_hashlib
import json as DX_json
import os as DX_os
import shutil as DX_shutil
import signal as DX_signal
import subprocess as DX_subprocess
import sys as DX_sys
import time as DX_time
import uuid as DX_uuid
import zipfile as DX_zipfile
from pathlib import Path as DX_Path

DX_COMMIT = "8590ac4a67de4340857a96ffe38bae53d7d902b8"
DX_TREE = "c841bf18f91d3d04dd6daf7e886e2aa473ab8c70"
DX_REPO = DX_Path(HG_REPO)
DX_TOOLCHAIN = DX_Path(TOOLCHAIN)
DX_APK = DX_Path(ASSETS) / "LightForge-2.3.1.apk"
DX_AUDIO = DX_Path(AUDIO)
DX_APK_SHA = "af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f"
DX_AUDIO_SHA = "33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650"
DX_PARENT_SETUP_SHA = "a92e864c73f5da16c9103291bc6057d73fd80dd1c70773c21220cf82f14b3926"
DX_SOURCE_HASHES = {
    "tools/benchmark_deux_accelerator.py": "0c19caa398c6fb1e1be121d359219074e71879979105d4172fbcf360906c9f0a",
    "tools/profile_deux_operators.py": "9a4e189d899a2f5c3c0e92df64ef4e1f3316ef422d53216d92b983e221c235d6",
    "tools/benchmark_deux_execution.py": "2fdeceb1fd4fd275b31338aeff6be6a5e53afb741c15de5dc020f65cbed72f3f",
    "tests/NativeDeuxExecutionBenchmark.java": "70eab8091070904493493bd94e7a6467a031628e0feb432055942cdd1bd1b0bb",
    "android/src/com/cyberbasslord/lightforge/NativeDeux.java": "084fec27d1fad0b10db01a960c614d333bb8c049e712c3fc4524d66e6dc3dd37",
    "android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java": "991b06501cfb88b904d0b714a525c389f169f00c231248b0e961b70f257e90b5",
    "android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java": "aa1d6bd370d88a774792cb76b4a18604d3ab2bffba58ab382e9045cad071acc1",
    "android/native-runtime.json": "e3ea568b3a8485235f23a59cd787466cdcbbfcaa54ac56df3ce040d29fcb2a94",
    "web/analysis/models/deux/manifest.json": "6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9",
}

def DX_digest(DX_path):
    with DX_Path(DX_path).open("rb") as DX_stream:
        return DX_hashlib.file_digest(DX_stream, "sha256").hexdigest()

def DX_write_json(DX_path, DX_value):
    DX_path.write_text(DX_json.dumps(DX_value, indent=2, allow_nan=False) + "\n")

def DX_git(*DX_args):
    return DX_subprocess.run(["git", "-C", str(DX_REPO), *DX_args], check=True,
                             capture_output=True, text=True, timeout=30).stdout.strip()

assert DX_git("rev-parse", "HEAD") == DX_COMMIT
assert DX_git("rev-parse", "HEAD^{tree}") == DX_TREE
assert not DX_git("status", "--porcelain", "--untracked-files=no"), "Tracked source changed."
for DX_relative, DX_expected in DX_SOURCE_HASHES.items():
    assert DX_digest(DX_REPO / DX_relative) == DX_expected, "Bound source differs: " + DX_relative
assert DX_APK.is_file() and not DX_APK.is_symlink() and DX_APK.stat().st_size == 1205116958
assert DX_digest(DX_APK) == DX_APK_SHA and DX_digest(DX_AUDIO) == DX_AUDIO_SHA
assert DX_digest(DX_Path(RUN) / "setup-receipt.json") == DX_PARENT_SETUP_SHA
DX_PARENT_SETUP = DX_json.loads((DX_Path(RUN) / "setup-receipt.json").read_text())
DX_CUDA_ROOT = DX_TOOLCHAIN / "cuda-wheels"
for DX_relative, DX_pin in DX_PARENT_SETUP["extractedNativeLibraries"].items():
    DX_path = DX_CUDA_ROOT / DX_relative
    assert DX_path.is_file() and not DX_path.is_symlink()
    assert DX_path.stat().st_size == DX_pin["bytes"] and DX_digest(DX_path) == DX_pin["sha256"]
DX_ENV = dict(benchmark_env)
assert DX_ENV.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8" and DX_ENV.get("NVIDIA_TF32_OVERRIDE") == "0"
assert not any(DX_ENV.get(DX_key) for DX_key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"))
assert DX_shutil.disk_usage(WORK).free >= 4 * 1024**3, "Need 4 GiB free for original graphs and fresh evidence."

DX_ID = DX_datetime.datetime.now(DX_datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-deux-" + DX_uuid.uuid4().hex[:8]
DX_RUN = DX_Path(WORK) / "evidence" / DX_ID
DX_MODELS = DX_Path(ASSETS) / ("original-" + DX_ID)
DX_RUN.mkdir(parents=True, exist_ok=False)
DX_MODELS.mkdir(parents=True, exist_ok=False)
print("Fresh Deux evidence:", DX_RUN, flush=True)
DX_manifest_path = DX_REPO / "web/analysis/models/deux/manifest.json"
DX_manifest = DX_json.loads(DX_manifest_path.read_text())
assert len(DX_manifest["files"]) == 27
with DX_zipfile.ZipFile(DX_APK) as DX_archive:
    assert DX_hashlib.sha256(DX_archive.read("assets/analysis/models/deux/manifest.json")).hexdigest() == DX_SOURCE_HASHES["web/analysis/models/deux/manifest.json"]
    for DX_name, DX_pin in DX_manifest["files"].items():
        assert DX_Path(DX_name).name == DX_name, "Unexpected model path."
        extract_member(DX_archive, "assets/analysis/models/deux/" + DX_name,
                       DX_MODELS / DX_name, DX_pin["bytes"], DX_pin["sha256"])
DX_shutil.copyfile(DX_manifest_path, DX_MODELS / "manifest.json")
DX_shutil.copyfile(DX_Path(RUN) / "setup-receipt.json", DX_RUN / "parent-game-setup-receipt.json")
for DX_relative in DX_SOURCE_HASHES:
    DX_snapshot = DX_RUN / "bound-source" / DX_relative
    DX_snapshot.parent.mkdir(parents=True, exist_ok=True)
    DX_shutil.copyfile(DX_REPO / DX_relative, DX_snapshot)
DX_write_json(DX_RUN / "setup-receipt.json", dict(
    schema="lightforge.deux-continuation-setup.v1", createdUtc=DX_datetime.datetime.now(DX_datetime.timezone.utc).isoformat(),
    sourceCommit=DX_COMMIT, sourceTree=DX_TREE, sourceHashes=DX_SOURCE_HASHES,
    parentSetupSha256=DX_PARENT_SETUP_SHA, publicApkSha256=DX_APK_SHA, publicAudioSha256=DX_AUDIO_SHA,
    modelManifestSha256=DX_digest(DX_MODELS / "manifest.json"), modelHashes=DX_manifest["files"],
    cudaWheelPins=DX_PARENT_SETUP["cudaWheelPins"], extractedNativeLibraries=DX_PARENT_SETUP["extractedNativeLibraries"],
    environment={DX_key: DX_ENV.get(DX_key) for DX_key in ("LD_LIBRARY_PATH", "CUBLAS_WORKSPACE_CONFIG", "NVIDIA_TF32_OVERRIDE", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")},
    startSample=-66150, samplesPerStem=573300, qualityApproved=False, target75Proven=False, releaseAuthorized=False))
DX_gpu = DX_subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"],
                          capture_output=True, text=True, timeout=30)
(DX_RUN / "gpu-inventory.txt").write_text(DX_gpu.stdout + DX_gpu.stderr)
assert DX_gpu.returncode == 0 and DX_gpu.stdout.strip(), "No GPU available; retain the setup evidence."
print("Verified 27 original graphs; GPU:", DX_gpu.stdout.strip(), flush=True)
DX_BENCHMARK = DX_REPO / "tools/benchmark_deux_accelerator.py"
DX_ARGUMENTS = [DX_sys.executable, str(DX_BENCHMARK), "--toolchain", str(DX_TOOLCHAIN),
                "--models", str(DX_MODELS), "--audio", str(DX_AUDIO), "--start-sample", "-66150"]

def DX_run_stage(DX_name, DX_extra):
    DX_output = DX_RUN / DX_name
    assert not DX_output.exists(), "Refusing existing evidence."
    DX_arguments = DX_ARGUMENTS + ["--output", str(DX_output)] + DX_extra
    DX_record = dict(arguments=DX_arguments, status="RUNNING", returnCode=None)
    with (DX_RUN / (DX_name + ".log")).open("x") as DX_log:
        DX_process = DX_subprocess.Popen(DX_arguments, cwd=DX_REPO, env=DX_ENV,
            stdout=DX_log, stderr=DX_subprocess.STDOUT, start_new_session=True)
        try:
            DX_record.update(pid=DX_process.pid, processGroup=DX_process.pid)
            DX_write_json(DX_RUN / (DX_name + "-process.json"), DX_record)
            DX_previous, DX_last_print = None, DX_time.monotonic()
            while DX_process.poll() is None:
                try:
                    DX_process.wait(timeout=20)
                except DX_subprocess.TimeoutExpired:
                    try:
                        DX_partial = DX_json.loads((DX_output / "receipt.json").read_text())
                        DX_progress = (DX_partial.get("status"), len(DX_partial.get("runs", [])))
                    except (FileNotFoundError, DX_json.JSONDecodeError):
                        DX_progress = ("STARTING", 0)
                    if DX_progress != DX_previous or DX_time.monotonic() - DX_last_print >= 60:
                        print(DX_name, "status:", DX_progress[0], "completed runs:", DX_progress[1], flush=True)
                        DX_previous, DX_last_print = DX_progress, DX_time.monotonic()
        except BaseException:
            # Signal the whole session, including Java. Kill survivors even if Python exits first.
            try:
                try:
                    DX_os.killpg(DX_process.pid, DX_signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    DX_process.wait(timeout=10)
                except DX_subprocess.TimeoutExpired:
                    pass
            finally:
                try:
                    DX_os.killpg(DX_process.pid, DX_signal.SIGKILL)
                except ProcessLookupError:
                    pass
                DX_process.wait(timeout=10)
                DX_record.update(status="INTERRUPTED", returnCode=DX_process.returncode, completed=False,
                                 qualityApproved=False, target75Proven=False, releaseAuthorized=False)
                DX_write_json(DX_RUN / (DX_name + "-process.json"), DX_record)
            raise
    try:
        DX_receipt = DX_json.loads((DX_output / "receipt.json").read_text())
    except (FileNotFoundError, DX_json.JSONDecodeError):
        DX_receipt = dict(status="PROCESS_FAILED_WITHOUT_VALID_RECEIPT")
    DX_record.update(status="PROCESS_EXITED", returnCode=DX_process.returncode, receiptStatus=DX_receipt.get("status"))
    DX_write_json(DX_RUN / (DX_name + "-process.json"), DX_record)
    print(DX_name, "exit:", DX_process.returncode, "status:", DX_receipt.get("status"), flush=True)
    if DX_receipt.get("failure"):
        print(DX_receipt["failure"], flush=True)
    return DX_receipt, DX_process.returncode

DX_readiness, DX_readiness_exit = DX_run_stage("readiness", ["--check-readiness"])
assert DX_readiness_exit == 0 and DX_readiness["status"] == "PREFLIGHT_READY", "Readiness failed; retain evidence."
# Unchanged experiment: 8 diagnostic passes. Repeated timing is admitted only if every exact-output check passes.
DX_experiment, DX_experiment_exit = DX_run_stage("qualification", [])
print(DX_json.dumps({DX_key: DX_experiment.get(DX_key) for DX_key in (
    "status", "measured", "inputsRecheckedAfterQualification", "outputBytesQualifiedForTiming",
    "qualityApproved", "target75Proven", "releaseAuthorized")}, indent=2))
print("Completed runs:", len(DX_experiment.get("runs", [])))
print("Observed placement:", DX_experiment.get("placement", {}))
print("Exit 1 and NUMERICAL_EQUIVALENCE_UNPROVEN are retained as diagnostic evidence, without quality approval.")
print("Run the separate export cell to retain every output, trace and receipt.")
