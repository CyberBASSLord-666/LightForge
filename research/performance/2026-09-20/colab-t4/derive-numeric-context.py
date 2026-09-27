#!/usr/bin/env python3
"""Re-derive original T4 output numerics; historical CPU thresholds are context only."""
import argparse, ast, array, gzip, hashlib, json, math, subprocess, sys, zipfile
from pathlib import Path
P=argparse.ArgumentParser();P.add_argument('--repo',type=Path,required=True);P.add_argument('--evidence',type=Path,required=True);P.add_argument('--archive',type=Path,required=True);P.add_argument('--output',type=Path,required=True);a=P.parse_args()
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def check(test,msg):
 if not test: raise RuntimeError(msg)
def assignment(path,name):
 for node in ast.parse(path.read_text()).body:
  if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):return ast.literal_eval(node.value)
 raise RuntimeError('Missing constant '+name)
q=a.evidence/'qualification'; rp=q/'receipt.json';receipt=json.loads(rp.read_text());setup=json.loads((a.evidence/'setup-receipt.json').read_text())
check(sha(rp)=='83bc446d518375e18cc47a17ff732e1a7320cdece4c5cc874ca0208b7f82190c','Original primary receipt differs')
gz=a.repo/'research/performance/2026-09-20/colab-t4/qualification-receipt.json.gz'
check(gzip.decompress(gz.read_bytes())==rp.read_bytes(),'Committed primary receipt differs')
check(setup['sourceCommit']=='1c7a7d2d3bc0a9eab94bbcb8266710ea7f8ded0b','Source commit differs')
check(receipt['status']=='NUMERICAL_EQUIVALENCE_UNPROVEN','Unexpected original status')
for key in ['qualityApproved','target75Proven','wholeSongSpeedupProven','androidSpeedupProven','releaseAuthorized','measured']:check(receipt[key] is False,'Original approval changed: '+key)
check(receipt['startSample']==-66150 and receipt['samplesPerStem']==573300,'Sample context differs')
source_hashes={}
for rel,expected in receipt['sourceHashes'].items():
 check(sha(a.repo/rel)==expected,'Source mismatch '+rel);source_hashes[rel]=expected
for rel,expected in receipt['compiledSnapshotHashes'].items():check(sha(q/rel)==expected,'Snapshot mismatch '+rel)
for variant,expected in receipt['variantSourceHashes'].items():check(sha(q/(variant+'.java'))==expected,'Variant source mismatch '+variant)
traces=0
for arm,data in receipt['providerTraces'].items():
 for g in data['graphs']:
  paths=list((q/(arm+'_profiled_traces')).rglob(g['traceFile']));check(len(paths)==1,'Missing trace '+g['traceFile']);path=paths[0]
  check(path.stat().st_size==g['traceBytes'] and sha(path)==g['traceSha256'],'Trace differs '+str(path));traces+=1
verified_outputs={};values={}
for run in receipt['runs']:
 variant=run['variant'];stem='diagnostic' if variant.endswith('_profiled') else 'qualification';path=q/variant/(stem+'-0.f32');profile=path.with_suffix('.profile.txt')
 check(path.stat().st_size==run['outputBytes']==4586400,'Wrong output length '+variant)
 check(sha(path)==run['outputSha256'],'Output differs '+variant);check(sha(profile)==run['profileSha256'],'Profile differs '+variant)
 floats=array.array('f');floats.frombytes(path.read_bytes())
 if sys.byteorder!='little':floats.byteswap()
 check(len(floats)==1146600 and all(math.isfinite(v) for v in floats),'Invalid samples '+variant)
 values[variant]=floats;verified_outputs[variant]={'path':str(path.relative_to(a.evidence)),'bytes':path.stat().st_size,'sha256':sha(path),'profileSha256':sha(profile),'finite':True,'samples':len(floats),'timingEligible':run['timingEligible']}
observer=[]
for arm in receipt['variants']:
 exact=values[arm].tobytes()==values[arm+'_profiled'].tobytes();check(exact,'Observer changed '+arm);observer.append({'variant':arm,'byteIdentical':exact})
hist=a.repo/'qa/release-2.3.2/verify-analysis.py';thresholds=assignment(hist,'THRESHOLDS');check(thresholds=={'max_absolute_error':1e-4,'rmse':1e-5,'relative_rmse':1e-3},'Historical thresholds differ')
check(assignment(hist,'SAMPLES')==573300,'Historical sample length differs')
comparisons=[]
for ref,cand in [('cpu_all','cuda_basic'),('cpu_all','cpu_basic'),('gpu_package_cpu_basic','cuda_basic')]:
 stems=[]
 for i,name in enumerate(['vocals','accompaniment']):
  x=values[ref][i*573300:(i+1)*573300];y=values[cand][i*573300:(i+1)*573300];errors=[float(b)-float(c) for b,c in zip(y,x)]
  rmse=math.sqrt(math.fsum(e*e for e in errors)/573300);rms=math.sqrt(math.fsum(float(v)*v for v in x)/573300)
  m={'stem':name,'samples':573300,'finite':True,'byteOffset':i*573300*4,'byteLength':573300*4,'referenceStemSha256':hashlib.sha256((q/verified_outputs[ref]['path'].split('/',1)[1]).read_bytes()[i*573300*4:(i+1)*573300*4]).hexdigest(),'candidateStemSha256':hashlib.sha256((q/verified_outputs[cand]['path'].split('/',1)[1]).read_bytes()[i*573300*4:(i+1)*573300*4]).hexdigest(),'numericallyUnequalSamples':sum(b!=c for b,c in zip(y,x)),'max_absolute_error':max(map(abs,errors)),'rmse':rmse,'reference_rms':rms,'relative_rmse':rmse/max(rms,1e-12),'snr_db':20*math.log10(rms/rmse) if rmse and rms else None,'identical':max(map(abs,errors))==0}
  m['withinHistoricalCpuMigrationThresholds']=all(m[k]<=v for k,v in thresholds.items());stems.append(m)
 comparisons.append({'reference':ref,'candidate':cand,'referenceSha256':verified_outputs[ref]['sha256'],'candidateSha256':verified_outputs[cand]['sha256'],'stems':stems,'contextOnly':True,'cudaQualityApproved':False})
