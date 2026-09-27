# Run after the original GAME notebook setup. Original globals/evidence remain intact.
DT_COMMIT = "9ca73bb8681434f6f2dc9ce1a00ce33531a04379"
DT_TREE = "a5a7071ce9252608bcb7b5d57126396669bd7abe"
DT_HARNESS_SHA = "d67fa0fe0d75bba041a1b9cf00a55a58d65fc81c93f25b9d76247d62c4bab527"
DT_PARENT_SETUP_SHA = "a92e864c73f5da16c9103291bc6057d73fd80dd1c70773c21220cf82f14b3926"
DT_PROVENANCE_SHA = "3bd1db1265dfd30a31bdc0fe4b92e5fe428404ccd45b2453a8221a1031760ffb"
DT_PROOF_SHA = "075a6cf2ae0c884ac14c8b9a5e6e67fb3f248091c043bb45468e0e34192ea8a9"
assert SOURCE_COMMIT == "d9b42bb79145cfe81367fd70e2ca0ff7f4d52c12"
assert digest(RUN / "setup-receipt.json") == DT_PARENT_SETUP_SHA
assert digest(INPUT_PROVENANCE) == DT_PROVENANCE_SHA
assert digest(RUN / "input-source-proof.json") == DT_PROOF_SHA
assert digest(PCM) == "a75b3b8d59c87d428e38e45db5f54ad8d2b1613fe79ee07c2595fecbf9215274"
assert digest(AUDIO) == AUDIO_SHA and digest(MODELS / "manifest.json") == MANIFEST_SHA
assert digest(ASSETS / "LightForge-2.3.1.apk") == APK_SHA
DT_REPO = WORK / "source-deterministic-9ca73bb"
assert not DT_REPO.exists(), "Use a fresh retry checkout; preserve any earlier attempt."
DT_REPO.mkdir()
command(["git", "init", "-q", DT_REPO])
command(["git", "-C", DT_REPO, "remote", "add", "origin", REPOSITORY])
command(["git", "-C", DT_REPO, "config", "core.sparseCheckout", "true"])
command(["git", "-C", DT_REPO, "config", "remote.origin.promisor", "true"])
command(["git", "-C", DT_REPO, "config", "remote.origin.partialclonefilter", "blob:none"])
(DT_REPO / ".git/info/sparse-checkout").write_text("\n".join(patterns) + "\n")
command(["git", "-C", DT_REPO, "fetch", "--filter=blob:none", "--depth=1", "origin", DT_COMMIT])
command(["git", "-C", DT_REPO, "checkout", "--detach", DT_COMMIT])
assert command(["git", "-C", DT_REPO, "rev-parse", "HEAD"], capture_output=True).stdout.strip() == DT_COMMIT
assert command(["git", "-C", DT_REPO, "rev-parse", "HEAD^{tree}"], capture_output=True).stdout.strip() == DT_TREE
assert not command(["git", "-C", DT_REPO, "status", "--porcelain", "--untracked-files=no"], capture_output=True).stdout.strip()
DT_BENCHMARK = DT_REPO / "tools/benchmark_game_accelerator.py"
assert digest(DT_BENCHMARK) == DT_HARNESS_SHA
for DT_name in ("web/analysis/wav-reader.js", "web/analysis/game.js", "web/analysis/models/game/manifest.json", "android/src/com/cyberbasslord/lightforge/NativeGame.java"):
    assert digest(DT_REPO / DT_name) == digest(REPO / DT_name), "Original application or input derivation changed."
DT_PARENT_SETUP = json.loads((RUN / "setup-receipt.json").read_text())
for DT_relative, DT_pin in DT_PARENT_SETUP["extractedNativeLibraries"].items():
    DT_path = CUDA_ROOT / DT_relative
    assert DT_path.is_file() and not DT_path.is_symlink()
    assert DT_path.stat().st_size == DT_pin["bytes"] and digest(DT_path) == DT_pin["sha256"]
DT_RUN = WORK / "evidence" / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-deterministic-" + uuid.uuid4().hex[:8])
DT_RUN.mkdir(parents=True, exist_ok=False)
for DT_name in ("input-provenance.json", "input-source-proof.json", "public-demo-mixture-first14s.f32"):
    shutil.copyfile(RUN / DT_name, DT_RUN / DT_name)
