#!/usr/bin/env python3
"""Portable production regression gate. Historical model evidence stays historical."""
from pathlib import Path
import datetime, hashlib, json, re, subprocess, sys
from verify_analysis_assets import verify as verify_assets

ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'version.json').read_text())['name']
OUT=ROOT/('qa/release-'+VERSION)
OUT.mkdir(parents=True,exist_ok=True)
TESTS=['analysis-timing-wiring.test.cjs','compiler-timing.test.cjs','analysis-dsp-timing.test.cjs','wav-reader-timing.test.cjs','runtime-timing-probes.test.cjs','engine.test.cjs','engine-manual.test.cjs','preview-engine.test.cjs','preview-lifecycle.test.cjs','preview-startup.test.cjs','light-planner.test.cjs','recorded-music-fixture-contract.test.cjs','collision-resolver.test.cjs','semantic-collision-allocation.test.cjs','semantic-allocation-integration.test.cjs','analysis-performance-projection.test.cjs','analysis-run-observation.test.cjs',
       'movement-planner.test.cjs','composer-1.6.test.cjs','role-composer-1.6.test.cjs',
       'role-reference-composer-1.6.test.cjs','bass-notes.test.cjs','vocal-detail.test.cjs',
       'stem-cache.test.cjs','stem-routing.test.cjs','stem-routing-worker.test.cjs','rhythm-hierarchy.test.cjs','recurrence-motif.test.cjs','recurrence-worker.test.cjs','motif-evolution-integration.test.cjs','wav-reader.test.cjs','precision-2.0.test.cjs','migration-2.0.test.cjs','precision-ui-2.0.test.cjs','cockpit-2.1.test.cjs','game-2.1.test.cjs','background-2.2.test.cjs','analysis-recovery-2.2.1.test.cjs','native-deux-bridge.test.cjs','native-mdx-bridge.test.cjs','mdx-downstream-compare.test.cjs','separator-mdx-runtime.test.cjs','separator-clock-resilience.test.cjs','native-runtime-guard.test.cjs','diagnostics.test.cjs','analysis-telemetry.test.cjs','resource-diagnostics.test.cjs','resource-diagnostics-wiring.test.cjs','analysis-scheduler.test.cjs','semantic-timeline.test.cjs','vocal-semantics.test.cjs','vocal-choreography.test.cjs','percussion-evidence.test.cjs','music-salience.test.cjs','choreography-quality.test.cjs','perceptual-validation.test.cjs','vehicle-perceptual-integration.test.cjs','semantic-choreography-strategy.test.cjs','analysis-cache-recovery-v3.test.cjs','feature-store-contract.test.cjs','source-reader-reuse-worker.test.cjs',
       # These contracts cover cache-identity isolation, native-to-WASM
       # fallback fencing, and bounded restore preview startup. They have no
       # archive-discovery name, so they remain explicit in the release gate.
       'execution-lineage-contract.test.cjs','analyzer-native-retry.test.cjs',
       'native-fallback-fence.test.cjs','native-mdx-fence.test.cjs',
       'completed-restore-preview-start.test.cjs','preview-environment.test.cjs',
       'musical-structure.test.cjs','musical-expression.test.cjs',
       'native-game-bridge.test.cjs','native-game-service-contract.test.cjs','native-game-pipeline.test.cjs','native-game-runner.test.cjs']
# The 2.2.2 adapter-retention contract freezes its then-current analysis
# manifest, and the 2.2.3 native/runtime source-clock contract freezes its
# measured source hashes. Both intentionally reject later release transitions.
# Keep these two contracts runnable directly, but do not let a new release fail
# the current regression gate by design.
HISTORICAL_PYTHON_TESTS=frozenset({
    'test_analysis_evidence_2_2_2',
    'test_analysis_evidence_2_2_3',
})
PYTHON_TESTS=sorted(
    p.stem for p in (ROOT/'tests').glob('test_*.py')
    if p.stem not in HISTORICAL_PYTHON_TESTS
)
# These tools use descriptive hyphenated filenames, so unittest discovery cannot
# import them as modules. Keep their direct execution explicit in the production
# gate: a green quality-gate workflow alone is not release verification.
QUALITY_TOOL_TESTS=[
    'performance-quality-gate.test.py',
    'performance-quality-gate-workflow.test.py',
    'analysis-benchmark-contract.test.py',
    'locked-benchmark-runner.test.py',
    'differential-analysis.test.py',
]

