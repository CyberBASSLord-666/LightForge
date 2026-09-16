"""Exercise real NativePassageTask shutdown with controlled native/executor boundaries."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'


class NativePassageLifecycleTest(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file() and (TOOLS / 'test-json.jar').is_file(),
                         'Host JDK and pinned test JSON dependency required')
    def test_production_task_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-passage-lifecycle-') as temporary:
            work = Path(temporary)
            classes = work / 'classes'
            classes.mkdir()
            clock = work / 'android/os/SystemClock.java'
            clock.parent.mkdir(parents=True)
            clock.write_text('package android.os; public final class SystemClock { '
                             'public static long elapsedRealtime(){return System.nanoTime()/1000000L;} }\n')
            sources = [ROOT / 'android/src/com/cyberbasslord/lightforge' / (name + '.java')
                       for name in ('NativePassageTask', 'NativeRuntimeGuard', 'NativeInferenceProfile')]
            sources += sorted((ROOT / 'tests/native-mdx-host/android').rglob('*.java'))
            sources += [ROOT / 'tests/native-mdx-host/com/cyberbasslord/lightforge/AnalysisJobStore.java',
                        ROOT / 'tests/NativePassageLifecycleTest.java', clock]
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8',
                                       '-cp', str(TOOLS / 'test-json.jar'), '-d', str(classes), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', os.pathsep.join([str(classes), str(TOOLS / 'test-json.jar')]),
                                     'com.cyberbasslord.lightforge.NativePassageLifecycleTest', str(work / 'data')],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('production NativePassageTask lifecycle checks', result.stdout)


if __name__ == '__main__':
    if not (JAVA / 'javac').is_file() or not (TOOLS / 'test-json.jar').is_file():
        raise SystemExit('Required lifecycle gate needs bootstrap_toolchain.py and bootstrap_testdeps.py first.')
    unittest.main()
