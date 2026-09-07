#!/usr/bin/env python3
"""Pinned host-JVM JSON implementation; Android's SDK jar contains only stubs."""
import hashlib, os, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST=Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR',ROOT.parent/'toolchain'))/'test-json.jar'
SHA='3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed'
if not DEST.is_file() or hashlib.sha256(DEST.read_bytes()).hexdigest()!=SHA:
    data=urllib.request.urlopen('https://repo.maven.apache.org/maven2/org/json/json/20240303/json-20240303.jar',timeout=60).read()
    if len(data)!=78332 or hashlib.sha256(data).hexdigest()!=SHA:raise SystemExit('Test dependency checksum mismatch.')
    DEST.parent.mkdir(parents=True,exist_ok=True);part=DEST.with_suffix('.part');part.write_bytes(data);os.replace(part,DEST)
print('Verified org.json 20240303 host-test dependency.')
