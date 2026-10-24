"""Synthetic provenance falsification tests, never host/performance evidence."""
import base64
import copy
import hashlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import traceback
import urllib.error
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('campaign_subject', ROOT / 'tools/host_inference_campaign.py')
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)
HEAD, REG, MAIN = '1' * 40, '2' * 40, '3' * 40


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return output.getvalue()


def producer():
    return dict(runId=123, runAttempt=1, headSha=HEAD, event='push',
                headBranch='main', workflowPath='.github/workflows/verify-v2.yml')


def valid_host():
    return dict(platform='Linux-unit-fixture-only', machine='x86_64', cpuCount=4,
                cpuAffinity=[0, 1, 2, 3], cpuQuota='400000 100000', memoryLimit='max',
                cpuModel='Synthetic test CPU, not hardware evidence')


def valid_admission():
    """Small synthetic schema fixture shared by candidate sealing tests."""
    return dict(schema=C.ADMISSION_SCHEMA, campaignId=C.CAMPAIGN_ID, policySha256='a' * 64,
                declarationSha256='b' * 64,
                registration=dict(commit=REG, path='tools/host-inference-campaigns/' + C.CAMPAIGN_ID + '.json',
                                  blobSha='4' * 40, sha256='c' * 64),
                request=dict(commit=HEAD, path='tools/host-inference-campaigns/' + C.CAMPAIGN_ID + '.request.json',
                             blobSha='9' * 40, sha256='9' * 64),
                producer=producer(), declarationArtifact=dict(id=456, sha256='d' * 64),
                proofArtifact=dict(id=789, sha256='e' * 64), proofReceiptSha256='f' * 64,
                measurementFinishedAt='2026-10-23T18:40:00+00:00', admissionCheckedAt='2026-10-23T18:50:00+00:00',
                candidate=dict(sourceCommit='5' * 40, sourceTreeSha='6' * 40, evidenceSession='7' * 64),
                recompiledClassHashes={'com/fixture/Unit.class': '8' * 64},
                knownLineage=[dict(runId=123, runAttempt=1, declarationArtifactId=456, proofArtifactId=789)])


