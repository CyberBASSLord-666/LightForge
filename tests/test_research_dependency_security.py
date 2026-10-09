"""Research dependency/security contracts; these do not certify model parity."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / 'research/upstream/vocal-candidates/EfficientAT'


def loader(torch):
    torch.serialization = SimpleNamespace(get_safe_globals=Mock(return_value=[]))
    spec = importlib.util.spec_from_file_location('research_safe_loading', RESEARCH / 'helpers/safe_loading.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'torch': torch}):
        spec.loader.exec_module(module)
    return module


class ResearchDependencySecurityTest(unittest.TestCase):
    def test_attention_parser_pin_is_patched_without_runtime_upgrade(self):
        pins = dict(line.split("==") for line in (ROOT / "research/inference-2.4.1/attention/requirements.txt").read_text().splitlines() if line)
        self.assertEqual(pins["onnx"], "1.22.0")
        self.assertEqual(pins["onnxruntime"], "1.25.1")

    def test_coordinated_reviewed_family(self):
        pins = dict(line.split('==') for line in (RESEARCH / 'requirements.txt').read_text().splitlines()
                    if line and not line.startswith('#'))
        self.assertEqual({name: pins[name] for name in ('torch', 'torchaudio', 'torchvision', 'scikit-learn')},
                         {'torch': '2.13.0', 'torchaudio': '2.11.0', 'torchvision': '0.28.0', 'scikit-learn': '1.5.2'})

    def test_old_or_prerelease_torch_rejected_before_loading(self):
        for version in ('1.13.0', '2.9.1', '2.12.1', '2.13.0rc1', '2.13.0.dev1', 'unknown'):
            with self.subTest(version=version):
                torch = SimpleNamespace(__version__=version, load=Mock(), hub=SimpleNamespace(load_state_dict_from_url=Mock()))
                module = loader(torch)
                with self.assertRaises(RuntimeError):
                    module.load_tensor_file('untrusted.pt')
                with self.assertRaises(RuntimeError):
                    module.load_state_dict_from_url('https://example.invalid/test.pt', model_dir='resources')
                torch.load.assert_not_called()
                torch.hub.load_state_dict_from_url.assert_not_called()

    def test_explicit_restricted_loading_cpu_and_no_fallback(self):
        torch = SimpleNamespace(__version__='2.13.0+cpu', load=Mock(side_effect=ValueError('blocked pickle')),
                                hub=SimpleNamespace(load_state_dict_from_url=Mock(side_effect=ValueError('blocked pickle'))))
        module = loader(torch)
        with self.assertRaisesRegex(ValueError, 'blocked pickle'):
            module.load_tensor_file('checkpoint.pt')
        torch.load.assert_called_once_with('checkpoint.pt', map_location='cpu', weights_only=True)
        with self.assertRaisesRegex(ValueError, 'blocked pickle'):
            module.load_state_dict_from_url('https://example.invalid/test.pt', model_dir='resources')
        torch.hub.load_state_dict_from_url.assert_called_once_with(
            'https://example.invalid/test.pt', model_dir='resources', map_location='cpu', weights_only=True)
        with self.assertRaisesRegex(ValueError, 'Unrestricted'):
            module.load_state_dict_from_url('https://example.invalid/test.pt', model_dir='resources', weights_only=False)
        self.assertEqual(torch.hub.load_state_dict_from_url.call_count, 1)

    def test_all_load_sites_use_guard(self):
        for path in RESEARCH.rglob('*.py'):
            if path.name == 'safe_loading.py':
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    self.assertNotEqual(ast.unparse(node.func), 'torch.load', str(path))
                if isinstance(node, ast.ImportFrom):
                    if node.module == 'torch.hub':
                        self.assertNotIn('load_state_dict_from_url', [a.name for a in node.names], str(path))

    def test_stft_preserves_real_imaginary_power_reduction(self):
        source = (RESEARCH / 'models/preprocess.py').read_text()
        self.assertIn('return_complex=True', source)
        self.assertNotIn('return_complex=False', source)
        self.assertIn('(torch.view_as_real(x) ** 2).sum(dim=-1)', source)
        self.assertIn('torch.amp.autocast(device_type=x.device.type, enabled=False)', source)

    def test_explicit_2d_layers(self):
        for rel in ('models/mn/model.py', 'models/mn/block_types.py', 'models/dymn/model.py'):
            source = (RESEARCH / rel).read_text()
            self.assertIn('Conv2dNormActivation', source)
            self.assertNotIn('ConvNormActivation', source)


if __name__ == '__main__':
    unittest.main()
