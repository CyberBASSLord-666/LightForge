"""Run the actual companion serializer without building an APK or executing inference."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get("LIGHTFORGE_TOOLCHAIN_DIR", ROOT.parent / "toolchain"))
JAVA = Path(os.environ.get("LIGHTFORGE_JAVA_HOME", TOOLS / "jdk17")) / "bin"
DEPS = [TOOLS / "test-json.jar", TOOLS / "onnx/onnxruntime-1.25.1.jar", TOOLS / "android-sdk/platforms/android-35/android.jar"]


class ProbeCandidateEvidenceTests(unittest.TestCase):
    @unittest.skipUnless((JAVA / "javac").is_file() and all(path.is_file() for path in DEPS), "Pinned Java compile dependencies required")
    def test_real_companion_json_transport_is_separate_and_bounded(self):
        with tempfile.TemporaryDirectory(prefix="lightforge-candidate-evidence-") as temporary:
            work = Path(temporary)
            stub = work / "com/cyberbasslord/lightforge/AppDiagnostics.java"
            stub.parent.mkdir(parents=True)
            stub.write_text("package com.cyberbasslord.lightforge; public final class AppDiagnostics { "
                            "public static void initialize(android.content.Context c){} "
                            "public static void log(android.content.Context c,String l,String t,String m){} "
                            "public static boolean flush(long t){return true;} }\n")
            sources = [ROOT / "android/src/com/cyberbasslord/lightforge" / (name + ".java") for name in
                       ("NativeDeux", "NativeDeuxTransform", "NativeExecutionPolicy", "NativePassagePolicy", "NativeInferenceProfile")]
            sources += [ROOT / "qa/inference-device-probe/src/com/cyberbasslord/lightforge/ProbeRunner.java",
                        ROOT / "tests/ProbeCandidateEvidenceTest.java", stub]
            classpath = os.pathsep.join(map(str, DEPS))
            result = subprocess.run([str(JAVA / "javac"), "--release", "8", "-encoding", "UTF-8", "-cp", classpath,
                                     "-d", str(work), *map(str, sources)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(JAVA / "java"), "-cp", os.pathsep.join([str(work), classpath]),
                                     "com.cyberbasslord.lightforge.ProbeCandidateEvidenceTest"], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS: bounded candidate JSON", result.stdout)


if __name__ == "__main__":
    unittest.main()
