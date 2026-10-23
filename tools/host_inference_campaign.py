#!/usr/bin/env python3
"""Prospective, one-producer host campaign control plane (never a timing gate).

Local/offline parsing establishes no GitHub authority. Online admission requires
an immutable declaration, the first and only registration of the campaign on the
currently protected main history, exact run-attempt metadata, and independently
retrieved source blobs. A separate numerical verifier must replay the raw proof.
No function here invokes a model, warms a JVM, changes controls, or writes to GitHub.
"""
import argparse
import base64
import datetime as dt
import hashlib
import http.client
import io
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

POLICY_PATH = 'tools/host_inference_policy.json'
POLICY_SCHEMA = 'lightforge.host-inference-policy.v1'
DECLARATION_SCHEMA = 'lightforge.host-inference-declaration.v1'
REGISTRATION_SCHEMA = 'lightforge.host-inference-registration.v1'
ADMISSION_SCHEMA = 'lightforge.host-inference-admission.v1'
CHECK_SCHEMA = 'lightforge.host-inference-online-check.v1'
DECLARATION_MEMBER = 'declaration.json'
RECEIPT_MEMBER = 'receipt.json'
MAX_JSON = 8 * 1024 * 1024
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024
MAX_MEMBERS = 2048
MAX_DEPTH = 32
MAX_NODES = 100000
REPOSITORY = 'CyberBASSLord-666/LightForge'
CAMPAIGN_ID = 'lightforge-2.4.2-neural-four-worker-host-001'
PROTOCOL = 'bounded-four-worker-three-cpu-v1'
EVENTS = {'push'}
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')


class Hold(ValueError):
    """Missing, invalid, or uncertain authority. No measurement is permitted."""


class AwaitingRegistration(Hold):
    """Only a positively observed registration HTTP 404 may wait for publication."""


class GitHubUnavailable(Hold):
    def __init__(self, status):
        self.status = status
        super().__init__("Authoritative GitHub request unavailable (HTTP " + str(status) + ")")


class TerminalFailure(Hold):
    """The one registered producer failed; no retry or replacement is permitted."""


def require(condition, message):
    if not condition:
        raise Hold(message) from None


def keys(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), 'Invalid fields: ' + label)


def integer(value, label):
    require(type(value) is int and 0 < value < 2**63, 'Invalid positive integer: ' + label)
    return value


def digest(value, label='SHA-256'):
    require(type(value) is str and SHA.fullmatch(value), 'Invalid ' + label)
    return value


def commit(value, label='commit'):
    require(type(value) is str and COMMIT.fullmatch(value), 'Invalid ' + label)
    return value


def safe_path(value):
    require(type(value) is str and 0 < len(value) <= 1024 and '\\' not in value
            and ':' not in value and all(32 <= ord(c) < 127 for c in value)
            and not value.startswith('/') and PurePosixPath(value).as_posix() == value
            and all(p not in ('', '.', '..') for p in value.split('/')), 'Unsafe artifact/source path')
    return value


def timestamp(value):
    require(type(value) is str and len(value) <= 40, 'Invalid timestamp')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise Hold('Invalid timestamp') from error
    require(parsed.utcoffset() == dt.timedelta(0), 'Timestamp must be UTC')
    return parsed


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _tree(value, depth=0, count=None):
    count = count if count is not None else [0]
    count[0] += 1
    require(depth <= MAX_DEPTH and count[0] <= MAX_NODES, 'JSON structure limit exceeded')
    if type(value) is dict:
        require(all(type(k) is str and len(k) <= 4096 for k in value), 'Invalid JSON object key')
        for item in value.values():
            _tree(item, depth + 1, count)
    elif type(value) is list:
        for item in value:
            _tree(item, depth + 1, count)
    elif type(value) is str:
        require(len(value) <= MAX_JSON and '\x00' not in value, 'Invalid JSON string')
    elif type(value) is float:
        require(math.isfinite(value), 'Nonfinite JSON number')
    elif type(value) is int:
        require(abs(value) < 2**64, 'Unbounded JSON integer')
    else:
        require(value is None or type(value) is bool, 'Unsupported JSON type')


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def strict_loads(data):
    require(type(data) in (str, bytes) and len(data) <= MAX_JSON, 'JSON byte limit exceeded')
    try:
        if type(data) is bytes:
            data = data.decode('utf-8', errors='strict')
        result = json.loads(data, object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(Hold('Nonfinite JSON number')),
                            parse_int=lambda value: int(value) if len(value.lstrip('-')) <= 20 else
                            (_ for _ in ()).throw(Hold('Unbounded JSON integer')))
        _tree(result)
        return result
    except (UnicodeError, RecursionError, json.JSONDecodeError, OverflowError) as error:
        raise Hold('Malformed or unbounded JSON') from error


def canonical_bytes(value):
    _tree(value)
    result = (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                         allow_nan=False) + '\n').encode('ascii')
    require(len(result) <= MAX_JSON, 'JSON byte limit exceeded')
    return result


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def read_bytes(path, limit=MAX_JSON):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing or symlinked file: ' + str(path))
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, 'File byte limit exceeded')
    return value


def source_bytes(root, path):
    safe_path(path)
    root = Path(root).resolve()
    target = root / path
    require(target.resolve().is_relative_to(root) and not any(
        p.is_symlink() for p in [target, *list(target.parents)[:len(PurePosixPath(path).parts)-1]]),
        'Source path is symlinked or outside root')
    return read_bytes(target)


def hash_map(value, expected=None, label='hash inventory'):
    require(type(value) is dict and 0 < len(value) <= MAX_MEMBERS, 'Invalid ' + label)
    for name, checksum in value.items():
        safe_path(name)
        digest(checksum)
    if expected is not None:
        require(set(value) == set(expected), 'Incomplete or extra ' + label)
    return value