shutil.copyfile(RUN / "setup-receipt.json", DT_RUN / "parent-setup-receipt.json")
DT_SETUP = dict(DT_PARENT_SETUP, sourceCommit=DT_COMMIT, parentSetupSha256=DT_PARENT_SETUP_SHA)
(DT_RUN / "setup-receipt.json").write_text(json.dumps(DT_SETUP, indent=2) + "\n")
DT_HANDOFF = dict(schema="lightforge.game-deterministic-handoff.v1", executionSourceCommit=DT_COMMIT,
    executionSourceTree=DT_TREE, inputDerivationSourceCommit=SOURCE_COMMIT,
    parentSetupSha256=DT_PARENT_SETUP_SHA, setupReceiptSha256=digest(DT_RUN / "setup-receipt.json"),
    inputProvenanceSha256=DT_PROVENANCE_SHA, inputSourceProofSha256=DT_PROOF_SHA,
    harnessSha256=DT_HARNESS_SHA, cudaHeavyOnly=True, cudaDeterministicCompute=True,
    createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    qualityApproved=False, target75Proven=False, releaseAuthorized=False)
(DT_RUN / "source-handoff.json").write_text(json.dumps(DT_HANDOFF, indent=2) + "\n")
DT_gpu = command(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"], capture_output=True)
(DT_RUN / "gpu-inventory.txt").write_text(DT_gpu.stdout + DT_gpu.stderr)
print("Fresh evidence:", DT_RUN, "GPU:", DT_gpu.stdout.strip(), flush=True)
DT_arguments = [sys.executable, str(DT_BENCHMARK), "--toolchain", str(TOOLCHAIN), "--models", str(MODELS),
    "--input", str(DT_RUN / "public-demo-mixture-first14s.f32"), "--input-provenance", str(DT_RUN / "input-provenance.json"), "--cuda-heavy-only", "--cuda-deterministic"]

def DT_run_stage(name, extra):
    output = DT_RUN / name
    assert not output.exists(), "Refusing existing evidence."
    with (DT_RUN / (name + ".log")).open("x") as log:
        process = subprocess.Popen(DT_arguments + ["--output", str(output)] + extra,
            cwd=DT_REPO, env=benchmark_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        previous = None
        try:
            while process.poll() is None:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    try:
                        partial = json.loads((output / "receipt.json").read_text())
                        progress = (partial.get("status"), len(partial.get("runs", [])))
                    except (FileNotFoundError, json.JSONDecodeError):
                        progress = ("STARTING", 0)
                    if progress != previous:
                        print(name, "status:", progress[0], "completed passes:", progress[1], flush=True)
                        previous = progress
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()
            (DT_RUN / (name + "-interrupted.json")).write_text(json.dumps(dict(status="INTERRUPTED", completed=False, target75Proven=False)) + "\n")
            raise
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    receipt_path = output / "receipt.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else dict(status="PROCESS_FAILED_WITHOUT_RECEIPT")
    (DT_RUN / (name + "-exit.json")).write_text(json.dumps(dict(exitCode=process.returncode, logSha256=digest(DT_RUN / (name + ".log")), receiptSha256=digest(receipt_path) if receipt_path.exists() else None), indent=2) + "\n")
    print(name, "exit:", process.returncode, "status:", receipt["status"], flush=True)
    if receipt.get("failure"):
        print(receipt["failure"], flush=True)
    return receipt

DT_readiness = DT_run_stage("readiness", ["--check-readiness"])
assert DT_readiness["status"] == "PREFLIGHT_READY", "Retain failed evidence; do not substitute execution."
DT_experiment = DT_run_stage("qualification", [])
print(json.dumps({key: DT_experiment.get(key) for key in ("status", "inputsRecheckedAfterQualification", "observerComparisonsPassed", "rawOutputsByteIdenticalAcrossVariants", "qualityApproved", "target75Proven", "releaseAuthorized")}, indent=2))
print("Completed diagnostic passes:", len(DT_experiment.get("runs", [])), "of 12")
print("Observed placement:", DT_experiment.get("placement", {}))
print("Diagnostic only; no accepted speed ratio or musical-quality approval.")
