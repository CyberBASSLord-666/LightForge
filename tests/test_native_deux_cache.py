"""Exercise production preflight with tiny checked graph assets, without an APK or inference."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain'))
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', TOOLS / 'jdk17')) / 'bin'
DEPENDENCIES = [TOOLS / 'test-json.jar', TOOLS / 'onnx/onnxruntime-1.25.1.jar']


class NativeDeuxCacheTest(unittest.TestCase):
    @unittest.skipUnless((JAVA / 'javac').is_file() and all(path.is_file() for path in DEPENDENCIES),
                         'Host JDK and pinned JSON/ORT compile dependencies required')
    def test_production_common_preparation_without_neural_execution(self):
        with tempfile.TemporaryDirectory(prefix='lightforge-deux-cache-') as temporary:
            work = Path(temporary)
            classes = work / 'classes'
            classes.mkdir()
            # Reuse the existing file-backed Context and AssetManager adapters.
            sources = [ROOT / 'tests/native-mdx-host' / name for name in [
                'android/content/Context.java', 'android/content/res/AssetManager.java',
                'android/content/pm/PackageManager.java', 'android/content/pm/PackageInfo.java']]
            stubs = {
                'android/os/Build.java': 'package android.os; public final class Build {'
                    ' public static final String FINGERPRINT="cache-test",MANUFACTURER="test",MODEL="test";'
                    ' public static final String[] SUPPORTED_ABIS={"test"}; }',
                'android/app/ActivityManager.java': 'package android.app; public final class ActivityManager {'
                    ' public static final class MemoryInfo {public long availMem,threshold; public boolean lowMemory;}'
                    ' public void getMemoryInfo(MemoryInfo info){throw new AssertionError("No memory admission expected in cache test");} }',
                'com/cyberbasslord/lightforge/AppDiagnostics.java': 'package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
                    ' public static void log(android.content.Context c,String l,String s,String m){}'
                    ' public static boolean flush(long timeout){return true;} }',
            }
            for name, content in stubs.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content + '\n')
                sources.append(path)
            sources += [ROOT / 'android/src/com/cyberbasslord/lightforge' / (name + '.java') for name in
                        ['NativeDeux', 'NativeDeuxTransform', 'NativeInferenceProfile', 'NativeExecutionPolicy', 'NativePassagePolicy']]
            sources.append(ROOT / 'tests/NativeDeuxCacheTest.java')
            classpath = os.pathsep.join(map(str, DEPENDENCIES))
            compiled = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-encoding', 'UTF-8',
                                       '-cp', classpath, '-d', str(classes), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', os.pathsep.join([str(classes), classpath]),
                                     'com.cyberbasslord.lightforge.NativeDeuxCacheTest', str(work / 'data'),
                                     str(ROOT / 'web/analysis/models/deux/manifest.json')],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('no-double-count checks passed; no neural execution', result.stdout)

    def test_common_preflight_finishes_before_any_comparison_or_nomination_timer(self):
        source = (ROOT / 'android/src/com/cyberbasslord/lightforge/NativeDeux.java').read_text()
        predict = source[source.index('synchronized void predict(File audio,long startSample,File output,Listener listener,Cancellation cancellation,'):]
        preflight = predict.index('preflightCache(check,profile);')
        timed = predict.index('profile.addPreflight(NativeInferenceProfile.elapsed(preflightStarted))')
        self.assertLess(preflight, timed)
        self.assertLess(timed, predict.index('nominate(audio,startSample,check,profile);'))
        self.assertLess(timed, predict.index('long pairStarted=System.nanoTime();'))


if __name__ == '__main__':
    unittest.main()
