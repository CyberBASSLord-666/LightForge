"""Compare shipped output to Tesla's independently published xLights contract."""
import base64
import hashlib
import io
import json
from pathlib import Path
import runpy
import struct
import subprocess
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'research/hardware-1.2.0'


class XLightsInteroperability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = r"""
const E=require('./web/engine/show-engine.js');
const input={duration:2.0399773243,bpm:120,beatConfidence:.95,beats:[0,.5,1,1.5,2],
  downbeats:[0,2],sections:[{start:0,end:2.0399773243,energy:.7}],waveform:[.7,.8,.6]};
const exports=[15,20].map(stepMs=>{
  const show=E.generate(input,{stepMs,dance:'off'});
  return {stepMs,frameCount:show.frameCount,bytes:Buffer.from(E.fseq(show,'contract.wav')).toString('base64'),
    payloadSha256:require('node:crypto').createHash('sha256').update(show.frames).digest('hex')};
});
process.stdout.write(JSON.stringify({outputs:E.getCapabilities().outputs,exports}));
"""
        cls.data = json.loads(subprocess.check_output(['node', '-e', source], cwd=ROOT, text=True))
        cls.validate = staticmethod(runpy.run_path(str(REFERENCE / 'commands-official-validator.py'))['validate'])
        cls.models = {m.attrib['name']: m for m in ET.parse(REFERENCE / 'commands-official-xlights_rgbeffects.xml').findall('./models/model')}

    def test_official_reference_snapshots_are_pinned(self):
        # Confirmed against teslamotors/light-show commit
        # 9f949512146d881b6eb66d042b22ee3f9e115afb on 2026-09-27.
        expected = {
            'commands-official-validator.py': '458b5141256c7abc8d3002fd66ab195131d317d384cc42819b75db444c5da027',
            'commands-official-xlights_rgbeffects.xml': '30760295adba5b859a86fd749eb6269ad6057b48ea92d623e5fdb69512995841',
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((REFERENCE / name).read_bytes()).hexdigest(), digest, name)

    def test_every_physical_output_maps_to_named_official_xlights_models(self):
        named = {
            'park-markers': ['Left Aux Park', 'Right Aux Park', 'Left Side Marker', 'Right Side Marker'],
            'brakes': ['Brake Lights'], 'reverse': ['Reverse Lights'], 'rear-fog': ['Rear Fog Lights'],
            'license-plate': ['License Plate'], 'display': ['Center Front Display'],
            'rgb-dash': ['Center Front RGB'], 'trunk': ['Liftgate'], 'charge': ['Charge Port'],
            'mirrorL': ['Left Mirror'], 'mirrorR': ['Right Mirror'],
            'windowFL': ['Left Front Window'], 'windowRL': ['Left Rear Window'],
            'windowFR': ['Right Front Window'], 'windowRR': ['Right Rear Window'],
        }
        for side in ['left', 'right']:
            label = side.title()
            for suffix, model in [('outer', 'Outer Main Beam'), ('inner', 'Inner Main Beam'),
                                  ('signature', 'Signature'), ('front-turn', 'Front Turn'),
                                  ('front-fog', 'Front Fog'), ('repeater', 'Side Repeater'),
                                  ('rear-turn', 'Rear Turn'), ('tail', 'Tail')]:
                named[side + '-' + suffix] = [label + ' ' + model]
            named[side + '-combined'] = [label + ' Channel ' + str(n) for n in [4, 5, 6]]
            for row in ['front', 'rear']:
                named['rgb-' + side + '-' + row] = [label + ' ' + row.title() + ' RGB']
        self.assertEqual(set(named), {row['id'] for row in self.data['outputs']}, 'every profile output must be audited')
        for output in self.data['outputs']:
            channels = []
            for name in named[output['id']]:
                model = self.models[name]
                start = int(model.attrib['StartChannel'].rsplit(':', 1)[-1])
                channels.extend(range(start, start + (3 if model.attrib['StringType'] == 'RGB Nodes' else 1)))
            self.assertEqual(output['channels'], channels, output['id'])

    def test_production_fseq_passes_teslas_validator_and_payload_contract(self):
        for sample in self.data['exports']:
            with self.subTest(stepMs=sample['stepMs']):
                binary = base64.b64decode(sample['bytes'])
                validated = self.validate(io.BytesIO(binary))
                self.assertEqual(validated.frame_count, sample['frameCount'])
                self.assertEqual(validated.step_time, sample['stepMs'])
                offset = struct.unpack_from('<H', binary, 4)[0]
                self.assertEqual(binary[:4], b'PSEQ')
                self.assertEqual(binary[6:8], b'\0\2')
                self.assertEqual(struct.unpack_from('<H', binary, 8)[0], 32)
                self.assertEqual(struct.unpack_from('<I', binary, 10)[0], 200)
                self.assertEqual(binary[19:32], bytes(13), 'no compression, sparse ranges, flags or UUID')
                self.assertEqual(len(binary), offset + 200 * sample['frameCount'])
                self.assertEqual(hashlib.sha256(binary[offset:]).hexdigest(), sample['payloadSha256'])
                fields = {}
                cursor = 32
                while cursor + 4 <= offset:
                    length = struct.unpack_from('<H', binary, cursor)[0]
                    if length == 0:
                        break
                    self.assertGreaterEqual(length, 4)
                    self.assertLessEqual(cursor + length, offset)
                    fields[binary[cursor+2:cursor+4]] = binary[cursor+4:cursor+length]
                    cursor += length
                self.assertEqual(fields[b'mf'], b'contract.wav\0')
                self.assertTrue(fields[b'sp'].startswith(b'LightForge '))


if __name__ == '__main__':
    unittest.main()
