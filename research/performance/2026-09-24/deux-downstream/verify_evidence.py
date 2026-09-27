#!/usr/bin/env python3
"""Bounded, read-only audit of the prepared Deux downstream diagnostic ZIP.

Checks archive/source/input/receipt bindings and reproduces the pure comparison
and original consumer replay/resampling. Never runs a model, alters thresholds,
or grants quality, performance, release or 75-percent approval.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import zipfile

SOURCE = '8590ac4a67de4340857a96ffe38bae53d7d902b8'
TREE = 'c841bf18f91d3d04dd6daf7e886e2aa473ab8c70'
SOURCE_HASHES = {
  "tools/compare_deux_downstream.cjs": "d1a4bf073d946d3f81d7d79e32842ec138c5c4510b809ddf6405ebc4307cb2ad",
  "qa/release-2.3.2/mdx-downstream-compare.cjs": "c17e44bcc89ca3f2e257abb1c065369a1747d8bef2541d0cd00f36bc5c284605",
  "web/analysis/ASSET_MANIFEST.json": "c0dc1d56b53cf7f316697d45f0a2cb5a63c4bf7068ba89829619cadfe46ff790",
  "web/analysis/separator-deux.js": "6a37acd3fd3923f32249d9640462cc06768c41901ee000837e17f21205d22867",
  "web/analysis/dsp.js": "f95357f71693a5df05e47c5baed5a15cca88bf5371d4b20dc51b3dbb6624fc06",
  "web/analysis/stem-cache.js": "d464a6759188c19e83e9ea7b22fdcbfcdaaca99c06fea930f2fbe9306dcdd5fd",
  "web/analysis/wav-reader.js": "6cd0a40392617cc020f2ec4f87952f165e070c8c17bc4aa3b36b212823d897d4",
  "web/analysis/vocal.js": "3f4be80b6b3747a733fcddce1257e332fe20bde70f29fa8c6be0ef076a9bf72d",
  "web/analysis/vocal-detail.js": "cd760d7a766d9a4ab0ac3a252a10f17a16a797b38e50b2d6712bc6adcd42713f",
  "web/analysis/game.js": "a4225b832bb8cee4d382b01b8753266b426d2a75be49515dc58bbb12e5a03b75",
  "web/analysis/worker.js": "0660d76f5e030e808cfafa2f987f6da4197f45e2415c3586f9a2313c5faab655",
  "web/analysis/models/features.json": "8a9fb3bc88c3e2f35934dd0024f22458aa8d357e3e3946a6e2c6230d3886e278",
  "web/analysis/models/vocal-model.json": "52093f26d0bfe3f04bbb1563b287fafe5e61aa57a61391ea643b04d97838ca7e",
  "web/analysis/models/vocal-frontend.json": "72bdffced29bfdd6d1da77a4da2a2a4af1b2f839c71131d19dc9423db3d4732f",
  "web/analysis/models/game/manifest.json": "51e172cfaa967d9e2518f01f508a64d49cd283d23ae8e8456af9c6e76eeb4f97",
  "web/analysis/models/game/config.json": "4d62b6d058a820e981184ea6f04605d37659c4331ee01979eb14a14be08af890",
  "web/analysis/models/deux/manifest.json": "6aebf45e6e7f6fa974f14fe47a252fc01f48da4815f40a1fdf10641a432529a9",
  "tools/benchmark_deux_accelerator.py": "0c19caa398c6fb1e1be121d359219074e71879979105d4172fbcf360906c9f0a",
  "tools/profile_deux_operators.py": "9a4e189d899a2f5c3c0e92df64ef4e1f3316ef422d53216d92b983e221c235d6",
  "tools/benchmark_deux_execution.py": "2fdeceb1fd4fd275b31338aeff6be6a5e53afb741c15de5dc020f65cbed72f3f",
  "tests/NativeDeuxExecutionBenchmark.java": "70eab8091070904493493bd94e7a6467a031628e0feb432055942cdd1bd1b0bb",
  "android/src/com/cyberbasslord/lightforge/NativeDeux.java": "084fec27d1fad0b10db01a960c614d333bb8c049e712c3fc4524d66e6dc3dd37",
  "android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java": "991b06501cfb88b904d0b714a525c389f169f00c231248b0e961b70f257e90b5",
  "android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java": "aa1d6bd370d88a774792cb76b4a18604d3ab2bffba58ab382e9045cad071acc1",
  "android/native-runtime.json": "e3ea568b3a8485235f23a59cd787466cdcbbfcaa54ac56df3ce040d29fcb2a94"
}
SOURCE_NAMES = [
    'tools/compare_deux_downstream.cjs', 'qa/release-2.3.2/mdx-downstream-compare.cjs',
    'web/analysis/ASSET_MANIFEST.json', 'web/analysis/separator-deux.js',
    'web/analysis/dsp.js', 'web/analysis/stem-cache.js', 'web/analysis/wav-reader.js',
    'web/analysis/vocal.js', 'web/analysis/vocal-detail.js', 'web/analysis/game.js',
    'web/analysis/worker.js', 'web/analysis/models/features.json',
    'web/analysis/models/vocal-model.json', 'web/analysis/models/vocal-frontend.json',
    'web/analysis/models/game/manifest.json', 'web/analysis/models/deux/manifest.json',
]
CAPTURE_NAMES = [
    'tools/benchmark_deux_accelerator.py', 'tools/profile_deux_operators.py',
    'tools/benchmark_deux_execution.py', 'tests/NativeDeuxExecutionBenchmark.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeux.java',
    'android/src/com/cyberbasslord/lightforge/NativeDeuxTransform.java',
    'android/src/com/cyberbasslord/lightforge/NativeInferenceProfile.java',
    'android/native-runtime.json', 'web/analysis/models/deux/manifest.json',
]
AUDIO = '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650'
APK = 'af83bf403875c55d42fd695d43f6e193114899c1324fbaeaffd6c02d299d882f'
NODE_SHA = 'c0649af18e6a24f6fe5535a3e86b341dd49a8e71117c8b68bde973ef834f16f2'
FALSE_FLAGS = ('qualityApproved', 'target75Proven', 'releaseAuthorized', 'benchmarkTimingAdmitted')
ARMS = ('cpu_all', 'cuda_basic')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pin(path):
    require(path.is_file() and not path.is_symlink(), 'Expected a regular file: ' + str(path))
    return dict(bytes=path.stat().st_size, sha256=digest(path))


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def floating(value):
        number = float(value)
        require(math.isfinite(number), 'Nonfinite JSON number')
        return number
    def bad(value):
        raise ValueError('Invalid JSON constant: ' + value)
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_float=floating, parse_constant=bad)


def safe_relative(name):
    require(isinstance(name, str) and name and '\\' not in name and '\0' not in name, 'Invalid relative path')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and all(part not in ('', '.', '..') for part in name.split('/'))
            and not re.match(r'^[A-Za-z]:', name), 'Unsafe relative path: ' + name)
    return relative


def file(root, name):
    value = root.joinpath(*safe_relative(name).parts)
    require(value.is_file() and not value.is_symlink() and value.resolve().is_relative_to(root.resolve()),
            'Missing/unsafe file: ' + name)
    return value


def flags(value, names=FALSE_FLAGS):
    for name in names:
        require(value.get(name) is False, 'Approval/timing flag must remain false: ' + name)


def extract(args):
    require(args.zip.is_file() and not args.zip.is_symlink(), 'Expected a regular input ZIP')
    expected = dict(bytes=args.expected_size, sha256=args.expected_sha256)
    require(pin(args.zip) == expected, 'ZIP size/SHA256 does not match displayed download identity')
    target = args.output_dir / 'extracted'
    target.mkdir()
    with zipfile.ZipFile(args.zip) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= 1000, 'Unexpected member count')
        seen, total = set(), 0
        for info in infos:
            name = info.filename.rstrip('/') if info.is_dir() else info.filename
            safe_relative(name)
            require(name not in seen, 'Duplicate ZIP member')
            seen.add(name)
            kind = stat.S_IFMT(info.external_attr >> 16)
            require(kind in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG), 'Unsafe ZIP member type')
            require(not info.flag_bits & 1, 'Encrypted ZIP member')
            total += info.file_size
            require(0 <= info.file_size <= args.max_uncompressed_bytes, 'Oversized member')
        require(total <= args.max_uncompressed_bytes, 'ZIP exceeds bounded extraction limit')
        for info in infos:
            path = target.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, path.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                require(path.stat().st_size == info.file_size, 'Extracted member size differs')
    require(pin(args.zip) == expected, 'ZIP changed during extraction')
    roots = list(target.iterdir())
    require(len(roots) == 1 and roots[0].is_dir(), 'Expected a single evidence root')
    require(re.fullmatch(r'\d{8}T\d{6}Z-deux-downstream-[a-f0-9]{8}', roots[0].name), 'Unexpected evidence root')
    return roots[0], dict(**expected, members=len(infos), uncompressedBytes=total, crcChecked=True)


def verify_sources(root, args):
    tree = subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', SOURCE + '^{tree}'], text=True).strip()
    require(tree == TREE, 'Frozen source tree differs')
    for name, expected in SOURCE_HASHES.items():
        data = subprocess.check_output(['git', '-C', str(args.repo), 'show', SOURCE + ':' + name])
        require(hashlib.sha256(data).hexdigest() == expected, 'Verifier source pin differs: ' + name)
        require(file(root, 'bound-source/' + name).read_bytes() == data, 'Archived source differs: ' + name)
    actual = {str(path.relative_to(root / 'bound-source')) for path in (root / 'bound-source').rglob('*') if path.is_file()}
    require(actual == set(SOURCE_HASHES), 'Bound source inventory differs')
    inventory = read_json(file(root, 'bound-source/web/analysis/ASSET_MANIFEST.json'))
    for name in SOURCE_HASHES:
        if name.startswith('web/analysis/') and not name.endswith('ASSET_MANIFEST.json'):
            require(pin(file(root, 'bound-source/' + name)) == inventory[name[13:]], 'Application inventory differs: ' + name)
    return inventory


def validate_parent(root, setup):
    parent = read_json(file(root, 'parent-binding.json'))
    captured = read_json(file(root, 'captured-inputs/receipt.json'))
    require(captured['schema'] == 'lightforge.deux-accelerator-experiment.v1', 'Unexpected upstream schema')
    require(captured['status'] == 'NUMERICAL_EQUIVALENCE_UNPROVEN', 'Unexpected upstream status')
    require(captured['inputsRecheckedAfterQualification'] is True, 'Upstream input recheck missing')
    flags(captured, ('measured', 'qualityApproved', 'target75Proven', 'releaseAuthorized', 'outputBytesQualifiedForTiming'))
    require(captured['startSample'] == -66150 and captured['samplesPerStem'] == 573300
            and captured['audioFrames'] == 2822400 and captured['audioSha256'] == AUDIO, 'Unexpected source passage')
    require(captured['sourceHashes'] == {name: SOURCE_HASHES[name] for name in CAPTURE_NAMES}, 'Capture source pins differ')
    require(parent['receipt'] == pin(file(root, 'captured-inputs/receipt.json')), 'Parent receipt pin differs')
    require(parent['upstreamSetup'] == pin(file(root, 'parent-setup-receipt.json')), 'Parent setup pin differs')
    require(parent['upstreamProcess'] == pin(file(root, 'parent-qualification-process.json')), 'Parent process pin differs')
    require(parent['audio']['sha256'] == AUDIO and parent['audio']['bytes'] > 0, 'Parent audio pin differs')
    require(set(parent['outputs']) == set(ARMS), 'Parent output inventory differs')
    for key, value in parent.items():
        require(setup['bindings'][key] == value, 'Setup/parent bindings differ: ' + key)
    process = read_json(file(root, 'parent-qualification-process.json'))
    require(process['status'] == 'PROCESS_EXITED' and process['returnCode'] == 1
            and process['receiptStatus'] == captured['status'], 'Upstream process was not the expected stopped diagnostic')
    expected_sources = {name: SOURCE_HASHES[name] for name in CAPTURE_NAMES}
    parent_setup = read_json(file(root, 'parent-setup-receipt.json'))
    require(parent_setup['sourceCommit'] == SOURCE and parent_setup['sourceTree'] == TREE
            and parent_setup['sourceHashes'] == expected_sources, 'Parent source identity differs')
    require(parent_setup['publicApkSha256'] == APK and parent_setup['publicAudioSha256'] == AUDIO, 'Parent public inputs differ')
    flags(parent_setup, ('qualityApproved', 'target75Proven', 'releaseAuthorized'))
    manifest = read_json(file(root, 'bound-source/web/analysis/models/deux/manifest.json'))
    require(captured['modelManifestSha256'] == SOURCE_HASHES['web/analysis/models/deux/manifest.json'], 'Capture manifest differs')
    require(captured['modelHashes'] == {name: item['sha256'] for name, item in manifest['files'].items()}, 'Capture model pins differ')
    for arm in ARMS:
        rows = [row for row in captured['runs'] if row['variant'] == arm and row['phase'] == 'qualification' and row['round'] == 0]
        observer_rows = [row for row in captured['runs'] if row['variant'] == arm + '_profiled' and row['phase'] == 'diagnostic' and row['round'] == 0]
        require(len(rows) == len(observer_rows) == 1, 'Missing/duplicate captured or profiled run')
        expected = parent['outputs'][arm]
        require(expected['bytes'] == 4586400, 'Unexpected captured size')
        for relative, row in ((arm + '/qualification-0.f32', rows[0]), (arm + '_profiled/diagnostic-0.f32', observer_rows[0])):
            path = file(root, 'captured-inputs/' + relative)
            require(pin(path) == expected == dict(bytes=row['outputBytes'], sha256=row['outputSha256']), 'Captured output identity differs')
            require(all(math.isfinite(value[0]) for value in struct.iter_unpack('<f', path.read_bytes())), 'Nonfinite captured waveform')
        observers = [item for item in captured['comparisons'] if item['reference'] == arm and item['candidate'] == arm + '_profiled']
        require(len(observers) == 1 and observers[0]['byteIdentical'] is True, 'Observer identity invalid')
        require(observers[0]['referenceSha256'] == observers[0]['candidateSha256'] == expected['sha256'], 'Observer digest differs')
        require(observers[0]['tolerance'] is None and observers[0]['qualityApproved'] is False, 'Observer tolerance/approval changed')
    return parent, captured


JS_AUDIT = r"""
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), crypto = require('node:crypto');
const root = process.argv[1], audio = process.argv[2], bound = path.join(root, 'bound-source');
const read = p => JSON.parse(fs.readFileSync(path.join(root, p)));
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const comparable = require(path.join(bound, 'qa/release-2.3.2/mdx-downstream-compare.cjs'));
const tool = require(path.join(bound, 'tools/compare_deux_downstream.cjs'));
const receipt = read('comparison/receipt.json'), declared = read('comparison/declared-contract.json');
assert.deepEqual(receipt.comparisonContract, declared.comparisonContract);
assert.deepEqual(receipt.comparisonContract.thresholds, comparable.thresholds);
const results = Object.fromEntries(['cpu_all','cuda_basic'].map(arm => [arm, read('comparison/' + arm + '/downstream.json')]));
const recomputed = comparable.compare(results.cuda_basic.comparable, results.cpu_all.comparable);
assert.deepEqual(recomputed, receipt.comparison, 'Stored comparison differs from unchanged comparator');
assert.equal(JSON.stringify(results.cpu_all.rawGameCheckpoints, null, 2) === JSON.stringify(results.cuda_basic.rawGameCheckpoints, null, 2), receipt.rawGameCheckpointsByteIdentical);
require(path.join(bound, 'web/analysis/dsp.js'));
require(path.join(bound, 'web/analysis/stem-cache.js'));
const Wav = require(path.join(bound, 'web/analysis/wav-reader.js'));
const config = JSON.parse(fs.readFileSync(path.join(bound, 'web/analysis/models/features.json')));
const manifest = JSON.parse(fs.readFileSync(path.join(bound, 'web/analysis/models/deux/manifest.json')));
const audioBytes = fs.readFileSync(audio);
assert.equal(sha(audioBytes), '33f07d502ba19832b62b97d8fb4a11354e81310264bd885d7a06438228773650');
const arrayBuffer = b => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
(async () => {
  let replayedWavs = 0;
  for (const arm of ['cpu_all','cuda_basic']) {
    const result = results[arm], reader = new Wav('host://public-demo');
    reader.cached = arrayBuffer(audioBytes); reader.totalBytes = audioBytes.length; await reader.open();
    assert.equal(reader.samples, 2822400);
    const bytes = fs.readFileSync(path.join(root, 'captured-inputs', arm, 'qualification-0.f32'));
    const {chunk, replay} = await tool.replayFirstChunk(reader, tool.readCaptured(bytes), manifest);
    assert.deepEqual(replay, result.replay);
    assert.deepEqual(replay, receipt.replay);
    for (const role of ['vocals', 'accompaniment']) {
      const parts = []; let closed = false;
      const stream = {async write(b) { assert.equal(closed, false); parts.push(Buffer.from(b)); }, async close() { closed = true; }};
      const writer = new LightForgeStemCache.DownsampleWriter(stream, config.resampleHalfFIR, chunk[role].length);
      await writer.push(chunk[role].subarray(0,65537),0); await writer.push(chunk[role].subarray(65537),65537); await writer.finish();
      assert.equal(closed,true);
      const payload = Buffer.concat(parts), wav = Buffer.concat([Buffer.from(LightForgeStemCache.header(Math.ceil(chunk[role].length/2))),payload]);
      assert.equal(sha(payload), result.resampledSha256[role]);
      const recorded = fs.readFileSync(path.join(root, 'comparison',arm,role+'-22050.wav'));
      assert.equal(wav.equals(recorded),true,'Original consumer/resampling bytes differ: '+arm+'/'+role);
      replayedWavs++;
    }
  }
  console.log(JSON.stringify({comparisonReproduced:true, consumerReplayReproduced:true, resampledWavsReproduced:replayedWavs,
    sensitivityPassed:recomputed.passed, errors:recomputed.errors, coverage:recomputed.coverage,
    arrays:recomputed.metrics.arrays, rawGameCheckpointsByteIdentical:receipt.rawGameCheckpointsByteIdentical,
    transcriptionExact:JSON.stringify(results.cpu_all.comparable.transcription)===JSON.stringify(results.cuda_basic.comparable.transcription),
    fusedVocalsExact:JSON.stringify(results.cpu_all.comparable.vocals)===JSON.stringify(results.cuda_basic.comparable.vocals),
    localAuditNode:process.version, modelInferencePerformed:false}));
})().catch(error => { console.error(error.stack); process.exitCode=1; });
"""


def audit(args):
    root, archive = extract(args)
    driver = read_json(file(root, 'driver-receipt.json'))
    require(driver['schema'] == 'lightforge.deux-downstream-driver.v1', 'Unexpected driver schema')
    flags(driver)
    inventory = driver['artifactHashes']
    actual = {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()} - {'driver-receipt.json'}
    require(set(inventory) == actual, 'Driver artifact inventory is incomplete or contains extras')
    for name, expected in inventory.items():
        require(pin(file(root, name)) == expected, 'Archived artifact identity differs: ' + name)
    # Every JSON must have unique keys and finite numbers, including partial artifacts.
    json_files = list(root.rglob('*.json'))
    for path in json_files:
        read_json(path)
    assets = verify_sources(root, args)
    setup = read_json(file(root, 'setup-receipt.json'))
    flags(setup)
    require(setup['schema'] == 'lightforge.deux-downstream-setup.v1' and setup['sourceCommit'] == SOURCE
            and setup['sourceTree'] == TREE and setup['originalSourceUntouched'] is True, 'Unexpected downstream setup')
    require(setup['bindings']['sourceSnapshot'] == SOURCE_HASHES, 'Setup source bindings differ')
    node = setup['bindings']['nodeArchive']
    require(node == dict(sha256=NODE_SHA, url='https://nodejs.org/dist/v22.19.0/node-v22.19.0-linux-x64.tar.xz',
        checksumSource='https://nodejs.org/en/blog/release/v22.19.0', version='v22.19.0'), 'Node archive pin differs')
    require(setup['bindings']['node']['bytes'] > 0 and re.fullmatch('[a-f0-9]{64}', setup['bindings']['node']['sha256']), 'Missing Node binary pin')
    game = read_json(file(root, 'bound-source/web/analysis/models/game/manifest.json'))
    vocal = read_json(file(root, 'bound-source/web/analysis/models/vocal-model.json'))
    binary_names = ['models/game/' + name for name in game['files']] + [
        'models/' + vocal['file'], 'vendor/ort.wasm.min.js', 'vendor/ort-wasm-simd-threaded.wasm', 'vendor/ort-wasm-simd-threaded.mjs']
    require(setup['bindings']['assets'] == {'web/analysis/' + name: assets[name] for name in binary_names}, 'Downstream asset inventory differs')
    parent, captured = validate_parent(root, setup)
    require(pin(args.audio) == parent['audio'], 'Local public audio does not match archived identity')
    report = read_json(file(root, 'comparison/receipt.json'))
    declared = read_json(file(root, 'comparison/declared-contract.json'))
    require(report['schema'] == declared['schema'] == 'lightforge.deux-downstream-sensitivity.v1', 'Unexpected comparator schema')
    flags(report); flags(declared)
    require(report['status'] in ('EXCERPT_SENSITIVITY_PASS', 'EXCERPT_SENSITIVITY_FAILED'), 'Comparator did not complete: ' + report['status'])
    require(driver['status'] == 'DIAGNOSTIC_COMPLETED' and driver['errors'] == report['errors'] == declared['errors'] == [], 'Driver/comparator did not complete cleanly')
    require(driver['inputsRecheckedAfterComparison'] is True and report['inputsRecheckedAfterComparison'] is True, 'Terminal input checks missing')
    require(driver['sensitivityPassed'] is report['sensitivityPassed'], 'Driver/result agreement differs')
    require(report['status'] == ('EXCERPT_SENSITIVITY_PASS' if report['sensitivityPassed'] else 'EXCERPT_SENSITIVITY_FAILED'), 'Comparator status/result mismatch')
    require(driver['returnCode'] == (0 if report['sensitivityPassed'] else 2), 'Comparator exit differs')
    require(driver['comparatorReceipt'] == pin(file(root, 'comparison/receipt.json'))
            and driver['driverLog'] == pin(file(root, 'driver.log')), 'Driver closed-file binding differs')
    require(declared['status'] == 'INCOMPLETE' and declared['sensitivityPassed'] is False, 'Pre-run declaration differs')
    require(declared['bindings'] == report['bindings'], 'Predeclared binding differs')
    bindings = report['bindings']
    require(bindings['receiptSha256'] == parent['receipt']['sha256'] and bindings['receiptStatus'] == captured['status'], 'Comparator input receipt differs')
    require(bindings['audioSha256'] == AUDIO and bindings['audioFrames'] == 2822400, 'Comparator audio differs')
    require(bindings['sourceHashes'] == {name: SOURCE_HASHES[name] for name in SOURCE_NAMES}, 'Comparator source inventory differs')
    require(bindings['captureSourceHashes'] == captured['sourceHashes'], 'Comparator capture-source inventory differs')
    asset_names = set(binary_names + [name[13:] for name in SOURCE_NAMES if name.startswith('web/analysis/') and not name.endswith('ASSET_MANIFEST.json')])
    require(bindings['assetHashes'] == {'web/analysis/' + name: assets[name]['sha256'] for name in asset_names}, 'Comparator asset pins differ')
    expected_replay = dict(nativeCalls=1, sourceSamples=2822400, reads=[dict(start=-66150,count=573300),dict(start=154350,count=573300)],
        stoppedAtMissingPassage=True, sourceComplete=False, firstCommittedSamples=220500, haloSamples=66150,
        coreSamples=441000, strideSamples=220500, overlapBetweenTwoMeasuredPassagesExercised=False)
    require(report['replay'] == expected_replay, 'Consumer replay scope differs')
    for arm in ARMS:
        expected_output = dict(file=arm + '/qualification-0.f32', **parent['outputs'][arm])
        require(bindings['outputs'][arm] == expected_output, 'Comparator waveform binding differs')
        path = file(root, 'comparison/' + arm + '/downstream.json')
        result = read_json(path)
        require(result['bindings'] == bindings and result['replay'] == expected_replay, 'Child input/replay binding differs')
        require(result['downstreamInputIsBoundedExcerpt'] is True and result['downstreamWholeSourceContextPreserved'] is False, 'Child scope widened')
        require(result['comparable']['runtime'] == '1.20.1', 'WASM runtime version differs')
        require(result['comparable']['samples44100'] == 220500 and result['comparable']['samples22050'] == 110250, 'Child sample count differs')
        require(result['comparable']['sourceClock'] == dict(sampleRate=44100,coreStartSample=0,emittedSamples=220500,
            contextReadStart=-66150,contextReadSamples=573300,fullSourceSamples=2822400), 'Child source clock differs')
        require(report['outputs'][arm] == dict(file=arm + '/downstream.json',sha256=digest(path)), 'Child output digest differs')
        recheck = read_json(file(root, 'comparison/' + arm + '-input-recheck.json'))
        require(recheck == dict(variant=arm,inputsRechecked=True,unchanged=True,errors=[]), 'Child terminal recheck differs')
        expected_models = {'web/analysis/' + name: assets[name]['sha256'] for name in binary_names if name.endswith('.onnx')}
        require(result['comparable']['loadedModels'] == expected_models, 'Missing or unbound executed model')
    require(report['comparisonContract']['source'] == 'qa/release-2.3.2/mdx-downstream-compare.cjs'
            and report['comparisonContract']['sha256'] == SOURCE_HASHES['qa/release-2.3.2/mdx-downstream-compare.cjs'], 'Comparison contract differs')
    executed = subprocess.run([args.node, '-e', JS_AUDIT, str(root), str(args.audio)],
        check=True, capture_output=True, text=True, timeout=180)
    replay = json.loads(executed.stdout)
    require(replay['sensitivityPassed'] is report['sensitivityPassed'], 'Recomputed comparison/receipt status differs')
    require(pin(args.zip) == dict(bytes=args.expected_size,sha256=args.expected_sha256), 'Input ZIP changed during audit')
    return dict(schema='lightforge.deux-downstream-independent-audit.v1', status='ARCHIVE_AND_RECORDED_DIAGNOSTIC_VERIFIED',
        archive=archive, evidenceRoot=root.name, sourceCommit=SOURCE, sourceTree=TREE,
        artifactFilesVerified=len(inventory), strictJsonFilesVerified=len(json_files), frozenSourceFilesVerified=len(SOURCE_HASHES),
        actualCapturedAndProfiledWaveformsVerified=4, upstreamStatus=captured['status'], comparatorStatus=report['status'],
        independentReplay=replay, qualityApproved=False,target75Proven=False,releaseAuthorized=False,benchmarkTimingAdmitted=False,
        limits=['This independently checks archived bytes, captured/profiled waveform identity, the consumer replay/resampling and the existing pure comparison.',
                'Model inference is not repeated by this auditor. Absent model/Node binaries are checked against recorded immutable pins, not rehashed here.',
                'The complete upstream accelerator archive remains necessary for compiled snapshots, native library and CUDA placement evidence.',
                'One five-second bounded excerpt does not establish full-song quality, second-passage overlap-add, Android behavior, or admitted benchmark ratios.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--expected-size', type=int, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--node', default='node')
    parser.add_argument('--max-uncompressed-bytes', type=int, default=256*1024*1024)
    args = parser.parse_args()
    args.zip, args.repo, args.audio, args.output_dir = (path.absolute() for path in (args.zip,args.repo,args.audio,args.output_dir))
    require(re.fullmatch('[a-f0-9]{64}', args.expected_sha256) and args.expected_size > 0, 'Invalid expected archive identity')
    require(not args.output_dir.exists(), 'Output directory must be new; existing evidence cannot be replaced')
    args.output_dir.mkdir(parents=True)
    try:
        result = audit(args)
    except Exception as error:
        result = dict(schema='lightforge.deux-downstream-independent-audit.v1',status='AUDIT_REJECTED',error=type(error).__name__+': '+str(error),
            qualityApproved=False,target75Proven=False,releaseAuthorized=False,benchmarkTimingAdmitted=False)
        (args.output_dir/'audit-rejected.json').write_text(json.dumps(result,indent=2)+'\n')
        raise
    (args.output_dir/'audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
