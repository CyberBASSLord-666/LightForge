/* Bounded PCM WAV reader shared by the neural worker and transport regression tests. */
(function(root){
'use strict';
const measure=(telemetry,name,fn)=>telemetry&&typeof telemetry.measure==='function'?telemetry.measure('performance.'+name,fn):fn();
const text4=(v,p)=>String.fromCharCode(v.getUint8(p),v.getUint8(p+1),v.getUint8(p+2),v.getUint8(p+3));
class WavReader{
 constructor(url,telemetry){this.telemetry=telemetry;this.url=url;this.cached=null;this.totalBytes=null;}
 async body(response,limit){
  // Never cache a multi-gigabyte response from a provider that ignores Range.
  const declared=Number(response.headers.get('Content-Length')||0);
  if(declared>limit){if(response.body)await response.body.cancel();throw new Error('The audio provider returned too much data for this request. Reopen the project in the updated app.');}
  if(!response.body?.getReader){const b=await response.arrayBuffer();if(b.byteLength>limit)throw new Error('The audio transfer exceeded its expected size.');return b;}
  const reader=response.body.getReader(),parts=[];let size=0;
  try{for(;;){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;if(size>limit){await reader.cancel();throw new Error('The audio transfer exceeded its expected size.');}parts.push(value);}}finally{reader.releaseLock();}
  const out=new Uint8Array(size);let offset=0;for(const part of parts){out.set(part,offset);offset+=part.byteLength;}return out.buffer;
 }
 async bytes(start,end){
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<start)throw new Error('Invalid audio read bounds.');
  if(this.cached)return this.cached.slice(start,end+1);
  const r=await fetch(this.url,{cache:'no-store',headers:{Range:`bytes=${start}-${end}`}});
  if(!r.ok)throw new Error(`Cannot open this project's audio (${r.status}). Reopen the project and try again.`);
  if(r.status===206){
   const range=/^bytes (\d+)-(\d+)\/(\d+)$/i.exec(r.headers.get('Content-Range')||'');
   if(!range){if(r.body)await r.body.cancel();throw new Error('The device returned an invalid audio range response. Reopen the project in the updated app.');}
   const first=Number(range[1]),last=Number(range[2]),total=Number(range[3]);
   if(!Number.isSafeInteger(total)||total<=0||first!==start||last!==Math.min(end,total-1)||(this.totalBytes!==null&&this.totalBytes!==total)){
    if(r.body)await r.body.cancel();throw new Error('The audio transfer did not match the requested position. Reopen this project.');
   }
   this.totalBytes=total;
   const b=await this.body(r,last-first+1);
   if(b.byteLength!==last-first+1)throw new Error('The device returned an incomplete audio chunk. Your project is still saved; reopen it in the updated app.');
   return b;
  }
  if(r.status!==200)throw new Error('The audio provider returned an unsupported response.');
  const b=await this.body(r,268435456);
  const length=Number(r.headers.get('Content-Length')||0);
  if(length&&length!==b.byteLength)throw new Error('The audio transfer was interrupted. Reopen this project.');
  this.cached=b;this.totalBytes=b.byteLength;return b.slice(start,end+1);
 }
 async open(){
  const prefix=await this.bytes(0,65535),v=new DataView(prefix);
  if(prefix.byteLength<44||text4(v,0)!=='RIFF'||text4(v,8)!=='WAVE')throw new Error('Analysis needs decoded PCM WAV. Import a music file through the app first.');
  const take=async(start,count)=>start+count<=prefix.byteLength?prefix.slice(start,start+count):this.bytes(start,start+count-1);
  let p=12,found=false,chunks=0;
  while(p+8<=this.totalBytes&&chunks++<4096){
   const header=await take(p,8);if(header.byteLength!==8)break;
   const h=new DataView(header),tag=text4(h,0),size=h.getUint32(4,true);
   if(p+8+size>this.totalBytes)throw new Error('This saved WAV file is incomplete. Restore a project backup or import the original music again.');
   if(tag==='fmt '){
    if(size<16)throw new Error('The WAV format header is incomplete.');
    const f=new DataView(await take(p+8,Math.min(size,40)));
    this.format=f.getUint16(0,true);this.channels=f.getUint16(2,true);this.rate=f.getUint32(4,true);this.align=f.getUint16(12,true);this.bits=f.getUint16(14,true);
    if(this.format===65534&&size>=40)this.format=f.getUint16(24,true);
   }
   if(tag==='data'){this.offset=p+8;this.dataBytes=size;found=true;break;}
   p+=8+size+(size%2);
  }
  if(!found||!this.align)throw new Error('The WAV header is incomplete or unsupported. Import the original music again.');
  if(![22050,44100].includes(this.rate)||![1,3].includes(this.format)||![16,24,32].includes(this.bits)||this.channels<1||this.channels>8||this.align!==this.channels*this.bits/8||(this.format===3&&this.bits!==32)||this.dataBytes%this.align)
   throw new Error('Use the app importer to convert this track to supported PCM audio.');
  this.samples=this.dataBytes/this.align;this.duration=this.samples/this.rate;
  if(!Number.isFinite(this.duration)||this.duration<1)throw new Error('Choose a music file at least one second long.');
  if(this.duration>14400.05)throw new Error('Tesla supports shows up to four hours. Trim this track before importing.');
 }
 async mono22050(start,count,config){const factor=this.rate/22050,margin=factor===2?31:0,rawStart=Math.floor(start*factor)-margin,rawEnd=Math.ceil((start+count-1)*factor)+margin+1,lo=Math.max(0,rawStart),hi=Math.min(this.samples,rawEnd);let raw=new Float32Array(Math.max(0,rawEnd-rawStart));if(hi>lo){const b=await this.bytes(this.offset+lo*this.align,this.offset+hi*this.align-1);if(b.byteLength!==(hi-lo)*this.align)throw new Error('The audio transfer was incomplete. Your project is still saved; reopen it in the updated app.');measure(this.telemetry,'audio_decode',()=>{const v=new DataView(b),width=this.bits/8;for(let i=0;i<hi-lo;i++){let sum=0;for(let c=0;c<this.channels;c++){let p=i*this.align+c*width,a;if(this.format===3)a=v.getFloat32(p,true);else if(this.bits===16)a=v.getInt16(p,true)/32768;else if(this.bits===32)a=v.getInt32(p,true)/2147483648;else{let n=v.getUint8(p)|(v.getUint8(p+1)<<8)|(v.getUint8(p+2)<<16);if(n&0x800000)n|=0xff000000;a=n/8388608;}sum+=Number.isFinite(a)?a:0;}raw[lo-rawStart+i]=sum/this.channels;}});}
 const out=new Float32Array(count);if(factor===1){out.set(raw.subarray(-rawStart+start,-rawStart+start+count));}else{measure(count>0?this.telemetry:null,'resample_normalize',()=>{const filter=config.resampleHalfFIR;for(let i=0;i<count;i++){let center=(start+i)*2-rawStart,sum=0;for(let j=0;j<filter.length;j++)sum+=(raw[center+j-31]||0)*filter[j];out[i]=sum;}});}return out;}
 async stereo44100(start,count){
  if(this.rate!==44100)throw new Error('Voice separation needs the original 44.1 kHz music. Import the track through the app first.');
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(count)||count<0||count>44100*40)throw new Error('Invalid stereo audio read bounds.');
  const output=[new Float32Array(count),new Float32Array(count)],lo=Math.max(0,start),hi=Math.min(this.samples,start+count);
  if(hi<=lo)return output;
  const bytes=await this.bytes(this.offset+lo*this.align,this.offset+hi*this.align-1);
  if(bytes.byteLength!==(hi-lo)*this.align)throw new Error('The stereo audio transfer was incomplete. Reopen the project and try again.');
  measure(this.telemetry,'audio_decode',()=>{
  const view=new DataView(bytes),width=this.bits/8;
  for(let i=0;i<hi-lo;i++)for(let c=0;c<2;c++){
   const at=i*this.align+Math.min(c,this.channels-1)*width;let sample;
   if(this.format===3)sample=view.getFloat32(at,true);
   else if(this.bits===16)sample=view.getInt16(at,true)/32768;
   else if(this.bits===32)sample=view.getInt32(at,true)/2147483648;
   else{let value=view.getUint8(at)|(view.getUint8(at+1)<<8)|(view.getUint8(at+2)<<16);if(value&0x800000)value|=0xff000000;sample=value/8388608;}
   output[c][lo-start+i]=Number.isFinite(sample)?sample:0;
  }
  });
  return output;
 }
}
root.LightForgeWavReader=WavReader;
if(typeof module!=='undefined'&&module.exports)module.exports=WavReader;
})(typeof self!=='undefined'?self:globalThis);
