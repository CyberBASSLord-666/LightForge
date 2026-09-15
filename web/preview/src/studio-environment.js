import * as THREE from 'three';
// The full 256-face CubeUV atlas, including every PMREM roughness level.
// Lossless gzip retains the original RGBA half-float lighting values.
export const STUDIO_ENVIRONMENT = Object.freeze({width:768,height:1024,bytes:6291456,url:'preview/models/studio-environment.rgba16f.gz'});
export async function loadStudioEnvironment() {
 const response=await fetch(STUDIO_ENVIRONMENT.url);
 if(!response.ok)throw Error('The offline studio lighting could not be read.');
 const compressed=await response.arrayBuffer();
 if(!compressed.byteLength||compressed.byteLength>STUDIO_ENVIRONMENT.bytes)throw Error('The offline studio lighting archive is invalid.');
 const stream=new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'));
 const reader=stream.getReader(),bytes=new Uint8Array(STUDIO_ENVIRONMENT.bytes);let offset=0;
 try{
  while(true){const {done,value}=await reader.read();if(done)break;if(offset+value.length>bytes.length)throw Error('The offline studio lighting size is invalid.');bytes.set(value,offset);offset+=value.length;}
 }finally{await reader.cancel();reader.releaseLock();}
 if(offset!==bytes.length)throw Error('The offline studio lighting is incomplete.');
 // Assets use explicit little-endian half-floats, independently of host order.
 const data=new Uint16Array(bytes.length/2),view=new DataView(bytes.buffer);
 for(let i=0;i<data.length;i++)data[i]=view.getUint16(i*2,true);
 return data;
}
export function createStudioEnvironmentTexture(data) {
 if(!(data instanceof Uint16Array)||data.byteLength!==STUDIO_ENVIRONMENT.bytes)throw Error('The offline studio lighting is unavailable.');
 const texture=new THREE.DataTexture(data,STUDIO_ENVIRONMENT.width,STUDIO_ENVIRONMENT.height,THREE.RGBAFormat,THREE.HalfFloatType);
 texture.mapping=THREE.CubeUVReflectionMapping;texture.colorSpace=THREE.LinearSRGBColorSpace;
 texture.minFilter=THREE.LinearFilter;texture.magFilter=THREE.LinearFilter;
 texture.generateMipmaps=false;texture.flipY=false;texture.needsUpdate=true;
 return texture;
}
