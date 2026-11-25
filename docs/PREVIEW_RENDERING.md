# Highland preview rendering and timing

The preview consumes `ShowEngine.stateAt()` from the same compiled frames used by FSEQ export. It does not create a separate sequence. Tesla's ramp commands are evaluated continuously between exported frame boundaries; closure travel remains a deterministic estimate, not a calibrated motor model.

## Playback clock

Studio supplies the current HTML audio media time immediately before GPU submission. The renderer samples it after any graphics-context recovery work, then applies that state to the complete rig. This replaces the previous refresh-old sample when a draw was queued by an earlier application animation frame. Pauses, seeks, playback-rate changes and resumed playback all use the media element's time; no independent advancing playback timer or guessed audio-output latency is added. Inspection uses its separate, explicitly identified inspection clock.

Multiple queued updates coalesce before material and geometry work. A requested snapshot can still inspect the latest queued state without forcing a GPU draw. `getPerformance().presentation` reports the frame/time/clock actually submitted, while `getSnapshot()` reports the inspected rig state. These are software submission observations, not measurements of the display, speaker or vehicle's physical latency.

## Optics and geometry

- White main-beam spill responds to the physical outer, inner and combined 4–6 beam requests on its own side.
- The fixed lower rear lamps have separate red tail, amber turn and white reverse sectors. With the virtual lid raised, either tail command lights both lower red sectors. Each turn remains side-specific. White reverse works with the lid open or closed. The red reflector above the strip remains passive.
- With the lid closed, the left and right tail and turn commands light their respective lid-mounted optics. The brake command reaches the stop surfaces on the lid and the fixed center stop light. The handoff point and sector boundaries are visual estimates. The North American profile continues to use the documented Tesla show channels. [Electrical and operating evidence](VEHICLE_HARDWARE_EVIDENCE.md)
- The raised decklid exposes the vehicle asset's cargo floor, wheelhouse liners, sill and rear seatbacks. These parts stay on the body along with the rear glass and fascia. The inside trim, upper lamps and plate move with the lid. Hinge travel is approximate. [Tesla rear trunk guide](https://www.tesla.com/ownersmanual/model3/en_us/GUID-3667D28B-5B3B-49CE-A1C1-3D70AC60D9F6.html) · [Tesla decklid trim](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-A7E2650C-3E69-47A6-B549-CDF39250FB5D.html)
- The charge-port cover rises clear of the fixed inlet. The unplugged indicator glows white when exposed and changes color during a charge-port Dance command. The front display is visually brighter than the five cabin accent zones for the same RGB input. Brightness and cover travel are estimates. [Tesla charging instructions](https://www.tesla.com/ownersmanual/model3/en_us/GUID-BEE08D47-0CE0-4BDD-83F2-9854FB3D578F.html) · [Tesla show channels](https://github.com/teslamotors/light-show#interior-rgb-lights)
- Reinhard tone mapping preserves the distinction between saturated red and amber at high brightness. The browser checks sample the illuminated sectors of the rendered lower lens and check cargo and liner visibility from the rear and both rear three-quarter views at three lid positions.

The rig retains the licensed Highland model. Its normalized bounds measure 4.720 m long, 2.087876 m wide including mirrors and 1.411295 m high; tire-center wheelbase is approximately 2.8732 m. Tesla's RWD/Long Range dimensions are approximately 4.720 m, 2.089 m, 1.440 m and 2.875 m respectively. The roughly 29 mm height difference is disclosed rather than hiding it behind a claim of an exact digital twin. Paint, wheels, optical intensities, beam distributions and mechanical travel are not VIN-calibrated measurements. See [vehicle evidence](VEHICLE_HARDWARE_EVIDENCE.md) and [model attribution](../web/preview/models/CREDITS.md).

[Rear view with the same compiled commands in the published and updated renderers](../qa/rig-audit/highland-rear-comparison.webp)

## Verification

Run the renderer state, lifecycle and exported-frame tests:

```sh
node --test tests/preview-engine.test.cjs tests/preview-lifecycle.test.cjs tests/preview-startup.test.cjs
```

Rebuild the offline bundle with the pinned graphics lock, then run the actual WebGL2 check:

```sh
node tools/build_preview.mjs
node tools/verify_preview_browser.cjs
```

The browser runner uses the repository's Playwright installation; `PLAYWRIGHT_EXECUTABLE_PATH` can select an installed compatible Chromium. It writes screenshots and `preview-verification.json` under the current release QA folder, or under `LIGHTFORGE_PREVIEW_OUTPUT` when supplied. It checks exact submission-time clock replacement, unchanged physical output across quality settings, seeking, offscreen suspension, context recovery, trunk/fascia attachment and red stop-light hue in the actual output framebuffer. Software rasterization verifies rendering behavior; it is not an Android GPU benchmark or vehicle calibration.
