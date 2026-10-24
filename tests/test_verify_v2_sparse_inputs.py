"""Sparse CI must execute the same security corpus without resetting user work."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import verify_v2
import verification_evidence_manifest as evidence


class SparseResearchInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.git('init','-q')
        self.git('config','user.email','test@example.invalid')
        self.git('config','user.name','Test')
        self.rel='research/upstream/omitted/helpers/safe_index.py'
        self.path=self.root/self.rel
        self.path.parent.mkdir(parents=True)
        self.path.write_text('value = 42\n')
        (self.path.parent/'requirements.txt').write_text('example==1\n')
        (self.root/'kept').mkdir()
        (self.root/'kept/input.txt').write_text('kept\n')
        self.git('add','.')
        self.git('commit','-qm','Fixture')
        self.git('sparse-checkout','set','kept')
        self.assertFalse(self.path.exists())

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.STDOUT)

    def test_sparse_corpus_restored_from_current_head_and_provenance_recorded(self):
        index_before=self.git('ls-files','--stage')
        result=verify_v2.prepare_regression_test_inputs(self.root)
        self.assertEqual(self.path.read_text(),'value = 42\n')
        self.assertEqual(result['head'],self.git('rev-parse','HEAD').decode().strip())
        self.assertEqual(len(result['files']),2)
        self.assertTrue(all(f['matches_head'] and f['materialized'] for f in result['files'].values()))
        receipt={'regression-verification.json': {'source_hashes': {p:v['sha256'] for p,v in result['files'].items()}}}
        bound=evidence._seal_source_bindings(receipt,source_root=self.root,source_commit=result['head'],
                                             release='2.4.2',output=self.root/'sealed')
        self.assertTrue(all(v['origin']=='candidate_tree' for v in bound.values()))
        self.assertEqual(index_before,self.git('ls-files','--stage'))
        again=verify_v2.prepare_regression_test_inputs(self.root,materialize=False)
        self.assertFalse(any(f['materialized'] for f in again['files'].values()))

    def test_existing_dirty_and_untracked_files_preserved_and_honestly_bound(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('local edit\n')
        extra=self.path.parent/'local.py'
        extra.write_text('untracked = True\n')
        (self.root/'kept/input.txt').write_text('unrelated edit\n')
        result=verify_v2.prepare_regression_test_inputs(self.root)
        self.assertEqual(self.path.read_text(),'local edit\n')
        self.assertFalse(result['files'][self.rel]['matches_head'])
        self.assertFalse(result['files'][self.rel]['materialized'])
        self.assertIsNone(result['files'][str(extra.relative_to(self.root))]['head_blob'])
        self.assertEqual((self.root/'kept/input.txt').read_text(),'unrelated edit\n')
        with patch.object(verify_v2,'ROOT',self.root), patch.object(verify_v2,'digest',return_value='fixture'):
            self.assertTrue(set(result['files']) <= set(verify_v2.hashes()))
        for relative in (self.rel,str(extra.relative_to(self.root))):
            receipt={'regression-verification.json': {'source_hashes': {relative:result['files'][relative]['sha256']}}}
            with self.assertRaisesRegex(ValueError,'not an exact candidate-tree byte'):
                evidence._seal_source_bindings(receipt,source_root=self.root,source_commit=result['head'],
                                               release='2.4.2',output=self.root/'sealed')

    def test_missing_non_sparse_file_is_not_recreated(self):
        self.git('update-index','--no-skip-worktree',self.rel)
        with self.assertRaisesRegex(RuntimeError,'not an unchanged sparse omission'):
            verify_v2.prepare_regression_test_inputs(self.root)
        self.assertFalse(self.path.exists())

    def test_staged_modified_missing_input_is_not_reset(self):
        oid=self.git('rev-parse','HEAD:kept/input.txt').decode().strip()
        self.git('update-index','--cacheinfo','100644,'+oid+','+self.rel)
        self.git('update-index','--skip-worktree',self.rel)
        with self.assertRaisesRegex(RuntimeError,'not an unchanged sparse omission'):
            verify_v2.prepare_regression_test_inputs(self.root)
        self.assertFalse(self.path.exists())

    def test_staged_deletion_is_not_recreated(self):
        self.git('update-index','--force-remove',self.rel)
        with self.assertRaisesRegex(RuntimeError,'not an unchanged sparse omission'):
            verify_v2.prepare_regression_test_inputs(self.root)
        self.assertFalse(self.path.exists())

    def test_symlink_file_and_parent_are_rejected_without_writing_target(self):
        outside=self.root/'outside'
        outside.mkdir()
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(outside/'missing.py')
        with self.assertRaisesRegex(RuntimeError,'Symlink'):
            verify_v2.prepare_regression_test_inputs(self.root)
        self.path.unlink()
        self.path.parent.rmdir()
        self.path.parent.symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'Symlink'):
            verify_v2.prepare_regression_test_inputs(self.root)
        self.assertEqual(list(outside.iterdir()),[])

    def test_tracked_symlink_is_not_materialized(self):
        self.git('sparse-checkout','disable')
        self.path.unlink()
        self.path.symlink_to('other.py')
        self.git('add',self.rel)
        self.git('commit','-qm','Symlink')
        self.git('sparse-checkout','set','kept')
        with self.assertRaisesRegex(RuntimeError,'Unsafe'):
            verify_v2.prepare_regression_test_inputs(self.root)

    def test_raced_parent_symlink_cannot_redirect_materialization(self):
        outside=self.root/'outside'
        outside.mkdir()
        original=verify_v2.os.open
        def replace_parent(path,flags,*args,**kwargs):
            if path=='helpers' and kwargs.get('dir_fd') is not None:
                self.path.parent.rmdir()
                self.path.parent.symlink_to(outside,target_is_directory=True)
            return original(path,flags,*args,**kwargs)
        with patch.object(verify_v2.os,'open',side_effect=replace_parent):
            with self.assertRaises(OSError):
                verify_v2.prepare_regression_test_inputs(self.root)
        self.assertEqual(list(outside.iterdir()),[])

    def test_raced_new_file_is_never_overwritten(self):
        original=verify_v2.os.open
        def create_file(path,flags,*args,**kwargs):
            if flags & verify_v2.os.O_EXCL:
                (self.path.parent/path).write_text('new user content\n')
            return original(path,flags,*args,**kwargs)
        with patch.object(verify_v2.os,'open',side_effect=create_file):
            with self.assertRaises(FileExistsError):
                verify_v2.prepare_regression_test_inputs(self.root)
        self.assertEqual((self.path.parent/'requirements.txt').read_text(),'new user content\n')

    def test_extra_document_is_restored_and_bound_like_source(self):
        self.git('sparse-checkout','disable')
        extra=self.root/verify_v2.REGRESSION_EXTRA_INPUTS[0]
        extra.parent.mkdir()
        extra.write_text('documented contract\n')
        self.git('add','.')
        self.git('commit','-qm','Document')
        self.git('sparse-checkout','set','kept')
        result=verify_v2.prepare_regression_test_inputs(self.root)
        self.assertEqual(extra.read_text(),'documented contract\n')
        self.assertTrue(result['files'][verify_v2.REGRESSION_EXTRA_INPUTS[0]]['matches_head'])
        self.assertTrue(result['files'][verify_v2.REGRESSION_EXTRA_INPUTS[0]]['materialized'])
        with patch.object(verify_v2,'ROOT',self.root), patch.object(verify_v2,'digest',return_value='fixture'):
            snapshot=verify_v2.hashes()
        self.assertTrue(set(result['files']) <= set(snapshot))

    def test_after_run_check_never_rehydrates_deleted_inputs(self):
        verify_v2.prepare_regression_test_inputs(self.root)
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError,'not an unchanged sparse omission'):
            verify_v2.prepare_regression_test_inputs(self.root,materialize=False)
        self.assertFalse(self.path.exists())


if __name__=='__main__':
    unittest.main()
