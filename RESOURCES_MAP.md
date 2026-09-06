# LightForge 1.6.0 — Resources map

**Project:** `/workspace/LightForge-1.6.0-Private-Source/LightForge-1.6.0/app/lightforge/`
**Built APK:** `dist/LightForge-1.6.0.apk` (177M, v10600)

## Android `android/res/` (minimal — same pattern as 1.5.0)

| Name | Path | Notes |
|------|------|-------|
| `ic_launcher` | `drawable/ic_launcher.xml` | vector 108dp; bg `#0B1222`, bolt `#9EFF85`, cyan strokes |
| `AppTheme` | `values/styles.xml` | `Theme.Material.NoActionBar`; `#080D18` / accent `#9EFF85` |

No layouts/mipmaps/strings — UI is WebView from `web/` (packaged as assets at build).

## Web UI (`web/` → APK assets)

Same tree as 1.5.0 assets, plus 1.6.0 stem-sep additions:
- `analysis/separator-mdx.js`, `stem-cache.js`, `vocal-detail.js`
- `analysis/models/uvr-mdx-voc-ft.onnx` (~64M) + license/notice + `separator-mdx-model.json`

## Fat binaries (keep out of git / use LFS)

| Path under `web/` | ~Size |
|-------------------|-------|
| `analysis/models/beat-this-large.onnx` | 80M |
| `analysis/models/uvr-mdx-voc-ft.onnx` | 64M **NEW in 1.6.0** |
| `analysis/models/frame-mn10-singing.onnx` | 13M |
| `demo/glass-castle.wav` | 11M |
| `analysis/vendor/ort-wasm-simd-threaded.wasm` | 11M |
| `analysis/models/beat-this-small.onnx` | 11M |
| `preview/models/highland.glb` | 8.4M |

## vs 1.5.0 APK assets

- Android res: theme/launcher equivalent (readable source; hex case differs only)
- Assets: 1.5.0 subset ⊆ 1.6.0; **+7 files** all stem/MDX vocal separation
- No files dropped from 1.5.0 → 1.6.0 web
