"""Build checked STEP models of the boards that go inside the enclosure.

  Firehat Rev 4  - exported from its KiCad project with 3D-model fixes applied to an extracted copy
  ROCK 2F v1.0   - Radxa's official PCBA model, downloaded and SHA256-pinned

Sources are never modified. Everything generated goes to hw/cad/boards/.build/.
Run:  FreeCADCmd hw/cad/boards/build_boards.py
Needs KiCad 10 (kicad-cli), easyeda2kicad and the easyeda2kicad 3D library in ~/Documents/KiCad/easyeda2kicad.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import Part

HERE = Path(os.environ.get('EQUIP1_BOARDS_ROOT') or Path(__file__).resolve().parent)
OUT = HERE / '.build'
KICAD_CLI = os.environ.get('KICAD_CLI', '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
EASYEDA_LIB = Path(os.environ.get('EASYEDA2KICAD', Path.home() / 'Documents/KiCad/easyeda2kicad'))

FIREHAT_ZIP = Path(os.environ.get('FIREHAT_REV4_ZIP', Path.home() / 'Desktop/ceg/wikis/firehat/raw/sources/2026-10-29-firehat-rev4/firehat_rev4_internal.zip'))
FIREHAT_SHA = '2e107eac7a18a76e8db7b6f86c0efbd62e55b626c84963af174ff741d9072809'
RADXA_URL = 'https://dl.radxa.com/rock2/2f/2F_pcba_20240401.zip'
RADXA_SHA = 'af06e6c56419f8bf23275883289bf734e6ea7e97939cc741c1727fedbd832ccb'
BT2_LCSC, BT2_SHA = 'C2926854', '4a16374e8759cd098da00ca4ed8b8878ee571304ad3d4b9e5357bd378caae033'

# Firehat Rev 4 3D fixes (datasheet-backed; see README.md)
VRML_ONLY = ['FPC-SMD_16P-P0.50_AFC07-S16FCC-00', 'HDR-TH_40P-P2.54-F-LI-2X20P', 'LED-SMD_4P-L2.0-W2.0-BR']
SWITCH_Z = 1.7            # KSC4TE01J: model bottom on the board, actuator 5.2 mm above it (C&K KSC4 TE datasheet)
SWITCH_HEIGHT = 5.2
BT2_OFFSET = (-8.74, -7.09, -8.99)  # LOTES AAA-BAT-046: centre the locating pegs (8.00 apart) on the footprint, holder on the board
BT2_HEIGHT = 3.70
TOL = 0.05


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pinned(path, digest):
    got = sha256(path)
    if got != digest:
        raise SystemExit(f'refusing: {path} SHA256 {got} != pinned {digest}')
    return path


def firehat():
    work = OUT / 'firehat-rev4'
    shutil.rmtree(work, ignore_errors=True)
    with zipfile.ZipFile(pinned(FIREHAT_ZIP, FIREHAT_SHA)) as z:
        z.extractall(work)
    proj = next(work.glob('*/firehat.kicad_pcb')).parent
    models = proj / '3dmodels'
    for name in VRML_ONLY:  # kicad-cli --subst-models picks a .step next to the .wrl
        shutil.copy(EASYEDA_LIB / 'easyeda2kicad.3dshapes' / f'{name}.step', models)
    bt2 = OUT / 'easyeda' / 'bt2.3dshapes' / 'BAT-SMD_AAA-BAT-046-K01.step'
    if not bt2.exists():
        subprocess.run(['easyeda2kicad', '--3d', f'--lcsc_id={BT2_LCSC}', '--output', str(OUT / 'easyeda' / 'bt2')], check=True)
    shutil.copy(pinned(bt2, BT2_SHA), models)

    pcb = (proj / 'firehat.kicad_pcb').read_text()
    pcb, n = re.subn(r'(SW-SMD_4P-L6\.2-W6\.2_KSC4DXJ\.step"\s*\(offset\s*\(xyz )[^)]*\)', rf'\g<1>0 0 {SWITCH_Z})', pcb)
    assert n == 3, f'expected 3 switch models, patched {n}'
    i = re.search(r'\(footprint "[^"]*BAT-SMD_AAA-BAT-046-K01"', pcb).start()
    depth, j = 0, i
    for j in range(i, len(pcb)):
        depth += {'(': 1, ')': -1}.get(pcb[j], 0)
        if depth == 0:
            break
    assert '(model' not in pcb[i:j], 'BT2 already has a model'
    model = ('(model "${KIPRJMOD}/3dmodels/BAT-SMD_AAA-BAT-046-K01.step"\n\t\t\t(offset (xyz %g %g %g))\n'
             '\t\t\t(scale (xyz 1 1 1))\n\t\t\t(rotate (xyz 0 0 0))\n\t\t)' % BT2_OFFSET)
    pcb = pcb[:j] + '\n\t\t' + model + '\n\t' + pcb[j:]
    (proj / 'firehat.kicad_pcb').write_text(pcb)

    step = OUT / 'firehat-rev4.step'
    env = dict(os.environ, EASYEDA2KICAD=str(EASYEDA_LIB), KICAD8_3RD_PARTY=str(Path.home() / 'Documents/KiCad/8.0/3rdparty'))
    r = subprocess.run([KICAD_CLI, 'pcb', 'export', 'step', '--subst-models', '--force', '-o', str(step), str(proj / 'firehat.kicad_pcb')],
                       env=env, capture_output=True, text=True)
    missing = sorted({Path(m).name for m in re.findall(r'File not found: (\S+)', r.stdout + r.stderr)})
    if r.returncode or not step.exists():
        raise SystemExit(f'kicad-cli failed: {r.stderr[-2000:]}')
    return step, missing, footprints(pcb)


def footprints(pcb):
    """Reference -> (x, y, layer) in STEP coordinates (KiCad Y is flipped)."""
    out = {}
    for m in re.finditer(r'\(footprint "[^"]+"\s*\(layer "([^"]+)"\)(.*?)\(property "Reference" "([^"]+)"', pcb, re.S):
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+)', m.group(2))
        out[m.group(3)] = (float(at.group(1)), -float(at.group(2)), m.group(1))
    return out


def rock2f():
    z = OUT / '2F_pcba_20240401.zip'
    if not z.exists():
        urllib.request.urlretrieve(RADXA_URL, z)
    with zipfile.ZipFile(pinned(z, RADXA_SHA)) as f:
        f.extractall(OUT / 'rock-2f')
    return next((OUT / 'rock-2f').glob('*.stp'))


def near(solids, x, y, r=4.0):
    return [s for s in solids if abs(s.BoundBox.Center.x - x) < r and abs(s.BoundBox.Center.y - y) < r]


def check_firehat(step, missing, fp):
    s = Part.read(str(step))
    board = max(s.Solids, key=lambda so: so.BoundBox.XLength * so.BoundBox.YLength if so.BoundBox.ZLength < 2 else 0)
    top, bottom = board.BoundBox.ZMax, board.BoundBox.ZMin
    rows = [('board outline', abs(board.BoundBox.XLength - 65) < TOL and abs(board.BoundBox.YLength - 56) < TOL,
             f'{board.BoundBox.XLength:.2f} x {board.BoundBox.YLength:.2f} x {board.BoundBox.ZLength:.2f} mm')]
    for ref in ('SW1', 'SW2', 'SW3'):
        x, y, _ = fp[ref]
        sw = [so for so in near(s.Solids, x, y) if so.BoundBox.ZMax > top + 1]
        zmin, zmax = min(so.BoundBox.ZMin for so in sw), max(so.BoundBox.ZMax for so in sw)
        rows.append((f'{ref} seated, {SWITCH_HEIGHT} mm tall', abs(zmin - top) < TOL and abs(zmax - top - SWITCH_HEIGHT) < TOL,
                     f'bottom {zmin - top:+.3f} mm, actuator top {zmax - top:.3f} mm above board'))
    x, y, _ = fp['BT2']
    bt = [so for so in s.Solids if so.BoundBox.ZMax <= bottom + 0.2 and 14 < so.BoundBox.XLength < 17]
    bb = bt[0].BoundBox if bt else None
    rows.append(('BT2 on board underside', bool(bt) and bb.ZMax <= bottom + 0.1 and bottom - bb.ZMin <= BT2_HEIGHT + 0.8,
                 f'top {bb.ZMax - bottom:+.2f} mm, depth {bottom - bb.ZMin:.2f} mm (drawing {BT2_HEIGHT} mm; model is conservative)' if bt else 'holder not found'))
    if bt:  # body centre sits 0.2 mm from the peg centre line in the model
        d = ((bb.Center.x - x) ** 2 + (bb.Center.y - y) ** 2) ** 0.5
        rows.append(('BT2 centred on footprint', d < 0.5, f'body centre {d:.2f} mm from footprint origin'))
    rows.append(('only 0402 passives lack models', all(m in ('C_0402.step', 'R_0402.step') for m in missing), f'missing: {missing}'))
    return rows, s


def main():
    OUT.mkdir(exist_ok=True)
    fh, missing, fp = firehat()
    rows, fh_shape = check_firehat(fh, missing, fp)
    rk = rock2f()
    rk_shape = Part.read(str(rk))
    rk_board = max(rk_shape.Solids, key=lambda so: so.Volume)
    holes = sorted({(round(f.Surface.Center.x, 2), round(f.Surface.Center.y, 2)) for f in rk_board.Faces
                    if type(f.Surface).__name__ == 'Cylinder' and abs(f.Surface.Radius - 1.75) < 0.01})
    xs, ys = sorted({h[0] for h in holes}), sorted({h[1] for h in holes})
    rows.append(('ROCK 2F mounting pattern', len(holes) == 4, f'{xs[-1] - xs[0]:.2f} x {ys[-1] - ys[0]:.2f} mm, board {rk_board.BoundBox.XLength:.2f} x {rk_board.BoundBox.YLength:.2f} x {rk_board.BoundBox.ZLength:.2f} mm'))
    report = {'firehat_rev4_step': fh.name, 'firehat_sha256': sha256(fh), 'rock2f_step': rk.name, 'rock2f_sha256': sha256(rk),
              'checks': [dict(check=c, ok=bool(ok), detail=d) for c, ok, d in rows]}
    (OUT / 'boards-report.json').write_text(json.dumps(report, indent=1))
    for c, ok, d in rows:
        print(f'{"PASS" if ok else "FAIL":5} {c:34} {d}')
    print('BOARDS DONE' if all(ok for _, ok, _ in rows) else 'BOARDS FAILED')


main()
