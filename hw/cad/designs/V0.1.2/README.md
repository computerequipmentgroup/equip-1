# Equip-1 enclosure CAD — V0.1.2 (all outer corners R5.0)

V0.1.2 is [V0.1.1](../V0.1.1/README.md), the slim case for Firehat Rev 4, with every outer corner
and edge at **R5.0**. It is built from the saved V0.1.1 file (SHA256-pinned): every parameter
value is read from it, then the change list in `scripts/build.py` is applied.

**CAD packaging only.** This is not physical fit, strength, electrical, thermal or
manufacturing qualification. The fit checks use Radxa's ROCK 2F v1.0 model and a Firehat
Rev 4 KiCad export (`hw/cad/boards/`), not measured boards.

## What changed from V0.1.1 (user request 2026-10-29: "make all corners r5.0")

| Parameter | V0.1.1 | V0.1.2 |
|---|---|---|
| `CornerR` (vertical corners) | 5.3 | **5.0** |
| `TopEdgeR` (top edge roll) | 4.5 | **5.0** |
| `BottomEdgeR` (bottom edge roll) | 4.0 | **5.0** |
| `InnerTopR` (new, inner ceiling edge) | 2.5 (was outer − wall) | 2.5, decoupled |
| `InnerBottomR` (new, inner floor edge) | 2.0 (was outer − wall) | 2.0, decoupled |

- **Corners:** with all three outer radii equal, every outer corner is a true spherical blend.
- **Audio jack spot-face (user choice):** the ROCK 2F jack opening's lower edge (z 3.55) lands on the R5 bottom roll, which would leave a ~0.3 mm knife-edge lip. A flat pad, 0.44 mm deep, around the jack meets the roll flush at z 2.95 and leaves 0.6 mm under the lip (1.26 mm wall).
- **LED windows:** raised above the roll (z 5.05–6.85, R0.85). They were also recentred on the real ROCK 2F LEDs at x −2.52 / 22.40; the stand-in had them about 1.8 mm off. Narrowed to 3 mm so they keep ≥ 1 mm wall to the USB-C / HDMI openings.
- **microSD notch:** moved up 0.65 mm to z 2.45–4.50 (same 2.05 mm opening). Its floor still met the R5 bottom roll in a 0.5 mm lip, so it gets the same treatment as the jack (user choice): a flat pad, 1.15 mm deep, around the notch meets the roll flush at z 1.81 and leaves 0.64 mm under the notch floor (0.85 mm wall at the pad).
- **Insert holes:** 2.8 mm deep (was 3.0), so the R5 spherical top corner keeps 0.6 mm over the front-left hole. Check that the heat-set inserts are ≤ 2.8 mm long.
- **Inner radii:** kept, so the board clearances don't change. The wall is a little thicker along the edges.
- **Unchanged:** everything else, including the window pocket (R3.9, matching the bought R3.7 cover) and the port openings. The screen cover and OLED panel are verified identical to V0.1.1.

**Structural note:** the corner construction is picked at build time from the radii. With them all equal, `TopEdgeR` can be increased in the saved file and recomputes cleanly. To make an outer roll *smaller* than `CornerR`, or `CornerR` smaller than `BottomEdgeR`, regenerate with `build.py` in a new version.

## Files, tree and commands

Same as V0.1.1. See `../V0.1.1/README.md` for the tree, the derived values to confirm on a real
board (panel position, FPC fold, board heights) and the known limits.

```sh
cd hw/cad/designs/V0.1.2
FreeCADCmd scripts/build.py && FreeCADCmd scripts/export.py && FreeCADCmd scripts/verify.py && FreeCADCmd scripts/render.py
python3 -m unittest discover -s tests
```
