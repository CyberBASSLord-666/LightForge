#!/usr/bin/env python3
"""Check exact WAV output and optionally measure bounded host conversion work.

No model preparation, Android device, full-song inference or release qualification
is performed. The old converter is a hash-pinned, test-only oracle. Actual current
AudioImporter.readWave and the existing NativeAudioTest also execute; unavailable
Android decoder/FSEQ APIs use throwing compile-only stubs and cannot be exercised.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "android/src/com/cyberbasslord/lightforge/WavConverter.java"
BASELINE = "tests/fixtures/wav-converter/WavConverter.java"
BASELINE_COMMIT = "e434d3880c47ebe0e951f01aba366181fd091f96"
BASELINE_SHA256 = "591e9e9ce5bc7bc665c5f3c9920c7cee5cd7fe33c07d8e6677f93e7aba223244"

# These declarations exist only in the temporary host compiler directory. Every
# executable API throws, so the existing test cannot accidentally claim Android
# media or FSEQ coverage. The production AudioImporter source is never rewritten.
STUBS = {
    "android/media/MediaFormat.java": """package android.media;
public class MediaFormat {
 public static final String KEY_MIME="mime",KEY_DURATION="duration",KEY_PCM_ENCODING="pcm-encoding",
  KEY_SAMPLE_RATE="sample-rate",KEY_CHANNEL_COUNT="channel-count",KEY_CHANNEL_MASK="channel-mask";
 public String getString(String k){throw new AssertionError("Android API unavailable");}
 public boolean containsKey(String k){throw new AssertionError("Android API unavailable");}
 public long getLong(String k){throw new AssertionError("Android API unavailable");}
 public int getInteger(String k){throw new AssertionError("Android API unavailable");}
 public void setInteger(String k,int v){throw new AssertionError("Android API unavailable");}
}
""",
    "android/media/MediaExtractor.java": """package android.media;
public class MediaExtractor {
 public static final int SAMPLE_FLAG_ENCRYPTED=2;
 public MediaExtractor(){throw new AssertionError("Android API unavailable");}
 public void setDataSource(String p){throw new AssertionError("Android API unavailable");}
 public int getTrackCount(){throw new AssertionError("Android API unavailable");}
 public MediaFormat getTrackFormat(int i){throw new AssertionError("Android API unavailable");}
 public void selectTrack(int i){throw new AssertionError("Android API unavailable");}
 public int getSampleFlags(){throw new AssertionError("Android API unavailable");}
 public int readSampleData(java.nio.ByteBuffer b,int o){throw new AssertionError("Android API unavailable");}
 public long getSampleTime(){throw new AssertionError("Android API unavailable");}
 public boolean advance(){throw new AssertionError("Android API unavailable");}
 public void release(){throw new AssertionError("Android API unavailable");}
}
""",
    "android/media/MediaCodec.java": """package android.media;
public class MediaCodec {
 public static final int BUFFER_FLAG_END_OF_STREAM=4,INFO_OUTPUT_FORMAT_CHANGED=-2,BUFFER_FLAG_CODEC_CONFIG=2;
 public static class BufferInfo{public int size,flags,offset;public long presentationTimeUs;}
 public static MediaCodec createDecoderByType(String t){throw new AssertionError("Android API unavailable");}
 public void configure(MediaFormat f,Object s,Object c,int flags){throw new AssertionError("Android API unavailable");}
 public void start(){throw new AssertionError("Android API unavailable");}
 public int dequeueInputBuffer(long t){throw new AssertionError("Android API unavailable");}
 public java.nio.ByteBuffer getInputBuffer(int i){throw new AssertionError("Android API unavailable");}
 public void queueInputBuffer(int i,int o,int s,long p,int f){throw new AssertionError("Android API unavailable");}
 public int dequeueOutputBuffer(BufferInfo b,long t){throw new AssertionError("Android API unavailable");}
 public MediaFormat getOutputFormat(){throw new AssertionError("Android API unavailable");}
 public java.nio.ByteBuffer getOutputBuffer(int i){throw new AssertionError("Android API unavailable");}
 public void releaseOutputBuffer(int i,boolean r){throw new AssertionError("Android API unavailable");}
 public void stop(){throw new AssertionError("Android API unavailable");}
 public void release(){throw new AssertionError("Android API unavailable");}
}
""",
    "com/cyberbasslord/lightforge/MainActivity.java": """package com.cyberbasslord.lightforge;