archive_sha=sha(a.archive);check(archive_sha=='657e0089895f377d34deb77a5a25c9d3a51dbee0dbe503e283993285484163c4','Original archive differs');check(a.archive.stat().st_size==50821544,'Original archive size differs')
allfiles={str(p.relative_to(a.evidence.parent)):p for p in a.evidence.rglob('*') if p.is_file()};check(not any(p.is_symlink() for p in a.evidence.rglob('*')),'Unexpected symlink')
with zipfile.ZipFile(a.archive) as z:
 check(len(z.namelist())==len(set(z.namelist())),'Duplicate archive member');check(set(z.namelist())==set(allfiles),'Archive/member inventory differs');check(z.testzip() is None,'Archive CRC failure')
 for name,path in allfiles.items(): check(hashlib.sha256(z.read(name)).hexdigest()==sha(path),'Extracted archive member differs '+name)
archive_meta={'bytes':a.archive.stat().st_size,'sha256':archive_sha,'fileCount':len(allfiles),'uncompressedBytes':sum(p.stat().st_size for p in allfiles.values()),'allExtractedMembersMatchOriginalArchive':True,'symlinks':False,'reconstruction':'Original archive survives. Re-zipping can preserve all member payloads, but byte-identical archive reconstruction is not asserted because ZIP timestamps, compression implementation and metadata may differ.'}
repo_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=a.repo,text=True).strip();histpaths=['qa/release-2.3.2/verify-analysis.py','qa/release-2.2.4/compare-native-runtime.py','qa/release-2.2.3/compare-native-runtime.py']
result={'schema':'lightforge.deux-cuda-numeric-context.v1','purpose':'Independent full-stem arithmetic derivation from the original free-Colab T4 run. Historical CPU runtime-migration thresholds are diagnostic context only; they do not approve CUDA or change any existing gate.','primaryReceiptSha256':sha(rp),'primaryReceiptStatus':receipt['status'],'setupReceiptSha256':sha(a.evidence/'setup-receipt.json'),'sourceCommit':setup['sourceCommit'],'evidenceRepositoryCommit':repo_head,'sourceHashesRechecked':source_hashes,'compiledSnapshotHashCountRechecked':len(receipt['compiledSnapshotHashes']),'variantSourceHashesRechecked':receipt['variantSourceHashes'],'providerTraceHashCountRechecked':traces,'sampleLayout':{'encoding':'IEEE-754 Float32 little-endian','sampleRateHz':44100,'startSample':-66150,'samplesPerStem':573300,'stemOrder':['vocals','accompaniment'],'totalSamples':1146600,'totalBytes':4586400,'layoutSource':'android/src/com/cyberbasslord/lightforge/NativeDeux.java','layoutSourceSha256':source_hashes['android/src/com/cyberbasslord/lightforge/NativeDeux.java']},'inputBindings':{k:receipt[k] for k in ['audioSha256','audioFrames','modelManifestSha256','modelHashes','dependencyHashes','cudaOptions','nvidiaTf32Override','deterministicCompute']},'outputsRechecked':verified_outputs,'observerChecks':observer,'comparisons':comparisons,'historicalCpuMigrationContext':{'thresholds':thresholds,'thresholdSource':'qa/release-2.3.2/verify-analysis.py','metricImplementation':'qa/release-2.2.4/compare-native-runtime.py','sourceHashes':{rel:sha(a.repo/rel) for rel in histpaths},'meaning':'Existing full-stem CPU ORT 1.23.2-to-1.25.1 migration limits; these values were not fitted to the CUDA observations and are not adopted here as a CUDA approval policy.','rmseFormula':'sqrt(fsum((candidate-reference)^2)/573300)','referenceRmsFormula':'sqrt(fsum(reference^2)/573300)','relativeRmseFormula':'rmse/max(reference_rms,1e-12)'},'archiveIntegrity':archive_meta,'derivationScriptSha256':sha(Path(__file__)),'qualityApproved':False,'cudaQualityApproved':False,'releaseAuthorized':False,'target75Proven':False,'wholeSongSpeedupProven':False,'androidSpeedupProven':False,'timingQualified':False}
a.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps({'output':str(a.output),'sha256':sha(a.output),'archive':archive_meta,'cpuAllToCuda':comparisons[0]},indent=2))
