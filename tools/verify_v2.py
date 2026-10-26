#!/usr/bin/env python3
"""Portable production regression gate. Historical model evidence stays historical."""
from pathlib import Path
import datetime, hashlib, json, os, re, subprocess, sys
from verify_analysis_assets import verify as verify_assets

ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'version.json').read_text())['name']
OUT=ROOT/('qa/release-'+VERSION)
OUT.mkdir(parents=True,exist_ok=True)
TESTS=['web-interaction-reliability.test.cjs','browser-transfer-lifecycle.test.cjs','analysis-timing-wiring.test.cjs','compiler-timing.test.cjs','analysis-dsp-timing.test.cjs','wav-reader-timing.test.cjs','wav-reader-integrity.test.cjs','wav-reader-pcm-fastpath.test.cjs','frontend-routing.test.cjs','runtime-timing-probes.test.cjs','engine.test.cjs','engine-manual.test.cjs','preview-engine.test.cjs','preview-lifecycle.test.cjs','preview-startup.test.cjs','light-planner.test.cjs','recorded-music-fixture-contract.test.cjs','collision-resolver.test.cjs','semantic-collision-allocation.test.cjs','semantic-allocation-integration.test.cjs','analysis-performance-projection.test.cjs','analysis-run-observation.test.cjs',
       'movement-planner.test.cjs','composer-1.6.test.cjs','role-composer-1.6.test.cjs',
       'role-reference-composer-1.6.test.cjs','bass-notes.test.cjs','vocal-detail.test.cjs',
       'stem-cache.test.cjs','stem-routing.test.cjs','stem-routing-worker.test.cjs','rhythm-hierarchy.test.cjs','recurrence-motif.test.cjs','recurrence-worker.test.cjs','motif-evolution-integration.test.cjs','wav-reader.test.cjs','precision-2.0.test.cjs','migration-2.0.test.cjs','precision-ui-2.0.test.cjs','cockpit-2.1.test.cjs','music-insights-resize.test.cjs','game-2.1.test.cjs','background-2.2.test.cjs','analysis-recovery-2.2.1.test.cjs','native-deux-bridge.test.cjs','native-mdx-bridge.test.cjs','mdx-downstream-compare.test.cjs','separator-mdx-runtime.test.cjs','separator-clock-resilience.test.cjs','native-runtime-guard.test.cjs','diagnostics.test.cjs','browser-diagnostic-capture.test.cjs','analysis-telemetry.test.cjs','resource-diagnostics.test.cjs','resource-diagnostics-wiring.test.cjs','analysis-scheduler.test.cjs','semantic-timeline.test.cjs','vocal-semantics.test.cjs','vocal-choreography.test.cjs','percussion-evidence.test.cjs','music-salience.test.cjs','choreography-quality.test.cjs','perceptual-validation.test.cjs','vehicle-perceptual-integration.test.cjs','semantic-choreography-strategy.test.cjs','analysis-cache-recovery-v3.test.cjs','feature-store-contract.test.cjs','source-reader-reuse-worker.test.cjs',
       # These contracts cover cache-identity isolation, native-to-WASM
       # fallback fencing, and bounded restore preview startup. They have no
       # archive-discovery name, so they remain explicit in the release gate.
       'execution-lineage-contract.test.cjs','analyzer-native-retry.test.cjs',
       'native-fallback-fence.test.cjs','native-mdx-fence.test.cjs',
       'completed-restore-preview-start.test.cjs','preview-environment.test.cjs',
       'musical-structure.test.cjs','musical-expression.test.cjs',
       'native-game-bridge.test.cjs','native-game-service-contract.test.cjs','native-game-pipeline.test.cjs','native-game-batch.test.cjs','native-game-runner.test.cjs',
       'musical-scheduling.test.cjs','quality-run-scanning.test.cjs','vocal-frontend-reuse.test.cjs','vocal-resampler-reuse.test.cjs']
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
    'preview-verification.json',
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

REGRESSION_EXTRA_INPUTS=('docs/EXPERIMENTAL_HOST_QUALIFICATION.md',)

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
    paths.extend(ROOT/p for p in REGRESSION_EXTRA_INPUTS)
    paths.extend(p for p in (ROOT/'research/upstream').rglob('*')
                 if p.is_file() and (p.suffix=='.py' or p.name=='requirements.txt'))
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(set(paths))}

