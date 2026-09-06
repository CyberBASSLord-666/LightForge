# Assets not in git

Large / private files live on the build machine, not in this repo.

| Location | Contents |
|----------|----------|
| Private extract `…/app/lightforge/` | Full tree including `signing/`, ONNX/WASM/wav/glb |
| `/workspace/lightforge-assets/` | Dropped research weights (`.pth`/`.pt`/`.h5`), Audioset CSVs, `tesla-xlights.zip`, oversized QA JSONs |

Also excluded by `.gitignore`: web ONNX/WASM/wav/glb (see Resources fat-bin list). Restore before full offline analysis builds. Signing keystore stays local under `signing/` only — never commit.
