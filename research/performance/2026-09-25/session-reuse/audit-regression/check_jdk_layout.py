#!/usr/bin/env python3
"""Exercise the corrected JDK evidence gate using copies of actual public inputs.

No inference, native execution, models, runtime binaries or original evidence
are modified. The original complete inventory must remain byte-identical.
"""
import argparse
import copy
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

VERIFIER = 'tools/game_benchmark/verify_session_reuse_evidence.py'
CORRECT = 'lib/libjli.so'
INCORRECT = 'lib/jli/libjli.so'
REJECTION = 'Essential JDK runtime libraries unbound'
INPUTS = ('runtime-input-bindings.json', 'host-preparation-receipt.json',
          'input-provenance.json', 'input-source-proof.json', 'public-demo-mixture-full64s.f32')


def pin(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Expected a regular file: ' + str(path))
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def inventory_pin(inventory):
    data = json.dumps(inventory, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return dict(files=len(inventory), bytes=sum(p['bytes'] for p in inventory.values()),
                canonicalInventorySha256=hashlib.sha256(data).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo, run, output = args.repo.resolve(), args.run.resolve(), args.output.absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(run):
        raise ValueError('Use a new output outside original evidence.')
    verifier_path = repo / VERIFIER
    verifier_pin = pin(verifier_path)
    spec = importlib.util.spec_from_file_location('verified_jdk_layout_regression', verifier_path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    before = verifier.tree_inventory(run)
    tree = subprocess.check_output(['git', 'rev-parse', args.source_commit + '^{tree}'], cwd=repo, text=True).strip()
    source, sources = verifier.verify_sources(run, repo, args.source_commit)
    archived_verifier = (source / VERIFIER).read_text()
    if archived_verifier.count("'" + INCORRECT + "'") != 1:
        raise ValueError('Expected the recorded single original JDK-path defect.')
    corrected = archived_verifier.replace("'" + INCORRECT + "'", "'" + CORRECT + "'")
    if verifier_path.read_text() != corrected:
        raise ValueError('This regression expects only the reviewed one-line verifier correction.')
    driver = verifier.strict_json(run / 'driver-receipt.json')
    if driver['status'] != 'COMPLETE_DIAGNOSTIC' or driver['executionSourceCommit'] != args.source_commit or driver['executionSourceTree'] != tree:
        raise ValueError('Expected completed source-bound original evidence.')
    bindings = verifier.strict_json(run / 'runtime-input-bindings.json')
    if CORRECT not in bindings['jdk'] or INCORRECT in bindings['jdk']:
        raise ValueError('Actual prepared archive layout is not the expected original layout.')
    report = dict(schema='lightforge.game-session-reuse-jdk-gate-regression.v1',
        createdUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status='INCOMPLETE', executionSourceCommit=args.source_commit, executionSourceTree=tree,
        verifier=verifier_pin, archivedVerifier=pin(source / VERIFIER),
        regressionScript=pin(Path(__file__)), originalDriverReceipt=pin(run / 'driver-receipt.json'),
        originalRuntimeBindings=pin(run / 'runtime-input-bindings.json'),
        originalPreparationReceipt=pin(run / 'host-preparation-receipt.json'),
        originalEvidenceBefore=inventory_pin(before), executionSourceInventory=inventory_pin(sources),
        actualOriginalJdkMember=dict(path=CORRECT, **bindings['jdk'][CORRECT]),
        mutationsOnlyInTemporaryCopies=True, modelInferenceExecuted=False, nativeExecutionPerformed=False,
        modelBytesCopied=False, runtimeBytesCopied=False, qualityApproved=False,
        target75Proven=False, benchmarkTimingAdmitted=False, releaseAuthorized=False, cases=[])
    try:
        with tempfile.TemporaryDirectory(prefix='lightforge-jdk-gate-regression-', dir=run.parent) as temporary:
            copied = Path(temporary)
            for name in INPUTS:
                shutil.copyfile(run / name, copied / name)
            shutil.copytree(source, copied / 'execution-source')
            verifier.verify_inputs_before_import(copied, copied / 'execution-source', repo, args.source_commit, tree)
            report['positiveOriginalInputsAccepted'] = True
            for name, move_old in (('missing_original_jli_member', False), ('misplaced_legacy_jli_member', True)):
                changed = copy.deepcopy(bindings)
                removed = changed['jdk'].pop(CORRECT)
                if move_old:
                    changed['jdk'][INCORRECT] = removed
                changed_path = copied / 'runtime-input-bindings.json'
                changed_path.write_text(json.dumps(changed, indent=2, allow_nan=False) + '\n')
                try:
                    verifier.verify_inputs_before_import(copied, copied / 'execution-source', repo, args.source_commit, tree)
                except ValueError as error:
                    if str(error) != REJECTION:
                        raise AssertionError('Rejected for an unexpected reason: ' + str(error)) from error
                    report['cases'].append(dict(name=name, rejected=True, rejection=str(error),
                        mutatedBindings=pin(changed_path), removedMember=CORRECT,
                        misplacedMember=INCORRECT if move_old else None))
                else:
                    raise AssertionError('Mutation was incorrectly admitted: ' + name)
        report['status'] = 'REGRESSION_PASSED'
    finally:
        after = verifier.tree_inventory(run)
        report['originalEvidenceAfter'] = inventory_pin(after)
        report['originalEvidenceUnchanged'] = before == after
        report['verifierUnchanged'] = pin(verifier_path) == verifier_pin
        if not report['originalEvidenceUnchanged'] or not report['verifierUnchanged']:
            report['status'] = 'FAILED_SOURCE_OR_EVIDENCE_CHANGED'
        with output.open('x') as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write('\n')
    if report['status'] != 'REGRESSION_PASSED':
        raise AssertionError(report['status'])
    print(json.dumps(dict(status=report['status'], negativeCases=len(report['cases']),
        originalEvidenceUnchanged=report['originalEvidenceUnchanged'], report=pin(output))))


if __name__ == '__main__':
    main()
