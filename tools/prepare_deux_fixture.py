#!/usr/bin/env python3
"""Reproduce the PCM16 Android parity fixture from the licensed QA excerpt."""
import hashlib
import json
import pathlib
import wave

import numpy as np
from scipy.io import wavfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
source = ROOT/'qa/release-1.6.0/fixtures/falcon-mix.wav'
output = ROOT/'qa/release-2.2.1/fixtures/falcon-mix-pcm16.wav'
source_sha = 'effbbe3e3c0df821bf3cfa6535360b18339ded8041992373b41f8344998dba99'
output_sha = '0d0bf21401ad0dbb8a49aae581a16f9a00cadca41e116b5a4dc27eaaa3625648'
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
rate, audio = wavfile.read(source)
assert rate == 44100 and audio.shape == (300032, 2) and audio.dtype == np.float32
pcm = np.clip(np.rint(audio.astype(np.float64)*32768), -32768, 32767).astype('<i2')
output.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(output), 'wb') as stream:
    stream.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
    stream.writeframes(pcm.tobytes())
assert hashlib.sha256(output.read_bytes()).hexdigest() == output_sha
original = json.loads((ROOT/'qa/release-1.6.0/musdb-fixture-provenance.json').read_text())
track = next(track for track in original['tracks'] if track['id'] == 'falcon')
receipt = {
    'fixture': str(output.relative_to(ROOT)), 'fixtureSHA256': output_sha,
    'source': str(source.relative_to(ROOT)), 'sourceSHA256': source_sha,
    'title': track['title'], 'license': track['license'], 'datasetSource': track['source'],
    'archive': original['archive'], 'archiveMember': track['archiveMember'],
    'conversion': 'Float32 to signed PCM16: round to nearest (ties to even), clip [-32768,32767], interleaved little-endian stereo.',
    'samples': len(pcm), 'sampleRate': rate, 'channels': 2,
    'scope': 'QA only; excluded from the installed app. A 6.8-second excerpt cannot establish full-song or physical-phone performance.',
}
(output.parent.parent/'deux-fixture-provenance.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
