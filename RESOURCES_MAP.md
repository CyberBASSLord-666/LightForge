# LightForge resources map

The app lives at the repository root. `version.json` defines the release; builds create `dist/LightForge-<version>.apk`. See [BUILD.md](BUILD.md) and [ASSETS.md](ASSETS.md).

| Location | Responsibility |
| --- | --- |
| `android/res/`, `android/AndroidManifest.xml` | Launcher, native theme, permissions and package metadata |
| `android/src/` | Android lifecycle, media decoding, project storage, WebView transport and export |
| `web/version.js` | Generated runtime identity from `version.json` |
| `web/cockpit.js`, `web/cockpit.css` | Compose/Music/Outputs/Review navigation and musical score |
| `web/app.js`, `web/*studio*.js` | Project orchestration, transactional edits, output control and musical corrections |
| `web/analysis/separator-deux.js`, `models/deux/` | Full-context Studio voice/instrument separation |
| `web/analysis/separator-mdx.js` | Balanced separation with the retained MDX model |
| `web/analysis/game.js`, `models/game/` | Learned singing-note timing and pitch |
| `web/analysis/stem-cache.js` | Replaceable, bounded Float32 audio caches on the source clock |
| `web/analysis/worker.js` | Offline rhythm, source separation, singing evidence and bass orchestration |
| `web/analysis/ASSET_MANIFEST.json` | Exact inventory and hashes for every analysis asset |
| `web/engine/` | Vehicle profile, constraints, choreography, manual cues, frame compilation and synchronization review |
| `web/preview/src/`, `web/preview/models/` | Renderer source and attributed Highland vehicle geometry |
| `qa/release-2.1.0/` | Current reference, runtime, browser, native and regression evidence |
| `tools/prepare_game.py`, `tools/prepare_deux.py` | Pinned model reproduction at build time |
| `tools/apk_delta.py`, `tools/publish_github_release.py` | Exact signed-APK transfer and gated GitHub publication |

The full APK includes all models, WebAssembly, fonts, geometry, notices and demo audio. Development npm dependencies, test fixtures, build caches and signing material are excluded. Historical evidence remains in its original versioned folders.
