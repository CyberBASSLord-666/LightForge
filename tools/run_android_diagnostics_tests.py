#!/usr/bin/env python3
"""Verify real Android crash capture and app-to-Downloads diagnostic export, without inference."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
from android_evidence_binding import verify_provenance
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'com.cyberbasslord.lightforge'
RUNNER = PACKAGE + '.diagnostics.tests/' + PACKAGE + '.DiagnosticsInstrumentation'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-dir', type=Path, default=ROOT / 'candidate')
    args = parser.parse_args()
    version = json.loads((ROOT / 'version.json').read_text())['name']
    out = ROOT / ('qa/release-' + version)
    out.mkdir(parents=True, exist_ok=True)
    sdk = Path(os.environ['ANDROID_HOME'])
    adb = sdk / 'platform-tools/adb'
    sources = sorted(set([*ROOT.joinpath('android').rglob('*.java'),
                          *ROOT.joinpath('android').rglob('*.xml'),
                          *ROOT.joinpath('web').rglob('*.js'),
                          *ROOT.joinpath('web').rglob('*.html'),
                          ROOT / 'tests/android/DiagnosticsInstrumentation.java',
                          ROOT / 'tools/build_diagnostics_tests.py', ROOT / 'tools/android_evidence_binding.py', Path(__file__).resolve(),
                          ROOT / 'android/native-runtime.json',
                          ROOT / 'version.json']))

    def source_hashes():
        return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sources if path.is_file()}

    hashes = source_hashes()
    receipt = dict(release=version, passed=False, checks=[], errors=[], source_hashes=hashes,
                   scope='Android API 35 emulator: real uncaught worker and intentional native SIGILL '
                         'crashes followed by process restart, binary tombstone extraction and production '
                         'native compatibility selection from a durable execution lease; persistent '
                         'sanitized traces, production Guide export through its JavaScript '
                         'bridge to MediaStore Downloads, repeated files and detached renderer recovery. '
                         'No neural inference or physical-device performance claim.')

    def run(*command, timeout=120, check=True):
        result = subprocess.run([str(adb), *map(str, command)], text=True, capture_output=True,
                                timeout=timeout, check=check)
        return result.stdout + result.stderr

    def instrument(mode, marker, native_pid=0):
        path = out / ('android-diagnostics-' + mode + '.log')
        command = [str(adb), 'shell', 'am', 'instrument', '-w', '-e', 'mode', mode,
                   '-e', 'marker', marker, '-e', 'nativePid', str(native_pid), RUNNER]
        # A hard four-minute bound catches an unresponsive main thread; the test does no inference.
        with path.open('w', encoding='utf-8') as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=240)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                raise RuntimeError('Diagnostic instrumentation timed out in ' + mode)
        result = path.read_text()
        print(result, flush=True)
        if mode not in ('crash', 'native-crash') and code:
            raise RuntimeError('Diagnostic instrumentation adb exited with code ' + str(code))
        return result

    native_probe_started = False
    marker = None
    try:
        receipt['candidateBinding'] = verify_provenance(ROOT, args.candidate_dir)
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            log = ROOT / 'emulator.log'
            if log.is_file():
                fatal = [line for line in log.read_text(errors='replace').splitlines() if 'FATAL' in line]
                if fatal:
                    raise RuntimeError('Emulator boot failed: ' + fatal[-1])
            try:
                if run('shell', 'getprop', 'sys.boot_completed', timeout=10).strip() == '1':
                    break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Android emulator did not boot')
        apk = args.candidate_dir / ('LightForge-' + version + '.apk')
        metadata = json.loads(apk.with_suffix('.apk.json').read_text())
        with apk.open('rb') as stream:
            actual_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert apk.stat().st_size == metadata['bytes'] and actual_hash == metadata['sha256'], 'Candidate APK does not match its build receipt'
        receipt['candidate'] = metadata
        run('install', '-r', apk, timeout=300)
        run('install', '-r', args.candidate_dir / 'diagnostics-tests.apk')
        run('shell', 'dumpsys', 'deviceidle', 'unforce')
        run('shell', 'dumpsys', 'battery', 'reset')
        run('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
        run('shell', 'wm', 'dismiss-keyguard')
        run('shell', 'settings', 'put', 'global', 'show_first_crash_dialog', '0')
        run('shell', 'am', 'force-stop', PACKAGE)
        marker = 'probe' + str(time.time_ns() // 1000000)
        crashed = instrument('crash', marker)
        expected = re.search(r'DIAGNOSTICS_EXPECTED_UNCAUGHT_CRASH ' + marker + r' pid=(\d+)', crashed)
        assert expected, 'Crash fixture did not reach the intentional uncaught exception'
        assert 'Process crashed' in crashed, 'Android did not report the intentionally crashed process'
        run('shell', 'am', 'force-stop', PACKAGE)
        native_probe_started = True
        native_crashed = instrument('native-crash', marker)
        native_expected = re.search(r'DIAGNOSTICS_EXPECTED_NATIVE_CRASH ' + marker + r' pid=(\d+)', native_crashed)
        assert native_expected, 'Native crash fixture did not durably mark its intentional SIGILL'
        assert 'Process crashed' in native_crashed, 'Android did not report the intentional native crash'
        assert native_expected.group(1) != expected.group(1), 'Native crash fixture did not restart after the Java crash'
        run('shell', 'am', 'force-stop', PACKAGE)
        result = instrument('verify', marker, int(native_expected.group(1)))
        assert 'DIAGNOSTICS_ANDROID_PASS' in result, 'Android diagnostic checks failed; see android-diagnostics-verify.log'
        details = [json.loads(line.split('DIAGNOSTICS_ANDROID_RESULT ', 1)[1])
                   for line in result.splitlines() if 'DIAGNOSTICS_ANDROID_RESULT ' in line]
        assert len(details) == 1 and details[0]['passed'], 'Diagnostic report missing or invalid'
        assert details[0]['pid'] != int(expected.group(1)), 'Persistence was not verified across different app processes'
        assert details[0]['pid'] != int(native_expected.group(1)), 'Native recovery was not verified in a fresh process'
        assert details[0]['nativeCrashPid'] == int(native_expected.group(1)), 'Native recovery is not bound to the exact crashed process'
        assert details[0]['mode'] == 'verify', 'Unexpected diagnostic verification mode'
        assert details[0]['marker'] == marker and details[0]['checks'], 'Diagnostic report is not bound to this run'
        receipt['device'] = details[0]
        receipt['crashProcesses'] = dict(javaPid=int(expected.group(1)), nativePid=int(native_expected.group(1)),
                                         restartedPid=details[0]['pid'])
        receipt['checks'] = details[0]['checks']
        assert hashes == source_hashes(), 'Diagnostic sources changed during verification'
        receipt['passed'] = True
    except Exception as error:
        receipt['errors'].append(str(error))
        raise
    finally:
        if native_probe_started:
            try:
                # A timed-out UI verification may still own an unresponsive target process.
                # Cleanup must run in a new process and touch only this marker's saved fixture.
                run('shell', 'am', 'force-stop', PACKAGE)
                cleanup = instrument('cleanup', marker)
                assert 'DIAGNOSTICS_ANDROID_PASS' in cleanup, 'Native diagnostic fixture cleanup failed'
            except Exception as error:
                receipt['errors'].append('Native probe cleanup: ' + str(error))
                receipt['passed'] = False
        try:
            (out / 'android-diagnostics-logcat.txt').write_text(run('logcat', '-d', '-v', 'threadtime', timeout=20))
        except Exception:
            pass
        if not receipt['passed']:
            for name, command in [('last-anr', ('shell', 'dumpsys', 'activity', 'lastanr')),
                                  ('memory', ('shell', 'dumpsys', 'meminfo', PACKAGE))]:
                try:
                    (out / ('android-diagnostics-' + name + '.txt')).write_text(run(*command, timeout=15))
                except Exception:
                    pass
        receipt['completedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (out / 'android-diagnostics-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
        if not receipt['passed'] and not receipt['errors']:
            raise RuntimeError('Android diagnostic verification failed')
        if not receipt['passed'] and native_probe_started and any(
                error.startswith('Native probe cleanup:') for error in receipt['errors']):
            raise RuntimeError('Native diagnostic fixture cleanup failed; see verification receipt')


if __name__ == '__main__':
    main()
