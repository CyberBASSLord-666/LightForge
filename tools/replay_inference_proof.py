#!/usr/bin/env python3
"""Replay the immutable 2.4.2 inference experiment for the unchanged 2.4.3 engine.

No function measures, warms or runs a model. The original authority and numerical
verifiers execute against an exact historical source view, never a version-edited
candidate. A separate current-source projection and fresh class rebuild bind the
old observation to the new release. All ordinary app/Android/signing gates remain.
"""
from contextlib import contextmanager
from functools import lru_cache
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'tools/inference_replay_policy.json'
OLD_HELPER = 'tools/host_inference_campaign.py'
OLD_POLICY = 'tools/host_inference_policy.json'
CAMPAIGN = 'lightforge-2.4.2-neural-four-worker-host-001'
REGISTRATION = 'tools/host-inference-campaigns/' + CAMPAIGN + '.json'
BASE_COMMIT = '214b8f868ab3b412ebf4d57f75f3ba4b1863272b'
HELPER_SHA = 'dc0dbe2168831b1d741f0197bdeb6adf8c33a5158202bd22dc8925259817419b'
OLD_POLICY_SHA = 'af4ac4c7706fde42abd99a92c583565206a1e07b2d80810a1e5db01bf7a60af1'
REGISTRATION_SHA = '42049411c3014dca6072a0dc2e983cd2987b7dbac0fa0244b52e9d2872187131'
METADATA_PATHS = frozenset({'version.json', '.github/workflows/verify-v2.yml'})
TARGET = {'name': '2.4.3', 'code': 20403}
GRAPH_FILES = {'front.onnx', 'head-0.onnx', 'head-1.onnx'} | {
    'block-%02d-%s.onnx' % (index, axis) for index in range(12) for axis in ('time', 'frequency')}
PREREQUISITE = 'research/inference-current/production-parallel-qualification.json'
PREREQUISITE_SCHEMA = 'lightforge.replayed-inference-prerequisite.v1'
SCOPE = ('Immutable 2.4.2 bounded-host timing replay for the byte-identical Deux '
         'numerical source/model/runtime/class set in 2.4.3. Within the original '
         '27-file closure, only release metadata and the reviewed verification '
         'entrypoint differ. Not a new measurement, Android or whole-analysis '
         'speedup, or a substitute for fresh app/Android/signing gates.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(root, relative, limit=8 * 1024 * 1024):
    root, relative = Path(root).resolve(), Path(relative)
    require(not relative.is_absolute() and relative.parts and
            all(part not in ('', '.', '..') for part in relative.parts), 'Unsafe replay source path')
    target = root / relative
    require(target.is_file() and not any(p.is_symlink() for p in (target, *target.parents) if p != root.parent),
            'Replay source is missing or symlinked: ' + relative.as_posix())
    with target.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'Replay source exceeds limit: ' + relative.as_posix())
    return raw


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=8)
def _helper_module(root, verified_bytes):
    module = ModuleType('frozen_host_campaign_replay')
    module.__file__ = str(Path(root) / OLD_HELPER)
    # Execute the exact bytes whose digest was checked, without a second file
    # open that could race a worktree mutation between hashing and import.
    exec(compile(verified_bytes, module.__file__, 'exec'), module.__dict__)
    return module


def trusted_helper(root):
    raw = read(root, OLD_HELPER)
    require(sha(raw) == HELPER_SHA, 'Frozen campaign verifier changed')
    return _helper_module(str(Path(root).resolve()), raw)


