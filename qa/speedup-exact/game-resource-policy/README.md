The current receipt validates the 2.2.5 Android GAME admission policy on the host JVM: at least 7 GiB total memory, 6 GiB freshly available memory, four cores, a 64-bit process, and no Android low-memory flag. It does not measure model memory or device performance.

The real-file job-store suite exercises exact threshold admission, one-byte-below rejection, explicit rejection of the former 4 GiB limit and of 5 GiB, source/version invalidation, duplicate and stale owners, interrupted leases, caught worker fallback, successful release, completed-project retry, and cancellation.

`verification.json` binds the production Java files, test, generated Android resource source, current version, and raw compile/test logs. The receipt passes only after current production compilation and the actual host test complete without source changes.

`prior-4gib/` retains the earlier policy's receipt and logs as historical evidence. Those files do not qualify current admission and are not rebound to the 6 GiB policy.
