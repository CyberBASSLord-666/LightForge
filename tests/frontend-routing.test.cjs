'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..');
function load(){let logs=0;const math=Object.create(Math);math.log2=x=>{logs++;return Math.log2(x);};const context=vm.createContext({Math:math});vm.runInContext(fs.readFileSync(path.join(root,'web/analysis/dsp.js'),'utf8'),context);return {dsp:context.LightForgeDSP,logs:()=>logs};}
const frequencies=[0,59.999,60,179.999,180,2399.999,2400,4000,4000.001,Infinity,-Infinity,NaN];
function config(){return {windowLength:1411,hop:441,bands:Array.from({length:136},(_,i)=>({frequency:frequencies[i%frequencies.length],start:i%5,weights:[.2,.37,.61]}))};}
function referenceRouting(cfg,magnitudes,previous,hadFrame){
 const result={features:new Float32Array(magnitudes.length*272),bass:new Float32Array(magnitudes.length),mid:new Float32Array(magnitudes.length),high:new Float32Array(magnitudes.length),colour:new Float32Array(magnitudes.length*3),chroma:new Float32Array(magnitudes.length*12)};
 for(let f=0;f<magnitudes.length;f++){
  for(let b=0;b<136;b++){
   const band=cfg.bands[b];let sum=0;for(let k=0;k<band.weights.length;k++)sum+=magnitudes[f][band.start+k]*band.weights[k];
   const value=Math.log10(1+sum),difference=hadFrame?Math.max(0,value-previous[b]):0;
   result.features[f*272+b]=value;result.features[f*272+136+b]=difference;previous[b]=value;
   if(band.frequency>=60&&band.frequency<=4000){const pitch=((Math.round(69+12*Math.log2(band.frequency/440))%12)+12)%12;result.chroma[f*12+pitch]+=value;}
   const channel=band.frequency<180?0:band.frequency<2400?1:2;result.colour[f*3+channel]+=value;result[['bass','mid','high'][channel]][f]+=difference;
  }
  hadFrame=true;
 }
 return result;
}
function sameBits(left,right){assert.equal(left.byteLength,right.byteLength);assert.equal(Buffer.compare(Buffer.from(left.buffer,left.byteOffset,left.byteLength),Buffer.from(right.buffer,right.byteOffset,right.byteLength)),0);}
test('routing retains reference Float32 tensors across frequency edges and mutable chunks',()=>{
 const api=load(),cfg=config(),extractor=new api.dsp.FeatureExtractor(cfg),previous=new Float32Array(136);let hadFrame=false;
 for(let chunk=0;chunk<5;chunk++){
  if(chunk===1)cfg.bands[0].frequency=110;
  if(chunk===2)cfg.bands[1]={frequency:2400,start:2,weights:[.7,.01]};
  if(chunk===3)cfg.bands=cfg.bands.slice().reverse();
  if(chunk===4)extractor.cfg={...cfg,bands:cfg.bands.map(b=>({...b,frequency:82.406}))};
  const current=extractor.cfg,frames=chunk+2,magnitudes=Array.from({length:frames},(_,f)=>Float64Array.from({length:8},(_,k)=>.03+(chunk+1)*(f+1)*(k+1)/91));let at=0;
  extractor.spectrum.run=()=>magnitudes[at++];
  const actual=extractor.extract(new Float32Array(frames*441+1411),0,frames),expected=referenceRouting(current,magnitudes,previous,hadFrame);hadFrame=true;
  for(const key of Object.keys(expected))sameBits(actual[key],expected[key]);
 }
});
test('unchanged routing avoids repeated transcendental work without freezing caller config',()=>{
 const api=load(),cfg=config(),extractor=new api.dsp.FeatureExtractor(cfg);extractor.spectrum.run=()=>new Float64Array(8).fill(.1);
 const pcm=new Float32Array(5000);extractor.extract(pcm,0,4);const first=api.logs();assert.ok(first>0);
 extractor.extract(pcm,0,4);assert.equal(api.logs(),first);
 cfg.bands[0].frequency=110;extractor.extract(pcm,0,4);assert.equal(api.logs(),first+1);
 assert.equal(extractor.extract(pcm,0,0).features.length,0);assert.equal(api.logs(),first+1);
});
