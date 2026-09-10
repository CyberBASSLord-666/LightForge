#!/usr/bin/env python3
"""Portable production regression gate. Historical model evidence stays historical."""
from pathlib import Path
import datetime, hashlib, json, subprocess, sys
from verify_analysis_assets import verify as verify_assets

ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'version.json').read_text())['name']
OUT=ROOT/('qa/release-'+VERSION)
OUT.mkdir(parents=True,exist_ok=True)
TESTS=['engine.test.cjs','engine-manual.test.cjs','preview-engine.test.cjs','preview-lifecycle.test.cjs','light-planner.test.cjs','collision-resolver.test.cjs',
       'movement-planner.test.cjs','composer-1.6.test.cjs','role-composer-1.6.test.cjs',
       'role-reference-composer-1.6.test.cjs','bass-notes.test.cjs','vocal-detail.test.cjs',
       'stem-cache.test.cjs','wav-reader.test.cjs','precision-2.0.test.cjs','migration-2.0.test.cjs','precision-ui-2.0.test.cjs','cockpit-2.1.test.cjs','game-2.1.test.cjs','background-2.2.test.cjs','deux-2.2.1.test.cjs','analysis-recovery-2.2.1.test.cjs','native-deux-bridge.test.cjs','native-mdx-bridge.test.cjs','mdx-downstream-compare.test.cjs','separator-mdx-runtime.test.cjs','native-runtime-guard.test.cjs','diagnostics.test.cjs','analysis-telemetry.test.cjs','analysis-scheduler.test.cjs','semantic-timeline.test.cjs']
# The 2.2.2 adapter-retention test is intentionally historical: its contract
# rejects any later analysis-manifest transition. Keep it runnable directly,
# but do not let a new release fail the current regression gate by design.
PYTHON_TESTS=sorted(p.stem for p in (ROOT/'tests').glob('test_*.py') if p.stem!='test_analysis_evidence_2_2_2')
# These tools use descriptive hyphenated filenames, so unittest discovery cannot
# import them as modules. Keep their direct execution explicit in the production
# gate: a green quality-gate workflow alone is not release verification.
QUALITY_TOOL_TESTS=[
    'performance-quality-gate.test.py',
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
    'native-mdx-comparison-verification.json',
    'native-mdx-downstream-native.json',
    'native-mdx-downstream-verification.json',
    'native-mdx-downstream-wasm.json',
    'native-recovery-results.json',
    'native-runtime-comparison-verification.json',
    'native-verification.json',
    'regression-verification.json',
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
            result.check_returncode()
    log_path.write_text('\\n'.join(output))

def main():
    receipt={'release':VERSION,'passed':False,'checks':[],'errors':[], 'source_hashes':hashes(),
             'selected_test_suites':{'node':TESTS,'python_archive':PYTHON_TESTS,'python_quality_tools':QUALITY_TOOL_TESTS},
             'scope':'Node engine/worker/WebCrypto/gzip, real app DOM integration with simulated native and graphics, Python archive and quality-tool tests. Not a visual browser or physical Android/Tesla test.'}
    try:
        subprocess.run([sys.executable,str(ROOT/'tools/sync_version.py'),'--check'],check=True)
        result=subprocess.run(['node','--test',*[str(ROOT/'tests'/t) for t in TESTS]],cwd=ROOT,capture_output=True,text=True)
        (OUT/'regression-tests.log').write_text(result.stdout+result.stderr)
        result.check_returncode();receipt['checks'].append('All selected engine, model-component, migration and DOM integration suites passed.')
        result=subprocess.run([sys.executable,'-m','unittest',*[f'tests.{name}' for name in PYTHON_TESTS]],cwd=ROOT,capture_output=True,text=True)
        (OUT/'archive-tests.log').write_text(result.stdout+result.stderr)
        result.check_returncode();receipt['checks'].append('Python APK archive and bounded release packaging regression suites passed.')
        run_python_scripts(QUALITY_TOOL_TESTS,OUT/'quality-tool-tests.log')
        receipt['checks'].append('Performance-quality gate, benchmark contract, locked-runner and differential-analysis suites passed.')
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
