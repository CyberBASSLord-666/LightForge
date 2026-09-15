'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { parse } = require('../qa/locked-benchmark/strict-json.cjs');

test('JSON values, finite numbers and legal whitespace match native parsing', () => {
  for (const input of [
    'null', 'true', 'false', '0', '-0', '12345678901234567890', '-42', '1.25',
    '1e2', '-1E-2', '1e+2', '1e-9999', '1.7976931348623157e308',
    '""', '"text"', '[]', '{}', ' \t\r\n [1, {"a": true, "b": null}, []] \n',
    '{"0":1,"10":2,"2":3,"empty":{},"list":[false,-3.5e+2]}',
  ]) assert.deepEqual(parse(input), JSON.parse(input), input);
  assert.ok(Object.is(parse('-0'), -0));
});

test('JSON strings preserve every escape, Unicode and legal lone surrogates', () => {
  for (const input of [
    String.raw`"\"\\\/\b\f\n\r\t\u0000\u001F\u007f\uFEFF"`,
    String.raw`"\ud83d\ude80"`, String.raw`"\ud800"`, String.raw`"\udfff"`,
    '"🚀 café \u2028\u2029\ufeff"', '"\ud800"', '"\udfff"',
  ]) assert.deepEqual(parse(input), JSON.parse(input));
});

test('duplicate members fail at root, nested objects and objects inside arrays', () => {
  for (const input of [
    '{"same":1,"same":2}', '{"same":null,"same":null}',
    '{"outer":{"same":1,"same":2}}', '[{"same":1,"same":2}]',
    '{"same":1,"inner":[{"deep":{"same":1,"same":2}}]}',
    '{"":0,"":1}', '{"__proto__":{},"__proto__":null}',
  ]) assert.throws(() => parse(input), /Duplicate object key at position \d+/);
});

test('duplicate comparison uses decoded keys including escapes and surrogate pairs', () => {
  for (const input of [
    String.raw`{"name":1,"\u006eame":2}`,
    String.raw`{"\u0061":1,"a":2}`,
    String.raw`{"/":1,"\/":2}`,
    String.raw`{"\n":1,"\u000a":2}`,
    String.raw`{"\u00aF":1,"\u00Af":2}`,
    '{"🚀":1,"\\ud83d\\ude80":2}',
    String.raw`{"__proto__":1,"\u005f_proto__":2}`,
  ]) assert.throws(() => parse(input), /Duplicate object key/);
});

test('same names in different objects and distinct Unicode spellings remain legal', () => {
  const input = '{"x":1,"nested":{"x":2},"array":[{"x":3},{"x":4}],"é":5,"é":6}';
  assert.deepEqual(parse(input), JSON.parse(input));
});

test('prototype-like keys remain ordinary own data properties', () => {
  const input = '{"__proto__":{"polluted":true},"constructor":{"prototype":{"x":1}},"prototype":2,"toString":3,"hasOwnProperty":4}';
  const value = parse(input);
  assert.deepEqual(value, JSON.parse(input));
  assert.equal(Object.getPrototypeOf(value), Object.prototype);
  assert.equal(Object.getPrototypeOf(value.__proto__), Object.prototype);
  assert.deepEqual(Object.getOwnPropertyDescriptor(value, '__proto__'), {
    value: { polluted: true }, writable: true, enumerable: true, configurable: true,
  });
  assert.equal(Object.hasOwn(Object.prototype, 'polluted'), false);
  assert.equal(value.polluted, undefined);
  assert.equal(JSON.stringify(value), input);
});

test('overflow and non-JSON numeric spellings fail at every depth', () => {
  for (const number of ['1e309', '-1e99999', '1.7976931348623159e308']) {
    for (const input of [number, `[${number}]`, `{"x":{"y":${number}}}`]) {
      assert.throws(() => parse(input), /Non-finite JSON number/);
    }
  }
  for (const input of [
    'NaN', 'Infinity', '-Infinity', '+1', '.5', '1.', '01', '-01', '00',
    '0x10', '0b11', '1_000', '1e', '1e+', '1e-', '--1', '-', '-.1',
    '[01]', '{"x":1e}',
  ]) assert.throws(() => parse(input), SyntaxError, input);
});

test('invalid strings, escapes and literal control characters fail', () => {
  for (const input of [
    '"', '"missing', '"backslash\\', String.raw`"\x00"`, String.raw`"\v"`,
    String.raw`"\0"`, String.raw`"\'"`, String.raw`"\u000"`,
    String.raw`"\uZZZZ"`, String.raw`"\u{0000}"`, '"line\nbreak"',
    '"tab\there"', '"null\0here"', '"\u001f"',
  ]) assert.throws(() => parse(input), SyntaxError, input);
});

test('malformed containers, comments, missing values and trailing content fail', () => {
  for (const input of [
    '', ' \r\n\t', '[', '{', '[1,]', '{"a":1,}', '[,1]', '[1,,2]',
    '{a:1}', "{'a':1}", '{"a" 1}', '{"a":}', '{:1}', '{"a":1 "b":2}',
    '[1 2]', 'true false', '{}[]', 'nullx', 'undefined', '// comment\n0',
    '/* comment */0', '[1/* comment */]', 'TRUE', 'Null', '\ufeff{}',
    '\u00a0{}', '{}\u00a0', '[\u000b0]', '\ufeff',
  ]) assert.throws(() => parse(input), SyntaxError, input);
});

test('exactly 512 nested containers are accepted and deeper arrays fail boundedly', () => {
  const allowed = '['.repeat(512) + '0' + ']'.repeat(512);
  assert.deepEqual(parse(allowed), JSON.parse(allowed));
  for (const depth of [513, 10000]) {
    assert.throws(() => parse('['.repeat(depth) + '0' + ']'.repeat(depth)),
      error => error instanceof SyntaxError && /nesting exceeds 512 containers/.test(error.message));
  }
});

test('nesting bound also covers objects and mixed containers, including empty ones', () => {
  assert.doesNotThrow(() => parse('{"a":'.repeat(512) + '0' + '}'.repeat(512)));
  assert.throws(() => parse('{"a":'.repeat(513) + '0' + '}'.repeat(513)), /nesting exceeds 512/);
  assert.doesNotThrow(() => parse('['.repeat(511) + '{}' + ']'.repeat(511)));
  assert.throws(() => parse('['.repeat(512) + '{}' + ']'.repeat(512)), /nesting exceeds 512/);
});

test('non-string inputs fail without implicit coercion', () => {
  for (const input of [null, undefined, 0, true, [], {}, Buffer.from('{}'), new String('{}')]) {
    assert.throws(() => parse(input), TypeError);
  }
  assert.throws(() => parse({ toString() { throw new Error('must not run'); } }), TypeError);
});
