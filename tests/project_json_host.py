"""Pinned, actual AOSP JSON reader for host storage tests, never APK inputs."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tests/project-json-host'


def sources():
    provenance = json.loads((SUPPORT / 'provenance.json').read_text())
    for relative, record in provenance['files'].items():
        source = SUPPORT / relative
        if hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError('Pinned AOSP source digest mismatch: ' + relative)
    return sorted(SUPPORT.rglob('*.java'))


def compile_support(javac, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(javac), '--release', '8', '-encoding', 'UTF-8', '-d', str(destination),
                    *map(str, sources())], check=True)
    return destination
