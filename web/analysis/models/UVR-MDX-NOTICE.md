# UVR MDX-Net Voc FT attribution

The pretrained `UVR-MDX-NET-Voc_FT.onnx` weights were trained and distributed by the Ultimate Vocal Remover project. Credit: **UVR and its developers Anjok07 and aufr33**. The MDX-Net architecture was developed by **KUIELab / Woosung Choi and collaborators**.

Primary permission statement: <https://github.com/Anjok07/ultimatevocalremovergui#license>. The authors identify the models as MIT licensed and request credit to UVR and its developers. The original architecture's complete MIT license is provided in `MDX-NET-LICENSE.txt`. Upstream license statements and inference source are retained in the private source archive.

The pretrained model bytes are unmodified. `separator-mdx-model.json` records their SHA-256, original asset URL, verified model parameters and model-tail identifier. The JavaScript STFT, reconstruction, bounded streaming and orchestration are implemented for LightForge; they do not alter the trained weights.

The model estimates a combined vocal stem, including backing vocals and effects. It does not understand words or guarantee perfect vocal isolation, especially for distorted voices, vocal-like synths, reverberation and dense mixes. CPU time and memory depend on the device.