class FakeGitHub:
    def __init__(self, root):
        self.root = root
        self.policy = C.load_policy(root)
        self.calls = []
        self.overrides = {}
        self.status = 'in_progress'
        self.conclusion = None
        self.latest_attempt = 1
        self.history_count = 1
        self.request_history_count = 1
        self.missing_request = False
        self.protected = True
        self.missing_registration = False
        self.missing_artifacts = set()
        self.source_corruption = set()
        self.record = dict(createdAt='2026-10-23T18:05:00+00:00',
                           sourceBindings={p: C.sha_bytes(C.source_bytes(root, p)) for p in self.policy['sourcePaths']},
                           compiledClassHashes={'com/fixture/Unit.class': '8' * 64},
                           models={'manifestSha256': 'a' * 64}, runtime={'version': '1.25.1'},
                           runtimeBindings={'schema': 'unit-only'}, audio={'sha256': 'b' * 64},
                           geometry=self.policy['geometry'], criteria=self.policy['criteria'], hostControls={'unitFixture': True}, host=valid_host())
        self.declaration = C.create_declaration(root, self.record, producer())
        self.declaration_zip = archive({C.DECLARATION_MEMBER: C.canonical_bytes(self.declaration)})
        self.registration = dict(schema=C.REGISTRATION_SCHEMA, campaignId=C.CAMPAIGN_ID,
                                 policySha256=self.declaration['policySha256'],
                                 declarationSha256=C.sha_bytes(C.canonical_bytes(self.declaration)), producer=producer(),
                                 declarationArtifactId=456, declarationArtifactSha256=C.sha_bytes(self.declaration_zip),
                                 executionClosure=self.declaration['executionClosure'])
        self.request = dict(schema='lightforge.host-inference-request.v1', campaignId=C.CAMPAIGN_ID, policySha256=self.declaration['policySha256'])
        self.receipt = dict(campaignDeclaration=self.declaration, host=copy.deepcopy(self.declaration['host']),
                            sourceBindings=self.declaration['sourceBindings'],
                            compiledClassHashes=self.declaration['compiledClassHashes'],
                            finishedAt='2026-10-23T18:40:00+00:00', measurementStartedAt='2026-10-23T18:30:00+00:00', passed=True)
        with mock.patch.object(C, 'now', return_value='2026-10-23T18:25:00+00:00'):
            self.receipt['registrationCheck'] = C.check_online_admission(root, self.declaration, self)
        self.proof_zip = archive({C.DECLARATION_MEMBER: C.canonical_bytes(self.declaration), C.RECEIPT_MEMBER: C.canonical_bytes(self.receipt)})

    def metadata(self, ident):
        kind, data = ('declaration', self.declaration_zip) if ident == 456 else ('proof', self.proof_zip)
        return dict(id=ident, name=C.artifact_name(kind, self.policy, producer()), expired=False,
                    size_in_bytes=len(data), digest='sha256:' + C.sha_bytes(data),
                    created_at='2026-10-23T18:10:00Z' if ident == 456 else '2026-10-23T18:41:00Z',
                    updated_at='2026-10-23T18:41:00Z', expires_at='2099-01-01T00:00:00Z',
                    workflow_run=dict(id=123, head_sha=HEAD, head_branch='main', repository_id=42, head_repository_id=42))

    def get(self, route):
        self.calls.append(route)
        if route in self.overrides:
            value = self.overrides[route]
            return value() if callable(value) else copy.deepcopy(value)
        if route == '/branches/main':
            return dict(name='main', protected=self.protected, commit=dict(sha=MAIN))
        if route.startswith('/contents/'):
            path = route[len('/contents/'):].split('?ref=')[0]
            if path.endswith('.request.json'):
                if self.missing_request:
                    raise C.GitHubUnavailable(404)
                raw = C.canonical_bytes(self.request)
            elif path.startswith('tools/host-inference-campaigns/'):
                if self.missing_registration:
                    raise C.GitHubUnavailable(404)
                raw = C.canonical_bytes(self.registration)
            else:
                raw = C.source_bytes(self.root, path)
                if path in self.source_corruption:
                    raw += b'wrong committed bytes'
            return dict(type='file', path=path, encoding='base64', size=len(raw),
                        content=base64.b64encode(raw).decode(),
                        sha=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
        if route.startswith('/commits?'):
            if '.request.json' in route:
                return [dict(sha=HEAD)] * self.request_history_count
            return [dict(sha=REG)] * self.history_count
        if route == '/commits/' + REG:
            return dict(sha=REG, commit=dict(committer=dict(date='2026-10-23T18:20:00Z')))
        if route.startswith('/compare/'):
            base = route.split('/compare/')[1].split('...')[0]
            return dict(status='ahead', merge_base_commit=dict(sha=base))
        if route == '/actions/workflows/verify-v2.yml':
            return dict(id=99, path='.github/workflows/verify-v2.yml', state='active')
        if route.startswith('/actions/runs/123/artifacts?'):
            return dict(total_count=1, artifacts=[self.metadata(789)])
        if route == '/actions/runs/123/attempts/1/jobs?per_page=100':
            return dict(total_count=1, jobs=[dict(name='host-campaign', run_id=123, head_sha=HEAD,
                status=self.status, conclusion=self.conclusion, started_at='2026-10-23T18:00:00Z',
                completed_at='2026-10-23T18:45:00Z' if self.status == 'completed' else None)])
        if route in ('/actions/runs/123', '/actions/runs/123/attempts/1'):
            return dict(id=123, head_sha=HEAD, head_branch='main', event='push',
                        path='.github/workflows/verify-v2.yml', workflow_id=99,
                        repository=dict(full_name=C.REPOSITORY, id=42), head_repository=dict(full_name=C.REPOSITORY, id=42),
                        run_attempt=self.latest_attempt if route.endswith('/123') else 1,
                        status=self.status, conclusion=self.conclusion, run_started_at='2026-10-23T18:00:00Z')
        if route.startswith('/actions/artifacts/'):
            ident = int(route.rsplit('/', 1)[1])
            if ident in self.missing_artifacts:
                raise C.GitHubUnavailable(404)
            return self.metadata(ident)
        raise AssertionError('Unexpected authoritative route: ' + route)

    def download(self, artifact_id):
        self.calls.append(('download', artifact_id))
        if artifact_id in self.missing_artifacts:
            raise C.GitHubUnavailable(404)
        return self.declaration_zip if artifact_id == 456 else self.proof_zip


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        policy_raw = (ROOT / C.POLICY_PATH).read_bytes()
        policy = C.strict_loads(policy_raw)
        for name in policy['executionClosurePaths']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC UNIT FIXTURE: ' + name.encode())
        (self.root / C.POLICY_PATH).write_bytes(policy_raw)
        (self.root / 'version.json').write_bytes(b'{"name":"2.4.2","code":20402}\n')
        self.api = FakeGitHub(self.root)

    def check(self, purpose='producer', admission=None):
        return C.check_online_admission(self.root, self.api.declaration, self.api, purpose,
                                        self.api.receipt if purpose == 'replay' else None, admission, C.sha_bytes(C.canonical_bytes(self.api.receipt)))

    def completed(self):
        self.api.status, self.api.conclusion = 'completed', 'success'

    def test_live_prospective_gate_fetches_known_ids_and_committed_closure(self):
        result = self.check()
        self.assertTrue(result['measurementAuthorized'])
        self.assertFalse(result['trustedReplayAuthorized'])
        self.assertIn('/actions/artifacts/456', self.api.calls)
        self.assertIn(('download', 456), self.api.calls)
        for path in self.api.policy['executionClosurePaths']:
            self.assertIn('/contents/' + path + '?ref=' + HEAD, self.api.calls)

    def test_decoder_trust_helper_is_prospectively_frozen_without_becoming_neural_source(self):
        path = 'tools/prepare_fixture_decoder.py'
        self.assertIn(path, self.api.policy['executionClosurePaths'])
        self.assertNotIn(path, self.api.policy['sourcePaths'])
        self.assertEqual(self.api.policy['campaignId'], 'lightforge-2.4.2-neural-four-worker-host-001')
        self.assertIn(path, self.api.declaration['executionClosure'])
        (self.root / path).write_bytes(b'SYNTHETIC CHANGED DECODER TRUST')
        with self.assertRaisesRegex(C.Hold, 'Source/closure drift'):
            C.verify_source_bindings(self.root, self.api.declaration)

    def test_declaration_host_is_prospective_and_receipt_must_match_exactly(self):
        self.assertEqual(self.api.declaration['host'], valid_host())
        self.completed()
        self.api.receipt['host']['cpuModel'] = 'Different synthetic CPU'
        with self.assertRaisesRegex(C.Hold, 'host drifted'):
            self.check('replay')
        self.api.receipt['host'] = valid_host()
        changed = copy.deepcopy(self.api.declaration)
        changed['host']['cpuModel'] = 'Different synthetic CPU'
        with self.assertRaisesRegex(C.Hold, 'Registration/declaration mismatch'):
            C.check_online_admission(self.root, changed, self.api, 'replay', self.api.receipt)

    def test_host_metadata_rejects_missing_malformed_and_private_fields(self):
        mutations = [lambda h: h.pop('cpuModel'), lambda h: h.update(platform=None),
                     lambda h: h.update(machine=''), lambda h: h.update(cpuCount=0),
                     lambda h: h.update(cpuCount=True), lambda h: h.update(cpuAffinity=None),
                     lambda h: h.update(cpuAffinity=[]), lambda h: h.update(cpuAffinity=[1, 0]),
                     lambda h: h.update(cpuAffinity=[0, 0]), lambda h: h.update(cpuAffinity=[True]),
                     lambda h: h.update(cpuAffinity=[-1]), lambda h: h.update(cpuAffinity=[1048576]),
                     lambda h: h.update(cpuModel='x' * 513), lambda h: h.update(cpuQuota='max\n100000'),
                     lambda h: h.update(memoryLimit=123)]
        for mutate in mutations:
            declaration = copy.deepcopy(self.api.declaration)
            mutate(declaration['host'])
            with self.assertRaises(C.Hold):
                C.validate_declaration(declaration, self.api.policy)
        secret = 'PRIVATE_HOST_ENV_SENTINEL_123'
        for field in ('environment', 'env', 'GITHUB_TOKEN', 'jvmProperties', 'commandLine', 'hostname'):
            declaration = copy.deepcopy(self.api.declaration)
            declaration['host'][field] = secret
            self.assert_sanitized_error(lambda: C.validate_declaration(declaration, self.api.policy), secret)

    def test_optional_informational_host_fields_can_be_null_without_replacing_controls(self):
        host = valid_host()
        for field in ('cpuQuota', 'memoryLimit', 'cpuModel'):
            host[field] = None
        self.assertEqual(C.validate_host_metadata(host), host)
        declaration = copy.deepcopy(self.api.declaration)
        declaration['host'] = host
        declaration['hostControls'] = None
        with self.assertRaisesRegex(C.Hold, 'hostControls'):
            C.validate_declaration(declaration, self.api.policy)

    def test_offline_declaration_never_claims_authority(self):
        self.assertTrue(C.verify_source_bindings(self.root, self.api.declaration))
        self.assertNotIn('measurementAuthorized', self.api.declaration)
        self.assertNotIn('trustedReplayAuthorized', self.api.declaration)

    def test_only_missing_direct_registration_can_wait(self):
        self.api.missing_registration = True
        with self.assertRaises(C.AwaitingRegistration):
            self.check()
        self.api.missing_registration = False
        self.api.missing_artifacts.add(456)
        with self.assertRaises(C.Hold) as caught:
            self.check()
        self.assertNotIsInstance(caught.exception, C.AwaitingRegistration)

    def test_protected_main_and_registration_single_creation_required(self):
        self.api.protected = False
        with self.assertRaisesRegex(C.Hold, 'protection'):
            self.check()
        self.api.protected = True
        for count in (0, 2):
            self.api.history_count = count
            with self.assertRaisesRegex(C.Hold, 'history'):
                self.check()

    def test_local_registration_cannot_supply_authority(self):
        self.api.missing_registration = True
        path = self.root / 'tools/host-inference-campaigns' / (C.CAMPAIGN_ID + '.json')
        path.parent.mkdir()
        path.write_bytes(C.canonical_bytes(self.api.registration))
        with self.assertRaises(C.AwaitingRegistration):
            self.check()

    def test_source_hashes_must_match_committed_blobs_not_self_assertions(self):
        self.api.source_corruption.add('tools/benchmark_deux_parallel.py')
        with self.assertRaisesRegex(C.Hold, 'committed source'):
            self.check()

    def test_local_source_or_policy_drift_holds_while_waiting(self):
        path = self.root / 'tools/benchmark_deux_parallel.py'
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(C.Hold, 'drift'):
            self.check()

    def test_registration_cannot_choose_another_run_attempt_or_declaration(self):
        changes = [lambda r: r['producer'].update(runId=124), lambda r: r['producer'].update(runAttempt=2),
                   lambda r: r.update(declarationSha256='0' * 64), lambda r: r.update(policySha256='0' * 64),
                   lambda r: r['executionClosure'].update({'version.json': '0' * 64})]
        for change in changes:
            original = copy.deepcopy(self.api.registration)
            change(self.api.registration)
            with self.assertRaises(C.Hold):
                self.check()
            self.api.registration = original

    def test_failed_terminal_attempt_never_retries_and_unknown_or_cancelled_hold(self):
        for conclusion in ('failure', 'timed_out', 'action_required', 'startup_failure'):
            self.api.status, self.api.conclusion = 'completed', conclusion
            with self.assertRaises(C.TerminalFailure):
                self.check('replay')
        for status, conclusion in [('completed', 'cancelled'), ('in_progress', None), ('completed', None)]:
            self.api.status, self.api.conclusion = status, conclusion
            with self.assertRaises(C.Hold) as caught:
                self.check('replay')
            self.assertNotIsInstance(caught.exception, C.TerminalFailure)

    def test_rerun_cannot_measure_but_original_success_can_replay(self):
        self.api.latest_attempt = 2
        with self.assertRaisesRegex(C.Hold, 'original attempt'):
            self.check()
        self.completed()
        self.assertTrue(self.check('replay')['trustedReplayAuthorized'])

    def test_wrong_run_repository_workflow_event_head_or_attempt_hold(self):
        route = '/actions/runs/123/attempts/1'
        baseline = self.api.get(route)
        for field, bad in [('id', 124), ('head_sha', '9' * 40), ('head_branch', 'topic'), ('event', 'workflow_dispatch'),
                           ('path', '.github/workflows/evil.yml'), ('workflow_id', 100), ('run_attempt', 2),
                           ('head_repository', {'full_name': 'attacker/LightForge', 'id': 66})]:
            value = copy.deepcopy(baseline)
            value[field] = bad
            self.api.overrides[route] = value
            with self.assertRaises(C.Hold):
                self.check()
        del self.api.overrides[route]

    def test_missing_expired_or_wrong_digest_artifacts_hold(self):
        route = '/actions/artifacts/456'
        baseline = self.api.metadata(456)
        changes = [('expired', True), ('digest', None), ('digest', 'sha256:' + '0' * 64),
                   ('name', 'some-other-run'), ('id', 999), ('created_at', '2026-10-23T17:00:00Z')]
        for field, bad in changes:
            value = copy.deepcopy(baseline)
            value[field] = bad
            self.api.overrides[route] = value
            with self.assertRaises(C.Hold):
                self.check()

    def test_proof_lookup_pins_exact_named_id_then_direct_fetch(self):
        self.completed()
        decl, receipt, directory, check = C.fetch_proof(self.root, self.api, output_dir=Path(self.tmp.name) / 'proof')
        self.assertEqual(decl, self.api.declaration)
        self.assertEqual(receipt, self.api.receipt)
        self.assertTrue((directory / 'receipt.json').is_file())
        self.assertEqual(check['proofArtifact']['id'], 789)
        self.assertIn('/actions/artifacts/789', self.api.calls)
        self.assertIn(('download', 789), self.api.calls)
        self.assertNotIn('passed', check)

    def artifact_page(self, page, total, entries):
        route = '/actions/runs/123/artifacts?per_page=100&page=' + str(page)
        self.api.overrides[route] = dict(total_count=total, artifacts=entries)

    def inventory_entries(self, count):
        return [dict(id=1000 + index, name='unrelated-' + str(index)) for index in range(count)]

    def test_complete_paginated_inventory_reconciles_exactly(self):
        entries = [self.api.metadata(789), *self.inventory_entries(100)]
        self.artifact_page(1, 101, entries[:100])
        self.artifact_page(2, 101, entries[100:])
        self.assertEqual(C.find_proof_artifact(self.api, self.api.policy, producer()), 789)
        self.assertIn('/actions/runs/123/artifacts?per_page=100&page=2', self.api.calls)

    def test_matching_proof_on_truncated_first_page_is_not_enough(self):
        # Original repro: total_count=101, one match, then an empty second page.
        self.artifact_page(1, 101, [self.api.metadata(789)])
        self.artifact_page(2, 101, [])
        with self.assertRaisesRegex(C.Hold, 'Truncated'):
            C.find_proof_artifact(self.api, self.api.policy, producer())

    def test_matching_proof_on_full_first_page_cannot_hide_empty_second_page(self):
        self.artifact_page(1, 101, [self.api.metadata(789), *self.inventory_entries(99)])
        self.artifact_page(2, 101, [])
        with self.assertRaisesRegex(C.Hold, 'Truncated'):
            C.find_proof_artifact(self.api, self.api.policy, producer())

    def test_pagination_total_must_remain_stable(self):
        self.artifact_page(1, 101, [self.api.metadata(789), *self.inventory_entries(99)])
        for total in (100, 102):
            self.artifact_page(2, total, [dict(id=2000, name='other')])
            with self.assertRaisesRegex(C.Hold, 'total changed'):
                C.find_proof_artifact(self.api, self.api.policy, producer())

    def test_pagination_rejects_repeated_ids_within_or_across_pages(self):
        entries = [self.api.metadata(789), *self.inventory_entries(99)]
        self.artifact_page(1, 101, entries)
        self.artifact_page(2, 101, [entries[-1]])
        with self.assertRaisesRegex(C.Hold, 'Duplicate'):
            C.find_proof_artifact(self.api, self.api.policy, producer())
        self.artifact_page(1, 2, [self.api.metadata(789), self.api.metadata(789)])
        with self.assertRaisesRegex(C.Hold, 'Duplicate'):
            C.find_proof_artifact(self.api, self.api.policy, producer())

    def test_pagination_rejects_repeated_full_page_and_overfull_final_page(self):
        entries = [self.api.metadata(789), *self.inventory_entries(99)]
        self.artifact_page(1, 200, entries)
        self.artifact_page(2, 200, entries)
        with self.assertRaisesRegex(C.Hold, 'Duplicate'):
            C.find_proof_artifact(self.api, self.api.policy, producer())
        self.artifact_page(1, 101, entries)
        self.artifact_page(2, 101, [dict(id=2000, name='other'), dict(id=2001, name='another')])
        with self.assertRaisesRegex(C.Hold, 'overfull'):
            C.find_proof_artifact(self.api, self.api.policy, producer())

    def test_pagination_rejects_malformed_or_boolean_inventory_ids(self):
        for entry in (None, {'name': 'missing-id'}, {'id': True, 'name': 'boolean-id'},
                      {'id': 0, 'name': 'zero-id'}, {'id': 2, 'name': None}):
            self.artifact_page(1, 2, [self.api.metadata(789), entry])
            with self.assertRaises(C.Hold):
                C.find_proof_artifact(self.api, self.api.policy, producer())

    def test_no_proof_artifact_never_authorizes_new_measurements(self):
        self.completed()
        route = '/actions/runs/123/artifacts?per_page=100&page=1'
        self.api.overrides[route] = dict(total_count=0, artifacts=[])
        with self.assertRaisesRegex(C.Hold, 'absence never authorizes'):
            C.fetch_proof(self.root, self.api)

    def test_sealed_admission_rechecks_known_artifacts_and_fresh_classes(self):
        self.completed()
        _, receipt, _, check = C.fetch_proof(self.root, self.api, output_dir=Path(self.tmp.name) / 'proof')
        admission = C.seal_admission(check, receipt, candidate_source_commit='5' * 40, candidate_source_tree_sha='6' * 40,
                                     evidence_session='7' * 64, recompiled_class_hashes=receipt['compiledClassHashes'])
        self.check('replay', admission)
        admission['recompiledClassHashes']['com/fixture/Unit.class'] = '9' * 64
        with self.assertRaisesRegex(C.Hold, 'classes'):
            self.check('replay', admission)

    def test_admission_candidate_commit_tree_session_and_lineage_strict(self):
        value = valid_admission()
        C.validate_admission(value, candidate_source_commit='5' * 40, candidate_source_tree_sha='6' * 40, evidence_session='7' * 64)
        for field in ('sourceCommit', 'sourceTreeSha', 'evidenceSession'):
            changed = copy.deepcopy(value)
            changed['candidate'][field] = '0' * len(changed['candidate'][field])
            with self.assertRaises(C.Hold):
                C.validate_admission(changed, candidate_source_commit='5' * 40, candidate_source_tree_sha='6' * 40, evidence_session='7' * 64)
        for change in [lambda v: v.update(knownLineage=[]), lambda v: v['knownLineage'].append(v['knownLineage'][0]),
                       lambda v: v.update(recompiledClassHashes={}), lambda v: v.update(extra=True),
                       lambda v: v['producer'].update(runAttempt=True)]:
            changed = copy.deepcopy(value)
            change(changed)
            with self.assertRaises(C.Hold):
                C.validate_admission(changed)

    def test_duplicate_nonfinite_deep_unbounded_json_rejected(self):
        for raw in [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1e400}', b'{"x":18446744073709551616}',
                    b'[' * 40 + b'0' + b']' * 40, b'{}\x00', b'\xff']:
            with self.assertRaises(C.Hold):
                C.strict_loads(raw)
        with mock.patch.object(C, 'MAX_JSON', 10):
            with self.assertRaises(C.Hold):
                C.strict_loads(b' ' * 11)

    def test_zip_traversal_duplicate_symlink_special_and_expansion_rejected(self):
        for name in ('../escape', '/escape', 'x/../../escape', 'x\\escape', 'a//b', 'a/./b', 'C:escape'):
            with self.assertRaises(C.Hold):
                C.safe_zip(archive({name: b'bad'}))
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as z:
                info = zipfile.ZipInfo('link')
                info.external_attr = mode << 16
                z.writestr(info, b'../outside')
            with self.assertRaises(C.Hold):
                C.safe_zip(buffer.getvalue())
        with mock.patch.object(C, 'MAX_UNPACKED', 2):
            with self.assertRaises(C.Hold):
                C.safe_zip(archive({'x': b'abc'}))
        with self.assertRaises(C.Hold):
            C.safe_zip(archive({'a': b'x', 'a/b': b'y'}))

    def test_source_symlinks_rejected(self):
        target = self.root / 'version.json'
        target.unlink()
        target.symlink_to(ROOT / 'version.json')
        with self.assertRaises(C.Hold):
            C.load_policy(self.root)

    def test_fresh_admission_requires_numerical_replay_and_rebuild_before_seal(self):
        self.completed()
        _, receipt, directory, check = C.fetch_proof(self.root, self.api, output_dir=Path(self.tmp.name) / 'proof')
        with mock.patch.object(C, 'verify_numerical_proof', side_effect=C.Hold('synthetic numerical rejection')):
            with self.assertRaisesRegex(C.Hold, 'numerical rejection'):
                C.admit_proof(self.root, directory, check, receipt, '7' * 64, self.api)
        revisions = [SimpleNamespace(returncode=0, stdout='5' * 40), SimpleNamespace(returncode=0, stdout='6' * 40)]
        with mock.patch.object(C, 'verify_numerical_proof', return_value=25.0) as verify, \
             mock.patch.object(C.subprocess, 'run', side_effect=revisions):
            admission = C.admit_proof(self.root, directory, check, receipt, '7' * 64, self.api)
        verify.assert_called_once_with(self.root, directory, rebuild_classes=True)
        self.assertEqual(admission['recompiledClassHashes'], receipt['compiledClassHashes'])
        self.assertEqual(admission['measurementFinishedAt'], receipt['finishedAt'])
        self.assertEqual(admission['candidate']['evidenceSession'], '7' * 64)

    def test_deleted_known_proof_during_candidate_compile_blocks_admission(self):
        self.completed()
        _, receipt, directory, check = C.fetch_proof(self.root, self.api, output_dir=Path(self.tmp.name) / 'proof')
        revisions = [SimpleNamespace(returncode=0, stdout='5' * 40), SimpleNamespace(returncode=0, stdout='6' * 40)]
        def compile_then_delete(*args, **kwargs):
            self.api.missing_artifacts.add(789)
            return 25.0
        with mock.patch.object(C, 'verify_numerical_proof', side_effect=compile_then_delete), \
             mock.patch.object(C.subprocess, 'run', side_effect=revisions):
            with self.assertRaises(C.Hold):
                C.admit_proof(self.root, directory, check, receipt, '7' * 64, self.api)

    def test_receipt_digest_binds_exact_raw_bytes_not_reformatted_json(self):
        self.completed()
        raw = (json.dumps(self.api.receipt, indent=2) + '\n').encode()
        self.api.proof_zip = archive({C.DECLARATION_MEMBER: C.canonical_bytes(self.api.declaration), C.RECEIPT_MEMBER: raw})
        _, receipt, _, check = C.fetch_proof(self.root, self.api, output_dir=Path(self.tmp.name) / 'proof')
        self.assertEqual(check['proofReceiptSha256'], C.sha_bytes(raw))
        self.assertNotEqual(check['proofReceiptSha256'], C.sha_bytes(C.canonical_bytes(receipt)))

    def test_proof_upload_after_original_job_end_or_duplicate_name_holds(self):
        self.completed()
        metadata = self.api.metadata(789)
        metadata['updated_at'] = '2026-10-23T19:00:00Z'
        self.api.overrides['/actions/artifacts/789'] = metadata
        with self.assertRaisesRegex(C.Hold, 'after original'):
            C.fetch_proof(self.root, self.api)
        del self.api.overrides['/actions/artifacts/789']
        self.api.overrides['/actions/runs/123/artifacts?per_page=100&page=1'] = dict(
            total_count=2, artifacts=[self.api.metadata(789), self.api.metadata(790)])
        with self.assertRaisesRegex(C.Hold, 'Exactly one'):
            C.fetch_proof(self.root, self.api)

    def test_immutable_request_allocates_only_its_exact_main_push(self):
        env = dict(GITHUB_EVENT_NAME='push', GITHUB_REF_NAME='main', GITHUB_SHA=HEAD,
                   GITHUB_REPOSITORY=C.REPOSITORY, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1')
        self.assertEqual(C.route_campaign(self.root, self.api, env)['mode'], 'producer')
        env['GITHUB_RUN_ATTEMPT'] = '2'
        self.assertEqual(C.route_campaign(self.root, self.api, env)['mode'], 'producer-replay')
        env['GITHUB_SHA'] = REG
        self.assertEqual(C.route_campaign(self.root, self.api, env)['mode'], 'consumer')
        env['GITHUB_SHA'] = HEAD
        env['GITHUB_EVENT_NAME'] = 'workflow_dispatch'
        self.assertEqual(C.route_campaign(self.root, self.api, env)['mode'], 'consumer')
        env['GITHUB_EVENT_NAME'] = 'push'
        self.api.missing_request = True
        self.assertEqual(C.route_campaign(self.root, self.api, env)['mode'], 'consumer')
        with self.assertRaises(C.Hold):
            self.check()

    def test_request_replacement_and_policy_drift_hold(self):
        self.api.request_history_count = 2
        with self.assertRaisesRegex(C.Hold, 'request.*history'):
            self.check()
        self.api.request_history_count = 1
        self.api.request['policySha256'] = '0' * 64
        with self.assertRaisesRegex(C.Hold, 'allocated'):
            self.check()

    def test_missing_or_reordered_live_gate_receipt_holds(self):
        self.completed()
        for change in (lambda r: r.pop('registrationCheck'),
                       lambda r: r['registrationCheck'].update(measurementAuthorized=False),
                       lambda r: r.update(measurementStartedAt='2026-10-23T18:00:00Z')):
            original = copy.deepcopy(self.api.receipt)
            change(self.api.receipt)
            with self.assertRaises(C.Hold):
                self.check('replay')
            self.api.receipt = original

    def assert_sanitized_error(self, action, *secrets):
        try:
            action()
        except C.Hold as error:
            rendered = ''.join(traceback.format_exception(error))
            for secret in secrets:
                self.assertNotIn(secret, str(error))
                self.assertNotIn(secret, rendered)
        else:
            self.fail('Unsafe or failing operation was not rejected')

    def test_authenticated_get_uses_token_only_at_pinned_github_api(self):
        token, signature = 'ghs_PRIVATE_TOKEN_123', 'PRIVATE_SIGNED_QUERY_456'
        api = C.GitHub(token)
        redirect = 'https://productionresultssa1.blob.core.windows.net/artifact?sig=' + signature
        requests = []
        def opened(request, **kwargs):
            requests.append(request)
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 302, 'Found', {'Location': redirect}, None)
            response = io.BytesIO(b'archive')
            response.status = 200
            return response
        api.opener.open = opened
        result = api.download(456)
        self.assertEqual(result, b'archive')
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].full_url, 'https://api.github.com/repos/' + C.REPOSITORY + '/actions/artifacts/456/zip')
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer ' + token)
        self.assertIsNone(requests[1].get_header('Authorization'))
        self.assertNotIn(token, repr(result))
        self.assertNotIn(signature, repr(result))

    def test_malicious_redirects_cannot_leak_token_signed_url_or_parser_details(self):
        token, secret = 'ghs_PRIVATE_TOKEN_123', 'PRIVATE_QUERY_OR_PORT_456'
        destinations = [
            'https://attacker.test/?sig=' + secret,
            'https://api.github.com/repos/' + C.REPOSITORY + '/contents/private?sig=' + secret,
            'https://productionresultssa1.blob.core.windows.net:' + secret + '/artifact',
            'https://user:' + secret + '@productionresultssa1.blob.core.windows.net/artifact',
            'https://productionresultssa1.blob.core.windows.net@attacker.test/?sig=' + secret,
            'http://productionresultssa1.blob.core.windows.net/artifact?sig=' + secret,
            'https://[invalid-' + secret + '/artifact',
            'https://productionresultssa1.blob.core.windows.net/artifact?sig=' + secret + '\nHEADER',
            'https://productionresultssa1.blob.core.windows.net/artifact?sig=' + secret + '\tHEADER',
            'https://productionresultssa1.blob.core.windows.net/artifact?sig=' + secret + '\x7fHEADER',
        ]
        for destination in destinations:
            api = C.GitHub(token)
            api.opener.open = mock.Mock(side_effect=urllib.error.HTTPError(
                'https://api.github.com/private?sig=' + secret, 302, secret,
                {'Location': destination}, None))
            self.assert_sanitized_error(lambda: api.download(456), token, secret, destination)
            api.opener.open.assert_called_once()

    def test_network_and_stream_exceptions_are_sanitized_without_chained_secrets(self):
        token, secret = 'ghs_PRIVATE_TOKEN_123', 'PRIVATE_ERROR_URL_456'
        for error in [OSError('transport ' + secret), ValueError('authorization ' + token),
                      http.client.InvalidURL('URL query ' + secret), http.client.BadStatusLine('status ' + secret),
                      urllib.error.HTTPError('https://api.github.com/private?sig=' + secret,
                                             403, secret, {}, io.BytesIO(token.encode()))]:
            api = C.GitHub(token)
            api.opener.open = mock.Mock(side_effect=error)
            self.assert_sanitized_error(lambda: api.download(456), token, secret)
        for error in (OSError('signed stream URL ' + secret + ' token ' + token),
                      http.client.IncompleteRead(secret.encode()), http.client.InvalidURL('stream ' + secret)):
            response = mock.MagicMock()
            response.status = 200
            response.__enter__.return_value = response
            response.read.side_effect = error
            api = C.GitHub(token)
            api.opener.open = mock.Mock(return_value=response)
            self.assert_sanitized_error(lambda: api.download(456), token, secret)

    def test_malformed_producer_environment_never_reflects_raw_values(self):
        secret = 'PRIVATE_ENV_VALUE_789'
        environment = dict(GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA=HEAD,
                           GITHUB_EVENT_NAME='push', GITHUB_REF_NAME='main', GITHUB_REPOSITORY=C.REPOSITORY,
                           GITHUB_TOKEN='ghs_' + secret, UNRELATED_PRIVATE_ENV=secret)
        for field in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA',
                      'GITHUB_EVENT_NAME', 'GITHUB_REF_NAME', 'GITHUB_REPOSITORY'):
            malformed = dict(environment, **{field: secret})
            with mock.patch.dict(C.os.environ, malformed, clear=True):
                self.assert_sanitized_error(C.producer_from_environment, secret)
        with mock.patch.dict(C.os.environ, environment, clear=True):
            result = C.producer_from_environment()
        self.assertEqual(result, producer())
        self.assertNotIn(secret, json.dumps(result))
        for field in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            malformed = dict(environment, **{field: secret})
            self.assert_sanitized_error(lambda: C.route_campaign(self.root, self.api, malformed), secret)

    def test_malformed_token_errors_never_echo_token(self):
        secret = 'PRIVATE_TOKEN_789'
        for token in (secret + '\nHEADER', secret + '\rHEADER', secret + '\x00', secret + ' suffix'):
            self.assert_sanitized_error(lambda: C.GitHub(token), secret)

    def test_token_never_forwarded_or_sent_to_arbitrary_host(self):
        api = C.GitHub('not-a-real-secret')
        for url, authenticated in [('https://attacker.test/x', True), ('https://api.github.com/evil', True),
                                   ('http://api.github.com/repos/' + C.REPOSITORY + '/x', True),
                                   ('https://attacker.blob.core.windows.net/x', False),
                                   ('https://api.github.com/repos/' + C.REPOSITORY + '/x', False)]:
            with self.assertRaises(C.Hold):
                api._request(url, authenticated, 10)
        fake = mock.MagicMock()
        fake.status = 200
        fake.read.side_effect = [b'ok', b'']
        fake.__enter__.return_value = fake
        api.opener.open = mock.Mock(return_value=fake)
        self.assertEqual(api._request('https://productionresultssa1.blob.core.windows.net/x?sig=opaque', False, 10), b'ok')
        request = api.opener.open.call_args.args[0]
        self.assertNotIn('Authorization', request.headers)


if __name__ == '__main__':
    unittest.main()
