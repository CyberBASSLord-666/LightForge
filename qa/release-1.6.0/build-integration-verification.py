"""Audit preserved functional/styled evidence; do not rerun model inference."""
import copy
import hashlib
import io
import json
import struct
import subprocess
import wave
import zipfile
from datetime import datetime, timezone
from pathlib import Path

QA = Path(__file__).resolve().parent
ROOT = QA.parent.parent
EXPECTED = {'nightowl-mix', 'falcon-mix', 'user-glass-prefix64'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    return json.loads((QA / name).read_text())


def check_hashes(mapping):
    assert mapping, 'Source hash map must not be empty'
    for name, expected in mapping.items():
        assert sha((ROOT / name).read_bytes()) == expected, f'Changed source: {name}'


def main():
    raw = read('real-music-export-verification.json')
    styled = read('styled-real-projects-verification.json')
    assert raw['passed'] and not raw['errors'] and not raw['externalRequests']
    assert styled['passed'] and not styled['errors']
    assert raw['styledVerification'] == styled
    assert styled['styles']['loaded']
    assert styled['styles']['body'] == styled['styles']['viewport']
    check_hashes(raw['source_hashes'])
    check_hashes(styled['source_hashes'])
    check_hashes(raw['styledVerification']['source_hashes'])
    assert {t['track'] for t in raw['tracks']} == EXPECTED
    assert len(raw['tracks']) == 3
    assert {t['track'] for t in styled['cases']} == EXPECTED
    styled_cases = {t['track']: t for t in styled['cases']}
    audited = []
    validator = ROOT / 'research/hardware-1.2.0/commands-official-validator.py'
    for track in raw['tracks']:
        name = track['track']
        assert track['engineVersion'] == '1.6.0'
        assert track['analysisVersion'] == 5
        saved = read(f'actual-music-{name}-analysis.json')
        assert saved['analysisVersion'] == 5 and saved['separation']['sourceSeparated']
        assert saved['separation']['modelId'] == 'uvr-mdx-net-voc-ft'
        assert saved['separation'] == track['separationModel']
        expected = track['export']
        assert expected['crcError'] is None and expected['terminalDark']
        replay = styled_cases[name]
        assert replay['valid'] and replay['sourceSeparated'] and replay['exportIdentical']
        assert replay['audioSHA256'] == expected['audioSHA256']
        for prefix in ['actual', 'styled']:
            archive = QA / 'fixtures' / f'{prefix}-music-{name}.zip'
            with zipfile.ZipFile(archive) as z:
                assert z.testzip() is None
                assert z.namelist() == expected['files']
                audio = z.read('LightShow/lightshow.wav')
                fseq = z.read('LightShow/lightshow.fseq')
                project = json.loads(z.read('Review/LightForge_Project.json'))
            assert sha(audio) == expected['audioSHA256']
            assert sha(fseq) == expected['fseqSHA256']
            assert project['music'] == saved, f'Preserved inference changed: {name}'
            with wave.open(io.BytesIO(audio)) as w:
                assert [w.getnchannels(), w.getsampwidth(), w.getframerate(),
                        w.getnframes()] == expected['wav']
                assert [w.getnchannels(), w.getsampwidth(), w.getframerate()] == [2, 2, 44100]
            assert struct.unpack_from('<I', fseq, 14)[0] == expected['frames']
            assert fseq[18] == expected['step'] == 20
            assert not any(fseq[-200:])
        sequence = QA / 'fixtures' / f'actual-music-{name}.fseq'
        assert sha(sequence.read_bytes()) == expected['fseqSHA256']
        result = subprocess.run(['python3', str(validator), str(sequence)],
                                input='\n', text=True, capture_output=True, check=True)
        assert result.stdout == track['officialValidator'], f'Validator output changed: {name}'
        assert 'ERROR' not in result.stdout and 'INVALID' not in result.stdout
        audited.append({'track': name, 'engineVersion': track['engineVersion'],
                        'analysisVersion': track['analysisVersion'],
                        'audioSHA256': expected['audioSHA256'],
                        'fseqSHA256': expected['fseqSHA256'],
                        'officialValidatorUnchanged': True})
    composite = copy.deepcopy(raw)
    composite.update(release='1.6.0', analysisVersion=5, passed=True, errors=[])
    composite['metadataAudit'] = {
        'passed': True,
        'createdAt': datetime.now(timezone.utc).isoformat(),
        'method': 'Metadata-only release aggregation of preserved actual functional and styled runs. '
                  'Current production and nested styled hashes, three saved actual analyses, '
                  'both sets of audio/FSEQ ZIP hashes, WAV/FSEQ structure, and unchanged official '
                  'validator results were rechecked. No model inference was repeated.',
        'tracks': audited,
        'evidence_hashes': {f'qa/release-1.6.0/{name}': sha((QA / name).read_bytes())
                           for name in ['real-music-export-verification.json',
                                        'styled-real-projects-verification.json',
                                        'build-integration-verification.py']},
        'errors': [],
    }
    target = QA / 'integration-verification.json'
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(composite, indent=2) + '\n')
    temp.replace(target)
    print('PASS integration metadata audit: release 1.6.0, analysisVersion 5, 3 unchanged actual exports')


if __name__ == '__main__':
    main()
