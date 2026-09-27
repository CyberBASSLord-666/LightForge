#!/usr/bin/env python3
"""Read-only Deux diagnostic audit; never executes inference or grants approval."""
import argparse, hashlib, importlib.machinery, importlib.util, json, math, re, shutil, stat, subprocess, sys, zipfile
from pathlib import Path, PurePosixPath
sys.dont_write_bytecode = True
SOURCE = "8590ac4a67de4340857a96ffe38bae53d7d902b8"
TREE = "c841bf18f91d3d04dd6daf7e886e2aa473ab8c70"


def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def blob(repo, name, commit=SOURCE):
    return subprocess.check_output(['git', '-C', str(repo), 'show', commit + ':' + name])

def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result

    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON value')
        return result

    def constant(value):
        raise ValueError('Invalid JSON constant: ' + value)

    require(path.is_file() and not path.is_symlink(), 'Missing regular JSON file: ' + str(path))
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_float=floating, parse_constant=constant)

def safe_relative(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            'Invalid relative path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(part not in ('', '.', '..') for part in value.split('/'))
            and not re.match(r'^[A-Za-z]:', value), 'Unsafe relative path: ' + value)
    return path

def safe_file(root, relative):
    path = root.joinpath(*safe_relative(relative).parts)
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            'Missing/unsafe evidence file: ' + str(relative))
    return path

def extract_verified(args):
    archive = args.zip.resolve()
    require(archive.is_file() and not archive.is_symlink(), 'ZIP must be a regular file')
    require(archive.stat().st_size == args.expected_size, 'ZIP size does not match displayed size')
    actual = sha(archive)
    require(actual == args.expected_sha256, 'ZIP SHA256 does not match displayed digest')
    destination = args.output_dir / 'evidence'
    destination.mkdir()
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        require(0 < len(infos) <= 10000, 'Unexpected ZIP member count')
        seen = set()
        total = 0
        for info in infos:
            name = info.filename[:-1] if info.is_dir() else info.filename
            safe_relative(name)
            require(name not in seen, 'Duplicate ZIP member: ' + name)
            seen.add(name)
            mode = (info.external_attr >> 16) & 0xffff
            kind = stat.S_IFMT(mode)
            require(kind in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG),
                    'Non-regular ZIP member: ' + name)
            require(not (info.flag_bits & 1), 'Encrypted ZIP member: ' + name)
            require(info.file_size >= 0 and info.file_size <= args.max_uncompressed_bytes,
                    'Oversized ZIP member: ' + name)
            total += info.file_size
        require(total <= args.max_uncompressed_bytes, 'ZIP exceeds uncompressed-byte safety limit')
        for info in infos:
            path = destination.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as incoming, path.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            require(path.stat().st_size == info.file_size, 'Extracted member length differs')
        # Reading each complete ZipExtFile above also checks its CRC.
    require(archive.stat().st_size == args.expected_size and sha(archive) == actual,
            'Input ZIP changed during verification')
    return destination, dict(bytes=args.expected_size, sha256=actual,
                             members=len(infos), uncompressedBytes=total, crcChecked=True)

PARENT_SETUP_SHA = 'a92e864c73f5da16c9103291bc6057d73fd80dd1c70773c21220cf82f14b3926'
APK_SHA = 'af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f'
AUDIO_SHA = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
SOURCE_HASHES = {
 'tools/benchmark_deux_accelerator.py': '0c19caa398c6fb1e1be121d359219074e71879979105d4172fbcf360906c9f0a',
 'tools/profile_deux_operators.py': '9a4e189d899a2f5c3c0e92df64ef4e1f3316ef422d53216d92b983e221c235d6',
 'tools/benchmark_deux_execution.py': '2fdeceb1fd4fd275b31338aeff6be6a5e53afb741c15de5dc020f65cbed72f3f',
 'tests/NativeDeuxExecutionBenchmark.java': '70eab8091070904493493bd94e7a6467a031628e0feb432055942cdd1bd1b0bb',
 'android/src/com/cyberbasslord/lightforge/NativeDeux.java': '084fec27d1fad0b10db01a960c614d333bb8c049e712c3fc4524d66e6dc3dd37',
 'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java': '991b06501cfb88b904d0b714a525c389f169f00c231248b0e961b70f257e90b5',
 'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java': 'aa1d6bd370d88a774792cb76b4a18604d3ab2bffba58ab382e9045cad071acc1',
 'android/native-runtime.json': 'e3ea568b3a8485235f23a59cd787466cdcbbfcaa54ac56df3ce040d29fcb2a94',
 'web/analysis/models/deux/manifest.json': '6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9',
}
FLAGS = ('measured','outputBytesQualifiedForTiming','qualityApproved','releaseAuthorized',
         'target75Proven','wholeSongSpeedupProven','androidSpeedupProven')
