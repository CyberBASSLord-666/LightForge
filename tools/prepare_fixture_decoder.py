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
import tempfile

SOURCE = Path('/etc/apt/sources.list.d/ubuntu.sources')
KEYRING = Path('/usr/share/keyrings/ubuntu-archive-keyring.gpg')
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
    raw = read_public_file(SOURCE)
    keyring = read_public_file(KEYRING)
    mirror_raw = read_public_file(MIRRORS) if MIRROR_URI.encode() in raw else None
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
    (work / 'ubuntu.sources').write_bytes(source)
    (work / 'ubuntu.sources').chmod(0o644)
    subprocess.run(['sudo', '-u', '_apt', 'test', '-r', str(work / 'ubuntu.sources')], check=True, timeout=10)
    print(json.dumps(dict(scope='official-fixture-decoder-setup-only', distribution='ubuntu-24.04',
        architecture=architecture, suites=suites, components=components,
        originalSourceSha256=hashlib.sha256(raw).hexdigest(),
        temporarySourceSha256=hashlib.sha256(source).hexdigest(),
        signingKeyringSha256=hashlib.sha256(keyring).hexdigest()), sort_keys=True), flush=True)
    # These overrides affect only these two calls. No /etc, trust, TLS, proxy or
    # network settings are written. No privileged recursive cleanup is used:
    # the disposable runner removes its temporary metadata/cache at teardown.
    subprocess.run(apt_command(work, ['update', '-qq']), check=True, timeout=180)
    subprocess.run(apt_command(work, ['install', '-y', '--no-install-recommends', 'ffmpeg']),
                   check=True, timeout=600)
    require(read_public_file(SOURCE) == raw and read_public_file(KEYRING) == keyring,
            'Original Ubuntu source or signing key changed during setup')
    decoder = shutil.which('ffmpeg')
    require(decoder is not None, 'Official decoder installation did not provide ffmpeg')
    subprocess.run([decoder, '-version'], check=True, timeout=30)


def main():
    try:
        prepare()
    except DecoderValidationError as error:
        observed_reason = str(error)
        reason = observed_reason if observed_reason in VALIDATION_REASONS else 'Unrecognized validation failure'
        raise SystemExit('Official fixture decoder preparation failed closed: ' + reason) from None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        # Do not reflect environment, arbitrary source rows, or command arguments.
        raise SystemExit('Official fixture decoder preparation failed closed') from None


if __name__ == '__main__':
    main()
