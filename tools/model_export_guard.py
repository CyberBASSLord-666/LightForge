"""Fail-closed source and toolchain admission for reproducible model exports."""
from importlib import metadata
from pathlib import Path
import hashlib
import platform

PYTHON_VERSION = '3.12.14'
TORCH_VERSION = '2.13.0+cpu'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_digest(path, expected, label):
    if digest(path) != expected:
        raise ValueError(f'{label} hash mismatch')


def exporter_identity(root):
    """Verify approved installed distributions before model code is imported."""
    root = Path(root)
    python_version = platform.python_version()
    if python_version != PYTHON_VERSION:
        raise ValueError(f'Model exporter Python mismatch: expected {PYTHON_VERSION}; installed {python_version}')
    expected = {'torch': TORCH_VERSION}
    requirements = root / 'tools/model-requirements.txt'
    for line in requirements.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, version = line.partition('==')
        if not separator or not name or not version or any(c.isspace() for c in version):
            raise ValueError('Model requirements must use exact version pins')
        if name in expected:
            raise ValueError(f'Duplicate model requirement: {name}')
        expected[name] = version
    installed = {name: metadata.version(name) for name in expected}
    if installed != expected:
        raise ValueError(f'Model exporter toolchain mismatch: expected {expected}; installed {installed}')
    sources = ['tools/model-requirements.txt', 'tools/model_export_guard.py',
               'research/upstream/deux/config.yaml',
               'research/upstream/deux/models/bs_roformer/attend.py',
               'research/upstream/deux/models/bs_roformer/mel_band_roformer.py']
    return {'python': python_version, 'distributions': installed,
            'sourceSHA256': {name: digest(root / name) for name in sources},
            'onnxExporter': 'torch.onnx.export; dynamo=False; opset=17'}


def cached_graph_matches(path, previous, converter_sha, identity):
    path = Path(path)
    entry = previous.get('files', {}).get(path.name, {})
    return (path.is_file() and previous.get('converterSHA256') == converter_sha
            and previous.get('exporterIdentity') == identity
            and entry.get('bytes') == path.stat().st_size
            and entry.get('sha256') == digest(path))