def policy_and_closure(root):
    helper = trusted_helper(root)
    value = helper.strict_loads(read(root, POLICY))
    helper.keys(value, ('schema', 'baselineCampaignId', 'baselineSourceCommit',
                       'baselinePolicySha256', 'targetRelease', 'permittedMetadataChanges',
                       'currentWorkflowSha256', 'scope'), 'cross-release replay policy')
    require(value['schema'] == 'lightforge.inference-replay-policy.v1' and
            value['baselineCampaignId'] == CAMPAIGN and value['baselineSourceCommit'] == BASE_COMMIT and
            value['baselinePolicySha256'] == OLD_POLICY_SHA and value['targetRelease'] == TARGET and
            value['permittedMetadataChanges'] == sorted(METADATA_PATHS) and value['scope'] == SCOPE,
            'Unreviewed inference replay policy')
    helper.digest(value['currentWorkflowSha256'])
    require(sha(read(root, OLD_POLICY)) == OLD_POLICY_SHA, 'Original inference policy changed')
    require(sha(read(root, REGISTRATION)) == REGISTRATION_SHA, 'Original inference registration changed')
    registration = helper.strict_loads(read(root, REGISTRATION))
    require(registration.get('producer', {}).get('headSha') == BASE_COMMIT,
            'Original producer source differs')
    closure = registration['executionClosure']
    helper.hash_map(closure, helper.strict_loads(read(root, OLD_POLICY))['executionClosurePaths'],
                    'original inference closure')
    return helper, value, closure


def current_projection(root):
    """Metadata exceptions cannot authorize changed numerical or replay code."""
    helper, policy, closure = policy_and_closure(root)
    current = {name: sha(read(root, name)) for name in closure}
    unchanged = {name: checksum for name, checksum in closure.items() if name not in METADATA_PATHS}
    require(all(current[name] == checksum for name, checksum in unchanged.items()),
            'Current numerical/execution closure differs from the original proof')
    require(helper.strict_loads(read(root, 'version.json')) == TARGET, 'Wrong target release identity')
    require(current['.github/workflows/verify-v2.yml'] == policy['currentWorkflowSha256'],
            'Verification workflow differs from the reviewed replay policy')
    return dict(scope=SCOPE, targetRelease=TARGET, baselineSourceCommit=BASE_COMMIT,
                replayPolicySha256=sha(read(root, POLICY)), unchangedExecutionSources=unchanged,
                declaredMetadataChanges={name: {'originalSha256': closure[name], 'currentSha256': current[name]}
                                         for name in sorted(METADATA_PATHS)})


def current_java_bindings(root):
    current_projection(root)
    _, _, closure = policy_and_closure(root)
    return {name: checksum for name, checksum in closure.items() if name.endswith('.java')}


def git_identity(root):
    def revision(value):
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', value],
                                capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, 'Current candidate Git identity is unavailable')
        return result.stdout.strip()
    helper = trusted_helper(root)
    return helper.commit(revision('HEAD')), helper.commit(revision('HEAD^{tree}'))


@contextmanager
def original_source(root, api, *, include_models=False):
    """Never overwrite version/workflow files in the current candidate checkout."""
    root = Path(root).resolve()
    helper, policy, closure = policy_and_closure(root)
    current_projection(root)
    # Siblings share the same managed, pinned toolchain directory. The source
    # view contains regular files and is never a symlink to a modified version.
    with tempfile.TemporaryDirectory(prefix='.lightforge-original-proof-', dir=root.parent) as temporary:
        original = Path(temporary)
        for name, checksum in closure.items():
            if name in METADATA_PATHS:
                raw, _ = helper.remote_file(api, name, BASE_COMMIT)
            else:
                raw = read(root, name)
            require(sha(raw) == checksum, 'Original committed closure bytes differ: ' + name)
            target = original / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        if include_models:
            manifest_path = 'web/analysis/models/deux/manifest.json'
            manifest_raw = read(root, manifest_path)
            manifest = helper.strict_loads(manifest_raw)
            require(type(manifest.get('files')) is dict and set(manifest['files']) == GRAPH_FILES,
                    'Original graph file inventory differs')
            target = original / manifest_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(manifest_raw)
            material = ['web/demo/glass-castle.wav'] + [
                'web/analysis/models/deux/' + name for name in manifest['files']]
            for name in material:
                source = root / name
                require(source.is_file() and source.resolve().is_relative_to(root) and
                        not any(p.is_symlink() for p in (source, *list(source.parents)[:len(Path(name).parts)-1])),
                        'Original material unavailable or symlinked: ' + name)
                target = original / name
                target.parent.mkdir(parents=True, exist_ok=True)
                # Hard links avoid a second 900MB model copy. The original
                # verifier hashes every complete graph and input before admission.
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copyfile(source, target)
        yield helper, original


