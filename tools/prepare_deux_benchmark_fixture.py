#!/usr/bin/env python3
"""Build a deterministic multi-passage Deux input from verified MUSDB WAVs.

The actual-model preprocessing gate needs more than one 13-second passage. The
licensed QA excerpts are intentionally short, so this utility concatenates their
already-decoded float32 stereo PCM without resampling, mixing, silence insertion
or sample conversion. It rejects an input that is not named and hashed in the
immutable MUSDB fixture provenance record and writes a separate provenance
receipt for the generated benchmark-only WAV.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_fixture_hashes(path):
    document = json.loads(Path(path).read_text())
    expected = {}
    for track in document.get('tracks', []):
        for name, digest in track.get('pcmSHA256', {}).items():
            require(isinstance(digest, str) and len(digest) == 64,
                    'Fixture provenance contains an invalid hash for ' + name)
            if name in expected:
                require(expected[name] == digest,
                        'Fixture provenance contains conflicting hashes for ' + name)
            expected[name] = digest
    require(expected, 'Fixture provenance has no PCM hashes.')
    return expected


def write_atomic_wav(path, rate, pcm):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.unlink(missing_ok=True)
    try:
        wavfile.write(temporary, rate, pcm)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build(sources, samples, output, provenance):
    require(samples > 0, '--samples must be positive.')
    source_paths = [Path(value).resolve() for value in sources]
    require(source_paths, 'At least one --source is required.')
    fixture_provenance = source_paths[0].parent.parent / 'musdb-fixture-provenance.json'
    require(fixture_provenance.is_file(),
            'The immutable MUSDB fixture provenance is unavailable: ' + str(fixture_provenance))
    expected = expected_fixture_hashes(fixture_provenance)
    pieces, receipt_sources, rate, shape = [], [], None, None
    remaining = samples
    for source in source_paths:
        require(source.is_file(), 'Benchmark source is unavailable: ' + str(source))
        expected_hash = expected.get(source.name)
        require(expected_hash is not None,
                'Benchmark source is not listed in the immutable fixture provenance: ' + source.name)
        source_hash = sha256(source)
        require(source_hash == expected_hash,
                'Benchmark source hash differs from immutable fixture provenance: ' + source.name)
        current_rate, pcm = wavfile.read(source)
        require(pcm.dtype == np.float32 and pcm.ndim == 2 and pcm.shape[1] == 2,
                'Benchmark source must be stereo float32 PCM: ' + source.name)
        require(np.isfinite(pcm).all(), 'Benchmark source has non-finite PCM: ' + source.name)
        if rate is None:
            rate, shape = current_rate, pcm.shape[1:]
        require(current_rate == rate and pcm.shape[1:] == shape,
                'Benchmark sources must retain an identical sample rate and channel layout.')
        count = min(remaining, pcm.shape[0])
        if count:
            pieces.append(pcm[:count])
            receipt_sources.append({
                'file': source.name,
                'sha256': source_hash,
                'source_samples': int(pcm.shape[0]),
                'used_samples': int(count),
            })
            remaining -= count
        if not remaining:
            break
    require(not remaining,
            'Provided licensed sources contain fewer samples than required by the multi-passage gate.')
    merged = np.concatenate(pieces, axis=0)
    require(merged.dtype == np.float32 and merged.shape == (samples, 2) and np.isfinite(merged).all(),
            'Generated benchmark PCM is invalid.')
    output = Path(output).resolve()
    write_atomic_wav(output, rate, merged)
    verified_rate, verified = wavfile.read(output)
    require(verified_rate == rate and verified.dtype == np.float32 and np.array_equal(verified, merged),
            'Generated benchmark WAV did not retain exact concatenated float32 PCM.')
    receipt = {
        'schema': 'lightforge.deux-benchmark-fixture.v1',
        'scope': 'Benchmark-only concatenation of verified licensed MUSDB mix excerpts; no resampling, mixing, silence insertion or source-model change.',
        'fixture_provenance': {
            'file': fixture_provenance.name,
            'sha256': sha256(fixture_provenance),
        },
        'sources': receipt_sources,
        'output': {
            'file': output.name,
            'sha256': sha256(output),
            'samples': samples,
            'sample_rate': rate,
            'channels': 2,
            'dtype': 'float32',
        },
    }
    write_atomic_json(provenance, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True,
                        help='Verified MUSDB float32 mix WAV. Repeat in concatenation order.')
    parser.add_argument('--samples', type=int, required=True,
                        help='Exact output sample count required by the benchmark.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, required=True)
    args = parser.parse_args()
    receipt = build(args.source, args.samples, args.output, args.provenance)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
