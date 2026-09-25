# Bounded filesystem rename investigation

The September 25 probe did **not reproduce reappearing partial files**. Three
single-write moves and two two-part moves completed in each of a fresh workspace
directory and a fresh `/tmp` directory. Every final payload retained its expected
SHA-256, and the final inspection found no partial files.

`/tmp` persisted across separate execution calls and was visible to a concurrent
inspection call. Both locations reported the same filesystem device identifier.
These observations provide no evidence that moving the model experiment to
`/tmp` would isolate it from the suspected behavior.

The second probe used two 2,293,200-byte writes, matching the native stem payload
sizes. It held the file open for ten seconds after the first write, then appended
the second write, flushed, called `fsync`, closed, and used `os.replace`. A
separate execution call observed the first-half partial in both locations while
the writer was active. Writer receipts retain the immediate and ten-second
post-move inventories, hashes and timestamps. No model ran; project sources and
failed model evidence were left untouched.

The cause of the failed Deux evidence remains unresolved. This Python probe did
not reproduce Java `Files.move`, native inference, or every condition of the
long-running execution. It establishes no execution workaround and authorizes
no relaxation of artifact-integrity gates.

To repeat the single-write case, create two new empty directories, then invoke:

```sh
python3 single_write_probe.py NEW_WORKSPACE_DIRECTORY NEW_TMP_DIRECTORY
```

For the two-part case, pass two new directory paths whose parents exist; the
script creates those directories itself:

```sh
python3 two_part_probe.py NEW_WORKSPACE_DIRECTORY NEW_TMP_DIRECTORY
```

During either run, use a separate execution call to inspect only the two test
directories. Each script writes public synthetic bytes and a final
`runner-receipt.json`; existing output names are never overwritten. The retained
JSON observations and `report.json` describe the executed probes.
