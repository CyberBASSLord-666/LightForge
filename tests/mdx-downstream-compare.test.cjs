'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {compare, thresholds} = require('../qa/release-2.2.4/mdx-downstream-compare.cjs');

// A synthetic schema fixture, not evidence of model quality. Every passing
// baseline contains actual singing, measured pitch, and sustained fused notes.
function fixture() {
  const note = (start, midi) => ({
    start, end: start + .6, midi,
    frequency: 440 * 2 ** ((midi - 69) / 12),
    confidence: .8, strength: .7, peakTime: start + .2,
    source: 'game', continuation: false, estimated: true, type: 'held-note',
  });
  return {
    samples44100: 176400,
    samples22050: 88200,
    transcription: {steps: 8, notes: [note(.2, 69), note(1, 71), note(1.8, 72)]},
    classified: {
      presence: 'detected',
      classifier: {
        frameStep: .04,
        singingScores: Array.from({length: 200}, (_, i) => .6 + (i % 5) * .01),
        speechScores: Array.from({length: 200}, (_, i) => .01 + (i % 3) * .001),
      },
    },
    features: {
      fineEnergy: Array(200).fill(.002),
      residualEnergy: Array(200).fill(.0004),
      frequency: [440, 493.883, 523.251, 0],
      periodicity: Array(200).fill(.8),
    },
    vocals: {
      presence: 'detected', available: true, source: 'separated-vocals',
      confidence: .8, modelScore: .7, coverage: .6,
      phrases: [{
        start: .2, end: 2.6, peakTime: 1.1, releaseTime: 2.6,
        kind: 'singing', source: 'separated-vocals',
        confidence: .8, strength: .7, modelScore: .7, speechScore: .02,
        voicedFraction: .8, stemEnergyRatio: .9, estimated: true,
      }],
      notes: [note(.2, 69), note(1, 71), note(1.8, 72)],
      accents: [{time: .2, strength: .7, confidence: .8,
        kind: 'entrance', source: 'separated-vocals', estimated: true}],
      envelope: [.1, .3, .7, .1], envelopeStep: .02,
      pitchContour: {step: .04, midi: [69, 69, 71, 72], confidence: [.8, .9, .7, .8]},
    },
    executions: {segmenter: 8, encoder: 1, dur2bd: 1, bd2dur: 1, estimator: 1, frameMn10: 1},
  };
}

function resultFor(mutate) {
  const reference = fixture();
  const candidate = structuredClone(reference);
  mutate(candidate, reference);
  return compare(candidate, reference);
}

function rejected(result) {
  assert.equal(result.passed, false, JSON.stringify(result));
  assert.ok(Array.isArray(result.errors) && result.errors.length > 0);
  assert.ok(result.errors.every(error => typeof error === 'string' && error.length > 0));
}

test('identical rich results pass and expose their comparison contract', () => {
  const reference = fixture();
  const result = compare(structuredClone(reference), reference);
  assert.equal(result.passed, true, JSON.stringify(result.errors));
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.thresholds, thresholds);
  assert.ok(result.metrics && typeof result.metrics === 'object');
  assert.ok(result.coverage && typeof result.coverage === 'object');
});

test('small independent differences inside all documented tolerances pass', () => {
  const result = resultFor(candidate => {
    for (const note of [...candidate.transcription.notes, ...candidate.vocals.notes]) {
      note.start += .0005;
      note.end += .0005;
      note.peakTime += .0005;
      note.midi += .005;
      note.frequency += .05;
      note.confidence += .0005;
      note.strength += .0005;
    }
    const phrase = candidate.vocals.phrases[0];
    for (const field of ['start', 'end', 'peakTime', 'releaseTime', 'confidence',
      'strength', 'modelScore', 'speechScore', 'voicedFraction', 'stemEnergyRatio']) phrase[field] += .0005;
    candidate.vocals.accents[0].time += .004;
    candidate.vocals.accents[0].strength += .0005;
    candidate.vocals.accents[0].confidence += .0005;
    candidate.vocals.envelope[1] += .0005;
    candidate.vocals.pitchContour.midi[1] += .005;
    candidate.vocals.pitchContour.confidence[1] += .0005;
    candidate.classified.classifier.singingScores[0] += 5e-6;
    candidate.classified.classifier.speechScores[0] += 5e-6;
    candidate.features.fineEnergy[0] += 5e-7;
    candidate.features.residualEnergy[0] += 5e-7;
    candidate.features.periodicity[0] += 5e-6;
    candidate.features.frequency[0] += .004;
  });
  assert.equal(result.passed, true, JSON.stringify(result.errors));
});

