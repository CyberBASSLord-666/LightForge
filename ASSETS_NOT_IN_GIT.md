# Large / private assets excluded from git

Restore from the private 1.6.0 archive before a full offline build:

- Large `web/analysis/models/*.onnx` (keep small mel frontend if present)
- `web/analysis/vendor/ort-wasm-simd-threaded.wasm`
- `web/demo/glass-castle.wav`
- `web/preview/models/highland.glb`
- `signing/` (never commit)

Build: `python3 tools/bootstrap_toolchain.py`, then unset `ANDROID_SDK_ROOT`/`ANDROID_HOME` and run `bash build.sh`.
