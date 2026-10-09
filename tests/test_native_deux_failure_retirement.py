"""Exercise real production retirement and failure classification without neural inference."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'
DEPS = [TOOLS / 'test-json.jar', TOOLS / 'android-sdk/platforms/android-35/android.jar',
        TOOLS / 'onnx/onnxruntime-1.25.1.jar']


class NativeDeuxFailureRetirementTest(unittest.TestCase):
    def test_device_probe_uses_production_classifier(self):
        probe = (ROOT / 'qa/inference-device-probe/src/com/cyberbasslord/lightforge/ProbeRunner.java').read_text()
        self.assertIn('if (!NativeDeux.cleanCancellation(failure)) uncertainNativeCleanup = true;', probe)
        self.assertNotIn('failure.getSuppressed().length', probe)

    @unittest.skipUnless((JAVA / 'javac').is_file() and all(p.is_file() for p in DEPS), 'Pinned host dependencies required')
    def test_actual_production_helper(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-deux-retirement-') as temporary:
            work = Path(temporary)
            stub = work / 'AppDiagnostics.java'
            stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
                            'public static void log(android.content.Context c,String l,String s,String m){}'
                            'public static boolean flush(long timeout){return true;}}\n')
            sources = [ROOT / 'android/src/com/cyberbasslord/lightforge' / (name + '.java') for name in
                       ('NativeDeux', 'NativeDeuxTransform', 'NativeInferenceProfile', 'NativeExecutionPolicy', 'NativePassagePolicy')]
            sources += [stub, ROOT / 'tests/NativeDeuxFailureRetirementTest.java']
            before = {str(p): p.read_bytes() for p in sources}
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',
                                       os.pathsep.join(map(str, DEPS)), '-d', str(work), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(JAVA / 'java'), '-cp', os.pathsep.join(map(str, [work, *DEPS])),
                                  'com.cyberbasslord.lightforge.NativeDeuxFailureRetirementTest'],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('PASS: production temporal retirement preserves every failure', run.stdout)
            self.assertEqual(before, {str(p): p.read_bytes() for p in sources}, 'Sources changed during verification')


if __name__ == '__main__':
    if not (JAVA / 'javac').is_file() or not all(p.is_file() for p in DEPS):
        raise SystemExit('Required host gate needs the pinned toolchain and native runtime dependencies.')
    unittest.main()
