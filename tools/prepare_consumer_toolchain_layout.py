#!/usr/bin/env python3
"""Prepare the frozen CI consumer's relative-root toolchain lookup, not its identity.

The immutable consumer uses --root . and therefore looks inside the checkout.
Bootstrap installs its pinned bytes in the sibling toolchain directory later.
This explicit npm-test preparation aliases only those two locations. It neither
installs nor validates a runtime; frozen admission must still replay and recompile.
"""
from pathlib import Path
import json
import os
import stat
import subprocess

ROOT = Path(__file__).absolute().parents[1]
LINK_TEXT = '../toolchain'
PATH_OVERRIDES = ('LIGHTFORGE_TOOLCHAIN_DIR', 'LIGHTFORGE_JAVA_HOME')


def prepare(root=ROOT, *, environment=None):
    env = os.environ if environment is None else environment
    result = {'scope': 'frozen-ci-consumer-toolchain-layout', 'runtimeValidated': False}
    if env.get('GITHUB_ACTIONS') != 'true':
        return dict(result, status='not-applicable')
    root = Path(root)
    workspace = Path(env.get('GITHUB_WORKSPACE', ''))
    if not root.is_absolute() or not workspace.is_absolute():
        raise RuntimeError('Consumer layout requires an absolute CI workspace')
    if root.resolve(strict=True) != root or workspace != root or workspace.resolve(strict=True) != root:
        raise RuntimeError('Consumer layout workspace is noncanonical or differs from the checkout')
    if any(env.get(name) for name in PATH_OVERRIDES):
        raise RuntimeError('Consumer layout does not support project toolchain path overrides')

    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True)

    if Path(git('rev-parse', '--show-toplevel').strip()) != root:
        raise RuntimeError('Consumer layout is not at the Git checkout root')
    if git('ls-files', '--stage', '--', 'toolchain') or git('ls-tree', 'HEAD', '--', 'toolchain'):
        raise RuntimeError('Consumer layout would shadow tracked source')
    sibling = root.parent / 'toolchain'
    alias = root / 'toolchain'
    anchors = [(p, p.stat().st_dev, p.stat().st_ino) for p in (root.parent, root)]

    def validate_anchors():
        for path, device, inode in anchors:
            stat = path.stat()
            if path.resolve(strict=True) != path or (stat.st_dev, stat.st_ino) != (device, inode):
                raise RuntimeError('Consumer layout anchor changed')
        if sibling.is_symlink() or (sibling.exists() and not sibling.is_dir()):
            raise RuntimeError('Consumer layout sibling must be a real directory or absent')
        if sibling.resolve() != sibling:
            raise RuntimeError('Consumer layout sibling escapes its canonical location')

    validate_anchors()
    # Descriptor-relative creation cannot follow a checkout parent replaced
    # between validation and creation. O_NOFOLLOW protects the final component;
    # fstat pins the directory identity already recorded above.
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    created = False
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != anchors[-1][1:]:
            raise RuntimeError('Consumer layout checkout changed before creation')
        validate_anchors()
        try:
            os.symlink(LINK_TEXT, 'toolchain', dir_fd=descriptor, target_is_directory=True)
            created = True
        except FileExistsError:
            # A concurrent creator is safe only if it installed this exact alias.
            pass
        validate_anchors()
        entry = os.stat('toolchain', dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISLNK(entry.st_mode) or os.readlink('toolchain', dir_fd=descriptor) != LINK_TEXT:
            raise RuntimeError('Consumer layout refuses to replace an existing toolchain entry')
        if alias.resolve() != sibling:
            raise RuntimeError('Consumer layout alias does not resolve to the exact sibling')
    finally:
        os.close(descriptor)
    return dict(result, status='layout-ready', created=created,
                alias='toolchain', target=LINK_TEXT,
                installation='present-but-unvalidated' if sibling.exists() else 'pending-bootstrap')


def main():
    try:
        print(json.dumps(prepare(), sort_keys=True))
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'scope': 'frozen-ci-consumer-toolchain-layout',
                          'status': 'hold', 'runtimeValidated': False, 'reason': str(error)}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
