"""Compile real NativeMdxTask with controllable JNI boundaries and test its lifecycle."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'


class NativeMdxLifecycleTest(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file() and (TOOLS / 'test-json.jar').is_file(), 'Host JDK and pinned test JSON dependency required')
    def test_production_task_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-mdx-lifecycle-') as temporary:
            work = Path(temporary)
            classes = work / 'classes'
            classes.mkdir()
            models = work / 'assets/analysis/models'
            models.mkdir(parents=True)
            graph = b'Controlled native graph fixture; no numerical claim.'
            (models / 'uvr-mdx-voc-ft.onnx').write_bytes(graph)
            (models / 'separator-mdx-model.json').write_text(json.dumps({
                'file': 'uvr-mdx-voc-ft.onnx', 'bytes': len(graph),
                'sha256': hashlib.sha256(graph).hexdigest(), 'sampleRate': 44100,
                'frequencyBins': 3072, 'frames': 256, 'nFFT': 7680, 'hop': 1024, 'channels': 2,
            }))
            sources = [ROOT / 'android/src/com/cyberbasslord/lightforge' / (name + '.java')
                       for name in ['NativeMdxTask', 'NativeRuntimeGuard']]
            sources += sorted((ROOT / 'tests/native-mdx-host').rglob('*.java'))
            sources += sorted((ROOT / 'tests/native-mdx-lifecycle').rglob('*.java'))
            sources += [ROOT / 'tests/NativeMdxLifecycleTest.java']
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8',
                                       '-cp', str(TOOLS / 'test-json.jar'), '-d', str(classes), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', os.pathsep.join([str(classes), str(TOOLS / 'test-json.jar')]),
                                     'com.cyberbasslord.lightforge.NativeMdxLifecycleTest', str(work / 'data'), str(work / 'assets')],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('production NativeMdxTask lifecycle checks', result.stdout)


if __name__ == '__main__':
    if not (JAVA / 'javac').is_file() or not (TOOLS / 'test-json.jar').is_file():
        raise SystemExit('Required lifecycle gate needs bootstrap_toolchain.py and bootstrap_testdeps.py first.')
    unittest.main()
