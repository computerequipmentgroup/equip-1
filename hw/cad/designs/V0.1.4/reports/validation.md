# V0.1.4 validation

- File: `equip-1-V0.1.4.FCStd`
- SHA256: `9a07d0868b869bd427e2b5d8d060d508f7ba38a219749b7cd653c1f535b11bf6`
- Run: 2026-11-02 23:42 CET, FreeCAD 1.1.3, 758 s
- Result: **320/321 checks pass**, 17/17 negative controls fail as expected

| Check | Pass | Fail |
|---|---|---|
| recompute | 1 | 0 |
| preview reset | 1 | 0 |
| reopen recompute | 17 | 0 |
| solid+bbox | 17 | 0 |
| no interference | 122 | 0 |
| clearance | 5 | 0 |
| OLED locators | 1 | 0 |
| shoe mount | 1 | 0 |
| min wall | 8 | 0 |
| cut effective | 68 | 0 |
| predecessor | 18 | 0 |
| fit | 21 | 1 |
| fit port clearance | 4 | 0 |
| edit/restore | 18 | 0 |
| tooltips | 1 | 0 |
| export STEP | 17 | 0 |

## Failures

- **fit** — OLED FPC through the slot into FPC2: expected one 16.75 x 2.25 mm slot and one FPC2 body, found 1 / 0

## Information (not counted)

- fit — board files: 2F_pcba_20240401.stp cb231da3ac67, firehat-rev5-proposal.step b18c5d76973a

## Negative controls

- solid+bbox: NEG two disjoint boxes → FAILS AS EXPECTED
- no interference: NEG overlapping boxes → FAILS AS EXPECTED
- OLED locators: NEG panel moved 0.3 mm → FAILS AS EXPECTED
- clearance: NEG cover moved 0.2 mm → FAILS AS EXPECTED
- min wall: NEG ShellTop 0.3 mm skin → FAILS AS EXPECTED
- cut effective: NEG cutter outside part → FAILS AS EXPECTED
- predecessor: NEG cover scaled 1.02 → FAILS AS EXPECTED
- fit: NEG Button1 lifted 0.3 mm → FAILS AS EXPECTED
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

Details: `.build/verify-9a07d0868b86.json` (regenerable; rerun `scripts/verify.py`).
