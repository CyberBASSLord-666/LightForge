"""Retained vehicle geometry must keep its licensed source and texture fidelity.

These are current invariants, not a new rendering or release qualification.
"""
import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read_glb(path):
    data = path.read_bytes()
    if len(data) < 28 or struct.unpack_from('<III', data) != (0x46546C67, 2, len(data)):
        raise ValueError('Invalid GLB header')
    length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A or length % 4 or 28 + length > len(data):
        raise ValueError('Invalid GLB JSON chunk')
    document = json.loads(data[20:20 + length])
    size, kind = struct.unpack_from('<II', data, 20 + length)
    if kind != 0x004E4942 or 28 + length + size != len(data):
        raise ValueError('Invalid GLB binary chunk')
    return document, data[28 + length:]


def textures(document, binary):
    result = []
    for image in document['images']:
        if image.get('uri') or image['mimeType'] != 'image/png':
            raise ValueError('Expected embedded PNG texture')
        view = document['bufferViews'][image['bufferView']]
        offset, size = view.get('byteOffset', 0), view['byteLength']
        if view.get('buffer', 0) != 0 or offset < 0 or size < 8 or offset + size > len(binary):
            raise ValueError('Texture outside embedded buffer')
        texture = binary[offset:offset + size]
        if not texture.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Texture format does not match PNG declaration')
        result.append(texture)
    return result


class RenderAssetIntegrityTest(unittest.TestCase):
    def test_geometry_retains_attributed_source_and_all_embedded_texture_bytes(self):
        original = ROOT / 'research/model-source/2024_tesla_model_3.glb'
        rendered = ROOT / 'web/preview/models/highland.glb'
        source, source_binary = read_glb(original)
        model, model_binary = read_glb(rendered)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),
                         model['asset']['extras']['lightforge_source_sha256'])
        for key in ['author', 'license', 'source', 'title']:
            self.assertEqual(model['asset']['extras'][key], source['asset']['extras'][key])
        self.assertEqual(len(model['meshes']), 684)
        self.assertEqual(len(model['images']), 6)
        self.assertEqual(textures(model, model_binary), textures(source, source_binary))
        self.assertFalse(any(item.get('uri') for item in model['buffers']))
        self.assertIn(model['asset']['extras']['lightforge_source_sha256'],
                      (ROOT / 'web/preview/models/CREDITS.md').read_text())

    def test_offline_font_container_is_complete_and_license_is_bundled(self):
        data = (ROOT / 'web/fonts/InterVariable.woff2').read_bytes()
        self.assertEqual(data[:4], b'wOF2')
        self.assertEqual(struct.unpack_from('>I', data, 8)[0], len(data))
        self.assertGreater(struct.unpack_from('>H', data, 12)[0], 0)
        self.assertIn('SIL OPEN FONT LICENSE Version 1.1',
                      (ROOT / 'web/fonts/OFL.txt').read_text())


if __name__ == '__main__':
    unittest.main()
