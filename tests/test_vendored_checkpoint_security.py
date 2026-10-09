import ast
import importlib.util
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'research/upstream'
GUARD = UPSTREAM / '_lightforge_research_checkpoint_security.py'


def guard(version='2.13.0+cpu', allowed=None):
    torch = SimpleNamespace(__version__=version, serialization=SimpleNamespace(get_safe_globals=Mock(return_value=allowed or [])),
                            load=Mock(return_value={'weight': 'tensor-placeholder'}),
                            hub=SimpleNamespace(load_state_dict_from_url=Mock(return_value={'weight': 'tensor-placeholder'})))
    spec = importlib.util.spec_from_file_location('checkpoint_guard_fixture', GUARD)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'torch': torch}):
        spec.loader.exec_module(module)
    return module, torch


class VendoredCheckpointSecurityTest(unittest.TestCase):
    def test_old_and_prerelease_runtimes_never_load(self):
        for version in ('1.13.0', '2.12.1', '2.13.0rc1', '2.13.0.dev1'):
            module, torch = guard(version)
            with self.assertRaises(RuntimeError):
                module.load_tensor_checkpoint('test.pt')
            with self.assertRaises(RuntimeError):
                module.load_remote_tensor_checkpoint('https://example.invalid/test.pt')
            torch.load.assert_not_called()
            torch.hub.load_state_dict_from_url.assert_not_called()

    def test_local_tensor_loading_preserves_arguments_and_does_not_retry(self):
        module, torch = guard()
        module.load_tensor_checkpoint('test.pt', 'cpu', mmap=True)
        torch.load.assert_called_once_with('test.pt', map_location='cpu', weights_only=True, mmap=True)
        torch.load.reset_mock()
        torch.load.side_effect = ValueError('arbitrary class refused')
        with self.assertRaisesRegex(ValueError, 'arbitrary class refused'):
            module.load_tensor_checkpoint('legacy.pt')
        torch.load.assert_called_once_with('legacy.pt', map_location='cpu', weights_only=True)

    def test_unsafe_options_and_ambient_custom_classes_are_rejected(self):
        module, torch = guard()
        for kwargs in ({'weights_only': False}, {'pickle_module': object()}):
            with self.assertRaises(ValueError):
                module.load_tensor_checkpoint('test.pt', **kwargs)
        torch.load.assert_not_called()
        module, torch = guard(allowed=[object])
        with self.assertRaisesRegex(ValueError, 'trusted environment'):
            module.load_tensor_checkpoint('legacy-demucs.pt')
        with self.assertRaises(ValueError):
            module.load_remote_tensor_checkpoint('https://example.invalid/test.pt')
        torch.load.assert_not_called()
        torch.hub.load_state_dict_from_url.assert_not_called()

    def test_remote_loading_requires_https_and_preserves_hub_options(self):
        module, torch = guard()
        for url in ('http://example.invalid/x', 'file:///tmp/x', 'https://name:secret@example.invalid/x'):
            with self.assertRaises(ValueError):
                module.load_remote_tensor_checkpoint(url)
        with self.assertRaises(ValueError):
            module.load_remote_tensor_checkpoint('https://example.invalid/x', weights_only=False)
        torch.hub.load_state_dict_from_url.assert_not_called()
        module.load_remote_tensor_checkpoint('https://example.invalid/x', file_name='model.pt', model_dir='resources')
        torch.hub.load_state_dict_from_url.assert_called_once_with('https://example.invalid/x', file_name='model.pt',
                                                                 model_dir='resources', map_location='cpu', progress=True, check_hash=False, weights_only=True)

    def test_hub_positional_map_location_preserved(self):
        module, torch = guard()
        module.load_remote_tensor_checkpoint('https://example.invalid/x', 'resources', 'cpu')
        torch.hub.load_state_dict_from_url.assert_called_once_with(
            'https://example.invalid/x', model_dir='resources', map_location='cpu',
            progress=True, check_hash=False, file_name=None, weights_only=True)

    def test_legacy_demucs_refuses_before_importing_torch(self):
        script = UPSTREAM / 'separation-candidates/check-demucs-weight-identity.py'
        result = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('plain tensor state dictionary', result.stderr)
        self.assertNotIn('ModuleNotFoundError', result.stderr)
        self.assertNotIn('safe_globals', script.read_text())

    def test_delegated_legacy_loaders_cannot_bypass_restrictions(self):
        uvr = (UPSTREAM / 'source-separation/uvr-separate.py').read_text()
        self.assertNotIn('.load_from_checkpoint(', uvr)
        self.assertNotIn('_gm(', uvr)
        self.assertIn("separator.load_state_dict(checkpoint['state_dict'], strict=True)", uvr)
        source = (UPSTREAM / 'separation-candidates/demucs-upstream-api.py').read_text()
        self.assertNotIn('get_model(name=', source)
        tree = ast.parse(source)
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_load_model')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<demucs-refusal-fixture>', 'exec'), namespace)
        with self.assertRaisesRegex(RuntimeError, 'plain tensor state dictionary'):
            namespace['_load_model'](object())
        m2d = (UPSTREAM / 'pretrained-sed/models/m2d/portable_m2d.py').read_text()
        self.assertIn('trust_remote_code=False, use_safetensors=True', m2d)

    def test_all_vendored_torch_load_sites_are_guarded(self):
        approved = {GUARD, UPSTREAM / 'vocal-candidates/EfficientAT/helpers/safe_loading.py'}
        guarded_files = set()
        for path in UPSTREAM.rglob('*.py'):
            if path in approved:
                continue
            source = path.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    self.assertNotIn(ast.unparse(node.func), ('torch.load', 'torch.hub.load_state_dict_from_url'), str(path))
                if isinstance(node, ast.ImportFrom) and node.module == 'torch.hub':
                    self.assertNotIn('load_state_dict_from_url', [a.name for a in node.names], str(path))
            if '_safe_torch_load(' in source or '_safe_hub_load(' in source or 'as load_state_dict_from_url' in source:
                guarded_files.add(path)
                self.assertIn('from _lightforge_research_checkpoint_security import', source)
                expected_parent = len(path.parent.relative_to(UPSTREAM).parts)
                self.assertIn(f'.parents[{expected_parent}]', source)
        self.assertEqual(len(guarded_files), 14)


if __name__ == '__main__':
    unittest.main()
