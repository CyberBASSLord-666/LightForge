/* Frozen Float32 frontend oracle from LightForge 2.3.2.
 * Source commit: 1cdc96773b2a5c54411d2a7170a799dd19efd7ea.
 * This reference intentionally retains per-frame trigonometry and computes
 * every reflected STFT window independently. Never used by the application.
 */
'use strict';
const RATE=16000,FFT=512,WIN=400,HOP=160,BANDS=128,CONTEXT=160000,FRAMES=1000,OUTPUT=250;
const clamp=(n,a=0,b=1)=>Math.min(b,Math.max(a,n));
const reverse=Uint16Array.from({length:FFT},(_,i)=>{let r=0;for(let b=0;b<9;b++){r=(r<<1)|(i&1);i>>=1;}return r;});
function reflect(i,n){if(n<=1)return 0;while(i<0||i>=n)i=i<0?-i:2*n-2-i;return i;}
function logMel(pcm,frontend){
 const frames=Math.floor((pcm.length-1)/HOP)+1,out=new Float32Array(frames*BANDS),re=new Float64Array(FFT),im=new Float64Array(FFT),power=new Float64Array(257),preamp=new Float32Array(Math.max(1,pcm.length-1));
 // Author's Conv1D [-.97, 1] shortens by one sample. torch.stft centers
 // the 400-point nonperiodic Hann in a 512-point FFT, reflect-padding PCM.
 for(let i=0;i<pcm.length-1;i++)preamp[i]=pcm[i+1]-.97*pcm[i];
 for(let f=0;f<frames;f++){
  re.fill(0);im.fill(0);for(let i=0;i<WIN;i++)re[reverse[56+i]]=preamp[reflect(f*HOP-200+i,preamp.length)]*frontend.windowValues[i];
  for(let len=2;len<=FFT;len*=2){const half=len/2;for(let j=0;j<half;j++){const c=Math.cos(-2*Math.PI*j/len),s=Math.sin(-2*Math.PI*j/len);for(let i=j;i<FFT;i+=len){const k=i+half,r=re[k]*c-im[k]*s,t=re[k]*s+im[k]*c;re[k]=re[i]-r;im[k]=im[i]-t;re[i]+=r;im[i]+=t;}}}
  for(let k=0;k<=256;k++)power[k]=re[k]*re[k]+im[k]*im[k];
  for(let b=0;b<BANDS;b++){let sum=0;for(const [k,w] of frontend.melWeights[b])sum+=power[k]*w;out[b*frames+f]=(Math.log(Math.max(1e-7,sum))+4.5)/5;}
 }
 return out;
}
module.exports={logMel};
