# Dependency and security maintenance

## Supported build boundaries

Use [BUILD.md](../BUILD.md) for the production toolchain. The two npm lockfiles
are separate: root packages support tests, while `web/preview/src/` supplies the
offline renderer build. Install with `npm ci`; keep each manifest and lockfile in
sync. Renderer resolved versions are frozen by the lockfile and `npm ci`.
The baked lighting atlas additionally binds the exact lockfile bytes. Even a
declaration-only lockfile change needs a fresh atlas provenance build; preserve
the existing lockfile unless that full rebake is intentionally performed.

Production model exporters use `tools/model-requirements.txt`, the pinned CPU
Torch version in the build guide, and checksum-bound source/weights. Do not apply
research dependency updates to that environment. A model-exporter or runtime
upgrade requires regenerated graphs, manifest validation and fresh numerical,
actual-model and Android qualification. A dependency audit alone cannot establish
model equivalence or release readiness.

## Research environment warning

`research/upstream/` preserves third-party research code, not a supported
application installation environment. In particular, EfficientAT retains an old
Torch/audio/vision stack and other unqualified dependencies. Do not install its
requirements into the production conversion environment or load untrusted
checkpoints or serialized datasets with it. Its full stack has not been security
cleared or requalified on current Python.

The isolated EfficientAT `tqdm` update to 4.66.3 addresses
[CVE-2024-34062](https://github.com/tqdm/tqdm/security/advisories/GHSA-g7vv-2v7x-gj9p),
an optional CLI argument code-injection issue. This does not claim to remediate
other research dependencies. Its progress-iterator API was smoke-tested; the
research training/evaluation pipeline was not run.

[PR #29](https://github.com/CyberBASSLord-666/LightForge/pull/29) must not be adopted
as an atomic dependency update: it changes Torch to 2.13.0 while retaining
`torchaudio==0.13.0` and `torchvision==0.14.0`, which belong to the Torch 1.13
family. [PyTorch's supported installation pairs](https://pytorch.org/get-started/previous-versions/)
identify a different vision version for Torch 2.13. Modernizing this research
stack needs coordinated library/API changes and model-output tests. The
scikit-learn and Torch changes remain unresolved rather than falsely claiming
that the isolated tqdm fix makes the environment safe.

## Performance branch integration

[PR #43](https://github.com/CyberBASSLord-666/LightForge/pull/43)'s description is
not an adequate scope summary. The checked head `549b49f` adds 1,017 files and
59,429 text lines relative to the common ancestor with `de831259`: research
receipts, binary evidence parts, experiment runners, tests and documentation.
This is not a docs-only change and was not merged during this audit. Review the
actual diff, retained evidence provenance, dependency/runtime assumptions and
storage impact before integration. Diagnostic GPU-readiness evidence does not
establish a qualified speedup on Android.

## Local audit on 2026-10-06

- `npm audit --json --ignore-scripts` reported zero known advisories for the root
  lockfile (42 dependency entries).
- The same audit for `web/preview/src` reported zero known advisories (28 entries).
- Both lockfiles installed with `npm ci --ignore-scripts --no-audit --no-fund`.
- Rebuilding the preview with the locked versions produced byte-identical
  `web/preview/vehicle-preview.js` (SHA-256
  `f4853edf29d312c760d0eafa1994efb4db132a57e84fd3607868d7e2cb54bfb1`).
- The precision/DOM suite passed all 17 tests.
- Declaration-only renderer pin changes were reverted after the atlas provenance
  regression test detected the changed lockfile hash. Original manifest and
  lockfile bytes were restored, and all eight preview-environment tests passed;
  no historical asset or evidence hash was rewritten.
- Repository hygiene regression tests cover rejection of accidentally tracked
  `local.properties` and `.pypirc`, including nested paths. `.pypirc` is ignored
  because Python publishing credentials may be stored there.

Audit results are a time-bound advisory-database observation, not proof that
there are no vulnerabilities. These checks do not replace full production,
Android, actual-model or release qualification. Repository hygiene is a path and
maintained-link check, not a general secret scanner. Keep private signing
material and publishing credentials outside the checkout.

## Additional security review

A direct-dependency `pip-audit --no-deps --disable-pip` check found no known
advisories in the nine pinned production conversion/native-runtime package
versions (Torch 2.13.0, ONNX Runtime 1.25.1 and the seven model requirements).
This does not audit Python transitive dependencies, Maven/native transitive
libraries or the Android system WebView. A separate temporary npm lockfile for
the bundled ONNX Runtime Web 1.20.1 package also returned zero known advisories;
the vendored runtime bytes and model-bound pins were left unchanged.

The EfficientAT research check returned 32 advisory records across Torch 1.13.0
and scikit-learn 1.1.3; duplicate IDs reduce this to 24 Torch advisory IDs and one
scikit-learn ID. The scikit-learn advisory concerns `TfidfVectorizer`, which this
vendored research code does not use. Its actual calls use metrics and
preprocessing. Old Torch loading remains unsafe for untrusted checkpoints or
serialized datasets: the research code uses `torch.load` and
`load_state_dict_from_url`. These Python research packages are not shipped in the
APK. No exploitable installed-app vulnerability was established by this review;
that is not a claim that the app or its system WebView is vulnerability-free.

Do not solve PR #29 by upgrading only Torch or copying the production exporter
environment. A coordinated research migration must select a supported
Torch/audio/vision family together, replace deprecated frontend calls such as
`torch.stft(return_complex=False)` and `ConvNormActivation` if required, preserve
mel/STFT numerical behavior, qualify checkpoint loading, and compare model
outputs and evaluation metrics on identical fixtures. NumPy, h5py and librosa
pins also need compatible wheels for the selected Python version. The current
production graph identity explicitly requires Python 3.12.14; it was unchanged.

The packaging audit found and closed two accidental-disclosure paths:

- The legacy pre-2.0 source packager explicitly selected the signing directory.
  It now excludes credentials, and shared archive staging rejects sensitive
  filenames, symlink payloads, archive traversal and manifest-line injection.
  The current v2 packaging route never selected that legacy source backup.
- Current APK asset selection accepted file symlinks, which could copy a private
  file outside `web/` into an otherwise innocently named asset. Asset staging now
  rejects symlinks and obvious credential/configuration paths before copying.
  Ignored npm dependency trees remain excluded. All 104 existing web assets were
  accepted by the tightened inventory check.

A bounded content scan of 2,203 tracked files at most 2 MiB found no private-key
headers, GitHub-token patterns or AWS access-key-ID patterns. Twenty larger or
missing files were outside that scan. The tracked Tesla/xLights ZIP's 53 entry
names contained no signing/password/credential-path candidates. These are
limited checks, not certification of historical archives or all binary contents.

Model notices agree with the repository asset guide and upstream model sources:
[Deux weights](https://huggingface.co/becruily/mel-band-roformer-deux) retain
CC BY-NC 4.0; [modified GAME weights](https://github.com/openvpi/GAME/releases/tag/v1.0.3)
retain CC BY-NC-SA 4.0. Their MIT architecture
or runtime code licenses do not replace weight licenses. Notices remain bundled;
no commercial-use or relicensing clearance is implied by this audit.
