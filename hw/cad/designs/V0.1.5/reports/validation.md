# V0.1.5 validation

- File: `equip-1-V0.1.5.FCStd`
- SHA256: `4f3bcf25f86ee7adbdddf70afb0b1859b24fe44419dfd9e70b2e559c1a5bb93f`
- Run: 2026-11-06 13:24 CET, FreeCAD 1.1.3, 899 s
- Result: **349/349 checks pass**, 18/18 negative controls fail as expected

| Check | Pass | Fail |
|---|---|---|
| recompute | 1 | 0 |
| preview reset | 1 | 0 |
| reopen recompute | 18 | 0 |
| solid+bbox | 18 | 0 |
| no interference | 138 | 0 |
| clearance | 5 | 0 |
| OLED locators | 1 | 0 |
| shoe mount | 1 | 0 |
| min wall | 8 | 0 |
| cut effective | 71 | 0 |
| predecessor | 19 | 0 |
| fit | 25 | 0 |
| fit port clearance | 4 | 0 |
| edit/restore | 20 | 0 |
| tooltips | 1 | 0 |
| export STEP | 18 | 0 |

## Failures

None.

## Information (not counted)

- fit — board files: 2F_pcba_20240401.stp cb231da3ac67, firehat-rev5-proposal.step 43d323b9b0ed

## Negative controls

- solid+bbox: NEG two disjoint boxes → FAILS AS EXPECTED
- no interference: NEG overlapping boxes → FAILS AS EXPECTED
- OLED locators: NEG panel moved 0.3 mm → FAILS AS EXPECTED
- clearance: NEG cover moved 0.2 mm → FAILS AS EXPECTED
- min wall: NEG ShellTop 0.3 mm skin → FAILS AS EXPECTED
- cut effective: NEG cutter outside part → FAILS AS EXPECTED
- predecessor: NEG cover scaled 1.02 → FAILS AS EXPECTED
- fit: NEG Button1 lifted 0.3 mm → FAILS AS EXPECTED
- fit: NEG blower 1 mm higher → FAILS AS EXPECTED
- fit: NEG spacer 0.3 mm short → FAILS AS EXPECTED
- fit: NEG heat spreader 0.3 mm thicker → FAILS AS EXPECTED
- fit: NEG heatsink 5.6 mm taller → FAILS AS EXPECTED
- fit: NEG FPC with panel moved 1 mm in X → FAILS AS EXPECTED
- fit: NEG GlassJig shifted 0.3 mm → FAILS AS EXPECTED
- fit: NEG Firehat lifted 1 mm → FAILS AS EXPECTED
- edit/restore: NEG unbound parameter → FAILS AS EXPECTED
- tooltips: NEG stale WindowR tooltip → FAILS AS EXPECTED
- export STEP: NEG scaled 1.01 → FAILS AS EXPECTED

## Limits

CAD packaging only. Not physical fit, strength, electrical, thermal or manufacturing qualification.
Fit checks use Radxa's ROCK 2F v1.0 model and the Firehat Rev 4 KiCad export (hw/cad/boards); neither is a measured board.

Details: `.build/verify-4f3bcf25f86e.json` (regenerable; rerun `scripts/verify.py`).
