"""Reopen the saved equip-1-V0.1.0.FCStd and run every check. Never saves.

Writes reports/validation.md (summary) and .build/verify-<sha12>.json (details).
Each check is also run once on a deliberately broken input (negative control) and
must fail there, otherwise the check itself is reported as unproven.

Run headless:   FreeCADCmd scripts/verify.py
"""
import hashlib
import json
import math
import os
import time
from pathlib import Path

import FreeCAD as App
import Part

ROOT = Path(os.environ.get('EQUIP1_CAD_ROOT') or Path(__file__).resolve().parents[1])
CFG = json.loads((ROOT / 'config' / 'assembly.json').read_text())
FCSTD = ROOT / CFG['document']
BUILD = ROOT / '.build'

# Check tolerances (not design dimensions)
VOL_EPS = 1e-3            # mm³, "no interference" / "nothing left behind"
BBOX_TOL = 0.02           # mm, native bbox vs reference bbox
PRESERVE_DEV = 0.5        # mm, max two-way surface deviation native vs predecessor
CLEAR_TOL = 0.01          # mm, measured clearance vs expected derived value
EXPORT_REL = 1e-5         # |directed difference| / part volume, native vs STEP read-back (volume-integration noise)
FUZZY = 1e-4             # mm, boolean fuzzy value for near-coincident faces
RAYS = 3                  # wall-thickness samples per face direction (RAYS² per face)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def directed(a, b):
    # fuzzy common: plain OCC booleans mis-handle the coincident faces of near-identical solids
    c = a.common(b, FUZZY).Volume
    return a.Volume - c, b.Volume - c


def bbox(s):
    bb = s.BoundBox
    return [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]


# ---- checks: pure functions returning (ok, detail) -------------------------------

def check_solid(shape, ref_bbox):
    n = len(shape.Solids)
    ok = n == 1 and shape.isValid() and shape.Solids[0].isClosed()
    dev = max(abs(a - b) for a, b in zip(bbox(shape), ref_bbox))
    return ok and dev <= BBOX_TOL, f'solids={n} valid={shape.isValid()} max bbox dev={dev:.4f} mm'


def check_no_interference(a, b):
    v = a.common(b).Volume
    return v < VOL_EPS, f'common volume {v:.5f} mm³'


def check_clearance(a, b, expected):
    d = a.distToShape(b)[0]
    return abs(d - expected) <= CLEAR_TOL, f'min distance {d:.4f} mm, expected {expected:.4f} mm'


def wall_samples(shape):
    """Wall thickness along the inward normal at RAYS² interior points of every face."""
    worst = []
    for fi, f in enumerate(shape.Faces):
        u0, u1, v0, v1 = f.ParameterRange
        for i in range(RAYS):
            for j in range(RAYS):
                u, v = u0 + (u1 - u0) * (i + 0.5) / RAYS, v0 + (v1 - v0) * (j + 0.5) / RAYS
                p = f.valueAt(u, v)
                if not f.isInside(p, 1e-5, True):
                    continue
                n = f.normalAt(u, v)
                if shape.isInside(p - n * 0.01, 1e-6, False) is False:
                    n = -n
                seg = Part.LineSegment(p - n * 1e-4, p - n * 40).toShape()
                inner = [e for e in seg.common(shape).Edges if e.Vertexes and min((vx.Point - p).Length for vx in e.Vertexes) < 0.01]
                if inner:
                    worst.append((min(e.Length for e in inner), fi, [round(c, 2) for c in p]))
    return sorted(worst)


def check_min_wall(shape, min_wall):
    s = wall_samples(shape)
    thin = {}
    for t, fi, p in s:
        if t < min_wall and fi not in thin:
            thin[fi] = (round(t, 3), p)
    lo = s[0] if s else (math.inf, None, None)
    spots = '; '.join(f'{t} mm near {p}' for t, p in thin.values())
    return not thin, f'{len(s)} samples, min {lo[0]:.3f} mm; {len(thin)} face(s) below {min_wall} mm' + (f': {spots}' if thin else '')


def check_cut(cutter, base, final):
    removed = cutter.common(base).Volume
    left = cutter.common(final).Volume
    return removed > VOL_EPS and left < VOL_EPS, f'removed {removed:.3f} mm³, left {left:.5f} mm³'


def surface_points(s):
    pts = [e.valueAt((e.FirstParameter + e.LastParameter) / 2) for e in s.Edges]
    for f in s.Faces:
        u0, u1, v0, v1 = f.ParameterRange
        for i in range(RAYS):
            for j in range(RAYS):
                p = f.valueAt(u0 + (u1 - u0) * (i + 0.5) / RAYS, v0 + (v1 - v0) * (j + 0.5) / RAYS)
                if f.isInside(p, 1e-5, True):
                    pts.append(p)
    return pts


