"""
Pure numpy + onnxruntime reference implementation for the HT-Demucs FT
vocals specialist. NO TORCH at inference.

Usage:
    python infer.py input.mp3 out_dir/
    # writes out_dir/vocals.wav

Or as a library:
    import infer
    vocals = infer.separate_vocals("song.mp3")
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf

SAMPLE_RATE = 44100
SEGMENT_S = 7.8
N_SAMPLES = int(SEGMENT_S * SAMPLE_RATE)
N_CHANNELS = 2
SOURCES = ["drums", "bass", "other", "vocals"]
SPECIALIST_STEM = "vocals"
DEFAULT_ONNX = Path(__file__).resolve().parent / "htdemucs_ft_vocals.onnx"


def _make_transition_window(segment: int, overlap_frac: float = 0.25) -> np.ndarray:
    transition = int(segment * overlap_frac)
    window = np.ones(segment, dtype=np.float32)
    fade = np.linspace(0, 1, transition, dtype=np.float32)
    window[:transition] = fade
    window[-transition:] = fade[::-1]
    return window


def separate(mix: np.ndarray, sample_rate: int,
             onnx_path: Path = DEFAULT_ONNX,
             providers: list[str] | None = None,
             verbose: bool = True) -> np.ndarray:
    """Run chunked overlap-add separation on a full-length mix.
    Returns: (n_sources, channels, samples). Only the row at
    SOURCES.index(SPECIALIST_STEM) is meaningfully predicted.
    """
    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"Bound to {SAMPLE_RATE} Hz; got {sample_rate}.")
    if mix.ndim != 2 or mix.shape[0] != N_CHANNELS:
        raise ValueError(f"Expected (2, samples) input, got {mix.shape}")

    if providers is None:
        providers = ["CPUExecutionProvider"]
    sess = ort.InferenceSession(str(onnx_path), providers=providers)

    total_len = mix.shape[1]
    overlap = N_SAMPLES // 4
    stride = N_SAMPLES - overlap
    n_chunks = max(1, (total_len + stride - 1) // stride)

    if verbose:
        print(f"  input:    {total_len:,} samples ({total_len / sample_rate:.1f}s)")
        print(f"  segment:  {N_SAMPLES:,} samples ({SEGMENT_S}s)")
        print(f"  chunks:   {n_chunks}, provider {sess.get_providers()[0]}")

    window = _make_transition_window(N_SAMPLES)
    out = np.zeros((len(SOURCES), N_CHANNELS, total_len), dtype=np.float32)
    weight = np.zeros(total_len, dtype=np.float32)

    t0 = time.perf_counter()
    for i in range(n_chunks):
        start = i * stride
        end = min(start + N_SAMPLES, total_len)
        chunk = mix[:, start:end]
        if chunk.shape[1] < N_SAMPLES:
            chunk = np.pad(chunk, ((0, 0), (0, N_SAMPLES - chunk.shape[1])),
                           mode="constant")
        x = chunk[np.newaxis, ...].astype(np.float32)
        stems = sess.run(["stems"], {"mix": x})[0][0]
        chunk_len = end - start
        w = window[:chunk_len]
        out[:, :, start:end] += stems[:, :, :chunk_len] * w
        weight[start:end] += w
        if verbose:
            print(f"    chunk {i+1}/{n_chunks}: "
                  f"{time.perf_counter() - t0:.1f}s elapsed")

    weight = np.maximum(weight, 1e-8)
    out /= weight
    if verbose:
        rtf = (time.perf_counter() - t0) / (total_len / sample_rate)
        print(f"  total:    {time.perf_counter() - t0:.2f}s (RTF {rtf:.2f})")
    return out


def separate_vocals(input_path: str, onnx_path: Path = DEFAULT_ONNX,
                  providers: list[str] | None = None) -> np.ndarray:
    """Convenience: load audio, separate, return only the vocals stem."""
    audio, sr = sf.read(input_path, dtype="float32", always_2d=True)
    audio = audio.T
    if audio.shape[0] == 1:
        audio = np.tile(audio, (2, 1))
    elif audio.shape[0] > 2:
        audio = audio[:2]
    stems = separate(audio, sr, onnx_path=onnx_path, providers=providers)
    return stems[SOURCES.index(SPECIALIST_STEM)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--onnx", type=Path, default=DEFAULT_ONNX)
    ap.add_argument("--providers", type=str, default="cpu",
                    choices=["cpu", "coreml", "cuda", "dml"])
    ap.add_argument("--write-all-stems", action="store_true",
                    help="Also write the (low-quality) by-product stems.")
    args = ap.parse_args()

    providers_map = {
        "cpu":    ["CPUExecutionProvider"],
        "coreml": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
        "cuda":   ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "dml":    ["DmlExecutionProvider", "CPUExecutionProvider"],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)

    audio, sr = sf.read(str(args.input), dtype="float32", always_2d=True)
    audio = audio.T
    if audio.shape[0] == 1:
        audio = np.tile(audio, (2, 1))
    elif audio.shape[0] > 2:
        audio = audio[:2]

    stems = separate(audio, sr, onnx_path=args.onnx,
                     providers=providers_map[args.providers])
    if args.write_all_stems:
        for i, src in enumerate(SOURCES):
            sf.write(str(args.out_dir / f"{src}.wav"), stems[i].T, sr)
    else:
        target = stems[SOURCES.index(SPECIALIST_STEM)]
        sf.write(str(args.out_dir / f"{SPECIALIST_STEM}.wav"), target.T, sr)
        print(f"  wrote {args.out_dir / f'{SPECIALIST_STEM}.wav'}")


if __name__ == "__main__":
    main()
