"""Fail-closed tensor loading for the isolated EfficientAT research environment.

Restricted unpickling is defense in depth, not checkpoint authenticity or a
sandbox. Only use trusted checkpoints; never retry a rejected file unrestricted.
"""
import re
from urllib.parse import urlsplit

import torch


def _require_patched_torch():
    version = str(torch.__version__)
    # Prereleases and old versions are not the reviewed research baseline.
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\+[A-Za-z0-9._-]+)?", version)
    if match is None or tuple(map(int, match.groups())) < (2, 13, 0):
        raise RuntimeError("EfficientAT research loading requires stable torch >=2.13.0; "
                           "install its isolated security-migration requirements")

    if torch.serialization.get_safe_globals():
        raise ValueError('Custom checkpoint classes require isolated trusted conversion first')


def load_tensor_file(path):
    _require_patched_torch()
    return torch.load(path, map_location="cpu", weights_only=True)


def load_state_dict_from_url(url, *, model_dir, map_location="cpu", weights_only=True):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Checkpoint downloads require HTTPS without credentials')
    if weights_only is not True:
        raise ValueError("Unrestricted checkpoint loading is not supported")
    _require_patched_torch()
    return torch.hub.load_state_dict_from_url(
        url, model_dir=model_dir, map_location=map_location, weights_only=True)
