# Offline music source separation research and provenance

LightForge 1.6 evaluates genuine pretrained stereo source-separation networks, not a sound-event classifier relabelled as separation.

- **UVR MDX-Net Voc FT**: official public UVR model asset, unchanged 66,762,490-byte ONNX graph. Source: <https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Voc_FT.onnx>. Original model parameters and code are snapshotted here; the MIT permission/credit statement is in `uvr-README.md`, lines under “License.” Credit UVR developers Anjok07 and aufr33, and original MDX-Net architecture by KUIELab.
- **Spleeter 2 stems**: original Deezer pretrained 2-stem weights converted by sherpa-onnx author Fangjun Kuang. Source: <https://github.com/deezer/spleeter>; conversion: <https://github.com/k2-fsa/sherpa-onnx/tree/master/scripts/spleeter>. Converted graphs are pinned to Hugging Face repository commit `7001ba316a615cacddb3f9ef3ec416661a277e26`. MIT original model / Apache-2.0 conversion licenses are retained.

Production asset manifests under `web/analysis/models/separator*-model.json` bind each exact model graph, size, parameters and SHA-256. We do not equate model names, parameter count or CPU time with measured quality.

## Time-preserving inference

MDX uses the trained **7680-point periodic-Hann FFT**, hop 1024, 3072 complex bins, 256 frames, channel order `[L.real,L.imag,R.real,R.imag]`, reflection padding and zeroed first three input bins. Its published compensation is 1.021. Two polarity passes are combined as `(f(x)-f(-x))/2`; bounded segments overlap by 50%. A mixed-radix FFT preserves the exact trained bin geometry. The frontend is checked against PyTorch STFT/ISTFT independently; no manual time shift is applied.

Spleeter receives stereo 44.1 kHz magnitude spectra with the trained 4096-point FFT, hop 1024, 512 frames and 1024 learned frequency bins. Both vocal and accompaniment networks run. Their squared magnitudes form the normalized Wiener mask; isolated vocals are reconstructed with original phase, and residual accompaniment is original mixture minus the estimated voice. The port's metadata mistakenly says 41000 Hz; original Deezer settings and sherpa inference use 44100 Hz, which LightForge follows. Context margins and complementary crossfades prevent discontinuities at analysis chunk edges.

Both paths stream exact-clock mono voice and residual samples to consumers without retaining whole-track audio in JavaScript memory. The original imported/exported music is unchanged. Separation can leak instruments, soften voices or include reverberation; it does not transcribe lyrics or certify semantic phrase boundaries.

## Validation

`qa/release-1.6.0/test-separator.cjs` runs actual packaged ONNX Runtime Web WASM graphs. It captures voice and accompaniment PCM from six short official MUSDB studio-stem examples, backing-only mixtures and controlled voice entrances. Independent comparison code evaluates fixed-clock SI-SDR, waveform reconstruction, envelope correlation, instrumental leakage and timing. These are small development excerpts; training overlap is unknown, and they are neither a held-out benchmark nor proof of physical Tesla synchronization.
