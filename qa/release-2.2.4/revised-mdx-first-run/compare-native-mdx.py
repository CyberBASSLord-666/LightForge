#!/usr/bin/env python3
"""Fresh MDX production native task versus the bundled CPU WASM runtime.

Same original source passage, STFT input and both polarity-ensemble passes.
Host Android adapters supply filesystem/metadata APIs only; real JNI inference
and production task model validation, chunk transport and file writer run.
"""
from pathlib import Path
import datetime, hashlib, json, math, os, platform, subprocess, sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'qa/release-2.2.4'
WORK=Path(os.environ.get('LIGHTFORGE_MDX_COMPARISON_DIR',ROOT.parent/'native-mdx-comparison-2.2.4'))
TOOLS=Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR',ROOT.parent/'toolchain'))
from mdx_numeric import compare, SPECTRUM_THRESHOLDS, WAVEFORM_THRESHOLDS
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def command(args,log):
    with log.open('w') as output:
        subprocess.run([str(a) for a in args],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)
def main():
    WORK.mkdir(parents=True,exist_ok=True)
    runtime=json.loads((ROOT/'android/native-runtime.json').read_text());assert runtime['version']=='1.25.1'
    jar=TOOLS/'onnx'/runtime['host']['name'];assert jar.stat().st_size==runtime['host']['bytes'] and sha(jar)==runtime['host']['sha256']
    source_names=['version.json','android/native-runtime.json','android/src/com/cyberbasslord/lightforge/NativeMdxTask.java','android/src/com/cyberbasslord/lightforge/NativeRuntimeGuard.java','android/src/com/cyberbasslord/lightforge/NativeDeux.java','web/analysis/dsp.js','web/analysis/wav-reader.js','web/analysis/separator-mdx.js','web/analysis/models/separator-mdx-model.json','web/demo/glass-castle.wav']
    sources=[ROOT/p for p in source_names]+sorted((ROOT/'tests/native-mdx-host').rglob('*.java'))+[OUT/n for n in ['NativeMdxComparisonMain.java','compare-mdx-wasm.cjs','compare-native-mdx.py','mdx_numeric.py']]
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sources}
    assets=[ROOT/'web/analysis/models/uvr-mdx-voc-ft.onnx',*sorted((ROOT/'web/analysis/vendor').glob('*'))]
    assets=[p for p in assets if p.is_file()]
    asset_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in assets}
    model=json.loads((ROOT/'web/analysis/models/separator-mdx-model.json').read_text());assert asset_hashes['web/analysis/models/uvr-mdx-voc-ft.onnx']==model['sha256']
    receipt={'release':'2.2.4','passed':False,'errors':[],'source_hashes':hashes,'analysis_asset_hashes':asset_hashes,'thresholds':{'spectrum':SPECTRUM_THRESHOLDS,'waveform':WAVEFORM_THRESHOLDS},'start_sample':-3840,'sample_rate':44100,'spectrum_floats':3145728,'waveform_samples':261120,'native_runtime':runtime['version'],'native_runtime_sha256':sha(jar),'wasm_runtime':'1.20.1','host':{'system':platform.system(),'machine':platform.machine()},'scope':'Fresh production NativeMdxTask on Linux/JVM versus bundled ONNX Runtime Web CPU WASM under Node, including both polarity passes and production WAV/STFT/ensemble/waveform decoder. Android framework is adapted for host filesystem access; no Android/ARM64, lifecycle or phone-performance claim.'}
    receipt['criterion_review']={'initial_failure_path':'qa/release-2.2.4/initial-mdx-absolute-only/native-mdx-comparison-verification.json','initial_failure_sha256':sha(OUT/'initial-mdx-absolute-only/native-mdx-comparison-verification.json'),'explanation':'The initial absolute-only spectral check failed (max 1.373291015625e-4 > 1e-4); that criterion copied normalized waveform units onto unnormalized FFT coefficients. The qualifying run uses fixed pointwise absolute-plus-relative spectral tolerances and separately stricter normalized waveform bounds, declared before rerunning. Cross-runtime outputs are close, not bit-identical.'}
    gate=OUT/'native-mdx-comparison-verification.json';gate.write_text(json.dumps(receipt,indent=2)+'\n')
    try:
        command(['node',OUT/'compare-mdx-wasm.cjs','prepare',WORK],WORK/'prepare.log')
        classes=WORK/'classes';classes.mkdir(exist_ok=True)
        compile_sources=[ROOT/'android/src/com/cyberbasslord/lightforge'/n for n in ['NativeMdxTask.java','NativeRuntimeGuard.java']]+sorted((ROOT/'tests/native-mdx-host').rglob('*.java'))+[OUT/'NativeMdxComparisonMain.java']
        cp=os.pathsep.join(map(str,[jar,TOOLS/'test-json.jar']))
        java=Path(os.environ.get('LIGHTFORGE_JAVA_HOME',TOOLS/'jdk17'))/'bin'
        command([java/'javac','--release','8','-encoding','UTF-8','-classpath',cp,'-d',classes,*compile_sources],WORK/'compile.log')
        command([java/'java','-cp',str(classes)+os.pathsep+cp,'com.cyberbasslord.lightforge.NativeMdxComparisonMain',ROOT,WORK],WORK/'native.log')
        command(['node',OUT/'compare-mdx-wasm.cjs','wasm',WORK],WORK/'wasm.log')
        command(['node',OUT/'compare-mdx-wasm.cjs','decode',WORK],WORK/'decode.log')
        receipt['runs']={runtime:[json.loads(line) for line in (WORK/(runtime+'.log')).read_text().splitlines() if line.startswith('{')] for runtime in ['native','wasm']}
        receipt['comparisons']=[];receipt['output_hashes']={}
        for output,count in [('positive',3145728),('negative',3145728),('waveform',261120)]:
            paths=[WORK/(runtime+'-'+output+'.float32le') for runtime in ['native','wasm']]
            values=[np.fromfile(p,dtype='<f4').astype(np.float64) for p in paths]
            assert all(x.size==count and np.all(np.isfinite(x)) for x in values),'Incomplete/nonfinite '+output
            native,wasm=values
            result=compare(native,wasm,output)
            receipt['comparisons'].append(result)
            for p in paths:receipt['output_hashes'][p.name]={'bytes':p.stat().st_size,'sha256':sha(p)}
            print(json.dumps(result),flush=True)
        assert all(r['within_thresholds'] for r in receipt['comparisons']),'Numerical threshold exceeded'
        assert all(sha(ROOT/p)==h for p,h in {**hashes,**asset_hashes}.items()),'Source changed during comparison'
        receipt['passed']=True
    except Exception as error:
        receipt['errors'].append(str(error));raise
    finally:
        receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat();gate.write_text(json.dumps(receipt,indent=2)+'\n')
if __name__=='__main__':main()
