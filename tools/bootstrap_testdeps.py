#!/usr/bin/env python3
"""Pinned host-JVM JSON implementation; Android's SDK jar contains only stubs."""
import hashlib
import os
from pathlib import Path
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain')) / 'test-json.jar'
SHA = 'c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6'
SIZE = 90031
URL = 'https://repo.maven.apache.org/maven2/org/json/json/20260719/json-20260719.jar'


def matches(path):
    if not path.is_file() or path.stat().st_size != SIZE:
        return False
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest() == SHA


def prepare():
    if matches(DEST):
        return
    DEST.parent.mkdir(parents=True, exist_ok=True)
    # Unique same-directory temporary files prevent concurrent bootstraps
    # from replacing a file another writer has not finished validating.
    with tempfile.NamedTemporaryFile(dir=DEST.parent, prefix=DEST.name + '.', suffix='.part', delete=False) as output:
        temp = Path(output.name)
        try:
            received = 0
            checksum = hashlib.sha256()
            deadline = time.monotonic() + 120
            with urllib.request.urlopen(URL, timeout=60) as response:
                while chunk := response.read(min(1024 * 1024, SIZE - received + 1)):
                    received += len(chunk)
                    if received > SIZE or time.monotonic() > deadline:
                        raise RuntimeError('Test dependency download limit exceeded.')
                    checksum.update(chunk)
                    output.write(chunk)
            if received != SIZE or checksum.hexdigest() != SHA:
                raise RuntimeError('Test dependency checksum mismatch.')
            output.flush()
            os.fsync(output.fileno())
            os.replace(temp, DEST)
        finally:
            temp.unlink(missing_ok=True)


if __name__ == '__main__':
    prepare()
    print('Verified org.json 20260719 host-test dependency.')