public class MainActivity {
 public static Object verifySequence(java.io.File a,java.io.File b)throws java.io.IOException {
  throw new AssertionError("FSEQ API outside WAV test scope");
 }
}
""",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args: list[str], *, timeout: int = 120) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Host WAV command failed:\n" + result.stdout[-8000:] + result.stderr[-8000:])
    return result.stdout


def java_commands() -> tuple[list[str], list[str]]:
    configured = os.environ.get("LIGHTFORGE_JAVA_HOME") or os.environ.get("JAVA_HOME")
    if configured and (Path(configured) / "bin/javac").is_file():
        return [str(Path(configured) / "bin/java")], [str(Path(configured) / "bin/javac")]
    java, javac = shutil.which("java"), shutil.which("javac")
    if not java:
        raise RuntimeError("A Java 17 host runtime with the Java compiler module is required")
    # Some host images retain the compiler module but omit its javac launcher.
    return [java], [javac] if javac else [java, "-m", "jdk.compiler/com.sun.tools.javac.Main"]


def run(seconds: int | None) -> dict:
    baseline = ROOT / BASELINE
    if sha(baseline) != BASELINE_SHA256:
        raise RuntimeError("Frozen WAV reference differs from its reviewed source SHA-256")
    java, javac = java_commands()
    with tempfile.TemporaryDirectory(prefix="lightforge-wav-block-") as directory:
        temp = Path(directory)
        reference = temp / "FrozenWavConverter.java"
        reference.write_text(re.sub(r"\bWavConverter\b", "FrozenWavConverter", baseline.read_text()))
        stub_paths = []
        for relative, content in STUBS.items():
            path = temp / "stubs" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            stub_paths.append(str(path))
        classes = temp / "classes"
        classes.mkdir()
        command([*javac, "--release", "8", "-encoding", "UTF-8", "-d", str(classes),
                 str(ROOT / SOURCE), str(reference),
                 str(ROOT / "android/src/com/cyberbasslord/lightforge/AudioImporter.java"),
                 str(ROOT / "tests/NativeAudioTest.java"),
                 str(ROOT / "tests/WavConverterBlockWriteTest.java"), *stub_paths])
        native_audio = command([*java, "-cp", str(classes), "com.cyberbasslord.lightforge.NativeAudioTest",
                                str(temp / "existing-native-audio")])
        if "PASS:" not in native_audio:
            raise RuntimeError("Existing NativeAudioTest did not confirm success")
        args = [*java, "-cp", str(classes), "com.cyberbasslord.lightforge.WavConverterBlockWriteTest",
                str(temp / "differential")]
        if seconds is not None:
            args.append(str(seconds))
        result = json.loads(command(args, timeout=180))
    version = subprocess.run([*java, "-version"], capture_output=True, text=True, check=True)
    result.update({
        "scope": "Host WAV conversion and file I/O only; not Android, neural inference, whole-song analysis or release evidence",
        "baseline_commit": BASELINE_COMMIT, "baseline_source_sha256": BASELINE_SHA256,
        "candidate_source_sha256": sha(ROOT / SOURCE),
        "differential_harness_sha256": sha(ROOT / "tests/WavConverterBlockWriteTest.java"),
        "existing_native_audio_test": native_audio.strip(),
        "existing_test_scope": "Actual AudioImporter.readWave; Android codec and FSEQ APIs are throwing compile-only stubs",
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "logical_cpus": os.cpu_count(), "java": (version.stdout + version.stderr).strip()},
        "timing_protocol": "One excluded warmup per variant/rate; three alternating paired complete conversions including finish, file flush and sync; fixture generation and byte comparisons excluded" if seconds else "Timing not requested",
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, help="Optional bounded timing duration per rate (1-120 seconds)")
    parser.add_argument("--output", type=Path, help="Optional host observation JSON path")
    args = parser.parse_args()
    if args.seconds is not None and not 1 <= args.seconds <= 120:
        parser.error("--seconds must be between 1 and 120")
    result = run(args.seconds)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
