# Highland capability and preview audit — 2026-09-06

Target: stock 2025 Tesla Model 3 Long Range Rear Wheel Drive, North America.

## What is verified

The official xLights layout defines channel addresses, not a separate Highland model. `official-channels.json` is extracted from the root `xlights_rgbeffects.xml` in Tesla's downloaded project ZIP. The app profile accounts for every applicable address without presenting the Cybertruck light bars or other vehicle closures as Model 3 hardware. The 37 controls comprise 20 available exterior command groups, 6 RGB zones, 8 closures, and 3 unavailable fog-light controls. Some controls drive several physical lamps together.

The public Tesla guide specifies shared headlamp aliases, the shared park/marker output, one front-display RGB zone and five accent-light zones, and supported closure commands. It exposes no per-pixel Model 3 matrix addresses, rear-display address, or Model 3 powered-door, handle, frunk, suspension, steering or wiper commands. RGB capability must not be extended to other cabin lamps merely because they physically exist.

Sources: [Tesla guide](https://github.com/teslamotors/light-show), [official xLights project](https://github.com/teslamotors/light-show/blob/master/xlights/tesla_xlights_show_folder.zip).

## Physical assembly evidence

The [2024+ service manual](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/) is the correct Highland manual. The similarly named manual without `/2024/` describes 2017–2023 cars. The Highland exterior-light parts list contains headlamp, rear fascia, trunk-lid, license-plate and side-repeater assemblies; it contains no separate lower-front fog lamp. Its SAE headlight and front-fascia drawings likewise show no legacy lower-front lamp. Therefore the old app's optional bumper fog tubes should be removed for this stock profile. This absence conclusion is an inference from the parts list and drawings, not an explicit Tesla sentence saying "no fog lights". A generic inspection page contains inherited fog-light checklist language and must not override the generation-specific parts/drawings.

The [headlight procedure](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-AC157E1C-9441-4687-AAD9-0CF4A69B166E.html) shows the actual slim Highland housing. Its shape alone does not establish whether Tesla's custom-show software supports outer-beam ramping. The default remains on/off, with an explicit optional ramp setting requiring vehicle confirmation.

The [trunk-lid light procedure](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-D88A21D6-BA20-4743-90B8-87AE67886BD3.html) locates the C-shaped main rear assemblies on the powered lid. The [rear-fascia procedure](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-7E6EE2BC-38C5-4EEB-829E-C1020819F471.html) locates separate lower bumper lamp assemblies. These must stay fixed when the trunk moves. The [plate-light procedure](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-3723453A-1326-47E8-A7B5-59574E57DC57.html) identifies two lights mounted to the trunk lid. They share the single plate-light command.

## Accuracy boundary that remains

Tesla does not supply a Highland-specific FSEQ-to-sub-lens diagram in the downloaded material. The upstream [request for updated headlight documentation](https://github.com/teslamotors/light-show/issues/113) remains open. Its [firsthand comment](https://github.com/teslamotors/light-show/issues/113#issuecomment-2536787987) reports changes to legacy beam/signature mapping and parallel bumper turns, but the commenter does not identify whether they mean Model X or Highland. The issue covers both vehicles, so those observations cannot be adopted as confirmed Highland behavior.

Consequently exact inner/outer/combined headlamp sub-lens allocation, signature behavior, brake sub-surfaces, bumper-turn behavior, and park-marker allocation require an individually sequenced in-car comparison. A rendered surface is an estimate until observed on this car. Do not claim physical verification from browser screenshots or from the existence of a model mesh.

`brakes` is the single official "Brake Lights" group. The guide does not document a separate CHMSL-only custom-show address, nor independently addressable left/right brake arrays. Previewing only the center brake lamp as a confirmed mapping would be unsupported. Reverse is likewise one group. Some elements of these physical groups remain uncertain as above.

The rear display exists but has no documented custom-show RGB address: it must remain unbound. The charge LED is controlled by the charge-port Dance command rather than an arbitrary RGB channel. Body reflectors, black trim, lamp bezels and charge-door surfaces must not be emissive just because they share a source-model material with a lamp.

## Archived evidence

Downloaded README, complete official xLights ZIP, extracted XML/address JSON, generation-specific service pages, four service illustrations, and raw issue/comment JSON are adjacent. `SOURCE_SHA256.json` records the fetched evidence at audit time. Service drawings are reference evidence, not licensed app visual assets. The production car model remains the separately licensed asset credited in `web/preview/models/CREDITS.md`.
