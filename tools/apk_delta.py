#!/usr/bin/env python3
"""Transfer APK signatures and ZIP metadata without private keys or model copies.

The delta contains literal public APK bytes and bounded copy instructions from
one SHA-256-pinned CI candidate. Applying it produces the exact locally signed
APK, never a newly signed file. Android signature verification remains mandatory.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import zipfile

BLOCK = 1024 * 1024
MAX_LITERAL = 8 * BLOCK
MAX_APK = 2 * 1024**3


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def region_hash(stream, start, size):
    stream.seek(start)
    result = hashlib.sha256()
    while size:
        chunk = stream.read(min(BLOCK, size))
        if not chunk:
            raise ValueError('Truncated APK region')
        result.update(chunk)
        size -= len(chunk)
    return result.hexdigest()


def entries(path):
    with zipfile.ZipFile(path) as archive, Path(path).open('rb') as source:
        info = archive.infolist()
        if len({item.filename for item in info}) != len(info):
            raise ValueError('Duplicate APK entries')
        result = {}
        for item in info:
            source.seek(item.header_offset)
            header = source.read(30)
            if len(header) != 30 or header[:4] != b'PK\x03\x04':
                raise ValueError('Invalid local ZIP header')
            names, extra = struct.unpack_from('<HH', header, 26)
            start = item.header_offset + 30 + names + extra
            result[item.filename] = (start, item.compress_size,
                                     region_hash(source, start, item.compress_size))
        return result


def catalog(path):
    path = Path(path)
    return {'schema': 1, 'base_bytes': path.stat().st_size,
            'base_sha256': digest(path), 'entries': entries(path)}


def make_delta(base, target, from_catalog=False):
    base, target = Path(base), Path(target)
    if not 0 < target.stat().st_size < MAX_APK:
        raise ValueError('APK exceeds release size bounds')
    source = json.loads(base.read_text()) if from_catalog else catalog(base)
    if source.get('schema') != 1:
        raise ValueError('Invalid candidate catalog')
    before = {name: tuple(value) for name, value in source['entries'].items()}
    after = entries(target)
    operations, position, literal_bytes = [], 0, 0
    with target.open('rb') as stream:
        def literal(start, size):
            nonlocal literal_bytes
            if not size:
                return
            literal_bytes += size
            if literal_bytes > MAX_LITERAL:
                raise ValueError('Delta exceeds 8 MiB; candidate payloads differ')
            stream.seek(start)
            operations.append({'data': base64.b64encode(stream.read(size)).decode('ascii')})
        for name, (start, size, checksum) in sorted(after.items(), key=lambda row: row[1][0]):
            match = before.get(name)
            if match and match[1:] == (size, checksum) and size:
                literal(position, start - position)
                operations.append({'offset': match[0], 'bytes': size})
                position = start + size
        literal(position, target.stat().st_size - position)
    return {'schema': 1, 'base_bytes': source['base_bytes'], 'base_sha256': source['base_sha256'],
            'target_bytes': target.stat().st_size, 'target_sha256': digest(target),
            'literal_bytes': literal_bytes, 'operations': operations}


def apply_delta(base, document, destination):
    base, destination = Path(base), Path(destination)
    if document.get('schema') != 1 or base.stat().st_size != document['base_bytes'] or digest(base) != document['base_sha256']:
        raise ValueError('CI candidate identity mismatch')
    if not isinstance(document['target_bytes'], int) or not 0 < document['target_bytes'] < MAX_APK:
        raise ValueError('Invalid target size')
    if destination.resolve() == base.resolve():
        raise ValueError('Output must differ from the candidate')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.apk-delta-', dir=destination.parent)
    total, literals, checksum = 0, 0, hashlib.sha256()
    try:
        with os.fdopen(fd, 'wb') as output, base.open('rb') as source:
            def write(chunk):
                nonlocal total
                total += len(chunk)
                if total > document['target_bytes']:
                    raise ValueError('Output exceeds declared size')
                checksum.update(chunk)
                output.write(chunk)
            for op in document['operations']:
                if set(op) == {'data'}:
                    if len(op['data']) > MAX_LITERAL * 2:
                        raise ValueError('Oversized literal')
                    chunk = base64.b64decode(op['data'], validate=True)
                    literals += len(chunk)
                    if literals > MAX_LITERAL:
                        raise ValueError('Too much literal data')
                    write(chunk)
                elif set(op) == {'offset', 'bytes'}:
                    start, remaining = op['offset'], op['bytes']
                    if type(start) is not int or type(remaining) is not int or start < 0 or remaining <= 0 or start + remaining > document['base_bytes']:
                        raise ValueError('Invalid copy bounds')
                    source.seek(start)
                    while remaining:
                        chunk = source.read(min(BLOCK, remaining))
                        if not chunk:
                            raise ValueError('Truncated candidate')
                        write(chunk)
                        remaining -= len(chunk)
                else:
                    raise ValueError('Unknown delta operation')
            output.flush()
            os.fsync(output.fileno())
        if total != document['target_bytes'] or checksum.hexdigest() != document['target_sha256'] or literals != document['literal_bytes']:
            raise ValueError('Signed APK identity mismatch')
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('Reconstructed APK CRC failure')
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['make', 'apply', 'catalog'])
    parser.add_argument('--from-catalog', action='store_true', help='Make from the verified CI ZIP index instead of downloading its complete APK')
    parser.add_argument('base', type=Path)
    parser.add_argument('input', type=Path, help='Signed APK for make; delta JSON for apply')
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    if args.command == 'catalog':
        args.input.write_text(json.dumps(catalog(args.base), separators=(',', ':')) + '\n')
    elif args.command == 'make':
        if args.output is None:parser.error('make requires an output path')
        value = make_delta(args.base, args.input, from_catalog=args.from_catalog)
        args.output.write_text(json.dumps(value, separators=(',', ':')) + '\n')
        print(json.dumps({key: value[key] for key in ['target_bytes', 'target_sha256', 'literal_bytes']}))
    else:
        if args.output is None:parser.error('apply requires an output path')
        apply_delta(args.base, json.loads(args.input.read_text()), args.output)
        print(json.dumps({'apk': str(args.output), 'sha256': digest(args.output)}))
