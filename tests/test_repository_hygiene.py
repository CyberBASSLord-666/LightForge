"""Regression coverage for the dependency-free repository maintenance gate."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('repository_hygiene', Path(__file__).resolve().parents[1] / 'tools/repository_hygiene.py')
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


class RepositoryHygieneTests(unittest.TestCase):
    def check(self, files, extra=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            return hygiene.check(root, set(files) | set(extra))

    def test_relative_parent_and_root_links(self):
        self.assertEqual([], self.check({'README.md': '[Guide](docs/guide.md)', 'docs/guide.md': '[Home](../README.md) [Root](/README.md)'}))

    def test_missing_link_is_rejected(self):
        self.assertIn('missing tracked link target', self.check({'README.md': '[Gone](gone.md)'})[0])

    def test_untracked_file_is_not_a_valid_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('[Local](local.md)')
            (root / 'local.md').write_text('not staged')
            self.assertTrue(hygiene.check(root, {'README.md'}))

    def test_sparse_asset_is_valid_when_tracked(self):
        self.assertEqual([], self.check({'README.md': '[Model](web/model.onnx)'}, ['web/model.onnx']))

    def test_directory_link(self):
        self.assertEqual([], self.check({'README.md': '[Source](web/)'}, ['web/app.js']))

    def test_url_encoded_local_path(self):
        self.assertEqual([], self.check({'README.md': '[Space](docs/a%20b.md)', 'docs/a b.md': '# Space'}))

    def test_angle_bracket_destination(self):
        self.assertEqual([], self.check({'README.md': '[Space](<docs/a b.md>)', 'docs/a b.md': '# Space'}))

    def test_heading_fragment(self):
        self.assertEqual([], self.check({'README.md': '# Hello, `World`!\n[Here](#hello-world)'}))

    def test_missing_heading_fragment(self):
        self.assertIn('missing heading', self.check({'README.md': '[No](#missing)'})[0])

    def test_duplicate_heading_fragment(self):
        self.assertEqual([], self.check({'README.md': '# Same\n# Same\n[Second](#same-1)'}))

    def test_explicit_anchor(self):
        self.assertEqual([], self.check({'README.md': '<a id="custom"></a>\n[Here](#custom)'}))

    def test_external_schemes_and_protocol_relative(self):
        self.assertEqual([], self.check({'README.md': '[Web](https://example.com/missing) [Mail](mailto:a@example.com) [Host](//example.com/x)'}))

    def test_query_does_not_change_target(self):
        self.assertEqual([], self.check({'README.md': '[Self](README.md?plain=1)'}))

    def test_fenced_code_is_not_a_link(self):
        self.assertEqual([], self.check({'README.md': '```md\n[Missing](missing.md)\n```\n~~~\n[Also](absent)\n~~~'}))

    def test_nested_shorter_fence_does_not_close(self):
        self.assertEqual([], self.check({'README.md': '````\n```\n[Missing](gone)\n```\n````'}))

    def test_inline_code_and_comment_are_not_links(self):
        self.assertEqual([], self.check({'README.md': '`[No](missing)` <!-- [No](missing) -->'}))

    def test_named_reference(self):
        self.assertEqual([], self.check({'README.md': '[Home][ HOME ]\n\n[home]: README.md'}))

    def test_collapsed_reference(self):
        self.assertEqual([], self.check({'README.md': '[Home][]\n\n[home]: README.md'}))

    def test_undefined_reference(self):
        self.assertIn('undefined reference', self.check({'README.md': '[Home][absent]'})[0])

    def test_reference_target_is_validated(self):
        self.assertIn('missing tracked', self.check({'README.md': '[Home][id]\n[id]: gone.md'})[0])

    def test_traversal_rejected_including_encoded(self):
        for target in ('../outside', '%2e%2e/outside', '/%2e%2e/outside'):
            with self.subTest(target=target):
                self.assertIn('escapes repository', self.check({'README.md': f'[Outside]({target})'})[0])

    def test_managed_docs_must_be_present(self):
        self.assertIn('cannot read', self.check({}, ['docs/guide.md'])[0])

    def test_historical_links_are_not_current_contracts(self):
        self.assertEqual([], self.check({'qa/release-1.6.0/README.md': '[Old](retired.md)'}))

    def test_retired_paths_are_rejected(self):
        for path in ('migration/manifest.json', 'releases/v1.6.0/parts/001', 'SOURCE_MANIFEST.json', '.github/workflows/inspect-android-2.2.1.yml'):
            with self.subTest(path=path):
                self.assertIsNotNone(hygiene.clutter_reason(path))

    def test_caches_and_compiled_outputs_are_rejected(self):
        for path in ('tools/__pycache__/x.pyc', 'web/node_modules/x.js', 'dist/app.apk', 'x.class', '.venv/bin/python'):
            with self.subTest(path=path):
                self.assertIsNotNone(hygiene.clutter_reason(path))

    def test_signing_and_personal_exports_are_rejected(self):
        for path in ('signing/notes.txt', 'backup.jks', 'keys/keystore-password.txt', '.env.local', 'LightForge-diagnostics-private.txt', 'My-Private-Source.zip'):
            with self.subTest(path=path):
                self.assertIsNotNone(hygiene.clutter_reason(path))

    def test_retained_assets_tests_and_public_receipts_are_allowed(self):
        for path in ('web/analysis/models/model.onnx', 'research/upstream/model.pt', 'tests/migration-2.0.test.cjs', 'releases/v2.2.5/signed-apk.delta.json', 'release-verification.json', 'qa/release-1.6.0/failed.log', '.env.example'):
            with self.subTest(path=path):
                self.assertIsNone(hygiene.clutter_reason(path))

    def test_markdown_image_is_a_local_link(self):
        self.assertIn('missing tracked', self.check({'README.md': '![Missing](gone.png)'})[0])

    def test_optional_link_title(self):
        self.assertEqual([], self.check({'README.md': '[Self](README.md "Home")'}))


if __name__ == '__main__':
    unittest.main()
