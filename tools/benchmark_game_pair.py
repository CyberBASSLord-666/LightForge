#!/usr/bin/env python3
"""Compare fresh single/pair GAME execution on two original demo passages."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import signal
import wave

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["android/src/com/cyberbasslord/lightforge/" + name + ".java"
           for name in ("NativeGame", "NativeGameProfile")]
HARNESS = "tests/NativeGamePairComparison.java"


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def identities():
    return {name: digest(ROOT / name) for name in SOURCES + [HARNESS, "tools/benchmark_game_pair.py"]}


def equal_notes(left, right):
    if len(left) != 2 or len(right) != 2:
        raise ValueError("Missing pair output")
    for baseline, candidate in zip(left, right):
        if len(baseline) != len(candidate):
            raise ValueError("Note count differs")
        for first, second in zip(baseline, candidate):
            if set(first) != {"start", "end", "midi"} or set(second) != set(first):
                raise ValueError("Unexpected note shape")
            for key in first:
                if struct.pack("!d", first[key]) != struct.pack("!d", second[key]):
                    raise ValueError("Unrounded note differs: " + key)


def run_with_rss(command, log):
    if not sys.platform.startswith("linux") or not hasattr(os, "wait4"):
        raise RuntimeError("Peak-RSS comparison requires Linux wait4")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    def stop():
        try:
            os.kill(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = threading.Timer(300, stop)
    deadline.daemon = True
    deadline.start()
    try:
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    finally:
        deadline.cancel()
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)
    return usage.ru_maxrss


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = identities()
    model_manifest = json.loads((args.models / "manifest.json").read_text())
    for name, record in model_manifest["files"].items():
        path = args.models / name
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError("Model identity differs: " + name)
    java = [args.java]
    classpath = os.pathsep.join(map(str, (args.dependencies / "onnxruntime-1.25.1.jar", args.dependencies / "test-json.jar")))
    runtime = json.loads((ROOT / "android/native-runtime.json").read_text())["host"]
    for name, expected_bytes, expected_sha in [(runtime["name"], runtime["bytes"], runtime["sha256"]),
            ("test-json.jar", 90031, "c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6")]:
        path = args.dependencies / name
        if path.stat().st_size != expected_bytes or digest(path) != expected_sha:
            raise ValueError("Host dependency pin differs: " + name)
    version = subprocess.run([*java, "-version"], capture_output=True, text=True, check=True)
    java_version = (version.stdout + version.stderr).strip()
    results = []
    with tempfile.TemporaryDirectory(prefix="lightforge-game-pair-") as directory:
        work = Path(directory)
        with wave.open(str(args.wav), "rb") as source:
            if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (44100, 2, 2) or source.getnframes() < 26 * 44100:
                raise ValueError("Expected complete stereo PCM16 demo with at least 26 seconds")
            total = source.getnframes()
            pcm = array.array("h", source.readframes(total))
        if sys.byteorder != "little":
            pcm.byteswap()
        plan = [(max(0, (index * 12 - 2) * 44100), min(total, (index * 12 + 14) * 44100))
                for index in (args.first_passage, args.first_passage + 1)]
        if any(last <= first or (last - first) > 16 * 44100 for first, last in plan):
            raise ValueError("Requested original passages exceed the source")
        seeds = [(2025 + index * 104729) & 0xffffffff for index in (args.first_passage, args.first_passage + 1)]
        inputs = []
        for index, (first, last) in enumerate(plan):
            values = array.array("f", ((pcm[2 * i] + pcm[2 * i + 1]) / 65536 for i in range(first, last)))
            if sys.byteorder != "little":
                values.byteswap()
            path = work / (str(index) + ".f32")
            path.write_bytes(values.tobytes())
            inputs.append(path)
        classes = work / "classes"
        classes.mkdir()
        # Context is compile-only. File-based production constructors never call
        # these Android adapters; omit Process so the profile uses real JVM CPU.
        stubs = [path for path in (ROOT / "tests/native-mdx-host/android").rglob("*.java")
                 if path.name != "Process.java"]
        subprocess.run([*java, "-m", "jdk.compiler/com.sun.tools.javac.Main", "--release", "8", "-encoding", "UTF-8",
                        "-cp", classpath, "-d", str(classes), *map(str, [ROOT / name for name in SOURCES + [HARNESS]] + stubs)],
                       check=True, cwd=ROOT, timeout=60)
        runtime_classpath = os.pathsep.join([str(classes), classpath])
        for pair in range(-1, args.pairs):
            modes = ("single", "pair") if pair % 2 == 0 else ("pair", "single")
            records = {}
            for mode in modes:
                name = ("warmup" if pair < 0 else str(pair)) + "-" + mode
                notes = output / (name + ".json")
                command = [*java, "-Xmx512m", "-cp", runtime_classpath, "com.cyberbasslord.lightforge.NativeGamePairComparison",
                           mode, str(args.models), *map(str, inputs), str(notes), *map(str, seeds)]
                with (output / (name + ".log")).open("wb") as log:
                    peak_rss = run_with_rss(command, log)
                record = json.loads(notes.read_text())
                record.update(pair=pair, warmup=pair < 0, peakRssKiB=peak_rss)
                fields = [dict(re.findall(r"(\w+)=([^ ]+)", profile)) for profile in record["profiles"]]
                record["sessionInitializations"] = sum(int(field["sessionInitCount"]) for field in fields)
                record["graphRuns"] = sum(int(field["inferenceCount"]) for field in fields)
                if record["sessionInitializations"] != (10 if mode == "single" else 5) or record["graphRuns"] != 24:
                    raise ValueError("Original graph work or expected model-load reduction differs")
                records[mode] = record
                results.append(record)
                print(json.dumps({"pair": pair, "mode": mode, "wallSeconds": record["wallSeconds"],
                                  "peakRssKiB": record["peakRssKiB"], "sessionInitializations": record["sessionInitializations"]}), flush=True)
            equal_notes(records["single"]["notes"], records["pair"]["notes"])
        input_hashes = [digest(path) for path in inputs]
    if identities() != before:
        raise ValueError("Compared production source changed during execution")
    measured = [record for record in results if not record["warmup"]]
    baseline = statistics.median(record["wallSeconds"] for record in measured if record["mode"] == "single")
    candidate = statistics.median(record["wallSeconds"] for record in measured if record["mode"] == "pair")
    summary = {"scope": "Original GAME model, two adjacent original full-mix demo passages with complete context and independent production seeds. Host execution only; not separated-vocal accuracy, Android, whole-song or 75% whole-analysis evidence.",
               "javaVersion": java_version, "javaOptions": ["-Xmx512m"], "sourceHashes": before, "modelManifestSha256": digest(args.models / "manifest.json"),
               "inputWavSha256": digest(args.wav), "inputPcmSha256": input_hashes, "originalSampleSpans": plan,
               "allUnroundedNoteBitsIdentical": True, "baselineMedianSeconds": baseline, "pairMedianSeconds": candidate,
               "medianReductionPercent": 100 * (1 - candidate / baseline), "runs": results}
    (output / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=ROOT / "web/analysis/models/game")
    parser.add_argument("--wav", type=Path, default=ROOT / "web/demo/glass-castle.wav")
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--first-passage", type=int, choices=range(0, 4), default=0)
    parser.add_argument("--java", default="java")
    run(parser.parse_args())
