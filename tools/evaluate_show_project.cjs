#!/usr/bin/env node
'use strict';
/* Local companion to evaluate_show_archive.py; executes production code only. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const runWorker = require('../tests/worker-harness.cjs');
const engine = require('../web/engine/show-engine.js');
const ROOT = path.resolve(__dirname, '..');
const MAX_PROJECT_BYTES = 64 * 1024 ** 2;
const MAX_FRAME_BYTES = 960000 * 200;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function requireValue(value, message) { if (!value) throw Error(message); }
function readBounded(filename, limit) {
  const fd = fs.openSync(filename, 'r');
  try {
    const info = fs.fstatSync(fd);
    requireValue(info.isFile() && info.size > 0 && info.size <= limit, 'Input file size is outside supported bounds');
    const data = fs.readFileSync(fd);
    requireValue(data.length === info.size, 'Input file changed while reading');
    return data;
  } finally { fs.closeSync(fd); }
}
// There is no shared FSEQ reader in the repository. Only inspect the bounded
// uncompressed LightForge envelope here; actual channel/motion/duration rules
// are checked by the production ShowEngine validator below.
function inspectFseq(bytes) {
  requireValue(bytes.length >= 32 && bytes.toString('ascii', 0, 4) === 'PSEQ', 'Invalid FSEQ signature/header');
  const offset = bytes.readUInt16LE(4), channels = bytes.readUInt32LE(10), frames = bytes.readUInt32LE(14), stepMs = bytes[18];
  requireValue(bytes[6] === 0 && bytes[7] === 2 && bytes.readUInt16LE(8) === 32, 'Expected LightForge FSEQ 2.0');
  requireValue(offset >= 32 && offset <= bytes.length && channels === 200 && frames >= 1 && frames <= 960000 && [15,20].includes(stepMs), 'Invalid FSEQ dimensions');
  requireValue(bytes.subarray(19, 24).every(value => value === 0), 'Compressed, sparse or flagged FSEQ is unsupported');
  requireValue(bytes.length - offset === frames * channels, 'FSEQ payload length differs from declared frames');
  const fields = Object.create(null);
  for (let cursor = 32; cursor < offset;) {
    if (bytes.subarray(cursor, offset).every(value => value === 0)) break;
    requireValue(cursor + 4 <= offset, 'Truncated FSEQ variable header');
    const length = bytes.readUInt16LE(cursor), code = bytes.toString('ascii', cursor + 2, cursor + 4);
    requireValue(length >= 5 && cursor + length <= offset && !Object.hasOwn(fields, code), 'Invalid or duplicate FSEQ variable header');
    const value = bytes.subarray(cursor + 4, cursor + length);
    requireValue(value.at(-1) === 0 && !value.subarray(0, -1).includes(0), 'Malformed FSEQ text field');
    fields[code] = value.subarray(0, -1).toString('utf8'); cursor += length;
  }
  requireValue(fields.mf === 'lightshow.wav', 'FSEQ media reference must be lightshow.wav');
  return {version:'2.0', offset, channels, frameCount:frames, stepMs, durationSeconds:frames * stepMs / 1000, mediaFilename:fields.mf, producer:fields.sp || null};
}
function summarizeSync(sync) {
  if (!sync) return null;
  const keep = ['version','scope','frameStepMs','roles','selected','matched','coverage','maxErrorMs','medianErrorMs','timing','collision','calibrationProvenance','targets','mechanical','issues','omittedIssues','mechanicalIssues','omittedMechanicalIssues','manual'];
  return Object.fromEntries(keep.filter(key => Object.hasOwn(sync, key)).map(key => [key, sync[key]]));
}
function sourceIdentity() {
  const paths = new Set([__filename, path.join(ROOT,'tools/evaluate_show_archive.py'), path.join(ROOT,'tools/project_performance_timings.py'), path.join(ROOT,'tests/worker-harness.cjs'), path.join(ROOT,'web/version.js')]);
  for (const dir of ['web/engine','web/analysis']) {
    for (const name of fs.readdirSync(path.join(ROOT, dir))) if (name.endsWith('.js')) paths.add(path.join(ROOT, dir, name));
  }
  const fileSHA256 = Object.fromEntries([...paths].sort().map(filename => [path.relative(ROOT, filename).split(path.sep).join('/'), sha(fs.readFileSync(filename))]));
  let commit = null;
  try { commit = execFileSync('git', ['rev-parse','HEAD'], {cwd:ROOT,encoding:'utf8',stdio:['ignore','pipe','ignore']}).trim(); } catch {}
  return {commit, currentEngineVersion:engine.version, inventorySHA256:sha(Buffer.from(JSON.stringify(fileSHA256))), fileSHA256, scope:'Current local source inventory, including uncommitted edits; commit alone does not identify evaluated bytes.'};
}
async function evaluateProject(projectPath, fseqPath) {
  const identity = sourceIdentity();
  const rawProject = readBounded(projectPath, MAX_PROJECT_BYTES), project = JSON.parse(rawProject);
  requireValue(project && project.version === 1 && project.compiled && project.settings && project.music, 'Expected a LightForge v1 exported project with compiled frames');
  requireValue(Number.isFinite(project.music.duration) && project.music.duration > 0 && project.music.duration <= 14400, 'Invalid project audio duration');
  const fseq = readBounded(fseqPath, MAX_FRAME_BYTES + 65535), header = inspectFseq(fseq);
  // Restore performs the exact application's input/metadata digests, bounded
  // decompression, frame hash, format validation and preview preparation.
  const startRestore = performance.now();
  const restored = await runWorker(path.join(ROOT,'web/engine'), {action:'restore',music:project.music,settings:project.settings,compiled:project.compiled});
  const restoreMs = performance.now() - startRestore;
  const savedFrames = Buffer.from(restored.show.frames);
  const archiveFrames = fseq.subarray(header.offset);
  const archiveShow = {...restored.show,frames:Uint8Array.from(archiveFrames),frameCount:header.frameCount,channels:header.channels,channelCount:header.channels,stepMs:header.stepMs,duration:header.durationSeconds};
  const archiveValidation = engine.validate(archiveShow, project.music);
  const startCompile = performance.now();
  const current = engine.generate(project.music, project.settings);
  const compileMs = performance.now() - startCompile;
  const currentFrames = Buffer.from(current.frames), currentFseq = Buffer.from(engine.fseq(current, 'lightshow.wav'));
  let changedBytes = Math.abs(currentFrames.length - savedFrames.length), firstChangedByte = null;
  for (let i = 0; i < Math.min(currentFrames.length, savedFrames.length); i++) {
    if (currentFrames[i] !== savedFrames[i]) { changedBytes++; if (firstChangedByte === null) firstChangedByte = i; }
  }
  if (firstChangedByte === null && changedBytes) firstChangedByte = Math.min(currentFrames.length, savedFrames.length);
  requireValue(sourceIdentity().inventorySHA256 === identity.inventorySHA256, 'Evaluated source changed during replay; rerun after edits finish');
  return {
    schema:'lightforge.show-project-evaluation.v1', source:identity,
    input:{projectSHA256:sha(rawProject), fseqSHA256:sha(fseq), savedEngineVersion:project.compiled.engineVersion, savedFrameSHA256:project.compiled.sha256, audioDurationSeconds:project.music.duration},
    archive:{header, validation:archiveValidation, payloadMatchesSavedProject:savedFrames.equals(archiveFrames), metadataMatchesSavedProject:header.frameCount === project.compiled.frameCount && header.stepMs === project.compiled.stepMs && header.channels === project.compiled.channels, savedSnapshotRestorePassed:true, lastFrameAllOff:archiveFrames.subarray(-200).every(value=>value===0)},
    replay:{validation:current.validation && {valid:current.validation.valid,errors:current.validation.errors,warnings:current.validation.warnings,stats:current.validation.stats}, frameSHA256:sha(currentFrames), fseqSHA256:sha(currentFseq), framesEqualSavedProject:currentFrames.equals(savedFrames), fseqEqualArchive:currentFseq.equals(fseq), changedFrameBytes:changedBytes, firstChangedByte:firstChangedByte === null ? null : {offset:firstChangedByte,frame:Math.floor(firstChangedByte/200),channel:firstChangedByte%200+1}, compilerWallMilliseconds:compileMs, savedRestoreWallMilliseconds:restoreMs, timingScope:'Single Node host replay of saved analysis; excludes audio analysis and Android/browser transport. Not a speedup measurement.', runtime:{node:process.version,platform:process.platform,architecture:process.arch,logicalCPUCount:os.cpus().length}},
    synchronization:{basis:'Selected targets from saved automatic music detection; no independent annotation or physical response measurements.', saved:{origin:'Hash-verified saved metadata; historical reported realization',report:summarizeSync(restored.show.synchronization)}, current:{origin:'Recomputed by current production compiler against its final frame bytes',report:summarizeSync(current.synchronization)}},
    analysisEvidence:{counts:{beats:project.music.beats?.length || 0,downbeats:project.music.downbeats?.length || 0,vocalPhrases:project.music.vocals?.phrases?.length || 0,vocalNotes:project.music.vocals?.notes?.length || 0,bassNotes:project.music.bassNotes?.length || 0,semanticEvents:project.music.semanticTimeline?.events?.length || 0},warnings:project.music.warnings || [],advancedChoreography:{semantic:current.settings.semanticChoreography === true,motifEvolution:current.settings.motifEvolution === true,vocal:current.settings.vocalChoreography === true}},
    limitations:['Exact replay checks compiler determinism and exported commands; it does not prove music detection accuracy or musical quality.','Mechanical command lead times and predicted motion are not measurements of Tesla actuator latency.','No model inference, audio ground-truth labeling, Android lifecycle test or physical vehicle test is performed.']
  };
}
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length !== 2) { console.error('Usage: node tools/evaluate_show_project.cjs PROJECT.json lightshow.fseq'); process.exitCode = 1; }
  else evaluateProject(args[0], args[1]).then(result => process.stdout.write(JSON.stringify(result)+'\n')).catch(error => {console.error(error.message);process.exitCode=1;});
}
module.exports = {evaluateProject, inspectFseq};
