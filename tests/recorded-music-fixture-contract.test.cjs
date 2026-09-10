'use strict';

/*
 * These are checked-in analysis snapshots, not audio fixtures.  They let the
 * FSEQ/choreography regression run without shipping the external Sample.wav
 * source used when the snapshots were originally captured.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');

const root=path.resolve(__dirname,'..');
const fixtureDirectory=path.join(root,'qa','music-1.3.0');
const contractPath=path.join(fixtureDirectory,'recorded-fixture-contract.json');
const EXPECTED=Object.freeze([
  {file:'baseline-demo-music.json',lineage:'baseline',track:'demo',analysisVersion:1,bytes:186709,sha256:'18b5ecdc10ba976de474d580e174106d292ffe88c2544dd5023459e2cb864319',duration:64,beats:99,downbeats:25,sections:4},
  {file:'baseline-sample-music.json',lineage:'baseline',track:'sample',analysisVersion:1,bytes:594175,sha256:'33a2aed406a0842c24e6895882e27b0c17d6c8da81136066e1f792c69959c39b',duration:238.04,beats:369,downbeats:93,sections:12},
  {file:'current-demo-music.json',lineage:'current',track:'demo',analysisVersion:2,bytes:199911,sha256:'b5c925d1f3eb4d1c36b043587849c161186a99039f88537660b0f58bd5958533',duration:64,beats:99,downbeats:25,sections:4,phrases:7,impacts:24},
  {file:'current-sample-music.json',lineage:'current',track:'sample',analysisVersion:2,bytes:641621,sha256:'74764bd55772fcd54769423c5931f906fb1eb1a1706e541df2cad2a716dc7ad1',duration:238.04,beats:369,downbeats:92,sections:14,phrases:27,impacts:75},
]);

const isObject=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const add=(errors,condition,message)=>{if(!condition)errors.push(message);};
const digest=content=>crypto.createHash('sha256').update(content).digest('hex');

function verify(){
  const errors=[];
  let contract;
  try{contract=JSON.parse(fs.readFileSync(contractPath,'utf8'));}
  catch(error){errors.push(`required committed fixture contract is unavailable (${path.relative(root,contractPath)}): ${error.message}`);return errors;}
  add(errors,isObject(contract),'fixture contract must be an object');
  if(!isObject(contract))return errors;
  add(errors,contract.schemaVersion===1,'fixture contract schemaVersion must be 1');
  add(errors,contract.kind==='committed-recorded-analysis-exports','fixture contract kind changed');
  add(errors,contract.fixtureDirectory==='qa/music-1.3.0','fixture contract directory changed');
  add(errors,isObject(contract.provenance),'fixture contract provenance is required');
  if(isObject(contract.provenance)){
    add(errors,contract.provenance.baselineCapture==='qa/music-1.3.0/capture-baseline.cjs','fixture contract baseline-capture provenance changed');
    add(errors,contract.provenance.currentCapture==='qa/music-1.3.0/capture-analysis.cjs','fixture contract current-capture provenance changed');
    const sample=contract.provenance.sampleSourceAudio;
    add(errors,isObject(sample),'fixture contract must declare Sample.wav provenance');
    if(isObject(sample)){
      add(errors,sample.availability==='external-not-shipped','Sample.wav availability must remain external-not-shipped');
      add(errors,sample.requiredFor==='recapture-only','Sample.wav must be required only for recapture');
      add(errors,sample.requiredByPlannerRegression===false,'planner regression must not require Sample.wav');
      add(errors,sample.metadata==='qa/music-1.3.0/audio-metadata.json','Sample.wav provenance metadata path changed');
    }
  }
  add(errors,Array.isArray(contract.fixtures),'fixture contract fixtures must be an array');
  const byFile=new Map(Array.isArray(contract.fixtures)?contract.fixtures.filter(isObject).map(item=>[item.file,item]):[]);
  add(errors,Array.isArray(contract.fixtures)&&contract.fixtures.length===EXPECTED.length,'fixture contract must contain exactly four entries');
  add(errors,byFile.size===EXPECTED.length,'fixture contract must list exactly the four required analysis snapshots');
  for(const expected of EXPECTED){
    const declared=byFile.get(expected.file);
    add(errors,isObject(declared),`fixture contract is missing ${expected.file}`);
    if(isObject(declared))for(const key of ['file','lineage','track','analysisVersion','bytes','sha256'])add(errors,declared[key]===expected[key],`fixture contract ${expected.file} ${key} changed`);
    const file=path.join(fixtureDirectory,expected.file);
    let content;
    try{
      const stat=fs.statSync(file);
      add(errors,stat.isFile(),`${expected.file} must be a regular committed file`);
      add(errors,stat.size===expected.bytes,`${expected.file} byte length changed (expected ${expected.bytes}, got ${stat.size})`);
      content=fs.readFileSync(file);
    }catch(error){errors.push(`required committed analysis snapshot ${path.relative(root,file)} is unavailable: ${error.message}`);continue;}
    add(errors,digest(content)===expected.sha256,`${expected.file} SHA-256 changed`);
    let analysis;
    try{analysis=JSON.parse(content.toString('utf8'));}
    catch(error){errors.push(`${expected.file} is not valid JSON: ${error.message}`);continue;}
    add(errors,isObject(analysis),`${expected.file} must decode to an analysis object`);
    if(!isObject(analysis))continue;
    add(errors,analysis.analysisVersion===expected.analysisVersion,`${expected.file} analysisVersion changed`);
    add(errors,Number.isFinite(analysis.duration)&&Math.abs(analysis.duration-expected.duration)<1e-9,`${expected.file} duration schema/value changed`);
    for(const [key,count] of Object.entries({beats:expected.beats,downbeats:expected.downbeats,sections:expected.sections}))add(errors,Array.isArray(analysis[key])&&analysis[key].length===count,`${expected.file} ${key} schema/count changed`);
    for(const key of ['onsets','waveform','energy','warnings'])add(errors,Array.isArray(analysis[key]),`${expected.file} ${key} must remain an array`);
    add(errors,isObject(analysis.engine)&&analysis.engine.neural===true,`${expected.file} must retain recorded neural-engine provenance`);
    for(const key of ['phrases','impacts'])if(Object.hasOwn(expected,key))add(errors,Array.isArray(analysis[key])&&analysis[key].length===expected[key],`${expected.file} ${key} schema/count changed`);
    if(expected.analysisVersion===2){
      add(errors,Array.isArray(analysis.activityRanges),`${expected.file} must retain v2 activityRanges`);
      add(errors,Array.isArray(analysis.beatDetails),`${expected.file} must retain v2 beatDetails`);
      add(errors,isObject(analysis.timing),`${expected.file} must retain v2 timing`);
    }
  }
  return errors;
}

test('committed recorded-analysis snapshots are present, immutable, and independently usable',()=>{
  const errors=verify();
  assert.deepEqual(errors,[],`Recorded analysis fixture contract failed:\n- ${errors.join('\n- ')}\nThese JSON snapshots are committed regression inputs. Restore a complete checkout; do not substitute audio or regenerate them during release verification.`);
});
