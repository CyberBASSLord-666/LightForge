# Assets not in git

Large / private files live on the build machine, not in this repo. Use this doc to restore a full build tree.

## Where the bits live

| Location | Contents |
|----------|----------|
| Private extract `/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge/` | Full tree: `web/` ONNX/WASM/wav/glb + `signing/` |
| `/workspace/lightforge-assets/` | Dropped research weights (`.pth`/`.pt`/`.h5`), Audioset CSVs, `tesla-xlights.zip`, oversized QA JSONs |
| This repo (`main`) | Source + small assets only (`beat-this-mel.onnx` kept) |

Signing keystore stays under `signing/` locally — never commit. LFS not enabled; escalate to Chief of Staff if you want Git LFS instead of archive restore.

## Restore web fat bins into a git checkout (required for full APK)

From the **git checkout root** (e.g. `/workspace/lightforge-git-seed`):

```bash
PRIV=/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge
ROOT="$(pwd)"

mkdir -p \
  "$ROOT/web/analysis/models" \
  "$ROOT/web/analysis/vendor" \
  "$ROOT/web/demo" \
  "$ROOT/web/preview/models"

cp -n "$PRIV/web/analysis/models/beat-this-large.onnx"        "$ROOT/web/analysis/models/"
cp -n "$PRIV/web/analysis/models/beat-this-small.onnx"        "$ROOT/web/analysis/models/"
cp -n "$PRIV/web/analysis/models/frame-mn10-singing.onnx"     "$ROOT/web/analysis/models/"
cp -n "$PRIV/web/analysis/models/beatnet-v1.onnx"             "$ROOT/web/analysis/models/"
cp -n "$PRIV/web/analysis/models/uvr-mdx-voc-ft.onnx"         "$ROOT/web/analysis/models/"
cp -n "$PRIV/web/analysis/vendor/ort-wasm-simd-threaded.wasm" "$ROOT/web/analysis/vendor/"
cp -n "$PRIV/web/demo/glass-castle.wav"                      "$ROOT/web/demo/"
cp -n "$PRIV/web/preview/models/highland.glb"                "$ROOT/web/preview/models/"
```

`cp -n` skips existing files. Then:

```bash
python3 tools/bootstrap_toolchain.py
unset ANDROID_SDK_ROOT ANDROID_HOME
bash build.sh
# → dist/LightForge-1.6.0.apk
```

## Web fat-bin checklist (must match `.gitignore`)

| Path under `web/` | ~Size | In git? |
|-------------------|-------|---------|
| `analysis/models/beat-this-large.onnx` | 80M | no |
| `analysis/models/uvr-mdx-voc-ft.onnx` | 64M | no |
| `analysis/models/frame-mn10-singing.onnx` | 13M | no |
| `analysis/models/beat-this-small.onnx` | 11M | no |
| `analysis/vendor/ort-wasm-simd-threaded.wasm` | 11M | no |
| `demo/glass-castle.wav` | 11M | no |
| `preview/models/highland.glb` | 8.4M | no |
| `analysis/models/beatnet-v1.onnx` | 1.6M | no |
| `analysis/models/beat-this-mel.onnx` | 268K | **yes** |

Also gitignored (research / QA, not needed for app APK): research glb/wavs, `**/*.{pth,pt,h5}`, Audioset CSVs, `tesla-xlights.zip`, oversized activation JSONs, `release-verification.json`. See `/workspace/lightforge-assets/` for dropped copies.

## Optional: research binaries

```bash
# only if you need research tooling — not required for LightForge APK
# cp -n "$PRIV/research/model-source/2024_tesla_model_3.glb" "$ROOT/research/model-source/"
# cp -a /workspace/lightforge-assets/research/. "$ROOT/research/"   # weights etc.
```

## Signing (local only)

```bash
# cp -a "$PRIV/signing" "$ROOT/signing"   # never git add
```

See also [`RESOURCES_MAP.md`](RESOURCES_MAP.md) for Android `res/` + web layout.