for (const section of ['transcription', 'vocals']) {
  test(`${section} note count is exact`, () => rejected(resultFor(c => c[section].notes.pop())));
  for (const [field, delta] of [['start', .002], ['end', .002], ['peakTime', .002],
    ['midi', .02], ['frequency', .3], ['confidence', .002], ['strength', .002]]) {
    test(`${section} note ${field} exceeding its tolerance fails`, () =>
      rejected(resultFor(c => { c[section].notes[0][field] += delta; })));
  }
  for (const [field, value] of [['source', 'other-source'], ['continuation', true],
    ['type', 'note'], ['estimated', false]]) {
    test(`${section} note ${field} category is exact`, () =>
      rejected(resultFor(c => { c[section].notes[0][field] = value; })));
  }
}

for (const field of ['start', 'end', 'peakTime', 'releaseTime', 'confidence',
  'strength', 'modelScore', 'speechScore', 'voicedFraction', 'stemEnergyRatio']) {
  test(`phrase ${field} cannot silently drift`, () =>
    rejected(resultFor(c => { c.vocals.phrases[0][field] += .002; })));
}

for (const [label, mutate] of [
  ['accent time', c => { c.vocals.accents[0].time += .006; }],
  ['accent category', c => { c.vocals.accents[0].kind = 'syllabic-accent'; }],
  ['phrase category', c => { c.vocals.phrases[0].kind = 'speech'; }],
  ['classified presence', c => { c.classified.presence = 'uncertain'; }],
  ['fused presence', c => { c.vocals.presence = 'uncertain'; }],
  ['envelope', c => { c.vocals.envelope[0] += .002; }],
  ['contour pitch', c => { c.vocals.pitchContour.midi[0] += .02; }],
  ['contour confidence', c => { c.vocals.pitchContour.confidence[0] += .002; }],
  ['measured frequency relative limit', c => { c.features.frequency[0] += .006; }],
  ['zero-frequency absolute limit', c => { c.features.frequency[3] += .002; }],
  ['classifier frame step', c => { c.classified.classifier.frameStep += .000001; }],
  ['envelope frame step', c => { c.vocals.envelopeStep += .000001; }],
  ['contour frame step', c => { c.vocals.pitchContour.step += .000001; }],
]) {
  test(`${label} regression fails`, () => rejected(resultFor(mutate)));
}

for (const [section, field, maxAbsSpike, accumulated] of [
  ['classifier', 'singingScores', 1.1e-5, 2e-6],
  ['classifier', 'speechScores', 1.1e-5, 2e-6],
  ['features', 'fineEnergy', 1.1e-6, 2e-7],
  ['features', 'residualEnergy', 1.1e-6, 2e-7],
  ['features', 'periodicity', 1.1e-5, 2e-6],
]) {
  const array = candidate => section === 'classifier'
    ? candidate.classified.classifier[field] : candidate.features[field];
  test(`${field} maximum absolute error gate catches an isolated outlier`, () =>
    rejected(resultFor(c => { array(c)[0] += maxAbsSpike; })));
  test(`${field} RMSE gate catches distributed errors below maximum tolerance`, () =>
    rejected(resultFor(c => { const values = array(c); for (let i = 0; i < values.length; i++) values[i] += accumulated; })));
}

for (const [label, select] of [
  ['classifier singing', c => c.classified.classifier.singingScores],
  ['classifier speech', c => c.classified.classifier.speechScores],
  ['energy', c => c.features.fineEnergy],
  ['residual energy', c => c.features.residualEnergy],
  ['frequency', c => c.features.frequency],
  ['periodicity', c => c.features.periodicity],
  ['envelope', c => c.vocals.envelope],
  ['contour midi', c => c.vocals.pitchContour.midi],
  ['contour confidence', c => c.vocals.pitchContour.confidence],
]) {
  for (const invalid of [NaN, Infinity, -Infinity, '0.5', null, true]) {
    test(`${label} rejects ${String(invalid)} numeric array elements`, () =>
      rejected(resultFor(c => { select(c)[0] = invalid; })));
  }
  test(`${label} rejects identical nonfinite values on both sides`, () =>
    rejected(resultFor((c, r) => { select(c)[0] = NaN; select(r)[0] = NaN; })));
  test(`${label} array length is exact`, () => rejected(resultFor(c => select(c).pop())));
}

