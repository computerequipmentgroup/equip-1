# V0.1.1 validation

- File: `equip-1-V0.1.1.FCStd`
- SHA256: `c6d74194bb2f7072c8baa9af6dfb58f21a04da9ae80a8f4e3aad8507d5053d9b`
- Run: 2026-10-29 22:20 CET, FreeCAD 1.1.3, 424 s
- Result: **114/114 checks pass**, 10/10 negative controls fail as expected

| Check | Pass | Fail |
|---|---|---|
| recompute | 1 | 0 |
| preview reset | 1 | 0 |
| reopen recompute | 4 | 0 |
| solid+bbox | 4 | 0 |
| no interference | 6 | 0 |
| clearance | 4 | 0 |
| min wall | 3 | 0 |
| cut effective | 57 | 0 |
| predecessor | 5 | 0 |
| fit | 10 | 0 |
| fit port clearance | 4 | 0 |
| edit/restore | 10 | 0 |
| tooltips | 1 | 0 |
| export STEP | 4 | 0 |

## Failures

None.

## Information (not counted)

- fit — board files: 2F_pcba_20240401.stp cb231da3ac67, firehat-rev4.step e78ac18e77d6

## Negative controls

- solid+bbox: NEG two disjoint boxes → FAILS AS EXPECTED
- no interference: NEG overlapping boxes → FAILS AS EXPECTED
- clearance: NEG cover moved 0.2 mm → FAILS AS EXPECTED
- min wall: NEG ShellTop 0.3 mm skin → FAILS AS EXPECTED
- cut effective: NEG cutter outside part → FAILS AS EXPECTED
- predecessor: NEG cover scaled 1.02 → FAILS AS EXPECTED
- fit: NEG Firehat lifted 1 mm → FAILS AS EXPECTED
- edit/restore: NEG unbound parameter → FAILS AS EXPECTED
- tooltips: NEG stale WindowR tooltip → FAILS AS EXPECTED
- export STEP: NEG scaled 1.01 → FAILS AS EXPECTED

## Limits

CAD packaging only. Not physical fit, strength, electrical, thermal or manufacturing qualification.
Fit checks use Radxa's ROCK 2F v1.0 model and the Firehat Rev 4 KiCad export (hw/cad/boards); neither is a measured board.

Details: `.build/verify-c6d74194bb2f.json` (regenerable; rerun `scripts/verify.py`).
