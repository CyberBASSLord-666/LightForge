/* Independent numerical audit: absolute audio time, chunk seams and anti-aliasing. */
const fs=require('fs'),path=require('path'),assert=require('assert'),crypto=require('crypto');
const ROOT=path.resolve(__dirname,'../..'),source=path.join(ROOT,'web/analysis/vocal.js');
const vocal=require(source);
const readerFor=signal=>({duration:signal.length/22050,async mono22050(first,count){return Float32Array.from({length:count},(_,i)=>signal[first+i]||0);}});
const rms=a=>Math.sqrt(a.reduce((s,v)=>s+v*v,0)/Math.max(1,a.length));
(async()=>{
 const sine=(hz,length=22050)=>Float32Array.from({length},(_,i)=>.5*Math.sin(2*Math.PI*hz*i/22050));
 const mixed=Float32Array.from({length:22050},(_,i)=>.3*Math.sin(2*Math.PI*211*i/22050)+.2*Math.cos(2*Math.PI*6111*i/22050));
 const whole=await vocal.pcm16000(readerFor(mixed),0,16000,{}),parts=new Float32Array(16000);
 for(const [start,count] of [[0,3341],[3341,6023],[9364,6636]])parts.set(await vocal.pcm16000(readerFor(mixed),start,count,{}),start);
 const chunkMaxError=Math.max(...whole.map((v,i)=>Math.abs(v-parts[i])));assert.strictEqual(chunkMaxError,0,'Chunk boundaries changed rational audio coordinates');
 const impulse=new Float32Array(22050);impulse[8820]=1;
 const response=await vocal.pcm16000(readerFor(impulse),0,16000,{});
 let peakIndex=0;for(let i=0;i<response.length;i++)if(Math.abs(response[i])>Math.abs(response[peakIndex]))peakIndex=i;
 assert.strictEqual(peakIndex,6400,'Resampler introduced an audio-time offset');
 const pass=await vocal.pcm16000(readerFor(sine(6000)),0,16000,{}),stop=await vocal.pcm16000(readerFor(sine(9000)),0,16000,{});
 const passDb=20*Math.log10(rms(pass.slice(200,-200))/(.5/Math.sqrt(2))),stopDb=20*Math.log10(rms(stop.slice(200,-200))/(.5/Math.sqrt(2)));
 assert(Math.abs(passDb)<.1,`6kHz passband attenuated ${passDb}dB`);assert(stopDb< -40,`9kHz input aliased at ${stopDb}dB`);
 const quiet=await vocal.pcm16000(readerFor(new Float32Array(13)), -17,1000,{});assert(quiet.every(x=>x===0));
 let frontend=null;const gp=path.join(__dirname,'vocal-fixtures/sed-frontend-reference.json');if(fs.existsSync(gp)){const g=JSON.parse(fs.readFileSync(gp)),front=JSON.parse(fs.readFileSync(path.join(ROOT,'web/analysis/models/vocal-frontend.json'))),actual=vocal.logMel(Float32Array.from(g.pcm),front);let maximum=0,squared=0;assert.equal(actual.length,g.mel.length);for(let i=0;i<actual.length;i++){const d=actual[i]-g.mel[i];maximum=Math.max(maximum,Math.abs(d));squared+=d*d;}assert(maximum<.001);frontend={values:actual.length,maxAbsError:maximum,rmsError:Math.sqrt(squared/actual.length)};}
 let chunkSchedules=0;for(const duration of [.001,.02,.04,.5,9.99,10,10.001,10.04,15.97,16,17,21.9,22,238.333,14400]){const n=Math.ceil(duration/.04),starts=vocal.chunkStarts(duration),coverage=new Uint16Array(n);for(const first of starts){assert(first>=0&&Number.isInteger(first));for(let i=first;i<Math.min(n,first+250);i++)coverage[i]++;}assert(coverage.every(x=>x>0));chunkSchedules++;}
 const results={frontend,gapFreeChunkSchedules:chunkSchedules,passed:true,release:'1.5.0',scope:'Independent analytic resampling checks; not vocal classification accuracy',chunkMaxError,impulse:{sourceSample:8820,sourceRate:22050,destinationSample:peakIndex,destinationRate:16000,delayMs:0},passband6000HzDb:passDb,stopband9000HzDb:stopDb,shortSilentTailFinite:quiet.every(Number.isFinite),source_hashes:{'web/analysis/vocal.js':crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex')}};
 fs.writeFileSync(path.join(__dirname,'vocal-resampling-audit.json'),JSON.stringify(results,null,2)+'\n');console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