test('numeric array replaced with an array-like object is rejected', () =>
  rejected(resultFor(c => { c.features.frequency = {0: 440, 1: 493.883, 2: 523.251, 3: 0, length: 4}; })));

for (const field of ['samples44100', 'samples22050']) {
  test(`${field} sample count is exact`, () => rejected(resultFor(c => { c[field]++; })));
  test(`${field} rejects numeric text`, () => rejected(resultFor(c => { c[field] = String(c[field]); })));
}

test('transcription keeps all eight diffusion steps', () =>
  rejected(resultFor(c => { c.transcription.steps = 7; })));

for (const graph of ['segmenter', 'encoder', 'dur2bd', 'bd2dur', 'estimator', 'frameMn10']) {
  test(`${graph} execution count must match the complete pipeline`, () =>
    rejected(resultFor(c => { c.executions[graph]++; })));
  test(`identically missing ${graph} execution coverage cannot pass`, () =>
    rejected(resultFor((c, r) => { c.executions[graph] = 0; r.executions[graph] = 0; })));
}

for (const [label, mutate] of [
  ['zero transcription notes', c => { c.transcription.notes = []; }],
  ['too few transcription notes', c => { c.transcription.notes = c.transcription.notes.slice(0, 2); }],
  ['zero fused notes', c => { c.vocals.notes = []; }],
  ['subsecond fused note coverage', c => { c.vocals.notes = [c.vocals.notes[0]]; }],
  ['zero phrases', c => { c.vocals.phrases = []; }],
  ['speech-only phrases', c => { c.vocals.phrases[0].kind = 'speech'; }],
  ['missing classifier', c => { delete c.classified.classifier; }],
  ['empty singing scores', c => { c.classified.classifier.singingScores = []; }],
  ['empty speech scores', c => { c.classified.classifier.speechScores = []; }],
  ['insufficient singing evidence', c => { c.classified.classifier.singingScores.fill(.1); }],
  ['seven transcription steps', c => { c.transcription.steps = 7; }],
]) {
  test(`identical ${label} is a vacuous baseline and fails`, () =>
    rejected(resultFor((c, r) => { mutate(c); mutate(r); })));
}

for (const field of ['releaseTime', 'modelScore', 'speechScore', 'voicedFraction', 'stemEnergyRatio']) {
  test(`optional event ${field} present on only one side fails`, () =>
    rejected(resultFor(c => { delete c.vocals.phrases[0][field]; })));
}

test('unknown added event field cannot silently pass', () =>
  rejected(resultFor(c => { c.vocals.notes[0].newDecisionEvidence = .5; })));

test('unknown scalar event field is compared exactly', () =>
  rejected(resultFor((c, r) => {
    r.vocals.notes[0].newDecisionEvidence = .5;
    c.vocals.notes[0].newDecisionEvidence = .50000001;
  })));

test('identical optional metadata is preserved without invalidating real comparisons', () => {
  const result = resultFor((c, r) => {
    c.vocals.notes[0].newDecisionEvidence = .5;
    r.vocals.notes[0].newDecisionEvidence = .5;
  });
  assert.equal(result.passed, true, JSON.stringify(result.errors));
});

test('optional nested field present on the reference alone fails', () =>
  rejected(resultFor((c, r) => { r.vocals.notes[0].metadata = {status: 'accepted'}; })));

test('optional numeric scalar with nonfinite values on both sides fails', () =>
  rejected(resultFor((c, r) => {
    c.vocals.phrases[0].speechScore = Infinity;
    r.vocals.phrases[0].speechScore = Infinity;
  })));

test('exact decimal timing, strength, and MIDI boundaries tolerate binary roundoff', () => {
  const result = resultFor(c => {
    c.transcription.notes[0].start += .001;
    c.transcription.notes[0].midi += .01;
    c.vocals.notes[0].strength += .001;
  });
  assert.equal(result.passed, true, JSON.stringify(result.errors));
});

test('identical numeric-text optional confidence scalars are rejected', () =>
  rejected(resultFor((c, r) => {
    c.classified.confidence = '0.8';
    r.classified.confidence = '0.8';
  })));

test('optional classified summary envelopes honor the same 0.001 limit', () => {
  const compareDelta = delta => resultFor((c, r) => {
    r.classified.envelope = [.1, .3, .7];
    c.classified.envelope = [.1 + delta, .3, .7];
  });
  const boundary = compareDelta(.001);
  assert.equal(boundary.passed, true, JSON.stringify(boundary.errors));
  rejected(compareDelta(.002));
});
