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
SYNTHETIC_KEYRING = b'K' * 3607


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

    def test_source_and_mirror_identity_rejects_links_mutability_or_unbounded_data(self):
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
        for role, rejected in (('source', D.SOURCE), ('mirrors', D.MIRRORS)):
            def observed(path):
                return SimpleNamespace(st_mode=stat.S_IFREG | (0o777 if path == rejected else 0o644),
                                       st_uid=0, st_size=3607)
            def contents(path):
                return SOURCE if path == D.SOURCE else MIRRORS if path == D.MIRRORS else b'keyring'
            output = io.StringIO()
            with self.subTest(role=role), mock.patch.object(D.shutil, 'which', return_value=None), \
                 mock.patch.object(Path, 'lstat', observed), mock.patch.object(Path, 'read_bytes', contents), \
                 mock.patch.object(D, 'read_authenticated_keyring', return_value=(SYNTHETIC_KEYRING, ())), \
                 mock.patch.object(D.subprocess, 'run') as run, \
                 contextlib.redirect_stdout(output), self.assertRaisesRegex(SystemExit, 'configuration file identity'):
                D.main(['--check-files'])
            records = json.loads(output.getvalue())['files']
            self.assertEqual([row['role'] for row in records if row['failedChecks']], [role])
            self.assertEqual(next(row['failedChecks'] for row in records if row['role'] == role), ['writable-mode'])
            run.assert_not_called()

    def test_shared_reader_preserves_conditional_mirror_requirement(self):
        for raw, expected in [(SOURCE, [D.SOURCE, D.MIRRORS]),
                              (SOURCE.replace(D.MIRROR_URI.encode(), D.ARCHIVE.encode()), [D.SOURCE])]:
            with self.subTest(mirrors=len(expected) == 2), \
                 mock.patch.object(D, 'read_public_file', side_effect=[raw, MIRRORS]) as read, \
                 mock.patch.object(D, 'read_authenticated_keyring', return_value=(b'keyring', ())) as authenticated:
                result = D.read_configuration_files()
            self.assertEqual([call.args[0] for call in read.call_args_list], expected)
            authenticated.assert_called_once_with(D.KEYRING, 0)
            self.assertEqual(result, (raw, b'keyring', MIRRORS if len(expected) == 2 else None))

    def exercise(self, failure=None, foreign='', drift=False, copy_drift=None, private_comment=False, comment_separator=None):
        temporary = tempfile.TemporaryDirectory(prefix='decoder-fixture-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source_fixture = (b'# PRIVATE_COMMENT_SENTINEL\n' if private_comment else b'') + SOURCE
        if comment_separator is not None:
            source_fixture = source_fixture.replace(b'Types: deb\n', b'Types: deb' + comment_separator + b'# PRIVATE_COMMENT_SENTINEL\n')
        calls, metadata = [], io.StringIO()
        def workspace():
            # Owned unit fixture only; real fixed-root validation has its own tests.
            result = Path(tempfile.mkdtemp(prefix='lightforge-ffmpeg-apt-', dir=root))
            result.chmod(0o755)
            return result
        reads = {D.SOURCE: 0, D.MIRRORS: 0}
        authentic_reader = D.read_authenticated_keyring
        def read_keyring(path, owner, **options):
            return (SYNTHETIC_KEYRING, ()) if path == D.KEYRING else authentic_reader(path, owner, **options)
        def read(path):
            reads[path] += 1
            if path == D.SOURCE:
                return source_fixture if not drift or reads[path] == 1 else source_fixture + b'# changed\n'
            return MIRRORS
        def run(command, **options):
            calls.append((command, options))
            if command[:3] == ['sudo', '-u', '_apt']:
                source = Path(command[-1])
                self.assertIn(source.name, ('ubuntu.sources', 'ubuntu-archive-keyring.gpg'))
                self.assertEqual(source.parent.parent, root)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o644 if source.suffix == '.sources' else 0o444)
                for name in ('', 'sourceparts', 'lists', 'archives'):
                    self.assertEqual(stat.S_IMODE((source.parent / name).stat().st_mode), 0o755)
                if source.suffix == '.sources':
                    self.assertNotIn(b'azure.archive', source.read_bytes())
                    self.assertIn(str(source.parent / 'ubuntu-archive-keyring.gpg').encode(), source.read_bytes())
                    self.assertNotIn(str(D.KEYRING).encode(), source.read_bytes())
                else:
                    self.assertEqual(source.read_bytes(), SYNTHETIC_KEYRING)
            phase = ('sandbox' if command[-1].endswith('ubuntu.sources') else 'sandbox-keyring') if command[:3] == ['sudo', '-u', '_apt'] else (
                'update' if 'update' in command else 'install' if 'install' in command else 'version')
            if failure == phase:
                raise subprocess.CalledProcessError(41, command)
            if failure == phase + '-timeout':
                raise subprocess.TimeoutExpired(command, 30)
            if phase == copy_drift:
                copied = next(root.glob('lightforge-ffmpeg-apt-*/ubuntu-archive-keyring.gpg'))
                copied.chmod(0o644)
                copied.write_bytes(b'X' + SYNTHETIC_KEYRING[1:])
                copied.chmod(0o444)
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(D.shutil, 'which', side_effect=[None, '/installed/ffmpeg']), \
             mock.patch.object(D.platform, 'freedesktop_os_release', return_value=OS), \
             mock.patch.object(D.subprocess, 'check_output', side_effect=['amd64\n', foreign]), \
             mock.patch.object(D, 'configuration_file_identity', return_value={'scope': 'test', 'files': []}), \
             mock.patch.object(D, 'read_public_file', side_effect=read), \
             mock.patch.object(D, 'read_authenticated_keyring', side_effect=read_keyring), \
             mock.patch.object(D, 'KEYRING_SHA256', hashlib.sha256(SYNTHETIC_KEYRING).hexdigest()), \
             mock.patch.object(D, 'create_public_workspace', side_effect=workspace), \
             mock.patch.object(D.subprocess, 'run', side_effect=run), \
             mock.patch.dict(os.environ, {'RUNNER_TEMP': str(root)}), contextlib.redirect_stdout(metadata):
            error = None
            previous_umask = os.umask(0o077)
            try:
                D.prepare()
            except (ValueError, subprocess.SubprocessError, D.DecoderStageError) as caught:
                error = caught
            finally:
                os.umask(previous_umask)
        return calls, metadata.getvalue(), error

    def test_install_uses_only_owned_sources_and_cache_with_bounded_options(self):
        calls, output, error = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(len(calls), 5)
        update, install = calls[2:4]
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
        for failure, count in [('sandbox', 1), ('sandbox-keyring', 2), ('update', 3), ('update-timeout', 3),
                               ('install', 4), ('install-timeout', 4), ('version', 5)]:
            with self.subTest(failure=failure):
                calls, _, error = self.exercise(failure=failure)
                self.assertIsNotNone(error)
                self.assertEqual(len(calls), count)
                expected = {'sandbox': 'sandbox-source-readable', 'sandbox-keyring': 'sandbox-keyring-readable',
                            'update': 'apt-update', 'install': 'apt-install', 'version': 'installed-decoder-version'}
                self.assertEqual(error.stage, expected[failure.removesuffix('-timeout')])

    def test_foreign_architecture_holds_before_apt_or_workspace_creation(self):
        calls, output, error = self.exercise(foreign='i386\n')
        self.assertIsNotNone(error)
        self.assertEqual(calls, [])
        self.assertEqual(output, '')

    def test_source_drift_holds_before_decoder_execution(self):
        calls, _, error = self.exercise(drift=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(len(calls), 4)

    def test_copy_drift_after_either_apt_call_holds_before_next_action(self):
        for phase, count in [('update', 3), ('install', 4)]:
            with self.subTest(phase=phase):
                calls, _, error = self.exercise(copy_drift=phase)
                self.assertIsInstance(error, D.DecoderValidationError)
                self.assertEqual(len(calls), count)

    def test_private_comments_are_not_publicly_staged_or_logged_but_original_hash_is_bound(self):
        calls, output, error = self.exercise(private_comment=True)
        self.assertIsNone(error)
        source = Path(calls[0][0][-1]).read_bytes()
        self.assertNotIn(b'PRIVATE_COMMENT_SENTINEL', source)
        self.assertFalse(any(line.startswith(b'#') for line in source.splitlines()))
        self.assertNotIn('PRIVATE_COMMENT_SENTINEL', output)
        record = json.loads(output.splitlines()[-1])
        self.assertEqual(record['originalSourceSha256'], hashlib.sha256(b'# PRIVATE_COMMENT_SENTINEL\n' + SOURCE).hexdigest())

    def test_all_validator_logical_line_separators_remove_private_comments(self):
        for separator in (b'\x0b', b'\x0c', b'\x1c', b'\x1d', b'\x1e', b'\xc2\x85', b'\xe2\x80\xa8', b'\xe2\x80\xa9'):
            with self.subTest(separator=separator.hex()):
                calls, output, error = self.exercise(comment_separator=separator)
                self.assertIsNone(error)
                source = Path(calls[0][0][-1]).read_bytes()
                self.assertNotIn(b'PRIVATE_COMMENT_SENTINEL', source)
                self.assertNotIn(separator, source)
                self.assertNotIn('PRIVATE_COMMENT_SENTINEL', output)
                original = SOURCE.replace(b'Types: deb\n', b'Types: deb' + separator + b'# PRIVATE_COMMENT_SENTINEL\n')
                record = json.loads(output.splitlines()[-1])
                self.assertEqual(record['originalSourceSha256'], hashlib.sha256(original).hexdigest())
                expected, _, _ = D.canonical_source(SOURCE, OS, 'amd64', MIRRORS)
                observed = source.decode().splitlines()
                expected_lines = [line for line in expected.decode().splitlines() if not line.startswith('#')]
                self.assertEqual([line for line in observed if not line.startswith('Signed-By:')],
                                 [line for line in expected_lines if not line.startswith('Signed-By:')])

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


class AuthenticatedKeyringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='keyring-identity-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.key = self.root / 'original.gpg'
        self.key.write_bytes(SYNTHETIC_KEYRING)
        self.key.chmod(0o644)
        patcher = mock.patch.object(D, 'KEYRING_SHA256', hashlib.sha256(SYNTHETIC_KEYRING).hexdigest())
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, path=None, **options):
        return D.read_authenticated_keyring(path or self.key, os.getuid(), **options)

    def test_checked_in_pin_matches_independently_authenticated_official_member(self):
        tree = ast.parse((ROOT / 'tools/prepare_fixture_decoder.py').read_text())
        values = {node.targets[0].id: node.value.value for node in tree.body
                  if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                  and isinstance(node.value, ast.Constant)}
        self.assertEqual(values['KEYRING_SHA256'], '80a36b0a6de2f69f49d2df75ef473ccde121e9e190b9ea01d20a4f63778d5c31')
        self.assertEqual(values['KEYRING_BYTES'], 3607)

    def test_original_normal_and_observed_modes_require_identical_pinned_content(self):
        for mode in (0o444, 0o644, 0o777):
            with self.subTest(mode=oct(mode)):
                self.key.chmod(mode)
                raw, identity = self.read()
                self.assertEqual(raw, SYNTHETIC_KEYRING)
                self.assertEqual(identity[2], stat.S_IFREG | mode)
                self.assertEqual(stat.S_IMODE(self.key.stat().st_mode), mode)
        for mode in (0o666, 0o664, 0o774, 0o4777, 0o1644):
            with self.subTest(rejected_mode=oct(mode)):
                self.key.chmod(mode)
                with self.assertRaisesRegex(ValueError, 'file identity'):
                    self.read()

    def test_wrong_content_length_owner_and_file_type_fail_closed(self):
        for content in (b'X' + SYNTHETIC_KEYRING[1:], SYNTHETIC_KEYRING[:-1], SYNTHETIC_KEYRING + b'X'):
            with self.subTest(size=len(content)):
                self.key.write_bytes(content)
                with self.assertRaises(ValueError):
                    self.read()
        self.key.write_bytes(SYNTHETIC_KEYRING)
        with self.assertRaisesRegex(ValueError, 'file identity'):
            D.read_authenticated_keyring(self.key, os.getuid() + 1)
        directory = self.root / 'directory'; directory.mkdir()
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        for path in (directory, fifo):
            with self.subTest(type=path.name), self.assertRaisesRegex(ValueError, 'file identity'):
                self.read(path)

    def test_symlink_final_component_and_ancestor_are_never_followed(self):
        link = self.root / 'link.gpg'; link.symlink_to(self.key)
        ancestor = self.root / 'linked-directory'; ancestor.symlink_to(self.root, target_is_directory=True)
        for path in (link, ancestor / self.key.name):
            with self.subTest(path=path.name), mock.patch.object(D.os, 'read') as read, self.assertRaises(OSError):
                self.read(path)
            read.assert_not_called()

    def test_every_stable_identity_attribute_is_compared(self):
        real_fstat = os.fstat
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        for field in fields:
            observations = []
            def fstat(descriptor):
                info = real_fstat(descriptor)
                values = {name: getattr(info, name) for name in fields}
                observations.append(True)
                if len(observations) == 2:
                    values[field] += 1
                return SimpleNamespace(**values)
            with self.subTest(field=field), mock.patch.object(D.os, 'fstat', side_effect=fstat), \
                 self.assertRaisesRegex(ValueError, 'identity changed'):
                self.read()

    def test_same_name_replacement_is_rejected_even_with_identical_bytes(self):
        real_read = os.read
        replaced = False
        def read(descriptor, count):
            nonlocal replaced
            block = real_read(descriptor, count)
            if not replaced:
                replacement = self.root / 'replacement.gpg'
                replacement.write_bytes(SYNTHETIC_KEYRING)
                replacement.chmod(0o644)
                replacement.replace(self.key)
                replaced = True
            return block
        with mock.patch.object(D.os, 'read', side_effect=read), self.assertRaisesRegex(ValueError, 'identity changed'):
            self.read()

    def test_isolated_copy_is_exact_readonly_and_only_rebinds_signing_location(self):
        original = self.key.read_bytes()
        self.key.chmod(0o777)
        source, _, _ = D.canonical_source(SOURCE, OS, 'amd64', MIRRORS)
        copied, snapshot, rebound = D.isolate_keyring(self.root, original, source)
        self.assertEqual(copied.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(self.key.stat().st_mode), 0o777)
        self.assertEqual(rebound.replace(str(copied).encode(), str(D.KEYRING).encode()).splitlines(),
                         [line for line in source.splitlines() if not line.startswith(b'#')])
        self.assertEqual(rebound.count(b'Signed-By: ' + str(copied).encode()), 2)
        D.verify_isolated_keyring(copied, snapshot)
        for mode in (0o644, 0o777):
            copied.chmod(mode)
            with self.assertRaisesRegex(ValueError, 'file identity'):
                D.verify_isolated_keyring(copied, snapshot)

    def test_isolated_copy_creation_never_overwrites_existing_file_or_link(self):
        destination = self.root / 'ubuntu-archive-keyring.gpg'
        destination.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            D.isolate_keyring(self.root, SYNTHETIC_KEYRING, SOURCE)
        self.assertEqual(destination.read_bytes(), b'existing')
        destination.unlink()
        destination.symlink_to(self.key)
        with self.assertRaises(FileExistsError):
            D.isolate_keyring(self.root, SYNTHETIC_KEYRING, SOURCE)
        self.assertEqual(self.key.read_bytes(), SYNTHETIC_KEYRING)

    def test_isolated_copy_replacement_with_identical_bytes_fails_snapshot(self):
        copied, snapshot, _ = D.isolate_keyring(self.root, SYNTHETIC_KEYRING, SOURCE)
        replacement = self.root / 'new-copy.gpg'
        replacement.write_bytes(SYNTHETIC_KEYRING)
        replacement.chmod(0o444)
        replacement.replace(copied)
        with self.assertRaisesRegex(ValueError, 'Temporary Ubuntu keyring identity changed'):
            D.verify_isolated_keyring(copied, snapshot)

    def test_signed_by_path_rejects_whitespace_commas_and_non_ascii_before_writing(self):
        for name in ('space path', 'tab\tpath', 'line\npath', 'comma,path', 'quote"path', 'nonascii-é'):
            work = self.root / name; work.mkdir()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'signing key path'):
                D.isolate_keyring(work, SYNTHETIC_KEYRING, SOURCE)
            self.assertEqual(list(work.iterdir()), [])

    def test_early_probe_distinguishes_writable_metadata_from_content_authentication(self):
        output, errors = io.StringIO(), io.StringIO()
        observed = {'scope': 'official-fixture-decoder-file-identity-only', 'files': [
            {'role': 'keyring', 'type': 'regular', 'uid': 0, 'mode': 0o777,
             'sizeBytes': 3607, 'failedChecks': ['writable-mode']}]}
        self.key.chmod(0o777)
        authenticated_reader = D.read_authenticated_keyring
        def original(path, owner):
            self.assertEqual(path, self.key)
            self.assertEqual(owner, 0)
            # Test files are caller-owned; the separate wrong-owner test checks
            # the real descriptor predicate, while this checks production UID0 routing.
            return authenticated_reader(path, os.getuid())
        with mock.patch.object(D, 'KEYRING', self.key), \
             mock.patch.object(D, 'configuration_file_identity', return_value=observed), \
             mock.patch.object(D.shutil, 'which', return_value=None), \
             mock.patch.object(D, 'read_public_file', side_effect=[SOURCE, MIRRORS]), \
             mock.patch.object(D, 'read_authenticated_keyring', side_effect=original) as inspected, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            D.main(['--check-files'])
        self.assertEqual(json.loads(output.getvalue()), observed)
        inspected.assert_called()
        self.assertEqual(errors.getvalue().strip(),
            'Authenticated original Ubuntu keyring SHA-256: ' + hashlib.sha256(SYNTHETIC_KEYRING).hexdigest())
        self.key.write_bytes(b'X' + SYNTHETIC_KEYRING[1:])
        with mock.patch.object(D, 'KEYRING', self.key), \
             mock.patch.object(D, 'configuration_file_identity', return_value=observed), \
             mock.patch.object(D.shutil, 'which', return_value=None), \
             mock.patch.object(D, 'read_public_file', return_value=SOURCE), \
             mock.patch.object(D, 'read_authenticated_keyring', side_effect=original), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
             self.assertRaises(SystemExit):
            D.main(['--check-files'])

    def test_keyring_os_failure_suppresses_arbitrary_paths_in_full_traceback(self):
        secret = '/PRIVATE_KEYRING_URL_ENV_SENTINEL'
        with mock.patch.object(D, 'configuration_file_identity', return_value={'scope': 'test', 'files': []}), \
             mock.patch.object(D.shutil, 'which', return_value=None), \
             mock.patch.object(D, 'read_public_file', return_value=SOURCE), \
             mock.patch.object(D.os, 'open', side_effect=OSError(13, secret, secret)), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            D.main(['--check-files'])
        self.assertNotIn(secret, ''.join(traceback.format_exception(caught.exception)))

    def test_keyring_read_is_bounded_and_descriptor_traversal_does_not_follow_links(self):
        real_open, real_read = os.open, os.read
        with mock.patch.object(D.os, 'open', wraps=real_open) as opened, \
             mock.patch.object(D.os, 'read', wraps=real_read) as reads:
            self.read()
        for call in opened.call_args_list:
            self.assertTrue(call.args[1] & os.O_NOFOLLOW)
        self.assertTrue(opened.call_args_list[-1].args[1] & os.O_NONBLOCK)
        self.assertTrue(all(0 < call.args[1] <= 3608 for call in reads.call_args_list))


