# Preserved Android preview-readiness failure

Production verification run [34417512894](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34417512894) used source `222fe9956f91579b34d80b1cad2f993b52b5fbb4`. Its verification/build job passed. Android job `102690333300` failed during `reconnect-completed-project`; this was the follow-up to the [earlier teardown ANR](../android-first-run/README.md).

The production service completed native Studio separation, neural analysis and choreography with the Activity destroyed, the display off and Doze forced under a user-equivalent battery exemption. The project was durably saved; the recorded job elapsed time was **304.809 seconds**. Reopening then exceeded the harness's 45-second bootstrap/first-frame readiness wait. The completed-project reconnection assertion did not pass. Balanced execution, cancellation/Resume, timeout cleanup and the later diagnostics checks were not reached. The receipt's broad `scope` describes the intended suite; only its one completed `checks` entry is a passing result from this run.

The captured `dumpsys activity lastanr` states that no ANR had occurred since boot. This distinguishes the observed outcome from the first run's HWUI/focus-dispatch ANR; it does not identify the timeout's cause or establish that a readiness predicate, rendering, bootstrap or restored-project behavior was responsible. Those possibilities require independent diagnosis and another complete run.

The four original files below are copied byte-for-byte from the downloaded artifact. The artifact ZIP was checksum-verified before extraction: SHA-256 `e0dbbd0bc857cb228d98d4ece0ee35c5955658bddf6ff4221fdd83be2c6cd803`. The failed receipt, progress, log and no-ANR report remain failures/history, never current passing release gates.

| Original file | SHA-256 |
| --- | --- |
| `android-background-verification.json` | `4666746c28b2a65e7697e88cae906fa8b9cc994f74920fd8ed7c3664f52c1abe` |
| `android-background.log` | `480eac50fc05ce102ef15afdc5c4afe8440d0568441647686004d3e94ae3e474` |
| `android-background-progress.json` | `200c1241b20b92505aec2ce275be476a7ae83d3a0e546659ce26e75b2e872ae5` |
| `android-last-anr.txt` | `42cf4931006fd0ff42d3522af31f9346431b409aa22a793ecc16b5aedeed28a1` |
