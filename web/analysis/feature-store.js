/* Content-addressed, opt-in cache for reusable deterministic analysis features.
 * It deliberately owns no decoder/model and never changes a pipeline result on
 * a miss: analyzers may read it only when their feature semantics match exactly.
 */
(function(root){'use strict';
const SCHEMA_VERSION=1,DOMAIN='shared-features',MAX_FEATURE_NAME=48;
const validSha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const validFeature=value=>typeof value==='string'&&/^[a-z][a-z0-9-]{0,47}$/.test(value);
const validVersion=value=>typeof value==='string'&&value.length>0&&value.length<=128;
const plain=value=>value&&Object.prototype.toString.call(value)==='[object Object]';
function cloneJson(value,path='value',depth=0){
 if(depth>32)throw Error('Feature cache metadata is too deeply nested.');
 if(value===null||typeof value==='string'||typeof value==='boolean')return value;
 if(typeof value==='number'){if(!Number.isFinite(value))throw Error('Feature cache metadata contains an invalid number at '+path+'.');return value;}
 if(Array.isArray(value))return value.map((item,index)=>cloneJson(item,path+'['+index+']',depth+1));
 if(plain(value)){const result={};for(const key of Object.keys(value).sort())result[key]=cloneJson(value[key],path+'.'+key,depth+1);return result;}
 throw Error('Feature cache metadata must contain only JSON values at '+path+'.');
}
function validateValue(value,path='value',depth=0){
 if(depth>32)throw Error('Feature cache value is too deeply nested.');
 if(value===null||typeof value==='string'||typeof value==='boolean')return;
 if(typeof value==='number'){if(!Number.isFinite(value))throw Error('Feature cache value contains an invalid number at '+path+'.');return;}
 if(value instanceof Float32Array){for(const sample of value)if(!Number.isFinite(sample))throw Error('Feature cache value contains invalid float samples.');return;}
 if(Array.isArray(value)){for(let i=0;i<value.length;i++)validateValue(value[i],path+'['+i+']',depth+1);return;}
 if(plain(value)){for(const [key,item]of Object.entries(value))validateValue(item,path+'.'+key,depth+1);return;}
 throw Error('Feature cache value must be JSON or Float32 data at '+path+'.');
}
function normalizeIdentity(value){
 if(!plain(value))throw Error('Feature cache identity is required.');
 const audioIdentity=value.audioIdentity||value.audioSha256;
 if(!validSha(audioIdentity))throw Error('Feature cache identity requires an audio SHA-256.');
 if(!validVersion(value.preprocessingVersion))throw Error('Feature cache identity requires a preprocessing version.');
 if(!plain(value.modelVersions)||!Object.keys(value.modelVersions).length)throw Error('Feature cache identity requires model versions.');
 const modelVersions={};for(const key of Object.keys(value.modelVersions).sort()){if(!/^[a-z][a-z0-9_.-]{0,63}$/.test(key)||!validVersion(value.modelVersions[key]))throw Error('Invalid feature cache model version.');modelVersions[key]=value.modelVersions[key];}
 return {schemaVersion:SCHEMA_VERSION,domain:DOMAIN,audioIdentity,preprocessingVersion:value.preprocessingVersion,modelVersions,analysisConfiguration:cloneJson(value.analysisConfiguration??value.configuration??{},'analysisConfiguration')};
}
function names(feature){
 if(!validFeature(feature)||feature.length>MAX_FEATURE_NAME)throw Error('Invalid feature cache name.');
 const prefix='feature-'+feature;
 return {prefix,json:prefix+'-json',float:prefix+'-float',meta:prefix+'-float-meta'};
}
function validDescriptor(record,feature,key){
 return plain(record)&&record.schemaVersion===SCHEMA_VERSION&&record.domain===DOMAIN&&record.feature===feature&&record.identityKey===key;
}
async function open(identity){
 const storeApi=root.LightForgeAnalysisStore;
 if(!storeApi||typeof storeApi.open!=='function'||typeof storeApi.contentAddress!=='function')throw Error('Recoverable analysis storage is unavailable.');
 const normalized=normalizeIdentity(identity),key=await storeApi.contentAddress(DOMAIN,normalized);
 // A FeatureStore is deliberately portable across projects: source/project IDs
 // are neither an identity input nor a substitute for the audio digest.
 const store=await storeApi.open(key,{sourceId:''});
 async function discardInvalid(prefix){try{await store.invalidate([prefix]);}catch(_){} }
 async function read(feature){
  const item=names(feature),record=await store.read(item.json);
  if(record===null)return null;
  if(!validDescriptor(record,feature,key)||!Object.prototype.hasOwnProperty.call(record,'value')){await discardInvalid(item.prefix);return null;}
  try{validateValue(record.value);cloneJson(record.metadata??{},'metadata');}catch(_){await discardInvalid(item.prefix);return null;}
  return {value:record.value,metadata:record.metadata??{}};
 }
 async function write(feature,value,metadata={}){
  const item=names(feature);validateValue(value);const cleanMetadata=cloneJson(metadata,'metadata');
  // Fence every feature kind before publishing its replacement. A reader sees
  // either the old committed feature or a miss, never a JSON/Float32 mix.
  await store.invalidate([item.prefix]);
  await store.write(item.json,{schemaVersion:SCHEMA_VERSION,domain:DOMAIN,feature,identityKey:key,metadata:cleanMetadata,value});
  return {identityKey:key,feature,kind:'json'};
 }
 async function readFloat32(feature){
  const item=names(feature),record=await store.read(item.meta);
  if(record===null)return null;
  if(!validDescriptor(record,feature,key)||!Array.isArray(record.lengths)||record.lengths.length<1||record.lengths.length>4||record.lengths.some(length=>!Number.isSafeInteger(length)||length<1)){await discardInvalid(item.prefix);return null;}
  const arrays=await store.readFloats(item.float);
  if(!arrays||arrays.length!==record.lengths.length||arrays.some((array,index)=>array.length!==record.lengths[index])){await discardInvalid(item.prefix);return null;}
  try{cloneJson(record.metadata??{},'metadata');}catch(_){await discardInvalid(item.prefix);return null;}
  return {arrays,metadata:record.metadata??{}};
 }
 async function writeFloat32(feature,arrays,metadata={}){
  const item=names(feature);
  if(!Array.isArray(arrays)||!arrays.length||arrays.length>4||arrays.some(array=>!(array instanceof Float32Array)||!array.length))throw Error('Feature cache Float32 payload is invalid.');
  for(const array of arrays)for(const value of array)if(!Number.isFinite(value))throw Error('Feature cache Float32 payload contains invalid samples.');
  const cleanMetadata=cloneJson(metadata,'metadata'),lengths=arrays.map(array=>array.length);
  // Fence before writing. The binary record is durable before its descriptor;
  // a crash between writes leaves an unreachable orphan, never a false hit.
  await store.invalidate([item.prefix]);
  await store.writeFloats(item.float,arrays);
  await store.write(item.meta,{schemaVersion:SCHEMA_VERSION,domain:DOMAIN,feature,identityKey:key,metadata:cleanMetadata,lengths});
  return {identityKey:key,feature,kind:'float32',lengths};
 }
 async function invalidate(features){
  if(!Array.isArray(features)||!features.length)throw Error('Feature cache invalidation requires feature names.');
  return store.invalidate([...new Set(features.map(feature=>names(feature).prefix))]);
 }
 function diagnostics(){
  const cache=typeof store.diagnostics==='function'?store.diagnostics():{};
  return {schemaVersion:SCHEMA_VERSION,domain:DOMAIN,identityKey:key,cache};
 }
 return {schemaVersion:SCHEMA_VERSION,domain:DOMAIN,identityKey:key,read,write,readFloat32,writeFloat32,invalidate,diagnostics};
}
root.LightForgeFeatureStore={open,normalizeIdentity,featureNames:names,schemaVersion:SCHEMA_VERSION,domain:DOMAIN};
if(typeof module!=='undefined'&&module.exports)module.exports=root.LightForgeFeatureStore;
})(typeof self!=='undefined'?self:globalThis);