class PublicWorkspaceTests(unittest.TestCase):
    def root_info(self, **changes):
        return SimpleNamespace(**(dict(st_dev=1, st_ino=2, st_mode=stat.S_IFDIR | 0o1777,
                                       st_uid=0, st_gid=0, st_mtime_ns=1, st_ctime_ns=1) | changes))

    def child_info(self, **changes):
        return SimpleNamespace(**(dict(st_dev=1, st_ino=3, st_mode=stat.S_IFDIR | 0o700,
                                       st_uid=os.getuid(), st_gid=os.getgid()) | changes))

    def exercise(self, root_changes=None, child_changes=None, replace_root=False, replace_child=False):
        root = self.root_info(**(root_changes or {}))
        child = self.child_info(**(child_changes or {}))
        after = self.child_info(st_mode=stat.S_IFDIR | 0o755)
        root_after = self.root_info(st_ino=4) if replace_root else root
        child_after = self.child_info(st_mode=stat.S_IFDIR | 0o755, st_ino=4) if replace_child else after
        output = io.StringIO()
        with mock.patch.object(Path, 'lstat', side_effect=[root, root_after, root_after]), \
             mock.patch.object(D.os, 'open', side_effect=[11, 12]) as opened, \
             mock.patch.object(D.os, 'fstat', side_effect=[root, child, after]), \
             mock.patch.object(D.os, 'stat', side_effect=[child, child_after]), \
             mock.patch.object(D.os, 'fchmod') as modes, mock.patch.object(D.os, 'close'), \
             mock.patch.object(D.tempfile, 'mkdtemp', return_value='/tmp/lightforge-ffmpeg-apt-fixture') as temporary, \
             mock.patch.object(Path, 'chmod') as parent_chmod, \
             mock.patch.dict(os.environ, {'RUNNER_TEMP': '/PRIVATE_RUNNER_SENTINEL', 'TMPDIR': '/PRIVATE_TMPDIR_SENTINEL'}), \
             contextlib.redirect_stdout(output):
            result, error = None, None
            try:
                result = D.create_public_workspace()
            except (D.DecoderValidationError, OSError) as caught:
                error = caught
        parent_chmod.assert_not_called()
        self.assertNotIn('PRIVATE_', output.getvalue())
        return result, error, opened, modes, temporary, output.getvalue()

    def test_only_fixed_verified_public_root_and_new_owned_child_are_used(self):
        result, error, opened, modes, temporary, output = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(D.PUBLIC_TEMP_ROOT, Path('/tmp'))
        self.assertEqual(result, Path('/tmp/lightforge-ffmpeg-apt-fixture'))
        temporary.assert_called_once_with(prefix='lightforge-ffmpeg-apt-', dir=Path('/tmp'))
        modes.assert_called_once_with(12, 0o755)
        self.assertEqual(opened.call_args_list[0].args[0], Path('/tmp'))
        self.assertEqual(opened.call_args_list[1].kwargs, {'dir_fd': 11})
        self.assertTrue(all(call.args[1] & os.O_NOFOLLOW for call in opened.call_args_list))
        records = list(map(json.loads, output.splitlines()))
        self.assertEqual([row['role'] for row in records], ['system-temp-root', 'owned-public-workspace'])
        self.assertEqual([row['mode'] for row in records], [0o1777, 0o755])
        self.assertNotIn('/tmp', output)

    def test_nonpublic_unowned_link_or_non_directory_root_fails_before_creation(self):
        for changes in ({'st_uid': 1001}, {'st_mode': stat.S_IFREG | 0o1777},
                        {'st_mode': stat.S_IFLNK | 0o777}, {'st_mode': stat.S_IFDIR | 0o777},
                        {'st_mode': stat.S_IFDIR | 0o1770}, {'st_mode': stat.S_IFDIR | 0o3777}):
            with self.subTest(changes=changes):
                _, error, opened, modes, temporary, _ = self.exercise(root_changes=changes)
                self.assertIsInstance(error, D.DecoderValidationError)
                temporary.assert_not_called()
                opened.assert_not_called()
                modes.assert_not_called()

    def test_unowned_preexisting_or_non_directory_child_is_never_chmodded(self):
        for changes in ({'st_uid': os.getuid() + 1}, {'st_mode': stat.S_IFDIR | 0o755},
                        {'st_mode': stat.S_IFDIR | 0o777}, {'st_mode': stat.S_IFREG | 0o700},
                        {'st_mode': stat.S_IFLNK | 0o700}):
            with self.subTest(changes=changes):
                _, error, _, modes, _, _ = self.exercise(child_changes=changes)
                self.assertIsInstance(error, D.DecoderValidationError)
                modes.assert_not_called()

    def test_parent_or_child_replacement_fails_closed(self):
        _, error, _, modes, _, _ = self.exercise(replace_root=True)
        self.assertRegex(str(error), 'root identity changed')
        modes.assert_not_called()
        _, error, _, modes, _, _ = self.exercise(replace_child=True)
        self.assertRegex(str(error), 'directory identity changed')
        modes.assert_called_once_with(12, 0o755)

    def test_metadata_does_not_reflect_hostile_labels_or_noninteger_fields(self):
        secret = 'SECRET_WORKSPACE_SENTINEL'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            D.public_directory_observation(SimpleNamespace(st_mode=secret, st_uid=secret, st_gid=secret), secret)
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(json.loads(output.getvalue()), {'scope': 'official-fixture-decoder-public-workspace',
            'role': 'unknown-role', 'type': 'not-directory', 'uid': None, 'gid': None, 'mode': None})


