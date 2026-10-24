#!/usr/bin/env python3
"""Install pinned, official build dependencies on Linux x86_64 (Python >=3.12)."""
from __future__ import annotations
import concurrent.futures
import fcntl
import hashlib
import json
import os
import platform
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', PROJECT.parent / 'toolchain')).resolve()
PACKAGES = [
    dict(name='build-tools_r35_linux.zip',
         url='https://dl.google.com/android/repository/build-tools_r35_linux.zip',
         sha256='bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88',
         size=61958799, source='android-15', target='android-sdk/build-tools/35.0.0', check='aapt2'),
    dict(name='platform-35_r02.zip',
         url='https://dl.google.com/android/repository/platform-35_r02.zip',
         sha256='0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0',
         size=64273788, source='android-35', target='android-sdk/platforms/android-35', check='android.jar'),
    dict(name='jdk17.tar.gz',
         url='https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.21%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.21_9.tar.gz',
         sha256='8b9b611d917e3dfd8419d3566b5949226f69b052fed7e109c1368add1dfe8711',
         size=193594705, source='jdk-17.0.21+9', target='jdk17', check='bin/javac'),
]

def digest(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def download(p):
    path = DEST / 'downloads' / p['name']
    if not (path.is_file() and path.stat().st_size == p['size'] and digest(path) == p['sha256']):
        print('Downloading ' + p['name'], flush=True)
        # A pinned JDK archive is ~193 MB. Stream instead of retaining the
        # entire response, and use unique siblings so concurrent bootstraps
        # cannot truncate or replace each other's in-progress download.
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.',
                                         suffix='.part', delete=False) as output:
            temp = Path(output.name)
            try:
                received = 0
                checksum = hashlib.sha256()
                with urllib.request.urlopen(p['url'], timeout=240) as response:
                    while chunk := response.read(1024 * 1024):
                        received += len(chunk)
                        if received > p['size']:
                            raise RuntimeError('Download integrity failure: ' + p['name'])
                        checksum.update(chunk)
                        output.write(chunk)
                if received != p['size'] or checksum.hexdigest() != p['sha256']:
                    raise RuntimeError('Download integrity failure: ' + p['name'])
                output.flush()
                os.fsync(output.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
    print('Verified ' + p['name'], flush=True)
    return p, path

INSTALL_RECEIPT = '.lightforge-package.json'


def inventory(root):
    """Compare installed bytes, modes and links, not a forgeable receipt alone."""
    result = {'.': ('directory', stat.S_IMODE(root.lstat().st_mode))}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if relative == INSTALL_RECEIPT:
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            value = ('link', os.readlink(path))
        elif stat.S_ISREG(mode):
            value = ('file', stat.S_IMODE(mode), digest(path))
        elif stat.S_ISDIR(mode):
            value = ('directory', stat.S_IMODE(mode))
        else:
            raise RuntimeError('Unsupported installed file: ' + str(path))
        result[relative] = value
    return result


def install(p, archive):
    # Serialize managed writers and never merge an extraction into an existing
    # directory. A legacy, changed or differently pinned install needs a new
    # LIGHTFORGE_TOOLCHAIN_DIR; it is never silently overwritten or deleted.
    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / '.install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _install(p, archive)


def _install(p, archive):
    relative = Path(p['target'])
    if relative.is_absolute() or '..' in relative.parts or relative == Path('.'):
        raise RuntimeError('Unsafe installation target: ' + p['target'])
    target = DEST / relative
    # A managed leaf must not publish through an unmanaged ancestor symlink.
    parent = DEST
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise RuntimeError('Unsafe installation ancestor: ' + str(parent))
    if not (archive.is_file() and archive.stat().st_size == p['size']
            and digest(archive) == p['sha256']):
        raise RuntimeError('Install archive integrity failure: ' + p['name'])
    exists = target.exists() or target.is_symlink()
    if exists:
        receipt = target / INSTALL_RECEIPT
        try:
            managed = (not target.is_symlink() and receipt.is_file()
                       and not receipt.is_symlink()
                       and json.loads(receipt.read_text()) == p)
        except (OSError, ValueError):
            managed = False
        if not managed:
            raise RuntimeError('Unmanaged or differently pinned installation: '
                               + str(target) + '; choose a fresh LIGHTFORGE_TOOLCHAIN_DIR')
    with tempfile.TemporaryDirectory(dir=DEST) as temp:
        scratch = Path(temp)
        if archive.suffix == '.zip':
            with zipfile.ZipFile(archive) as z:
                if z.testzip():
                    raise RuntimeError('Invalid ZIP: ' + str(archive))
                for item in z.infolist():
                    rel = Path(item.filename)
                    if rel.is_absolute() or '..' in rel.parts:
                        raise RuntimeError('Unsafe archive path: ' + item.filename)
                    z.extract(item, scratch)
                    if not item.is_dir():
                        mode = item.external_attr >> 16
                        if mode & 0o111:
                            (scratch / item.filename).chmod(0o755)
        else:
            with tarfile.open(archive) as t:
                t.extractall(scratch, filter='data')
        source = scratch / p['source']
        if not source.is_dir() or source.is_symlink() or not (source / p['check']).is_file():
            raise RuntimeError('Incomplete package: ' + p['name'])
        if exists:
            if inventory(target) != inventory(source):
                raise RuntimeError('Changed managed installation: ' + str(target)
                                   + '; choose a fresh LIGHTFORGE_TOOLCHAIN_DIR')
            print('Verified installed ' + str(target), flush=True)
            return
        (source / INSTALL_RECEIPT).write_text(json.dumps(p, sort_keys=True) + '\n')
        target.parent.mkdir(parents=True, exist_ok=True)
        # The lock coordinates concurrent bootstrap processes.
        source.rename(target)
    print('Installed ' + str(target), flush=True)

def main():
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise SystemExit('This pinned bootstrap supports Linux x86_64. For other systems, install JDK17 and Android SDK35, then set LIGHTFORGE_JAVA_HOME and ANDROID_SDK_ROOT for build.sh.')
    (DEST / 'downloads').mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fetched = list(pool.map(download, PACKAGES))
    for p, archive in fetched:
        install(p, archive)
    (DEST / 'toolchain-lock.json').write_text(json.dumps(PACKAGES, indent=2)+'\n')
    subprocess.run([str(DEST/'jdk17/bin/javac'), '-version'], check=True)
    subprocess.run([str(DEST/'android-sdk/build-tools/35.0.0/aapt2'), 'version'], check=True)
    subprocess.run([__import__('sys').executable, str(PROJECT/'tools/bootstrap_native_runtime.py')], check=True)
    print('Build toolchain ready. Run bash build.sh from ' + str(PROJECT))

if __name__ == '__main__':
    main()
