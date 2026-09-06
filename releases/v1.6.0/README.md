# LightForge 1.6.0

Download [LightForge-1.6.0.apk from the private release](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v1.6.0). Install it over the existing app; do not uninstall first. Older projects can use **Analyze voice detail** to receive the new music analysis.

The APK is 185,631,779 bytes. Its SHA-256 is:

```text
9767c40847534f7438a42a5c6821bfffd0434ddbdc231c86538f80f7f7cdba57
```

If the release is not available yet, reconstruct the same signed APK from a full repository checkout:

```bash
python3 migration/restore.py --only apk
```

The result is `releases/v1.6.0/LightForge-1.6.0.apk`. Reconstruction verifies every piece, the final checksum and the APK archive. It requires Python 3.11 or newer and no Android toolchain. The pieces accommodate transfer limits; they are not separately installable.

See [release notes](RELEASE_NOTES.md). No physical phone or Tesla test is claimed by the automated verification.
