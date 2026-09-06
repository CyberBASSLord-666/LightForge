# Rebuild the bundled vehicle geometry

The original licensed model is included here, so rebuilding does not depend on an account or network download. Credits and provenance are in `MODEL_SELECTION.md`, `download-receipt.json` and the app's `web/preview/models/CREDITS.md`.

Requirements: Python 3 and NumPy (`python3 -m pip install numpy`). Run from the project root (`app/lightforge`):

```sh
python3 research/model-source/audit_components.py
python3 research/model-source/split_components.py
python3 research/model-source/verify_split.py
python3 research/model-source/normalize-highland.py research/model-source/2024_tesla_model_3_components_v2_raw.glb web/preview/models/highland.glb
python3 research/model-source/verify_model.py web/preview/models/highland.glb
```

The split verification compares all original triangle attributes and winding plus embedded textures bit for bit. Normalization then applies a proper rotation and uniform metric scale without changing triangle topology. The bundled model has 179,692 triangles and 684 separately addressable geometric components. The runtime rig consolidates static components for rendering efficiency.
