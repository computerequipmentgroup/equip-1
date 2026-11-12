# Equip-1 enclosure CAD — V0.1.6 (no blower, front-left low seam)

V0.1.6 is [V0.1.5](../V0.1.5/README.md) **without the blower**, plus a reworked USB-C opening and seam. It is built
from the saved V0.1.5 file (SHA256-pinned); everything not listed here is V0.1.5 unchanged (the verify predecessor
check proves it part by part). For the rest of the design see the V0.1.5 and V0.1.4 READMEs.

**CAD packaging only.** This is not physical fit, strength, electrical, thermal or manufacturing qualification.

## What changed from V0.1.5

**No blower** (user decision 2026-11-11: "blower we dont do"; the final Firehat Rev 5 has no fan connector or load switch).

- Removed: the Sunon UB3H3-500 blower, its cradle on `Spacer1`, the exhaust window (both shells, left wall), the inlet
  slots (top shell, right wall) and the **Active cooling** parameter group. `Spacer1` is identical to V0.1.4 again.
- Kept from V0.1.5: the FPC2 update for the JUSHUO AFC07-S30FCA-00 (entry y −25.331, cable z 15.4, insertion 2.8 mm).
- The case is sealed again, cooled by the aluminium heat spreader and thermal pad as in V0.1.4: the V0.1.5 thermal
  estimate puts the SoC at about 80 °C (4.25 W estimate, 25 °C room). Measure under load on the real board.

**USB-C opening and front-left low seam** (user requests 2026-11-12).

- The USB-C opening follows the plug outline: corners R 1.43 (`UsbConnR + UsbClearance`, was R 0.6), an even 0.15 mm gap.
- From the USB-C round the front-left corner the seam runs at the port's centre line (`UsbSplitZ` z 6.38, was 7.5), so
  each shell holds half the port and the split meets its straight sides square. On the left wall it climbs along the
  FireWire tab's front flank, now one straight line from the FireWire split to z 6.38 at `LowSeamY` y −28.5
  (`FwTabFlareFront` 22.28 by expression, was 27.95). At the USB-C right side it flares back up to z 7.5 (`UsbTabMargin`
  0.6, `UsbTabFlare` 0.5, about 66°).
- Fit: all outer split faces mate exactly, like the main seam: the low-seam floor, both flanks, and the FireWire tab top
  and flanks (`UsbTabGap` and `FwTabGap` 0; `FwTabGap` was 0.2). A gap there only made steps and wedges where a gapped face
  met a contact face, and a 1 mm wide see-through slit on the shallow (11°) FireWire flank. The fit clearance stays hidden:
  the lip / groove keep 0.2 mm all round, also on the FireWire tab's climbing flanks and past the lip ends at its flat top
  (the groove flanks now carry that clearance themselves, `LipInset − GrooveInset`). No lip on the low seam: lip gaps from the
  USB-C round the corner to y −22.6 (`LipGapFront1X0`, `LipGapLeftY1`); the groove is filled up to the FireWire flank.
- Mount inset 1 moved +0.4 mm (`LedWin1X0` −3.62) to keep 0.6 mm wall to the notch; the shoe-mount finger follows.

**LED light chamber** (user request 2026-11-12): the three Ø2.2 mm tunnels (one per Firehat LED, walls between) are
now one shared chamber: a 2.2 mm wide stadium over LED1–LED3 with a vaulted roof (half cylinder, ball ends, R 1.1)
that peaks under the 0.65 mm skin, so the LEDs light one rounded bar. The light block's 0.8 mm outer walls stay and keep
the light out of the case. No parameter changes (`LedLightD` is the chamber width, `LedLightSkin` the skin at the peak).

## Checks

`FreeCADCmd scripts/build.py && FreeCADCmd scripts/export.py && FreeCADCmd scripts/verify.py`, against the final
Firehat Rev 5 board model (`hw/cad/boards/build_boards.py`): **321/321 pass**, 17/17 negative controls fail as expected
(`reports/validation.md`). New: `UsbTabGap`
edit/restore; the lip ↔ groove clearance check now measures the lip only (from 0.3 mm above the seam, without the
FireWire tab's outer skin and flat top, which mate with the lid on purpose); the three LED tunnel cut checks are one chamber check; the blower checks and the `CradleT` / `ExhaustZ1` edit-restore checks are gone with the parts. A separate
shell-to-shell probe (2026-11-12) found no overlap and contact along the whole outer split.
