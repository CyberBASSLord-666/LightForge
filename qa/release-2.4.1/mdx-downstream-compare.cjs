'use strict';

/* Fixed before the paired real-model run. This checks integration sensitivity
 * on the supplied vocal passage; it does not establish corpus-level accuracy
 * or Android performance. Tolerances retain their physical/serialized units. */
function freeze(value) {
  for (const child of Object.values(value)) if (child && typeof child === 'object') freeze(child);
  return Object.freeze(value);
}
const thresholds = freeze({
  sampleCounts: 'exact positive integers',
  transcriptionSteps: 8,
  executions: {segmenter: 8, encoder: 1, dur2bd: 1, bd2dur: 1, estimator: 1, frameMn10: 1},
  eventTimingSeconds: 0.001,
  noteMidiSemitones: 0.01,
  accentTimingSeconds: 0.005,
  serializedEventScalar: 0.001,
  classifierScores: {absolute: 1e-5, rmse: 1e-6},
  sourceEnergy: {absolute: 1e-6, rmse: 1e-7},
  periodicity: {absolute: 1e-5, rmse: 1e-6},
  measuredFrequencyHz: {absolute: 0.001, relative: 1e-5},
  derivedNoteFrequencyHz: {absolute: 0.001, relative: 2 ** (0.01 / 12) - 1},
  serializedEnvelopeAndConfidence: {absolute: 0.001},
  contourMidi: {absolute: 0.01},
  coverage: {rawGameNotes: 3, fusedNotes: 1, fusedNoteSeconds: 1, nonspeechPhrases: 1, maximumSingingScore: 0.11},
  categoricalAndUnspecifiedFields: 'exact; matching keys and array lengths required',
});

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value) && !ArrayBuffer.isView(value);
const array = value => Array.isArray(value) || (ArrayBuffer.isView(value) && !(value instanceof DataView));
const number = value => typeof value === 'number' && Number.isFinite(value);
const own = (value, key) => value != null && Object.prototype.hasOwnProperty.call(value, key);
const get = (value, path) => path.split('.').reduce((at, key) => at == null ? undefined : at[key], value);
const arrayRules = {
  'classified.classifier.singingScores': thresholds.classifierScores,
  'classified.classifier.speechScores': thresholds.classifierScores,
  'features.fineEnergy': thresholds.sourceEnergy,
  'features.residualEnergy': thresholds.sourceEnergy,
  'features.frequency': thresholds.measuredFrequencyHz,
  'features.periodicity': thresholds.periodicity,
  'vocals.envelope': thresholds.serializedEnvelopeAndConfidence,
  'vocals.pitchContour.midi': thresholds.contourMidi,
  'vocals.pitchContour.confidence': thresholds.serializedEnvelopeAndConfidence,
};
const requiredArrayPaths = Object.keys(arrayRules);
// Full production classifier summaries may include these serialized views in
// addition to the required raw score arrays. They use the same declared units.
arrayRules['classified.envelope'] = thresholds.serializedEnvelopeAndConfidence;
arrayRules['classified.classifierScores'] = thresholds.classifierScores;
// Decimal millisecond/cent values are not exact binary doubles. Admit only
// representational rounding at a nonzero boundary, never slack for exact gates.
const within = (difference, limit, a, b) => difference <= limit ||
  (limit > 0 && difference - limit <= 4 * Number.EPSILON * Math.max(1, Math.abs(a), Math.abs(b)));

