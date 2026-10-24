"""Keep model-build bootstrap hardening consistent without changing graph identity."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PINS = 'pip==26.2.1 setuptools==84.1.0 filelock==4.2.1'


class PythonBootstrapSecurityTest(unittest.TestCase):
    def test_every_model_install_has_patched_bootstrap(self):
        expected = {'.github/workflows/verify-v2.yml': 2,
                    '.github/workflows/model-browser-regression.yml': 1,
                    '.github/workflows/publish-release.yml': 1,
                    'BUILD.md': 1}
        for relative, count in expected.items():
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text()
                self.assertEqual(source.count(PINS), count)
                installs = [line.strip() for line in source.splitlines() if 'pip install' in line]
                bootstrap = None
                for index, line in enumerate(installs):
                    if PINS in line:
                        bootstrap = index
                    if 'torch==2.13.0' in line or '-r tools/model-requirements.txt' in line:
                        self.assertIsNotNone(bootstrap, relative)
                        self.assertLess(bootstrap, index)

    def test_bootstrap_packages_do_not_change_exporter_requirements(self):
        names = {line.split('==')[0] for line in
                 (ROOT / 'tools/model-requirements.txt').read_text().splitlines()
                 if line and not line.startswith('#')}
        self.assertFalse(names & {'pip', 'setuptools', 'filelock'})


if __name__ == '__main__':
    unittest.main()
