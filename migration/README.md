# Initial large-file transfer

`manifest.json` records ordered pieces, lengths and SHA-256 hashes for eight original large source assets and the original signed APK. Pieces are at most 8 MiB. `restore.py` streams and verifies them before atomically installing each output; it never needs a signing key.

```bash
python3 migration/restore.py --only source
python3 verify_snapshot.py
python3 migration/restore.py --only apk
```

The publication workflow restores the complete source assets into their normal repository-root paths, commits only those eight paths, then publishes the existing signed APK. It never overwrites an existing GitHub release or force-pushes history. All source and APK parts stay available for recovery.
