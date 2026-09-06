# LightForge 1.2.0 command audit

Reviewed 2026-09-06 against Tesla's public custom-light-show guide, root xLights layout/keybindings, and validator. Saved upstream snapshots are `commands-official-*`. The canonical vehicle profile separately records Highland hardware sources and uncertainty in headlamp sub-lens placement.

## Confirmed command scope

- 20 available exterior output groups, six RGB outputs (front display plus five accent segments), and eight closure components. The catalog contains 56 byte addresses including three unavailable fog channels; 53 addresses can be active in the North American Highland profile.
- The three headlamp aliases per side are physically OR-combined, with channel 4 selecting the ramp duration. Parking/side-marker channels 17–20 are also OR-combined. These aliases are one physical editor output; no independent matrix pixel control is implied.
- Mirror Open/Close means Unfold/Fold. Mirrors do not accept Dance. Four windows, powered trunk and charge port accept Dance; charge Dance animates its rainbow LED rather than oscillating the port door.
- Canonical closure commands: Idle 0, Open 63, Dance 127, Close 191, Stop 255. Open/Close continue through Idle. Stop interrupts travel immediately, and later Open/Close resumes from the reached position.
- Only Open/Close/Dance transitions consume the command budget: mirrors 20 each; each window and trunk 6; charge port 3. The approximate 30-second dance duration is Tesla's thermal guidance, enforced as an explicit app budget, rather than claimed as a field in FSEQ.
- Trunk/charge Dance requires an already open component. Motor durations and dance endpoints remain estimates; the preview and audit do not claim physical vehicle telemetry.
- Exterior ramp commands use the guide's percentage table: off 26/51/77 for 500/1000/2000 ms and on 178/204/230 for those durations. Instant off/on are 0/255. Full RGB values are available only on the RGB outputs here.
- Outer beams remain on/off by default. `outerBeamRamping:true` is an explicit hardware-confirmation option because Tesla documents different support for reflector versus projector lamps without publishing an exact Highland lens diagram. The native FSEQ gate accepts valid outer ramp codes; the app editor/generator/preview enables them only with this option.

## Upstream discrepancy

The current root xLights ZIP assigns E=90% and C=70%, while the README ramp table assigns E=70% and C=90%. LightForge uses the documented command percentages and durations, not copied keyboard shortcut labels. The downloaded keybindings independently confirm closure percentages 25/50/75/100. The upstream Python validator checks format and duration, not physical output mapping or closure actuation limits.

## Editable API

`settings.manualCues` contains `{id, outputId, start, end, value?, rgb?, label?}`. `settings.outputEnabled` maps output IDs to booleans. Color outputs accept integer RGB values 0–255; other outputs accept their canonical command bytes. Timing is in seconds and quantized to the selected 15/20 ms interval.

Light/RGB cues override the generated arrangement within their interval. Manual closure cues replace that component's whole generated track, preserving independent control and making budget accounting predictable. Overlaps are rejected. Disabled output switches mask generated and manual data. An actual all-zero last frame is retained. Playback, preview and FSEQ read the same final frame bytes.

The engine and native export gate now validate command-state evolution rather than rejecting all closely spaced commands. A one-frame Open followed by Idle works, Stop can interrupt a partial movement, and final closure settling remains required. No original audio transport or import code was changed.

## Verification

- 36 Node test cases: previous engine/preview suites plus manual authoring, every available light/RGB output independently decoded from FSEQ, every closure command, masks, linked-output OR behavior, invalid inputs, optional outer ramps, persistence and movement budgets.
- 16 host-JVM checks invoke the production `MainActivity.verifySequence` on valid/corrupted exported FSEQ, including Stop/Idle and interrupted travel.
- Four fixtures pass Tesla's downloaded Python format validator.
- Receipts: `qa/hardware-1.2.0/commands-verification.json`, `engine-verification.txt`, `native-verification.txt`.
- No Android runtime or physical vehicle was connected for these checks.

Primary source: https://github.com/teslamotors/light-show