# Node and native regression suites deliberately emit these current-release
# receipts while they run. They are diagnostics uploaded by CI, not source
# inputs or golden references. Keep this small explicit allowlist: any other
# source mutation still fails closed and reports the exact paths.
GENERATED_RUNTIME_REPORTS=frozenset({
    'analysis-browser-verification.json',
    'analysis-verification.json',
    'background-ui-verification.json',
    'browser-verification.json',
    'composer-verification.json',
    'light-verification.json',
    'movement-verification.json',
    'native-inference-profile-equivalence.json',
    'native-mdx-comparison-verification.json',
    'native-mdx-downstream-native.json',
    'native-mdx-downstream-verification.json',
    'native-mdx-downstream-wasm.json',
    'native-recovery-results.json',
    'native-runtime-comparison-verification.json',
    'native-verification.json',
    'native-game-verification.json',
    'native-game-demo-output.json',
    'native-game-falcon-output.json',
    'regression-verification.json',
    'restore-preview-verification.json',
    'role-composer-verification.json',
    'role-reference-composer-verification.json',
    'source-clock-verification.json',
})

def is_generated_runtime_report(path):
    try:
        relative=path.relative_to(OUT)
    except ValueError:
        return False
    return len(relative.parts)==1 and relative.name in GENERATED_RUNTIME_REPORTS

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def hashes():
    paths=[ROOT/'version.json',ROOT/'package.json',ROOT/'package-lock.json',ROOT/'build.sh',ROOT/'android/native-runtime.json',ROOT/'qa/release-1.6.0/prepare-musdb-fixtures.py']
    for folder, suffixes in {
        'web': {'.js','.cjs','.mjs','.java','.css','.html','.py','.xml'},
        'android': {'.js','.cjs','.mjs','.java','.css','.html','.py','.xml'},
        'tools': {'.js','.cjs','.mjs','.java','.css','.html','.py','.xml'},
        'tests': {'.js','.cjs','.mjs','.java','.css','.html','.py','.xml'},
        'qa': {'.json','.py'},
        '.github/workflows': {'.yml','.yaml'},
    }.items():
        paths.extend(
            p for p in (ROOT/folder).rglob('*')
            if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts
            and not is_generated_runtime_report(p)
        )
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(set(paths))}

def node_failure_summary(output, limit=12):
    """Return bounded trusted TAP labels with their first failure detail."""
    if not isinstance(output, str):
        return 'no TAP failure marker captured'
    lines=output.splitlines()
    markers=[]
    for index, raw in enumerate(lines):
        line=raw.strip()
        if not line.startswith('not ok '):
            continue
        detail=''
        for detail_index in range(index+1, min(len(lines), index+18)):
            text=lines[detail_index].strip()
            if text.startswith('not ok '):
                break
            if text.startswith('error:'):
                detail=text[len('error:'):].strip()
                if detail in {'', '|', '|-', '>', '>-'}:
                    for continuation in lines[detail_index+1:min(len(lines), detail_index+7)]:
                        text=continuation.strip()
                        if text and text not in {'---', '...'} and not text.startswith(('duration_', 'type:', 'location:', 'failureType:', 'code:')):
                            detail=text
                            break
                break
        markers.append((line+(' ['+detail+']' if detail else ''))[:240])
    if not markers:
        return 'no TAP failure marker captured'
    if limit<=1 or len(markers)<=limit:
        return ' | '.join(markers[:limit])
    return ' | '.join([markers[0],*markers[-(limit-1):]])

# Diagnostics may include a traceback, assertion data, or arbitrary test output.
# Keep only standard unittest result labels, whose grammar is restricted below.
ASCII_IDENTIFIER=re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
UNITTEST_FAILURE_SUMMARY_FIELD=re.compile(r'^[a-z]+(?: [a-z]+)*=\d+$')
ANSI_ESCAPE=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
PYTHON_FAILURE_SUMMARY_MAX_CHARS=1200

def _standard_unittest_label(line):
    for prefix in ('FAIL: ','ERROR: ','UNEXPECTED SUCCESS: '):
        if line.startswith(prefix):
            label=line[len(prefix):]
            test_name,separator,qualified=label.partition(' (')
            if not separator or not qualified.endswith(')') or not ASCII_IDENTIFIER.fullmatch(test_name):
                return False
            parts=qualified[:-1].split('.')
            return len(parts)>=2 and parts[0] in {'tests','__main__'} and all(
                ASCII_IDENTIFIER.fullmatch(part) for part in parts
            )
    return False

