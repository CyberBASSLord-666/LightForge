# Highland preview rendering and timing

The preview consumes `ShowEngine.stateAt()` from the same compiled frames used by FSEQ export. It does not create a separate sequence. Tesla's ramp commands are evaluated continuously between exported frame boundaries; closure travel remains a deterministic estimate, not a calibrated motor model.

## Playback clock

Studio supplies the current HTML audio media time immediately before GPU submission. The renderer samples it after any graphics-context recovery work, then applies that state to the complete rig. This replaces the previous refresh-old sample when a draw was queued by an earlier application animation frame. Pauses, seeks, playback-rate changes and resumed playback all use the media element's time; no independent advancing playback timer or guessed audio-output latency is added. Inspection uses its separate, explicitly identified inspection clock.

Multiple queued updates coalesce before material and geometry work. A requested snapshot can still inspect the latest queued state without forcing a GPU draw. `getPerformance().presentation` reports the frame/time/clock actually submitted, while `getSnapshot()` reports the inspected rig state. These are software submission observations, not measurements of the display, speaker or vehicle's physical latency.

## Optics and geometry

- White main-beam spill responds to the physical outer, inner and combined 4–6 beam requests on its own side.
- Paired white reverse illumination originates at the existing fascia optic surfaces and stays fixed when the trunk opens.
- Separate left and right red tail illumination originates at the lid-mounted tail surfaces, follows the lid, and responds to the corresponding tail channel or shared brake command. Removing the old external red point light avoids its artificial bright reflection in the middle of the bumper.
- Reinhard display mapping preserves the distinction between red brake/tail light and amber turn signals at high emissive values; cinematic ACES desaturation previously made the red optics appear amber.
- Front/rear turn and reverse sub-lens bindings are explicitly marked estimated, matching the headlamp/tail uncertainty already exposed by the rig. Manufacturer channel semantics do not establish every Highland sub-lens allocation. Shared electrical references name additional fascia Tail/Turn/Fog functions; their light-show or lid-open routing is not established, so the preview does not invent that behavior.

The detailed licensed artistic model is retained; the assembled preview rig contains 180,081 triangles. Its normalized bounds measure 4.720 m long, 2.087876 m wide including mirrors and 1.411295 m high; tire-center wheelbase is approximately 2.8732 m. Tesla's RWD/Long Range dimensions are approximately 4.720 m, 2.089 m, 1.440 m and 2.875 m respectively. The roughly 29 mm height difference is disclosed rather than hiding it behind a claim of an exact digital twin. Paint, wheels, optical intensities, beam distributions and mechanical travel are not VIN-calibrated measurements. See [vehicle evidence](VEHICLE_HARDWARE_EVIDENCE.md) and [model attribution](../web/preview/models/CREDITS.md).

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
