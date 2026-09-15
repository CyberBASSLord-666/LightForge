"""Run the real Node capture module's protocol/security tests in verify_v2."""
from pathlib import Path
import subprocess
import unittest


class LockedAppCaptureTests(unittest.TestCase):
    def test_capture_protocol(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "--test", str(root / "tests/app-capture.test.cjs")],
            cwd=root, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=60, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-16000:])


if __name__ == "__main__":
    unittest.main()
