'use strict';

/*
 * These are checked-in analysis snapshots, not audio fixtures. They let the
 * FSEQ/choreography regression run without shipping the external Sample.wav
 * source used when the snapshots were originally captured.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {isDeepStrictEqual}=require('node:util');

const root=path.resolve(__dirname,'..');
const EXPECTED=Object.freeze([
  {file:'baseline-demo-music.json',lineage:'baseline',track:'demo',analysisVersion:1,bytes:186709,sha256:'18b5ecdc10ba976de474d580e174106d292ffe88c2544dd5023459e2cb864319',duration:64,beats:99,downbeats:25,sections:4},
  {file:'baseline-sample-music.json',lineage:'baseline',track:'sample',analysisVersion:1,bytes:594175,sha256:'33a2aed406a0842c24e6895882e27b0c17d6c8da81136066e1f792c69959c39b',duration:238.04,beats:369,downbeats:93,sections:12},
  {file:'current-demo-music.json',lineage:'current',track:'demo',analysisVersion:2,bytes:199911,sha256:'b5c925d1f3eb4d1c36b043587849c161186a99039f88537660b0f58bd5958533',duration:64,beats:99,downbeats:25,sections:4,phrases:7,impacts:24},
  {file:'current-sample-music.json',lineage:'current',track:'sample',analysisVersion:2,bytes:641621,sha256:'74764bd55772fcd54769423c5931f906fb1eb1a1706e541df2cad2a716dc7ad1',duration:238.04,beats:369,downbeats:92,sections:14,phrases:27,impacts:75},
]);
const EXPECTED_SAMPLE_AUDIO=Object.freeze({
  path:'upload/Sample.wav',channels:2,sampleRate:48000,sampleWidth:2,frames:11425919,
  duration:238.03997916666665,bytes:45703720,
  sha256:'1904d9697a1cb3640bcfdc5b1ede23f7512105976c7b662b08423a5e4cca99d8',
  chunks:[
    {tag:'fmt ',declaredBytes:16,availableBytes:16,offset:20},
    {tag:'data',declaredBytes:45703676,availableBytes:45703676,offset:44},
  ],
  payloadComplete:true,
});
const EXPECTED_PROVENANCE=Object.freeze({
  baselineCapture:{file:'qa/music-1.3.0/capture-baseline.cjs',bytes:1536,sha256:'99c8c3f2063be3d8af19153a55c53528f946fe88f6ec3d8c9dccb86cbe2f3d2a'},
  currentCapture:{file:'qa/music-1.3.0/capture-analysis.cjs',bytes:3319,sha256:'084c5f15222e0f6e7dec2dddfb43ad9fc9fbd343531d130282d6fcc41efc1562'},
  sampleSourceAudio:{
    availability:'external-not-shipped',requiredFor:'recapture-only',requiredByPlannerRegression:false,
    metadata:{file:'qa/music-1.3.0/audio-metadata.json',bytes:1743,sha256:'74295316510fb392870ad73a565c2e82a967d775b35ba3fa73cdea117623779a',sample:EXPECTED_SAMPLE_AUDIO},
  },
});
const PROVENANCE_FILES=Object.freeze([
  ['baseline capture',EXPECTED_PROVENANCE.baselineCapture],
  ['current capture',EXPECTED_PROVENANCE.currentCapture],
  ['Sample.wav metadata',EXPECTED_PROVENANCE.sampleSourceAudio.metadata],
]);

const isObject=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const add=(errors,condition,message)=>{if(!condition)errors.push(message);};
const digest=content=>crypto.createHash('sha256').update(content).digest('hex');

function pinnedPath(rootDir,descriptor){
  if(!isObject(descriptor)||typeof descriptor.file!=='string')return null;
  const file=path.resolve(rootDir,descriptor.file);
  return file.startsWith(rootDir+path.sep)?file:null;
}

function readPinnedFile(rootDir,descriptor,label,errors){
  const file=pinnedPath(rootDir,descriptor);
  if(!file){errors.push(label+' has an invalid pinned path');return null;}
  let stat;
  try{stat=fs.lstatSync(file);}
  catch(error){errors.push('required pinned '+label+' is unavailable ('+descriptor.file+'): '+error.message);return null;}
  if(!stat.isFile()||stat.isSymbolicLink()){
    errors.push(label+' must be a regular non-symlink committed file');
    return null;
  }
  let content;
  try{content=fs.readFileSync(file);}
  catch(error){errors.push('required pinned '+label+' could not be read: '+error.message);return null;}
  add(errors,content.byteLength===descriptor.bytes,label+' byte length changed (expected '+descriptor.bytes+', got '+content.byteLength+')');
  add(errors,digest(content)===descriptor.sha256,label+' SHA-256 changed');
  return content;
}

function verifySampleMetadata(metadata,errors){
  const matches=Array.isArray(metadata)?metadata.filter(item=>isObject(item)&&item.path===EXPECTED_SAMPLE_AUDIO.path):[];
  add(errors,matches.length===1,'audio metadata must contain exactly one Sample.wav record');
  if(matches.length===1)add(errors,isDeepStrictEqual(matches[0],EXPECTED_SAMPLE_AUDIO),'Sample.wav provenance identity or WAV geometry changed');
}

function verifyProvenance(rootDir,errors){
  for(const [label,descriptor] of PROVENANCE_FILES){
    const content=readPinnedFile(rootDir,descriptor,label,errors);
    if(label!=='Sample.wav metadata'||content===null)continue;
    let metadata;
    try{metadata=JSON.parse(content.toString('utf8'));}
    catch(error){errors.push('Sample.wav metadata is not valid JSON: '+error.message);continue;}
    verifySampleMetadata(metadata,errors);
  }
}

function provenanceErrors(rootDir){
  const errors=[];
  verifyProvenance(rootDir,errors);
  return errors;
}

function verify(rootDir=root){
  const errors=[];
  const fixtureDirectory=path.join(rootDir,'qa','music-1.3.0');
  const contractPath=path.join(fixtureDirectory,'recorded-fixture-contract.json');
  let contract;
  try{contract=JSON.parse(fs.readFileSync(contractPath,'utf8'));}
  catch(error){errors.push('required committed fixture contract is unavailable ('+path.relative(rootDir,contractPath)+'): '+error.message);return errors;}
  add(errors,isObject(contract),'fixture contract must be an object');
  if(!isObject(contract))return errors;
  add(errors,contract.schemaVersion===1,'fixture contract schemaVersion must be 1');
  add(errors,contract.kind==='committed-recorded-analysis-exports','fixture contract kind changed');
  add(errors,contract.fixtureDirectory==='qa/music-1.3.0','fixture contract directory changed');
  add(errors,isDeepStrictEqual(contract.provenance,EXPECTED_PROVENANCE),'fixture contract provenance changed');
  verifyProvenance(rootDir,errors);
  add(errors,Array.isArray(contract.fixtures),'fixture contract fixtures must be an array');
  const byFile=new Map(Array.isArray(contract.fixtures)?contract.fixtures.filter(isObject).map(item=>[item.file,item]):[]);
  add(errors,Array.isArray(contract.fixtures)&&contract.fixtures.length===EXPECTED.length,'fixture contract must contain exactly four entries');
  add(errors,byFile.size===EXPECTED.length,'fixture contract must list exactly the four required analysis snapshots');
  for(const expected of EXPECTED){
    const declared=byFile.get(expected.file);
    add(errors,isObject(declared),'fixture contract is missing '+expected.file);
    if(isObject(declared))for(const key of ['file','lineage','track','analysisVersion','bytes','sha256'])add(errors,declared[key]===expected[key],'fixture contract '+expected.file+' '+key+' changed');
    const content=readPinnedFile(rootDir,{file:'qa/music-1.3.0/'+expected.file,bytes:expected.bytes,sha256:expected.sha256},expected.file,errors);
    if(content===null)continue;
    let analysis;
    try{analysis=JSON.parse(content.toString('utf8'));}
    catch(error){errors.push(expected.file+' is not valid JSON: '+error.message);continue;}
    add(errors,isObject(analysis),expected.file+' must decode to an analysis object');
    if(!isObject(analysis))continue;
    add(errors,analysis.analysisVersion===expected.analysisVersion,expected.file+' analysisVersion changed');
    add(errors,Number.isFinite(analysis.duration)&&Math.abs(analysis.duration-expected.duration)<1e-9,expected.file+' duration schema/value changed');
    for(const [key,count] of Object.entries({beats:expected.beats,downbeats:expected.downbeats,sections:expected.sections}))add(errors,Array.isArray(analysis[key])&&analysis[key].length===count,expected.file+' '+key+' schema/count changed');
    for(const key of ['onsets','waveform','energy','warnings'])add(errors,Array.isArray(analysis[key]),expected.file+' '+key+' must remain an array');
    add(errors,isObject(analysis.engine)&&analysis.engine.neural===true,expected.file+' must retain recorded neural-engine provenance');
    for(const key of ['phrases','impacts'])if(Object.hasOwn(expected,key))add(errors,Array.isArray(analysis[key])&&analysis[key].length===expected[key],expected.file+' '+key+' schema/count changed');
    if(expected.analysisVersion===2){
      add(errors,Array.isArray(analysis.activityRanges),expected.file+' must retain v2 activityRanges');
      add(errors,Array.isArray(analysis.beatDetails),expected.file+' must retain v2 beatDetails');
      add(errors,isObject(analysis.timing),expected.file+' must retain v2 timing');
    }
  }
  return errors;
}

function withProvenanceSandbox(run){
  const sandbox=fs.mkdtempSync(path.join(os.tmpdir(),'lightforge-recorded-provenance-'));
  try{
    for(const [,descriptor] of PROVENANCE_FILES){
      const source=pinnedPath(root,descriptor);
      const target=pinnedPath(sandbox,descriptor);
      fs.mkdirSync(path.dirname(target),{recursive:true});
      fs.copyFileSync(source,target);
    }
    return run(sandbox);
  }finally{fs.rmSync(sandbox,{recursive:true,force:true});}
}

test('committed recorded-analysis snapshots are present, immutable, and independently usable',()=>{
  const errors=verify();
  assert.deepEqual(errors,[],'Recorded analysis fixture contract failed:\n- '+errors.join('\n- ')+'\nThese JSON snapshots are committed regression inputs. Restore a complete checkout; do not substitute audio or regenerate them during release verification.');
});

test('recorded provenance pins reject missing, mutated, and symlinked inputs',()=>{
  const scenarios=[
    ['missing',EXPECTED_PROVENANCE.baselineCapture,file=>fs.unlinkSync(file),'baseline capture is unavailable'],
    ['mutated',EXPECTED_PROVENANCE.currentCapture,file=>fs.appendFileSync(file,'\n'),'current capture SHA-256 changed'],
    ['symlinked',EXPECTED_PROVENANCE.sampleSourceAudio.metadata,file=>{const retained=file+'.retained';fs.renameSync(file,retained);fs.symlinkSync(path.basename(retained),file);},'Sample.wav metadata must be a regular non-symlink committed file'],
  ];
  for(const [kind,descriptor,mutate,expected] of scenarios)withProvenanceSandbox(sandbox=>{
    assert.deepEqual(provenanceErrors(sandbox),[],'sandbox should begin with valid pinned provenance');
    mutate(pinnedPath(sandbox,descriptor));
    assert.ok(provenanceErrors(sandbox).some(error=>error.includes(expected)),kind+' provenance substitution must fail closed');
  });
});

test('Sample.wav provenance requires its original identity and WAV geometry',()=>{
  const altered=JSON.parse(JSON.stringify(EXPECTED_SAMPLE_AUDIO));
  altered.frames--;
  const errors=[];
  verifySampleMetadata([altered],errors);
  assert.ok(errors.some(error=>error.includes('identity or WAV geometry changed')));
});