CLASS_NAMES = {'AppDiagnostics', 'NativeDeux', 'NativeDeux$ExecutionScope', 'NativeDeux$Listener',
 'NativeDeux$Cancellation', 'NativeDeuxTransform', 'NativeDeuxTransform$Check', 'NativeDeuxTransform$FFT',
 'NativeDeuxExecutionBenchmark', 'NativeInferenceProfile', 'NativeInferenceProfile$Timing',
 'NativeInferenceProfile$Measurement', 'NativeInferenceProfile$Snapshot', 'NativeInferenceProfile$Metric',
 'NativeInferenceProfile$Stage', 'NativeInferenceProfile$Graph', 'NativeInferenceProfile$Heap',
 'NativeInferenceProfile$CpuClock', *(f'NativeInferenceProfile${n}' for n in range(1,5))}
CLASS_FILES = {'com/cyberbasslord/lightforge/'+name+'.class' for name in CLASS_NAMES}
STUB = ('package com.cyberbasslord.lightforge; public final class AppDiagnostics {'
        'public static void log(android.content.Context c,String l,String s,String m){}'
        'public static boolean flush(long timeout){return true;}}\n')


def pinned_modules(repo, root):
    tree = subprocess.check_output(['git','-C',str(repo),'rev-parse',SOURCE+'^{tree}'], text=True).strip()
    require(tree == TREE, 'Pinned source tree differs')
    python_sources = {}
    for name, expected in SOURCE_HASHES.items():
        data = blob(repo, name)
        require(hashlib.sha256(data).hexdigest() == expected, 'Git source pin differs: '+name)
        require(sha(safe_file(repo,name)) == expected, 'Local source differs from immutable pin: '+name)
        require(sha(safe_file(root/'bound-source',name)) == expected, 'Retained source differs: '+name)
        if name.endswith('.py'):
            python_sources[(repo/name).resolve()] = data
    class SourceOnly(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return compile(python_sources[Path(self.path).resolve()], self.path, 'exec', dont_inherit=True)
    original = importlib.util.spec_from_file_location
    def spec(name, location=None, *, loader=None, submodule_search_locations=None):
        path = Path(location).resolve()
        require(path in python_sources and loader is None and submodule_search_locations is None,
                'Unexpected comparator import')
        return original(name,str(path),loader=SourceOnly(name,str(path)))
    importlib.util.spec_from_file_location = spec
    try:
        module_spec = spec('verified_deux_accelerator',repo/'tools/benchmark_deux_accelerator.py')
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    finally:
        importlib.util.spec_from_file_location = original
    return module


def verify_bindings(root, receipt, repo, accel):
    setup = strict_json(root/'setup-receipt.json')
    parent_path = root/'parent-game-setup-receipt.json'
    require(sha(parent_path)==PARENT_SETUP_SHA, 'Original setup checksum differs')
    parent = strict_json(parent_path)
    expected_setup = dict(schema='lightforge.deux-continuation-setup.v1',sourceCommit=SOURCE,sourceTree=TREE,
        sourceHashes=SOURCE_HASHES,parentSetupSha256=PARENT_SETUP_SHA,publicApkSha256=APK_SHA,
        publicAudioSha256=AUDIO_SHA,startSample=-66150,samplesPerStem=573300,
        qualityApproved=False,target75Proven=False,releaseAuthorized=False)
    for key,value in expected_setup.items():
        require(setup.get(key)==value,'Setup binding differs: '+key)
    for key in ('cudaWheelPins','extractedNativeLibraries'):
        require(setup[key]==parent[key], 'Reused runtime binding differs: '+key)
    require(len(setup['extractedNativeLibraries'])==20, 'Native extraction inventory differs')
    manifest_name='web/analysis/models/deux/manifest.json'
    manifest=json.loads(blob(repo,manifest_name))
    require(manifest['execution']=='bounded-independent-batches-v1' and manifest['frames']==1301
        and manifest['samples']==573300 and manifest['headFrames']==128, 'Original geometry differs')
    require(set(manifest['files'])=={name+'.onnx' for name in accel.benchmark.GRAPH_NAMES}
        and len(manifest['files'])==27,'Original 27 model inventory differs')
    require(setup['modelHashes']==manifest['files'],'Setup original model pins differ')
    require(setup['modelManifestSha256']==SOURCE_HASHES[manifest_name],'Setup manifest pin differs')
    runtime=json.loads(blob(repo,'android/native-runtime.json'))
    deps={'test-json.jar':'c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6',
          'android.jar':'4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b',
          runtime['host']['name']:runtime['host']['sha256'],accel.GPU_RUNTIME['name']:accel.GPU_RUNTIME['sha256']}
    required = dict(schema='lightforge.deux-accelerator-experiment.v1',audioSha256=AUDIO_SHA,
        audioFrames=2822400,startSample=-66150,samplesPerStem=573300,runtimeVersion='1.25.1',
        cpuRuntime=runtime['host'],gpuRuntime=accel.GPU_RUNTIME,sourceHashes=SOURCE_HASHES,
        dependencyHashes=deps,modelManifestSha256=SOURCE_HASHES[manifest_name],
        modelHashes={name:pin['sha256'] for name,pin in manifest['files'].items()},
        cudaOptions=accel.CUDA_OPTIONS,cublasWorkspaceConfig=':4096:8',nvidiaTf32Override='0',
        requestedCudaLogicalDevice=0,variants=list(accel.VARIANTS),
        deterministicCompute={variant:dict(explicitlyRequested=None,
          note='No setDeterministicCompute override; retains runtime default. CUBLAS workspace configuration does not guarantee all CUDA kernels are deterministic.') for variant in accel.VARIANTS})
    readiness=strict_json(root/'readiness/receipt.json')
    require(readiness['status']=='PREFLIGHT_READY' and not readiness['runs']
        and all(readiness.get(flag) is False for flag in FLAGS),'Readiness did not remain discovery-only')
    for key,value in required.items():
        require(receipt.get(key)==value,'Qualification binding differs: '+key)
        require(readiness.get(key)==value,'Readiness binding differs: '+key)
    env=setup['environment']
    require(env['CUBLAS_WORKSPACE_CONFIG']==':4096:8' and env['NVIDIA_TF32_OVERRIDE']=='0', 'Setup precision environment differs')
    require(receipt['cudaVisibility']=={key:env[key] for key in ('CUDA_VISIBLE_DEVICES','CUDA_DEVICE_ORDER')}
        and readiness['cudaVisibility']==receipt['cudaVisibility'], 'GPU visibility differs')
    for document in (receipt,readiness):
        probes=document['runtimeProbes']
        require(len(probes)==2,'Runtime discovery count differs')
        for i,probe in enumerate(probes):
            require(probe['runtimeVersion']=='1.25.1' and probe['cudaRequested'] is (i==1)
                and probe['cudaKernelExecutionProven'] is False,'Runtime discovery claims differ')
    return setup


def verify_processes(root, receipt):
    records={stage:strict_json(root/(stage+'-process.json')) for stage in ('readiness','qualification')}
    for stage,record in records.items():
        expected_status='PREFLIGHT_READY' if stage=='readiness' else receipt['status']
        expected_code=0 if stage=='readiness' else 1
        require(record['status']=='PROCESS_EXITED' and record['returnCode']==expected_code
            and record['receiptStatus']==expected_status,'Process completion disagrees: '+stage)
        require(type(record['pid']) is int and record['pid']>0 and record['processGroup']==record['pid'],
            'Invalid process group record')
        args=record['arguments']
        require(len(args)==(13 if stage=='readiness' else 12),'Unexpected process arguments')
        require(Path(args[1]).name=='benchmark_deux_accelerator.py' and args[2]=='--toolchain'
            and args[4]=='--models' and args[6]=='--audio' and args[8:11]==['--start-sample','-66150','--output']
            and Path(args[11]).parts[-2:]==(root.name,stage),'Process argument binding differs')
        if stage=='readiness': require(args[12]=='--check-readiness','Readiness flag missing')
        require(safe_file(root,stage+'.log').stat().st_size>0,'Missing final process log')
    require(records['readiness']['arguments'][:10]==records['qualification']['arguments'][:10],
        'Readiness and qualification used different inputs')
    return records


def verify_snapshots(evidence,receipt,accel,repo):
    bound=receipt['compiledSnapshotHashes']
    require(isinstance(bound,dict) and bound,'Missing compiled snapshot hashes')
    for name,digest in bound.items():
        require(sha(safe_file(evidence,name))==digest,'Compiled artifact hash differs: '+name)
    expected_bound={'cuda-jvm-loaded-library-maps.txt'}
    source=blob(repo,'android/src/com/cyberbasslord/lightforge/NativeDeux.java').decode()
    original_roots=set()
    expected_names={name+suffix for name in accel.VARIANTS for suffix in ('','_profiled')}
    require(set(receipt['variantSourceHashes'])==expected_names,'Variant source inventory differs')
    for name in sorted(expected_names):
        text=safe_file(evidence,name+'.java').read_text()
        variant=name.removesuffix('_profiled')
        changed=accel.variant_source(source,variant)
        if name.endswith('_profiled'):
            matches=re.findall(r'options\.enableProfiling\(new File\(("(?:[^"\\]|\\.)*")',text)
            require(len(matches)==1,'Missing/ambiguous profile path')
            traces=Path(json.loads(matches[0]))
            require(traces.is_absolute() and '..' not in traces.parts and traces.name==name+'_traces'
                and traces.parent.name=='qualification','Unexpected original trace path')
            original_roots.add(str(traces.parent))
            changed=accel.profiler.instrument_source(changed,traces)
            if variant=='cuda_basic':
                maps=traces.parent/'cuda-jvm-loaded-library-maps.txt'
                changed=accel.capture_library_maps(changed,maps)
        require(text==changed,'Snapshot differs from immutable generator: '+name)
        require(safe_file(evidence,name+'/NativeDeux.java').read_bytes()==text.encode(),
            'Copied Java snapshot differs: '+name)
        require(receipt['variantSourceHashes'][name]==hashlib.sha256(text.encode()).hexdigest(),
            'Variant source hash differs: '+name)
        require(safe_file(evidence,name+'/AppDiagnostics.java').read_text()==STUB,'Compile stub differs')
        classes=evidence/name/'classes'
        actual={str(path.relative_to(classes)) for path in classes.rglob('*') if path.is_file()}
        require(actual==CLASS_FILES,'Incomplete/unexpected compiled class inventory: '+name+': '+repr(actual^CLASS_FILES))
        expected_bound.update([name+'.java',name+'/NativeDeux.java'])
        expected_bound.update(name+'/classes/'+file for file in actual)
    require(set(bound)==expected_bound,'Unexpected/missing bound compiled artifact')
    require(len(original_roots)==1 and Path(next(iter(original_roots))).parent.name==evidence.parent.name,
        'Snapshot original evidence directory differs')
    return len(bound)


def verify_runs(evidence,receipt,accel):
    runs=receipt['runs']
    pairs=[(variant+suffix,phase) for variant in accel.VARIANTS
           for suffix,phase in (('','qualification'),('_profiled','diagnostic'))]
    require([(row['variant'],row['phase']) for row in runs]==pairs,'Missing/reordered/extra diagnostic run')
    for row in runs:
        require(row['round']==0 and row['timingEligible'] is False,'Unexpected measurement admission')
        prefix=row['variant']+'/'+row['phase']+'-0'
        output=safe_file(evidence,prefix+'.f32'); profile=safe_file(evidence,prefix+'.profile.txt')
        require(output.stat().st_size==4586400==row['outputBytes'] and accel.benchmark.read_output(output)==row['outputSha256'],
            'Output length/hash/finiteness differs: '+prefix)
        require(sha(profile)==row['profileSha256'],'Profile hash differs: '+prefix)
        fields=accel.benchmark.profile_fields(profile)
        require(row['inferenceMillis']==float(fields['inferenceWallMs']) and row['modelInitMillis']==float(fields['modelInitWallMs']),
            'Recorded profile timings differ')
        log=safe_file(evidence,prefix+'.log').read_text()
        observations=[]
        for line in log.splitlines():
            try: value=json.loads(line)
            except (ValueError,TypeError): continue
            if isinstance(value,dict) and set(value)=={'wallNanos','processCpuNanos','peakRssBytes'}: observations.append(value)
        require(len(observations)==1,'Missing/ambiguous native measurement in log')
        for key,value in observations[0].items():
            require(type(value) is int and (value>0 or (key!='wallNanos' and value==-1)), 'Invalid native measurement')
            require(row[key]==(None if value==-1 else value),'Run/native log measurement differs')
        require(type(row['processWallIncludingStartupAndInspectionNanos']) is int
            and row['processWallIncludingStartupAndInspectionNanos']>=row['wallNanos'],'Invalid process timing')
    return runs


def verify_libraries(root,receipt,setup):
    maps=safe_file(root/'qualification','cuda-jvm-loaded-library-maps.txt')
    require(0<maps.stat().st_size<64*1024*1024,'Invalid library map size')
    mapped=set(); prefixes=('libcuda','libcudnn','libcublas','libnvrtc','libnvJitLink')
    for line in maps.read_text().splitlines():
        fields=line.split(None,5)
        if len(fields)==6 and fields[5].startswith('/') and Path(fields[5]).name.startswith(prefixes): mapped.add(fields[5])
    libraries=receipt['gpuNativeLibraries']
    require(mapped==set(libraries) and mapped,'Full mapped library paths differ; aliases require runtime proof')
    basenames=set()
    for name,pin in libraries.items():
        path=Path(name)
        require(path.is_absolute() and '..' not in path.parts and path.name not in basenames,'Invalid/duplicate library path')
        basenames.add(path.name)
        require(type(pin['bytes']) is int and pin['bytes']>0 and re.fullmatch('[0-9a-f]{64}',pin['sha256']), 'Invalid native pin')
        if '/cuda-wheels/' in name:
            relative=name.split('/cuda-wheels/',1)[1]
            require(setup['extractedNativeLibraries'].get(relative)==pin,'Mapped extracted library binding differs')
        else: require(path.name.startswith('libcuda.so'),'Unpinned non-driver native library')
    for prefix in ('libcudart.so','libcudnn.so','libcublas.so'):
        require(sum(name.startswith(prefix) for name in basenames)==1,'Missing/duplicate primary native library')
    require(receipt['gpuNativeLibraryVersions']==dict(cudaRuntimeVersion=12090,cudnnVersion=91002,cublasVersion=[12,9,1]),
        'Mapped runtime version differs from original wheel stack')
    return dict(mappedLibraryCount=len(libraries),versions=receipt['gpuNativeLibraryVersions'],
        fullPathsVerified=True,wheelHashBindingsMatch=True,actualLibraryBytesIncluded=False)


def verify(args,destination):
    roots=list(destination.iterdir())
    require(len(roots)==1 and roots[0].is_dir(),'Expected one evidence root')
    root=roots[0]; evidence=root/'qualification'; receipt_path=evidence/'receipt.json'
    receipt=strict_json(receipt_path)
    accel=pinned_modules(args.repo,root)
    setup=verify_bindings(root,receipt,args.repo,accel)
    require(all(receipt.get(flag) is False for flag in FLAGS) and 'performance' not in receipt,
        'Unexpected timing/quality/release admission')
    require(receipt.get('inputsRecheckedAfterQualification') is True,'Missing final external input integrity attestation')
    processes=verify_processes(root,receipt)
    artifacts=verify_snapshots(evidence,receipt,accel,args.repo)
    runs=verify_runs(evidence,receipt,accel)
    observers=[]; placements={}; trace_count=0
    for variant in accel.VARIANTS:
        comparison=accel.compare_outputs(evidence/variant/'qualification-0.f32',evidence/(variant+'_profiled')/'diagnostic-0.f32')
        comparison.update(reference=variant,candidate=variant+'_profiled'); observers.append(comparison)
        traces=accel.profiler.summarize_traces(evidence/(variant+'_profiled_traces'))
        require(traces==receipt['providerTraces'][variant],'Recomputed provider trace summary differs: '+variant)
        trace_count+=len(traces['graphs'])
        placement=accel.validate_placement(traces,variant)
        require(placement==receipt['placement'][variant],'Recomputed provider placement differs')
        placements[variant]=placement
    require(set(receipt['providerTraces'])==set(accel.VARIANTS)==set(receipt['placement']), 'Trace/placement variants differ')
    cross=[]
    for left,right in zip(accel.VARIANTS,accel.VARIANTS[1:]):
        comparison=accel.compare_outputs(evidence/left/'qualification-0.f32',evidence/right/'qualification-0.f32')
        comparison.update(reference=left,candidate=right);cross.append(comparison)
    require(observers+cross==receipt['comparisons'],'Recomputed exact comparisons differ')
    expected_status=None;expected_failure=None
    try: accel.require_output_qualification(observers+cross)
    except accel.InvalidObserver as error: expected_status='OBSERVER_COMPARISON_INVALID';expected_failure=str(error)
    except accel.NumericalEquivalenceUnproven as error: expected_status='NUMERICAL_EQUIVALENCE_UNPROVEN';expected_failure=str(error)
    require(expected_status is not None,'All diagnostic outputs exact; a complete timing-run verifier is required')
    require(receipt['status']==expected_status and receipt['failure']==expected_failure,'Gate result differs from immutable policy')
    # A rejected observer can be a valid retained record, but can never pass observer qualification.
    observer_passed=all(row['byteIdentical'] for row in observers)
    direct=accel.compare_outputs(evidence/'cpu_all/qualification-0.f32',evidence/'cuda_basic/qualification-0.f32')
    direct.update(reference='cpu_all',candidate='cuda_basic',additionalIndependentComparison=True)
    libraries=verify_libraries(root,receipt,setup)
    return dict(schema='lightforge.deux-continuation-independent-audit.v1',verificationPassed=True,
        verificationMeaning='Integrity and unchanged-policy diagnostic status verified; no quality or timing admission.',
        sourceCommit=SOURCE,sourceTree=TREE,receiptSha256=sha(receipt_path),receiptBytes=receipt_path.stat().st_size,
        diagnosticStatus=expected_status,qualificationExitCode=processes['qualification']['returnCode'],
        sourceHashCount=9,modelBindingCount=27,dependencyHashCount=4,boundCompiledArtifactCount=artifacts,
        runCount=len(runs),rawOutputBytes=8*4586400,rawFloat32SamplesPerRun=1146600,
        nativeProfileCount=8,graphsPerPass=27,graphCallsPerPass=335,providerTraceFiles=trace_count,
        observerComparisonsPassed=observer_passed,observerComparisons=observers,crossVariantComparisons=cross,
        cpuAllVersusCuda=direct,placement=placements,nativeLibraries=libraries,
        allFinalInputHashesRecheckedByFrozenHarness=True,
        diagnosticTimings=[{key:row[key] for key in ('variant','phase','wallNanos','processCpuNanos','peakRssBytes',
            'inferenceMillis','modelInitMillis','processWallIncludingStartupAndInspectionNanos','timingEligible')} for row in runs],
        measured=False,qualityApproved=False,target75Proven=False,releaseAuthorized=False,
        limitations=['Input audio, model, runtime and native-library bytes are not included in this ZIP; their immutable receipt bindings and frozen-harness before/after rehash attestations are verified.',
          'The full APK is not included; its pinned hash was checked once by the continuation setup before extracting the 27 graphs. The inference harness does not rehash the full APK afterward.',
          'Closed process logs are bound by the confirmed archive digest, not by separate log-hash exit receipts.',
          'Single diagnostic timings are not repeated speed measurements or accepted performance ratios.',
          'Different Float32 bytes do not by themselves prove perceptual degradation; no tolerance or quality approval is inferred.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True);parser.add_argument('--expected-size',type=int,required=True)
    parser.add_argument('--expected-sha256',required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--max-uncompressed-bytes',type=int,default=1024*1024*1024)
    args=parser.parse_args();args.repo=args.repo.resolve();args.output_dir=args.output_dir.resolve()
    require(re.fullmatch('[0-9a-f]{64}',args.expected_sha256),'Invalid expected digest')
    require(not args.output_dir.exists(),'Use a new verification directory')
    args.output_dir.mkdir(parents=True)
    try:
        destination,archive=extract_verified(args)
        report=verify(args,destination);report['archive']=archive
        report['verifierSha256']=sha(Path(__file__))
        (args.output_dir/'verification.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(json.dumps({key:report[key] for key in ('verificationPassed','diagnosticStatus','runCount','observerComparisonsPassed','qualityApproved','target75Proven')}))
    except Exception as error:
        (args.output_dir/'verification-failure.json').write_text(json.dumps(dict(verificationPassed=False,error=str(error)),indent=2)+'\n')
        raise

if __name__=='__main__': main()
