# Research security migration (2026-10-09)

This directory is isolated research, not the application runtime or production
model-export environment. Its dependency declarations have been remediated;
**the migrated training/inference environment is not numerically qualified**.
Do not regenerate production models or reuse historical output claims with it.

## Coordinated changes

- Torch 1.13.0 → 2.13.0; torchvision 0.14.0 → 0.28.0; torchaudio 0.13.0 → 2.11.0.
  The [official Torch/vision pair](https://pytorch.org/get-started/previous-versions/)
  and [TorchAudio stable-ABI compatibility](https://docs.pytorch.org/audio/main/installation.html)
  support these versions together. TorchAudio 2.11 supports Torch 2.11 and later;
  an old TorchAudio extension must not be retained with a new Torch.
- scikit-learn 1.1.3 → 1.5.2, addressing
  [CVE-2024-5206](https://github.com/advisories/GHSA-jw8x-6495-233v).
  The vulnerable TF-IDF feature is not used here, but the vulnerable pin is
  removed. Metrics and LabelEncoder are the actual research call sites.
- Tensor/checkpoint loads explicitly use `weights_only=True`, CPU mapping, and
  refuse Torch older than the reviewed 2.13.0 baseline or prereleases. A rejected
  load is never retried with unrestricted pickle. This is defense in depth,
  not a sandbox or a replacement for trusted, provenance-verified model inputs.
- Modern STFT returns complex tensors; `view_as_real` retains the original
  real/imaginary squared-sum order. Two-dimensional layers use
  `Conv2dNormActivation`; autocast uses the current device-aware API.

Torch 2.13.0 is required by the current advisory range for
[CVE-2025-3000](https://github.com/advisories/GHSA-rrmf-rvhw-rf47).
Other relevant checkpoint issues include
[CVE-2025-32434](https://github.com/pytorch/pytorch/security/advisories/GHSA-53q9-r3pm-6pq6)
and [CVE-2026-24747](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p).
Merely adding `weights_only=True` to Torch 1.13 would not address the old runtime.

## Compatibility and remaining work

Unrelated direct pins remain unchanged, limiting numerical changes. The upstream
research target is Python 3.10.8. Official PyPI release metadata supports the
new Torch family on Python >=3.10, and sklearn 1.5.2 permits NumPy >=1.19.5,
including the existing 1.23.3. Linux CPython 3.10 wheels were listed for Torch,
audio, vision, sklearn, NumPy and h5py. This is metadata compatibility, not an
installation result. PyAV 10.0.0 did not list a matching manylinux CPython 3.10
wheel; its native FFmpeg/build dependencies still need review. Do not regard
this as a complete supported long-term Python environment.

The 2026-10-09 `pip-audit 2.10.1 --no-deps --disable-pip` check covered all eleven
direct pins and found no known advisories. The old manifest returned 32 records,
24 distinct Torch advisory IDs and one scikit-learn advisory ID. This check does
not cover resolved transitive dependencies, native libraries or unknown issues.

The stdlib regression suite `tests/test_research_dependency_security.py` tests
pin coordination, guarded loading, no unsafe fallback and source API contracts.
It does not import a real Torch installation. Before using the migration:

1. Resolve and audit the full isolated environment, including transitive Python
   dependencies and the native audio stack; record exact versions and hashes.
2. Verify trusted checkpoint provenance; run restricted loading and state-dict
   key/shape checks on the actual retained models.
3. Compare STFT/mel intermediates, model tensors and evaluation metrics against
   identical fixtures and the archived baseline. Keep Float32 and all original
   input/processing lengths; do not loosen tolerances to make a test pass.
4. Record new results separately. Historical research receipts are not new
   qualification and must not be rewritten to claim compatibility.

No Torch package was installed and no model inference was run for this patch.

The four hand-computable sklearn fixtures in `verify_metrics.py` passed with
scikit-learn 1.5.2 and NumPy 2.3.5 in an isolated test environment. Run it with
`python research/upstream/vocal-candidates/EfficientAT/verify_metrics.py`.
This API smoke check does not establish the old NumPy 1.23.3 environment or model
parity. NumPy was not changed in the research manifest.

Additional AudioSet index hardening replaces raw `pickle.load` with the restricted
primitive filename-index reader documented in [research security boundaries](../../SECURITY.md).
The raw dictionary reader rejects executable opcodes and never falls back to
unrestricted deserialization; training and real teacher-index parity remain unrun.
