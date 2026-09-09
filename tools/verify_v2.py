#!/usr/bin/env python3
"""Portable production regression gate. Historical model evidence stays historical."""
from pathlib import Path
import datetime, hashlib, json, subprocess, sys
from verify_analysis_assets import verify as verify_assets

ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'version.json').read_text())['name']
OUT=ROOT/('qa/release-'+VERSION)
OUT.mkdir(parents=True,exist_ok=True)
TESTS=['engine.test.cjs','engine-manual.test.cjs','preview-engine.test.cjs','light-planner.test.cjs',
       'movement-planner.test.cjs','composer-1.6.test.cjs','role-composer-1.6.test.cjs',
       'role-reference-composer-1.6.test.cjs','bass-notes.test.cjs','vocal-detail.test.cjs',
       'stem-cache.test.cjs','wav-reader.test.cjs','precision-2.0.test.cjs','migration-2.0.test.cjs','precision-ui-2.0.test.cjs','cockpit-2.1.test.cjs','game-2.1.test.cjs','background-2.2.test.cjs','deux-2.2.1.test.cjs','analysis-recovery-2.2.1.test.cjs','native-deux-bridge.test.cjs','native-mdx-bridge.test.cjs','separator-mdx-runtime.test.cjs','native-runtime-guard.test.cjs','diagnostics.test.cjs']
# The 2.2.2 adapter-retention test is intentionally historical: its contract
# rejects any later analysis-manifest transition. Keep it runnable directly,
# but do not let a new release fail the current regression gate by design.
PYTHON_TESTS=sorted(p.stem for p in (ROOT/'tests').glob('test_*.py') if p.stem!='test_analysis_evidence_2_2_2')

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def hashes():
    paths=[ROOT/'version.json',ROOT/'package.json',ROOT/'package-lock.json',ROOT/'build.sh',ROOT/'android/native-runtime.json']
    for folder in ['web','android','tools','tests']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.js','.cjs','.mjs','.java','.css','.html','.py','.xml'} and '__pycache__' not in p.parts)
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(set(paths))}

def main():
    receipt={'release':VERSION,'passed':False,'checks':[],'errors':[], 'source_hashes':hashes(),
             'scope':'Node engine/worker/WebCrypto/gzip, real app DOM integration with simulated native and graphics, Python archive tests. Not a visual browser or physical Android/Tesla test.'}
    try:
        subprocess.run([sys.executable,str(ROOT/'tools/sync_version.py'),'--check'],check=True)
        result=subprocess.run(['node','--test',*[str(ROOT/'tests'/t) for t in TESTS]],cwd=ROOT,capture_output=True,text=True)
        (OUT/'regression-tests.log').write_text(result.stdout+result.stderr)
        result.check_returncode();receipt['checks'].append('All selected engine, model-component, migration and DOM integration suites passed.')
        result=subprocess.run([sys.executable,'-m','unittest',*[f'tests.{name}' for name in PYTHON_TESTS]],cwd=ROOT,capture_output=True,text=True)
        (OUT/'archive-tests.log').write_text(result.stdout+result.stderr)
        result.check_returncode();receipt['checks'].append('Python APK archive and bounded release packaging regression suites passed.')
        verify_assets()
        receipt['checks'].append('Every bundled analysis asset matches the current manifest; actual model quality and runtime are checked separately.')
        receipt['analysis_manifest_sha256']=digest(ROOT/'web/analysis/ASSET_MANIFEST.json')
        assert receipt['source_hashes']==hashes(),'Sources changed during verification.'
        receipt['passed']=True
    except Exception as error:receipt['errors'].append(str(error))
    receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (OUT/'regression-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='source_hashes'},indent=2))
    return 0 if receipt['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
