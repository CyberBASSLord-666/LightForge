#!/usr/bin/env python3
"""Evaluate a local exported LightForge ZIP without uploading its audio or project.

This is a compiler/export evidence tool, not a model accuracy or release gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import wave
import zipfile

# Reuse the existing strict JSON reader and executed timing-profile contract.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_performance_timings import load_strict, wall, span

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'Review/LightForge_Project.json'
FSEQ = 'LightShow/lightshow.fseq'
AUDIO = 'LightShow/lightshow.wav'
VALIDATION = 'Review/Validation.json'
REQUIRED = frozenset({PROJECT, FSEQ, AUDIO})
MAX_JSON_BYTES = 64 * 1024**2
MAX_FSEQ_BYTES = 960000 * 200 + 65535
DEFAULT_MAX_TOTAL = 3 * 1024**3
CHUNK_BYTES = 1024**2


def require(value, message):
    if not value:
        raise ValueError(message)


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def number(value):
    if type(value) not in (float, int) or value < 0:
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def audit_entries(archive, max_total_bytes):
    """Reject ambiguous names and archive bombs before reading any payload."""
    infos = archive.infolist()
    require(0 < len(infos) <= 128, 'Archive entry count is outside supported bounds')
    seen, files, total = set(), {}, 0
    for info in infos:
        name = info.filename
        parts = PurePosixPath(name).parts
        require(name and '\\' not in name and ':' not in name and '\x00' not in name and not name.startswith('/')
                and all(part not in ('', '.', '..') for part in name.rstrip('/').split('/')),
                'Unsafe archive member path')
        require(all(not any(ord(ch) < 32 for ch in part) for part in parts), 'Unsafe archive member control character')
        normalized = name.rstrip('/').casefold()
        require(normalized not in seen, 'Duplicate or ambiguous archive member')
        seen.add(normalized)
        mode = info.external_attr >> 16
        require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'Archive links or special files are unsupported')
        require(not (info.flag_bits & 1), 'Encrypted archives are unsupported')
        require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported archive compression')
        if info.is_dir():
            require(info.file_size == 0, 'Nonempty archive directory entry')
            continue
        limit = MAX_JSON_BYTES if name.casefold().endswith('.json') else MAX_FSEQ_BYTES if name == FSEQ else max_total_bytes
        require(0 <= info.file_size <= limit, 'Archive member exceeds size limit')
        total += info.file_size
        require(total <= max_total_bytes, 'Archive expands beyond total size limit')
        files[name] = info
    require(REQUIRED <= set(files), 'Archive needs exported project, lightshow.fseq and lightshow.wav')
    # Even unused names may not describe both a file and a directory tree.
    file_names = {name.casefold() for name in files}
    for name in files:
        require(not any('/'.join(name.casefold().split('/')[:i]) in file_names
                        for i in range(1, len(name.split('/')))), 'Conflicting archive file/directory paths')
    return files


def stage_archive(archive_path, destination, max_total_bytes=DEFAULT_MAX_TOTAL):
    """Stream every member through CRC and SHA-256 checks; stage only fixed names."""
    require(type(max_total_bytes) is int and max_total_bytes > 0, 'Total size limit must be positive')
    source = Path(archive_path)
    require(source.is_file() and 0 < source.stat().st_size <= max_total_bytes, 'Archive file size is outside supported bounds')
    inventory = []
    with zipfile.ZipFile(source) as archive:
        files = audit_entries(archive, max_total_bytes)
        for name, info in files.items():
            keep = name in REQUIRED or name == VALIDATION
            target = destination / name
            if keep:
                target.parent.mkdir(parents=True, exist_ok=True)
            output = target.open('xb') if keep else None
            count, digest = 0, hashlib.sha256()
            try:
                with archive.open(info) as stream:
                    while chunk := stream.read(CHUNK_BYTES):
                        count += len(chunk)
                        require(count <= info.file_size, 'Archive member expands beyond declared size')
                        digest.update(chunk)
                        if output:
                            output.write(chunk)
                require(count == info.file_size, 'Archive member is truncated')
            finally:
                if output:
                    output.close()
            inventory.append({'name':name, 'bytes':count, 'sha256':digest.hexdigest()})
    return inventory


def inspect_audio(path):
    with wave.open(str(path), 'rb') as audio:
        require(audio.getcomptype() == 'NONE' and audio.getnchannels() == 2
                and audio.getsampwidth() == 2 and audio.getframerate() == 44100,
                'Expected exported stereo 44.1 kHz 16-bit PCM WAV')
        frames, byte_count = audio.getnframes(), 0
        require(0 < frames <= 44100 * 14400, 'Audio duration exceeds supported bounds')
        while chunk := audio.readframes(262144):
            byte_count += len(chunk)
        require(byte_count == frames * 4, 'WAV sample payload is truncated')
        return {'format':'PCM', 'sampleRate':44100, 'channels':2, 'bitsPerSample':16,
                'samplesPerChannel':frames, 'durationSeconds':frames / 44100}


def saved_timings(project):
    model = project.get('music', {}).get('engine') or project.get('provenance', {}).get('model') or {}
    require(isinstance(model, dict), 'Invalid saved model timing metadata')
    stages = model.get('stages', {})
    require(isinstance(stages, dict), 'Invalid saved timing stages')
    rows = {}
    for name in ('rhythm', 'separation', 'voice', 'bass'):
        row = stages.get(name, {})
        require(isinstance(row, dict), 'Invalid stage timing metadata')
        profile = row.get('profile')
        try:
            measured = wall(profile, name)
            inference = span(profile, name, 'model_inference')
        except OverflowError as error:
            raise ValueError('Saved timing metadata contains an out-of-range number') from error
        cache = profile.get('cache', []) if isinstance(profile, dict) else []
        cache = cache if isinstance(cache, list) else []
        outcomes = {entry.get('outcome') for entry in cache if isinstance(entry, dict) and entry.get('domain') == name}
        restored = row.get('restored') is True or 'restore' in outcomes
        cache_state = 'restored' if restored else 'miss' if row.get('restored') is False and 'miss' in outcomes else 'unknown'
        rows[name] = {'cacheState':cache_state, 'declaredSeconds':number(row.get('seconds')),
                      'observedWallSeconds':measured['seconds'] if measured else None,
                      'observedModelInferenceSeconds':inference['seconds'] if inference else None}
    resource = model.get('resourceDiagnostics', {})
    resource = resource if isinstance(resource, dict) else {}
    total_ms = number(resource.get('totalWallClockMs'))
    separation = model.get('separationModel', {})
    separation = separation if isinstance(separation, dict) else {}
    restored_passages = number(separation.get('restoredPassages'))
    passages_restored = restored_passages is not None and restored_passages > 0
    cache_restored = any(row['cacheState'] == 'restored' for row in rows.values()) or passages_restored
    return {
        'source':'Historical metadata saved in the exported project; not newly measured analysis',
        'executionClassification':'restored-or-resumed' if cache_restored else 'cache-state-unknown' if any(row['cacheState'] == 'unknown' for row in rows.values()) else 'no-stage-restores-reported',
        'coldStartVerified':False,
        'reportedPipelineWallSeconds':None if total_ms is None else total_ms / 1000,
        'declaredAnalysisSeconds':number(model.get('analysisSeconds')),
        'stages':rows,
        'separationModelHistoricalSeconds':number(separation.get('analysisSeconds')),
        'separationRestoredPassages':restored_passages,
        'speedupPercent':None,
        'limitations':['A stage reporting seconds=0 after restoration is not zero-cost analysis; observed wall time is separate.',
                       'Separation model history may precede the recorded pipeline attempt; do not add it to the current attempt.',
                       'A complete cold/resumed lineage and controlled baseline/candidate pair are absent. No cold-start speedup is inferred.',
                       'Inclusive stage times and model inference spans overlap; do not sum them.']}


def evaluate_archive(archive_path, *, node='node', max_total_bytes=DEFAULT_MAX_TOTAL):
    source = Path(archive_path).resolve()
    require(type(max_total_bytes) is int and max_total_bytes > 0, 'Total size limit must be positive')
    require(source.is_file() and 0 < source.stat().st_size <= max_total_bytes, 'Archive file size or type is outside supported bounds')
    before = digest_file(source)
    with tempfile.TemporaryDirectory(prefix='lightforge-show-evidence-') as temporary:
        destination = Path(temporary)
        require(not destination.is_relative_to(ROOT), 'Temporary extraction must remain outside the repository')
        inventory = stage_archive(source, destination, max_total_bytes)
        project = load_strict((destination / PROJECT).read_bytes())
        require(isinstance(project, dict), 'Project JSON must be an object')
        validation = load_strict((destination / VALIDATION).read_bytes()) if (destination / VALIDATION).exists() else None
        require(validation is None or isinstance(validation, dict), 'Validation JSON must be an object')
        audio = inspect_audio(destination / AUDIO)
        completed = subprocess.run([node, str(ROOT/'tools/evaluate_show_project.cjs'), str(destination/PROJECT), str(destination/FSEQ)],
                                   capture_output=True, text=True, timeout=180, check=False)
        require(completed.returncode == 0, 'Project replay failed: ' + completed.stderr.strip()[:2000])
        result = load_strict(completed.stdout)
        timings = saved_timings(project)
        project_duration = result['input']['audioDurationSeconds']
        header = result['archive']['header']
        native = validation.get('nativeChecks', {}) if validation else {}
        native = native if isinstance(native, dict) else {}
        reported_hash = native.get('sha256')
        hash_match = reported_hash == result['input']['fseqSHA256'] if reported_hash is not None else None
        duration_match = abs(audio['durationSeconds'] - project_duration) <= 0.5 / audio['sampleRate']
        delta_ms = (header['durationSeconds'] - audio['durationSeconds']) * 1000
        integrity = (result['archive']['payloadMatchesSavedProject'] and result['archive']['metadataMatchesSavedProject']
                     and result['archive']['validation']['valid'] and duration_match
                     and -1e-4 <= delta_ms <= header['stepMs'] + 1e-4 and hash_match is not False)
        require(digest_file(source) == before, 'Input archive changed during evaluation')
        return {'schema':'lightforge.show-archive-evidence.v1','status':'evaluated','archiveSHA256':before,
                'integrityPassed':bool(integrity), 'inventory':inventory, 'audio':audio,
                'alignment':{'projectAudioDurationMatches':duration_match,'sequenceMinusAudioMilliseconds':delta_ms},
                'savedValidationFseqSHA256Matches':hash_match, 'savedAnalysisTiming':timings, 'projectEvaluation':result,
                'evidenceBoundary':{'audioGroundTruthAvailable':False,'physicalVehicleMeasurementsAvailable':False,
                                    'freshModelInferencePerformed':False,'releaseQualificationPerformed':False},
                'privacy':'No network access is used. Audio/project payloads are read locally and temporary extracted copies are removed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--node', default=shutil.which('node') or 'node')
    parser.add_argument('--max-total-bytes', type=int, default=DEFAULT_MAX_TOTAL)
    parser.add_argument('--require-exact', action='store_true', help='Exit 2 when regenerated frames or complete FSEQ differ')
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        require(not output.is_relative_to(ROOT), 'Save user-derived evidence outside the source repository')
        require(not args.output.exists() and not args.output.is_symlink(), 'Output already exists; choose a new evidence filename')
        result = evaluate_archive(args.archive, node=args.node, max_total_bytes=args.max_total_bytes)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write('\n')
        replay = result['projectEvaluation']['replay']
        print(json.dumps({'integrityPassed':result['integrityPassed'], 'framesEqual':replay['framesEqualSavedProject'],
                          'fseqEqual':replay['fseqEqualArchive'], 'output':str(output)}))
        return 0 if result['integrityPassed'] and (not args.require_exact or replay['framesEqualSavedProject'] and replay['fseqEqualArchive']) else 2
    except (ValueError, OSError, zipfile.BadZipFile, wave.Error, subprocess.SubprocessError, RecursionError) as error:
        print('Show archive evaluation failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