class DecoderStageDiagnosticsTests(unittest.TestCase):
    def test_every_declared_stage_is_used_and_allowlist_is_complete(self):
        tree = ast.parse((ROOT / 'tools/prepare_fixture_decoder.py').read_text())
        stages = {node.args[0].value for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == 'external_stage'}
        self.assertEqual(stages, D.EXTERNAL_STAGES)

    def test_external_failure_stage_is_safe_and_specific_even_in_traceback(self):
        secret = '/SECRET_STAGE_ENV_ARGV_URL_SENTINEL'
        failures = [(OSError(13, secret, secret), 'os-error', {'errno': 13}),
                    (subprocess.CalledProcessError(1, [secret], output=secret, stderr=secret), 'subprocess-exit', {'exitCode': 1}),
                    (subprocess.TimeoutExpired(secret, 600, output=secret), 'subprocess-timeout', {}),
                    (subprocess.SubprocessError(secret), 'subprocess-error', {}),
                    (ValueError(secret), 'invalid-value', {}), (KeyError(secret), 'missing-input', {})]
        for stage in sorted(D.EXTERNAL_STAGES):
            for external, reason, numeric in failures:
                def prepare():
                    with D.external_stage(stage):
                        raise external
                with self.subTest(stage=stage, reason=reason), mock.patch.object(D, 'prepare', side_effect=prepare), \
                     self.assertRaises(SystemExit) as caught:
                    D.main()
                report = str(caught.exception)
                self.assertNotIn(secret, ''.join(traceback.format_exception(caught.exception)))
                record = json.loads(report.split(': ', 1)[1])
                self.assertEqual(record, {'scope': 'official-fixture-decoder-failure', 'stage': stage,
                                          'reason': reason, **numeric})

    def test_unknown_labels_and_out_of_range_codes_are_never_reflected(self):
        secret = 'SECRET_STAGE_SENTINEL'
        for code in (secret, 999999999999, 1.5, True, -99999):
            with self.subTest(code=type(code).__name__):
                record = D.stage_failure_record(D.DecoderStageError(secret, secret, code))
                self.assertEqual(record, {'scope': 'official-fixture-decoder-failure',
                                          'stage': 'unknown-stage', 'reason': 'unknown-reason'})
                for reason in ('os-error', 'subprocess-exit'):
                    value = D.stage_failure_record(D.DecoderStageError('apt-update', reason, code))
                    self.assertEqual(set(value), {'scope', 'stage', 'reason'})


if __name__ == '__main__':
    unittest.main()
