'use strict';

const path = require('node:path');
const {spawn} = require('node:child_process');

const CLEANUP_MS = 3000;

/** Bound a trusted capture child and its normal Linux process descendants.
 * Python is a subreaper and uses pidfds; the outer watchdog reports failure if
 * that helper cannot finish, never inventing confirmation of termination.
 */
function supervise({executable, args = [], env = process.env, cwd,
  timeoutMs, stdio = 'inherit', onSpawn}) {
  if (process.platform !== 'linux') throw new Error('Capture supervision requires Linux');
  if (typeof executable !== 'string' || !executable || !Array.isArray(args) || args.some(arg => typeof arg !== 'string')) {
    throw new Error('An executable and string arguments are required');
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) throw new Error('timeoutMs must be a positive integer');
  if (!(typeof stdio === 'string' || (Array.isArray(stdio) && stdio.length <= 3))) {
    throw new Error('stdio must describe only stdin, stdout and stderr');
  }
  const deadline = process.hrtime.bigint() + BigInt(timeoutMs) * 1000000n;
  const helper = path.join(__dirname, 'capture-supervisor.py');
  return new Promise(resolve => {
    let receipt = '';
    let exited = false;
    let streamEnded = false;
    let finished = false;
    let helperExit = null;
    let helperSignal = null;
    let error = null;
    const io = typeof stdio === 'string' ? [stdio, stdio, stdio] : [stdio[0] ?? 'inherit', stdio[1] ?? 'inherit', stdio[2] ?? 'inherit'];
    const child = spawn('python3', ['-I', '-u', helper, String(deadline), '--', executable, ...args],
      {cwd, env, stdio: [...io, 'pipe']});
    const finish = () => {
      if (finished || !exited || !streamEnded) return;
      finished = true;
      clearTimeout(watchdog);
      clearTimeout(hardStop);
      let result;
      try {
        if (error) throw error;
        result = JSON.parse(receipt);
        if (!Number.isInteger(result.exit_code) || typeof result.timed_out !== 'boolean' ||
            typeof result.termination?.verified !== 'boolean' || !Array.isArray(result.termination.remaining_pids)) {
          throw new Error('Invalid supervisor receipt');
        }
        if (helperSignal || helperExit !== Math.min(255, Math.max(0, result.exit_code))) {
          throw new Error('Supervisor receipt disagrees with helper exit');
        }
      } catch (failure) {
        result = {exit_code: 1, signal: helperSignal, timed_out: process.hrtime.bigint() >= deadline,
          termination: {attempted: true, verified: false, remaining_pids: [], cleanup_required: true,
            scope: 'Unconfirmed: lifecycle supervisor did not return a valid receipt'},
          errors: [String(failure.message || failure).slice(0, 500)]};
      }
      // Do not let inherited pipes from an unconfirmed descendant delay return.
      for (const stream of child.stdio) if (stream && !stream.destroyed) stream.destroy();
      resolve(result);
    };
    let hardStop;
    const watchdog = setTimeout(() => {
      error = new Error('Lifecycle supervisor exceeded its deadline and cleanup allowance');
      child.kill('SIGTERM');
      hardStop = setTimeout(() => {
        child.kill('SIGKILL');
        // Even an uninterruptible helper must not hold the caller indefinitely.
        // Its termination is explicitly unconfirmed in this failure result.
        child.unref();
        exited = true;
        streamEnded = true;
        finish();
      }, 100);
    }, timeoutMs + CLEANUP_MS + 500);
    child.once('error', failure => {
      error = failure;
      exited = true;
      streamEnded = true;
      finish();
    });
    child.once('exit', (code, sig) => {
      helperExit = code;
      helperSignal = sig;
      exited = true;
      finish();
    });
    child.stdio[3].on('data', chunk => {
      if (receipt.length + chunk.length > 32768) {
        error = new Error('Supervisor receipt exceeds its size limit');
        child.kill('SIGTERM');
      } else receipt += chunk.toString('utf8');
    });
    child.stdio[3].once('end', () => { streamEnded = true; finish(); });
    child.stdio[3].once('error', failure => { error = failure; streamEnded = true; finish(); });
    if (onSpawn) {
      try { onSpawn(child); }
      catch (failure) { error = failure; child.kill('SIGTERM'); }
    }
  });
}

module.exports = {supervise};
