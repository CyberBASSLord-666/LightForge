import os
import pathlib
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = pathlib.Path(os.environ.get("LIGHTFORGE_TOOLCHAIN_DIR", ROOT.parent / "toolchain"))
JAVA = pathlib.Path(os.environ.get("LIGHTFORGE_JAVA_HOME", TOOLS / "jdk17")) / "bin"
ANDROID = "{http://schemas.android.com/apk/res/android}"


class NativeGamePassageCleanupTest(unittest.TestCase):
    def test_application_hook_precedes_single_process_components(self):
        manifest = ET.parse(ROOT / "android/AndroidManifest.xml").getroot()
        application = manifest.find("application")
        self.assertEqual(application.get(ANDROID + "name"), ".LightForgeApplication")
        self.assertTrue(all(ANDROID + "process" not in element.attrib for element in manifest.iter()))
        self.assertEqual(application.findall("provider"), [])
        self.assertEqual(application.find("service").get(ANDROID + "name"), ".AnalysisService")
        self.assertEqual(application.find("activity").get(ANDROID + "name"), ".MainActivity")
        task = (ROOT / "android/src/com/cyberbasslord/lightforge/NativeGameTask.java").read_text()
        self.assertNotIn("NativeGamePassageCleanup.recover", task)

    @unittest.skipUnless((JAVA / "javac").is_file(), "Host JDK required")
    def test_identifiable_orphans_only_and_once_per_process(self):
        sources = [ROOT / f"android/src/com/cyberbasslord/lightforge/{name}.java"
                   for name in ("LightForgeApplication", "NativeGamePassageCleanup")]
        sources += sorted((ROOT / "tests/native-game-cache-host").rglob("*.java"))
        sources += [ROOT / "tests/NativeGamePassageCleanupTest.java"]
        with tempfile.TemporaryDirectory(prefix="lightforge-game-cache-classes-") as directory:
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-encoding", "UTF-8",
                                       "-d", directory, *map(str, sources)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            for arguments in ([], ["failure-hook"]):
                result = subprocess.run([str(JAVA / "java"), "-cp", directory,
                                         "com.cyberbasslord.lightforge.NativeGamePassageCleanupTest", *arguments],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PASS: process-start-only", result.stdout)


if __name__ == "__main__":
    if not (JAVA / "javac").is_file():
        raise SystemExit("Required cleanup gate needs bootstrap_toolchain.py first.")
    unittest.main()
