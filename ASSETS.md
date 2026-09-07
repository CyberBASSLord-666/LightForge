# Assets and model reproduction

LightForge runs entirely offline. The installed APK includes every runtime model, WebAssembly binary, font, vehicle asset and required notice. Source builds download only the reproducible model inputs listed below.

| Asset family | Repository status | Build preparation |
| --- | --- | --- |
| Beat This!, UVR MDX Voc FT, Frame-MN10 and their frontends | Retained binary assets and manifests | Already present in the completed checkout |
| GAME Large 1.0.3 | Five generated graphs, approximately 376 MiB; manifests and converter tracked | `python3 tools/prepare_game.py` |
| Mel-Band RoFormer Deux | Fifteen generated graphs, approximately 842 MiB; manifests, architecture and converter tracked | `python3 tools/prepare_deux.py` |
| ONNX Runtime Web/WASM | Bundled runtime and license tracked | No additional preparation |
| Highland geometry, fonts and demo audio | Retained assets and attribution tracked | No additional preparation |
| Historical research weights, fixtures and evidence | Original preserved materials plus versioned QA | Optional research; excluded from APK |

Install the pinned model-build dependencies first as described in [BUILD.md](BUILD.md). `tools/verify_analysis_assets.py` rejects missing, added or byte-changed analysis assets. The GAME and Deux manifests pin checkpoint/archive hashes, graph hashes, authors, licenses and conversion choices. Generated graphs stay out of Git; the full APK contains them.

Deux weights are CC BY-NC 4.0. Original and modified GAME weights are CC BY-NC-SA 4.0. Architecture code licenses do not replace model-weight licenses. Keep the bundled notices and noncommercial scope. [RELEASE_NOTES.md](RELEASE_NOTES.md) records model tradeoffs and performance limits.

The historical 1.6 source migration restored all 900 non-secret backup files. `migration/` and `SOURCE_MANIFEST.json` preserve that provenance; they are historical reconstruction tools, not validators for modified 2.1 sources. See [REPOSITORY.md](REPOSITORY.md).

The original keystore and password stay together outside Git. APK candidates in Actions use a temporary identity. Release publication transfers only already-signed public APK bytes; neither the private source archive nor signing credentials may be committed or uploaded as release assets.
