# Run after the original GAME notebook setup. Original globals/evidence remain intact.
HG_COMMIT = "8590ac4a67de4340857a96ffe38bae53d7d902b8"
HG_TREE = "c841bf18f91d3d04dd6daf7e886e2aa473ab8c70"
HG_HARNESS_SHA = "0305734ab3102b375ae80b5d090cadaf68068541b84ced58cbf5466cd89403d9"
HG_PARENT_SETUP_SHA = "a92e864c73f5da16c9103291bc6057d73fd80dd1c70773c21220cf82f14b3926"
HG_PROVENANCE_SHA = "3bd1db1265dfd30a31bdc0fe4b92e5fe428404ccd45b2453a8221a1031760ffb"
HG_PROOF_SHA = "075a6cf2ae0c884ac14c8b9a5e6e67fb3f248091c043bb45468e0e34192ea8a9"
assert SOURCE_COMMIT == "d9b42bb79145cfe81367fd70e2ca0ff7f4d52c12"
assert digest(RUN / "setup-receipt.json") == HG_PARENT_SETUP_SHA
assert digest(INPUT_PROVENANCE) == HG_PROVENANCE_SHA
assert digest(RUN / "input-source-proof.json") == HG_PROOF_SHA
assert digest(PCM) == "a75b3b8d59c87d428e38e45db5f54ad8d2b1613fe79ee07c2595fecbf9215274"
assert digest(AUDIO) == AUDIO_SHA and digest(MODELS / "manifest.json") == MANIFEST_SHA
assert digest(ASSETS / "LightForge-2.3.1.apk") == APK_SHA
HG_REPO = WORK / "source-heavy-only-8590ac4"
assert not HG_REPO.exists(), "Use a fresh retry checkout; preserve any earlier attempt."
HG_REPO.mkdir()
command(["git", "init", "-q", HG_REPO])
command(["git", "-C", HG_REPO, "remote", "add", "origin", REPOSITORY])
command(["git", "-C", HG_REPO, "config", "core.sparseCheckout", "true"])
command(["git", "-C", HG_REPO, "config", "remote.origin.promisor", "true"])
command(["git", "-C", HG_REPO, "config", "remote.origin.partialclonefilter", "blob:none"])
(HG_REPO / ".git/info/sparse-checkout").write_text("\n".join(patterns) + "\n")
command(["git", "-C", HG_REPO, "fetch", "--filter=blob:none", "--depth=1", "origin", HG_COMMIT])
command(["git", "-C", HG_REPO, "checkout", "--detach", HG_COMMIT])
assert command(["git", "-C", HG_REPO, "rev-parse", "HEAD"], capture_output=True).stdout.strip() == HG_COMMIT
assert command(["git", "-C", HG_REPO, "rev-parse", "HEAD^{tree}"], capture_output=True).stdout.strip() == HG_TREE
assert not command(["git", "-C", HG_REPO, "status", "--porcelain", "--untracked-files=no"], capture_output=True).stdout.strip()
HG_BENCHMARK = HG_REPO / "tools/benchmark_game_accelerator.py"
assert digest(HG_BENCHMARK) == HG_HARNESS_SHA
for HG_name in ("web/analysis/wav-reader.js", "web/analysis/game.js", "web/analysis/models/game/manifest.json", "android/src/com/cyberbasslord/lightforge/NativeGame.java"):
    assert digest(HG_REPO / HG_name) == digest(REPO / HG_name), "Original application or input derivation changed."
HG_PARENT_SETUP = json.loads((RUN / "setup-receipt.json").read_text())
for HG_relative, HG_pin in HG_PARENT_SETUP["extractedNativeLibraries"].items():
    HG_path = CUDA_ROOT / HG_relative
    assert HG_path.is_file() and not HG_path.is_symlink()
    assert HG_path.stat().st_size == HG_pin["bytes"] and digest(HG_path) == HG_pin["sha256"]
HG_RUN = WORK / "evidence" / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-heavy-only-" + uuid.uuid4().hex[:8])
HG_RUN.mkdir(parents=True, exist_ok=False)
for HG_name in ("input-provenance.json", "input-source-proof.json", "public-demo-mixture-first14s.f32"):
    shutil.copyfile(RUN / HG_name, HG_RUN / HG_name)
shutil.copyfile(RUN / "setup-receipt.json", HG_RUN / "parent-setup-receipt.json")
HG_SETUP = dict(HG_PARENT_SETUP, sourceCommit=HG_COMMIT, parentSetupSha256=HG_PARENT_SETUP_SHA)
(HG_RUN / "setup-receipt.json").write_text(json.dumps(HG_SETUP, indent=2) + "\n")
HG_HANDOFF = dict(schema="lightforge.game-heavy-only-handoff.v1", executionSourceCommit=HG_COMMIT,
    executionSourceTree=HG_TREE, inputDerivationSourceCommit=SOURCE_COMMIT,
    parentSetupSha256=HG_PARENT_SETUP_SHA, setupReceiptSha256=digest(HG_RUN / "setup-receipt.json"),
    inputProvenanceSha256=HG_PROVENANCE_SHA, inputSourceProofSha256=HG_PROOF_SHA,
    harnessSha256=HG_HARNESS_SHA, cudaHeavyOnly=True,
    createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    qualityApproved=False, target75Proven=False, releaseAuthorized=False)
(HG_RUN / "source-handoff.json").write_text(json.dumps(HG_HANDOFF, indent=2) + "\n")
HG_gpu = command(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"], capture_output=True)
(HG_RUN / "gpu-inventory.txt").write_text(HG_gpu.stdout + HG_gpu.stderr)
print("Fresh evidence:", HG_RUN, "GPU:", HG_gpu.stdout.strip(), flush=True)
HG_arguments = [sys.executable, str(HG_BENCHMARK), "--toolchain", str(TOOLCHAIN), "--models", str(MODELS),
    "--input", str(HG_RUN / "public-demo-mixture-first14s.f32"), "--input-provenance", str(HG_RUN / "input-provenance.json"), "--cuda-heavy-only"]

def HG_run_stage(name, extra):
    output = HG_RUN / name
    assert not output.exists(), "Refusing existing evidence."
    with (HG_RUN / (name + ".log")).open("x") as log:
        process = subprocess.Popen(HG_arguments + ["--output", str(output)] + extra,
            cwd=HG_REPO, env=benchmark_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
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
            (HG_RUN / (name + "-interrupted.json")).write_text(json.dumps(dict(status="INTERRUPTED", completed=False, target75Proven=False)) + "\n")
            raise
    receipt_path = output / "receipt.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else dict(status="PROCESS_FAILED_WITHOUT_RECEIPT")
    print(name, "exit:", process.returncode, "status:", receipt["status"], flush=True)
    if receipt.get("failure"):
        print(receipt["failure"], flush=True)
    return receipt

HG_readiness = HG_run_stage("readiness", ["--check-readiness"])
assert HG_readiness["status"] == "PREFLIGHT_READY", "Retain failed evidence; do not substitute execution."
HG_experiment = HG_run_stage("qualification", [])
print(json.dumps({key: HG_experiment.get(key) for key in ("status", "inputsRecheckedAfterQualification", "observerComparisonsPassed", "rawOutputsByteIdenticalAcrossVariants", "qualityApproved", "target75Proven", "releaseAuthorized")}, indent=2))
print("Completed diagnostic passes:", len(HG_experiment.get("runs", [])), "of 12")
print("Observed placement:", HG_experiment.get("placement", {}))
print("Diagnostic only; no accepted speed ratio or musical-quality approval.")
