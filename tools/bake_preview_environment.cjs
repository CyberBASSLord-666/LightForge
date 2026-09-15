'use strict';
// Reproduce the lossless studio PMREM asset using the pinned Three.js build.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),zlib=require('node:zlib');
const root=path.resolve(__dirname,'..');
const graphics=process.env.LF_GRAPHICS_NODE_MODULES||path.resolve(root,'../toolchain/graphics/node_modules');
const esbuild=require(path.join(graphics,'esbuild'));
const {chromium}=require('playwright');
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
(async()=>{
 const module=path.join(root,'web/preview/src/studio-environment-source.js');
 const bundle=await esbuild.build({stdin:{contents:`import * as THREE from 'three';import {createStudioEnvironmentScene} from ${JSON.stringify(module)};
 window.bakeStudio=()=>{
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance',stencil:false});
  const scene=createStudioEnvironmentScene(THREE),generator=new THREE.PMREMGenerator(renderer),target=generator.fromScene(scene,.055);
  const data=new Uint16Array(target.width*target.height*4);renderer.readRenderTargetPixels(target,0,0,target.width,target.height,data);
  const bytes=new Uint8Array(data.length*2),view=new DataView(bytes.buffer);for(let i=0;i<data.length;i++)view.setUint16(i*2,data[i],true);
  let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));
  const result={width:target.width,height:target.height,bytes:btoa(text),three:THREE.REVISION};
  target.dispose();generator.dispose();scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});renderer.dispose();return result;
 };`,resolveDir:root,loader:'js'},write:false,bundle:true,format:'iife',target:['chrome91'],nodePaths:[graphics]});
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader']});
 try{
  const page=await browser.newPage();await page.addScriptTag({content:bundle.outputFiles[0].text});
  const result=await page.evaluate(()=>bakeStudio()),bytes=Buffer.from(result.bytes,'base64');
  if(result.width!==768||result.height!==1024||bytes.length!==6291456||result.three!=='180')throw Error('Unexpected PMREM format or Three.js revision');
  const output=path.join(root,'web/preview/models/studio-environment.rgba16f.gz');
  const metadata={schema:'lightforge.studio-environment.v1',three_revision:result.three,browser:browser.version(),mapping:'CubeUVReflectionMapping',color_space:'LinearSRGBColorSpace',format:'RGBA16F little-endian',width:result.width,height:result.height,bytes:bytes.length,sha256:sha(bytes),source_sha256:sha(fs.readFileSync(module)),graphics_lock_sha256:sha(fs.readFileSync(path.join(root,'web/preview/src/package-lock.json'))),sigma_radians:.055,cube_size:256};
  if(process.argv.includes('--check')){
   if(!bytes.equals(zlib.gunzipSync(fs.readFileSync(output))))throw Error('The baked studio atlas differs from this renderer output');
  }else{
   fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,zlib.gzipSync(bytes,{level:9}));
   fs.writeFileSync(output+'.json',JSON.stringify({...metadata,compressed_bytes:fs.statSync(output).size,compressed_sha256:sha(fs.readFileSync(output))},null,2)+'\n');
  }
  console.log(JSON.stringify({...metadata,mode:process.argv.includes('--check')?'verified':'baked'},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
