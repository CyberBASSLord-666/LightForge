#!/usr/bin/env python3
"""Frozen-source complete public GAME CPU/CUDA capture and production replay.

Arguments bind the actual new source commit, tree and harness before execution.
This is a 64-second mixed-audio diagnostic, not a vocal-stage or quality gate.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tarfile
import urllib.request
import uuid
import wave

REPOSITORY = "https://github.com/CyberBASSLord-666/LightForge.git"
ORIGINAL_SOURCE = "d9b42bb79145cfe81367fd70e2ca0ff7f4d52c12"
APK_SHA = "af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f"
AUDIO_SHA = "33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650"
MANIFEST_SHA = "51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97"
NODE_NAME = "node-v22.19.0-linux-x64.tar.xz"
NODE_URL = "https://nodejs.org/dist/v22.19.0/" + NODE_NAME
NODE_SHA = "c0649af18e6a24f6fe5535a3e86b341dd49a8e71117c8b68bde973ef834f16f2"
APP_FILES = ("android/src/com/cyberbasslord/lightforge/NativeGame.java", "android/native-runtime.json",
             "web/analysis/game.js", "web/analysis/wav-reader.js", "web/analysis/models/game/manifest.json")
SOURCE_PATTERNS = ("/android/src/", "/android/native-runtime.json", "/tests/NativeGameTest.java",
    "/tools/benchmark_game_accelerator.py", "/tools/game_benchmark/", "/tools/benchmark_game_source_cuda.py",
    "/tools/benchmark_deux_accelerator.py", "/tools/profile_deux_operators.py", "/tools/benchmark_deux_execution.py",
    "/tests/NativeDeuxExecutionBenchmark.java", "/tools/bootstrap_toolchain.py", "/web/analysis/game.js",
    "/web/analysis/wav-reader.js", "/web/analysis/models/game/manifest.json", "/web/analysis/models/game/config.json",
    "/web/analysis/models/deux/manifest.json", "/research/performance/2026-09-24/game-full-source/")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def command(arguments, **kwargs):
    return subprocess.run([str(v) for v in arguments], check=True, text=True, **kwargs)


def checked(path, sha256=None):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), "Missing/linked evidence: " + str(path)
    pin = {"bytes": path.stat().st_size, "sha256": digest(path)}
    assert sha256 is None or pin["sha256"] == sha256, "Digest mismatch: " + str(path)
    return pin


NODE_PROOF = r"""const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const [root,audioPath,pcmPath,proofPath]=process.argv.slice(1);
const WavReader=require(path.join(root,'web/analysis/wav-reader.js'));
const GAME=require(path.join(root,'web/analysis/game.js'));
const audio=fs.readFileSync(audioPath),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'web/analysis/models/game/manifest.json')));
(async()=>{
 globalThis.fetch=async(url,options={})=>{
  if(String(url)==='https://lightforge-public-fixture.invalid/manifest.json')return{json:async()=>manifest};
  assert.equal(String(url),'https://lightforge-public-fixture.invalid/demo.wav');
  const match=/^bytes=(\d+)-(\d+)$/.exec(options.headers.Range);assert(match);
  const first=Number(match[1]),last=Math.min(Number(match[2]),audio.length-1);
  return new Response(audio.subarray(first,last+1),{status:206,headers:{'Content-Length':String(last-first+1),'Content-Range':`bytes ${first}-${last}/${audio.length}`}});
 };
 const reader=new WavReader('https://lightforge-public-fixture.invalid/demo.wav');await reader.open();
 assert.equal(reader.rate,44100);assert.equal(reader.samples,2822400);
 const mono=new Float32Array(reader.samples),productionReaderCalls=[];
 for(let first=0;first<reader.samples;first+=32*44100){
  const count=Math.min(32*44100,reader.samples-first);
  const stereo=await reader.stereo44100(first,count);
  productionReaderCalls.push({first,count});
  for(let i=0;i<count;i++)mono[first+i]=(stereo[0][i]+stereo[1][i])*.5;
 }
 const bytes=Buffer.alloc(mono.length*4);for(let i=0;i<mono.length;i++)bytes.writeFloatLE(mono[i],i*4);
 assert(bytes.equals(fs.readFileSync(pcmPath)),'Full Python PCM differs from actual production WavReader mix');
 const observed=[],reads=[];
 const adapter=await GAME.create({baseUrl:'https://lightforge-public-fixture.invalid/',nativeInfer:async(pcm,language,seed)=>{observed.push({samples:pcm.length,language,seed});return[];}});
 try{await adapter.process(async(first,count)=>{reads.push({first,last:first+count});return new Float32Array(count).fill(.125);},reader.samples,{language:0});}
 finally{await adapter.release();}
 assert.equal(reads.length,observed.length);
 const plan=observed.map((value,index)=>({index,...reads[index],...value}));
 fs.writeFileSync(proofPath,JSON.stringify({schema:'lightforge.game-source-input-proof.v1',publicAudioSha256:hash(audio),pcmSha256:hash(bytes),
  totalSamples:reader.samples,sampleRate:44100,byteIdenticalToProductionReaderMix:true,productionReaderCalls,plan,
  scheduleProbeUsesSyntheticNonSilentPCM:true,planOnly:true,modelInferenceExecuted:false,qualityApproved:false,
  sourceHashes:Object.fromEntries(['web/analysis/wav-reader.js','web/analysis/game.js'].map(name=>[name,hash(fs.readFileSync(path.join(root,name)))]))},null,2)+'\n',{flag:'wx'});
})().catch(error=>{console.error(error);process.exitCode=1;});"""


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"pid": pid, "parent": int(fields[1]), "group": int(fields[2]), "start": fields[19]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants(pid):
    records = {}
    for path in Path("/proc").iterdir():
        if path.name.isdecimal():
            record = process_identity(int(path.name))
            if record:
                records[record["pid"]] = record
    found, pending = {}, [pid]
    while pending:
        parent = pending.pop()
        for child, record in records.items():
            if child != pid and child not in found and record["parent"] == parent:
                found[child] = record
                pending.append(child)
    return found


def retire_stage(process):
    """Let collector finally retire its separate-session JVM; bound fallback to verified descendants."""
    if process.poll() is not None:
        return
    root_identity = process_identity(process.pid)
    assert root_identity and root_identity["group"] == process.pid
    owned = descendants(process.pid)
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        owned.update(descendants(process.pid))
    # PID start ticks prevent signaling a recycled PID. Retire only descendants
    # actually observed under this launch, never global Java/Colab processes.
    for pid, identity in owned.items():
        current = process_identity(pid)
        if current and current["start"] == identity["start"]:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    if process.poll() is None:
        current = process_identity(process.pid)
        assert current and current["start"] == root_identity["start"]
        process.kill()
    process.wait()


def stage(run, name, arguments, repo, env):
    log_path = run / (name + ".log")
    with log_path.open("x") as log:
        process = subprocess.Popen(list(map(str, arguments)), cwd=repo, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        previous = None
        try:
            while process.poll() is None:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    progress_path = run / name / "receipt.json"
                    if progress_path.is_file():
                        try:
                            progress = json.loads(progress_path.read_text())
                            observed = (progress.get("status"), len(progress.get("runs", [])))
                            if observed != previous:
                                print(name, observed[0], "completed JVM runs", observed[1], flush=True)
                                previous = observed
                        except json.JSONDecodeError:
                            pass
        finally:
            retire_stage(process)
            write_json(run / (name + "-exit.json"), {"exitCode": process.returncode,
                "logSha256": digest(log_path), "qualityApproved": False, "target75Proven": False})
    print(name, "exit", process.returncode, flush=True)
    return process.returncode


def execute(args, run, receipt):
    setup_run = args.setup_run.resolve()
    assert setup_run.parent.name == "evidence", "Pass the actual fresh original setup RUN directory."
    work = setup_run.parent.parent
    assert not work.is_symlink() and setup_run.is_dir()
    old_repo, toolchain, assets = [work / name for name in ("source", "toolchain", "assets")]
    models, audio = assets / "game", assets / "glass-castle.wav"
    parent_path = setup_run / "setup-receipt.json"
    parent_pin = checked(parent_path)
    parent = json.loads(parent_path.read_text())
    assert parent["schema"] == "lightforge.game-notebook-setup.v1" and parent["sourceCommit"] == ORIGINAL_SOURCE
    assert parent["publicApkSha256"] == APK_SHA and parent["publicAudioSha256"] == AUDIO_SHA
    assert parent["modelManifestSha256"] == MANIFEST_SHA
    for flag in ("qualityApproved", "target75Proven", "releaseAuthorized"):
        assert parent[flag] is False
    assert command(["git", "-C", old_repo, "rev-parse", "HEAD"], capture_output=True).stdout.strip() == ORIGINAL_SOURCE
    assert not command(["git", "-C", old_repo, "status", "--porcelain", "--untracked-files=no"], capture_output=True).stdout.strip()
    checked(assets / "LightForge-2.3.1.apk", APK_SHA)
    checked(audio, AUDIO_SHA)
    checked(models / "manifest.json", MANIFEST_SHA)
    manifest = json.loads((models / "manifest.json").read_text())
    assert len(manifest["files"]) == 6
    for name, pin in manifest["files"].items():
        assert Path(name).name == name and checked(models / name, pin["sha256"])["bytes"] == pin["bytes"]
    checked(setup_run / "input-provenance.json", parent["inputProvenanceSha256"])
    old_provenance = json.loads((setup_run / "input-provenance.json").read_text())
    checked(setup_run / "public-demo-mixture-first14s.f32", parent["inputPcmSha256"])
    checked(setup_run / "input-source-proof.json", old_provenance["inputSourceProofSha256"])
    parent_dir = run / "parent-setup"
    parent_dir.mkdir()
    for name in ("setup-receipt.json", "input-provenance.json", "input-source-proof.json", "input-source-proof.log", "gpu-inventory.txt"):
        checked(setup_run / name)
        shutil.copyfile(setup_run / name, parent_dir / name)
    cuda_root = toolchain / "cuda-wheels"
    library_pins = parent["extractedNativeLibraries"]
    for name, pin in library_pins.items():
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        assert checked(cuda_root / name, pin["sha256"])["bytes"] == pin["bytes"]
    env = os.environ.copy()
    assert not any(env.get(k) for k in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"))
    library_dirs = sorted(str(p) for p in cuda_root.glob("nvidia/*/lib") if p.is_dir())
    assert len(library_dirs) == 7
    env["LD_LIBRARY_PATH"] = os.pathsep.join(library_dirs + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else []))
    env["CUBLAS_WORKSPACE_CONFIG"], env["NVIDIA_TF32_OVERRIDE"] = ":4096:8", "0"
    repo = work / ("source-full-" + args.source_commit[:12] + "-" + uuid.uuid4().hex[:8])
    repo.mkdir()
    command(["git", "init", "-q", repo])
    command(["git", "-C", repo, "remote", "add", "origin", REPOSITORY])
    command(["git", "-C", repo, "config", "core.sparseCheckout", "true"])
    command(["git", "-C", repo, "config", "remote.origin.promisor", "true"])
    command(["git", "-C", repo, "config", "remote.origin.partialclonefilter", "blob:none"])
    (repo / ".git/info/sparse-checkout").write_text("\n".join(SOURCE_PATTERNS) + "\n")
    command(["git", "-C", repo, "fetch", "--filter=blob:none", "--depth=1", "origin", args.source_commit])
    command(["git", "-C", repo, "checkout", "--detach", args.source_commit])
    assert command(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True).stdout.strip() == args.source_commit
    assert command(["git", "-C", repo, "rev-parse", "HEAD^{tree}"], capture_output=True).stdout.strip() == args.source_tree
    assert not command(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"], capture_output=True).stdout.strip()
    benchmark = repo / "tools/benchmark_game_source_cuda.py"
    checked(benchmark, args.harness_sha256)
    for name in APP_FILES:
        assert digest(repo / name) == digest(old_repo / name), "Original application/input derivation changed: " + name
    node_dir = toolchain / ("full-source-node-" + run.name)
    node_dir.mkdir()
    node_archive, node = node_dir / NODE_NAME, node_dir / "node"
    with urllib.request.urlopen(NODE_URL, timeout=120) as response, node_archive.open("xb") as target:
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            assert total <= 50 * 1024 * 1024, "Node archive exceeds bounded size."
            target.write(block)
    checked(node_archive, NODE_SHA)
    with tarfile.open(node_archive, "r:xz") as archive:
        member = archive.getmember("node-v22.19.0-linux-x64/bin/node")
        assert member.isfile()
        with archive.extractfile(member) as source, node.open("xb") as target:
            shutil.copyfileobj(source, target)
    node.chmod(0o700)
    assert command([node, "--version"], capture_output=True).stdout.strip() == "v22.19.0"
    env["PATH"] = str(node_dir) + os.pathsep + env.get("PATH", "")
    pcm = run / "public-demo-mixture-full64s.f32"
    with wave.open(str(audio), "rb") as source:
        assert source.getnchannels() == 2 and source.getsampwidth() == 2 and source.getframerate() == 44100
        assert source.getcomptype() == "NONE" and source.getnframes() == 2822400
        raw = source.readframes(source.getnframes())
    assert len(raw) == 2822400 * 4
    with pcm.open("xb") as target:
        for left, right in struct.iter_unpack("<hh", raw):
            target.write(struct.pack("<f", (left / 32768.0 + right / 32768.0) * .5))
    proof = run / "input-source-proof.json"
    with (run / "input-source-proof.log").open("x") as log:
        command([node, "-e", NODE_PROOF, repo, audio, pcm, proof], env=env, stdout=log, stderr=subprocess.STDOUT)
    actual_proof = json.loads(proof.read_text())
    plan = [dict(index=i, first=max(0, i*12-2)*44100, last=min(2822400, ((i+1)*12+2)*44100),
                 samples=min(2822400, ((i+1)*12+2)*44100)-max(0,i*12-2)*44100, language=0,
                 seed=(2025+i*104729)&0xffffffff) for i in range(6)]
    assert actual_proof["plan"] == plan and actual_proof["byteIdenticalToProductionReaderMix"] is True
    assert actual_proof["pcmSha256"] == digest(pcm) and actual_proof["publicAudioSha256"] == AUDIO_SHA
    assert actual_proof["productionReaderCalls"] == [dict(first=0, count=32*44100), dict(first=32*44100, count=32*44100)]
    provenance = run / "input-provenance.json"
    write_json(provenance, dict(schema="lightforge.game-source-input.v1", sourceCommit=args.source_commit,
        sourceTree=args.source_tree, sourceKind="public-mixture", separatedVocals=False,
        publicRelease="https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.3.1",
        apkSha256=APK_SHA, audioMember="assets/demo/glass-castle.wav", sampleRate=44100, sourceSamples=2822400,
        channels=1, encoding="float32-le", language=0, pcmSHA256=digest(pcm), sourceSHA256=AUDIO_SHA,
        inputSourceProofSha256=digest(proof), qualityApproved=False, target75Proven=False,
        derivation="All 2822400 frames of the hash-pinned public 64-second glass-castle.wav are retained. PCM16 left/right samples are divided by 32768, averaged in double precision and rounded once to Float32. Complete bytes match two consecutive 32-second reads through actual production WavReader.stereo44100 plus JavaScript scalar averaging, within its unchanged 40-second per-read bound. This is mixed audio, not separated vocals."))
    source_copy = run / "execution-source"
    source_copy.mkdir()
    source_pins = {}
    # Copy only tracked text sources from the explicit sparse checkout; no model graphs, APK, credentials or private audio.
    names = command(["git", "-C", repo, "ls-files"], capture_output=True).stdout.splitlines()
    for name in names:
        path = repo / name
        if not path.is_file() or path.suffix not in (".py", ".java", ".cjs", ".js", ".json", ".md"):
            continue
        if not (name.startswith(("android/src/", "tools/", "tests/", "research/performance/2026-09-24/game-full-source/")) or name in APP_FILES or name == "web/analysis/models/game/config.json"):
            continue
        assert not path.is_symlink()
        target = source_copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        source_pins[name] = checked(path)
    setup = dict(schema="lightforge.game-full-source-handoff.v1", createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        executionSourceCommit=args.source_commit, executionSourceTree=args.source_tree, harnessSha256=args.harness_sha256,
        originalSetupSourceCommit=ORIGINAL_SOURCE, parentSetupReceipt=parent_pin,
        originalApplicationSourceUnchanged=True, applicationSourceHashes={n:digest(repo/n) for n in APP_FILES},
        inputProvenance=checked(provenance), inputSourceProof=checked(proof), fullPcm=checked(pcm),
        publicAudioSha256=AUDIO_SHA, modelManifestSha256=MANIFEST_SHA, sourceFiles=source_pins,
        nodeVersion="v22.19.0", node=checked(node), nodeArchive={"url":NODE_URL,**checked(node_archive)},
        extractedNativeLibraries=library_pins, qualityApproved=False, target75Proven=False, releaseAuthorized=False)
    write_json(run / "source-handoff.json", setup)
    gpu = command(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"], capture_output=True)
    (run / "gpu-inventory.txt").write_text(gpu.stdout + gpu.stderr)
    arguments = [sys.executable, benchmark, "--models", models, "--input", pcm,
                 "--input-provenance", provenance, "--toolchain", toolchain]
    readiness_exit = stage(run, "readiness", arguments+["--output", run/"readiness", "--check-readiness"], repo, env)
    readiness = json.loads((run / "readiness/receipt.json").read_text())
    assert readiness_exit == 0 and readiness["status"] == "PREFLIGHT_READY" and readiness["readinessSnapshotCount"] == 6 and readiness["inferenceExecuted"] is False
    qualification_exit = stage(run, "qualification", arguments+["--output", run/"qualification"], repo, env)
    qualification = json.loads((run / "qualification/receipt.json").read_text())
    assert qualification_exit == 0 and qualification["status"] in ("COMPLETE_DIAGNOSTIC", "NUMERICAL_EQUIVALENCE_UNPROVEN")
    assert qualification["observerComparisonsPassed"] is True and qualification["inputsRecheckedAfterQualification"] is True
    replay_exit = stage(run, "replay", [node, repo/"tools/game_benchmark/replay_cuda_source.cjs",
        run/"qualification/replay-manifest.json", pcm, run/"replay.json"], repo, env)
    assert replay_exit in (0, 2), "Production replay invalid; preserve evidence."
    for name, pin in source_pins.items():
        assert checked(repo/name) == pin and checked(source_copy/name) == pin
    for name, pin in library_pins.items():
        assert checked(cuda_root/name) == pin
    assert checked(parent_path) == parent_pin and checked(node) == setup["node"]
    assert checked(pcm) == setup["fullPcm"] and checked(provenance) == setup["inputProvenance"] and checked(proof) == setup["inputSourceProof"]
    checked(audio, AUDIO_SHA)
    assert not command(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"], capture_output=True).stdout.strip()
    receipt.update(status="COMPLETE_DIAGNOSTIC", qualificationStatus=qualification["status"],
        replayExitCode=replay_exit, replayReceipt=checked(run/"replay.json"), qualificationReceipt=checked(run/"qualification/receipt.json"),
        inputsAndSourcesRecheckedAfterReplay=True, completedJvmRuns=len(qualification["runs"]))
    return replay_exit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup-run", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--harness-sha256", required=True)
    args = parser.parse_args()
    assert re.fullmatch("[a-f0-9]{40}", args.source_commit) and re.fullmatch("[a-f0-9]{40}", args.source_tree)
    assert re.fullmatch("[a-f0-9]{64}", args.harness_sha256)
    assert args.setup_run.is_dir() and args.setup_run.resolve().parent.name == "evidence"
    run = args.setup_run.resolve().parent / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-game-full-source-"+uuid.uuid4().hex[:8])
    run.mkdir()
    print("Fresh full-source evidence:", run, flush=True)
    shutil.copyfile(Path(__file__).resolve(), run / "executed-colab-run.py")
    receipt = dict(schema="lightforge.game-full-source-driver.v1", status="INCOMPLETE", driverScript=checked(run/"executed-colab-run.py"), executionSourceCommit=args.source_commit,
        executionSourceTree=args.source_tree, harnessSha256=args.harness_sha256, qualityApproved=False, target75Proven=False,
        benchmarkTimingAdmitted=False, releaseAuthorized=False, completeVocalStageMeasured=False,
        scope="Full 64-second public mixture through GAME only, six fresh JVM arms/modes, actual production stitching and checkpoint replay; no speed ratio.")
    result = 1
    try:
        result = execute(args, run, receipt)
    except BaseException as error:
        receipt.update(status="BLOCKED_OR_REJECTED", failure=str(error), failureType=type(error).__name__)
        raise
    finally:
        write_json(run/"driver-receipt.json", receipt)
        print("Evidence retained:", run, flush=True)
        print(json.dumps(receipt, indent=2), flush=True)
    return result


if __name__ == "__main__":
    sys.exit(main())