def prepare_regression_test_inputs(root=ROOT, *, materialize=True):
    """Restore sparse-omitted test inputs from this HEAD, never reset user edits.

    The security suites scan *all* upstream Python sources (not merely their
    directly imported helpers). Include every tracked Python source and dependency
    manifest, but not unrelated checkpoints/audio. No alternate checkout or network
    source is used. Existing worktree bytes remain the authoritative test inputs.
    """
    root=Path(root).resolve()
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args])
    head=git('rev-parse','HEAD').decode().strip()
    entries={}
    for row in git('ls-tree','-rz',head,'--','research/upstream',*REGRESSION_EXTRA_INPUTS).split(b'\0'):
        if not row:
            continue
        info,raw_path=row.split(b'\t',1)
        path=raw_path.decode()
        if not (path.endswith('.py') or Path(path).name=='requirements.txt' or path in REGRESSION_EXTRA_INPUTS):
            continue
        mode,kind,oid=info.decode().split()
        if kind!='blob' or mode not in {'100644','100755'}:
            raise RuntimeError('Unsafe regression test input in HEAD: '+path)
        entries[path]=(mode,oid)
    index={}
    for row in git('ls-files','--stage','-z','--','research/upstream',*REGRESSION_EXTRA_INPUTS).split(b'\0'):
        if row:
            info,path=row.split(b'\t',1)
            index.setdefault(path.decode(),[]).append(tuple(info.decode().split()))
    skipped={row[2:].decode() for row in git('ls-files','-v','-z','--','research/upstream',*REGRESSION_EXTRA_INPUTS).split(b'\0')
             if row and row[:1].upper()==b'S'}
    def safe_path(relative):
        path=root
        for part in Path(relative).parts:
            path=path/part
            if path.is_symlink():
                raise RuntimeError('Symlink regression test input: '+relative)
        if path.exists() and not path.is_file():
            raise RuntimeError('Non-file regression test input: '+relative)
        return path
    # Validate every target before creating any file. Staged/deleted paths are
    # user intent, not sparse omissions. Do not hide them by checking out HEAD.
    missing=[]
    for relative,(mode,oid) in entries.items():
        path=safe_path(relative)
        if not path.exists():
            if not materialize or relative not in skipped or index.get(relative)!=[(mode,oid,'0')]:
                raise RuntimeError('Missing regression test input is not an unchanged sparse omission: '+relative)
            missing.append(relative)
    for relative in missing:
        mode,oid=entries[relative]
        data=git('cat-file','blob',oid)
        # Descriptor-relative traversal prevents swapped parent symlinks from
        # redirecting writes. Exclusive creation and fchmod never follow a
        # replacement leaf or overwrite a file created after preflight.
        directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            parts=Path(relative).parts
            for part in parts[:-1]:
                try:
                    os.mkdir(part,dir_fd=directory)
                except FileExistsError:
                    pass
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                os.close(directory)
                directory=child
            descriptor=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                               0o600,dir_fd=directory)
            with os.fdopen(descriptor,'wb') as output:
                output.write(data)
                os.fchmod(output.fileno(),0o755 if mode=='100755' else 0o644)
        finally:
            os.close(directory)
    # Record actual tested bytes, including local edits and untracked scan inputs.
    actual=set(entries)
    actual.update(str(p.relative_to(root)) for p in (root/'research/upstream').rglob('*.py'))
    files={}
    for relative in sorted(actual):
        path=safe_path(relative)
        data=path.read_bytes()
        oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        expected=entries.get(relative,(None,None))[1]
        files[relative]={'sha256':hashlib.sha256(data).hexdigest(),
                         'head_blob':expected,'matches_head':oid==expected,
                         'materialized':relative in missing}
    if git('rev-parse','HEAD').decode().strip()!=head:
        raise RuntimeError('HEAD changed while preparing regression test inputs')
    return {'head':head,'files':files}

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
    receipt={'release':VERSION,'passed':False,'checks':[],'errors':[], 'source_hashes':{},
             'selected_test_suites':{'node':TESTS,'python_archive':PYTHON_TESTS,'python_quality_tools':QUALITY_TOOL_TESTS},
             'scope':'Node engine/worker/WebCrypto/gzip, real app DOM integration with simulated native and graphics, Python archive and quality-tool tests. Not a visual browser or physical Android/Tesla test.'}
    try:
        receipt['regression_test_inputs']=prepare_regression_test_inputs()
        receipt['source_hashes']=hashes()
        subprocess.run([sys.executable,str(ROOT/'tools/sync_version.py'),'--check'],check=True)
        result=subprocess.run(['node','--test','--test-reporter=tap',*[str(ROOT/'tests'/t) for t in TESTS]],cwd=ROOT,capture_output=True,text=True)
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
        research_after=prepare_regression_test_inputs(materialize=False)
        if research_after['head']!=receipt['regression_test_inputs']['head'] or {p:v['sha256'] for p,v in receipt['regression_test_inputs']['files'].items()}!={p:v['sha256'] for p,v in research_after['files'].items()}:
            raise RuntimeError('Regression test inputs or HEAD changed during verification')
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