def _standard_unittest_summary(line):
    if not line.startswith('FAILED (') or not line.endswith(')'):
        return False
    fields=line[len('FAILED ('):-1].split(', ')
    return bool(fields) and all(UNITTEST_FAILURE_SUMMARY_FIELD.fullmatch(field) for field in fields)

def python_failure_summary(output, limit=12):
    """Return bounded standard unittest labels without exposing test output."""
    empty='no unittest failure marker captured'
    if not isinstance(output, str) or type(limit) is not int or limit<=0:
        return empty
    markers=[]
    for raw in output.splitlines():
        line=ANSI_ESCAPE.sub('', raw)
        if _standard_unittest_label(line) or _standard_unittest_summary(line):
            markers.append(line[:240])
    if not markers:
        return empty
    selected=markers if len(markers)<=limit else [markers[0],*markers[-(limit-1):]]
    result=[]
    size=0
    for marker in selected:
        addition=len(marker)+(3 if result else 0)
        if size+addition>PYTHON_FAILURE_SUMMARY_MAX_CHARS:
            if not result:
                return marker[:PYTHON_FAILURE_SUMMARY_MAX_CHARS]
            break
        result.append(marker)
        size+=addition
    return ' | '.join(result) or empty

def run_python_scripts(scripts, log_path):
    output=[]
    for script in scripts:
        path=ROOT/'tests'/script
        if not path.is_file():
            raise FileNotFoundError(f'production verification suite is missing: {path}')
        result=subprocess.run([sys.executable,str(path)],cwd=ROOT,capture_output=True,text=True)
        output.append(f'$ {sys.executable} {path.relative_to(ROOT)}\\n{result.stdout}{result.stderr}')
        if result.returncode:
            log_path.write_text('\\n'.join(output))
            raise RuntimeError('Python quality-tool regression failed: '+python_failure_summary(output[-1]))
    log_path.write_text('\\n'.join(output))

def main():
    receipt={'release':VERSION,'passed':False,'checks':[],'errors':[], 'source_hashes':hashes(),
             'selected_test_suites':{'node':TESTS,'python_archive':PYTHON_TESTS,'python_quality_tools':QUALITY_TOOL_TESTS},
             'scope':'Node engine/worker/WebCrypto/gzip, real app DOM integration with simulated native and graphics, Python archive and quality-tool tests. Not a visual browser or physical Android/Tesla test.'}
    try:
        subprocess.run([sys.executable,str(ROOT/'tools/sync_version.py'),'--check'],check=True)
        result=subprocess.run(['node','--test',*[str(ROOT/'tests'/t) for t in TESTS]],cwd=ROOT,capture_output=True,text=True)
        node_output=result.stdout+result.stderr
        (OUT/'regression-tests.log').write_text(node_output)
        if result.returncode:
            raise RuntimeError('Node production regression failed: '+node_failure_summary(node_output))
        receipt['checks'].append('All selected engine, model-component, migration and DOM integration suites passed.')
        result=subprocess.run([sys.executable,'-m','unittest',*[f'tests.{name}' for name in PYTHON_TESTS]],cwd=ROOT,capture_output=True,text=True)
        archive_output=result.stdout+result.stderr
        (OUT/'archive-tests.log').write_text(archive_output)
        if result.returncode:
            raise RuntimeError('Python archive and release regression failed: '+python_failure_summary(archive_output))
        receipt['checks'].append('Python APK archive and bounded release packaging regression suites passed.')
        run_python_scripts(QUALITY_TOOL_TESTS,OUT/'quality-tool-tests.log')
        receipt['checks'].append('Performance-quality gate/workflow, benchmark contract, locked-runner and differential-analysis suites passed.')
        verify_assets()
        receipt['checks'].append('Every bundled analysis asset matches the current manifest; actual model quality and runtime are checked separately.')
        receipt['analysis_manifest_sha256']=digest(ROOT/'web/analysis/ASSET_MANIFEST.json')
        source_after=hashes()
        changed=sorted(path for path in set(receipt['source_hashes'])|set(source_after) if receipt['source_hashes'].get(path)!=source_after.get(path))
        assert not changed,'Sources changed during verification: '+', '.join(changed)
        receipt['passed']=True
    except Exception as error:receipt['errors'].append(str(error))
    receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (OUT/'regression-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='source_hashes'},indent=2))
    return 0 if receipt['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
