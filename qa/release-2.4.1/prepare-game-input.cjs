'use strict';
// Public, fixed QA inputs decoded by the shipped WAV reader. No private audio.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const WavReader = require(path.join(root, 'web/analysis/wav-reader.js'));
const SOURCES = Object.freeze({demo:'web/demo/glass-castle.wav', falcon:'qa/release-1.6.0/fixtures/falcon-mix.wav'});

async function prepare(id, destination) {
  assert.ok(Object.hasOwn(SOURCES, id), 'Unknown public GAME fixture');
  assert.equal(require('node:os').endianness(), 'LE');
  const source = SOURCES[id], bytes = fs.readFileSync(path.join(root, source));
  const wav = new WavReader('host://fixed-public-game-input');
  wav.cached = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  wav.totalBytes = bytes.length;
  await wav.open();
  assert.equal(wav.rate, 44100);
  assert.ok(wav.samples > 0 && wav.samples <= 120 * 44100, 'Fixture exceeds bounded QA source');
  const fd = fs.openSync(destination, 'wx'), monoDigest = crypto.createHash('sha256');
  try {
    for (let first = 0; first < wav.samples; first += 40 * 44100) {
      const samples = Math.min(40 * 44100, wav.samples - first);
      const [left,right] = await wav.stereo44100(first, samples), mono = new Float32Array(samples);
      for (let index = 0; index < samples; index++) {
        mono[index] = (left[index] + right[index]) / 2;
        assert.ok(Number.isFinite(mono[index]), 'Nonfinite fixture PCM');
      }
      const chunk = Buffer.from(mono.buffer);
      fs.writeFileSync(fd, chunk); monoDigest.update(chunk);
    }
  } finally { fs.closeSync(fd); }
  return {id, source, sourceSha256:crypto.createHash('sha256').update(bytes).digest('hex'),
          monoPcmSha256:monoDigest.digest('hex'), samples:wav.samples, sampleRate:44100,
          channels:wav.channels, monoDerivation:'production-stereo44100-float32-mean-v1',
          separationApplied:false};
}

module.exports = {prepare, SOURCES};
if (require.main === module) {
  if (process.argv.length !== 4) throw Error('Expected fixture-id new-output.f32');
  prepare(process.argv[2], process.argv[3]).then(value=>console.log(JSON.stringify(value)))
    .catch(error=>{console.error(error);process.exitCode=1;});
}
