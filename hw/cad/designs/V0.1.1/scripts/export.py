"""Export STEP/BREP per part (incl. the OLED panel reference body) and the 1:1 feel-print mockup (3MF + STL) from the saved .FCStd.

Never saves the CAD. Run verify.py afterwards: it reads every STEP back and only then
are the exports qualified for publishing.

Run headless:   FreeCADCmd scripts/export.py
"""
import json
import os
from pathlib import Path

import FreeCAD as App
import Mesh
import MeshPart

ROOT = Path(os.environ.get('EQUIP1_CAD_ROOT') or Path(__file__).resolve().parents[1])
CFG = json.loads((ROOT / 'config' / 'assembly.json').read_text())
EXPORTS, MOCKUP = ROOT / 'exports', ROOT / 'print-mockup'
GAP = 6.0  # mm between parts on the print bed


def bed_layout(parts):
    """Detached copies laid out for printing: top shell flipped onto its top face, others as-is."""
    placed, x = [], 0.0
    for name in ('ShellBottom', 'ShellTop', 'ScreenCover'):
        s = parts[name].copy()
        if name == 'ShellTop':
            s.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 180)
        bb = s.BoundBox
        s.translate(App.Vector(x - bb.XMin, -bb.YMin, -bb.ZMin))
        placed.append((name, s))
        x += bb.XLength + GAP
    return placed


def main():
    doc = App.openDocument(str(ROOT / CFG['document']))
    if doc.getObject(CFG['groups']['preview']).TopLift.Value != 0:
        raise SystemExit('refusing: Preview.TopLift is not 0 in the saved file')
    EXPORTS.mkdir(exist_ok=True)
    MOCKUP.mkdir(exist_ok=True)
    parts = {p['name']: doc.getObject(p['name']).Shape for p in CFG['parts']}
    for name, s in parts.items():
        s.exportStep(str(EXPORTS / f'equip-1-{CFG["version"]}-{name}.step'))
        s.exportBrep(str(EXPORTS / f'equip-1-{CFG["version"]}-{name}.brep'))  # OledPanel is a reference body (bought part)

    meshes = []
    for name, s in bed_layout(parts):
        m = MeshPart.meshFromShape(Shape=s, LinearDeflection=0.01, AngularDeflection=0.1, Relative=False)
        if not m.isSolid() or m.hasNonManifolds():
            raise SystemExit(f'refusing: {name} mesh is not a closed manifold')
        f = doc.addObject('Mesh::Feature', f'Mockup{name}')
        f.Mesh = m
        meshes.append(f)
    Mesh.export(meshes, str(MOCKUP / f'equip-1-{CFG["version"]}-feel.3mf'))
    bb = App.BoundBox()
    for f in meshes:
        bb.add(f.Mesh.BoundBox)
    print(f'EXPORT DONE: {len(parts)} STEP/BREP, mockup bed {bb.XLength:.1f} x {bb.YLength:.1f} x {bb.ZLength:.1f} mm')
    App.closeDocument(doc.Name)  # never saved


main()
