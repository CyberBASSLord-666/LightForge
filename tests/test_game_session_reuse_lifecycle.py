"""Executed Java tests of host reuse ownership; controlled native boundaries only."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('game_reuse_lifecycle', ROOT / 'tools/game_benchmark/session_reuse_lifecycle/run.py')
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)
JAVA = Path(os.environ.get('LIGHTFORGE_JAVA_HOME', '/usr/lib/jvm/java-17-openjdk-amd64'))
DEPENDENCIES = Path(os.environ.get('LIGHTFORGE_LIFECYCLE_DEPS', ROOT.parent / 'reuse-lifecycle-deps'))


class GameSessionReuseLifecycleTest(unittest.TestCase):
    def test_fixture_preserves_generated_lifecycle_and_numerics(self):
        original = lifecycle.reuse.game.SOURCE.read_text()
        for variant in lifecycle.reuse.VARIANTS:
            candidate = lifecycle.reuse.generate(original, variant, source_samples=lifecycle.SOURCE_SAMPLES)
            fixture = lifecycle.fixture_source(candidate)
            prepare = '    private void prepareModels('
            self.assertEqual(candidate.split(prepare)[0], fixture.split(prepare)[0])
            self.assertIn('ai.onnxruntime.Control.prepare();', fixture)

    @unittest.skipUnless((JAVA / 'bin/java').is_file() and (DEPENDENCIES / 'test-json.jar').is_file() and
                         (DEPENDENCIES / 'onnxruntime-1.25.1.jar').is_file(), 'Java compiler module and pinned ORT/JSON JARs required')
    def test_executed_lifecycle_both_variants(self):
        with tempfile.TemporaryDirectory(prefix='game-reuse-lifecycle-') as temporary:
            receipt = lifecycle.execute(Path(temporary) / 'evidence', JAVA, DEPENDENCIES)
            self.assertEqual(receipt['status'], 'PASSED_MOCK_LIFECYCLE_AND_REAL_API_COMPILATION')
            self.assertEqual(set(receipt['casesPerVariant']), {'cpu_all', 'cuda_basic'})
            self.assertTrue(all(count >= 40 for count in receipt['casesPerVariant'].values()))
            self.assertTrue(receipt['realOrtApiCompiled'])
            self.assertFalse(receipt['nativeJniLifecycleQualified'])
            self.assertFalse(receipt['qualityApproved'])
            self.assertFalse(receipt['benchmarkTimingAdmitted'])


if __name__ == '__main__':
    unittest.main()
