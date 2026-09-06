# Assets not in git

Large and private files live **on disk**, not in this repository. There is no Git LFS yet (escalate to Chief of Staff if wanted).

**Checkout note:** On GitHub `main`, the app tree is the **repo root** (`android/`, `web/`, `tools/`, …). A private extract may nest the same tree under `…/app/lightforge/`. Commands below use `ROOT="$(pwd)"` at that app-tree root.

## Decision guide

| Goal | What to restore |
| --- | --- |
| **1. Full APK** (models, WASM, demo wav, Highland GLB) | **Restore A** from the **private extract** |
| **2. Research / training weights & datasets** (optional; not needed for APK) | **Restore B** from `/workspace/lightforge-assets/` (+ a few research media still only in the private extract) |
| **3. Oversized QA / verification dumps** (optional) | **Restore C** from `/workspace/lightforge-assets/` |

**Already in git on `main`:** small analysis frontend `web/analysis/models/beat-this-mel.onnx` (~268K). Fat ONNX/WASM/wav/glb listed under Restore A are gitignored.

Demo / synthetic activation dumps are **not tracked on `main` after** commit `99e038d`. Keep copies on disk under `/workspace/lightforge-assets/` if needed (see `.gitignore` `qa/**/*demo*` and `qa/**/*synthetic*activations*.json`).

Build after Restore A: see [`BUILD.md`](BUILD.md). Layout map: [`RESOURCES_MAP.md`](RESOURCES_MAP.md).

## On-disk locations

| Path | Role |
|------|------|
| `/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge/` | **Private extract** — full `web/` ONNX/WASM/wav/glb, research glb/wavs still under tree, `signing/` |
| `/workspace/lightforge-assets/` | **Dropped from git** — research weights (`.pth`/`.pt`/`.h5`), Audioset CSVs, `tesla-xlights.zip`, oversized QA / `release-verification.json`, demo/synthetic dumps |
| This repo (`main`) | Source + small assets only (`web/analysis/models/beat-this-mel.onnx` kept) |

Signing stays under private `signing/` only — never commit (see Signing below).

## Restore A — web fat bins (required for full APK)

Source: **private extract** (not under `lightforge-assets/`).

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
ROOT="$(pwd)"   # git checkout root on main, or the nested app/lightforge tree in a private extract

mkdir -p "$ROOT/web/analysis/models" "$ROOT/web/analysis/vendor" \
         "$ROOT/web/demo" "$ROOT/web/preview/models"

cp -n "$PRIV/web/analysis/models/beat-this-large.onnx"        "$ROOT/web/analysis/models/"   # 80M
cp -n "$PRIV/web/analysis/models/uvr-mdx-voc-ft.onnx"         "$ROOT/web/analysis/models/"   # 64M
cp -n "$PRIV/web/analysis/models/frame-mn10-singing.onnx"     "$ROOT/web/analysis/models/"   # 13M
cp -n "$PRIV/web/analysis/models/beat-this-small.onnx"        "$ROOT/web/analysis/models/"   # 11M
cp -n "$PRIV/web/analysis/vendor/ort-wasm-simd-threaded.wasm" "$ROOT/web/analysis/vendor/"   # 11M
cp -n "$PRIV/web/demo/glass-castle.wav"                      "$ROOT/web/demo/"               # 11M
cp -n "$PRIV/web/preview/models/highland.glb"                "$ROOT/web/preview/models/"     # 8.4M
cp -n "$PRIV/web/analysis/models/beatnet-v1.onnx"             "$ROOT/web/analysis/models/"   # 1.6M
```

Then build (happy path; details in [`BUILD.md`](BUILD.md)):

```bash
python3 tools/bootstrap_toolchain.py
unset ANDROID_SDK_ROOT ANDROID_HOME
bash build.sh
# → dist/LightForge-1.6.0.apk
```

| Relative path | ~Size | In git? |
|---------------|-------|---------|
| `web/analysis/models/beat-this-large.onnx` | 80M | no |
| `web/analysis/models/uvr-mdx-voc-ft.onnx` | 64M | no |
| `web/analysis/models/frame-mn10-singing.onnx` | 13M | no |
| `web/analysis/models/beat-this-small.onnx` | 11M | no |
| `web/analysis/vendor/ort-wasm-simd-threaded.wasm` | 11M | no |
| `web/demo/glass-castle.wav` | 11M | no |
| `web/preview/models/highland.glb` | 8.4M | no |
| `web/analysis/models/beatnet-v1.onnx` | 1.6M | no |
| `web/analysis/models/beat-this-mel.onnx` | 268K | **yes** |

Models ship **APK-bundled** at build time (no runtime downloads). See [`ARCHITECTURE.md`](ARCHITECTURE.md).


## Neural audio path map

Inventory locked by LF Audio ML (Lead/CoS). Authoritative tree for full 1.6 neural assets:

`/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge`

Fat binaries are restored via **Restore A/B** above — this section is the **runtime / research map**, not a second copy list.

### Build-required (WebView ORT WASM)

Relative to the app-tree root (`ROOT`):

| Kind | Paths |
| --- | --- |
| Models | `web/analysis/models/beat-this-{large,small,mel}.onnx`, `uvr-mdx-voc-ft.onnx`, `frame-mn10-singing.onnx` |
| ORT WASM | `web/analysis/vendor/ort-wasm-simd-threaded.wasm` |
| JS | `web/analysis/` — `worker.js`, `analyzer.js`, `separator-mdx.js`, `stem-cache.js`, `vocal.js`, `vocal-detail.js`, `bass-notes.js` |
| Manifests | `model-manifest.json`, `separator-mdx-model.json`, `vocal-model.json`, `vocal-frontend.json` (under `web/analysis/`) |

`web/analysis/models/beatnet-v1.onnx` is **shipped but unused at runtime** (still listed in Restore A). Do not treat it as an active pipeline stage.

### Pipeline

`MusicAnalyzer` → Beat This → UVR MDX → Frame-MN10 on stems → vocal-detail / bass DSP → show-engine.

Android Java is **I/O only** (decode, projects, export, WebView bridge) — not inference. See [`ARCHITECTURE.md`](ARCHITECTURE.md).

### Research-only (not needed for APK)

Under `/workspace/lightforge-assets/research/upstream/{panns,BeatNet,yamnet,pretrained-sed}` plus Audioset CSVs — restore via **Restore B**.

### Holds

- No model / manifest / `analysisQuality` swaps until QA smoke is green.
- No BeatNet cleanup until QA smoke is green.

### Workspace gaps (notes)

- A thin git-seed checkout still needs **Restore A** before a full APK build.
- `/workspace/LightForge/` is **1.5-era** (missing the MDX stack) — do not use it as the 1.6 authoritative tree.
- Spleeter eval weights are **absent on disk** in this workspace.

## Restore B — research weights / datasets (optional; not needed for APK)

Source: **`/workspace/lightforge-assets/`** (paths mirror repo layout).

```bash
ASSETS=/workspace/lightforge-assets
ROOT="$(pwd)"

