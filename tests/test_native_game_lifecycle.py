"""Compile the production GAME task with a controlled engine and test real ownership/retirement."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'


class NativeGameLifecycleTest(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file() and (TOOLS / 'test-json.jar').is_file(),
                         'Host JDK and pinned test JSON dependency required')
    def test_production_task_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-game-lifecycle-') as temporary:
            work = Path(temporary)
            classes = work / 'classes'
            classes.mkdir()
            sources = [ROOT / 'android/src/com/cyberbasslord/lightforge' / (name + '.java')
                       for name in ('NativeGameTask', 'NativeRuntimeGuard')]
            sources += sorted((ROOT / 'tests/native-mdx-host/android').rglob('*.java'))
            sources += [ROOT / 'tests/native-mdx-host/com/cyberbasslord/lightforge/NativeDeux.java',
                        ROOT / 'tests/NativeGameLifecycleTest.java']
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8',
                                       '-cp', str(TOOLS / 'test-json.jar'), '-d', str(classes), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            command = [str(JAVA / 'java'), '-cp', os.pathsep.join([str(classes), str(TOOLS / 'test-json.jar')]),
                       'com.cyberbasslord.lightforge.NativeGameLifecycleTest']
            for mode in ('normal', 'throw', 'unconfirmed'):
                # Unknown JNI ownership is intentionally unrecoverable inside a
                # process. Each fatal control gets its own fresh JVM.
                arguments = [str(work / mode)] + ([] if mode == 'normal' else [mode])
                result = subprocess.run(command + arguments, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                expected = ('production NativeGameTask lifecycle checks' if mode == 'normal'
                            else 'native retirement failure blocks fallback until process restart')
                self.assertIn(expected, result.stdout)


if __name__ == '__main__':
    if not (JAVA / 'javac').is_file() or not (TOOLS / 'test-json.jar').is_file():
        raise SystemExit('Required lifecycle gate needs bootstrap_toolchain.py and bootstrap_testdeps.py first.')
    unittest.main()
