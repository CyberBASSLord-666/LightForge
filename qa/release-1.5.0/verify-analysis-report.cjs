'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),read=n=>JSON.parse(fs.readFileSync(path.join(__dirname,n))),sha=p=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex');
const reports={worker:read('analysis-worker-verification.json'),vocal:read('vocal-inference-verification.json'),vocalReference:read('vocal-reference-verification.json'),vocalResampling:read('vocal-resampling-audit.json'),vocalEdges:read('vocal-independent-edge-verification.json'),bass:read('bass-verification.json')};
const source_hashes={};
for(const [name,r] of Object.entries(reports)){
 assert.equal(r.passed,true,name+' must pass');assert(!r.errors?.length,name+' reports errors');
 for(const [file,hash] of Object.entries(r.source_hashes||r.sourceHashes||{})){assert.equal(sha(file),hash,name+': source changed '+file);source_hashes[file]=hash;}
}
const manifests=['web/analysis/models/model-manifest.json','web/analysis/models/vocal-model.json','web/analysis/models/vocal-frontend.json'];
for(const file of manifests)source_hashes[file]=sha(file);
const beat=JSON.parse(fs.readFileSync(path.join(root,manifests[0]))),vocal=JSON.parse(fs.readFileSync(path.join(root,manifests[1]))),models={};
for(const item of [...Object.values(beat),vocal]){
 const file='web/analysis/models/'+item.file,bytes=fs.statSync(path.join(root,file)).size;
 assert.equal(sha(file),item.sha256);assert.equal(bytes,item.bytes);
 models[item.file]={bytes,sha256:item.sha256,model:item.model||item.name,id:item.id,license:item.license,source:item.origin||item.source};
}
assert.equal(vocal.id,'frame-mn10-strong-1');assert.equal(vocal.frameSeconds,.04);
const result={release:'1.5.0',analysisVersion:4,passed:true,errors:[],source_hashes,models,checks:reports.worker.checks,tracks:reports.worker.tracks,evidence:reports,fixtureProvenance:read('audio-fixture-provenance.json'),limits:['No physical Android device or Tesla test.','Model/frontend parity verifies implementation, not singing accuracy.','Mixed-song vocal positives and selected negatives are spot checks, not a broad genre benchmark or lyric/word alignment.','Supplied Sample is complete; Glass Castle is tested only as its physically available recovered prefix. Neither has independent vocal/bass annotations.','Synthetic bass onset bounds are 40 ms in tested ordinary/nearby-kick cases and 80 ms for the closest 50 ms overlap; these do not certify real-song or hardware timing.','Bass and singing are mixture estimates; low instruments, overlapping sources and quiet passages can remain ambiguous.']};
fs.writeFileSync(path.join(__dirname,'analysis-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({passed:true,models,tracks:result.tracks,sourceFiles:Object.keys(source_hashes).length},null,2));
