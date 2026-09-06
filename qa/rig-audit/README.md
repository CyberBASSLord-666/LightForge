# Highland preview lamp geometry audit — LightForge 1.2

The production WebGL rig was checked against the normalized licensed Highland model, by isolating individual connected components and probing one FSEQ light channel at a time. `verification.json` records the actual emissive surfaces and the logical inspector values produced by the bundled renderer. `verified-*.png` are renderer screenshots, not concept images.

## Corrections

- Outer beam uses the optical projector face, rather than its chrome surround.
- Inner reflector surfaces are extracted from the actual lamp cavities. Black housings and chrome trim do not glow.
- Signature uses the model's J-shaped diffuser, replacing the floating duplicate tube.
- Combined headlight channels no longer illuminate or change the color of the front turn signal.
- The North American marker adaptation uses a patch of the actual outer headlamp lens, rather than a floating fender light. A first trial patch was occluded from the driver-side view; the visual audit caught this and the final patch is visible inside the headlamp boundary.
- No separate front fog lamps are fabricated. The unused North American rear-fog slot does not light the lower red reflectors.
- Rear tail/stop surfaces exclude the separate charge-port cover and quarter-panel lens.
- Brake logical inspection includes both rear stop assemblies and the fixed center high-mounted stop lamp.
- Both lower reverse lamps share the actual reverse output. The two license-plate fixtures share channel 30 and move with the trunk.
- The charge-port status indicator has a Tesla T silhouette, replacing the old torus.
- The center FRONT display and five ambient trim segments are RGB-controlled. The rear passenger display does not respond to the front display's RGB channel.
- All supported legacy numeric light slots have inspector records, including shared-channel aliases and reverse slot 28. A logical value is separate from the physical aggregate value when multiple logical commands share a displayed surface.

## Mapping limitations requiring car calibration

Tesla's public light-show interface provides the FSEQ channels and shared-control rules, but does not publish an updated Highland headlamp-sector diagram. Upstream issue 113 explicitly requests it:
https://github.com/teslamotors/light-show/issues/113

The real outer optical face, inner reflector assembly, signature diffuser and turn diffuser are distinct model surfaces. Their Highland-specific assignment to the legacy main-beam/4–6 slots is an assembly-level estimate. In particular, inner beam and combined 4–6 slots share the model's inner optical assembly; this does NOT assert that their vehicle outputs are electrically tied. Their logical values remain separate. `estimatedMapping` is set for those records. Exact stop/tail subdivision and the North American marker's illuminated extent are also estimated, not independently measured from this car.

## Reproduce

From the workspace root with the supplied project and toolchain:

```sh
node app/lightforge/tools/build_preview.mjs
node app/lightforge/qa/rig-audit/verify.cjs
```

The verification uses desktop Chromium with SwiftShader. It proves bundled-renderer behavior and geometry bindings; it is not Android-device or vehicle testing. The optical model does not simulate measured beam photometry or individual matrix pixels, which the Model 3 custom-show interface does not expose.
