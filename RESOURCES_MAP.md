# LightForge 1.6.0 — Resources map

**Private tree:** `/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge/`
**Git seed / `main`:** `/workspace/lightforge-git-seed` → https://github.com/CyberBASSLord-666/LightForge
**Built APK:** `dist/LightForge-1.6.0.apk` (177M, v10600)
**Restore fat bins:** see [`ASSETS.md`](ASSETS.md)

## Android `android/res/` (minimal)

| Name | Path | Notes |
|------|------|-------|
| `ic_launcher` | `drawable/ic_launcher.xml` | vector 108dp; bg `#0B1222`, bolt `#9EFF85`, cyan strokes |
| `AppTheme` | `values/styles.xml` | `Theme.Material.NoActionBar`; `#080D18` / accent `#9EFF85` |

No layouts/mipmaps/strings — UI is WebView from `web/` (packaged as assets at build).

## Web UI (`web/` → APK assets)

Same tree as 1.5.0 assets, plus 1.6.0 stem-sep additions:
- `analysis/separator-mdx.js`, `stem-cache.js`, `vocal-detail.js`
- `analysis/models/uvr-mdx-voc-ft.onnx` (~64M) + license/notice + `separator-mdx-model.json`

## Fat binaries vs git

**In git:** `beat-this-mel.onnx` (~268K) + licenses/JSON + all JS/CSS/HTML/fonts.

**Not in git** (must restore for full build — listed in `.gitignore`):

| Path under `web/` | ~Size |
|-------------------|-------|
| `analysis/models/beat-this-large.onnx` | 80M |
| `analysis/models/uvr-mdx-voc-ft.onnx` | 64M (new in 1.6.0) |
| `analysis/models/frame-mn10-singing.onnx` | 13M |
| `demo/glass-castle.wav` | 11M |
| `analysis/vendor/ort-wasm-simd-threaded.wasm` | 11M |
| `analysis/models/beat-this-small.onnx` | 11M |
| `preview/models/highland.glb` | 8.4M |
| `analysis/models/beatnet-v1.onnx` | 1.6M |

Also gitignored (research/QA — restore via [`ASSETS.md`](ASSETS.md)):
- Weights/CSVs/zip from `/workspace/lightforge-assets/research/` (+ QA JSONs there)
- Media still in private extract: `research/model-source/2024_tesla_model_3.glb`, research wav samples

## vs 1.5.0 APK assets

- Android res: theme/launcher equivalent
- Assets: 1.5.0 ⊆ 1.6.0; **+7** stem/MDX files; no drops
