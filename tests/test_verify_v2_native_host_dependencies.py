"""Guard the host-JVM dependency needed by the native MDX evidence compiler."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/verify-v2.yml"
SESSION = 'test -n "$LIGHTFORGE_EVIDENCE_SESSION"'
BOOTSTRAP = "python3 tools/bootstrap_testdeps.py"
COMPARE = "python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/compare-native-mdx.py"
DOWNSTREAM = "node qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-mdx-downstream.cjs"
PROFILE = "python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-native-inference-profile.py"
ANALYSIS = "python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-analysis.py"


def job(text, name):
    matches = re.findall(r'(?ms)^  ' + re.escape(name) + r':\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)', text)
    if len(matches) != 1:
        raise AssertionError('Expected exactly one workflow job: ' + name)
    return matches[0]


def assert_native_evidence_order(text):
    text = job(text, 'verify')
    commands = (SESSION, BOOTSTRAP, COMPARE, DOWNSTREAM, PROFILE, ANALYSIS)
    positions = []
    for command in commands:
        if text.count(command) != 1:
            raise AssertionError("native evidence command must appear exactly once: " + command)
        positions.append(text.index(command))
    if positions != sorted(positions):
        raise AssertionError("bootstrap_testdeps must precede the native MDX javac comparison")


class VerifyV2NativeHostDependenciesTest(unittest.TestCase):
    def test_native_json_host_dependency_is_bootstrapped_before_javac(self):
        assert_native_evidence_order(WORKFLOW.read_text(encoding="utf-8"))

    def test_guard_rejects_missing_or_reversed_bootstrap(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        consumer = job(text, 'verify')
        missing = text.replace(consumer, consumer.replace(BOOTSTRAP + "\n", "", 1), 1)
        with self.assertRaises(AssertionError):
            assert_native_evidence_order(missing)
        reversed_consumer = consumer.replace(
            BOOTSTRAP + "\n          " + COMPARE,
            COMPARE + "\n          " + BOOTSTRAP,
            1,
        )
        with self.assertRaises(AssertionError):
            assert_native_evidence_order(text.replace(consumer, reversed_consumer, 1))
        duplicated = consumer.replace(BOOTSTRAP, BOOTSTRAP + "\n          " + BOOTSTRAP, 1)
        with self.assertRaises(AssertionError):
            assert_native_evidence_order(text.replace(consumer, duplicated, 1))

    def test_producer_bootstrap_cannot_mask_missing_consumer_dependency(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        producer = job(text, 'host-campaign')
        self.assertEqual(producer.count(BOOTSTRAP), 1)
        self.assertLess(producer.index('python3 tools/bootstrap_toolchain.py'), producer.index(BOOTSTRAP))
        self.assertLess(producer.index(BOOTSTRAP), producer.index('--phase prepare'))
        self.assertNotIn(SESSION, producer)
        # Removing the independent producer dependency must not alter the
        # consumer guard; deleting the consumer one still fails above.
        changed = text.replace(producer, producer.replace(BOOTSTRAP + "\n", "", 1), 1)
        assert_native_evidence_order(changed)


if __name__ == "__main__":
    unittest.main()

