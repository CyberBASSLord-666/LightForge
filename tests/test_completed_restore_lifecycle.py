"""Run production completed-preview monitor across background/resume boundaries."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get("LIGHTFORGE_TOOLCHAIN_DIR", ROOT.parent / "toolchain"))
JAVA = Path(os.environ.get("LIGHTFORGE_JAVA_HOME", TOOLS / "jdk17")) / "bin"


class CompletedRestoreLifecycleTests(unittest.TestCase):
    def test_activity_wires_visibility_before_loading_and_at_lifecycle_boundaries(self):
        source = (ROOT / "android/src/com/cyberbasslord/lightforge/MainActivity.java").read_text()
        self.assertIn("completedRestoreMonitor.setForeground(foreground);\n        createPreview();", source)
        resume = source.split("@Override protected void onResume()", 1)[1].split("@Override", 1)[0]
        pause = source.split("@Override protected void onPause()", 1)[1].split("@Override", 1)[0]
        self.assertIn("completedRestoreMonitor.setForeground(hasWindowFocus())", resume)
        self.assertIn("completedRestoreMonitor.setForeground(false)", pause)
        focus = source.split("@Override public void onWindowFocusChanged(", 1)[1].split("@Override", 1)[0]
        self.assertIn("completedRestoreMonitor.setForeground(foreground&&hasFocus)", focus)

    def test_legacy_draw_callback_and_retired_observers_are_removed_after_draw(self):
        source = (ROOT / "android/src/com/cyberbasslord/lightforge/MainActivity.java").read_text()
        self.assertIn("listener[0]=new DeferredDrawCallback(task->completedRestoreHandler.post(task),()->{", source)
        cleanup = source.split("private void clearCompletedRestoreVisualProofLocked()", 1)[1].split("static final class DeferredDrawCallback", 1)[0]
        self.assertIn("completedRestoreHandler.post(()->{", cleanup)
        self.assertIn("tree.removeOnDrawListener(listener)", cleanup)

    @unittest.skipUnless((JAVA / "javac").is_file(), "Pinned JDK required")
    def test_actual_monitor_foreground_budgets_and_late_callbacks(self):
        with tempfile.TemporaryDirectory(prefix="lightforge-completed-restore-") as temporary:
            compiled = subprocess.run([
                str(JAVA / "javac"), "--release", "8", "-encoding", "UTF-8", "-d", temporary,
                str(ROOT / "android/src/com/cyberbasslord/lightforge/CompletedRestoreMonitor.java"),
                str(ROOT / "tests/CompletedRestoreLifecycleTest.java"),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([
                str(JAVA / "java"), "-cp", temporary,
                "com.cyberbasslord.lightforge.CompletedRestoreLifecycleTest",
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("production completed-restore lifecycle checks", result.stdout)


if __name__ == "__main__":
    unittest.main()
