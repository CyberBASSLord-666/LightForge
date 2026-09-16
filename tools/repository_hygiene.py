#!/usr/bin/env python3
"""Check tracked clutter and local links in maintained docs, without network I/O.

Historical QA/research documentation is deliberately out of link-check scope.
This is not a secret scanner, asset-integrity verifier or release qualification.
Stage additions/deletions first: Git's index supplies the intended path inventory.
"""
from __future__ import annotations

import html
import posixpath
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

RETIRED = frozenset({
    'SOURCE_MANIFEST.json', 'verify_snapshot.py', 'RESOURCES_MAP.md',
    'INSTALL_OVER_1.5_to_1.6_CHECKLIST.md',
    '.github/workflows/inspect-android-2.2.1.yml',
    '.github/workflows/recover-workspace-2.2.1.yml',
    '.github/workflows/maintenance-audit.yml',
})
CACHE_DIRS = frozenset({'node_modules', '__pycache__', '.pytest_cache', '.venv',
                        'venv', '.gradle', '.idea', 'toolchain'})
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
INLINE_CODE = re.compile(r'(`+)(?!`)(.*?)(?<!`)\1(?!`)', re.DOTALL)
INLINE_LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s]+?)\s*(?:["\'][^\n]*?["\']\s*)?\)')
REFERENCE = re.compile(r'^ {0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)', re.MULTILINE)
REFERENCE_USE = re.compile(r'!?\[([^\]\n]+)\]\[([^\]\n]*)\]')
EXPLICIT_ANCHOR = re.compile(r'<a\s+[^>]*?(?:id|name)=["\']([^"\']+)["\']', re.I)


def prose(text: str) -> str:
    """Exclude fenced code and comments, retaining line counts for diagnostics."""
    text = re.sub(r'<!--.*?-->', lambda m: '\n' * m[0].count('\n'), text,
                  flags=re.DOTALL)
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = FENCE.match(line)
        if fence is None and match:
            fence = match[1]
            lines.append('\n')
        elif fence is not None:
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) +
                            '{' + str(len(fence)) + r',}\s*', line):
                fence = None
            lines.append('\n')
        else:
            lines.append(line)
    return ''.join(lines)


def label(value: str) -> str:
    return ' '.join(value.casefold().split())


def links(text: str) -> tuple[list[str], list[str]]:
    """Extract inline and explicit reference links in the maintained-doc dialect."""
    text = INLINE_CODE.sub('', prose(text))
    references = {label(m[1]): m[2].strip('<>') for m in REFERENCE.finditer(text)}
    targets = list(references.values())
    targets.extend(m[1].strip('<>') for m in INLINE_LINK.finditer(text))
    missing = []
    for match in REFERENCE_USE.finditer(text):
        key = label(match[2] or match[1])
        if key not in references:
            missing.append(key)
    return targets, missing


def anchors(text: str) -> set[str]:
    """GitHub-style ATX heading slugs, duplicates and explicit HTML anchors."""
    text = prose(text)
    result = set(EXPLICIT_ANCHOR.findall(text))
    for line in text.splitlines():
        match = re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        if not match:
            continue
        heading = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', match[1])
        heading = re.sub(r'<[^>]*>', '', html.unescape(heading)).lower()
        slug = ''.join(c for c in heading if c.isalnum() or c in ' _-').replace(' ', '-')
        candidate, number = slug, 0
        while candidate in result:
            number += 1
            candidate = f'{slug}-{number}'
        result.add(candidate)
    return result


def maintained_doc(name: str) -> bool:
    path = PurePosixPath(name)
    return path.suffix.lower() == '.md' and (
        len(path.parts) == 1 or
        (len(path.parts) == 2 and path.parts[0] == 'docs') or
        name == 'releases/v1.6.0/README.md'
    )


def clutter_reason(name: str) -> str | None:
    path = PurePosixPath(name)
    if name in RETIRED or name.startswith(('migration/', 'archive/v1.6.0/')):
        return 'retired migration/checklist material; retain through Git history'
    if len(path.parts) >= 3 and path.parts[0] == 'releases' and path.parts[2] == 'parts':
        return 'retired split release artifact; use Releases'
    if path.parts[0] in {'build', 'dist', 'output', 'signing'} or CACHE_DIRS.intersection(path.parts[:-1]):
        return 'generated output, dependency/cache directory or private signing directory'
    if path.suffix.lower() in {'.jks', '.keystore', '.p12', '.pfx', '.apk', '.dex', '.class', '.pyc', '.pyo'}:
        return 'signing material or compiled output'
    if path.name in {'keystore-password.txt', '.DS_Store', '.env'} or (
        path.name.startswith('.env.') and path.name not in {'.env.example', '.env.sample'}
    ):
        return 'private/local configuration'
    if path.name.startswith('LightForge-diagnostics-') and path.suffix == '.txt':
        return 'personal diagnostic export'
    if 'Private-Source' in path.name and path.suffix == '.zip':
        return 'private source backup'
    return None


def check(root: Path, tracked: set[str]) -> list[str]:
    """Use the full index inventory so sparse checkouts need no binary assets."""
    errors = []
    directories = {str(parent) for name in tracked for parent in PurePosixPath(name).parents}
    documents: dict[str, str] = {}
    for name in sorted(tracked):
        reason = clutter_reason(name)
        if reason:
            errors.append(f'{name}: {reason}')
        if maintained_doc(name):
            try:
                documents[name] = (root / name).read_text(encoding='utf-8')
            except (OSError, UnicodeError) as exc:
                errors.append(f'{name}: cannot read maintained documentation ({type(exc).__name__})')
    for name, text in documents.items():
        targets, missing = links(text)
        errors.extend(f'{name}: undefined reference [{key}]' for key in missing)
        for target in targets:
            try:
                parsed = urlsplit(html.unescape(target))
            except ValueError:
                errors.append(f'{name}: malformed link {target!r}')
                continue
            if parsed.scheme or parsed.netloc:
                continue  # External availability is intentionally not a network gate.
            raw_path = unquote(parsed.path)
            if raw_path.startswith('/'):
                resolved = posixpath.normpath(raw_path.lstrip('/'))
            elif raw_path:
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), raw_path))
            else:
                resolved = name
            if resolved == '..' or resolved.startswith('../') or '\\' in resolved:
                errors.append(f'{name}: link escapes repository: {target}')
            elif resolved not in tracked and resolved not in directories:
                errors.append(f'{name}: missing tracked link target: {target}')
            elif parsed.fragment and resolved in documents and unquote(parsed.fragment) not in anchors(documents[resolved]):
                errors.append(f'{name}: missing heading/anchor: {target}')
    return sorted(set(errors))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(['git', 'ls-files', '-z', '--cached'], cwd=root,
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tracked = {p.decode('utf-8') for p in result.stdout.split(b'\0') if p}
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        print('Repository hygiene requires a Git checkout with a UTF-8 path inventory.', file=sys.stderr)
        return 2
    if not tracked:
        print('No tracked paths: stage the intended source tree before checking.', file=sys.stderr)
        return 2
    errors = check(root, tracked)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        print(f'Repository hygiene failed: {len(errors)} problem(s).', file=sys.stderr)
        return 1
    print(f'Repository hygiene passed: {len(tracked)} tracked paths; '
          f'{sum(maintained_doc(p) for p in tracked)} maintained documents. '
          'External links, historical QA links and release qualification are outside this check.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
