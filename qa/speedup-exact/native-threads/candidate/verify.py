#!/usr/bin/env python3
"""Actual production NativeDeux, original 4-thread source versus current policy.

Strict full-output equality on two real audio fixtures. No source patch changes
threads in the candidate: this host must expose at least 8 available processors.
"""
from pathlib import Path
import argparse,array,datetime,hashlib,json,math,os,platform,struct,subprocess,sys,wave
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
TOOLS=Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR',ROOT.parent/'toolchain'))
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(command,log,timeout=600):
 with log.open('w') as stream:subprocess.run([str(x) for x in command],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=timeout)
def pcm16_fixture(source,target):
 data=source.read_bytes();assert data[:4]==b'RIFF' and data[8:12]==b'WAVE';at=12;fmt=None;pcm=None
 while at+8<=len(data):
  key=data[at:at+4];size=struct.unpack_from('<I',data,at+4)[0];payload=data[at+8:at+8+size];assert len(payload)==size
  if key==b'fmt ':fmt=payload
  if key==b'data':pcm=payload
  at+=8+size+(size&1)
 assert fmt is not None and pcm is not None
 kind,channels,rate,byte_rate,align,bits=struct.unpack_from('<HHIIHH',fmt)
 assert kind==65534 and channels==2 and rate==44100 and align==8 and bits==32
 assert fmt[24:40]==bytes.fromhex('0300000000001000800000aa00389b71')
 values=array.array('f');values.frombytes(pcm)
 if sys.byteorder!='little':values.byteswap()
 assert all(math.isfinite(v) for v in values)
 converted=array.array('h',(max(-32768,min(32767,round(float(v)*32768))) for v in values))
 if sys.byteorder!='little':converted.byteswap()
 with wave.open(str(target),'wb') as output:output.setnchannels(2);output.setsampwidth(2);output.setframerate(44100);output.writeframes(converted.tobytes())
 return len(values)//2
parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,default=ROOT.parent/'native-thread-qualification');args=parser.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
java=Path(os.environ.get('LIGHTFORGE_JAVA_HOME',TOOLS/'jdk17'))/'bin';android=TOOLS/'android-sdk/platforms/android-35/android.jar';runtime=json.loads((ROOT/'android/native-runtime.json').read_text());jar=TOOLS/'onnx'/runtime['host']['name'];assert runtime['version']=='1.25.1' and sha(jar)==runtime['host']['sha256'];cp=os.pathsep.join(map(str,[TOOLS/'test-json.jar',android,jar]))
source_paths=[ROOT/'android/src/com/cyberbasslord/lightforge/NativeDeux.java',ROOT/'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',ROOT/'tests/NativeDeuxTest.java',ROOT/'android/native-runtime.json',ROOT/'web/analysis/models/deux/manifest.json',ROOT/'web/demo/glass-castle.wav',ROOT/'qa/release-1.6.0/fixtures/falcon-mix.wav',HERE/'reference/NativeDeux.java',HERE/'reference/NativeDeuxTest.java',Path(__file__).resolve()]
bindings={str(p.relative_to(ROOT)):sha(p) for p in source_paths}
report={'passed':False,'createdUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Actual original/current NativeDeux production classes on Linux/JVM x86_64 using pinned ONNX Runtime 1.25.1; no Android/ARM64 or physical-phone speed claim.','threadPolicy':'Cores 1–7 retain the old min(4, cores) with minimum 1; 8 or more cores use 8 intra-op threads. MDX unchanged.','host':{'system':platform.system(),'machine':platform.machine(),'pythonLogicalCpuCount':os.cpu_count(),'runtimeJarSha256':sha(jar)},'sourceHashes':bindings,'fixtures':[],'modelHashes':{},'comparisonRule':'Exact complete float32LE file bytes; no tolerance.','sampleRate':44100,'contextSamples':573300,'samplesPerStem':573300,'outputBytes':4586400,'startSample':-66150,'limitations':['Heterogeneous phone CPUs can have slower efficiency cores; more logical cores does not guarantee faster ARM64 performance.','Host byte identity does not establish ARM64 bit identity or long-song thermal throughput.','Peak RSS is sampled per-process host memory, not Android memory admission evidence.']}
gate=HERE/'verification.json';gate.write_text(json.dumps(report,indent=2)+'\n')
try:
 manifest=json.loads((ROOT/'web/analysis/models/deux/manifest.json').read_text())
 for name,item in manifest['files'].items():
  p=ROOT/'web/analysis/models/deux'/name;assert p.stat().st_size==item['bytes'] and sha(p)==item['sha256'];report['modelHashes'][name]=item['sha256']
 stub=work/'AppDiagnostics.java';stub.write_text('package com.cyberbasslord.lightforge; public final class AppDiagnostics { public static void log(android.content.Context c,String l,String s,String m){} public static boolean flush(long t){return true;} }\n')
 probe=work/'NativeThreadProbeMain.java';probe.write_text('package com.cyberbasslord.lightforge; public final class NativeThreadProbeMain { public static void main(String[] a)throws Exception{int cores=Runtime.getRuntime().availableProcessors();String v=ai.onnxruntime.OrtEnvironment.getEnvironment().getVersion();if(cores<8||!v.equals("1.25.1"))throw new AssertionError("Unqualified host/runtime");System.out.println("HOST_CORES "+cores);NativeDeuxTest.main(a);} }\n')
 classpaths={}
 for variant in ['baseline','candidate']:
  classes=work/variant/'classes';classes.mkdir(parents=True,exist_ok=True);source=HERE/'reference/NativeDeux.java' if variant=='baseline' else ROOT/'android/src/com/cyberbasslord/lightforge/NativeDeux.java';test=HERE/'reference/NativeDeuxTest.java' if variant=='baseline' else ROOT/'tests/NativeDeuxTest.java'
  run([java/'javac','-encoding','UTF-8','--release','8','-cp',cp,'-d',classes,source,ROOT/'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',test,stub,probe],work/variant/'compile.log');classpaths[variant]=str(classes)+os.pathsep+cp
 run([java/'java','-cp',classpaths['candidate'],'com.cyberbasslord.lightforge.NativeDeuxTest'],work/'policy-and-transform.log');report['policyAndTransformChecksPassed']=True
 falcon=work/'falcon-pcm16.wav';frames=pcm16_fixture(ROOT/'qa/release-1.6.0/fixtures/falcon-mix.wav',falcon)
 fixtures=[('demo-start',ROOT/'web/demo/glass-castle.wav',None),('falcon-start',falcon,{'source':'qa/release-1.6.0/fixtures/falcon-mix.wav','sourceSha256':sha(ROOT/'qa/release-1.6.0/fixtures/falcon-mix.wav'),'sampleFrames':frames,'preparation':'Existing float32 stereo fixture converted deterministically to the native PCM16 input contract with round-to-nearest/ties-even and signed 16-bit clamp. Both predictors read these exact same prepared bytes; production audio conversion is unchanged.'})]
 for index,(name,audio,preparation) in enumerate(fixtures):
  item={'id':name,'inputSha256':sha(audio),'inputBytes':audio.stat().st_size,'preparation':preparation,'runs':{}};report['fixtures'].append(item)
  for variant in (['baseline','candidate'] if index==0 else ['candidate','baseline']):
   folder=work/name/variant;folder.mkdir(parents=True,exist_ok=True);output=folder/'output.float32le';log=folder/'inference.log'
   run([java/'java','-cp',classpaths[variant],'com.cyberbasslord.lightforge.NativeThreadProbeMain',ROOT/'web/analysis/models/deux',audio,output,-66150],log)
   lines=log.read_text().splitlines();metrics=[json.loads(l) for l in lines if l.startswith('{"seconds":')];assert len(metrics)==1;metric=metrics[0];assert output.stat().st_size==4586400 and sha(output)==metric['sha256'];cores=[int(l.split()[1]) for l in lines if l.startswith('HOST_CORES ')];assert len(cores)==1 and cores[0]>=8;actual_cores=cores[0]
   values=array.array('f');values.frombytes(output.read_bytes())
   if sys.byteorder!='little':values.byteswap()
   assert len(values)==1146600 and all(math.isfinite(v) for v in values) and any(v!=0 for v in values)
   item['runs'][variant]={**metric,'outputBytes':output.stat().st_size,'logSha256':sha(log),'actualAvailableCores':actual_cores,'selectedIntraOpThreads':4 if variant=='baseline' else 8};gate.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'fixture':name,'variant':variant,**metric}),flush=True)
  baseline=(work/name/'baseline/output.float32le').read_bytes();candidate=(work/name/'candidate/output.float32le').read_bytes();item['byteIdentical']=baseline==candidate;item['speedRatio']=item['runs']['baseline']['seconds']/item['runs']['candidate']['seconds'];assert item['byteIdentical'],name+' full output bytes differ';item['maxAbsoluteError']=0.0;item['rmse']=0.0
 for p in source_paths:assert sha(p)==bindings[str(p.relative_to(ROOT))],str(p)+' changed during verification'
 report['passed']=True;report['completedUtc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
except Exception as error:report['error']=str(error);raise
finally:gate.write_text(json.dumps(report,indent=2)+'\n')
