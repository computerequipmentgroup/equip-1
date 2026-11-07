# Equip-1 enclosure CAD — V0.1.5 (active cooling: blower)

V0.1.5 is [V0.1.4](../V0.1.4/README.md) plus a **small blower** that pulls air through the case. It is built from
the saved V0.1.4 file (SHA256-pinned); everything not listed here is V0.1.4 unchanged (the verify predecessor
check proves it part by part). For the rest of the design see the V0.1.4 README.

**CAD packaging only.** This is not physical fit, strength, electrical, thermal or manufacturing qualification.

## What changed from V0.1.4 (user request 2026-11-02)

- **FPC2 (2026-11-06)**: OLED FPC now enters the JUSHUO AFC07-S30FCA-00 (bottom contact) on Firehat Rev 5 NOV5: entry y −25.331,
  cable height z 15.4, insertion 2.8 mm (customer drawing). The route needs 10.9 mm of the shortest 11.7 mm FPC.
- **Blower**: Sunon **UB3H3-500** MagLev blower, 17 × 17 × 3 mm (intake guard 3.8 mm), 3 V (2.0–3.5 V),
  6.5 l/min free air, 40 Pa, 37 mA, **20.4 dB(A) @ 1 m**, 3 leads (red +, black −, yellow tach), 100 mm
  (Sunon spec D01000941F-01; Sunon recommends JST SUR 0.8 mm connectors).
  Both boards cover the whole case outline, so it lies flat **between the boards** in the front-left free zone
  (x −20.1…−3.1, y −17.6…−0.6, z 9.7…12.7), intake up, outlet edge against the left wall. Measured limits:
  ROCK 2F part at z 8.7 below, Firehat parts at z 14.4 above, Firehat PCIe FPC1 at the front, FireWire J2 behind.
- **Cradle on `Spacer1`**: two C-rails grip the blower edges (it slides in from +X, outlet first; a drop of
  glue or tape holds it), an outlet frame against the wall, and an arm along the left wall to the corner
  spacer. It goes in with the board stack (the Firehat covers the footprint, so no lid bracket can reach).
- **Exhaust window** (both shells, left wall, y −17.0…−1.2, z 9.0…14.3) over the blower outlet. It crosses the
  FireWire split flank, so it runs from below the flank to above the groove (no slivers); the cradle frame
  closes it above and below the outlet so outside air cannot short-circuit into the intake.
- **Inlet slots** (top shell, right wall above the ROCK 2F USB-A ports): 12 × 1.5 mm, z 12.9…15.9.
  Fresh air crosses both boards and the SoC heatsink to the blower.
- New parameter group **Active cooling** (`Blower*`, `Cradle*`, `Exhaust*`, `Inlet*`); `BlowerCX` is an expression.

## Firehat change needed (user routes)

- 2- or 3-pin **JST SUR** (SM02B/SM03B-SURS-TF) near the blower (Firehat underside, front-left).
- **On/off** 3.3 V load switch from a GPIO (Sunon: no PWM on the supply). Tach (yellow, open collector) optional
  to a GPIO with pull-up.

## Thermal estimate (`scripts/thermal.py`, 4.25 W estimated, 25 °C room)

| | SoC | air between boards | case outside max |
|---|---|---|---|
| V0.1.4 (alu plate + pad, sealed) | 80.0 °C | 66.7 °C | 74.3 °C |
| + blower, still air (pessimistic) | 80.0 °C | 66.6 °C | 74.3 °C |
| + blower, mixed air (optimistic) | 67.8 °C | 62.1 °C | 63.3 °C |

Blower operating point 5.4 l/min at 6.6 Pa. The model's air does not flow, so the still-air row cannot show
a gain; the real result lies between the rows (≈ 10–15 °C less at the SoC). Power is still an estimate:
measure under load on the real board.

## Checks

`FreeCADCmd scripts/build.py && FreeCADCmd scripts/export.py && FreeCADCmd scripts/verify.py`:
349/349 pass on 2026-11-02. New: blower in its cradle with an open outlet path out of the window and 0.9 mm
from the intake guard to the Firehat (negative control: blower 1 mm higher); ROCK 2F / Firehat × blower.