def load_policy(root):
    value = strict_loads(source_bytes(root, POLICY_PATH))
    keys(value, ('schema', 'campaignId', 'targetRelease', 'protocol', 'repository', 'protectedBranch',
                 'workflowPath', 'producerEvents', 'sourcePaths', 'executionClosurePaths',
                 'geometry', 'criteria', 'childProtocol', 'pairOrder'), 'policy')
    require(value['schema'] == POLICY_SCHEMA and value['campaignId'] == CAMPAIGN_ID
            and value['targetRelease'] == '2.4.2' and value['protocol'] == PROTOCOL
            and value['repository'] == REPOSITORY and value['protectedBranch'] == 'main'
            and value['workflowPath'] == '.github/workflows/verify-v2.yml'
            and value['producerEvents'] == ['push'], 'Unrecognized campaign policy')
    for name in ('sourcePaths', 'executionClosurePaths'):
        paths = value[name]
        require(type(paths) is list and paths == sorted(set(paths)) and 0 < len(paths) <= 256,
                'Invalid policy path inventory')
        for path in paths:
            safe_path(path)
            require(not path.startswith('tools/host-inference-campaigns/'),
                    'Registration cannot be part of measured source identity')
    require(set(value['sourcePaths']).issubset(value['executionClosurePaths'])
            and {POLICY_PATH, 'version.json', 'tools/host_inference_campaign.py',
                 'tools/verify_inference_improvement.py'}.issubset(value['sourcePaths'])
            and value['workflowPath'] in value['executionClosurePaths'], 'Incomplete campaign closure')
    version = strict_loads(source_bytes(root, 'version.json'))
    require(type(version) is dict and version.get('name') == value['targetRelease'],
            'Campaign target release is not the current source release')
    return value


def measured_paths(root):
    return set(load_policy(root)['sourcePaths'])


def producer_identity(value):
    keys(value, ('runId', 'runAttempt', 'headSha', 'event', 'headBranch', 'workflowPath'), 'producer')
    integer(value['runId'], 'run ID')
    integer(value['runAttempt'], 'run attempt')
    require(value['runAttempt'] == 1, 'Only the first run attempt can produce measurements')
    commit(value['headSha'])
    require(value['event'] in EVENTS and value['headBranch'] == 'main'
            and value['workflowPath'] == '.github/workflows/verify-v2.yml',
            'Producer must be the reviewed allocated main push')
    return value


def producer_from_environment():
    try:
        value = dict(runId=int(os.environ['GITHUB_RUN_ID']), runAttempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
                     headSha=os.environ['GITHUB_SHA'], event=os.environ['GITHUB_EVENT_NAME'],
                     headBranch=os.environ['GITHUB_REF_NAME'], workflowPath='.github/workflows/verify-v2.yml')
    except (KeyError, ValueError) as error:
        raise Hold('Missing explicit GitHub producer context') from None
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Wrong producer repository')
    return producer_identity(value)


def validate_host_metadata(value):
    """Bind only the benchmark's existing safe informational host inventory.

    These fields never replace the separately mandatory hostControls resource
    ancestry, affinity and counters. No environment/JVM/system-property dump is
    permitted in this declaration.
    """
    keys(value, ('platform', 'machine', 'cpuCount', 'cpuAffinity', 'cpuQuota',
                 'memoryLimit', 'cpuModel'), 'host metadata')
    for name in ('platform', 'machine', 'cpuQuota', 'memoryLimit', 'cpuModel'):
        item = value[name]
        if item is None and name in ('cpuQuota', 'memoryLimit', 'cpuModel'):
            continue
        require(type(item) is str and 0 < len(item) <= 512 and item.isprintable(),
                'Invalid bounded host metadata string')
    integer(value['cpuCount'], 'host CPU count')
    affinity = value['cpuAffinity']
    require(type(affinity) is list and 0 < len(affinity) <= 65536
            and all(type(cpu) is int and 0 <= cpu <= 1048575 for cpu in affinity)
            and affinity == sorted(set(affinity)), 'Invalid host CPU affinity')
    return value


def validate_declaration(value, policy):
    keys(value, ('schema', 'campaignId', 'policySha256', 'producer', 'declaredAt', 'protocol',
                 'sourceBindings', 'executionClosure', 'compiledClassHashes', 'models', 'runtime',
                 'runtimeBindings', 'audio', 'geometry', 'criteria', 'hostControls', 'host',
                 'pairOrder', 'childProtocol'), 'declaration')
    require(value['schema'] == DECLARATION_SCHEMA and value['campaignId'] == policy['campaignId']
            and value['protocol'] == policy['protocol'], 'Wrong declaration campaign/protocol')
    digest(value['policySha256'])
    producer_identity(value['producer'])
    timestamp(value['declaredAt'])
    hash_map(value['sourceBindings'], policy['sourcePaths'], 'measured source inventory')
    hash_map(value['executionClosure'], policy['executionClosurePaths'], 'execution closure')
    hash_map(value['compiledClassHashes'], label='compiled class inventory')
    require(all(name.endswith('.class') for name in value['compiledClassHashes']), 'Invalid class member')
    validate_host_metadata(value['host'])
    for key in ('models', 'runtime', 'runtimeBindings', 'audio', 'hostControls'):
        require(type(value[key]) is dict and value[key], 'Missing declaration ' + key)
    for key in ('geometry', 'criteria', 'pairOrder', 'childProtocol'):
        require(canonical_bytes(value[key]) == canonical_bytes(policy[key]), 'Changed declaration ' + key)
    require(value['sourceBindings'][POLICY_PATH] == value['policySha256']
            and all(value['executionClosure'][p] == h for p, h in value['sourceBindings'].items()),
            'Contradictory source/closure policy identity')
    _tree(value)
    return value


def create_declaration(root, record, producer=None):
    policy = load_policy(root)
    declaration = dict(schema=DECLARATION_SCHEMA, campaignId=policy['campaignId'],
                       policySha256=sha_bytes(source_bytes(root, POLICY_PATH)),
                       producer=producer or producer_from_environment(),
                       declaredAt=record.get('createdAt', now()), protocol=policy['protocol'])
    for key in ('sourceBindings', 'compiledClassHashes', 'models', 'runtime', 'runtimeBindings',
                'audio', 'geometry', 'criteria', 'hostControls', 'host'):
        require(key in record, 'Prepared record lacks ' + key)
        declaration[key] = record[key]
    declaration['pairOrder'] = record.get('pairOrder', policy['pairOrder'])
    declaration['childProtocol'] = record.get('childProtocol', policy['childProtocol'])
    declaration['executionClosure'] = {p: sha_bytes(source_bytes(root, p)) for p in policy['executionClosurePaths']}
    validate_declaration(declaration, policy)
    verify_source_bindings(root, declaration, policy)
    return strict_loads(canonical_bytes(declaration))


