#!/usr/bin/env python3
"""Keep the native producer compatible with sealed verification evidence."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "tests/verify_native_release.py").read_text(encoding="utf-8")


class NativeVerificationReceiptContractTest(unittest.TestCase):
    def test_native_receipt_always_has_an_explicit_errors_list(self):
        self.assertIn("checks=[], errors=[]", SOURCE)
        self.assertIn("receipt['errors'].append(str(error))", SOURCE)


if __name__ == "__main__":
    unittest.main()
