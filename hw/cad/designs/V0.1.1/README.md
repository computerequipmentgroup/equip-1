# Equip-1 enclosure CAD — V0.1.1 (slim case for Firehat Rev 4)

V0.1.1 fits **Firehat Rev 4** and its glued **Liyuan LYA130WG30C-128064** OLED panel over a
**ROCK 2F**. It is built from the saved V0.1.0 file: every parameter value is read from it
(SHA256-pinned), then the explicit change list in `scripts/build.py` is applied.

**CAD packaging only.** This is not physical fit, strength, electrical, thermal or
manufacturing qualification. The fit checks use Radxa's ROCK 2F v1.0 model and a Firehat
Rev 4 KiCad export (`hw/cad/boards/`), not measured boards.

## What changed from V0.1.0 (user decisions: wiki `sources/2026-10-29-cad-v0.1.1-brief`)

| Area | V0.1.0 | V0.1.1 |
|---|---|---|
| Height | 24.0 mm (25.5 over the caps) | **21.7 mm**; the switch actuators stand about 1.5 mm proud |
| Top edge | R8 roll | **R4.5** roll, uniform 2 mm wall. R8 would cut into the wall next to the Firehat edge, which sits 0.3 mm from it |
| Top skin | 2.0 mm | 1.7 mm. The ceiling sits 0.3 mm above the panel face and 0.24 mm above the FireWire connector; the cover pocket is 1.05 mm deep, leaving a 0.65 mm ledge |
| Buttons | 3 caps with flanges | **No caps.** The KSC4 actuators go through Ø3.2 mm holes, with switch-body pockets that leave a 0.8 mm skin |
| Display | Old module aperture with tabs | Panel opening (glass + 0.3 mm). The same bought 1 mm cover, centred on the panel's active area. Cover-to-panel gap is 1.0 mm, down from about 3.3 mm |
| Bottom screws | 57.85 × 48.92 mm (from the old stand-in) | **58 × 49 mm**, coaxial with the top towers (real ROCK 2F) |
| Port openings | Sized from the stand-in | Fitted to the Radxa model with ≥ 0.22 mm clearance: USB-C 9.44 × 3.66, HDMI funnel lowered, audio r 3.5 plus a 0.3 mm wall relief, USB-A openings 0.4 mm lower |
| Seam slivers | 0.19 mm at USB-C / HDMI, 0.55 mm at the LED windows | **Removed.** Opening corners no longer straddle the seam line |
| New reliefs | — | Over the Firehat PCIe FPC connector (opens into the window pocket, under the cover), over the FireWire connector top, and for the USB-A shell legs in the floor (1.05 mm floor left) |
| Reference body | — | `OledPanel` from the Liyuan datasheet (34.5 × 23.0 × 1.4 mm on a 0.3 mm FPC fold) |

The outside layout, seam/lip, towers, FireWire opening, floor vents, back recess and microSD
notch carry over from V0.1.0.

## Derived values to confirm on a real board

- **Panel position** (`PanelX` 11.0, `PanelY` −9.85): the panel is not drawn in the Firehat KiCad project. Its position was derived from the FPC route: the 40 mm FPC is folded under the glass and runs through the board slot to FPC2. X is set 0.2 mm clear of the PCIe FPC connector. The window follows `PanelX`/`PanelY` by expression.
- **`PanelFold` 0.3 mm:** the FPC plus adhesive under the glass, unmeasured.
- **Firehat height** (board top at z 18.0, the tower bottoms) and **ROCK 2F height** (on the 3.6 mm bosses) are carried over from V0.1.0. The 40-pin header engages 4.4 mm.

## Files and tree

Same layout and rules as V0.1.0 (see `../V0.1.0/README.md`). `02 · Assembly` holds `ShellTop`,
`ShellBottom`, `ScreenCover` and the `OledPanel` reference body. `03 · Preview inputs` has
`TopLift`, which lifts the top shell and cover for exploded views; keep it at 0 when saving.
`04 · Outputs` adds panel gaps, actuator protrusion and the skin over the switches and inserts.

```sh
cd hw/cad/designs/V0.1.1
FreeCADCmd ../../boards/build_boards.py   # board models for the fit checks (local, not committed)
FreeCADCmd scripts/build.py               # one-time migration from V0.1.0 (guarded)
FreeCADCmd scripts/export.py
FreeCADCmd scripts/verify.py              # ~7 min incl. fit checks
FreeCADCmd scripts/render.py              # + local fit renders in .build/fit-renders/
python3 -m unittest discover -s tests
```

## Known limits

- **Accepted contacts:** a ROCK 2F edge part overhangs its board by 0.3 mm and touches the left inner wall (≈ 0.004 mm average overlap). The audio jack body sits on its new 0.3 mm wall relief.
- **Firehat LEDs:** the top shell has no light openings for the three Firehat LEDs, same as V0.1.0.
- **PCIe ribbon route** between the ROCK 2F and the Firehat is not modelled.
- **Not modelled:** button feel, actuator sealing, and the panel's adhesive.
