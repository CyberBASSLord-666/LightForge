#!/usr/bin/env python3
"""CPU ONNX Runtime proxy for bounded Deux inference; no neural approximations.

The Android implementation must be verified separately. This executable records
real full-context inference cost and float32 PCM against an optional WASM oracle.
Requires onnxruntime, numpy and soundfile in the model preparation environment.
"""
import argparse, hashlib, json, pathlib, resource, time
import numpy as np
import onnxruntime as ort
import soundfile as sf

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fixture', type=pathlib.Path, default=ROOT/'qa/release-1.6.0/fixtures/falcon-mix.wav')
parser.add_argument('--models', type=pathlib.Path, default=ROOT/'web/analysis/models/deux')
parser.add_argument('--output', type=pathlib.Path, required=True)
parser.add_argument('--reference', type=pathlib.Path)
parser.add_argument('--pcm', type=pathlib.Path)
parser.add_argument('--threads', type=int, default=4)
args = parser.parse_args()
assert 1 <= args.threads <= 8
sha = lambda b: hashlib.sha256(b).hexdigest()
manifest_bytes = (args.models/'manifest.json').read_bytes()
manifest = json.loads(manifest_bytes)
for name, entry in manifest['files'].items():
    model_file = args.models/name
    with model_file.open('rb') as stream:
        assert model_file.stat().st_size == entry['bytes'] and hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256'], name
assert manifest['execution'] == 'bounded-independent-batches-v1'
audio, rate = sf.read(args.fixture, dtype='float32', always_2d=True)
assert rate == 44100 and audio.shape[1] == 2 and len(audio) <= 441000
SAMPLES, FRAMES, FFT, HOP, HALO = 573300, 1301, 2048, 441, 66150
stereo = np.zeros((2, SAMPLES), dtype=np.float32)
stereo[:, HALO:HALO+len(audio)] = audio.T
window = .5-.5*np.cos(2*np.pi*np.arange(FFT)/FFT)
started = time.perf_counter()
padded = np.pad(stereo, ((0, 0), (FFT//2, FFT//2)), mode='reflect')
frames = np.lib.stride_tricks.sliding_window_view(padded, FFT, axis=1)[:, ::HOP, :][:, :FRAMES]
complex_spectrum = np.fft.rfft(frames*window, axis=-1).transpose(2, 0, 1).reshape(2050, FRAMES)
spectrum = np.stack((complex_spectrum.real, complex_spectrum.imag), -1).astype(np.float32)[None]
del complex_spectrum, frames, padded
options = ort.SessionOptions()
options.intra_op_num_threads = args.threads
options.inter_op_num_threads = 1
options.enable_cpu_mem_arena = False
options.enable_mem_pattern = False
options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
session, session_name, timings = None, None, []

def run(name, values):
    global session, session_name
    if session_name != name:
        session = None
        session = ort.InferenceSession(str(args.models/(name+'.onnx')), sess_options=options, providers=['CPUExecutionProvider'])
        session_name = name
    return session.run(None, {'input': values})[0]

latents = run('front', spectrum)[0]
for i in range(12):
    at = time.perf_counter()
    for first in range(0, 60, 4):
        inputs = np.ascontiguousarray(latents[:, first:first+4].transpose(1, 0, 2))
        latents[:, first:first+4] = run(f'block-{i:02}-time', inputs).transpose(1, 0, 2)
    for first in range(0, FRAMES, 128):
        latents[first:first+128] = run(f'block-{i:02}-frequency', np.ascontiguousarray(latents[first:first+128]))
    timings.append({'stage': f'block-{i:02}', 'seconds': time.perf_counter()-at})
    print(json.dumps(timings[-1]), flush=True)

def decode(mask):
    summed = np.zeros_like(spectrum)
    for j, index in enumerate(manifest['indices']):
        summed[:, index] += mask[:, j]
    denominator = np.repeat(np.array(manifest['bandsPerFrequency']), 2)
    mask_complex = (summed[..., 0].astype(np.float64)+1j*summed[..., 1])/np.maximum(1e-8, denominator[None, :, None])
    z = (spectrum[..., 0].astype(np.float64)+1j*spectrum[..., 1])*mask_complex
    z = z.reshape(1025, 2, FRAMES).transpose(1, 2, 0)
    pcm = np.zeros(SAMPLES+FFT, dtype=np.float32)
    normalization = np.zeros(SAMPLES+FFT, dtype=np.float64)
    for f in range(FRAMES):
        normalization[f*HOP:f*HOP+FFT] += window*window
    for channel in range(2):
        signals = np.fft.irfft(z[channel], n=FFT, axis=-1)*window*.5
        for f in range(FRAMES):
            pcm[f*HOP:f*HOP+FFT] += signals[f]
    return (pcm[FFT//2:FFT//2+SAMPLES]/np.maximum(1e-12, normalization[FFT//2:FFT//2+SAMPLES])).astype(np.float32)

report = {'schema': 1, 'passed': True, 'errors': [], 'backend': 'onnxruntime-cpu', 'backendVersion': ort.__version__, 'threads': args.threads,
          'sourceSHA256': sha(pathlib.Path(__file__).read_bytes()), 'fixtureSHA256': sha(args.fixture.read_bytes()),
          'manifestSHA256': sha(manifest_bytes), 'modelId': manifest['id'], 'stages': timings, 'pcm': {}}
for i, role in enumerate(['vocals', 'accompaniment']):
    at = time.perf_counter()
    name = f'head-{i}'
    mask = np.empty((1, len(manifest['indices']), FRAMES, 2), dtype=np.float32)
    for first in range(0, FRAMES, 128):
        count = min(128, FRAMES-first)
        mask[:, :, first:first+count] = run(name, np.ascontiguousarray(latents[None, first:first+count]))
    session, session_name = None, None
    pcm = decode(mask)[HALO:HALO+len(audio)].copy()
    del mask
    timings.append({'stage': name, 'seconds': time.perf_counter()-at})
    assert np.isfinite(pcm).all() and len(pcm) == len(audio)
    data = pcm.astype('<f4').tobytes()
    info = {'samples': len(pcm), 'sha256': sha(data), 'nonFiniteSamples': 0}
    if args.reference:
        reference_bytes = pathlib.Path(str(args.reference)+'-'+role+'.f32').read_bytes()
        ref = np.frombuffer(reference_bytes, dtype='<f4').astype(np.float64)
        assert len(ref) == len(pcm)
        difference = pcm.astype(np.float64)-ref
        info.update(referenceSHA256=sha(reference_bytes), maxAbsError=float(np.abs(difference).max()),
                    rmsError=float(np.sqrt(np.mean(difference*difference))),
                    snrDb=float(10*np.log10(max(1e-30, np.sum(ref*ref))/max(1e-30, np.sum(difference*difference)))))
        if info['maxAbsError'] > 0.00003 or info['rmsError'] > 0.000003:
            report['passed'] = False
            report['errors'].append(role+' differs from the Float32 reference.')
    report['pcm'][role] = info
    if args.pcm:
        dest = pathlib.Path(str(args.pcm)+'-'+role+'.f32')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
report.update(seconds=time.perf_counter()-started, peakRssMiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2), flush=True)
if not report['passed']:
    raise SystemExit(1)
