"""The quality report uses the same immutable transfer boundary as APK evidence."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import publish_github_release as p


class QualityArtifactTransferTest(unittest.TestCase):
    def check_transfer(self, *, run_changes=None, inventory=None, artifact_changes=None, download_error=None):
        head = 'a' * 40
        run = {'id': 55, 'status': 'completed', 'conclusion': 'success',
               'head_repository': {'full_name': 'owner/repo'}, 'head_sha': head,
               'path': p.QUALITY_WORKFLOW, 'event': 'workflow_dispatch', 'head_branch': 'main'}
        run.update(run_changes or {})
        artifact = {'id': 77, 'name': p.QUALITY_ARTIFACT, 'expired': False,
                    'size_in_bytes': 100, 'digest': 'sha256:' + 'b' * 64,
                    'workflow_run': {'id': 55, 'head_sha': head, 'head_branch': 'main'}}
        artifact.update(artifact_changes or {})
        def api(path):
            if path.endswith('/actions/runs/55'): return run
            if '/git/commits/' in path: return {'tree': {'sha': 'c' * 40}}
            if '/artifacts?' in path:
                return {'artifacts': [{'id': 77, 'name': p.QUALITY_ARTIFACT}] if inventory is None else inventory}
            if path.endswith('/actions/artifacts/77'): return artifact
            raise AssertionError(path)
        def download(repo, record, destination, names):
            self.assertEqual(record, artifact)
            self.assertEqual(names, {'quality-gate-report.json', 'quality-gate-provenance.json'})
            if download_error: raise download_error
            destination.mkdir(parents=True)
            for name in names: (destination / name).write_text('{}')
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            stack.enter_context(patch.object(p, 'ROOT', Path(temporary)))
            stack.enter_context(patch.object(p, 'api', side_effect=api))
            stack.enter_context(patch.object(p, 'source_release_declaration', return_value={'requirement': 'performance_quality_gate'}))
            stack.enter_context(patch.object(p, 'validate_declaration_receipt'))
            stack.enter_context(patch.object(p, '_derive_published_release_scope', return_value={}))
            stack.enter_context(patch.object(p, '_live_benchmark_artifact', return_value=({}, {}, {})))
            validate = stack.enter_context(patch.object(p, 'validate_publication_evidence', return_value={'accepted': True}))
            transfer = stack.enter_context(patch.object(p, '_download_exact_artifact', side_effect=download))
            command = stack.enter_context(patch.object(p, 'run', side_effect=AssertionError('No gh run download permitted')))
            result = p.verify_release_quality({'quality_gate_policy': {}, 'quality_gate': {'run_id': 55}},
                                               {'name': '2.4.2', 'code': 20402}, 'owner/repo', {'head_sha': head}, head, 'c' * 40)
            transfer.assert_called_once()
            validate.assert_called_once()
            command.assert_not_called()
            self.assertTrue(result['accepted'])

    def test_exact_id_verified_metadata_and_two_file_inventory(self):
        self.check_transfer()

    def test_wrong_producer_is_rejected_before_download(self):
        for change in [{'id': 56}, {'path': '.github/workflows/other.yml'}, {'event': 'pull_request'},
                       {'head_branch': 'other'}, {'head_sha': 'b' * 40}, {'conclusion': 'failure'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check_transfer(run_changes=change)

    def test_missing_duplicate_expired_and_wrong_artifacts_fail(self):
        for inventory in [[], [{'id': 77, 'name': p.QUALITY_ARTIFACT}] * 2]:
            with self.assertRaises(ValueError): self.check_transfer(inventory=inventory)
        for change in [{'id': 88}, {'expired': True}, {'digest': None}, {'name': 'other'},
                       {'workflow_run': {'id': 56, 'head_sha': 'a' * 40, 'head_branch': 'main'}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check_transfer(artifact_changes=change)

    def test_transfer_integrity_rejection_propagates(self):
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.check_transfer(download_error=ValueError('digest mismatch'))


if __name__ == '__main__': unittest.main()