# weights
mkdir -p "$ROOT/research/upstream/panns" \
         "$ROOT/research/upstream/BeatNet" \
         "$ROOT/research/upstream/yamnet" \
         "$ROOT/research/upstream/pretrained-sed/resources" \
         "$ROOT/research/upstream/pretrained-sed/hf_dataset_gen/metadata" \
         "$ROOT/research/hardware-1.2.0"

cp -n "$ASSETS/research/upstream/panns/Cnn6_mAP=0.343.pth"              "$ROOT/research/upstream/panns/"
cp -n "$ASSETS/research/upstream/panns/MobileNetV2_mAP=0.383.pth"       "$ROOT/research/upstream/panns/"
cp -n "$ASSETS/research/upstream/BeatNet/model_1_weights.pt"            "$ROOT/research/upstream/BeatNet/"
cp -n "$ASSETS/research/upstream/yamnet/yamnet.h5"                      "$ROOT/research/upstream/yamnet/"
cp -n "$ASSETS/research/upstream/pretrained-sed/resources/frame_mn10_strong_1.pt" \
      "$ROOT/research/upstream/pretrained-sed/resources/"
cp -n "$ASSETS/research/upstream/pretrained-sed/hf_dataset_gen/metadata/audioset_train_strong.csv" \
      "$ROOT/research/upstream/pretrained-sed/hf_dataset_gen/metadata/"
cp -n "$ASSETS/research/upstream/pretrained-sed/hf_dataset_gen/metadata/audioset_eval_strong.csv" \
      "$ROOT/research/upstream/pretrained-sed/hf_dataset_gen/metadata/"
cp -n "$ASSETS/research/hardware-1.2.0/tesla-xlights.zip"               "$ROOT/research/hardware-1.2.0/"
```

Inventory under `/workspace/lightforge-assets/research/`:

| On-disk path | ~Size |
|--------------|-------|
| `research/upstream/pretrained-sed/hf_dataset_gen/metadata/audioset_train_strong.csv` | 35M |
| `research/upstream/panns/Cnn6_mAP=0.343.pth` | 23M |
| `research/upstream/panns/MobileNetV2_mAP=0.383.pth` | 20M |
| `research/upstream/yamnet/yamnet.h5` | 15M |
| `research/upstream/pretrained-sed/resources/frame_mn10_strong_1.pt` | 15M |
| `research/hardware-1.2.0/tesla-xlights.zip` | 8.3M |
| `research/upstream/pretrained-sed/hf_dataset_gen/metadata/audioset_eval_strong.csv` | 5.2M |
| `research/upstream/BeatNet/model_1_weights.pt` | 1.6M |

Research media still in the **private extract** (gitignored, not moved to `lightforge-assets/`):

| Private path | ~Size |
|--------------|-------|
| `research/model-source/2024_tesla_model_3.glb` | 8.4M |
| `research/upstream/vocal-candidates/EfficientAT/resources/metro_station-paris.wav` | 1.3M |
| `research/upstream/pretrained-sed/test_files/*.wav` | small |

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
mkdir -p "$ROOT/research/model-source"
cp -n "$PRIV/research/model-source/2024_tesla_model_3.glb" "$ROOT/research/model-source/"
# + wavs as needed from the same PRIV tree
```

## Restore C — oversized QA / verification JSON (optional)

```bash
ASSETS=/workspace/lightforge-assets
ROOT="$(pwd)"
cp -n "$ASSETS/release-verification.json" "$ROOT/"
# sample / demo / synthetic activation dumps (not on main after 99e038d):
# cp -a "$ASSETS/qa/." "$ROOT/qa/"
```

## Signing (local only)

Restore or generate under `signing/` **outside git**. Never `git add` keystores, password files, or signing directories.

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
# cp -a "$PRIV/signing" "$(pwd)/signing"   # never git add
```

`build.sh` creates a local identity on first build if none exists; keep that identity for install-over updates. See [`BUILD.md`](BUILD.md) (signing continuity). No secret values belong in documentation.

## Related docs

- [`BUILD.md`](BUILD.md) — toolchain bootstrap and APK build
- [`RESOURCES_MAP.md`](RESOURCES_MAP.md) — Android `res/` + web layout
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — offline WebView shell, APK-bundled models
