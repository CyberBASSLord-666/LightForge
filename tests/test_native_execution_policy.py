"""Pure Java scheduling selection, output-quality admission, and durable cache proof."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'


class NativeExecutionPolicyTest(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file(), 'Host JDK required')
    def test_selection_quality_and_atomic_persistence(self):
        sources = [ROOT / 'android/src/com/cyberbasslord/lightforge/NativeExecutionPolicy.java',
                   ROOT / 'tests/NativeExecutionPolicyTest.java']
        with tempfile.TemporaryDirectory(prefix='lightforge-native-policy-') as classes:
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', classes, *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', classes,
                                     'com.cyberbasslord.lightforge.NativeExecutionPolicyTest'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('bounded native execution policy checks', result.stdout)


if __name__ == '__main__':
    unittest.main()
