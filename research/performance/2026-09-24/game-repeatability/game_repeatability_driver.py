# Diagnostic driver only. Never grants quality, speed or publication approval.
import hashlib, importlib.machinery, importlib.util, json, os, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.dont_write_bytecode = True

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def write(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)

run = Path(sys.argv[1]).resolve()
config = json.loads((run / 'plan.json').read_text())
repo, toolchain, models, cuda_root = (Path(config[key]).resolve() for key in ('repo','toolchain','models','cudaRoot'))
receipt = dict(schema='lightforge.game-repeatability-screen.v1', status='INCOMPLETE',
    sourceCommit=config['sourceCommit'], matrix=config['matrix'], runs=[], comparisons={},
    measured=False, qualityApproved=False, target75Proven=False, releaseAuthorized=False,
    scope='Six predeclared fresh-JVM diagnostic runs; two separately identified configurations. Not a qualification or timing benchmark.',
    limitations=['Two matching repeats cannot prove universal determinism.',
                'One plain/profiled deterministic run cannot isolate observer causality.',
                'Plain mode has no retained raw tensors.'])
write(run / 'receipt.json', receipt)
try:
    require(config['matrix'] == [dict(label=a, mode=b, deterministicCompute=c) for a,b,c in
        [('A1','captured',False),('B1','captured',True),('A2','captured',False),
         ('B2','captured',True),('Bplain','plain',True),('Bprofiled','profiled',True)]], 'Unexpected matrix')
    require(subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'], text=True).strip() == config['sourceCommit'], 'Wrong source checkout')
    require(subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD^{tree}'], text=True).strip() == config['sourceTree'], 'Wrong source tree')
    require(not subprocess.check_output(['git','-C',str(repo),'status','--porcelain','--untracked-files=no'], text=True).strip(), 'Source checkout changed')
    for name,pin in config['parentArtifactPins'].items():
        require(sha(run / name) == pin, 'Parent evidence differs: ' + name)
    parent = json.loads((run / 'parent-qualification-receipt.json').read_text())
    setup = json.loads((run / 'setup-receipt.json').read_text())
    require(parent['status'] == 'OBSERVER_COMPARISON_INVALID' and parent['inputsRecheckedAfterQualification'] is True and parent['cudaHeavyOnly'] is True, 'Wrong parent diagnostic')
    python_sources = {}
    for relative,pin in parent['sourceHashes'].items():
        path = repo / relative
        require(path.is_file() and not path.is_symlink() and sha(path) == pin, 'Source binding differs: ' + relative)
        if path.suffix == '.py':
            python_sources[path.resolve()] = path.read_bytes()
    original_spec = importlib.util.spec_from_file_location
    class BoundLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return compile(python_sources[Path(self.path).resolve()], self.path, 'exec', dont_inherit=True)
    def pinned_spec(name, location=None, *, loader=None, submodule_search_locations=None):
        path = Path(location).resolve()
        require(path in python_sources and loader is None and submodule_search_locations is None, 'Unbound dynamic import')
        return original_spec(name, str(path), loader=BoundLoader(name, str(path)))
    importlib.util.spec_from_file_location = pinned_spec
    try:
        spec = pinned_spec('frozen_game', repo / 'tools/benchmark_game_accelerator.py')
        h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
    finally:
        importlib.util.spec_from_file_location = original_spec
    require(sha(repo / 'tools/benchmark_game_accelerator.py') == config['harnessSha256'], 'Wrong harness')
    pcm, provenance_file = run / 'public-demo-mixture-first14s.f32', run / 'input-provenance.json'
    provenance = h.validate_input(pcm, provenance_file)
    require(provenance == parent['inputProvenance'], 'Input provenance changed')
    manifest = h.verify_models(models)
    native = json.loads((repo / 'android/native-runtime.json').read_text())
    host, gpu = toolchain / 'onnx' / native['host']['name'], toolchain / 'onnx' / h.accel.GPU_RUNTIME['name']
    h.accel.verify_runtime(host, native['host']); h.accel.verify_runtime(gpu, h.accel.GPU_RUNTIME)
    shared = [toolchain / 'test-json.jar', toolchain / 'android-sdk/platforms/android-35/android.jar']
    dependencies = shared + [gpu]
    for path in shared + [host,gpu]:
        require(path.is_file() and not path.is_symlink() and sha(path) == parent['dependencyHashes'][path.name], 'Runtime dependency changed')
    require(not any(os.environ.get(key) for key in ('JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS')), 'Injected Java options')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8' and os.environ.get('NVIDIA_TF32_OVERRIDE') == '0', 'Numeric environment changed')
    hashes = {path:sha(path) for path in [*(repo / key for key in parent['sourceHashes']), pcm, provenance_file,
              models / 'manifest.json', *(models / key for key in manifest['files']), *shared, host, gpu]}
    for name,pin in config['parentArtifactPins'].items():
        hashes[run / name] = pin
    for path in (run / 'plan.json', Path(__file__).resolve()):
        hashes[path] = sha(path)
    for relative,pin in setup['extractedNativeLibraries'].items():
        path = cuda_root / relative
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256'], 'Extracted native library changed')
        hashes[path] = pin['sha256']
    for name,pin in parent['gpuNativeLibraries'].items():
        path=Path(name)
        require(path.is_file() and path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256'], 'Previously mapped native library changed')
        hashes[path] = pin['sha256']
    java = toolchain / 'jdk17/bin'
    h.accel.verify_java_api(java, gpu)
    api = subprocess.run([str(java/'javap'),'-public','-classpath',str(gpu),'ai.onnxruntime.OrtSession$SessionOptions'], capture_output=True,text=True,timeout=60,check=True)
    (run / 'deterministic-api.txt').write_text(api.stdout + api.stderr)
    require('public void setDeterministicCompute(boolean) throws ai.onnxruntime.OrtException;' in api.stdout, 'Pinned runtime API unavailable')
    receipt['runtimeProbe'] = h.accel.probe_runtime(java, dependencies, run / 'gpu-runtime-probe', True)
    receipt['gpuInventory'] = h.accel.gpu_inventory()
    receipt['sourceHashes'] = parent['sourceHashes']; receipt['dependencyHashes'] = parent['dependencyHashes']
    receipt['requestedGraphProviders'] = h.requested_graph_providers('cuda_basic', True)
    receipt['inputProvenance'] = provenance; receipt['modelHashes'] = parent['modelHashes']
    receipt['cudaOptions'] = h.accel.CUDA_OPTIONS
    receipt['numericEnvironment'] = dict(CUBLAS_WORKSPACE_CONFIG=':4096:8', NVIDIA_TF32_OVERRIDE='0')
    baseline = h.variant_source(h.SOURCE.read_text(), 'cuda_basic', True)
    anchor = '                            options.addCUDA(cuda);'
    require(baseline.count(anchor) == 1 and 'setDeterministicCompute(' not in baseline, 'Deterministic option anchor differs')
    deterministic = baseline.replace(anchor, anchor.replace('options.addCUDA(cuda);','options.setDeterministicCompute(true);') + '\n' + anchor)
    (run / 'default-source.java').write_text(baseline)
    (run / 'deterministic-source.java').write_text(deterministic)
    for path in (run / 'default-source.java', run / 'deterministic-source.java'):
        hashes[path] = sha(path)
    receipt['sourceDelta'] = dict(defaultSha256=sha(run/'default-source.java'), deterministicSha256=sha(run/'deterministic-source.java'),
        exactChange='Insert options.setDeterministicCompute(true) immediately before options.addCUDA(cuda) inside the existing heavy-graph selector; all other source bytes unchanged.')
    receipt['bindingsBefore'] = {str(path):dict(bytes=path.stat().st_size,sha256=digest) for path,digest in hashes.items()}
    args = SimpleNamespace(models=models,input=pcm,output=run,input_provenance=provenance_file,toolchain=toolchain)
    actual = {}
    write(run/'receipt.json',receipt)
    for arm in config['matrix']:
        label, mode = arm['label'], arm['mode']
        directory, traces = run / label, run / (label + '_traces')
        source = deterministic if arm['deterministicCompute'] else baseline
        if mode == 'profiled':
            traces.mkdir()
        if mode != 'plain':
            source = h.observed_source(source, traces if mode == 'profiled' else None)
        print('Starting',label,mode,'deterministic requested:',arm['deterministicCompute'],flush=True)
        classes, artifacts = h.compile_snapshot(directory, source, java, dependencies)
        for path in artifacts:
            hashes[path] = sha(path)
        row, actual[label] = h.run_once('cuda_basic',mode,directory,classes,java,dependencies,args,provenance,manifest)
        row.update(label=label,deterministicCompute=arm['deterministicCompute'],snapshotSha256=sha(directory/'NativeGame.java'))
        receipt['runs'].append(row)
        for path in (directory/'output').iterdir():
            require(path.is_file() and not path.is_symlink(), 'Unexpected output file'); hashes[path]=sha(path)
        if mode == 'profiled':
            summary = h.summarize_traces(traces)
            receipt['providerTraces'] = summary
            receipt['placement'] = h.validate_placement(summary,'cuda_basic',True)
            for path in traces.iterdir(): hashes[path]=sha(path)
            maps=directory/'cuda-jvm-loaded-library-maps.txt'; hashes[maps]=sha(maps)
            libraries=h.accel.native_library_paths(maps)
            observed={str(path):dict(bytes=path.stat().st_size,sha256=sha(path)) for path in libraries}
            for path in libraries:
                key=str(path)
                if path.is_relative_to(cuda_root):
                    pin=setup['extractedNativeLibraries'][str(path.relative_to(cuda_root))]
                else:
                    require(key in parent['gpuNativeLibraries'],'Unexpected external native library')
                    pin=parent['gpuNativeLibraries'][key]
                require(observed[key] == pin,'Mapped native library differs');hashes[path]=pin['sha256']
            receipt['gpuNativeLibraries']=observed
            receipt['gpuNativeLibraryVersions']=h.accel.native_library_versions(libraries)
            require(receipt['gpuNativeLibraryVersions']==parent['gpuNativeLibraryVersions'],'Mapped native runtime versions changed')
        write(run/'receipt.json',receipt)
    for name,left,right in [('defaultCapturedRepeat','A1','A2'),('deterministicCapturedRepeat','B1','B2'),
                            ('deterministicCaptureProfile','B1','Bprofiled'),('configurationDifference','A1','B1')]:
        receipt['comparisons'][name]=h.comparator.compare(run/left/'output',run/right/'output')
    a,b=actual['Bplain']['notes'],actual['B1']['notes']
    receipt['comparisons']['deterministicPlainCapture']=dict(unroundedNotesIdentical=a==b,leftNoteCount=len(a),rightNoteCount=len(b),
        boundariesIdentical=len(a)==len(b) and all(x['start']==y['start'] and x['end']==y['end'] for x,y in zip(a,b)),
        maxPitchDifferenceMidi=max((abs(x['midi']-y['midi']) for x,y in zip(a,b)),default=0) if len(a)==len(b) else None,
        leftNotes=a,rightNotes=b,rawTensorsUnobservedInPlain=True)
    for path,pin in hashes.items():
        require(path.is_file() and sha(path)==pin,'Bound file changed after screening: '+str(path))
    receipt['bindingsRecheckedAfterScreen']=True
    receipt['defaultCapturedRepeatExact']=receipt['comparisons']['defaultCapturedRepeat']['exactParity']
    receipt['deterministicScreenStable']=all(receipt['comparisons'][name]['exactParity'] for name in
        ('deterministicCapturedRepeat','deterministicCaptureProfile')) and receipt['comparisons']['deterministicPlainCapture']['unroundedNotesIdentical']
    receipt['nextFullQualificationCandidate']=receipt['deterministicScreenStable']
    receipt['artifactHashes']={str(path.relative_to(run)):sha(path) for path in run.rglob('*')
        if path.is_file() and not path.is_symlink() and path not in (run/'receipt.json',run/'driver.log')}
    receipt['status']='REPEATABILITY_SCREEN_COMPLETE'
    write(run/'receipt.json',receipt)
    print(json.dumps({key:receipt[key] for key in ('status','defaultCapturedRepeatExact','deterministicScreenStable',
          'qualityApproved','target75Proven','releaseAuthorized')},indent=2),flush=True)
except BaseException as error:
    receipt.update(status='SCREEN_BLOCKED_OR_INTERRUPTED',failure=type(error).__name__+': '+str(error))
    write(run/'receipt.json',receipt)
    raise