def deviation(a, b):
    skin = Part.Compound(b.Faces)
    return max((skin.distToShape(Part.Vertex(p))[0], [round(c, 2) for c in p]) for p in surface_points(a))


def check_preserved(native, ref):
    # Boolean-free: OCC booleans between independently modelled near-identical solids are unreliable.
    (d1, p1), (d2, p2) = deviation(native, ref), deviation(ref, native)
    dv = native.Volume - ref.Volume
    return max(d1, d2) <= PRESERVE_DEV, f'surface deviation native→ref {d1:.3f} mm at {p1}, ref→native {d2:.3f} mm at {p2}; volume Δ {dv:+.2f} mm³ ({dv / ref.Volume * 100:+.3f}%)'


def check_export(native, step_shape):
    ok = len(step_shape.Solids) == 1 and step_shape.isValid() and step_shape.Solids[0].isClosed()
    dev = max(abs(a - b) for a, b in zip(bbox(native), bbox(step_shape)))
    a, b = directed(native, step_shape)
    tol = EXPORT_REL * native.Volume
    return ok and dev <= 1e-3 and max(abs(a), abs(b)) <= tol, f'solids={len(step_shape.Solids)} bbox dev {dev:.5f} mm, directed {a:.5f}/{b:.5f} mm³ (tol {tol:.4f})'


def check_tooltip(vs, name):
    value = getattr(vs, name).Value
    tip = vs.getDocumentationOfProperty(name)
    want = f'Current value: {value:g} mm'
    return want in tip, f'tooltip says "{tip.split("Current value: ")[-1]}", value {value:g} mm'


# ---- runner ----------------------------------------------------------------------

class Report:
    def __init__(self):
        self.rows = []

    def add(self, check, subject, result, negative=False):
        ok, detail = result
        status = 'INFO' if ok is None else ('PASS' if ok else 'FAIL') if not negative else ('FAILS AS EXPECTED' if not ok else 'UNPROVEN (did not fail)')
        self.rows.append(dict(check=check, subject=subject, status=status, detail=detail, negative=negative))
        print(f'{status:24} {check:18} {subject:28} {detail}')
        return ok


def reference_shapes():
    refs, cache = {}, {}
    for p in CFG['parts']:
        path = (ROOT / p['reference']).resolve()
        cache.setdefault(path, Part.read(str(path)))
        s = cache[path]
        if 'reference_solid' in p:
            solids = sorted(s.Solids, key=lambda so: so.CenterOfMass.y)
            s = solids[['front', 'middle', 'back'].index(p['reference_solid'])]
        refs[p['name']] = (s, path)
    return refs


