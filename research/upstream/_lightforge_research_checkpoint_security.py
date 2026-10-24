"""Restricted checkpoint loading for vendored research, never an unsafe fallback.

This protects deserialization boundaries, not model provenance or numerical
qualification. Serialized arbitrary classes require separate trusted conversion.
"""
import re
from urllib.parse import urlsplit

import torch


def _require_patched_restricted_runtime():
    version = str(torch.__version__)
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:\+[A-Za-z0-9._-]+)?', version)
    if match is None or tuple(map(int, match.groups())) < (2, 13, 0):
        raise RuntimeError('Research checkpoint loading requires stable Torch >=2.13.0')
    # Do not let ambient allowlists turn weights_only into arbitrary class loading.
    if torch.serialization.get_safe_globals():
        raise ValueError('Custom checkpoint classes are not accepted; convert trusted '
                         'legacy objects to plain tensor state dictionaries in an '
                         'isolated trusted environment first')


def load_tensor_checkpoint(path, map_location='cpu', pickle_module=None, *, weights_only=True, **kwargs):
    if weights_only is not True or pickle_module is not None:
        raise ValueError('Unrestricted checkpoint deserialization is not supported')
    _require_patched_restricted_runtime()
    return torch.load(path, map_location=map_location, weights_only=True, **kwargs)


def load_remote_tensor_checkpoint(url, model_dir=None, map_location='cpu', progress=True,
                                  check_hash=False, file_name=None, weights_only=True):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Research checkpoint downloads require an HTTPS URL without credentials')
    if weights_only is not True:
        raise ValueError('Unrestricted checkpoint deserialization is not supported')
    _require_patched_restricted_runtime()
    return torch.hub.load_state_dict_from_url(
        url, model_dir=model_dir, map_location=map_location, progress=progress,
        check_hash=check_hash, file_name=file_name, weights_only=True)
