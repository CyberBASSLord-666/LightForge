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

    def test_file_metadata_has_fixed_roles_and_identifies_all_failed_attributes(self):
        infos = [SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_size=200),
                 SimpleNamespace(st_mode=stat.S_IFREG | 0o777, st_uid=123, st_size=1024 * 1024 + 1),
                 SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0, st_size=0)]
        with mock.patch.object(Path, 'lstat', side_effect=infos) as observed, \
             mock.patch.object(Path, 'read_bytes') as read:
            record = D.configuration_file_identity()
        self.assertEqual(observed.call_count, 3)
        read.assert_not_called()
        self.assertEqual(record['scope'], 'official-fixture-decoder-file-identity-only')
        self.assertEqual(record['files'], [
            {'role': 'source', 'type': 'regular', 'uid': 0, 'mode': 0o644, 'sizeBytes': 200, 'failedChecks': []},
            {'role': 'keyring', 'type': 'regular', 'uid': 123, 'mode': 0o777,
             'sizeBytes': 1024 * 1024 + 1, 'failedChecks': ['owner', 'writable-mode', 'size']},
            {'role': 'mirrors', 'type': 'symlink', 'uid': 0, 'mode': 0o777, 'sizeBytes': 0,
             'failedChecks': ['file-type', 'writable-mode', 'size']},
        ])
        self.assertLess(len(json.dumps(record)), 2048)

    def test_file_metadata_suppresses_private_paths_errors_and_invalid_numbers(self):
        secret = 'PRIVATE_SOURCE_ENV_URL_SENTINEL'
        cases = [FileNotFoundError(2, secret, secret), PermissionError(13, secret, secret),
                 OSError(999999, secret, secret), OSError(secret),
                 SimpleNamespace(st_mode=secret, st_uid=secret, st_size=secret),
                 SimpleNamespace(st_mode=-1, st_uid=2**100, st_size=2**100),
                 SimpleNamespace(st_mode=True, st_uid=False, st_size=1.5)]
        for case in cases:
            with self.subTest(case=type(case).__name__), \
                 mock.patch.object(Path, 'lstat', side_effect=[case] * 3), \
                 mock.patch.object(Path, 'read_bytes') as read, \
                 mock.patch.object(Path, 'readlink') as links:
                output = json.dumps(D.configuration_file_identity())
            self.assertNotIn(secret, output)
            self.assertNotIn(str(2**100), output)
            self.assertLess(len(output), 2048)
            read.assert_not_called()
            links.assert_not_called()

    def test_diagnostic_cli_never_reads_contents_or_invokes_setup(self):
        output = io.StringIO()
        with mock.patch.object(D, 'configuration_file_identity', return_value={'scope': 'test', 'files': []}), \
             mock.patch.object(D, 'read_configuration_files') as read, \
             mock.patch.object(D, 'prepare') as prepare, mock.patch.object(D.subprocess, 'run') as run, \
             mock.patch.object(D.subprocess, 'check_output') as check, \
             mock.patch.object(D.tempfile, 'mkdtemp') as temporary, \
             contextlib.redirect_stdout(output):
            D.main(['--diagnose-files'])
        self.assertEqual(json.loads(output.getvalue()), {'scope': 'test', 'files': []})
        read.assert_not_called()
        prepare.assert_not_called()
        run.assert_not_called()
        check.assert_not_called()
        temporary.assert_not_called()

    def test_early_check_uses_unchanged_reader_and_retains_rejected_metadata(self):
        for existing in (None, '/existing/ffmpeg'):
            output = io.StringIO()
            with self.subTest(existing=bool(existing)), \
                 mock.patch.object(D, 'configuration_file_identity', return_value={'scope': 'test', 'files': []}), \
                 mock.patch.object(D.shutil, 'which', return_value=existing), \
                 mock.patch.object(D, 'read_public_file', side_effect=D.DecoderValidationError(
                     'Unsupported Ubuntu configuration file identity')) as read, \
                 mock.patch.object(D, 'prepare') as prepare, mock.patch.object(D.subprocess, 'run') as run, \
                 mock.patch.object(D.subprocess, 'check_output') as check, \
                 mock.patch.object(D.tempfile, 'mkdtemp') as temporary, \
                 contextlib.redirect_stdout(output):
                if existing:
                    D.main(['--check-files'])
                    read.assert_not_called()
                else:
                    with self.assertRaisesRegex(SystemExit, 'Unsupported Ubuntu configuration file identity'):
                        D.main(['--check-files'])
                    read.assert_called_once_with(D.SOURCE)
            self.assertEqual(json.loads(output.getvalue()), {'scope': 'test', 'files': []})
            prepare.assert_not_called()
            run.assert_not_called()
            check.assert_not_called()
            temporary.assert_not_called()

    def test_early_probe_rejects_each_required_writable_file_with_exact_role(self):
        for role, rejected in (('source', D.SOURCE), ('keyring', D.KEYRING), ('mirrors', D.MIRRORS)):
            def observed(path):
                return SimpleNamespace(st_mode=stat.S_IFREG | (0o777 if path == rejected else 0o644),
                                       st_uid=0, st_size=3607)
            def contents(path):
                return SOURCE if path == D.SOURCE else MIRRORS if path == D.MIRRORS else b'keyring'
            output = io.StringIO()
            with self.subTest(role=role), mock.patch.object(D.shutil, 'which', return_value=None), \
                 mock.patch.object(Path, 'lstat', observed), mock.patch.object(Path, 'read_bytes', contents), \
                 mock.patch.object(D.subprocess, 'run') as run, \
                 contextlib.redirect_stdout(output), self.assertRaisesRegex(SystemExit, 'configuration file identity'):
                D.main(['--check-files'])
            records = json.loads(output.getvalue())['files']
            self.assertEqual([row['role'] for row in records if row['failedChecks']], [role])
            self.assertEqual(next(row['failedChecks'] for row in records if row['role'] == role), ['writable-mode'])
            run.assert_not_called()

    def test_shared_reader_preserves_conditional_mirror_requirement(self):
        for raw, expected in [(SOURCE, [D.SOURCE, D.KEYRING, D.MIRRORS]),
                              (SOURCE.replace(D.MIRROR_URI.encode(), D.ARCHIVE.encode()), [D.SOURCE, D.KEYRING])]:
            with self.subTest(mirrors=len(expected) == 3), \
                 mock.patch.object(D, 'read_public_file', side_effect=[raw, b'keyring', MIRRORS]) as read:
                result = D.read_configuration_files()
            self.assertEqual([call.args[0] for call in read.call_args_list], expected)
            self.assertEqual(result, (raw, b'keyring', MIRRORS if len(expected) == 3 else None))

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
             mock.patch.object(D, 'configuration_file_identity', return_value={'scope': 'test', 'files': []}), \
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
        # Validate option syntax/keys, not random temporary-path substrings.
        # For example, an owned path containing 'rm' is not an rm command.
        self.assertEqual(update[0][:2], ['sudo', 'apt-get'])
        self.assertEqual(update[0][2:-2:2], ['-o'] * len(options))
        self.assertEqual(len(update[0]), 4 + 2 * len(options))
        self.assertEqual(set(options), {
            'Dir::Etc::sourcelist', 'Dir::Etc::sourceparts', 'Dir::State::lists',
            'Dir::Cache::archives', 'Dir::Cache::pkgcache', 'Dir::Cache::srcpkgcache',
            'Acquire::Retries', 'Acquire::http::Timeout', 'Acquire::https::Timeout',
            'APT::Update::Error-Mode',
        })
        self.assertEqual(options['Acquire::http::Timeout'], '30')
        self.assertFalse(any(arg in ('rm', 'apt-key') or arg.startswith('--force')
                             for arg in update[0]))
        identity, record = map(json.loads, output.splitlines())
        self.assertEqual(identity, {'scope': 'test', 'files': []})
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
