"""Fixture regeneration must preserve evidence bytes and reject changed audio."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('musdb_fixture_generator',ROOT/'qa/release-1.6.0/prepare-musdb-fixtures.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FixtureProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'provenance.json'
        self.record={'archive':{'sha256':'a'*64,'bytes':100},'tracks':[{'id':'falcon','pcmSHA256':{'mix.wav':'b'*64,'vocals.wav':'c'*64}}]}

    def test_key_order_differences_preserve_exact_recorded_bytes(self):
        before=json.dumps(self.record,indent=4).encode()+b'\n\n'
        self.path.write_bytes(before)
        reordered=json.loads(json.dumps(self.record,sort_keys=True))
        self.assertFalse(module.retain_or_write_provenance(self.path,reordered))
        self.assertEqual(self.path.read_bytes(),before)

    def test_changed_waveform_hash_rejects_without_rewriting(self):
        before=json.dumps(self.record).encode()
        self.path.write_bytes(before)
        changed=json.loads(before)
        changed['tracks'][0]['pcmSHA256']['mix.wav']='d'*64
        with self.assertRaisesRegex(ValueError,'Regenerated MUSDB fixtures differ'):
            module.retain_or_write_provenance(self.path,changed)
        self.assertEqual(self.path.read_bytes(),before)

    def test_changed_archive_metadata_rejects_without_rewriting(self):
        before=json.dumps(self.record).encode()
        self.path.write_bytes(before)
        changed=json.loads(before)
        changed['archive']['bytes']=101
        with self.assertRaises(ValueError):module.retain_or_write_provenance(self.path,changed)
        self.assertEqual(self.path.read_bytes(),before)

    def test_new_record_has_deterministic_key_order(self):
        self.assertTrue(module.retain_or_write_provenance(self.path,self.record))
        self.assertEqual(self.path.read_text(),json.dumps(self.record,indent=2,sort_keys=True)+'\n')

    def test_malformed_existing_record_is_never_replaced(self):
        before=b'{broken'
        self.path.write_bytes(before)
        with self.assertRaises(json.JSONDecodeError):module.retain_or_write_provenance(self.path,self.record)
        self.assertEqual(self.path.read_bytes(),before)

if __name__=='__main__':unittest.main()