function compare(native, reference) {
  const errors = [], metrics = {arrays: {}, scalars: {}, exactComparisons: 0};
  const add = message => { if (errors.length < 100) errors.push(message); };

  // These validations apply separately to both sides. Equal missing, NaN, or
  // empty results must never count as numerical agreement.
  function validate(value, label) {
    if (!object(value)) { add(`${label}: result must be an object`); return; }
    for (const path of ['transcription', 'classified', 'classified.classifier', 'features', 'vocals', 'vocals.pitchContour', 'executions']) {
      if (!object(get(value, path))) add(`${label}.${path}: required object is missing`);
    }
    for (const key of ['samples44100', 'samples22050']) {
      if (!Number.isSafeInteger(value[key]) || value[key] < 1) add(`${label}.${key}: expected a positive integer sample count`);
    }
    if (value.transcription?.steps !== thresholds.transcriptionSteps) add(`${label}.transcription.steps: expected all 8 steps`);
    for (const [key, expected] of Object.entries(thresholds.executions)) {
      if (value.executions?.[key] !== expected) add(`${label}.executions.${key}: expected ${expected} graph executions`);
    }
    for (const path of ['classified.presence', 'vocals.presence']) {
      if (!['detected', 'not_detected', 'uncertain'].includes(get(value, path))) add(`${label}.${path}: missing or invalid categorical presence`);
    }
    for (const path of requiredArrayPaths) {
      const values = get(value, path);
      if (!array(values) || !values.length) add(`${label}.${path}: expected a nonempty numeric array`);
      else if (Array.from(values).some(x => !number(x))) add(`${label}.${path}: all array values must be finite numbers`);
    }
    const collections = {
      'transcription.notes': {numeric: ['start', 'end', 'midi'], string: ['source'], boolean: ['continuation']},
      'vocals.notes': {numeric: ['start', 'end', 'midi'], string: ['type', 'source'], boolean: ['continuation']},
      'vocals.phrases': {numeric: ['start', 'end'], string: ['kind']},
      'vocals.accents': {numeric: ['time'], string: ['kind']},
    };
    for (const [path, schema] of Object.entries(collections)) {
      const entries = get(value, path);
      if (!Array.isArray(entries)) { add(`${label}.${path}: expected an event array`); continue; }
      entries.forEach((event, i) => {
        const at = `${label}.${path}[${i}]`;
        if (!object(event)) { add(`${at}: expected an event object`); return; }
        for (const key of schema.numeric) if (!number(event[key])) add(`${at}.${key}: expected a finite number`);
        for (const key of schema.string) if (typeof event[key] !== 'string' || !event[key]) add(`${at}.${key}: required category is missing`);
        for (const key of schema.boolean || []) if (typeof event[key] !== 'boolean') add(`${at}.${key}: expected a boolean category`);
        if (own(event, 'start') && own(event, 'end') && !(event.start >= 0 && event.end > event.start)) add(`${at}: invalid start/end interval`);
        if (own(event, 'midi') && !(event.midi >= 0 && event.midi <= 127)) add(`${at}.midi: pitch is outside [0, 127]`);
        if (own(event, 'time') && !(event.time >= 0)) add(`${at}.time: expected nonnegative time`);
      });
    }
    function finiteTree(at, path) {
      if (typeof at === 'number') { if (!Number.isFinite(at)) add(`${path}: numeric value is not finite`); return; }
      if (array(at)) {
        if (Array.from(at).some(x => typeof x === 'number' && !Number.isFinite(x))) add(`${path}: contains a nonfinite numeric value`);
        for (let i = 0; i < at.length; i++) if (typeof at[i] !== 'number') finiteTree(at[i], `${path}[${i}]`);
      } else if (object(at)) {
        for (const [key, child] of Object.entries(at)) finiteTree(child, `${path}.${key}`);
      } else if (at !== null && !['string', 'boolean'].includes(typeof at)) add(`${path}: unsupported non-JSON value`);
    }
    finiteTree(value, label);
  }
  validate(native, 'native');
  validate(reference, 'reference');

  function numericArray(a, b, path, rule) {
    if (!array(a) || !array(b)) { add(`${path}: both values must be numeric arrays`); return; }
    if (a.length !== b.length) { add(`${path}: array length differs (${a.length} versus ${b.length})`); return; }
    let maxAbsoluteError = 0, square = 0, violations = 0, nonfinite = 0;
    for (let i = 0; i < a.length; i++) {
      if (!number(a[i]) || !number(b[i])) { nonfinite++; continue; }
      const difference = Math.abs(a[i] - b[i]), limit = rule.absolute + (rule.relative || 0) * Math.abs(b[i]);
      maxAbsoluteError = Math.max(maxAbsoluteError, difference); square += difference * difference;
      if (!within(difference, limit, a[i], b[i])) violations++;
    }
    const rmse = a.length ? Math.sqrt(square / a.length) : 0;
    const passed = !nonfinite && !violations && (rule.rmse == null || rmse <= rule.rmse);
    metrics.arrays[path] = {samples: a.length, maxAbsoluteError: Number.isFinite(maxAbsoluteError) ? maxAbsoluteError : null, rmse: Number.isFinite(rmse) ? rmse : null, violations, nonfinite, passed};
    if (!passed) add(`${path}: numeric tolerance exceeded or nonfinite output (${violations} element violations, ${nonfinite} invalid values, RMSE ${rmse})`);
  }

  function scalarRule(path) {
    if (/\.notes\[\d+\]\.frequency$/.test(path)) return thresholds.derivedNoteFrequencyHz;
    if (/\.notes\[\d+\]\.midi$/.test(path)) return {absolute: thresholds.noteMidiSemitones};
    if (/\.accents\[\d+\]\.time$/.test(path)) return {absolute: thresholds.accentTimingSeconds};
    if (/\.(?:notes|phrases|accents)\[\d+\]\.(?:start|end|peakTime|releaseTime|accentTime)$/.test(path)) return {absolute: thresholds.eventTimingSeconds};
    if (/\.(?:confidence|strength|modelScore|speechScore|voicedFraction|stemEnergyRatio|coverage)$/.test(path)) return {absolute: thresholds.serializedEventScalar};
    return {absolute: 0};
  }

  // Compare all supplied fields, including optional event evidence and timing.
  // Newly added or unrecognized numerical/categorical fields use exact equality
  // until a physical-unit tolerance is explicitly reviewed before a model run.
  function walk(a, b, path) {
    if (arrayRules[path]) { numericArray(a, b, path, arrayRules[path]); return; }
    const rule = scalarRule(path);
    if (typeof a === 'number' || typeof b === 'number' || rule.absolute > 0) {
      if (!number(a) || !number(b)) { add(`${path}: both scalar values must be finite numbers`); return; }
      const difference = Math.abs(a - b), limit = rule.absolute + (rule.relative || 0) * Math.abs(b);
      metrics.scalars[path] = {absoluteError: difference, limit, passed: within(difference, limit, a, b)};
      if (!within(difference, limit, a, b)) add(`${path}: scalar difference ${difference} exceeds ${limit}`);
      return;
    }
    if (array(a) || array(b)) {
      if (!array(a) || !array(b)) { add(`${path}: array type differs`); return; }
      if (a.length !== b.length) add(`${path}: array count differs (${a.length} versus ${b.length})`);
      for (let i = 0; i < Math.min(a.length, b.length); i++) walk(a[i], b[i], `${path}[${i}]`);
      return;
    }
    if (object(a) || object(b)) {
      if (!object(a) || !object(b)) { add(`${path || 'result'}: object type differs`); return; }
      for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
        const child = path ? `${path}.${key}` : key;
        if (!own(a, key) || !own(b, key)) add(`${child}: field is present on only one side`);
        else walk(a[key], b[key], child);
      }
      return;
    }
    metrics.exactComparisons++;
    if (a !== b) add(`${path}: categorical or literal value differs`);
  }
  walk(native, reference, '');

  function coverageFor(value, label) {
    const rawNotes = Array.isArray(value?.transcription?.notes) ? value.transcription.notes : [];
    const fusedNotes = Array.isArray(value?.vocals?.notes) ? value.vocals.notes : [];
    const phrases = Array.isArray(value?.vocals?.phrases) ? value.vocals.phrases : [];
    const scores = value?.classified?.classifier?.singingScores;
    const fusedNoteSeconds = fusedNotes.reduce((sum, note) => sum + (number(note?.start) && number(note?.end) ? Math.max(0, note.end - note.start) : 0), 0);
    let maximumSingingScore = 0;
    if (array(scores)) for (const score of scores) if (number(score)) maximumSingingScore = Math.max(maximumSingingScore, score);
    const result = {rawGameNotes: rawNotes.length, fusedNotes: fusedNotes.length, fusedNoteSeconds,
      nonspeechPhrases: phrases.filter(phrase => typeof phrase?.kind === 'string' && phrase.kind !== 'speech' && phrase.kind.length).length,
      maximumSingingScore};
    result.passed = true;
    for (const [key, minimum] of Object.entries(thresholds.coverage)) {
      if (result[key] < minimum) { result.passed = false; add(`${label}.coverage.${key}: ${result[key]} is below the required ${minimum}`); }
    }
    return result;
  }
  const coverage = {native: coverageFor(native, 'native'), reference: coverageFor(reference, 'reference')};
  return {passed: errors.length === 0, errors, metrics, coverage, thresholds};
}

module.exports = {compare, thresholds};
