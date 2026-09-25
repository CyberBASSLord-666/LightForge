#!/usr/bin/env python3
"""Preserve one completed or failed public GAME diagnostic; never export runtime assets.

Archive allowlist includes only this runner's public PCM, text source snapshots,
compiled research classes, receipts, raw tensors and traces. It excludes APKs,
original model files, runtime binaries, environment dumps and credentials.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT_NAMES = {
    "driver-receipt.json", "executed-colab-run.py", "source-handoff.json",
    "public-demo-mixture-full64s.f32", "input-provenance.json", "input-source-proof.json",
    "input-source-proof.log", "gpu-inventory.txt", "replay.json",
    "readiness.log", "readiness-exit.json", "qualification.log", "qualification-exit.json",
    "replay.log", "replay-exit.json",
}
PARENT_NAMES = {"setup-receipt.json", "input-provenance.json", "input-source-proof.json", "input-source-proof.log", "gpu-inventory.txt"}
SOURCE_EXTENSIONS = {".py", ".java", ".cjs", ".js", ".json", ".md"}
CLASS_NAME = r"(?:NativeGame|GameSourceRunner|GameAcceleratorCapture)(?:\$[A-Za-z0-9_$]+)?\.class"
ARM = r"(?:cpu_all|cuda_basic)_(?:plain|captured|profiled)"
GRAPH = r"(?:encoder|dur2bd|segmenter|bd2dur|estimator)"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def allowed(relative):
    parts = relative.parts
    name = relative.as_posix()
    if len(parts) == 1:
        return name in ROOT_NAMES
    if len(parts) == 2 and parts[0] == "parent-setup":
        return parts[1] in PARENT_NAMES
    if parts[0] == "execution-source":
        child = Path(*parts[1:])
        return child.suffix in SOURCE_EXTENSIONS and (
            child.as_posix().startswith(("android/src/", "tools/", "tests/", "research/performance/2026-09-24/game-full-source/")) or
            child.as_posix() in {"android/native-runtime.json", "web/analysis/game.js", "web/analysis/wav-reader.js",
                                "web/analysis/models/game/manifest.json", "web/analysis/models/game/config.json"})
    if parts[0] not in ("readiness", "qualification"):
        return False
    child = "/".join(parts[1:])
    patterns = [
        r"(?:receipt\.json(?:\.partial)?|replay-manifest\.json)",
        r"(?:cpu_all|cuda_basic)-runtime-probe/(?:RuntimeProbe\.(?:java|class)|compile\.log|probe\.log)",
        rf"(?:readiness_)?{ARM}/(?:NativeGame\.java|GameSourceRunner\.java|GameAcceleratorCapture\.java|compile\.log|run\.log|cuda-jvm-loaded-library-maps\.txt)",
        rf"(?:readiness_)?{ARM}/classes/com/cyberbasslord/lightforge/{CLASS_NAME}",
        rf"{ARM}/output/receipt\.json(?:\.partial)?",
        rf"{ARM}/output/passage-\d{{3}}/receipt\.json(?:\.partial)?",
        rf"{ARM}/output/passage-\d{{3}}/(?:encoder|dur2bd|bd2dur|estimator|segmenter-\d+)-[A-Za-z0-9_]+\.bin",
        rf"{ARM}/output/passage-\d{{3}}/traces/{GRAPH}_[A-Za-z0-9_.-]+\.json",
        rf"(?:readiness_)?(?:cpu_all|cuda_basic)_active_traces/{GRAPH}_[A-Za-z0-9_.-]+\.json",
    ]
    return any(re.fullmatch(pattern, child) for pattern in patterns)


def export(run, output):
    run = run.resolve()
    assert run.is_dir() and re.fullmatch(r"\d{8}T\d{6}Z-game-full-source-[a-f0-9]{8}", run.name)
    assert output.parent.resolve() == run.parent, "Keep archive outside the evidence tree."
    assert not output.exists() and not output.is_symlink(), "Refusing to overwrite an archive."
    receipt = json.loads((run / "driver-receipt.json").read_text())
    assert receipt["schema"] == "lightforge.game-full-source-driver.v1"
    assert receipt["status"] in ("COMPLETE_DIAGNOSTIC", "BLOCKED_OR_REJECTED"), "Do not archive an active run."
    assert all(receipt[key] is False for key in ("qualityApproved", "target75Proven", "benchmarkTimingAdmitted", "releaseAuthorized", "completeVocalStageMeasured"))
    files = []
    for path in sorted(run.rglob("*")):
        assert not path.is_symlink(), "Refusing linked evidence: " + str(path)
        if not path.is_file():
            continue
        relative = path.relative_to(run)
        assert allowed(relative), "Unreviewed export member: " + relative.as_posix()
        files.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
    manifest = dict(schema="lightforge.game-full-source-archive.v1", runDirectory=run.name,
        driverStatus=receipt["status"], executionSourceCommit=receipt["executionSourceCommit"], executionSourceTree=receipt["executionSourceTree"],
        files=files, qualityApproved=False, target75Proven=False, releaseAuthorized=False,
        scope="Public-source research evidence only; manifest excludes itself; failures remain failures.")
    manifest_path = run / "archive-manifest.json"
    with manifest_path.open("x") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for row in files:
            path = run / row["path"]
            assert path.stat().st_size == row["bytes"] and digest(path) == row["sha256"], "Evidence changed during export."
            archive.write(path, arcname=(Path(run.name) / row["path"]).as_posix())
        archive.write(manifest_path, arcname=run.name + "/archive-manifest.json")
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None, "Archive CRC verification failed."
        assert len(archive.namelist()) == len(files) + 1
    result = dict(archive=output.name, bytes=output.stat().st_size, sha256=digest(output), members=len(files)+1,
                  status=receipt["status"], qualityApproved=False, target75Proven=False)
    print(json.dumps(result, indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Use Colab files.download after archive verification.")
    args = parser.parse_args()
    run = args.run.resolve()
    archive = run.with_suffix(".zip")
    export(run, archive)
    if args.download:
        from google.colab import files
        files.download(str(archive))
    return 0


if __name__ == "__main__":
    sys.exit(main())
