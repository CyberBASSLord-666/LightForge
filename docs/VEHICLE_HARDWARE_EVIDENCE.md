# Vehicle hardware evidence — 2026-09-27

This review checked the owner's supplied VIN against NHTSA's live `DecodeVinValues` API, Tesla's generation-specific identification table, and the official Tesla parts catalog's **Original Fitment** filter. The VIN and production sequence are intentionally excluded from the repository. The application remains configured for a North American 2025 Model 3 Long Range RWD.

## Identity and appearance

| Attribute | Finding | Evidence / limitation |
| --- | --- | --- |
| VIN validity | NHTSA returned error code `0`; check digit valid | [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/api/) was queried on 2026-09-27. A valid VIN does not authenticate installed replacement parts. |
| Manufacturer / model / year | Tesla Model 3, 2025 | NHTSA and [Tesla's VIN table](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-B7B9507C-C984-41F2-89EE-D23CA4E682ED.html). |
| Body / drive / factory | Four-door left-hand-drive sedan, single motor, Fremont, California, USA | NHTSA reports these fields; Tesla's table independently confirms the model, body, motor count, year and factory codes. |
| Low-beam technology | LED | NHTSA `LowerBeamHeadlampLightSource`. It does not identify an individual headlamp part number or firmware behavior. |
| Long Range RWD / North America | Owner trim retained; North American equipment supported by catalog | NHTSA returned no retail trim or series. The VIN-filtered catalog specifies SAE headlamps and North American charge-port assemblies below. |
| Paint / current appearance | Not established by these lookups | [Tesla identifies paint through Car Details or vehicle labels](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-769C9625-76EE-467B-B756-C9032AC2B99A.html). The black rendering is an appearance setting, not a paint-code result. |

[Tesla's RWD / Long Range dimensions](https://www.tesla.com/ownersmanual/model3/en_us/GUID-56562137-FC31-4110-A13C-9A9FC6657BF0.html) specify approximate length 4.720 m, body width 1.850 m, width with mirrors 2.089 m, height 1.440 m, and wheelbase 2.875 m. These are exposed in `VehicleProfile.dimensionsMeters`. The licensed reference mesh is normalized to 4.720 m length; its optical surfaces are modeled geometry, not a scan of the owner's car.

## VIN-filtered original-fitment catalog

The public [Tesla parts catalog](https://parts.tesla.com/en-US/landingpage) accepted the supplied VIN without sign-in and selected **Model 3 Jan 2024**, catalog `8d917dc8-c246-44ab-9a0b-069127b4262c`. Under **Original Fitment**, each entry below displayed Tesla's **Original VIN part** label. No parts were ordered. These are catalog observations, not an inspection of subsequent repairs or replacements.

| Assembly | Catalog part number(s) |
| --- | --- |
| SAE headlamps, left / right | `1694086-00-H` / `1694087-00-H` |
| Side repeaters, left / right | `1820734-00-D` / `1820735-00-D` |
| Decklid lamps, left / right | `1691498-00-F` / `1691500-00-F` |
| Rear fascia lamps, left / right | `1712513-00-E` / `1712514-00-E` |
| License plate lamp, Magna | `1713282-00-A` |
| North American charge port / door | `1490374-10-E` / `1715102-10-C` |
| North American charge-port ECU, generation 4.1 | `1537264-10-E` |
| 18-inch Glider wheel / cover entries | `1344229-00-B` / `1344251-P0-B` |

The wheel list also includes 19-inch Gemini entries `1044225-01-B` and `1044226-01-B`, and the charge-door list includes two actuator alternatives. Therefore this filter must not be presented as an unambiguous current wheel or actuator inventory. The headlamp list displayed one left/right revision pair. Exact-revision headlamp photos were unavailable in that detail view; the exploded diagram and generation-specific service illustrations remain the geometry references.

Reproduction paths after entering the VIN: **17 Electrical → 1740 Exterior Lights → Front Lights / Tail Lights**; **34 Wheels and Tires → Wheels**; **44 High Voltage System → Charge Port**. The public catalog link intentionally omits the VIN. Group identifiers are `3095d128-6a36-4009-aa28-eafa83b7496b` (front), `7ab7c759-9a09-418e-8d67-ef66616ad38e` (rear), and `d8ee18fd-5612-49e2-88c9-837bc4225cc4` (charge port).

## Physical assemblies and mapping

| Assembly | Confirmed physical relationship | Remaining uncertainty / implementation rule |
| --- | --- | --- |
| Front headlamps | The [SAE headlight procedure](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-AC157E1C-9441-4687-AAD9-0CF4A69B166E.html) shows Highland's slim, body-fixed housing. | The public show contract does not label Highland's individual optical sectors. Outer, inner, signature, combined and front-turn surface assignments remain estimates; do not manufacture matrix-pixel addresses. |
| Front fog lamps | Generation-specific [exterior overview](https://www.tesla.com/ownersmanual/model3/en_us/GUID-6C6C3944-9674-4E81-A0E8-94D60B6D87B9.html) and service parts/drawings do not show the legacy separate lower-front fog assembly. | Its absence in this stock profile is an inference from the hardware references. Keep front-fog outputs unavailable; the older generic show-guide statement is not a Highland fixture drawing. |
| Rear C-shaped lamps | [Trunk-lid assemblies](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-D88A21D6-BA20-4743-90B8-87AE67886BD3.html) move with the powered lid. | Stop/tail sub-surface sharing and photometry are estimated. Rear glass and the [package-tray-mounted center brake lamp](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-FBAFB0B2-C222-4822-97BD-13119F30BA66.html) are body-fixed. |
| Lower rear lamps | [Rear-fascia assemblies](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-7E6EE2BC-38C5-4EEB-829E-C1020819F471.html) are separate from the lid. The [exact left revision photo](https://epc.tesla.com/resources/partimages/public/1712/1712513-00-E/1712513-00-E_1.jpeg) shows upper red and lower clear areas. | Keep these surfaces body-fixed. The assembly has secondary lighting circuits below; do not describe every red area as proven passive. Its custom-show sector assignment and trunk-open switching are not documented by the catalog. |
| License plate lamps | [Two plate lamps](https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-3723453A-1326-47E8-A7B5-59574E57DC57.html) are fitted to the lid. | Their motion must follow the trunk and their common show command. |

The official [Tesla light-show contract](https://github.com/teslamotors/light-show/tree/9f949512146d881b6eb66d042b22ee3f9e115afb) remains the authority for FSEQ addresses and command semantics, not the mesh. It combines headlamp channels 4–6 per side and all four auxiliary-park/side-marker requests across both sides. It exposes one brake group, one reverse group, one front-screen RGB group and five cabin accent zones. North American Model 3 has no rear-fog substitution. Charge-port Dance changes the port indicator color; it does not repeatedly swing the door. Mirror Dance is unsupported. These behaviors must match the exported stream and preview.

## Electrical function evidence

Tesla's [electrical-reference selector](https://service.tesla.com/docs/Model3/ElectricalReference/) assigns SOP8 to Fremont production from 2024-01-01 through 2025-10-03, and SOP9 from 2025-10-04. Model year alone does not supply the manufacturing day; the VIN and catalog observations did not establish this vehicle's production date. SOP8 is therefore a dated generation reference, not a VIN-verified wiring specification for this car. The reviewed [SOP8 exterior-light sheet](https://service.tesla.com/docs/Model3/ElectricalReference/prog-233/interactive/pdf/lights_exterior_print.pdf) and [connector reference](https://service.tesla.com/docs/Model3/ElectricalReference/prog-233/interactive/json/connector_reference_export.json) document these circuits for that production range:

| Component | Electrical functions |
| --- | --- |
| Headlamps X260 / X261 | Power, LIN communication and ground; no individual optical-sector wiring shown. |
| Decklid lamps X271 / X273 | Tail/brake supply, turn signal and brightness control, plus ground. |
| Rear fascia X264 / X265 | Reverse, turn, tail, fog and fault connections, plus ground. |
| Center brake X274 | Stop supply and ground. |
| Plate lamps X278 / X279 | Power and ground. |
| Side repeaters X268 / X269 | Turn supply and ground. |

The shared wiring sheet has no regional fitment conditions or FSEQ assignments. In particular, a fog circuit does not establish a North American show output. It also does not specify a trunk-open secondary-light policy. Keep the existing documented show interface; do not invent a fallback animation or new address from the electrical connection alone. The rear-fascia service procedure names a dedicated controller self-test, but supplies no custom-show sub-lens table.

Retrieved electrical-source SHA-256 values: SVG `b259a5dd5187a8a58c5beb1eeb187ecc545b00120c9c8978af32deb8df586018`; PDF `4e7a9d185fd666cb371887e3a53a6e76e9a4eedd59124fa9ea01121d9e1e256e`; connector JSON `5e28dcde19e3872c0ce8a723464ad939424d2ad1a12344de7dea9c922c458081`. Catalog images and service diagrams are reference evidence, not redistributed application assets.

## Accuracy contract

`VehicleProfile.vehicleEvidence` distinguishes decoded identity, catalog original-fitment entries, owner configuration and unmeasured behavior. The catalog materially narrows the assembly revisions beyond the VIN decoder alone. Source-backed command simulation can be tested deterministically. Physical latency, closure travel, exact show-to-lens assignments, optical intensity and the owner's current firmware remain unmeasured or undocumented in the accessed sources. The application retains explicit calibration support and labels these properties as estimates. No invented hardware or shorter motor travel should be introduced to improve apparent synchronization.

Sources were reviewed on 2026-09-27. The pinned Tesla guide commit is `9f949512146d881b6eb66d042b22ee3f9e115afb` (2024-12-29). Its README SHA-256 is `f0370c6c00935f54689f590ead7c9c4e9874ed8e264804cd37680d9a0257970e`; its official xLights template ZIP SHA-256 is `997c2fde3bb04b61adf9ba7a77c5c24331442046ede325261149e69f37a47b80`. Tesla's online manuals are mutable; the links identify the generation-specific pages reviewed. The earlier archived assembly illustrations and source hashes remain in `research/hardware-1.2.0/`.
