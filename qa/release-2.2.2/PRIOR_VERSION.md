# Predecessor release metadata

`prior-version-2.2.1.json` is the exact `version.json` fetched from the immutable
2.2.1 release-candidate commit `f80de0d7fd075cf22506c60910e41ea9f625e922`, which is
also the source commit bound by `releases/v2.2.1/request.json`.

Source: <https://github.com/CyberBASSLord-666/LightForge/blob/f80de0d7fd075cf22506c60910e41ea9f625e922/version.json>.
Git blob SHA: `2ad2dcbe0f9e2758d48aecf7dee7377a071931f0`.
SHA-256: `c2bb2ac7b87451cfb09a2cc087581ef8217cd7395ec87fdea0dc2e248f83f9df`.

The exact SHA-256 is already bound by the original passing 2.2.1 numerical
receipt. The retention helper requires this match before classifying the
name/code transition as release metadata. Every other measured source and
model still requires an exact byte match; old evidence is never rewritten.

```bash
python3 tools/verify_retained_analysis.py --from-release 2.2.1 --prior-version-file qa/release-2.2.2/prior-version-2.2.1.json
```
