"""Official decoder transport setup tests; no package install or model inference."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixture_decoder', ROOT / 'tools/prepare_fixture_decoder.py')
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
OS = {'ID': 'ubuntu', 'VERSION_ID': '24.04', 'VERSION_CODENAME': 'noble'}
MIRRORS = b'http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\nhttps://archive.ubuntu.com/ubuntu/\tpriority:2\nhttps://security.ubuntu.com/ubuntu/\tpriority:3\n'
SOURCE = ('''# Original cloud image archive configuration

Types: deb
URIs: mirror+file:/etc/apt/apt-mirrors.txt
Suites: noble noble-updates noble-backports
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
Architectures: amd64

Types: deb
URIs: mirror+file:/etc/apt/apt-mirrors.txt
Suites: noble-security
Components: main universe restricted multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
''').encode()


class FixtureDecoderTests(unittest.TestCase):
    def test_rewrites_only_official_transport_preserving_source_fields(self):
        output, suites, components = D.canonical_source(SOURCE, OS, 'amd64', MIRRORS)
        expected = SOURCE.replace(D.MIRROR_URI.encode(), D.ARCHIVE.encode(), 1)
        expected = expected.replace(D.MIRROR_URI.encode(), D.SECURITY.encode(), 1)
        self.assertEqual(output, expected)
        self.assertEqual(suites, ['noble', 'noble-backports', 'noble-security', 'noble-updates'])
        self.assertEqual(components, ['main', 'multiverse', 'restricted', 'universe'])

    def test_official_direct_uri_does_not_require_mirror_configuration(self):
        for uri in sorted(D.OFFICIAL_URIS):
            with self.subTest(uri=uri):
                raw = SOURCE.replace(D.MIRROR_URI.encode(), uri.encode())
                output, _, _ = D.canonical_source(raw, OS, 'amd64')
                self.assertIn(D.ARCHIVE.encode(), output)
                self.assertIn(D.SECURITY.encode(), output)

    def test_unsupported_distribution_or_architecture_fails(self):
        for distro, arch in [(OS | {'ID': 'debian'}, 'amd64'),
                            (OS | {'VERSION_ID': '26.04'}, 'amd64'),
                            (OS | {'VERSION_CODENAME': 'jammy'}, 'amd64'), (OS, 'arm64')]:
            with self.subTest(distro=distro, arch=arch), self.assertRaises(ValueError):
                D.canonical_source(SOURCE, distro, arch, MIRRORS)

    def test_ambiguous_or_untrusted_source_definition_fails(self):
        changes = [
            (b'Types: deb', b'Types: deb-src'),
            (b'Components: main universe restricted multiverse', b'Components: main unknown'),
            (b'Suites: noble noble-updates noble-backports', b'Suites: jammy jammy-updates'),
            (b'Suites: noble-security', b'Suites: noble-proposed'),
            (b'Suites: noble-security', b'Suites: noble'),
            (b'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg', b'Signed-By: /tmp/untrusted.gpg'),
            (b'Architectures: amd64', b'Architectures: amd64 arm64'),
            (b'Types: deb', b'Types: deb\nTrusted: yes'),
            (b'Types: deb', b'Types: deb\nCheck-Valid-Until: no'),
            (b'Types: deb', b'Types: deb\nTypes: deb'),
            (b'Types: deb', b'Types: deb\n types-continuation'),
            (D.MIRROR_URI.encode(), b'https://archive.ubuntu.com.attacker.invalid/ubuntu/'),
            (D.MIRROR_URI.encode(), b'https://secret@archive.ubuntu.com/ubuntu/'),
            (D.MIRROR_URI.encode(), b'mirror+file:/tmp/arbitrary'),
        ]
        for old, new in changes:
            with self.subTest(change=new), self.assertRaises(ValueError):
                D.canonical_source(SOURCE.replace(old, new, 1), OS, 'amd64', MIRRORS)

    def test_unknown_missing_or_modified_mirror_list_fails(self):
        for mirrors in (None, b'', MIRRORS + b'https://unrecognized.invalid/ priority:4\n',
                        MIRRORS.replace(b'priority:1', b'priority:0')):
            with self.subTest(mirrors=mirrors), self.assertRaises(ValueError):
                D.canonical_source(SOURCE, OS, 'amd64', mirrors)

    def test_source_and_keyring_identity_rejects_links_mutability_or_unbounded_data(self):
        trusted = dict(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_size=10)
        cases = [trusted | {'st_uid': 123}, trusted | {'st_mode': stat.S_IFLNK | 0o777},
                 trusted | {'st_mode': stat.S_IFREG | 0o666}, trusted | {'st_size': 0},
                 trusted | {'st_size': 1024 * 1024 + 1}]
        path = Path('/synthetic/official-source')
        for fields in cases:
            with self.subTest(fields=fields), mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(**fields)), \
                 mock.patch.object(Path, 'read_bytes') as read, self.assertRaises(ValueError):
                D.read_public_file(path)
            read.assert_not_called()
        with mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(**trusted)), \
             mock.patch.object(Path, 'read_bytes', return_value=b'official'):
            self.assertEqual(D.read_public_file(path), b'official')

    def test_existing_decoder_never_reads_or_changes_apt_configuration(self):
        with mock.patch.object(D.shutil, 'which', return_value='/existing/ffmpeg'), \
             mock.patch.object(D, 'read_public_file') as read, \
             mock.patch.object(D.platform, 'freedesktop_os_release') as distro, \
             mock.patch.object(D.subprocess, 'run') as run, \
             mock.patch.object(D.subprocess, 'check_output') as check:
            D.prepare()
        run.assert_called_once_with(['/existing/ffmpeg', '-version'], check=True, timeout=30)
        read.assert_not_called()
        distro.assert_not_called()
        check.assert_not_called()

    def exercise(self, failure=None, foreign='', drift=False):
        temporary = tempfile.TemporaryDirectory(prefix='decoder fixture ')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        calls, metadata = [], io.StringIO()
        reads = {D.SOURCE: 0, D.KEYRING: 0, D.MIRRORS: 0}
        def read(path):
            reads[path] += 1
            if path == D.SOURCE:
                return SOURCE if not drift or reads[path] == 1 else SOURCE + b'# changed\n'
            return MIRRORS if path == D.MIRRORS else b'SYNTHETIC ORIGINAL KEYRING'
        def run(command, **options):
            calls.append((command, options))
            if command[:3] == ['sudo', '-u', '_apt']:
                source = Path(command[-1])
                self.assertEqual(source.name, 'ubuntu.sources')
                self.assertEqual(source.parent.parent, root)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o644)
                for name in ('', 'sourceparts', 'lists', 'archives'):
                    self.assertEqual(stat.S_IMODE((source.parent / name).stat().st_mode), 0o755)
                self.assertNotIn(b'azure.archive', source.read_bytes())
            phase = 'sandbox' if command[:3] == ['sudo', '-u', '_apt'] else (
                'update' if 'update' in command else 'install' if 'install' in command else 'version')
            if failure == phase:
                raise subprocess.CalledProcessError(41, command)
            if failure == phase + '-timeout':
                raise subprocess.TimeoutExpired(command, 30)
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(D.shutil, 'which', side_effect=[None, '/installed/ffmpeg']), \
             mock.patch.object(D.platform, 'freedesktop_os_release', return_value=OS), \
             mock.patch.object(D.subprocess, 'check_output', side_effect=['amd64\n', foreign]), \
             mock.patch.object(D, 'read_public_file', side_effect=read), \
             mock.patch.object(D.subprocess, 'run', side_effect=run), \
             mock.patch.dict(os.environ, {'RUNNER_TEMP': str(root)}), contextlib.redirect_stdout(metadata):
            error = None
            previous_umask = os.umask(0o077)
            try:
                D.prepare()
            except (ValueError, subprocess.SubprocessError) as caught:
                error = caught
            finally:
                os.umask(previous_umask)
        return calls, metadata.getvalue(), error

    def test_install_uses_only_owned_sources_and_cache_with_bounded_options(self):
        calls, output, error = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(len(calls), 4)
        update, install = calls[1:3]
        self.assertEqual(update[1], {'check': True, 'timeout': 180})
        self.assertEqual(install[1], {'check': True, 'timeout': 600})
        self.assertEqual(update[0][-2:], ['update', '-qq'])
        self.assertEqual(install[0][-4:], ['install', '-y', '--no-install-recommends', 'ffmpeg'])
        self.assertEqual(update[0][:-2], install[0][:-4])
        options = dict(item.split('=', 1) for item in update[0] if '=' in item)
        self.assertEqual(options['Acquire::Retries'], '2')
        self.assertEqual(options['Acquire::https::Timeout'], '30')
        self.assertEqual(options['APT::Update::Error-Mode'], 'any')
        for key, value in options.items():
            if key.startswith('Dir::'):
                self.assertIn('/lightforge-ffmpeg-apt-', value)
        forbidden = ('AllowUnauthenticated', 'AllowInsecure', 'Verify-Peer', 'Verify-Host',
                     'Proxy', 'Sandbox', 'trusted=yes', 'force', 'rm', 'apt-key')
        self.assertFalse(any(word in ' '.join(update[0]) for word in forbidden))
        record = json.loads(output)
        self.assertEqual(record['originalSourceSha256'], hashlib.sha256(SOURCE).hexdigest())
        self.assertEqual(set(record), {'scope', 'distribution', 'architecture', 'suites', 'components',
                                      'originalSourceSha256', 'temporarySourceSha256', 'signingKeyringSha256'})

    def test_failures_and_timeouts_do_not_continue_or_retry_installation(self):
        for failure, count in [('sandbox', 1), ('update', 2), ('update-timeout', 2),
                               ('install', 3), ('install-timeout', 3), ('version', 4)]:
            with self.subTest(failure=failure):
                calls, _, error = self.exercise(failure=failure)
                self.assertIsNotNone(error)
                self.assertEqual(len(calls), count)

    def test_foreign_architecture_holds_before_apt_or_workspace_creation(self):
        calls, output, error = self.exercise(foreign='i386\n')
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(output, '')

    def test_source_drift_holds_before_decoder_execution(self):
        calls, _, error = self.exercise(drift=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(len(calls), 3)

    def test_owned_validation_reasons_are_diagnosable_and_allowlist_is_complete(self):
        tree = ast.parse((ROOT / 'tools/prepare_fixture_decoder.py').read_text())
        reasons = {node.args[1].value for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == 'require'}
        self.assertEqual(reasons, D.VALIDATION_REASONS)
        for reason in reasons:
            with self.subTest(reason=reason), \
                 mock.patch.object(D, 'prepare', side_effect=D.DecoderValidationError(reason)):
                with self.assertRaises(SystemExit) as caught:
                    D.main()
                self.assertEqual(str(caught.exception),
                    'Official fixture decoder preparation failed closed: ' + reason)
                self.assertTrue(caught.exception.__suppress_context__)

    def test_main_errors_never_reflect_private_source_or_environment_text(self):
        secret = 'SECRET_TEST_SENTINEL'
        for error in (D.DecoderValidationError(secret), ValueError(secret), OSError(secret), KeyError(secret),
                      subprocess.CalledProcessError(1, [secret]), subprocess.TimeoutExpired(secret, 30)):
            with self.subTest(error=type(error).__name__), mock.patch.object(D, 'prepare', side_effect=error):
                with self.assertRaises(SystemExit) as caught:
                    D.main()
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(secret, ''.join(traceback.format_exception(caught.exception)))
                self.assertTrue(caught.exception.__suppress_context__)


if __name__ == '__main__':
    unittest.main()
