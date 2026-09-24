#!/usr/bin/env python3
"""Generate an isolated, host-only GAME session-reuse research snapshot.

NOT an Android implementation. cancel()/close() request termination immediately,
then may BLOCK until the serialized predictor and native destructors finish.
Only one source, at most 64 seconds, may use the generated class. Cancellation,
failure or close is terminal: a fresh engine/process is required afterward.
No inference, timing admission, model change or production file edit occurs.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('game_reuse_qualified_generator', ROOT / 'tools/benchmark_game_accelerator.py')
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)
ORIGINAL_SHA256 = 'a1bb68a4930b5acd74f7fdc2d1d105f1d7f5c9974f11514872f47672b8736369'
VARIANTS = ('cpu_all', 'cuda_basic')

PREFIX = '''        check(cancellation);
        float[] samples=validatedPcm(pcm,language,seed);
        synchronized(lifecycle){check(cancellation);running=true;}
        Throwable failure=null;
        try {
            prepareModels(cancellation);'''

ORIGINAL_FINALLY = '''            // No JNI close holds lifecycle: cancel/close must remain nonblocking.
            Throwable retirement=null;boolean cleanupConfirmed=false;
            try {
                for(OrtSession session:sessions.values())try{retire(session);}catch(Throwable error){
                    if(retirement==null)retirement=error;
                }
                sessions.clear();
                OrtSession.RunOptions retiringRun;
                synchronized(lifecycle) {
                    retiringRun=activeRun;activeRun=null;
                }
                // cancel cannot terminate a RunOptions handle once its destructor
                // starts, and a slow native destructor must not hold lifecycle.
                if(retiringRun!=null)try{retire(retiringRun);}catch(Throwable error){
                    if(retirement==null)retirement=error;
                }
                cleanupConfirmed=retirement==null;
            } finally {
                synchronized(lifecycle){
                    running=false;
                    // Even if another cleanup operation fails unexpectedly, never
                    // mistake an attempted destructor for confirmed retirement.
                    if(!cleanupConfirmed){retirementUnconfirmed=true;cancelled=true;}
                }
            }
            if(retirement!=null) {
                if(failure!=null)failure.addSuppressed(retirement);
                else if(retirement instanceof Exception)throw (Exception)retirement;
                else if(retirement instanceof Error)throw (Error)retirement;
                else throw new IOException("The singing runtime could not be retired.",retirement);
            }'''

REUSE_FINALLY = '''            // HOST RESEARCH ONLY: preserve sessions only after a successful passage.
            // A fresh per-call RunOptions is always detached and retired here.
            Throwable retirement=null;boolean cleanupConfirmed=false,sessionsDrained=false;
            try {
                OrtSession.RunOptions retiringRun;
                synchronized(lifecycle) {retiringRun=activeRun;activeRun=null;}
                if(retiringRun!=null)try{retire(retiringRun);}catch(Throwable error){retirement=error;}
                if(failure!=null||cancelled||closed||retirement!=null){
                    retirement=researchRetireSessions(retirement);
                    sessionsDrained=true;
                }
                cleanupConfirmed=retirement==null;
            } finally {
                synchronized(lifecycle){
                    running=false;
                    if(!cleanupConfirmed){researchResourcesRetired=false;retirementUnconfirmed=true;cancelled=true;}
                    else if(sessionsDrained)researchResourcesRetired=activeRun==null&&!retirementUnconfirmed;
                }
            }
            if(retirement!=null) {
                if(failure!=null)failure.addSuppressed(retirement);
                else if(retirement instanceof Exception)throw (Exception)retirement;
                else if(retirement instanceof Error)throw (Error)retirement;
                else throw new IOException("The singing runtime could not be retired.",retirement);
            }'''

ORIGINAL_CANCEL_CLOSE = '''    /** Stops kernels cooperatively; the active worker alone retires its sessions. */
    public void cancel() {
        synchronized(lifecycle) {
            cancelled=true;
            if(activeRun!=null)try{activeRun.setTerminate(true);}catch(OrtException ignored){/* check also observes cancellation. */}
        }
    }
    /** Nonblocking; callers must confirm isRetired before releasing native ownership. */
    @Override public void close(){synchronized(lifecycle){closed=true;cancel();}}'''

REUSE_CANCEL_CLOSE = '''    /** HOST RESEARCH ONLY: requests termination immediately, then may block draining resources. */
    public void cancel() {
        synchronized(lifecycle) {
            cancelled=true;
            if(activeRun!=null)try{activeRun.setTerminate(true);}catch(OrtException ignored){/* check also observes cancellation. */}
        }
        researchDrainWhenIdle();
    }
    /** HOST RESEARCH ONLY: blocking worker close, forbidden on Android lifecycle/UI threads. */
    @Override public void close(){synchronized(lifecycle){closed=true;}cancel();}

    // Called with the predictor monitor held; no native destructor holds lifecycle.
    // Every session gets a retirement attempt even if a previous destructor fails.
    private Throwable researchRetireSessions(Throwable first) {
        for(OrtSession session:sessions.values())try{retire(session);}catch(Throwable error){if(first==null)first=error;}
        sessions.clear();
        return first;
    }
    private synchronized void researchDrainWhenIdle() {
        // A listener can reenter cancel/close on the owner thread. The active
        // predict finally owns its resources; never destroy a running session.
        synchronized(lifecycle){
            if(running||researchDraining)return;
            researchDraining=true;researchResourcesRetired=false;
        }
        boolean cleanupConfirmed=false;
        try{cleanupConfirmed=researchRetireSessions(null)==null;}
        finally{synchronized(lifecycle){
            researchDraining=false;
            researchResourcesRetired=cleanupConfirmed&&activeRun==null&&!retirementUnconfirmed;
            if(!cleanupConfirmed){retirementUnconfirmed=true;cancelled=true;}
        }}
    }'''


def replace_once(source, old, new):
    game.require(source.count(old) == 1, 'Session-reuse anchor changed or duplicated; review required.')
    return source.replace(old, new)


def generate(original, variant, *, source_samples, language=0):
    game.require(hashlib.sha256(original.encode('utf-8')).hexdigest() == ORIGINAL_SHA256,
                 'Original NativeGame bytes changed; session-reuse review required.')
    game.require(variant in VARIANTS, 'Only qualified CPU/ALL or deterministic heavy-only CUDA candidates are allowed.')
    game.require(type(source_samples) is int and 0 < source_samples <= 64 * 44100 and
                 type(language) is int and 0 <= language <= 4, 'Bound one <=64-second original source clock and language.')
    source = game.variant_source(original, variant, True, True)
    source = replace_once(source, '    private OrtSession.RunOptions activeRun;',
        '    private OrtSession.RunOptions activeRun;\n'
        '    // ISOLATED HOST RESEARCH: never compile this snapshot into the Android app.\n'
        f'    private static final int RESEARCH_SOURCE_SAMPLES={source_samples}, RESEARCH_LANGUAGE={language};\n'
        '    private final Thread researchOwner=Thread.currentThread();\n'
        '    private int researchPassagesStarted;\n'
        '    // Guarded only by lifecycle; never infer resource retirement from running alone.\n'
        '    private boolean researchResourcesRetired=true,researchDraining;')
    source = replace_once(source, '        this.context=context;',
        '        if(context!=null)throw new IOException("Session reuse candidate is host research only; Android forbidden");\n'
        '        this.context=context;')
    source = replace_once(source, PREFIX, '''        synchronized(lifecycle){
            // synchronized methods are reentrant: reject before claiming or cleaning
            // the outer call's resources, including Cancellation callback reentry.
            if(running||researchDraining){
                cancelled=true;
                if(activeRun!=null)try{activeRun.setTerminate(true);}catch(OrtException ignored){/* outer check observes cancellation */}
                throw new IOException("Reentrant prediction forbidden; outer owner retains cleanup");
            }
            running=true;researchResourcesRetired=false;
        }
        Throwable failure=null;
        try {
            check(cancellation);
            if(Thread.currentThread()!=researchOwner)throw new IOException("One serialized host owner required");
            float[] samples=validatedPcm(pcm,language,seed);
            int index=researchPassagesStarted,core=12*SAMPLE_RATE,halo=2*SAMPLE_RATE;
            if(index>=(RESEARCH_SOURCE_SAMPLES+core-1)/core)
                throw new IOException("Bound complete-source passage count exceeded; use a fresh engine");
            int first=Math.max(0,index*core-halo),last=Math.min(RESEARCH_SOURCE_SAMPLES,(index+1)*core+halo);
            if(samples.length!=last-first||language!=RESEARCH_LANGUAGE||seed!=((2025L+index*104729L)&0xffffffffL))
                throw new IOException("Bound production source clock, halo or seed changed");
            researchPassagesStarted++;
            prepareModels(cancellation);''')
    source = replace_once(source, '            for(int i=0;i<GRAPHS.length;i++) {\n                check(cancellation);\n                progress(listener,0,"Loading singing model "+(i+1)+"/"+GRAPHS.length);',
        '            if(!sessions.isEmpty()&&sessions.size()!=GRAPHS.length)throw new IOException("Incomplete retained session set");\n'
        '            if(sessions.isEmpty()){\n'
        '            for(int i=0;i<GRAPHS.length;i++) {\n                check(cancellation);\n                progress(listener,0,"Loading singing model "+(i+1)+"/"+GRAPHS.length);')
    source = replace_once(source, '            JSONArray notes=infer(environment,samples,language,seed,listener,cancellation);',
        '            }\n            JSONArray notes=infer(environment,samples,language,seed,listener,cancellation);')
    source = replace_once(source, ORIGINAL_FINALLY, REUSE_FINALLY)
    source = replace_once(source, ORIGINAL_CANCEL_CLOSE, REUSE_CANCEL_CLOSE)
    source = replace_once(source,
        '    public boolean isRetired(){synchronized(lifecycle){return closed&&!running&&!retirementUnconfirmed;}}',
        '    public boolean isRetired(){synchronized(lifecycle){return closed&&!running&&!researchDraining&&researchResourcesRetired&&!retirementUnconfirmed;}}')
    # The numerical engine, tensor handling, note filtering and diffusion loop
    # must remain byte-identical, independently of the complete-source wrapper.
    for start, end in [('    private JSONArray infer(', '    /** HOST RESEARCH ONLY: requests termination'),
                       ('    private void check(', None)]:
        expected_end = '    /** Stops kernels cooperatively;' if start.startswith('    private JSONArray') else end
        before = original.split(start, 1)[1].split(expected_end, 1)[0] if expected_end else original.split(start, 1)[1]
        after = source.split(start, 1)[1].split(end, 1)[0] if end else source.split(start, 1)[1]
        game.require(before == after, 'Session-reuse candidate changed numerical or JNI-result ownership code.')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=VARIANTS, required=True)
    parser.add_argument('--source-samples', type=int, required=True)
    parser.add_argument('--language', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = game.SOURCE.read_text()
    candidate = generate(original, args.variant, source_samples=args.source_samples, language=args.language)
    game.require(not args.output.exists(), 'Use a new isolated candidate directory.')
    args.output.mkdir(parents=True)
    (args.output / 'NativeGame.java').write_text(candidate)
    qualified = game.variant_source(original, args.variant, True, True)
    (args.output / 'session-reuse.patch').write_text(''.join(difflib.unified_diff(
        qualified.splitlines(keepends=True), candidate.splitlines(keepends=True), fromfile='qualified/NativeGame.java', tofile='research-reuse/NativeGame.java')))
    metadata = dict(schema='lightforge.game-session-reuse-candidate.v1', variant=args.variant,
        originalSourceSha256=ORIGINAL_SHA256, qualifiedSourceSha256=hashlib.sha256(qualified.encode()).hexdigest(),
        candidateSourceSha256=hashlib.sha256(candidate.encode()).hexdigest(), sourceSamples=args.source_samples, language=args.language,
        status='GENERATED_NOT_QUALIFIED', hostOnly=True, cancellationAndCloseMayBlock=True,
        appLifecycleEquivalent=False, inferenceExecuted=False, withinProviderParityProven=False,
        benchmarkTimingAdmitted=False, qualityApproved=False, target75Proven=False, releaseAuthorized=False,
        lifecycle='Immediate cooperative termination request followed by a serialized blocking drain; failed/cancelled/closed instances are terminal.',
        scope='One host-only <=64s source. Production models are rehashed every passage. Five successful sessions may persist; RunOptions and all tensors/results remain per-call.')
    (args.output / 'candidate.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
