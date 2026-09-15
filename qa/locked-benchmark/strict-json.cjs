'use strict';

// JSON.parse silently replaces duplicate members and accepts numeric overflow.
// Evidence inputs must reject both before any schema or digest validation.
const MAX_DEPTH = 512;

function parse(text) {
  if (typeof text !== 'string') throw new TypeError('JSON input must be a string');
  let offset = 0;

  function fail(message, position = offset) {
    throw new SyntaxError(`${message} at position ${position}`);
  }

  function whitespace() {
    while (offset < text.length) {
      const code = text.charCodeAt(offset);
      if (code !== 0x20 && code !== 0x09 && code !== 0x0a && code !== 0x0d) break;
      offset += 1;
    }
  }

  function string() {
    if (text[offset] !== '"') fail('Expected a JSON string');
    offset += 1;
    let start = offset;
    const parts = [];
    while (offset < text.length) {
      const code = text.charCodeAt(offset);
      if (code === 0x22) {
        parts.push(text.slice(start, offset));
        offset += 1;
        return parts.join('');
      }
      if (code < 0x20) fail('Unescaped control character in JSON string');
      if (code !== 0x5c) {
        offset += 1;
        continue;
      }
      parts.push(text.slice(start, offset));
      offset += 1;
      if (offset >= text.length) fail('Unterminated JSON string escape');
      const escape = text[offset++];
      switch (escape) {
        case '"': parts.push('"'); break;
        case '\\': parts.push('\\'); break;
        case '/': parts.push('/'); break;
        case 'b': parts.push('\b'); break;
        case 'f': parts.push('\f'); break;
        case 'n': parts.push('\n'); break;
        case 'r': parts.push('\r'); break;
        case 't': parts.push('\t'); break;
        case 'u': {
          const digits = text.slice(offset, offset + 4);
          if (!/^[0-9a-fA-F]{4}$/.test(digits)) fail('Invalid JSON Unicode escape');
          parts.push(String.fromCharCode(Number.parseInt(digits, 16)));
          offset += 4;
          break;
        }
        default: fail('Invalid JSON string escape', offset - 1);
      }
      start = offset;
    }
    fail('Unterminated JSON string');
  }

  function digit() {
    const code = text.charCodeAt(offset);
    return code >= 0x30 && code <= 0x39;
  }

  function number() {
    const start = offset;
    if (text[offset] === '-') offset += 1;
    if (text[offset] === '0') offset += 1;
    else {
      if (!digit()) fail('Invalid JSON number');
      while (digit()) offset += 1;
    }
    if (text[offset] === '.') {
      offset += 1;
      if (!digit()) fail('Missing fractional digits in JSON number');
      while (digit()) offset += 1;
    }
    if (text[offset] === 'e' || text[offset] === 'E') {
      offset += 1;
      if (text[offset] === '+' || text[offset] === '-') offset += 1;
      if (!digit()) fail('Missing exponent digits in JSON number');
      while (digit()) offset += 1;
    }
    const result = Number(text.slice(start, offset));
    if (!Number.isFinite(result)) fail('Non-finite JSON number', start);
    return result;
  }

  function value(depth) {
    whitespace();
    const token = text[offset];
    if (token === '"') return string();
    if (token === '-' || digit()) return number();
    if (token === '{' || token === '[') {
      if (depth >= MAX_DEPTH) fail(`JSON nesting exceeds ${MAX_DEPTH} containers`);
      offset += 1;
      whitespace();
      if (token === '[') {
        const result = [];
        if (text[offset] === ']') { offset += 1; return result; }
        while (true) {
          result.push(value(depth + 1));
          whitespace();
          if (text[offset] === ']') { offset += 1; return result; }
          if (text[offset] !== ',') fail('Expected comma or closing JSON array');
          offset += 1;
        }
      }
      const result = {};
      const keys = new Set();
      if (text[offset] === '}') { offset += 1; return result; }
      while (true) {
        whitespace();
        const keyPosition = offset;
        const key = string();
        if (keys.has(key)) fail('Duplicate object key', keyPosition);
        keys.add(key);
        whitespace();
        if (text[offset] !== ':') fail('Expected colon after JSON object key');
        offset += 1;
        const member = value(depth + 1);
        // Assignment would invoke Object.prototype.__proto__ for that valid key.
        Object.defineProperty(result, key, {
          value: member, enumerable: true, configurable: true, writable: true,
        });
        whitespace();
        if (text[offset] === '}') { offset += 1; return result; }
        if (text[offset] !== ',') fail('Expected comma or closing JSON object');
        offset += 1;
      }
    }
    for (const [literal, result] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(literal, offset)) {
        offset += literal.length;
        return result;
      }
    }
    fail(offset === text.length ? 'Unexpected end of JSON input' : 'Unexpected JSON token');
  }

  const result = value(0);
  whitespace();
  if (offset !== text.length) fail('Unexpected content after JSON value');
  return result;
}

module.exports = { parse };
