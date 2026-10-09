# Vendored research security boundaries

Status: 2026-10-09. These sources are not a supported application installation
and must not be installed into the production exporter environment. A dependency
floor change does not establish model equivalence, a complete lockfile, or safe
handling of arbitrary model files. The release qualification hold remains.

## Manifest inventory and results

All tracked conventional Python dependency files are:

- `tools/model-requirements.txt`: seven production exporter packages; Torch
  2.13.0 CPU is separately declared in BUILD.md and workflows, and native ONNX
  Runtime 1.25.1 in `android/native-runtime.json`. Nine direct package versions
  returned zero known advisories. A separate non-Torch prospective resolution
  audited 34 packages with zero known advisories, but does not cover the actual
  CPU Torch wheel's transitive environment.
- `research/inference-2.4.1/attention/requirements.txt`: ONNX parser upgraded
  to 1.22.0; ONNX Runtime remains 1.25.1. Three direct pins returned zero known
  advisories. Original evidence was not rerun or rewritten.
- `research/upstream/vocal-candidates/EfficientAT/requirements.txt`: eleven
  direct pins returned zero known advisories after the coordinated migration.
  See [its migration limits](vocal-candidates/EfficientAT/SECURITY_MIGRATION.md).
- `research/upstream/pretrained-sed/requirements.txt`: mostly unpinned or minimum
  ranges, not a resolved environment. The exact `sed_scores_eval==0.0.3` and the
  old declared minimum versions of av, h5py, jsonpickle, hf-transfer and hf-fastup
  returned zero known advisories. This does not certify every allowed version.
  Two vulnerable allowed minima were identified and raised as described below.
- `research/upstream/beat_this/ckpt2onnx.py`: inline PEP 723 environment. Its Torch
  and ONNX lower bounds now exclude versions below 2.13.0 and 1.22.0 respectively.
  The upstream `beat-this` source URL still follows `main.zip`; it is not a
  reproducible dependency lock and the exporter has not been requalified.

No additional tracked pyproject, setup.py/setup.cfg, Pipfile, poetry.lock,
uv.lock, environment.yml or constraints file was found in this inventory.
Historical source snapshots and runtime receipts are provenance, not claims
that those historical environments are safe to reinstall.

The extra build pins `pip==26.2.1`, `setuptools==83.0.0`, and `scipy==1.18.1`
returned zero known advisories. OSV package/version queries for Maven
`com.microsoft.onnxruntime:onnxruntime:1.25.1`,
`com.microsoft.onnxruntime:onnxruntime-android:1.25.1`, `org.json:json:20260719`,
and npm `onnxruntime-web@1.20.1` returned no advisories. These queries do not
inspect bundled native libraries or the device WebView. npm lockfiles are
separately audited; downloaded build tools and native dependency contents need
separate provenance and vulnerability assessment.

## Pretrained SED dependency floors

The old `datasets>=2.15.0` allowed versions affected by
[CVE-2026-66007](https://github.com/advisories/GHSA-379c-qx7v-6h59), a folder-builder
metadata path traversal. The floor is now 5.0.1.

The old `pytorch-lightning>=2.0.0` permitted six distinct advisory records in a
minimum-version audit. The floor is now 2.6.6, the declared fix for checkpoint
`_instantiator` code execution
([CVE-2026-58659](https://github.com/advisories/GHSA-qqmf-gpg7-g8gw)).
[CVE-2026-31221](https://github.com/advisories/GHSA-75m9-98v2-hjpm) lists affected
versions through 2.6.0 with no patched version in that particular record;
2.6.6 is outside its listed affected range. Do not interpret this as permission
to accept arbitrary checkpoint objects. The 5.0.1 and 2.6.6 package versions
returned zero known advisories in the direct check.

Explicit Torch >=2.13.0, vision >=0.28.0 and audio >=2.11.0 floors prevent an old
runtime being accepted transitively. TorchAudio 2.11 supports Torch 2.11 and
later via its stable ABI; torchvision's resolver metadata ties its release to
a corresponding Torch release. These are research constraints, not changed
production pins.

Official release metadata declares Python >=3.10 for Torch 2.13.0 and datasets
5.0.1. The EfficientAT upstream README's Python 3.10.8 identifies its historical
environment; it is not a recommendation to reinstall that old patch release.
The migrated full environments were not installed or numerically qualified.
Datasets 5.x includes API changes, so training/data preparation requires fresh
compatibility tests before use. No Torch artifact was downloaded for this audit.

## Direct unsafe index deserialization removed

EfficientAT's two AudioSet training entry points downloaded and directly
unpickled `fname_to_index.pkl`. They now use a bounded reader that permits only
primitive dictionary/string/integer pickle opcodes, prohibits executable globals,
reduce/build/extension/persistent-object opcodes, rejects trailing input and
validates the final dictionary as string keys and nonnegative integer values.
It does not retry unsafe pickle or allow arbitrary classes. Primitive dictionary
fixtures for protocols 0–5 and rejection fixtures passed. Actual downloaded
teacher-index compatibility is untested; unsupported objects must be converted
in a trusted isolated environment, not enabled by relaxing this loader.

## Guarded source and remaining environment boundaries

Do not load untrusted models or serialized data with any of these research
entry points. Twenty-two additional checkpoint load call sites in fourteen vendored files now
route through a shared fail-closed guard, including:

- `pretrained-sed/data_util/audioset_strong.py` and several `pretrained-sed/models/`
  modules, including frame_mn, frame_passt, m2d, beats and asit
- `efficientat/models/mn/model.py`
- both retained `beat_this/inference.py` copies, including network checkpoint URLs
- `source-separation/spleeter-export_onnx.py` and `source-separation/uvr-separate.py`

The shared guard requires stable Torch >=2.13.0, forces restricted weights-only
loading, rejects custom pickle modules and caller-added class allowlists, and
never retries unrestricted pickle. Remote loader entry points require HTTPS
without URL credentials. Local tensor/state-dict arguments are preserved. Mocked
execution and whole-vendored-source static coverage tests passed; actual model
and training compatibility were not established.

The Demucs identity helper previously added arbitrary checkpoint classes to a
safe-globals context. It now refuses before importing Torch; the UVR Demucs v1 arbitrary-class path
also refuses explicitly. Those workflows
require trusted isolated conversion to a plain tensor state dictionary before
it can run; this patch does not silently re-enable class deserialization. Other
legacy object checkpoints may likewise be rejected. Restricted deserialization
is not checkpoint authenticity or a sandbox; network/download provenance still
needs verification before trusting inputs.

The modern minimum versions and mocked tests do not verify actual checkpoint
compatibility, API migration or tensor parity. Those remain explicit work. Other unpinned packages,
transitive dependencies, PyAV's native FFmpeg stack, OS toolchains and system
WebView also prevent a blanket repository/app security clearance.

Additional delegated-loading boundaries are closed: UVR's MDX checkpoint path
reuses the restricted checkpoint's `state_dict` with strict loading instead of
calling Lightning's `load_from_checkpoint` for a second deserialization. UVR's
unqualified Demucs model-manager branch and `demucs-upstream-api.py` now refuse
explicitly. The M2D Hugging Face model call requires safetensors and explicitly
disables remote code; unsupported weight formats fail rather than fall back to
pickle. These restrictions require fresh workflow compatibility qualification.
