#!/usr/bin/env python3
"""Focused contract tests for the actual-model multi-passage fixture builder."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('prepare_deux_benchmark_fixture', ROOT / 'tools/prepare_deux_benchmark_fixture.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class PrepareDeuxBenchmarkFixtureTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixtures = self.root / 'fixtures'
        self.fixtures.mkdir()
        self.first = self.fixtures / 'first-mix.wav'
        self.second = self.fixtures / 'second-mix.wav'
        self.first_pcm = np.array([[.1, -.1], [.2, -.2], [.3, -.3]], dtype=np.float32)
        self.second_pcm = np.array([[.4, -.4], [.5, -.5], [.6, -.6]], dtype=np.float32)
        wavfile.write(self.first, 44100, self.first_pcm)
        wavfile.write(self.second, 44100, self.second_pcm)
        metadata = {
            'tracks': [{'pcmSHA256': {
                self.first.name: sha256(self.first), self.second.name: sha256(self.second)}}]
        }
        (self.root / 'musdb-fixture-provenance.json').write_text(json.dumps(metadata))

    def tearDown(self):
        self.temporary.cleanup()

    def test_concatenates_only_verified_float32_source_samples_to_exact_length(self):
        output = self.root / 'benchmark.wav'
        provenance = self.root / 'benchmark.json'
        receipt = MODULE.build([self.first, self.second], 5, output, provenance)
        rate, pcm = wavfile.read(output)
        self.assertEqual(44100, rate)
        self.assertEqual(np.float32, pcm.dtype)
        self.assertTrue(np.array_equal(np.concatenate([self.first_pcm, self.second_pcm[:2]]), pcm))
        self.assertEqual(5, receipt['output']['samples'])
        self.assertEqual([3, 2], [item['used_samples'] for item in receipt['sources']])
        self.assertEqual(receipt, json.loads(provenance.read_text()))

    def test_rejects_source_not_bound_to_immutable_fixture_provenance(self):
        output = self.root / 'benchmark.wav'
        provenance = self.root / 'benchmark.json'
        wavfile.write(self.second, 44100, np.zeros_like(self.second_pcm))
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            MODULE.build([self.first, self.second], 5, output, provenance)


if __name__ == '__main__':
    unittest.main()
