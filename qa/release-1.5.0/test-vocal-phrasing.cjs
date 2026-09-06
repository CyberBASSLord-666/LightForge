const test=require('node:test'),assert=require('node:assert/strict');
const V=require('../../web/analysis/vocal.js'),model=require('../../web/analysis/models/vocal-model.json');
test('singing class selection includes trained specific singing classes and excludes speech',()=>{
 const names=model.singingClassIds.map(i=>model.classNames[i]);for(const n of ['Male singing','Female singing','Child singing','Singing','Choir'])assert(names.includes(n));
 assert(model.speechClassIds.every(i=>!model.singingClassIds.includes(i)));
});
test('confident regions preserve onset origin, silence gaps and compact envelopes',()=>{
 const scores=new Float32Array(250).fill(.75),detail=new Float32Array(500).fill(1);detail.fill(0,0,50);detail.fill(0,450);detail.fill(0,200,206);
 const result=V.summarize(scores,detail,10,model);assert.equal(result.presence,'detected');assert(result.phrases.length>=1);assert(result.phrases[0].start>=.96);assert(result.phrases.at(-1).end<=9.04);
 for(let i=0;i<500;i++){assert(Number.isFinite(result.envelope[i]));assert(result.envelope[i]>=0&&result.envelope[i]<=1);assert(Math.abs(result.envelope[i]*1000-Math.round(result.envelope[i]*1000))<1e-7);if(!detail[i])assert.equal(result.envelope[i],0);}
 for(const p of result.phrases){assert(p.confidence>=.55);assert.equal(p.estimated,true);assert(p.start>=0&&p.end<=10);}
});
test('weak singing evidence and zero PCM do not invent singing cues',()=>{
 const weak=V.summarize(new Float32Array(250).fill(.21),new Float32Array(500).fill(1),10,model);assert.equal(weak.presence,'uncertain');assert.equal(weak.phrases.length,0);assert(weak.envelope.every(x=>x===0));
 const silent=V.summarize(new Float32Array(250).fill(.85),new Float32Array(500),10,model);assert.equal(silent.phrases.length,0);assert.equal(silent.accents.length,0);assert(silent.envelope.every(x=>x===0));
});
test('nonmultiple tail stays within actual audio, including very short analysis spans',()=>{
 for(const duration of [1,1.013,1.0136,9.999,10,10.001,13.337]){
  const r=V.summarize(new Float32Array(Math.ceil(duration/.04)).fill(.8),new Float32Array(Math.ceil(duration/.02)).fill(1),duration,model);
  assert(r.phrases.every(p=>p.start>=0&&p.end<=duration&&p.end>p.start));assert.equal(r.envelope.length,Math.ceil(duration/.02));
 }
});
