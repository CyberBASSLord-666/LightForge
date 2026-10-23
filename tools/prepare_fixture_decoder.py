#!/usr/bin/env python3
"""Prepare the official Ubuntu fixture decoder without persistent APT edits.

Only missing-decoder setup changes: preserve the installed Ubuntu source's
suites/components/architecture/signing key, selecting Canonical HTTPS transport
instead of Azure mirror priority. No package-byte equivalence is asserted;
the existing canonical decoded-fixture hashes remain mandatory.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile

SOURCE = Path('/etc/apt/sources.list.d/ubuntu.sources')
KEYRING = Path('/usr/share/keyrings/ubuntu-archive-keyring.gpg')
# Independently checked against Canonical's Noble Packages index and package:
# https://packages.ubuntu.com/noble/all/ubuntu-keyring/download
# ubuntu-keyring_2023.11.28.1_all.deb SHA-256:
# 36de43b15853ccae0028e9a767613770c704833f82586f28eb262f0311adb8a8
# This authenticates the existing original bytes; no key is downloaded/imported.
KEYRING_SHA256 = '80a36b0a6de2f69f49d2df75ef473ccde121e9e190b9ea01d20a4f63778d5c31'
KEYRING_BYTES = 3607
MIRRORS = Path('/etc/apt/apt-mirrors.txt')
MIRROR_URI = 'mirror+file:/etc/apt/apt-mirrors.txt'
ARCHIVE = 'https://archive.ubuntu.com/ubuntu/'
SECURITY = 'https://security.ubuntu.com/ubuntu/'
OFFICIAL_URIS = {scheme + '://' + host + '/ubuntu' + slash
    for scheme in ('http', 'https')
    for host in ('azure.archive.ubuntu.com', 'archive.ubuntu.com', 'security.ubuntu.com')
    for slash in ('', '/')}


# Only these source-owned constants may cross the diagnostic boundary.
VALIDATION_REASONS = frozenset({
    'Ambiguous Ubuntu source fields',
    'Duplicate Ubuntu source target',
    'Incomplete original Ubuntu package sources',
    'Missing-decoder setup requires the reviewed Ubuntu 24.04 amd64 source',
    'Official decoder installation did not provide ffmpeg',
    'Official runner mirror definition is missing',
    'Original Ubuntu source or signing key changed during setup',
    'Original Ubuntu keyring content is not the authenticated Noble keyring',
    'Ubuntu keyring file identity changed during read',
    'Unsupported Ubuntu keyring file identity',
    'Temporary Ubuntu keyring identity changed',
    'Temporary Ubuntu signing key path is unsupported',
    'Runner temporary directory is unavailable or indirect',
    'Ubuntu source signing key or architecture differs',
    'Unrecognized Ubuntu archive URI',
    'Unrecognized runner mirror definition',
    'Unreviewed foreign package architecture',
    'Unsupported Ubuntu configuration file identity',
    'Unsupported Ubuntu source components',
    'Unsupported Ubuntu source encoding',
    'Unsupported Ubuntu source options',
    'Unsupported Ubuntu source paragraph count',
    'Unsupported Ubuntu source stanza count',
    'Unsupported Ubuntu source suites',
})


class DecoderValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise DecoderValidationError(message)


def read_public_file(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
            and 0 < info.st_size <= 1024 * 1024, 'Unsupported Ubuntu configuration file identity')
    return path.read_bytes()


def read_authenticated_keyring(path, owner, *, copied=False):
    """Reject link traversal and authenticate bounded bytes from one stable file."""
    descriptors = []
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    try:
        require(path.is_absolute() and '..' not in path.parts, 'Unsupported Ubuntu keyring file identity')
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptors.append(os.open('/', directory_flags))
        for component in path.parts[1:-1]:
            descriptors.append(os.open(component, directory_flags, dir_fd=descriptors[-1]))
        parent = descriptors[-1]
        descriptors.append(os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent))
        descriptor = descriptors[-1]
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        allowed_mode = mode == 0o444 if copied else (not mode & 0o7022 or mode == 0o777)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner and allowed_mode
                and before.st_size == KEYRING_BYTES, 'Unsupported Ubuntu keyring file identity')
        blocks, remaining = [], KEYRING_BYTES + 1
        while remaining:
            block = os.read(descriptor, remaining)
            if not block:
                break
            blocks.append(block)
            remaining -= len(block)
        raw = b''.join(blocks)
        require(identity(os.fstat(descriptor)) == identity(before)
                and identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) == identity(before),
                'Ubuntu keyring file identity changed during read')
        require(len(raw) == KEYRING_BYTES and hashlib.sha256(raw).hexdigest() == KEYRING_SHA256,
                'Original Ubuntu keyring content is not the authenticated Noble keyring')
        return raw, identity(before)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def isolate_keyring(work, keyring, source):
    destination = work / 'ubuntu-archive-keyring.gpg'
    # APT's list-valued Signed-By parser does not quote/escape path whitespace.
    require(re.fullmatch(r'/[A-Za-z0-9_./-]+', str(destination)) is not None,
            'Temporary Ubuntu signing key path is unsupported')
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(keyring)
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
    copied, snapshot = read_authenticated_keyring(destination, os.getuid(), copied=True)
    require(copied == keyring, 'Temporary Ubuntu keyring identity changed')
    rebound = re.sub(rb'(?m)^Signed-By:[^\n]+$',
                     lambda match: b'Signed-By: ' + str(destination).encode('ascii'), source)
    return destination, snapshot, rebound


def verify_isolated_keyring(path, snapshot):
    _, observed = read_authenticated_keyring(path, os.getuid(), copied=True)
    require(observed == snapshot, 'Temporary Ubuntu keyring identity changed')


def configuration_file_identity():
    """Bounded read-only metadata, never paths, link targets or file contents."""
    def integer(value, maximum):
        return value if type(value) is int and 0 <= value <= maximum else None

    files = []
    for role, path in (('source', SOURCE), ('keyring', KEYRING), ('mirrors', MIRRORS)):
        record = {'role': role}
        try:
            info = path.lstat()
        except OSError as error:
            record.update(type='unavailable', errno=integer(error.errno, 4095),
                          failedChecks=['metadata-unavailable'])
        else:
            mode = integer(info.st_mode, 0xffffffff)
            uid = integer(info.st_uid, 0xffffffff)
            size = integer(info.st_size, 0x7fffffffffffffff)
            kind = ('unavailable' if mode is None else 'regular' if stat.S_ISREG(mode)
                    else 'symlink' if stat.S_ISLNK(mode) else 'directory' if stat.S_ISDIR(mode) else 'other')
            failures = []
            if kind != 'regular':
                failures.append('file-type')
            if uid != 0:
                failures.append('owner')
            if mode is None or mode & 0o022:
                failures.append('writable-mode')
            if size is None or not 0 < size <= 1024 * 1024:
                failures.append('size')
            record.update(type=kind, uid=uid, mode=None if mode is None else stat.S_IMODE(mode),
                          sizeBytes=size, failedChecks=failures)
        files.append(record)
    return {'scope': 'official-fixture-decoder-file-identity-only', 'files': files}


def print_configuration_file_identity():
    print(json.dumps(configuration_file_identity(), sort_keys=True), flush=True)


def read_configuration_files():
    raw = read_public_file(SOURCE)
    keyring, _ = read_authenticated_keyring(KEYRING, 0)
    mirror_raw = read_public_file(MIRRORS) if MIRROR_URI.encode() in raw else None
    return raw, keyring, mirror_raw


def canonical_source(raw, distribution, architecture, mirror_raw=None):
    require(distribution.get('ID') == 'ubuntu' and distribution.get('VERSION_ID') == '24.04'
            and distribution.get('VERSION_CODENAME') == 'noble' and architecture == 'amd64',
            'Missing-decoder setup requires the reviewed Ubuntu 24.04 amd64 source')
    text = raw.decode('utf-8')
    require('\r' not in text and len(text) <= 65536, 'Unsupported Ubuntu source encoding')
    paragraphs = re.split(r'\n\s*\n', text.strip())
    require(0 < len(paragraphs) <= 32, 'Unsupported Ubuntu source paragraph count')
    output, suites, components, seen = [], set(), set(), set()
    stanza_count = 0
    for paragraph in paragraphs:
        fields = {}
        for line in paragraph.splitlines():
            if not line or line.startswith('#'):
                continue
            match = re.fullmatch(r'([A-Za-z-]+):[ \t]+([^\r\n]+)', line)
            require(match is not None and match[1] not in fields, 'Ambiguous Ubuntu source fields')
            fields[match[1]] = match[2].strip()
        if not fields:
            output.append(paragraph)
            continue
        stanza_count += 1
        require(stanza_count <= 4, 'Unsupported Ubuntu source stanza count')
        require(set(fields) in ({'Types', 'URIs', 'Suites', 'Components', 'Signed-By'},
                               {'Types', 'URIs', 'Suites', 'Components', 'Signed-By', 'Architectures'}),
                'Unsupported Ubuntu source options')
        require(fields['Types'] == 'deb' and fields['Signed-By'] == str(KEYRING)
                and fields.get('Architectures', architecture) == architecture,
                'Ubuntu source signing key or architecture differs')
        stanza_suites, stanza_components = fields['Suites'].split(), fields['Components'].split()
        require(stanza_suites and len(stanza_suites) == len(set(stanza_suites))
                and set(stanza_suites) <= {'noble', 'noble-updates', 'noble-security', 'noble-backports'},
                'Unsupported Ubuntu source suites')
        require(stanza_components and len(stanza_components) == len(set(stanza_components))
                and set(stanza_components) <= {'main', 'restricted', 'universe', 'multiverse'},
                'Unsupported Ubuntu source components')
        for suite in stanza_suites:
            for component in stanza_components:
                require((suite, component) not in seen, 'Duplicate Ubuntu source target')
                seen.add((suite, component))
        uri = fields['URIs']
        require(uri in OFFICIAL_URIS or uri == MIRROR_URI, 'Unrecognized Ubuntu archive URI')
        if uri == MIRROR_URI:
            require(mirror_raw is not None, 'Official runner mirror definition is missing')
            mirror_lines = mirror_raw.decode('ascii').splitlines()
            mirrors = [line.split() for line in mirror_lines if line.strip() and not line.startswith('#')]
            require(mirrors == [['http://azure.archive.ubuntu.com/ubuntu/', 'priority:1'],
                                [ARCHIVE, 'priority:2'], [SECURITY, 'priority:3']],
                    'Unrecognized runner mirror definition')
        replacement = SECURITY if all(suite == 'noble-security' for suite in stanza_suites) else ARCHIVE
        # Preserve every non-URI source line, including signing/architecture settings.
        output.append(re.sub(r'(?m)^URIs:[^\n]+$', 'URIs: ' + replacement, paragraph))
        suites.update(stanza_suites)
        components.update(stanza_components)
    require({'noble', 'noble-updates', 'noble-security'} <= suites
            and {'main', 'universe'} <= components, 'Incomplete original Ubuntu package sources')
    return ('\n\n'.join(output) + '\n').encode(), sorted(suites), sorted(components)


def apt_command(work, action):
    options = {
        'Dir::Etc::sourcelist': str(work / 'ubuntu.sources'),
        'Dir::Etc::sourceparts': str(work / 'sourceparts'),
        'Dir::State::lists': str(work / 'lists'),
        'Dir::Cache::archives': str(work / 'archives'),
        'Dir::Cache::pkgcache': str(work / 'pkgcache.bin'),
        'Dir::Cache::srcpkgcache': str(work / 'srcpkgcache.bin'),
        'Acquire::Retries': '2',
        'Acquire::http::Timeout': '30',
        'Acquire::https::Timeout': '30',
        'APT::Update::Error-Mode': 'any',
    }
    return ['sudo', 'apt-get', *[item for key, value in options.items() for item in ('-o', key + '=' + value)], *action]


def prepare():
    existing = shutil.which('ffmpeg')
    if existing:
        subprocess.run([existing, '-version'], check=True, timeout=30)
        return
    distribution = platform.freedesktop_os_release()
    architecture = subprocess.check_output(['dpkg', '--print-architecture'], text=True, timeout=10).strip()
    foreign = subprocess.check_output(['dpkg', '--print-foreign-architectures'], text=True, timeout=10).strip()
    require(not foreign, 'Unreviewed foreign package architecture')
    print_configuration_file_identity()
    raw, keyring, mirror_raw = read_configuration_files()
    source, suites, components = canonical_source(raw, distribution, architecture, mirror_raw)
    parent = Path(os.environ['RUNNER_TEMP'])
    require(parent.is_absolute() and parent.is_dir() and parent.resolve() == parent,
            'Runner temporary directory is unavailable or indirect')
    work = Path(tempfile.mkdtemp(prefix='lightforge-ffmpeg-apt-', dir=parent))
    # Public archive metadata only. The existing _apt sandbox must be able to
    # traverse/read it; no sandbox disablement or root-download fallback.
    work.chmod(0o755)
    for name in ('sourceparts', 'lists', 'archives'):
        (work / name).mkdir(mode=0o755)
        (work / name).chmod(0o755)
    isolated_keyring, keyring_snapshot, source = isolate_keyring(work, keyring, source)
    (work / 'ubuntu.sources').write_bytes(source)
    (work / 'ubuntu.sources').chmod(0o644)
    subprocess.run(['sudo', '-u', '_apt', 'test', '-r', str(work / 'ubuntu.sources')], check=True, timeout=10)
    subprocess.run(['sudo', '-u', '_apt', 'test', '-r', str(isolated_keyring)], check=True, timeout=10)
    print(json.dumps(dict(scope='official-fixture-decoder-setup-only', distribution='ubuntu-24.04',
        architecture=architecture, suites=suites, components=components,
        originalSourceSha256=hashlib.sha256(raw).hexdigest(),
        temporarySourceSha256=hashlib.sha256(source).hexdigest(),
        signingKeyringSha256=hashlib.sha256(keyring).hexdigest()), sort_keys=True), flush=True)
    # These overrides affect only these two calls. No /etc, trust, TLS, proxy or
    # network settings are written. No privileged recursive cleanup is used:
    # the disposable runner removes its temporary metadata/cache at teardown.
    verify_isolated_keyring(isolated_keyring, keyring_snapshot)
    subprocess.run(apt_command(work, ['update', '-qq']), check=True, timeout=180)
    verify_isolated_keyring(isolated_keyring, keyring_snapshot)
    subprocess.run(apt_command(work, ['install', '-y', '--no-install-recommends', 'ffmpeg']),
                   check=True, timeout=600)
    verify_isolated_keyring(isolated_keyring, keyring_snapshot)
    require(read_public_file(SOURCE) == raw and read_authenticated_keyring(KEYRING, 0)[0] == keyring
            and (mirror_raw is None or read_public_file(MIRRORS) == mirror_raw),
            'Original Ubuntu source or signing key changed during setup')
    decoder = shutil.which('ffmpeg')
    require(decoder is not None, 'Official decoder installation did not provide ffmpeg')
    subprocess.run([decoder, '-version'], check=True, timeout=30)


def main(arguments=()):
    try:
        if arguments:
            if list(arguments) not in (['--diagnose-files'], ['--check-files']):
                raise SystemExit('Unsupported fixture decoder command')
            print_configuration_file_identity()
            if list(arguments) == ['--check-files'] and not shutil.which('ffmpeg'):
                _, keyring, _ = read_configuration_files()
                print('Authenticated original Ubuntu keyring SHA-256: ' + hashlib.sha256(keyring).hexdigest(), file=sys.stderr)
            return
        prepare()
    except DecoderValidationError as error:
        observed_reason = str(error)
        reason = observed_reason if observed_reason in VALIDATION_REASONS else 'Unrecognized validation failure'
        raise SystemExit('Official fixture decoder preparation failed closed: ' + reason) from None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        # Do not reflect environment, arbitrary source rows, or command arguments.
        raise SystemExit('Official fixture decoder preparation failed closed') from None


if __name__ == '__main__':
    main(sys.argv[1:])