def rebuild_current_classes(root, original, receipt):
    """Compile actual CURRENT Java bytes, not the copied historical source view."""
    benchmark = load('frozen_replay_compiler', original / 'tools/benchmark_deux_parallel.py')
    benchmark.ROOT = Path(root)
    java, dependencies = benchmark.bounded_toolchain()
    require(benchmark.bounded_runtime_bindings(java, dependencies) == receipt['runtimeBindings'],
            'Current compiler/runtime differs from the immutable experiment')
    java_bindings = {name: checksum for name, checksum in receipt['sourceBindings'].items()
                     if name.endswith('.java')}
    require(java_bindings, 'Original Java source inventory is empty')
    with tempfile.TemporaryDirectory(prefix='lightforge-current-inference-classes-') as temporary:
        classes = benchmark.compile_production(Path(temporary), java, dependencies, java_bindings,
                                                controlled_environment=benchmark.BOUNDED_CHILD_ENV)
        actual = benchmark.portable_class_hashes(classes)
    require(actual == receipt['compiledClassHashes'], 'Fresh CURRENT compiled inference classes differ')
    return actual


def replay(root, *, api=None, output_dir, admission=None, evidence_session=None, rebuild_classes=False):
    root = Path(root).resolve()
    helper = trusted_helper(root)
    api = api or helper.GitHub()
    projection = current_projection(root)
    source_commit, tree_sha = git_identity(root)
    if admission is not None:
        helper.validate_admission(admission, candidate_source_commit=source_commit,
                                  candidate_source_tree_sha=tree_sha, evidence_session=evidence_session)
    with original_source(root, api, include_models=rebuild_classes or admission is not None) as (_, original):
        declaration, receipt, directory, check = helper.fetch_proof(
            original, api=api, admission=admission, output_dir=output_dir)
        require(declaration['producer']['headSha'] == BASE_COMMIT, 'Wrong original producer source')
        if evidence_session is None and admission is None:
            return dict(check, proofDirectory=str(directory), scope=SCOPE,
                        sourceProjection=projection, numericalReplayRequired=True)
        verifier = load('frozen_inference_numerical_replay', original / 'tools/verify_inference_improvement.py')
        reduction = verifier.verify_bounded(Path(directory) / 'receipt.json', root=original)
        classes = (rebuild_current_classes(root, original, receipt) if rebuild_classes
                   else admission['recompiledClassHashes'])
        require(classes == declaration['compiledClassHashes'], 'Current admitted classes differ from original proof')
        require(current_projection(root) == projection, 'Current execution sources changed during replay')
        require(git_identity(root) == (source_commit, tree_sha), 'Candidate Git identity changed during replay')
        require(helper.sha_bytes(helper.read_bytes(Path(directory) / 'receipt.json')) == check['proofReceiptSha256'],
                'Proof receipt changed during replay')
        live = helper.check_online_admission(original, declaration, api=api, purpose='replay', receipt=receipt,
                                             admission=admission, receipt_sha256=check['proofReceiptSha256'])
        old_policy = helper.load_policy(original)
        producer = declaration['producer']
        require(helper.find_proof_artifact(api, old_policy, producer) == check['proofArtifact']['id'],
                'Known proof artifact changed')
        run = helper.check_run(api, old_policy, producer, 'replay')
        metadata = helper.artifact_metadata(api, old_policy, producer, check['proofArtifact']['id'], 'proof', run)
        require(metadata['digest'][7:] == check['proofArtifact']['sha256'], 'Known proof archive changed')
        live.update(proofArtifact=check['proofArtifact'], proofReceiptSha256=check['proofReceiptSha256'])
        sealed = helper.seal_admission(live, receipt, candidate_source_commit=source_commit,
                                       candidate_source_tree_sha=tree_sha, evidence_session=evidence_session,
                                       recompiled_class_hashes=classes)
        require(admission is None or sealed['candidate'] == admission['candidate'], 'Sealed candidate changed')
        return dict(schema=PREREQUISITE_SCHEMA, scope=SCOPE, sourceProjection=projection,
                    admission=sealed, medianWallReductionPercent=reduction,
                    measurementSourceRelease='2.4.2', measurementSourceCommit=BASE_COMMIT,
                    newMeasurementPerformed=False)


