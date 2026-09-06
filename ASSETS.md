# Assets not in git

Large / private files live **on disk**, not in this repo. No Git LFS yet (escalate to Chief of Staff if wanted).

## On-disk locations

| Path | Role |
|------|------|
| `/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge/` | **Private extract** — full `web/` ONNX/WASM/wav/glb, research glb/wavs still under tree, `signing/` |
| `/workspace/lightforge-assets/` | **Dropped from git** — research weights (`.pth`/`.pt`/`.h5`), Audioset CSVs, `tesla-xlights.zip`, oversized QA / `release-verification.json` |
| This repo (`main`) / `/workspace/lightforge-git-seed` | Source + small assets only (`web/analysis/models/beat-this-mel.onnx` kept) |

Signing stays under private `signing/` only — never commit.

## Restore A — web fat bins (required for full APK)

Source: **private extract** (not under `lightforge-assets/`).

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
ROOT="$(pwd)"   # git checkout, e.g. /workspace/lightforge-git-seed

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

Then build:

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

Research media still in **private extract** (gitignored, not moved to `lightforge-assets/`):

| Private path | ~Size |
|--------------|-------|
| `research/model-source/2024_tesla_model_3.glb` | 8.4M |
| `research/upstream/vocal-candidates/EfficientAT/resources/metro_station-paris.wav` | 1.3M |
| `research/upstream/pretrained-sed/test_files/*.wav` | small |

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
cp -n "$PRIV/research/model-source/2024_tesla_model_3.glb" "$ROOT/research/model-source/"
# + wavs as needed from the same PRIV tree
```

## Restore C — oversized QA / verification JSON (optional)

```bash
ASSETS=/workspace/lightforge-assets
ROOT="$(pwd)"
cp -n "$ASSETS/release-verification.json" "$ROOT/"
# sample activation dumps:
# cp -a "$ASSETS/qa/." "$ROOT/qa/"
```

## Signing (local only)

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
# cp -a "$PRIV/signing" "$(pwd)/signing"   # never git add
```

See also [`RESOURCES_MAP.md`](RESOURCES_MAP.md) for Android `res/` + web layout.
