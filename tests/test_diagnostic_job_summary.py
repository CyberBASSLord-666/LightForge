"""Compile and execute the production compact diagnostics store on the host JVM."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get("LIGHTFORGE_TOOLCHAIN_DIR", ROOT.parent / "toolchain"))
JAVA = Path(os.environ.get("LIGHTFORGE_JAVA_HOME", TOOLS / "jdk17")) / "bin"


class DiagnosticJobSummaryTests(unittest.TestCase):
    def test_export_and_profile_are_bound_to_same_safe_job_reference(self):
        diagnostics = (ROOT / "android/src/com/cyberbasslord/lightforge/AppDiagnostics.java").read_text()
        passage = (ROOT / "android/src/com/cyberbasslord/lightforge/NativePassageTask.java").read_text()
        self.assertIn('append(DiagnosticJobSummary.reference(id))', diagnostics)
        self.assertIn('AppDiagnostics.profile(context,ownerJobId,snapshot)', passage)
        self.assertIn('DURABLE ANALYSIS SUMMARIES', diagnostics)

    @unittest.skipUnless((JAVA / "javac").is_file(), "Host JDK required")
    def test_durable_production_store(self):
        with tempfile.TemporaryDirectory(prefix="lightforge-summary-classes-") as classes:
            sources = [ROOT / "android/src/com/cyberbasslord/lightforge" / (name + ".java")
                       for name in ("DiagnosticJobSummary", "DiagnosticLog", "NativeInferenceProfile")]
            sources += [ROOT / "tests/DiagnosticJobSummaryTest.java", ROOT / "tests/NativeInferenceProfileTest.java"]
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-encoding", "UTF-8", "-d", classes,
                                       *map(str, sources)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            for test in ("DiagnosticJobSummaryTest", "NativeInferenceProfileTest"):
                result = subprocess.run([str(JAVA / "java"), "-cp", classes, "com.cyberbasslord.lightforge." + test],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # A host build can have Android APIs on its classpath even though they are stubs.
            # The real host process clock must remain usable when that reflected method throws.
            stub = Path(classes) / "stub/android/os/Process.java"
            stub.parent.mkdir(parents=True)
            stub.write_text('package android.os; public final class Process { '
                            'public static long getElapsedCpuTime(){throw new RuntimeException("Stub!");} }\n')
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", classes, str(stub)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(JAVA / "java"), "-cp", classes,
                                     "com.cyberbasslord.lightforge.NativeInferenceProfileTest", "require-process-clock"],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if not (JAVA / "javac").is_file():
        raise SystemExit("Required diagnostics gate needs bootstrap_toolchain.py first.")
    unittest.main()