def verify_release_admission(root, admission, pipeline, *, api=None, output_dir):
    helper = trusted_helper(root)
    helper.validate_admission(admission, candidate_source_commit=pipeline['head_sha'],
                              candidate_source_tree_sha=pipeline['tree_sha'],
                              evidence_session=pipeline['evidence_session'])
    result = replay(root, api=api, output_dir=output_dir, admission=admission,
                    evidence_session=pipeline['evidence_session'])
    return dict(admission=admission, median_wall_reduction_percent=result['medianWallReductionPercent'],
                scope=SCOPE, measurement_source_release='2.4.2', current_release=TARGET['name'],
                replay_policy_sha256=result['sourceProjection']['replayPolicySha256'])


def validate_prerequisite(value, root):
    require(set(value) == {'schema', 'scope', 'sourceProjection', 'admission',
                          'medianWallReductionPercent', 'measurementSourceRelease',
                          'measurementSourceCommit', 'newMeasurementPerformed'} and
            value['schema'] == PREREQUISITE_SCHEMA and value['scope'] == SCOPE and
            value['sourceProjection'] == current_projection(root) and
            value['measurementSourceRelease'] == '2.4.2' and value['measurementSourceCommit'] == BASE_COMMIT and
            value['newMeasurementPerformed'] is False, 'Invalid cross-release prerequisite')
    return value


def verify(root=ROOT, *, output_dir=None):
    helper = trusted_helper(root)
    value = validate_prerequisite(helper.strict_loads(read(root, PREREQUISITE)), root)
    session = os.environ.get('LIGHTFORGE_EVIDENCE_SESSION')
    helper.digest(session, 'fresh evidence session')
    def execute(destination):
        result = replay(root, output_dir=destination, admission=value['admission'],
                        evidence_session=session, rebuild_classes=True)
        require(result['medianWallReductionPercent'] == value['medianWallReductionPercent'],
                'Stored numerical replay result differs')
        return result['medianWallReductionPercent']
    if output_dir is not None:
        return execute(output_dir)
    with tempfile.TemporaryDirectory(prefix='lightforge-build-proof-') as temporary:
        return execute(Path(temporary) / 'proof')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('route', 'replay', 'verify'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--admission-output', type=Path)
    parser.add_argument('--prerequisite-output', type=Path)
    parser.add_argument('--evidence-session')
    args = parser.parse_args()
    try:
        if args.command == 'route':
            current_projection(args.root)
            result = dict(schema='lightforge.host-inference-route.v1', mode='consumer',
                          campaignId=CAMPAIGN, request=None, scope=SCOPE)
        elif args.command == 'verify':
            result = dict(scope=SCOPE, medianWallReductionPercent=verify(args.root, output_dir=args.output_dir),
                          newMeasurementPerformed=False)
        else:
            require(args.output_dir is not None, 'A fresh proof output directory is required')
            sealing = args.admission_output is not None or args.prerequisite_output is not None
            require((not sealing and args.evidence_session is None) or
                    (args.admission_output is not None and args.prerequisite_output is not None
                     and args.evidence_session is not None), 'Fresh admission requires both outputs and session')
            result = replay(args.root, output_dir=args.output_dir, evidence_session=args.evidence_session,
                            rebuild_classes=sealing)
            if sealing:
                helper = trusted_helper(args.root)
                helper.write_json(args.admission_output, result['admission'])
                helper.write_json(args.prerequisite_output, result)
        if args.output is not None:
            trusted_helper(args.root).write_json(args.output, result)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit('Inference replay held: ' + str(error)) from error


if __name__ == '__main__':
    main()
