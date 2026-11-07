# Equip-1 enclosure CAD — V0.1.3 (screen cover centred across the case)

V0.1.3 is [V0.1.2](../V0.1.2/README.md) (R5.0 corners, Firehat Rev 4) with the screen cover
**exactly centred across the case width**. It is built from the saved V0.1.2 file (SHA256-pinned).

**CAD packaging only.** This is not physical fit, strength, electrical, thermal or
manufacturing qualification. The fit checks use Radxa's ROCK 2F v1.0 model and a Firehat
Rev 4 KiCad export (`hw/cad/boards/`), not measured boards.

## What changed from V0.1.2 (user request 2026-10-30: "screen cover perfect center")

| Parameter | V0.1.2 | V0.1.3 |
|---|---|---|
| `PanelY` | −9.85 (derived from FPC route) | **= `BodyY0 + BodyWidth / 2 + ActiveAreaOffsetY`** (−4.54) |
| Window / cover centre Y | −11.90: 5.31 mm off the centre line | **−6.59: on the centre line** |

- The window still follows the panel's active area, so moving the panel keeps the visible screen
  centred inside the cover. `PanelY` is an expression on the case size, so changing `BodyWidth`
  keeps the cover centred.
- **X stays at 11.00 (1.73 mm off centre along the length), on purpose.** A cover centred in X has its edge at
  x 33.34, which cuts into the switch 1 pocket (x 32.3) and left a 0.15 mm wall; centring the panel
  in X also hit a Firehat part. The switches are fixed on the Firehat and the cover is bought. The
  original `screencover.step` used the same layout: centred in Y, offset along X for the buttons.
- **Confirm on the board:** the panel is glued 5.31 mm (Y) from the V0.1.2 position.
  Check that the 40 mm FPC still folds under the glass and reaches FPC2 through the board slot,
  and glue the panel to match.
- **Unchanged:** everything else. ShellTop changes only at the window, pocket and panel opening;
  ScreenCover and OledPanel are verified as pure moves.

## Files, tree and commands

Same as V0.1.1. See `../V0.1.1/README.md` for the tree and known limits.

```sh
cd hw/cad/designs/V0.1.3
FreeCADCmd scripts/build.py && FreeCADCmd scripts/export.py && FreeCADCmd scripts/verify.py && FreeCADCmd scripts/render.py
python3 -m unittest discover -s tests
```