def verify_source_bindings(root, declaration, policy=None):
    policy = policy or load_policy(root)
    validate_declaration(declaration, policy)
    require(sha_bytes(source_bytes(root, POLICY_PATH)) == declaration['policySha256'], 'Policy drift')
    for path, checksum in declaration['executionClosure'].items():
        require(sha_bytes(source_bytes(root, path)) == checksum, 'Source/closure drift: ' + path)
    return True


def artifact_name(kind, policy, producer):
    require(kind in ('declaration', 'proof'), 'Unknown artifact kind')
    return 'host-inference-' + kind + '-' + policy['campaignId'] + '-' + str(producer['runId']) + '-' + str(producer['runAttempt'])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Only read-only API routes in the pinned repository; never forward tokens."""
    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get('GITHUB_TOKEN')
        require(type(self.token) is str and 0 < len(self.token) <= 4096
                and all(33 <= ord(char) <= 126 for char in self.token), 'GITHUB_TOKEN read access is required')
        self.opener = urllib.request.build_opener(NoRedirect())

    def _request(self, url, authenticated, limit, redirect=False):
        require(type(url) is str and 0 < len(url) <= 32768
                and all(33 <= ord(char) <= 126 for char in url), 'Unsafe GitHub download URL')
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except (TypeError, ValueError):
            raise Hold('Unsafe GitHub download URL') from None
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password
                and port in (None, 443) and not parsed.fragment, 'Unsafe GitHub download URL')
        if authenticated:
            require(parsed.netloc == 'api.github.com' and parsed.path.startswith('/repos/' + REPOSITORY + '/'),
                    'API target outside pinned repository')
        else:
            require(parsed.hostname == 'release-assets.githubusercontent.com'
                    or re.fullmatch(r'productionresultssa[0-9]+\.blob\.core\.windows\.net', parsed.hostname or ''),
                    'Artifact download host is not allowlisted')
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'LightForge-host-campaign-read-only'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self.token
        try:
            request = urllib.request.Request(url, headers=headers, method='GET')
            response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            if redirect and error.code in (301, 302, 303, 307, 308):
                location = error.headers.get('Location')
                require(type(location) is str, 'Artifact redirect is missing')
                return self._request(location, False, limit, False)
            # Never include URL/query, headers, token, or response body in errors.
            raise GitHubUnavailable(error.code) from None
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise Hold('Authoritative GitHub request unavailable') from None
        try:
            with response:
                require(response.status == 200, 'Unexpected GitHub response status')
                started, size, chunks = time.monotonic(), 0, []
                while True:
                    require(time.monotonic() - started <= 300, 'GitHub response deadline exceeded')
                    chunk = response.read(min(65536, limit - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    require(size <= limit, 'GitHub response size limit exceeded')
                    chunks.append(chunk)
                return b''.join(chunks)
        except Hold:
            raise
        except (OSError, ValueError, http.client.HTTPException):
            raise Hold('Authoritative GitHub response unavailable') from None

    def get(self, route):
        require(type(route) is str and route.startswith('/') and not route.startswith('//')
                and '\\' not in route and '#' not in route and not any(ord(c) < 32 for c in route),
                'Unsafe GitHub route')
        patterns = (r'/branches/main', r'/contents/[A-Za-z0-9_./%+-]+\?ref=[0-9a-f]{40}',
                    r'/commits\?path=[A-Za-z0-9_.%+-]+&sha=[0-9a-f]{40}&per_page=2',
                    r'/commits/[0-9a-f]{40}', r'/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}',
                    r'/actions/workflows/verify-v2.yml', r'/actions/runs/[1-9][0-9]*',
                    r'/actions/runs/[1-9][0-9]*/attempts/[1-9][0-9]*',
                    r'/actions/runs/[1-9][0-9]*/attempts/[1-9][0-9]*/jobs\?per_page=100',
                    r'/actions/runs/[1-9][0-9]*/artifacts\?per_page=100&page=[1-9][0-9]*',
                    r'/actions/artifacts/[1-9][0-9]*')
        require(any(re.fullmatch(pattern, route) for pattern in patterns)
                and '..' not in urllib.parse.unquote(route.split('?')[0]).split('/'), 'GitHub route is not allowlisted')
        return strict_loads(self._request('https://api.github.com/repos/' + REPOSITORY + route, True, MAX_JSON))

    def download(self, artifact_id):
        integer(artifact_id, 'artifact ID')
        return self._request('https://api.github.com/repos/' + REPOSITORY + '/actions/artifacts/'
                             + str(artifact_id) + '/zip', True, MAX_ARCHIVE, True)


def api_get(api, route):
    value = api.get(route) if hasattr(api, 'get') else api(route)
    _tree(value)
    return value


def remote_file(api, path, sha):
    safe_path(path)
    commit(sha)
    value = api_get(api, '/contents/' + urllib.parse.quote(path, safe='/') + '?ref=' + sha)
    require(type(value) is dict and value.get('type') == 'file' and value.get('path') == path
            and value.get('encoding') == 'base64' and type(value.get('size')) is int
            and 0 <= value['size'] <= MAX_JSON, 'Invalid committed source response')
    commit(value.get('sha'), 'Git blob SHA')
    try:
        raw = base64.b64decode(value['content'].replace('\n', ''), validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise Hold('Invalid committed source encoding') from error
    require(len(raw) == value['size'], 'Committed source size mismatch')
    require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == value['sha'],
            'Committed source Git blob mismatch')
    return raw, value['sha']


def load_request(api, policy, *, absent_ok=False):
    """A separate immutable protected-main request allocates exactly one commit."""
    branch = api_get(api, '/branches/main')
    require(type(branch) is dict and branch.get('name') == 'main' and branch.get('protected') is True,
            'Main branch protection cannot be positively verified')
    head = commit(branch.get('commit', {}).get('sha'), 'protected main head')
    path = 'tools/host-inference-campaigns/' + policy['campaignId'] + '.request.json'
    try:
        raw, blob = remote_file(api, path, head)
    except GitHubUnavailable as error:
        if error.status == 404 and absent_ok:
            return None, None
        raise
    request = strict_loads(raw)
    keys(request, ('schema', 'campaignId', 'policySha256'), 'campaign request')
    require(request['schema'] == 'lightforge.host-inference-request.v1'
            and request['campaignId'] == policy['campaignId'], 'Wrong allocation request')
    digest(request['policySha256'])
    history = api_get(api, '/commits?path=' + urllib.parse.quote(path, safe='') + '&sha=' + head + '&per_page=2')
    require(type(history) is list and len(history) == 1, 'Campaign request was replaced, deleted, or has uncertain history')
    allocated = commit(history[0].get('sha'), 'allocation commit')
    original, original_blob = remote_file(api, path, allocated)
    require(original == raw and original_blob == blob, 'Campaign request changed')
    ancestry = api_get(api, '/compare/' + allocated + '...' + head)
    require(ancestry.get('status') in ('ahead', 'identical')
            and ancestry.get('merge_base_commit', {}).get('sha') == allocated,
            'Allocation commit is not on protected main history')
    return request, dict(commit=allocated, path=path, blobSha=blob, sha256=sha_bytes(raw))


def route_campaign(root, api=None, environment=None):
    """Route only. Neither a new run nor a local request can grant measurement."""
    policy = load_policy(root)
    environment = environment if environment is not None else os.environ
    result = dict(schema='lightforge.host-inference-route.v1', mode='consumer',
                  campaignId=policy['campaignId'], request=None)
    # PRs/dispatches cannot allocate any producer, nor need a privileged lookup.
    if environment.get('GITHUB_EVENT_NAME') != 'push' or environment.get('GITHUB_REF_NAME') != 'main':
        return result
    require(environment.get('GITHUB_REPOSITORY') == REPOSITORY, 'Wrong routing repository')
    sha = commit(environment.get('GITHUB_SHA'), 'routing commit')
    try:
        attempt = integer(int(environment['GITHUB_RUN_ATTEMPT']), 'routing attempt')
        integer(int(environment['GITHUB_RUN_ID']), 'routing run ID')
    except (KeyError, ValueError) as error:
        raise Hold('Missing routing run identity') from None
    request, provenance = load_request(api or GitHub(), policy, absent_ok=True)
    result['request'] = provenance
    if request is None:
        return result
    require(request['policySha256'] == sha_bytes(source_bytes(root, POLICY_PATH)), 'Allocation request policy drift')
    if sha == provenance['commit']:
        result['mode'] = 'producer' if attempt == 1 else 'producer-replay'
    return result


def load_registration(api, policy):
    branch = api_get(api, '/branches/' + policy['protectedBranch'])
    require(type(branch) is dict and branch.get('name') == 'main' and branch.get('protected') is True,
            'Main branch protection cannot be positively verified')
    head = commit(branch.get('commit', {}).get('sha'), 'protected main head')
    path = 'tools/host-inference-campaigns/' + policy['campaignId'] + '.json'
    try:
        raw, blob = remote_file(api, path, head)  # direct fetch: absence always holds
    except GitHubUnavailable as error:
        if error.status == 404:
            raise AwaitingRegistration('Protected main has no registered declaration yet') from None
        raise
    value = strict_loads(raw)
    keys(value, ('schema', 'campaignId', 'policySha256', 'declarationSha256', 'producer',
                 'declarationArtifactId', 'declarationArtifactSha256', 'executionClosure'), 'registration')
    require(value['schema'] == REGISTRATION_SCHEMA and value['campaignId'] == policy['campaignId'],
            'Invalid registration campaign')
    digest(value['policySha256'])
    digest(value['declarationSha256'])
    digest(value['declarationArtifactSha256'])
    integer(value['declarationArtifactId'], 'declaration artifact ID')
    producer_identity(value['producer'])
    hash_map(value['executionClosure'], policy['executionClosurePaths'], 'registered execution closure')
    history = api_get(api, '/commits?path=' + urllib.parse.quote(path, safe='') + '&sha=' + head + '&per_page=2')
    require(type(history) is list and len(history) == 1, 'Campaign registration was replaced, deleted, or has uncertain history')
    registered = commit(history[0].get('sha'), 'registration commit')
    original_raw, original_blob = remote_file(api, path, registered)
    require(original_raw == raw and original_blob == blob, 'Campaign registration changed')
    registration_commit = api_get(api, '/commits/' + registered)
    require(registration_commit.get('sha') == registered, 'Registration commit metadata mismatch')
    # GitHub's protected branch head and path history supply authority. The local
    # registration file and its own assertions never do. Git commit dates below
    # are consistency checks, not trusted server publication timestamps.
    registered_at = timestamp(registration_commit.get('commit', {}).get('committer', {}).get('date'))
    compare = api_get(api, '/compare/' + registered + '...' + head)
    require(compare.get('status') in ('ahead', 'identical')
            and compare.get('merge_base_commit', {}).get('sha') == registered,
            'Registration commit is not on protected main history')
    return value, dict(commit=registered, path=path, blobSha=blob, sha256=sha_bytes(raw)), registered_at


def check_run(api, policy, producer, purpose):
    latest = api_get(api, '/actions/runs/' + str(producer['runId']))
    attempt = api_get(api, '/actions/runs/' + str(producer['runId']) + '/attempts/' + str(producer['runAttempt']))
    workflow = api_get(api, '/actions/workflows/' + urllib.parse.quote(policy['workflowPath'].split('/')[-1], safe=''))
    require(type(workflow) is dict and workflow.get('path') == policy['workflowPath']
            and type(workflow.get('id')) is int and workflow.get('state') == 'active', 'Wrong/disabled producer workflow')
    for value in (latest, attempt):
        require(type(value) is dict and type(value.get('id')) is int and value.get('id') == producer['runId']
                and value.get('head_sha') == producer['headSha']
                and value.get('head_branch') == producer['headBranch'] and value.get('event') == producer['event']
                and value.get('path') == policy['workflowPath'] and value.get('workflow_id') == workflow['id'],
                'Producer run identity does not match registration')
        for field in ('repository', 'head_repository'):
            repo = value.get(field, {})
            require(type(repo) is dict and repo.get('full_name') == REPOSITORY
                    and type(repo.get('id')) is int and repo['id'] > 0, 'Foreign or missing producer repository')
        require(value['repository']['id'] == value['head_repository']['id'], 'Fork producer is forbidden')
        integer(value.get('run_attempt'), 'server run attempt')
    require(attempt['run_attempt'] == producer['runAttempt'], 'Wrong authoritative run attempt')
    require(latest['run_attempt'] >= producer['runAttempt'], 'Producer run history regressed')
    status, conclusion = attempt.get('status'), attempt.get('conclusion')
    if status == 'completed' and conclusion in ('failure', 'timed_out', 'action_required', 'startup_failure'):
        raise TerminalFailure('The registered producer attempt failed; no replacement or retry is allowed')
    if purpose == 'producer':
        require(latest['run_attempt'] == producer['runAttempt'] and status == 'in_progress' and conclusion is None,
                'Producer is not the one live original attempt')
    else:
        require(status == 'completed' and conclusion == 'success', 'Registered proof is cancelled, pending, or not successful')
    timestamp(attempt.get('run_started_at'))
    jobs = api_get(api, '/actions/runs/' + str(producer['runId']) + '/attempts/'
                   + str(producer['runAttempt']) + '/jobs?per_page=100')
    require(type(jobs) is dict and type(jobs.get('total_count')) is int
            and 0 < jobs['total_count'] <= 100 and type(jobs.get('jobs')) is list
            and len(jobs['jobs']) == jobs['total_count'], 'Incomplete original-attempt job inventory')
    producers = [job for job in jobs['jobs'] if type(job) is dict and job.get('name') == 'host-campaign']
    require(len(producers) == 1, 'Exactly one original host-campaign job is required')
    job = producers[0]
    require(job.get('run_id') == producer['runId'] and job.get('head_sha') == producer['headSha'],
            'Producer job identity mismatch')
    if purpose == 'producer':
        require(job.get('status') == 'in_progress' and job.get('conclusion') is None
                and job.get('completed_at') is None, 'Original host job is not live')
    else:
        require(job.get('status') == 'completed' and job.get('conclusion') == 'success',
                'Original host job did not succeed')
        timestamp(job.get('completed_at'))
    require(timestamp(job.get('started_at')) >= timestamp(attempt['run_started_at']), 'Producer job dates disagree')
    attempt = dict(attempt, hostCampaignJob=job)
    return attempt


def artifact_metadata(api, policy, producer, artifact_id, kind, run):
    value = api_get(api, '/actions/artifacts/' + str(integer(artifact_id, 'artifact ID')))
    require(type(value) is dict and type(value.get('id')) is int and value.get('id') == artifact_id and value.get('expired') is False
            and value.get('name') == artifact_name(kind, policy, producer), 'Artifact is missing, expired, or renamed')
    require(type(value.get('size_in_bytes')) is int and 0 < value['size_in_bytes'] <= MAX_ARCHIVE,
            'Invalid artifact archive size')
    server_digest = value.get('digest')
    require(type(server_digest) is str and server_digest.startswith('sha256:'), 'Missing authoritative artifact SHA-256')
    digest(server_digest[7:])
    origin = value.get('workflow_run', {})
    require(origin.get('id') == producer['runId'] and origin.get('head_sha') == producer['headSha']
            and origin.get('head_branch') == producer['headBranch']
            and origin.get('repository_id') == run['repository']['id']
            and origin.get('head_repository_id') == run['head_repository']['id'], 'Artifact producer mismatch')
    created = timestamp(value.get('created_at'))
    require(created >= timestamp(run['run_started_at']) and created <= timestamp(value.get('updated_at')),
            'Artifact predates registered attempt or has invalid dates')
    require(timestamp(value.get('expires_at')) > dt.datetime.now(dt.timezone.utc), 'Artifact retention expired')
    job = run['hostCampaignJob']
    require(created >= timestamp(job['started_at']), 'Artifact predates original host job')
    if job.get('completed_at') is not None:
        require(timestamp(value['updated_at']) <= timestamp(job['completed_at']),
                'Artifact was uploaded or changed after original producer job ended')
    return value


def safe_zip(data):
    require(type(data) is bytes and 0 < len(data) <= MAX_ARCHIVE, 'Invalid artifact ZIP size')
    result, names, total = {}, set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            require(0 < len(entries) <= MAX_MEMBERS, 'Artifact ZIP member limit exceeded')
            for entry in entries:
                name = entry.filename
                safe_path(name.rstrip('/') if entry.is_dir() else name)
                normalized = name.rstrip('/')
                require(normalized not in names, 'Duplicate artifact ZIP member')
                names.add(normalized)
                mode = (entry.external_attr >> 16) & 0xffff
                require(not entry.flag_bits & 1 and not stat.S_ISLNK(mode)
                        and (stat.S_IFMT(mode) in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG)),
                        'Encrypted or special artifact ZIP member')
                require(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported ZIP compression')
                total += entry.file_size
                require(0 <= entry.file_size <= MAX_UNPACKED and total <= MAX_UNPACKED,
                        'Artifact ZIP expansion limit exceeded')
                if entry.is_dir():
                    require(entry.file_size == 0, 'Directory member has content')
                    continue
                for parent in PurePosixPath(name).parents:
                    require(str(parent) not in result, 'Artifact ZIP file/directory collision')
                require(not any(existing.startswith(name + '/') for existing in names), 'Artifact ZIP path collision')
                with archive.open(entry) as stream:
                    content = stream.read(entry.file_size + 1)
                require(len(content) == entry.file_size, 'Artifact ZIP member size mismatch')
                result[name] = content
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as error:
        raise Hold('Invalid artifact ZIP') from error
    return result


def download_artifact(api, metadata, downloader=None):
    data = downloader(metadata['id']) if downloader else api.download(metadata['id'])
    require(type(data) is bytes and len(data) == metadata['size_in_bytes'], 'Downloaded artifact size mismatch')
    require(sha_bytes(data) == metadata['digest'][7:], 'Downloaded artifact server digest mismatch')
    return safe_zip(data)


def check_online_admission(root, declaration, api=None, purpose='producer', receipt=None, admission=None, receipt_sha256=None):
    require(purpose in ('producer', 'replay'), 'Unknown online admission purpose')
    api = api or GitHub()
    policy = load_policy(root)
    verify_source_bindings(root, declaration, policy)
    request, request_provenance = load_request(api, policy)
    require(request['policySha256'] == declaration['policySha256']
            and request_provenance['commit'] == declaration['producer']['headSha'],
            'Producer was not allocated by the immutable main request')
    registration, provenance, registered_at = load_registration(api, policy)
    require(registration['policySha256'] == declaration['policySha256']
            and registration['producer'] == declaration['producer']
            and registration['declarationSha256'] == sha_bytes(canonical_bytes(declaration))
            and registration['executionClosure'] == declaration['executionClosure'], 'Registration/declaration mismatch')
    run = check_run(api, policy, declaration['producer'], purpose)
    ancestry = api_get(api, '/compare/' + declaration['producer']['headSha'] + '...' + provenance['commit'])
    require(ancestry.get('status') in ('ahead', 'identical')
            and ancestry.get('merge_base_commit', {}).get('sha') == declaration['producer']['headSha'],
            'Producer source is not an ancestor of protected main registration')
    metadata = artifact_metadata(api, policy, declaration['producer'], registration['declarationArtifactId'], 'declaration', run)
    require(metadata['digest'][7:] == registration['declarationArtifactSha256'], 'Registered declaration archive digest mismatch')
    require(timestamp(metadata['created_at']) <= registered_at, 'Registration date predates declaration upload')
    files = download_artifact(api, metadata)
    require(set(files) == {DECLARATION_MEMBER} and files[DECLARATION_MEMBER] == canonical_bytes(declaration),
            'Immutable declaration artifact content mismatch')
    # Independent committed-file comparison, not a self-asserted source hash map.
    for path, checksum in declaration['executionClosure'].items():
        raw, _ = remote_file(api, path, declaration['producer']['headSha'])
        require(sha_bytes(raw) == checksum, 'Producer committed source differs: ' + path)
    if receipt is not None:
        require(type(receipt) is dict and receipt.get('campaignDeclaration') == declaration,
                'Receipt does not bind the immutable declaration')
        require(receipt.get('sourceBindings') == declaration['sourceBindings']
                and receipt.get('compiledClassHashes') == declaration['compiledClassHashes']
                and receipt.get('host') == declaration['host'],
                'Receipt source/classes/host drifted from declaration')
    result = dict(schema=CHECK_SCHEMA, purpose=purpose, campaignId=policy['campaignId'],
                  policySha256=declaration['policySha256'], declarationSha256=registration['declarationSha256'],
                  registration=provenance, request=request_provenance, producer=declaration['producer'],
                  declarationArtifact=dict(id=metadata['id'], sha256=metadata['digest'][7:]),
                  checkedAt=now(), measurementAuthorized=purpose == 'producer',
                  trustedReplayAuthorized=purpose == 'replay')
    if receipt is not None:
        before = receipt.get('registrationCheck')
        require(type(before) is dict and before.get('schema') == CHECK_SCHEMA
                and before.get('purpose') == 'producer' and before.get('measurementAuthorized') is True
                and before.get('trustedReplayAuthorized') is False, 'Missing premeasurement live registration check')
        for field in ('campaignId', 'policySha256', 'declarationSha256', 'registration', 'request', 'producer', 'declarationArtifact'):
            require(before.get(field) == result[field], 'Premeasurement check differs: ' + field)
        require(timestamp(declaration['declaredAt']) <= timestamp(before.get('checkedAt'))
                <= timestamp(receipt.get('measurementStartedAt')) <= timestamp(receipt.get('finishedAt')),
                'Invalid prospective check/measurement timestamp ordering')
    if admission is not None:
        validate_admission(admission)
        for field in ('campaignId', 'policySha256', 'declarationSha256', 'registration', 'request', 'producer', 'declarationArtifact'):
            require(admission[field] == result[field], 'Sealed admission mismatch: ' + field)
        require(admission['recompiledClassHashes'] == declaration['compiledClassHashes'],
                'Fresh candidate classes differ from immutable proof classes')
        require(receipt is not None and admission['measurementFinishedAt'] == receipt.get('finishedAt'),
                'Sealed measurement timestamp mismatch')
        require(receipt is not None and receipt_sha256 is not None
                and admission['proofReceiptSha256'] == digest(receipt_sha256),
                'Sealed proof receipt mismatch')
    return result


def find_proof_artifact(api, policy, producer):
    name = artifact_name('proof', policy, producer)
    matches, seen_ids, expected_total = [], set(), None
    for page in range(1, 21):
        value = api_get(api, '/actions/runs/' + str(producer['runId']) + '/artifacts?per_page=100&page=' + str(page))
        require(type(value) is dict and type(value.get('artifacts')) is list
                and type(value.get('total_count')) is int and 0 <= value['total_count'] <= 2000,
                'Unbounded or missing run artifact inventory')
        if expected_total is None:
            expected_total = value['total_count']
        require(value['total_count'] == expected_total, 'Run artifact inventory total changed during pagination')
        expected_size = min(100, expected_total - (page - 1) * 100)
        require(len(value['artifacts']) == expected_size, 'Truncated or overfull run artifact inventory page')
        for artifact in value['artifacts']:
            require(type(artifact) is dict, 'Malformed run artifact inventory entry')
            artifact_id = integer(artifact.get('id'), 'inventory artifact ID')
            require(artifact_id not in seen_ids, 'Duplicate run artifact inventory ID or page')
            seen_ids.add(artifact_id)
            require(type(artifact.get('name')) is str and 0 < len(artifact['name']) <= 1024,
                    'Malformed run artifact inventory name')
            if artifact['name'] == name:
                matches.append(artifact)
        if len(seen_ids) == expected_total:
            break
    require(expected_total is not None and len(seen_ids) == expected_total,
            'Run artifact inventory count did not reconcile')
    require(len(matches) == 1, 'Exactly one named proof artifact is required; absence never authorizes a new measurement')
    return integer(matches[0].get('id'), 'proof artifact ID')


def materialize(files, output_dir):
    root = Path(output_dir)
    require(not root.exists(), 'Proof destination must not already exist')
    root.mkdir(parents=True)
    try:
        for name, content in files.items():
            safe_path(name)
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(content)
    except OSError as error:
        raise Hold('Cannot materialize verified proof bundle') from error
    return root


def fetch_proof(root, api=None, admission=None, output_dir=None, downloader=None):
    """Return (declaration, receipt, proof_directory, live_check). Caller owns cleanup.

    This is authenticated provenance only. The caller MUST independently replay
    all raw numerical/profile/resource evidence before treating it as a pass.
    """
    api = api or GitHub()
    policy = load_policy(root)
    if admission is not None:
        validate_admission(admission)
    registration, _, _ = load_registration(api, policy)
    run = check_run(api, policy, registration['producer'], 'replay')
    declaration_meta = artifact_metadata(api, policy, registration['producer'], registration['declarationArtifactId'], 'declaration', run)
    require(declaration_meta['digest'][7:] == registration['declarationArtifactSha256'], 'Declaration archive digest mismatch')
    declarations = download_artifact(api, declaration_meta, downloader)
    require(set(declarations) == {DECLARATION_MEMBER}, 'Declaration artifact has unexpected members')
    declaration = strict_loads(declarations[DECLARATION_MEMBER])
    proof_id = find_proof_artifact(api, policy, registration['producer'])
    if admission is not None:
        require(admission['proofArtifact']['id'] == proof_id, 'Known proof artifact was replaced or omitted')
    proof_meta = artifact_metadata(api, policy, registration['producer'], proof_id, 'proof', run)
    if admission is not None:
        require(proof_meta['digest'][7:] == admission['proofArtifact']['sha256'], 'Sealed proof archive digest mismatch')
    files = download_artifact(api, proof_meta, downloader)
    require(DECLARATION_MEMBER in files and RECEIPT_MEMBER in files, 'Proof bundle lacks declaration or receipt')
    require(files[DECLARATION_MEMBER] == declarations[DECLARATION_MEMBER], 'Proof declaration differs from premeasurement declaration')
    receipt = strict_loads(files[RECEIPT_MEMBER])
    check = check_online_admission(root, declaration, api, 'replay', receipt, admission, sha_bytes(files[RECEIPT_MEMBER]))
    check['proofArtifact'] = dict(id=proof_id, sha256=proof_meta['digest'][7:])
    check['proofReceiptSha256'] = sha_bytes(files[RECEIPT_MEMBER])
    # This point still makes no assertion that timing or output passed.
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix='lightforge-host-proof-')) / 'proof'
    return declaration, receipt, materialize(files, output_dir), check


def validate_admission(value, *, candidate_source_commit=None, candidate_source_tree_sha=None, evidence_session=None):
    keys(value, ('schema', 'campaignId', 'policySha256', 'declarationSha256', 'registration', 'request', 'producer',
                 'declarationArtifact', 'proofArtifact', 'proofReceiptSha256', 'measurementFinishedAt',
                 'admissionCheckedAt', 'candidate', 'knownLineage', 'recompiledClassHashes'), 'sealed host admission')
    require(value['schema'] == ADMISSION_SCHEMA and value['campaignId'] == CAMPAIGN_ID, 'Wrong sealed campaign')
    for name in ('policySha256', 'declarationSha256', 'proofReceiptSha256'):
        digest(value[name])
    keys(value['registration'], ('commit', 'path', 'blobSha', 'sha256'), 'registration provenance')
    commit(value['registration']['commit'])
    commit(value['registration']['blobSha'], 'registration blob')
    digest(value['registration']['sha256'])
    require(value['registration']['path'] == 'tools/host-inference-campaigns/' + CAMPAIGN_ID + '.json', 'Wrong registration path')
    keys(value['request'], ('commit', 'path', 'blobSha', 'sha256'), 'allocation request provenance')
    commit(value['request']['commit'])
    commit(value['request']['blobSha'], 'request blob')
    digest(value['request']['sha256'])
    require(value['request']['path'] == 'tools/host-inference-campaigns/' + CAMPAIGN_ID + '.request.json'
            and value['request']['commit'] == value['producer']['headSha'], 'Wrong allocation request provenance')
    producer_identity(value['producer'])
    hash_map(value['recompiledClassHashes'], label='fresh candidate class inventory')
    require(all(path.endswith('.class') for path in value['recompiledClassHashes']), 'Invalid fresh candidate class path')
    for name in ('declarationArtifact', 'proofArtifact'):
        keys(value[name], ('id', 'sha256'), name)
        integer(value[name]['id'], 'artifact ID')
        digest(value[name]['sha256'])
    require(value['declarationArtifact']['id'] != value['proofArtifact']['id'], 'Declaration and proof artifacts must differ')
    finished = timestamp(value['measurementFinishedAt'])
    checked = timestamp(value['admissionCheckedAt'])
    require(finished <= checked <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
            'Admission predates measurement or is in the future')
    keys(value['candidate'], ('sourceCommit', 'sourceTreeSha', 'evidenceSession'), 'candidate identity')
    commit(value['candidate']['sourceCommit'])
    commit(value['candidate']['sourceTreeSha'], 'candidate Git tree')
    digest(value['candidate']['evidenceSession'], 'candidate evidence session')
    for name, expected in (('sourceCommit', candidate_source_commit), ('sourceTreeSha', candidate_source_tree_sha), ('evidenceSession', evidence_session)):
        require(expected is None or value['candidate'][name] == expected, 'Wrong fresh candidate ' + name)
    expected = [dict(runId=value['producer']['runId'], runAttempt=value['producer']['runAttempt'],
                     declarationArtifactId=value['declarationArtifact']['id'], proofArtifactId=value['proofArtifact']['id'])]
    require(value['knownLineage'] == expected, 'Incomplete or extra known campaign lineage')
    return value


def seal_admission(check, receipt, *, candidate_source_commit, candidate_source_tree_sha, evidence_session, recompiled_class_hashes):
    """Seal provenance into a candidate; does NOT replace numerical replay."""
    require(check.get('purpose') == 'replay' and check.get('trustedReplayAuthorized') is True,
            'Only live trusted replay can be sealed')
    result = {key: check[key] for key in ('campaignId', 'policySha256', 'declarationSha256', 'registration', 'request',
                                         'producer', 'declarationArtifact', 'proofArtifact', 'proofReceiptSha256')}
    require(recompiled_class_hashes == receipt.get('compiledClassHashes'), 'Fresh candidate compile differs from proof')
    result.update(schema=ADMISSION_SCHEMA, recompiledClassHashes=recompiled_class_hashes, measurementFinishedAt=receipt['finishedAt'], admissionCheckedAt=check['checkedAt'],
                  candidate=dict(sourceCommit=candidate_source_commit, sourceTreeSha=candidate_source_tree_sha, evidenceSession=evidence_session),
                  knownLineage=[dict(runId=check['producer']['runId'], runAttempt=check['producer']['runAttempt'],
                                     declarationArtifactId=check['declarationArtifact']['id'], proofArtifactId=check['proofArtifact']['id'])])
    return validate_admission(result)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def verify_numerical_proof(root, directory, *, rebuild_classes):
    path = Path(root) / 'tools/verify_inference_improvement.py'
    spec = importlib.util.spec_from_file_location('host_campaign_numerical_verifier', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_bounded(Path(directory) / RECEIPT_MEMBER, root=Path(root), rebuild_classes=rebuild_classes)


def admit_proof(root, directory, check, receipt, evidence_session, api=None):
    digest(evidence_session, 'fresh evidence session')
    verify_numerical_proof(root, directory, rebuild_classes=True)
    # The numerical verifier must rebuild the classes and compare their complete
    # byte inventory; copying the original class map alone is never sufficient.
    def git_revision(revision):
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', revision],
                                capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, 'Cannot establish current candidate Git identity')
        return commit(result.stdout.strip(), 'candidate Git identity')
    source_commit, tree_sha = git_revision('HEAD'), git_revision('HEAD^{tree}')
    require(sha_bytes(read_bytes(Path(directory) / RECEIPT_MEMBER)) == check['proofReceiptSha256'],
            'Proof receipt changed during fresh admission')
    api = api or GitHub()
    live = check_online_admission(root, receipt['campaignDeclaration'], api=api, purpose='replay', receipt=receipt)
    policy = load_policy(root)
    producer = receipt['campaignDeclaration']['producer']
    require(find_proof_artifact(api, policy, producer) == check['proofArtifact']['id'],
            'Known proof artifact changed during fresh admission')
    run = check_run(api, policy, producer, 'replay')
    proof_metadata = artifact_metadata(api, policy, producer, check['proofArtifact']['id'], 'proof', run)
    require(proof_metadata['digest'][7:] == check['proofArtifact']['sha256'],
            'Known proof digest changed during fresh admission')
    live.update(proofArtifact=check['proofArtifact'], proofReceiptSha256=check['proofReceiptSha256'])
    return seal_admission(live, receipt, candidate_source_commit=source_commit, candidate_source_tree_sha=tree_sha,
                          evidence_session=evidence_session, recompiled_class_hashes=receipt['compiledClassHashes'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('check', 'replay', 'seal', 'declare', 'route'):
        command = sub.add_parser(name)
        command.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
        command.add_argument('--output', type=Path)
        if name in ('check',):
            command.add_argument('--declaration', type=Path, required=True)
            command.add_argument('--purpose', choices=('producer', 'replay'), default='producer')
        if name in ('replay', 'seal'):
            command.add_argument('--admission', type=Path)
            command.add_argument('--output-dir', type=Path, required=True)
        if name == 'replay':
            command.add_argument('--admission-output', type=Path)
            command.add_argument('--prerequisite-output', type=Path)
            command.add_argument('--evidence-session')
        if name == 'declare':
            command.add_argument('--record', type=Path, required=True)
        if name == 'seal':
            command.add_argument('--recompiled-class-hashes', type=Path, required=True)
            command.add_argument('--source-commit', required=True)
            command.add_argument('--source-tree-sha', required=True)
            command.add_argument('--evidence-session', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'route':
            result = route_campaign(args.root)
        elif args.command == 'declare':
            result = create_declaration(args.root, strict_loads(read_bytes(args.record)))
        elif args.command == 'check':
            result = check_online_admission(args.root, strict_loads(read_bytes(args.declaration)), purpose=args.purpose)
        else:
            admission = strict_loads(read_bytes(args.admission)) if args.admission else None
            _, receipt, directory, check = fetch_proof(args.root, admission=admission, output_dir=args.output_dir)
            if args.command == 'seal':
                result = admit_proof(args.root, directory, check, receipt, args.evidence_session)
                validate_admission(result, candidate_source_commit=args.source_commit,
                                   candidate_source_tree_sha=args.source_tree_sha, evidence_session=args.evidence_session)
                require(result['recompiledClassHashes'] == strict_loads(read_bytes(args.recompiled_class_hashes)),
                        'Supplied class inventory differs from fresh candidate compile')
            else:
                if args.admission_output or args.prerequisite_output:
                    require(args.admission_output is not None and args.prerequisite_output is not None
                            and args.evidence_session is not None, 'Fresh admission requires both outputs and evidence session')
                    result = admit_proof(args.root, directory, check, receipt, args.evidence_session)
                    write_json(args.admission_output, result)
                    write_json(args.prerequisite_output, dict(schema='lightforge.host-inference-build-prerequisite.v1',
                               sourceBindings=receipt['sourceBindings'], sourceBindingsAfter=receipt['sourceBindingsAfter'], admission=result))
                else:
                    result = dict(check, proofDirectory=str(directory), numericalReplayRequired=True)
        code = 0
    except AwaitingRegistration as error:
        result, code = dict(status='awaiting-registration', reason=str(error), measurementAuthorized=False), 2
    except TerminalFailure as error:
        result, code = dict(status='terminal-failure', reason=str(error), measurementAuthorized=False), 3
    except (Hold, OSError, KeyError, TypeError, ValueError) as error:
        result, code = dict(status='hold', reason=str(error), measurementAuthorized=False), 2
    payload = canonical_bytes(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    print(payload.decode(), end='')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
