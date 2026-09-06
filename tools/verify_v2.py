#!/usr/bin/env python3
"""Portable 2.0 regression gate. Historical model evidence stays historical."""
from pathlib import Path
import datetime, hashlib, json, subprocess, sys

ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'version.json').read_text())['name']
OUT=ROOT/('qa/release-'+VERSION)
OUT.mkdir(parents=True,exist_ok=True)
TESTS=['engine.test.cjs','engine-manual.test.cjs','preview-engine.test.cjs','light-planner.test.cjs',
       'movement-planner.test.cjs','composer-1.6.test.cjs','role-composer-1.6.test.cjs',
       'role-reference-composer-1.6.test.cjs','bass-notes.test.cjs','vocal-detail.test.cjs',
       'stem-cache.test.cjs','wav-reader.test.cjs','precision-2.0.test.cjs','migration-2.0.test.cjs','precision-ui-2.0.test.cjs']

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def hashes():
    paths=[ROOT/'version.json',ROOT/'package.json',ROOT/'package-lock.json',ROOT/'build.sh']
    for folder in ['web','android','tools','tests']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.js','.cjs','.mjs','.java','.css','.html','.py','.xml'} and '__pycache__' not in p.parts)
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(set(paths))}

def main():
    receipt={'release':VERSION,'passed':False,'checks':[],'errors':[], 'source_hashes':hashes(),
             'scope':'Node engine/worker/WebCrypto/gzip, real app DOM integration with simulated native and graphics, Python archive tests. Not a visual browser or physical Android/Tesla test.'}
    try:
        result=subprocess.run(['node','--test',*[str(ROOT/'tests'/t) for t in TESTS]],cwd=ROOT,capture_output=True,text=True)
        (OUT/'regression-tests.log').write_text(result.stdout+result.stderr)
        result.check_returncode();receipt['checks'].append('All selected engine, model-component, migration and DOM integration suites passed.')
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],cwd=ROOT,capture_output=True,text=True)
        (OUT/'archive-tests.log').write_text(result.stdout+result.stderr)
        result.check_returncode();receipt['checks'].append('Python APK archive and bounded release packaging regression suites passed.')
        manifest=json.loads((ROOT/'web/analysis/ASSET_MANIFEST.json').read_text())
        for name,expected in manifest.items():
            p=ROOT/'web/analysis'/name
            assert p.stat().st_size==expected['bytes'] and digest(p)==expected['sha256'], 'Changed analysis asset: '+name
        receipt['checks'].append('All 32 analysis files match the preserved 1.6.0 asset manifest byte for byte; model accuracy evidence is retained, not claimed as newly measured.')
        receipt['analysis_manifest_sha256']=digest(ROOT/'web/analysis/ASSET_MANIFEST.json')
        assert receipt['source_hashes']==hashes(),'Sources changed during verification.'
        receipt['passed']=True
    except Exception as error:receipt['errors'].append(str(error))
    receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    (OUT/'regression-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='source_hashes'},indent=2))
    return 0 if receipt['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
