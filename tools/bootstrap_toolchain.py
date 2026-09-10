#!/usr/bin/env python3
"""Install pinned, official build dependencies on Linux x86_64 (Python >=3.12)."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import os
import platform
import shutil
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
         url='https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20.1_1.tar.gz',
         sha256='3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e',
         size=193252603, source='jdk-17.0.20.1+1', target='jdk17', check='bin/javac'),
]

def digest(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def download(p):
    path = DEST / 'downloads' / p['name']
    if not (path.is_file() and path.stat().st_size == p['size'] and digest(path) == p['sha256']):
        print('Downloading ' + p['name'], flush=True)
        with urllib.request.urlopen(p['url'], timeout=240) as response:
            data = response.read()
        if len(data) != p['size'] or hashlib.sha256(data).hexdigest() != p['sha256']:
            raise RuntimeError('Download integrity failure: ' + p['name'])
        temp = path.with_suffix(path.suffix + '.part')
        with temp.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    print('Verified ' + p['name'], flush=True)
    return p, path

def install(p, archive):
    target = DEST / p['target']
    if (target / p['check']).is_file():
        print('Already installed ' + str(target), flush=True)
        return
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
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(scratch / p['source']), str(target))
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
    subprocess.run([__import__('sys').executable, str(PROJECT/'tools/bootstrap_androidx_runtime.py')], check=True)
    print('Build toolchain ready. Run bash build.sh from ' + str(PROJECT))

if __name__ == '__main__':
    main()
