# V0.1.0 validation

- File: `equip-1-V0.1.0.FCStd`
- SHA256: `893f40edcc85e844fc9fb42b399d70355801d580003bfc8970f26f1a778d22ac`
- Run: 2026-10-29 20:39 CET, FreeCAD 1.1.3, 560 s
- Result: **108/110 checks pass**, 9/9 negative controls fail as expected

| Check | Pass | Fail |
|---|---|---|
| recompute | 1 | 0 |
| preview reset | 1 | 0 |
| reopen recompute | 6 | 0 |
| solid+bbox | 6 | 0 |
| no interference | 15 | 0 |
| clearance | 5 | 0 |
| min wall | 1 | 2 |
| cut effective | 50 | 0 |
| preserved | 6 | 0 |
| edit/restore | 10 | 0 |
| tooltips | 1 | 0 |
| export STEP | 6 | 0 |

## Failures

- **min wall** — ShellTop: 1620 samples, min 0.191 mm; 2 face(s) below 0.6 mm: 0.191 mm near [18.7, -36.56, 7.56]; 0.191 mm near [3.4, -36.56, 7.56]
- **min wall** — ShellBottom: 1410 samples, min 0.197 mm; 6 face(s) below 0.6 mm: 0.197 mm near [-13.86, -36.56, 7.37]; 0.197 mm near [-5.54, -36.56, 7.37]; 0.55 mm near [-1.36, -36.72, 6.95]; 0.55 mm near [-1.12, -36.56, 7.5]; 0.55 mm near [23.64, -36.72, 6.95]; 0.55 mm near [24.49, -36.56, 7.5]

## Information (not counted)

- min wall — reference shell-top.step: 1610 samples, min 0.190 mm; 2 face(s) below 0.6 mm: 0.19 mm near [3.4, -36.56, 7.56]; 0.19 mm near [18.7, -36.56, 7.56]
- min wall — reference shell-bot.step: 1525 samples, min 0.196 mm; 6 face(s) below 0.6 mm: 0.196 mm near [-5.55, -36.56, 7.37]; 0.196 mm near [-13.85, -36.56, 7.37]; 0.555 mm near [-1.13, -36.56, 7.5]; 0.555 mm near [24.49, -36.56, 7.5]; 0.555 mm near [23.64, -36.72, 6.95]; 0.555 mm near [-1.36, -36.72, 6.95]

## Negative controls

- solid+bbox: NEG two disjoint boxes → FAILS AS EXPECTED
- no interference: NEG overlapping boxes → FAILS AS EXPECTED
- clearance: NEG cover moved 0.2 mm → FAILS AS EXPECTED
- min wall: NEG ShellTop 0.3 mm skin → FAILS AS EXPECTED
- cut effective: NEG cutter outside part → FAILS AS EXPECTED
- preserved: NEG ShellTop moved 0.5 mm → FAILS AS EXPECTED
- edit/restore: NEG unbound parameter → FAILS AS EXPECTED
- tooltips: NEG stale WindowR tooltip → FAILS AS EXPECTED
- export STEP: NEG scaled 1.01 → FAILS AS EXPECTED

## Limits

CAD packaging only. Not physical fit, strength, electrical, thermal or manufacturing qualification.
Preservation is measured against the reference STEP set; known modelling simplifications are listed in the design README.

Details: `.build/verify-893f40edcc85.json` (regenerable; rerun `scripts/verify.py`).
