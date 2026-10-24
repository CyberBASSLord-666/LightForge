"""Legacy Demucs object-checkpoint comparison is intentionally unsupported.

The original research helper required allowlisting serialized model classes.
Restricted loading must not be weakened to reproduce that workflow. Historical
comparison receipts are retained separately and are not fresh qualification.
"""


def main():
    raise SystemExit(
        'This legacy Demucs identity check requires an arbitrary-class checkpoint '
        'and is disabled for safety. First convert the trusted original checkpoint '
        'to a plain tensor state dictionary in an isolated trusted environment, '
        'record its source and output hashes, then use a reviewed tensor-only '
        'comparison. No original-checkpoint identity proof is produced here.')


if __name__ == '__main__':
    main()
