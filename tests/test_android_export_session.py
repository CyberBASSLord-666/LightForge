"""Compile production Android sources and execute export ownership/state regressions."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get("LIGHTFORGE_TOOLCHAIN_DIR", ROOT.parent / "toolchain"))
JAVA = Path(os.environ.get("LIGHTFORGE_JAVA_HOME", TOOLS / "jdk17")) / "bin"
DEPS = [TOOLS / "test-json.jar", TOOLS / "android-sdk/platforms/android-35/android.jar",
        TOOLS / "onnx/onnxruntime-1.25.1.jar"]


class AndroidExportSessionTests(unittest.TestCase):
    def test_bridge_rejects_stale_append_without_aborting_current_owner(self):
        source = (ROOT / "android/src/com/cyberbasslord/lightforge/MainActivity.java").read_text()
        append = source.split("public boolean appendExport(", 1)[1].split("public void finishExport(", 1)[0]
        self.assertIn('if(activeExport==null||!activeExport.accepts(id)){error(new IOException("The export session has expired."));return false;}', append)
        finish = source.split("public void finishExport(", 1)[1].split("public void shareExport(", 1)[0]
        self.assertLess(finish.index("if(session.finishing)return;"), finish.index("worker.execute("))

    @unittest.skipUnless((JAVA / "javac").is_file() and all(p.is_file() for p in DEPS), "Pinned Android compile dependencies required")
    def test_actual_production_session(self):
        with tempfile.TemporaryDirectory(prefix="lightforge-export-lifecycle-") as temporary:
            work = Path(temporary)
            # R only names packaged assets here; no substitute production logic.
            r = work / "R.java"
            r.write_text("package com.cyberbasslord.lightforge; final class R { static final class drawable { static final int ic_analysis=1; } }")
            sources = sorted((ROOT / "android/src").rglob("*.java")) + [r, ROOT / "tests/AndroidExportSessionTest.java", ROOT / "tests/AndroidResourceCleanupTest.java"]
            classpath = os.pathsep.join(map(str, DEPS))
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-encoding", "UTF-8", "-cp", classpath,
                                       "-d", str(work), *map(str, sources)], capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(JAVA / "java"), "-cp", os.pathsep.join([str(work), classpath]),
                                  "com.cyberbasslord.lightforge.AndroidExportSessionTest"], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("production export session lifecycle checks", run.stdout)
            run = subprocess.run([str(JAVA / "java"), "-cp", os.pathsep.join([str(work), classpath]),
                                  "com.cyberbasslord.lightforge.AndroidResourceCleanupTest"], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("production Android resource cleanup checks", run.stdout)


if __name__ == "__main__":
    unittest.main()
