"""Fault-injected harness control flow, not rendered browser or model proof."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Exercise the real producer with deterministic Playwright/HTTP doubles. Only
# the test process accelerates deadlines; production budgets remain fixed.
HOOK = r"""
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const load = Module._load, nativeTimeout = global.setTimeout;
global.setTimeout = (fn, ms, ...args) => nativeTimeout(fn, ms >= 1000 ? 25 : ms, ...args);
const receiptPath = path.join(process.env.LIGHTFORGE_RESTORE_QA_OUTPUT, 'restore-preview-verification.json');
const receipt = () => JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
const scenario = JSON.parse(process.env.HARNESS_FAULTS || '{}');
function invoke(value) {
  const phase = receipt().phase;
  if (scenario[phase] === 'throw') throw Error('Injected failure at ' + phase);
  if (scenario[phase] === 'hang') {
    setInterval(() => {}, 10000); // Simulate an outstanding browser/socket handle.
    return new Promise(() => {});
  }
  return Promise.resolve(value);
}
const calls = ['begin', 'worker-started', 'worker-verified', 'show-adopted', 'preview-starting', 'preview-first-render', 'preview-visual-commit', 'terminal', 'ack'];
function page() {
  const handlers = {};
  return {
    on(event, handler) { handlers[event] = handler; },
    addInitScript() { return invoke(); }, goto() { return invoke(); }, close() { return invoke(); },
    screenshot() { return invoke(); },
    waitForFunction() {
      if (receipt().phase === 'cold-restore-proof') handlers.request?.({url: () => 'http://local/preview/models/highland.glb'});
      return invoke();
    },
    evaluate() {
      const phase = receipt().phase;
      if (phase === 'fixture-compile') return invoke({compiled: {sha256: 'fixture-sha'}});
      if (phase === 'cold-deferred-observation') return invoke({contexts: 0, graphics: false, started: false, deferred: true, frames: 0});
      if (phase === 'cold-complete-observation') return invoke({calls, contexts: 1, sha256: 'fixture-sha', loaded: true, frames: 1, pending: false, quality: {}});
      if (phase === 'foreground-paused-observation') return invoke({calls: [], pending: true, applying: false, busy: false, paused: true, ack: null});
      if (phase === 'foreground-resume') handlers.request?.({url: () => 'http://local/completed-project.json'});
      if (phase === 'foreground-complete-observation') return invoke({calls, sha256: 'fixture-sha', loaded: true, frames: 1, pending: false, paused: false});
      return invoke();
    },
  };
}
const browser = {
  newPage() { return invoke(page()); },
  close() {
    fs.writeFileSync(path.join(process.env.LIGHTFORGE_RESTORE_QA_OUTPUT, 'before-browser-close.json'), JSON.stringify(receipt()));
    return invoke();
  },
};
Module._load = function(name, ...args) {
  if (name === 'playwright') return {chromium: {launch: () => invoke(browser)}};
  if (name.endsWith('local-http-security.cjs')) return {allowLocalRequest: () => true};
  if (name === 'node:http') return {createServer() {
    return {
      listening: false, once() {}, address: () => ({port: 12345}),
      listen(_port, _host, callback) { this.listening = true; invoke().then(callback); },
      close(callback) { invoke().then(() => { this.listening = false; callback(); }); },
      closeAllConnections() { fs.writeFileSync(path.join(process.env.LIGHTFORGE_RESTORE_QA_OUTPUT, 'connections-closed'), 'yes'); },
    };
  }};
  return load.call(this, name, ...args);
};
"""


class RestorePreviewHarnessTimeoutTest(unittest.TestCase):
    def run_harness(self, faults):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'qa/restore-preview/browser.cjs'
            script.parent.mkdir(parents=True)
            script.write_bytes((ROOT / 'qa/restore-preview/browser.cjs').read_bytes())
            (root / 'version.json').write_text('{"name":"9.8.7"}')
            inventory_name = 'qa/release-9.8.7/browser-source-inventory.json'
            inventory = root / inventory_name
            inventory.parent.mkdir(parents=True)
            inventory.write_text(json.dumps({
                'schema': 'lightforge.browser-source-inventory.v1',
                'common': ['version.json', inventory_name],
                'restore_preview': ['qa/restore-preview/browser.cjs'],
            }))
            hook = root / 'hook.cjs'
            hook.write_text(HOOK)
            output = root / 'output'
            env = dict(os.environ, LIGHTFORGE_RESTORE_QA_OUTPUT=str(output),
                       LIGHTFORGE_EVIDENCE_SESSION='a' * 64,
                       HARNESS_FAULTS=json.dumps(faults))
            completed = subprocess.run(['node', '--require', str(hook), str(script)],
                                       cwd=root, env=env, text=True,
                                       capture_output=True, check=False, timeout=5)
            receipt = json.loads((output / 'restore-preview-verification.json').read_text())
            before_close_path = output / 'before-browser-close.json'
            before_close = json.loads(before_close_path.read_text()) if before_close_path.exists() else None
            return completed, receipt, before_close, (output / 'connections-closed').exists()

    def test_success_is_published_only_after_cleanup_and_all_original_checks(self):
        result, receipt, before_close, connections_closed = self.run_harness({})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(receipt['passed'])
        self.assertEqual(receipt['phase'], 'complete')
        self.assertEqual(receipt['errors'], [])
        self.assertEqual(len(receipt['checks']), 4)
        self.assertFalse(before_close['passed'])
        self.assertTrue(connections_closed)
        self.assertEqual(receipt['source_hashes'], before_close['source_hashes'])

    def test_unresponsive_compile_or_observation_records_phase_before_cleanup(self):
        for phase in ('fixture-compile', 'cold-complete-observation'):
            with self.subTest(phase=phase):
                result, receipt, before_close, connections_closed = self.run_harness({phase: 'hang'})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(receipt['passed'])
                self.assertEqual(receipt['phase'], 'failed')
                self.assertEqual(receipt['failurePhase'], phase)
                self.assertIn(f'phase "{phase}" exceeded', receipt['errors'][0])
                self.assertEqual(before_close['errors'], receipt['errors'])
                self.assertEqual(len(receipt['source_hashes']), 3)
                self.assertTrue(connections_closed)
                self.assertIn(f'[restore-preview] {phase}', result.stdout)

    def test_launch_timeout_still_closes_the_server_and_exits_nonzero(self):
        result, receipt, before_close, connections_closed = self.run_harness({'browser-launch': 'hang'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(receipt['passed'])
        self.assertEqual(receipt['failurePhase'], 'browser-launch')
        self.assertIn('browser-launch', receipt['errors'][0])
        self.assertIsNone(before_close)
        self.assertTrue(connections_closed)

    def test_browser_or_server_cleanup_timeout_cannot_publish_a_pass(self):
        for phase in ('browser-close', 'server-close'):
            with self.subTest(phase=phase):
                result, receipt, before_close, connections_closed = self.run_harness({phase: 'hang'})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(receipt['passed'])
                self.assertEqual(len(receipt['checks']), 4)
                self.assertEqual(receipt['failurePhase'], phase)
                self.assertIn(f'phase "{phase}" exceeded', receipt['errors'][0])
                self.assertFalse(before_close['passed'])
                self.assertTrue(connections_closed)

    def test_cleanup_failure_preserves_the_original_failure_and_evidence(self):
        result, receipt, before_close, connections_closed = self.run_harness({
            'fixture-navigation': 'throw', 'browser-close': 'hang',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(receipt['passed'])
        self.assertEqual(receipt['failurePhase'], 'fixture-navigation')
        self.assertEqual(len(receipt['errors']), 2)
        self.assertIn('Injected failure at fixture-navigation', receipt['errors'][0])
        self.assertIn('browser-close', receipt['errors'][1])
        self.assertEqual(before_close['errors'], receipt['errors'][:1])
        self.assertEqual(before_close['source_hashes'], receipt['source_hashes'])
        self.assertTrue(connections_closed)
        self.assertIn('completedAt', receipt)


if __name__ == '__main__':
    unittest.main()
