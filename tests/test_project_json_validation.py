"""Ordinary host storage validation with actual pinned AOSP JsonReader, not SDK stubs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
if __package__:
    from .project_json_host import compile_support
else:
    from project_json_host import compile_support

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'
DEPS = [TOOLS / 'test-json.jar', TOOLS / 'android-sdk/platforms/android-35/android.jar',
        TOOLS / 'onnx/onnxruntime-1.25.1.jar']


class ProjectJsonValidationTests(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file() and all(p.is_file() for p in DEPS), 'Pinned host dependencies required')
    def test_ordinary_validation_and_revision_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-json-validation-') as temporary:
            work = Path(temporary)
            host = compile_support(JAVA / 'javac', work / 'aosp-host')
            r = work / 'R.java'
            r.write_text('package com.cyberbasslord.lightforge; final class R { static final class drawable { static final int ic_analysis=1; } }')
            production = ROOT / 'android/src/com/cyberbasslord/lightforge/ProjectStore.java'
            original = production.read_bytes()
            for limit in (64, 4):
                classes = work / ('classes-' + str(limit)); classes.mkdir()
                sources = sorted((ROOT / 'android/src').rglob('*.java'))
                if limit == 4:
                    # Explicit test-only boundary configuration, not a production-byte-identity claim.
                    text = original.decode()
                    declaration = 'static final int MAX_JSON_DEPTH = 64;'
                    self.assertEqual(text.count(declaration), 1)
                    configured = work / 'ProjectStore.java'
                    configured.write_text(text.replace(declaration, 'static final int MAX_JSON_DEPTH = 4;'))
                    sources = [configured if p == production else p for p in sources]
                sources += [r, ROOT / 'tests/ProjectJsonValidationTest.java', ROOT / 'tests/ProjectStoreTest.java']
                compilepath = os.pathsep.join(map(str, DEPS))
                compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8', '-cp', compilepath,
                                           '-d', str(classes), *map(str, sources)], capture_output=True, text=True, timeout=90)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                runtimepath = os.pathsep.join(map(str, [host, classes, *DEPS]))
                for name in ('ProjectJsonValidationTest', 'ProjectStoreTest'):
                    run = subprocess.run([str(JAVA / 'java'), '-cp', runtimepath,
                                          'com.cyberbasslord.lightforge.' + name, str(work / (name + '-' + str(limit)))],
                                         capture_output=True, text=True, timeout=45)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn('PASS:', run.stdout)
                    print(run.stdout.strip())
            self.assertEqual(production.read_bytes(), original, 'Production source must stay unchanged')


if __name__ == '__main__':
    unittest.main()
