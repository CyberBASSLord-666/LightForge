"""No network: model GitHub tag semantics independently of release metadata."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import publish_github_release as publisher

A, B = 'a' * 40, 'b' * 40
REPO, TAG = 'owner/repo', 'v2.4.2'
REF = f'repos/{REPO}/git/matching-refs/tags/{TAG}'


def ref(sha=A, kind='commit'):
    return [{'ref': 'refs/tags/' + TAG, 'object': {'sha': sha, 'type': kind}}]


class ReleaseTagBindingTest(unittest.TestCase):
    def test_matching_lightweight_tag_is_read_twice(self):
        with patch.object(publisher, 'api', return_value=ref()) as api:
            publisher.require_release_tag(REPO, TAG, A)
        self.assertEqual([c.args[0] for c in api.call_args_list], [REF, REF])

    def test_missing_tag_only_allowed_for_draft_or_prepublication(self):
        for records in [[], [{'ref': 'refs/tags/' + TAG + '-other', 'object': {}}]]:
            with patch.object(publisher, 'api', return_value=records):
                publisher.require_release_tag(REPO, TAG, A, allow_missing=True)
                with self.assertRaisesRegex(ValueError, 'missing'):
                    publisher.require_release_tag(REPO, TAG, A)

    def test_api_failure_is_never_missing(self):
        with patch.object(publisher, 'api', side_effect=subprocess.CalledProcessError(1, ['gh'])):
            with self.assertRaises(subprocess.CalledProcessError):
                publisher.require_release_tag(REPO, TAG, A, allow_missing=True)

    def test_nested_annotated_tags(self):
        c = 'c' * 40
        responses = [ref(B, 'tag'), {'sha': B, 'object': {'sha': c, 'type': 'tag'}},
                     {'sha': c, 'object': {'sha': A, 'type': 'commit'}}, ref(B, 'tag')]
        with patch.object(publisher, 'api', side_effect=responses) as api:
            publisher.require_release_tag(REPO, TAG, A)
        self.assertEqual([call.args[0] for call in api.call_args_list],
                         [REF, f'repos/{REPO}/git/tags/{B}', f'repos/{REPO}/git/tags/{c}', REF])

    def test_wrong_commit_types_malformed_refs_and_duplicate_refs_fail(self):
        for records in [ref(B), ref(A, 'blob'), ref(A, 'tree'), ref('oops'),
                        [{'ref': 'refs/tags/' + TAG}], ref() * 2, {}, [None]]:
            with self.subTest(records=records), patch.object(publisher, 'api', return_value=records):
                with self.assertRaises(ValueError):
                    publisher.require_release_tag(REPO, TAG, A, allow_missing=True)

    def test_tag_identity_loop_and_depth_are_bounded(self):
        for objects in [[{'sha': A, 'object': {'sha': A, 'type': 'commit'}}],
                        [{'sha': B, 'object': {'sha': B, 'type': 'tag'}}],
                        [{'sha': B, 'object': {'sha': A, 'type': 'tree'}}]]:
            with patch.object(publisher, 'api', side_effect=[ref(B, 'tag')] + objects):
                with self.assertRaises(ValueError):
                    publisher.require_release_tag(REPO, TAG, A)
        hashes = [f'{n:040x}' for n in range(1, 10)]
        records = [ref(hashes[0], 'tag')] + [
            {'sha': sha, 'object': {'sha': hashes[i + 1], 'type': 'tag'}}
            for i, sha in enumerate(hashes[:-1])]
        with patch.object(publisher, 'api', side_effect=records) as api:
            with self.assertRaisesRegex(ValueError, 'depth'):
                publisher.require_release_tag(REPO, TAG, A)
            self.assertEqual(api.call_count, 9)

    def test_eight_annotated_tags_are_allowed(self):
        hashes = [f'{n:040x}' for n in range(1, 9)]
        records = [ref(hashes[0], 'tag')] + [
            {'sha': sha, 'object': {'sha': hashes[i + 1] if i < 7 else A,
                                    'type': 'tag' if i < 7 else 'commit'}}
            for i, sha in enumerate(hashes)] + [ref(hashes[0], 'tag')]
        with patch.object(publisher, 'api', side_effect=records):
            publisher.require_release_tag(REPO, TAG, A)

    def test_invalid_requested_tag_or_target_never_reaches_api(self):
        for tag, target in [('v2.4.2/extra', A), ('v2.4.2?x', A), (TAG, 'main')]:
            with patch.object(publisher, 'api') as api, self.assertRaises(ValueError):
                publisher.require_release_tag(REPO, tag, target)
            api.assert_not_called()

    def test_tag_movement_while_peeling_fails(self):
        with patch.object(publisher, 'api', side_effect=[ref(), ref(B)]):
            with self.assertRaisesRegex(ValueError, 'changed'):
                publisher.require_release_tag(REPO, TAG, A)

    def test_stale_tag_blocks_create_and_update_before_mutation(self):
        draft = {'id': 23, 'draft': True}
        for action in [lambda: publisher.create_draft(REPO, TAG, A, 'notes'),
                       lambda: publisher.update_metadata(REPO, draft, TAG, A, 'notes'),
                       lambda: publisher.update_metadata(REPO, draft, TAG, A, 'notes', True)]:
            with patch.object(publisher, 'api', return_value=ref(B)), patch.object(publisher, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'differs'):
                    action()
                run.assert_not_called()

    def test_creation_rechecks_new_tag_and_never_retries_mutation(self):
        created = {'id': 23, 'tag_name': TAG, 'target_commitish': A, 'draft': True, 'assets': []}
        for after in [[], ref(), ref(B)]:
            records = [[]] + ([after, after] if after == ref() else [after])
            with patch.object(publisher, 'api', side_effect=records), \
                    patch.object(publisher, 'run', return_value=json.dumps(created)) as run:
                if after == ref(B):
                    with self.assertRaisesRegex(ValueError, 'differs'):
                        publisher.create_draft(REPO, TAG, A, 'notes')
                else:
                    publisher.create_draft(REPO, TAG, A, 'notes')
                run.assert_called_once()

    def test_publication_requires_matching_tag_after_single_mutation(self):
        draft = {'id': 23, 'tag_name': TAG, 'draft': True}
        published = dict(draft, draft=False)
        for before in [[], ref()]:
            for after in [[], ref(), ref(B)]:
                records = ([before, before] if before else [before]) + ([after, after] if after == ref() else [after])
                with patch.object(publisher, 'api', side_effect=records), \
                        patch.object(publisher, 'run', return_value=json.dumps(published)) as run:
                    if after != ref():
                        with self.assertRaises(ValueError):
                            publisher.update_metadata(REPO, draft, TAG, A, 'notes', True)
                    else:
                        publisher.update_metadata(REPO, draft, TAG, A, 'notes', True)
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[3], 'PATCH')


if __name__ == '__main__':
    unittest.main()