def main():
    t0 = time.time()
    digest = sha256(FCSTD)
    doc = App.openDocument(str(FCSTD))
    R = Report()
    vs, pv = doc.getObject(CFG['groups']['parameters']), doc.getObject(CFG['groups']['preview'])
    parts = {p['name']: doc.getObject(p['name']) for p in CFG['parts']}
    refs = reference_shapes()

    # 0. Document state
    bad = [o.Name for o in doc.Objects if 'Invalid' in o.State or 'Error' in o.State]
    R.add('recompute', 'document', (not bad, f'objects in error: {bad}'))
    R.add('preview reset', 'Preview.ButtonPress', (pv.ButtonPress.Value == 0, f'{pv.ButtonPress.Value} mm'))
    shapes = {k: o.Shape.copy() for k, o in parts.items()}
    doc.recompute()
    for k, o in parts.items():
        a, b = directed(shapes[k], o.Shape)
        R.add('reopen recompute', k, (max(a, b) < VOL_EPS, f'saved vs recomputed directed {a:.5f}/{b:.5f} mm³'))

    # 1. Solids + bbox vs reference
    for k, s in shapes.items():
        R.add('solid+bbox', k, check_solid(s, bbox(refs[k][0])))
    R.add('solid+bbox', 'NEG two disjoint boxes', check_solid(Part.makeCompound([Part.makeBox(1, 1, 1), Part.makeBox(1, 1, 1, App.Vector(3, 0, 0))]), [0, 0, 0, 4, 1, 1]), negative=True)

    # 2. Interference + clearances
    names = list(shapes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            R.add('no interference', f'{a} × {b}', check_no_interference(shapes[a], shapes[b]))
    R.add('no interference', 'NEG overlapping boxes', check_no_interference(Part.makeBox(2, 2, 2), Part.makeBox(2, 2, 2, App.Vector(1, 1, 1))), negative=True)
    out = doc.getObject(CFG['groups']['outputs'])
    R.add('clearance', 'ScreenCover ↔ ShellTop', check_clearance(shapes['ScreenCover'], shapes['ShellTop'], vs.CoverClearance.Value))
    H, skin = vs.BodyHeight.Value, vs.TopSkin.Value
    for i in (1, 2, 3):
        cap = shapes[f'Button{i}'].common(Part.makeBox(100, 100, 10, App.Vector(-50, -60, H - skin + 0.01)))
        exp = (vs.ButtonHoleSize.Value - getattr(vs, f'Cap{i}Size').Value) / 2
        R.add('clearance', f'Button{i} cap ↔ hole', check_clearance(cap, shapes['ShellTop'], exp))
    lip = shapes['ShellBottom'].common(Part.makeBox(200, 200, 10, App.Vector(-100, -100, vs.SeamZ.Value + 0.01)))
    R.add('clearance', 'lip ↔ groove', check_clearance(lip, shapes['ShellTop'], min(out.SeamLateralClearance.Value, out.SeamVerticalClearance.Value)))
    R.add('clearance', 'NEG cover moved 0.2 mm', check_clearance(shapes['ScreenCover'].translated(App.Vector(0.2, 0, 0)), shapes['ShellTop'], vs.CoverClearance.Value), negative=True)

    # 3. Minimum wall / skin thickness
    walls = {}
    for k in ('ShellTop', 'ShellBottom', 'ScreenCover'):
        walls[k] = R.add('min wall', k, check_min_wall(shapes[k], vs.MinWall.Value))
    for k in ('ShellTop', 'ShellBottom'):
        ok, detail = check_min_wall(refs[k][0], vs.MinWall.Value)
        R.add('min wall', f'reference {refs[k][1].name}', (None, detail))
    pocket = Part.makeBox(6, 6, 2.7, App.Vector(5, 10, H - 0.3 - 2.7))  # leaves 0.3 mm top skin
    R.add('min wall', 'NEG ShellTop 0.3 mm skin', check_min_wall(shapes['ShellTop'].cut(pocket), vs.MinWall.Value), negative=True)

    # 4. Every intended cut removed material
    for p in CFG['parts']:
        if 'cut' not in p:
            continue
        cut = doc.getObject(p['cut'])
        base, final = cut.Base.Shape, shapes[p['name']]
        for c in cut.Tool.Shapes:
            R.add('cut effective', f'{p["name"]}: {c.Label}', check_cut(c.Shape, base, final))
    stray = Part.makeBox(2, 2, 2, App.Vector(100, 0, 0))
    R.add('cut effective', 'NEG cutter outside part', check_cut(stray, doc.getObject('ShellTop').Base.Shape, shapes['ShellTop']), negative=True)

    # 5. Preservation vs predecessor (reference STEP set; no intended changes)
    for k, s in shapes.items():
        R.add('preserved', f'{k} vs {refs[k][1].name}', check_preserved(s, refs[k][0]))
    R.add('preserved', 'NEG ShellTop moved 0.5 mm', check_preserved(shapes['ShellTop'].translated(App.Vector(0.5, 0, 0)), refs['ShellTop'][0]), negative=True)

    # 6. Edit / restore
    brep = {k: hashlib.sha256(o.Shape.exportBrepToString().encode()).hexdigest() for k, o in parts.items()}  # after the reopen recompute
    edits = [('BodyLength', 1.0, ['ShellTop', 'ShellBottom']), ('BodyHeight', 1.0, ['ShellTop', 'ScreenCover']),
             ('Wall', 0.2, ['ShellTop', 'ShellBottom']), ('CornerR', -0.5, ['ShellTop', 'ShellBottom']),
             ('TopEdgeR', -1.0, ['ShellTop']), ('SeamZ', 0.5, ['ShellTop', 'ShellBottom']),
             ('WindowX1', 1.0, ['ShellTop', 'ScreenCover']), ('ButtonX', 0.5, ['Button1', 'ShellTop']),
             ('RoundPortR', 0.3, ['ShellTop', 'ShellBottom']), ('FloorVentPitch', 0.5, ['ShellBottom'])]

    def edit_restore(vset, prop, delta, targets):
        orig = getattr(vset, prop).Value
        setattr(vset, prop, orig + delta)
        doc.recompute()
        moved = {t: sum(directed(shapes[t], parts[t].Shape)) for t in targets}
        setattr(vset, prop, orig)
        doc.recompute()
        same = {t: hashlib.sha256(parts[t].Shape.exportBrepToString().encode()).hexdigest() == brep[t] for t in targets}
        geo = {t: sum(directed(shapes[t], parts[t].Shape)) < VOL_EPS for t in targets}
        ok = all(v > VOL_EPS for v in moved.values()) and all(geo.values())
        return ok, f'Δ{delta:+g} mm changed ' + ', '.join(f'{t} by {v:.2f} mm³' for t, v in moved.items()) + \
            f'; restored geometry identical={all(geo.values())}, BREP byte-identical={all(same.values())}'

    for prop, delta, targets in edits:
        R.add('edit/restore', prop, edit_restore(vs, prop, delta, targets))
    vs.addProperty('App::PropertyLength', 'VerifyUnboundProbe', 'Verify', 'temporary, never saved')
    vs.VerifyUnboundProbe = 1.0
    R.add('edit/restore', 'NEG unbound parameter', edit_restore(vs, 'VerifyUnboundProbe', 1.0, ['ShellTop']), negative=True)
    vs.removeProperty('VerifyUnboundProbe')

    # 7. Tooltips state current values
    stale = [n for n in vs.PropertiesList if vs.getGroupOfProperty(n) not in ('', 'Base') and n != 'ExposedParameters' and not check_tooltip(vs, n)[0]]
    R.add('tooltips', f'{len(vs.PropertiesList)} properties', (not stale, f'stale: {stale}'))
    vs.setDocumentationOfProperty('WindowR', 'stale. Current value: 9 mm')
    R.add('tooltips', 'NEG stale WindowR tooltip', check_tooltip(vs, 'WindowR'), negative=True)

    # 8. Exports (only if present)
    exports = {}
    for k, s in shapes.items():
        step = ROOT / 'exports' / f'equip-1-V0.1.0-{k}.step'
        if step.exists():
            exports[k] = R.add('export STEP', step.name, check_export(s, Part.read(str(step))))
        else:
            R.add('export STEP', step.name, (False, 'missing (run scripts/export.py, then verify again)'))
    R.add('export STEP', 'NEG scaled 1.01', check_export(shapes['ShellTop'], shapes['ShellTop'].scaled(1.01)), negative=True)

    App.closeDocument(doc.Name)  # never saved
    write_reports(R, digest, time.time() - t0)


def write_reports(R, digest, seconds):
    BUILD.mkdir(exist_ok=True)
    (BUILD / f'verify-{digest[:12]}.json').write_text(json.dumps({'fcstd_sha256': digest, 'rows': R.rows}, indent=1))
    real = [r for r in R.rows if not r['negative'] and r['status'] != 'INFO']
    info = [r for r in R.rows if r['status'] == 'INFO']
    neg = [r for r in R.rows if r['negative']]
    fails = [r for r in real if r['status'] == 'FAIL']
    unproven = [r for r in neg if r['status'].startswith('UNPROVEN')]
    by_check = {}
    for r in real:
        c = by_check.setdefault(r['check'], [0, 0])
        c[0 if r['status'] == 'PASS' else 1] += 1
    lines = [
        '# V0.1.0 validation', '',
        f'- File: `{CFG["document"]}`',
        f'- SHA256: `{digest}`',
        f'- Run: {time.strftime("%Y-%m-%d %H:%M %Z")}, FreeCAD {".".join(App.Version()[:3])}, {seconds:.0f} s',
        f'- Result: **{len(real) - len(fails)}/{len(real)} checks pass**, {len(neg) - len(unproven)}/{len(neg)} negative controls fail as expected',
        '', '| Check | Pass | Fail |', '|---|---|---|',
        *[f'| {c} | {p} | {f} |' for c, (p, f) in by_check.items()],
        '', '## Failures', '',
        *([f'- **{r["check"]}** — {r["subject"]}: {r["detail"]}' for r in fails] or ['None.']),
        '', '## Information (not counted)', '',
        *([f'- {r["check"]} — {r["subject"]}: {r["detail"]}' for r in info] or ['None.']),
        '', '## Negative controls', '',
        *[f'- {r["check"]}: {r["subject"]} → {r["status"]}' for r in neg],
        '', '## Limits', '',
        'CAD packaging only. Not physical fit, strength, electrical, thermal or manufacturing qualification.',
        'Preservation is measured against the reference STEP set; known modelling simplifications are listed in the design README.',
        '', f'Details: `.build/verify-{digest[:12]}.json` (regenerable; rerun `scripts/verify.py`).', ''
    ]
    (ROOT / 'reports').mkdir(exist_ok=True)
    (ROOT / 'reports' / 'validation.md').write_text('\n'.join(lines))
    print(f'VERIFY DONE: {len(real) - len(fails)}/{len(real)} pass, {len(unproven)} unproven negative controls, sha256 {digest}')


main()
