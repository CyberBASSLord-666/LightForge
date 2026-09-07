# 2.2.1 visual inspection

Inspected current Chromium captures from production verification run 34162369481:

- `background-progress-320.png`: elapsed time, passage/reuse counts and background/cancel controls are visible with distinct touch targets.
- `background-waiting-393.png`: delayed-progress message fits the panel and does not obscure controls.
- `background-recovery-320.png`: recovery notice and Resume/Dismiss controls fit the phone viewport.
- `precision-1440.png`: vehicle preview, editor, playback, score and export panels render without visible overlap.

The automated browser gate additionally covers 320, 393, 768 and 1440 pixels, editing, persistence and export. These are desktop Chromium screenshots with a simulated Android bridge; they do not establish physical-phone rendering, memory or thermal behavior.
