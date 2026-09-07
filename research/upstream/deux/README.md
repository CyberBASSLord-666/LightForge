# Deux conversion source

`models/bs_roformer/{mel_band_roformer,attend}.py` are copied from
[ZFTurbo/Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training/tree/0e5f1159fc5ea87fc13b957584e178b4977e5dd3), under its MIT license.
`config.yaml` is the author's configuration from
[becruily/mel-band-roformer-deux](https://huggingface.co/becruily/mel-band-roformer-deux/tree/2da74427d682a3df47a774378fc24d7a1a0cdaad).

The model weights and their converted derivatives are CC BY-NC 4.0; the
architecture code's MIT license is not a replacement weight license.
`tools/prepare_deux.py` records the exact checkpoint checksum, preserves all
weights, and exports fixed 13-second-context stages with full attention.
