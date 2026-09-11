'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),{webcrypto}=require('node:crypto');
// Isolated execution of the actual worker with Node's standard WebCrypto/gzip.
// Browser worker transport has a separate end-to-end harness.
module.exports=async function runWorker(directory,payload,{onMessage}={}){
 let result,error;
 const context=vm.createContext({console,crypto:webcrypto,TextEncoder,TextDecoder,Uint8Array,Float32Array,ArrayBuffer,DataView,Blob,Response,ReadableStream,CompressionStream,DecompressionStream,atob,btoa,performance,setTimeout,clearTimeout});
 context.self=context;context.postMessage=data=>{onMessage?.(structuredClone(data));if(data.type==='result')result=data.value;else if(data.type==='error')error=Error(data.message);};
 context.importScripts=(...files)=>{for(const f of files)vm.runInContext(fs.readFileSync(path.join(directory,f),'utf8'),context,{filename:f});};
 context.importScripts('worker.js');await context.self.onmessage({data:structuredClone(payload)});if(error)throw error;if(!result)throw Error('Worker returned no result.');return result;
};
