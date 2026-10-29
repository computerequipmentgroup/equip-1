# Equip-1 enclosure CAD — V0.1.0 (reference rebuild)

Parametric FreeCAD rebuild of the existing Equip-1 enclosure (`hw/shell-top.step`, `shell-bot.step`,
`screencover.step`, `buttons.step`, product commit `0dcb520`). It keeps the reference envelope
(72.1 × 60.6 × 24.0 mm, buttons to 25.5 mm), layout and features. No design changes: those
start at V0.1.1. Target process: resin print. Power: external USB-C (no battery bay).

**CAD packaging only.** This is not physical fit, strength, electrical, thermal or
manufacturing qualification. The reference STEP files stay in `hw/` as inputs and are not modified.

## Files

| Path | What |
|---|---|
| `equip-1-V0.1.0.FCStd` | Native source, the only dimensional authority |
| `config/assembly.json` | Part names, groups, reference paths. No dimensions |
| `scripts/build.py` | One-time migration from the reference STEPs (guarded, see below) |
| `scripts/verify.py` | Reopens the saved file and runs every check, with negative controls |
| `scripts/export.py` | STEP + BREP per part, 1:1 feel-print 3MF |
| `scripts/render.py` | Blender renders from meshes captured from the saved file |
| `reports/validation.md` | Pass/fail summary bound to the `.FCStd` SHA256 |
| `exports/`, `renders/`, `print-mockup/` | Generated outputs (committed) |
| `.build/` | Gitignored meshes, backups, detailed verify JSON. Always regenerable |

## Document tree

- `01 · Parameters` (`App::VarSet`): every dimension, grouped Body, Seam, Fasteners, Display, Controls, Ports, Clearances. Coordinates use the reference frame, whose origin is off-centre. Tooltips state the current value; verify fails if one goes stale.
- `02 · Assembly`: `ShellTop`, `ShellBottom`, `ScreenCover`, `Button1`–`Button3`.
- `03 · Preview inputs`: `ButtonPress` pose slider. Keep it at 0 mm when saving; verify and export refuse otherwise.
- `04 · Outputs`: read-only derived values (envelope, cavity, seam clearances, cover gap, button protrusion).
- `90 · Construction`: shared outer body, cavity and hollow shell. All other construction features are nested under the part that uses them.

Every feature is a Part primitive or Boolean driven by expressions on `Parameters`. To change
geometry, edit a parameter, recompute, update that parameter's tooltip value, save, then rerun
`verify.py`. A meaningful change goes into a new `V0.1.1/` built from this saved file. Do not edit
this version once it is published.

## Rebuild / check

```sh
cd hw/cad/designs/V0.1.0
FreeCADCmd scripts/build.py     # refuses if the .FCStd exists or the reference STEP hashes changed
FreeCADCmd scripts/export.py
FreeCADCmd scripts/verify.py    # ~10 min; writes reports/validation.md
FreeCADCmd scripts/render.py    # needs Blender 5 at /Applications/Blender.app (or $BLENDER)
python3 -m unittest discover -s tests
```

`build.py` is **not a reset command**. It runs once. `EQUIP1_CAD_REPLACE=1` rebuilds anyway and
first moves the existing file to `.build/backup/`. In the GUI, run any script from the Python
console with the `exec(compile(...))` snippet in `hw/cad/README.md`.

## Fidelity against the reference

Measured by verify.py as two-way surface deviation, since OCC booleans between two independently
modelled near-identical solids proved unreliable:

| Part | Max surface deviation | Volume Δ | Where |
|---|---|---|---|
| ShellTop | 0.42 mm | +0.21% | R1 inside fillets of the display aperture tabs (not modelled); top-corner blend |
| ShellBottom | 0.27 mm | −0.03% | counterbore mouth fillets meeting the bottom corner roll |
| ScreenCover | 0.001 mm | 0.00% | — |
| Buttons | ≤ 0.02 mm | < 0.07% | — |

Known modelling simplifications:

- **Top corners:** the R8 top roll meets the R5.3 vertical corner as a revolved "dome" (G1, plan radius 5.3 where the roll starts). The reference uses an Autodesk spline blend; the two differ by less than 0.3 mm.
- **Small concave fillets omitted:** the R1 inside corners of the display aperture tabs and the R0.6 fillets in the HDMI-shaped port funnel.
- **FireWire opening:** modelled as rounded rectangles plus a wedge. It leaves slivers of at most 0.31 mm against the reference outline.

## Findings carried over from the reference (not fixed in V0.1.0)

- **Thin slivers at the seam (verify FAIL, identical in the reference):** 0.19 mm where the USB-C and centre (HDMI-shaped) port openings meet the seam, and 0.55 mm around the two front blind windows. All are below the 0.6 mm resin minimum wall.
- **Screw positions disagree between shells:** bottom screw holes sit 0.15 mm (X) and 0.08 mm (Y) off the top insert towers. Both are kept as separate parameters.
- **Inferred, not confirmed:** the centre port's purpose (its profile matches a full-size HDMI receptacle), the 6.3 mm round port, the two 1 mm-skin front blind windows (LED light windows?), the 1.2 mm-deep back recess, and the left bottom notch (microSD access?).

## Not in V0.1.0

- No bought-part placeholder bodies yet (ROCK 2F, Firehat, OLED module, tact switches, screws). The Firehat KiCad PCB in the Firehat repo is the intended source for V0.1.1.
- Button travel is unknown. The mechanism render uses an illustrative 0.5 mm.
- Restored geometry after edit/restore is geometrically identical, but its BREP text is not byte-identical (OCC output ordering).
