import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import publish_github_release as publication


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.expected = {'app.apk': {'bytes': 50, 'sha256': 'a' * 64}, 'release-verification.json': {'bytes': 20, 'sha256': 'b' * 64}}
        self.release = {'id': 23, 'tag_name': 'v2.1.0', 'draft': True, 'assets': [
            {'name': name, 'size': info['bytes'], 'digest': 'sha256:' + info['sha256'], 'state': 'uploaded'}
            for name, info in self.expected.items()]}

    def test_draft_lookup_does_not_require_a_published_tag(self):
        with patch.object(publication, 'api', return_value=[self.release]) as api:
            self.assertEqual(publication.lookup_release('owner/repo', 'v2.1.0')['id'], 23)
            api.assert_called_once_with('repos/owner/repo/releases?per_page=100')
        with patch.object(publication, 'api', return_value=self.release) as api:
            publication.lookup_release('owner/repo', 'v2.1.0', 23)
            api.assert_called_once_with('repos/owner/repo/releases/23')

    def test_creation_uses_returned_id_without_listing_drafts(self):
        target = 'a' * 40
        created = dict(self.release, assets=[], target_commitish=target)
        notes = 'Signed update\n\nExact notes with `code` and $literal text.\n'
        with patch.object(publication, 'run', return_value=json.dumps(created)) as run, \
                patch.object(publication, 'lookup_release') as lookup, \
                patch.object(publication, 'api') as api:
            self.assertEqual(publication.create_draft('owner/repo', 'v2.1.0', target, notes), created)
            run.assert_called_once()
            self.assertEqual(run.call_args.args,
                             ('gh', 'api', '--method', 'POST', 'repos/owner/repo/releases', '--input', '-'))
            self.assertEqual(json.loads(run.call_args.kwargs['input']), {
                'tag_name': 'v2.1.0', 'target_commitish': target,
                'name': 'LightForge 2.1.0', 'body': notes, 'draft': True, 'prerelease': False})
            lookup.assert_not_called()
            api.assert_not_called()

    def test_creation_rejects_invalid_or_mismatched_identity(self):
        target = 'a' * 40
        created = dict(self.release, assets=[], target_commitish=target)
        responses = [None, [], {k: v for k, v in created.items() if k != 'id'}]
        for field, value in [('id', 0), ('id', -1), ('id', True), ('id', '23'),
                             ('tag_name', 'untagged-123abc'), ('target_commitish', 'b' * 40),
                             ('draft', False), ('draft', 'true'), ('assets', [{'name': 'unexpected.apk'}])]:
            responses.append(dict(created, **{field: value}))
        for response in responses:
            with self.subTest(response=response), \
                    patch.object(publication, 'run', return_value=json.dumps(response)) as run, \
                    patch.object(publication, 'lookup_release') as lookup:
                with self.assertRaises(ValueError):
                    publication.create_draft('owner/repo', 'v2.1.0', target, 'Notes')
                run.assert_called_once()
                lookup.assert_not_called()

    def test_creation_request_failure_does_not_repeat_mutation_or_lookup(self):
        failure = subprocess.CalledProcessError(1, ['gh', 'api'])
        with patch.object(publication, 'run', side_effect=failure) as run, \
                patch.object(publication, 'lookup_release') as lookup:
            with self.assertRaises(subprocess.CalledProcessError):
                publication.create_draft('owner/repo', 'v2.1.0', 'a' * 40, 'Notes')
            run.assert_called_once()
            lookup.assert_not_called()

    def test_resumption_skips_exact_assets_and_only_replaces_draft_metadata(self):
        self.assertEqual(publication.asset_plan(self.release, self.expected), [])
        self.release['assets'][1]['digest'] = 'sha256:' + 'c' * 64
        with self.assertRaises(ValueError):publication.asset_plan(self.release, self.expected)
        self.assertEqual(publication.asset_plan(self.release, self.expected, True), [('release-verification.json', True)])

    def test_metadata_and_publication_preserve_explicit_tag_identity(self):
        for publish in [False, True]:
            updated = dict(self.release, draft=not publish)
            with patch.object(publication, 'run', return_value=json.dumps(updated)) as run:
                publication.update_metadata('owner/repo', self.release, 'v2.1.0', 'a' * 40, 'Notes', publish)
                payload = json.loads(run.call_args.kwargs['input'])
                self.assertEqual(payload['tag_name'], 'v2.1.0')
                self.assertEqual(payload['target_commitish'], 'a' * 40)
                self.assertEqual(payload['draft'], not publish)
                self.assertEqual(payload.get('make_latest'), 'true' if publish else None)
        untagged = dict(self.release, tag_name='untagged-123abc')
        with patch.object(publication, 'run', return_value=json.dumps(self.release)):
            publication.update_metadata('owner/repo', untagged, 'v2.1.0', 'a' * 40, 'Notes')

    def test_metadata_rejects_published_releases_and_identity_changes(self):
        with self.assertRaises(ValueError):
            publication.update_metadata('owner/repo', dict(self.release, draft=False), 'v2.1.0', 'a' * 40, 'Notes')
        for field, value in [('id', 24), ('tag_name', 'untagged-123abc'), ('draft', False)]:
            with patch.object(publication, 'run', return_value=json.dumps(dict(self.release, **{field: value}))):
                with self.assertRaises(ValueError):
                    publication.update_metadata('owner/repo', self.release, 'v2.1.0', 'a' * 40, 'Notes')

    def test_never_replaces_an_apk_or_modifies_a_published_release(self):
        changed = copy.deepcopy(self.release)
        changed['assets'][0]['size'] += 1
        with self.assertRaises(ValueError):publication.asset_plan(changed, self.expected, True)
        self.release['draft'] = False
        with self.assertRaises(ValueError):publication.asset_plan(self.release, self.expected, True)

    def test_publication_requires_all_uploaded_digests_and_no_unreviewed_assets(self):
        publication.verify_uploaded(self.release, self.expected)
        for change in ['digest', 'missing', 'extra', 'state']:
            bad = copy.deepcopy(self.release)
            if change == 'digest':bad['assets'][0]['digest'] = None
            elif change == 'missing':bad['assets'].pop()
            elif change == 'extra':bad['assets'].append({'name': 'unreviewed.txt'})
            else:bad['assets'][0]['state'] = 'new'
            with self.assertRaises(ValueError):publication.verify_uploaded(bad, self.expected)

    def test_post_ci_delta_cannot_change_classes_or_resources_but_may_replace_signatures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, signed = root / 'candidate.apk', root / 'signed.apk'

            def write(path, dex, signature, extra=None):
                payload = {
                    'AndroidManifest.xml': b'<manifest/>',
                    'classes.dex': dex,
                    'lib/arm64-v8a/runtime.so': b'native',
                    'assets/web/app.js': b'web',
                    'resources.arsc': b'resources',
                    'META-INF/MANIFEST.MF': b'manifest',
                    'META-INF/CERT.SF': signature,
                    'META-INF/CERT.RSA': signature + b'-cert',
                }
                if extra is not None:
                    payload.update(extra)
                with zipfile.ZipFile(path, 'w') as archive:
                    for name, value in payload.items():
                        archive.writestr(name, value)

            write(candidate, b'candidate-code', b'ci')
            write(signed, b'candidate-code', b'production')
            publication.verify_candidate_payload_equivalence(candidate, signed)
            write(signed, b'changed-code', b'production')
            with self.assertRaisesRegex(ValueError, 'Post-CI APK delta changed'):
                publication.verify_candidate_payload_equivalence(candidate, signed)
            write(signed, b'candidate-code', b'production', {'res/raw/new.bin': b'changed'})
            with self.assertRaisesRegex(ValueError, 'Post-CI APK delta changed'):
                publication.verify_candidate_payload_equivalence(candidate, signed)
