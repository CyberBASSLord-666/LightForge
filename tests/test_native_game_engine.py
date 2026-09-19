"""Compile and exercise production NativeGame's bounded, non-inference contracts."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'
DEPENDENCIES = [TOOLS / 'test-json.jar', TOOLS / 'onnx/onnxruntime-1.25.1.jar',
                TOOLS / 'android-sdk/platforms/android-35/android.jar']


class NativeGameEngineTest(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file() and all(path.is_file() for path in DEPENDENCIES),
                         'Host JDK, pinned JSON, ORT and Android compile dependencies required')
    def test_production_engine_contracts_without_model_inference(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-game-contract-') as folder:
            classes = Path(folder) / 'classes'
            classes.mkdir()
            classpath = os.pathsep.join(map(str, DEPENDENCIES))
            sources = [ROOT / 'android/src/com/cyberbasslord/lightforge/NativeGame.java',
                       ROOT / 'tests/NativeGameTest.java']
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8',
                                       '-cp', classpath, '-d', str(classes), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', os.pathsep.join([str(classes), classpath]),
                                     'com.cyberbasslord.lightforge.NativeGameTest',
                                     str(ROOT / 'web/analysis/models/game/manifest.json')],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('pre-runtime cancellation checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
