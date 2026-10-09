'use strict';
// Frozen LightForge de831259 resampler; verification oracle only.
const resamplePhases=Array.from({length:320},(_,p)=>{const a=new Float64Array(64),fraction=p/320,cutoff=16000/22050*.94;let sum=0;for(let j=0;j<64;j++){const x=j-31-fraction,w=.42+.5*Math.cos(Math.PI*x/32)+.08*Math.cos(2*Math.PI*x/32),v=Math.abs(x)<1e-10?cutoff:Math.sin(Math.PI*cutoff*x)/(Math.PI*x);a[j]=v*w;sum+=a[j];}for(let j=0;j<64;j++)a[j]/=sum;return a;});
async function pcm16000(reader,start,count,config,telemetry){
 const first=Math.floor(start*441/320)-32,last=Math.ceil((start+count-1)*441/320)+33;
 const raw=await reader.mono22050(first,last-first,config);
 const resample=()=>{const out=new Float32Array(count);
 for(let i=0;i<count;i++){const numerator=(start+i)*441,center=Math.floor(numerator/320),phase=numerator-center*320,filter=resamplePhases[phase];let sum=0;for(let j=0;j<64;j++)sum+=(raw[center-31+j-first]||0)*filter[j];out[i]=sum;}
 return out;};
 return telemetry?.measure?telemetry.measure('performance.resample_normalize',resample,{component:'vocal'}):resample();
}
module.exports={pcm16000};
