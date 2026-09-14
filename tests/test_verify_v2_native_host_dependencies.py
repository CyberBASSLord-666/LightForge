"""Guard the host-JVM dependency needed by the native MDX evidence compiler."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/verify-v2.yml"
SESSION = 'test -n "$LIGHTFORGE_EVIDENCE_SESSION"'
BOOTSTRAP = "python3 tools/bootstrap_testdeps.py"
COMPARE = "python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/compare-native-mdx.py"
DOWNSTREAM = "node qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-mdx-downstream.cjs"
PROFILE = "python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-native-inference-profile.py"
ANALYSIS = "python3 qa/release-${{ env.LIGHTFORGE_RELEASE }}/verify-analysis.py"


def assert_native_evidence_order(text):
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
        with self.assertRaises(AssertionError):
            assert_native_evidence_order(text.replace(BOOTSTRAP + "\n", "", 1))
        reversed_order = text.replace(
            BOOTSTRAP + "\n          " + COMPARE,
            COMPARE + "\n          " + BOOTSTRAP,
            1,
        )
        with self.assertRaises(AssertionError):
            assert_native_evidence_order(reversed_order)


if __name__ == "__main__":
    unittest.main()

