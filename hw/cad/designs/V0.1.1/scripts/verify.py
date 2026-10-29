"""Reopen the saved equip-1-V0.1.1.FCStd and run every check, including fit with the real boards. Never saves.

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


def check_preserved(native, ref, tol=None):
    # Boolean-free: OCC booleans between independently modelled near-identical solids are unreliable.
    (d1, p1), (d2, p2) = deviation(native, ref), deviation(ref, native)
    dv = native.Volume - ref.Volume
    return max(d1, d2) <= (PRESERVE_DEV if tol is None else tol), f'surface deviation native→ref {d1:.3f} mm at {p1}, ref→native {d2:.3f} mm at {p2}; volume Δ {dv:+.2f} mm³ ({dv / ref.Volume * 100:+.3f}%)'


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


MOVED_TOL = 0.01          # mm; a moved-only part must be an exact translation of its predecessor
FIT_INTERFERENCE = 0.005  # mm³; board solid vs printed part / panel
FIT_PORT_CLEAR = 0.10     # mm; connectors passing through wall openings
ACCEPTED_CONTACT = 0.10   # mm³; listed print-tolerance contacts (config boards.accepted_contacts)


def board_frame(shape, hole_lo, hole_hi):
    board = max(shape.Solids, key=lambda so: so.BoundBox.XLength * so.BoundBox.YLength if so.BoundBox.ZLength < 2 else 0)
    u = {(round(f.Surface.Center.x, 2), round(f.Surface.Center.y, 2)) for f in board.Faces
         if type(f.Surface).__name__ == 'Cylinder' and hole_lo < f.Surface.Radius < hole_hi}
    return board, App.Vector(sum(p[0] for p in u) / len(u), sum(p[1] for p in u) / len(u), 0)


def place_boards(vs, rk, fh, firehat_lift=0.0):
    """ROCK 2F on the bottom bosses (rotated so its HDMI edge faces the front), Firehat under the towers.
    Both hole patterns centred on the tower pattern."""
    cx, cy = (vs.TopScrewX0.Value + vs.TopScrewX1.Value) / 2, (vs.TopScrewY0.Value + vs.TopScrewY1.Value) / 2
    rb, rc = board_frame(rk, 1.7, 1.8)
    fb, fc = board_frame(fh, 1.3, 1.4)
    r = rk.copy(); r.translate(-rc); r.rotate(App.Vector(), App.Vector(0, 0, 1), 90)
    r.translate(App.Vector(cx, cy, vs.BotBossTopZ.Value - rb.BoundBox.ZMin))
    f = fh.copy(); f.translate(App.Vector(cx - fc.x, cy - fc.y, vs.TowerBottomZ.Value - fb.BoundBox.ZMax + firehat_lift))
    return r, f


def board_interference(board, part):
    hits = []
    for so in board.Solids:
        if so.BoundBox.intersect(part.BoundBox):
            v = so.common(part).Volume
            if v > FIT_INTERFERENCE:
                b = so.BoundBox
                hits.append((round(v, 3), [round(c, 1) for c in (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)]))
    return hits


def check_fit(board, part, accepted=0):
    hits = board_interference(board, part)
    if not hits:
        return True, 'no interference'
    if len(hits) <= accepted and all(h[0] <= ACCEPTED_CONTACT for h in hits):
        return True, f'{len(hits)} listed contact(s) accepted as print tolerance: {hits}'
    return False, f'interferences: {hits}'


def check_port_clearance(board, part, walls):
    worst = (9e9, None)
    for so in board.Solids:
        if any(so.BoundBox.intersect(w) for w in walls):
            d = so.distToShape(part)[0]
            if d < worst[0]:
                b = so.BoundBox
                worst = (d, [round(c, 1) for c in (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)])
    return worst[0] >= FIT_PORT_CLEAR, f'min clearance {worst[0]:.3f} mm (>= {FIT_PORT_CLEAR}) at solid {worst[1]}'


def main():
    t0 = time.time()
    digest = sha256(FCSTD)
    doc = App.openDocument(str(FCSTD))
    R = Report()
    vs, pv, out = (doc.getObject(CFG['groups'][k]) for k in ('parameters', 'preview', 'outputs'))
    parts = {p['name']: doc.getObject(p['name']) for p in CFG['parts']}

    # 0. Document state
    bad = [o.Name for o in doc.Objects if 'Invalid' in o.State or 'Error' in o.State]
    R.add('recompute', 'document', (not bad, f'objects in error: {bad}'))
    R.add('preview reset', 'Preview.TopLift', (pv.TopLift.Value == 0, f'{pv.TopLift.Value} mm'))
    shapes = {k: o.Shape.copy() for k, o in parts.items()}
    doc.recompute()
    for k, o in parts.items():
        a, b = directed(shapes[k], o.Shape)
        R.add('reopen recompute', k, (max(a, b) < VOL_EPS, f'saved vs recomputed directed {a:.5f}/{b:.5f} mm³'))

    # 1. Solids + bounding boxes against the parameters
    x0, y0 = vs.BodyX0.Value, vs.BodyY0.Value
    env = [x0, y0, 0, x0 + vs.BodyLength.Value, y0 + vs.BodyWidth.Value, vs.BodyHeight.Value]
    expected = {'ShellTop': env[:2] + [vs.SeamZ.Value] + env[3:], 'ShellBottom': env[:5] + [vs.LipTopZ.Value]}
    wcx, wcy, cc = vs.WindowCX.Value, vs.WindowCY.Value, vs.CoverClearance.Value
    expected['ScreenCover'] = [wcx - vs.WindowLength.Value / 2 + cc, wcy - vs.WindowWidth.Value / 2 + cc, vs.BodyHeight.Value - vs.CoverThickness.Value,
                               wcx + vs.WindowLength.Value / 2 - cc, wcy + vs.WindowWidth.Value / 2 - cc, vs.BodyHeight.Value]
    pz = vs.TowerBottomZ.Value + vs.PanelFold.Value
    expected['OledPanel'] = [vs.PanelX.Value - vs.PanelLength.Value / 2, vs.PanelY.Value - vs.PanelWidth.Value / 2, pz,
                             vs.PanelX.Value + vs.PanelLength.Value / 2, vs.PanelY.Value + vs.PanelWidth.Value / 2, pz + vs.PanelThickness.Value]
    for k, s in shapes.items():
        R.add('solid+bbox', k, check_solid(s, expected[k]))
    R.add('solid+bbox', 'NEG two disjoint boxes', check_solid(Part.makeCompound([Part.makeBox(1, 1, 1), Part.makeBox(1, 1, 1, App.Vector(3, 0, 0))]), [0, 0, 0, 4, 1, 1]), negative=True)

    # 2. Interference + clearances between our parts
    names = list(shapes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            R.add('no interference', f'{a} × {b}', check_no_interference(shapes[a], shapes[b]))
    R.add('no interference', 'NEG overlapping boxes', check_no_interference(Part.makeBox(2, 2, 2), Part.makeBox(2, 2, 2, App.Vector(1, 1, 1))), negative=True)
    R.add('clearance', 'ScreenCover ↔ ShellTop', check_clearance(shapes['ScreenCover'], shapes['ShellTop'], min(vs.CoverClearance.Value, out.ScreenCoverFloorGap.Value)))
    lip = shapes['ShellBottom'].common(Part.makeBox(200, 200, 10, App.Vector(-100, -100, vs.SeamZ.Value + 0.01)))
    R.add('clearance', 'lip ↔ groove', check_clearance(lip, shapes['ShellTop'], min(out.SeamLateralClearance.Value, out.SeamVerticalClearance.Value)))
    R.add('clearance', 'OledPanel ↔ ScreenCover', check_clearance(shapes['OledPanel'], shapes['ScreenCover'], out.PanelToCoverGap.Value))
    R.add('clearance', 'OledPanel ↔ ShellTop', check_clearance(shapes['OledPanel'], shapes['ShellTop'], math.hypot(vs.PanelClearance.Value, out.PanelToCeilingGap.Value)))  # nearest is the opening's lower edge, diagonal
    R.add('clearance', 'NEG cover moved 0.2 mm', check_clearance(shapes['ScreenCover'].translated(App.Vector(0.2, 0, 0)), shapes['ShellTop'], min(vs.CoverClearance.Value, out.ScreenCoverFloorGap.Value)), negative=True)

    # 3. Minimum wall / skin thickness
    for k in ('ShellTop', 'ShellBottom', 'ScreenCover'):
        R.add('min wall', k, check_min_wall(shapes[k], vs.MinWall.Value))
    H = vs.BodyHeight.Value
    pocket = Part.makeBox(5, 4, 1.3, App.Vector(-15, -25, H - 0.3 - 1.3))  # leaves 0.3 mm top skin away from other features
    R.add('min wall', 'NEG ShellTop 0.3 mm skin', check_min_wall(shapes['ShellTop'].cut(pocket), vs.MinWall.Value), negative=True)

    # 4. Every intended cut removed material
    for p in CFG['parts']:
        if 'cut' not in p:
            continue
        cut = doc.getObject(p['cut'])
        base, final = cut.Base.Shape, shapes[p['name']]
        for c in cut.Tool.Shapes:
            R.add('cut effective', f'{p["name"]}: {c.Label}', check_cut(c.Shape, base, final))
    R.add('cut effective', 'NEG cutter outside part', check_cut(Part.makeBox(2, 2, 2, App.Vector(100, 0, 0)), doc.getObject('ShellTop').Base.Shape, shapes['ShellTop']), negative=True)

    # 5. Predecessor: only intended parts changed; moved parts are exact translations
    pred = App.openDocument(str((ROOT / CFG['predecessor']['document']).resolve()))
    for p in CFG['parts']:
        k = p['name']
        old = pred.getObject(k)
        if k in CFG['intended_changes'] and k not in CFG.get('moved_only', []):
            R.add('predecessor', f'{k}', (True, 'intended change (see design README)'))
        elif old is None:
            R.add('predecessor', f'{k}', (True, 'new in this version'))
        else:
            o = old.Shape.copy()
            o.translate(shapes[k].BoundBox.Center - o.BoundBox.Center)
            R.add('predecessor', f'{k} moved only', check_preserved(shapes[k], o, tol=MOVED_TOL))
    neg = pred.getObject('ScreenCover').Shape.copy()
    neg.translate(shapes['ScreenCover'].BoundBox.Center - neg.BoundBox.Center)
    R.add('predecessor', 'NEG cover scaled 1.02', check_preserved(shapes['ScreenCover'], neg.scaled(1.02, neg.BoundBox.Center), tol=MOVED_TOL), negative=True)
    removed = [n for n in CFG.get('removed', []) if doc.getObject(n) is not None]
    R.add('predecessor', 'removed parts absent', (not removed, f'still present: {removed}'))
    App.closeDocument(pred.Name)

    # 6. Fit with the real boards (ROCK 2F Radxa model, Firehat Rev 4 export)
    rk_p, fh_p = (ROOT / CFG['boards']['rock2f']).resolve(), (ROOT / CFG['boards']['firehat']).resolve()
    if rk_p.exists() and fh_p.exists():
        rk, fh = Part.read(str(rk_p)), Part.read(str(fh_p))
        rkb, fhb = place_boards(vs, rk, fh)
        R.add('fit', 'board files', (None, f'{rk_p.name} {sha256(rk_p)[:12]}, {fh_p.name} {sha256(fh_p)[:12]}'))
        R.add('fit', 'ROCK 2F × ShellBottom', check_fit(rkb, shapes['ShellBottom'], accepted=len(CFG['boards']['accepted_contacts'])))
        for k in ('ShellTop', 'ScreenCover', 'OledPanel'):
            R.add('fit', f'ROCK 2F × {k}', check_fit(rkb, shapes[k]))
        for k in ('ShellTop', 'ShellBottom', 'ScreenCover', 'OledPanel'):
            R.add('fit', f'Firehat × {k}', check_fit(fhb, shapes[k]))
        X1 = x0 + vs.BodyLength.Value
        front = App.BoundBox(x0 - 2, y0 - 2, -1, X1 + 2, y0 + vs.Wall.Value, 30)
        right = App.BoundBox(X1 - vs.Wall.Value, y0 - 2, -1, X1 + 2, 30, 30)
        left = App.BoundBox(x0 - 2, y0 - 2, -1, x0 + vs.Wall.Value, 30, 30)
        for bn, bs, walls in (('ROCK 2F', rkb, [front, right]), ('Firehat', fhb, [left])):
            for k in ('ShellTop', 'ShellBottom'):
                R.add('fit port clearance', f'{bn} connectors ↔ {k}', check_port_clearance(bs, shapes[k], walls))
        acts = [so for so in fhb.Solids if so.BoundBox.ZMax > H]
        d = min(so.distToShape(shapes['ShellTop'])[0] for so in acts) if acts else -1
        prot = max(so.BoundBox.ZMax for so in acts) - H if acts else 0
        R.add('fit', 'switch actuators through the top', (len(acts) == 3 and d >= 0.15 and 0.5 <= prot <= 2.0,
                                                          f'{len(acts)} actuators, protrusion {prot:.2f} mm, min clearance to holes {d:.3f} mm'))
        pins = max(so.BoundBox.ZMax for so in rkb.Solids if so.BoundBox.ZLength > 9)
        sock = min(so.BoundBox.ZMin for so in fhb.Solids if so.BoundBox.ZLength > 9 and so.BoundBox.XLength > 40)
        R.add('fit', '40-pin header engagement', (pins - sock >= 3.0, f'{pins - sock:.2f} mm (ROCK 2F pin tips z {pins:.2f}, Firehat socket bottom z {sock:.2f})'))
        _, lifted = place_boards(vs, rk, fh, firehat_lift=1.0)
        R.add('fit', 'NEG Firehat lifted 1 mm', check_fit(lifted, shapes['ShellTop']), negative=True)
    else:
        R.add('fit', 'board models', (False, 'missing: run hw/cad/boards/build_boards.py first'))

    # 7. Edit / restore
    brep = {k: hashlib.sha256(o.Shape.exportBrepToString().encode()).hexdigest() for k, o in parts.items()}
    edits = [('BodyLength', 1.0, ['ShellTop', 'ShellBottom']), ('BodyHeight', 0.5, ['ShellTop', 'ScreenCover']),
             ('Wall', 0.2, ['ShellTop', 'ShellBottom']), ('CornerR', -0.5, ['ShellTop', 'ShellBottom']),
             ('TopEdgeR', -0.5, ['ShellTop']), ('SeamZ', 0.5, ['ShellTop', 'ShellBottom']),
             ('PanelX', 0.3, ['ShellTop', 'ScreenCover', 'OledPanel']), ('ButtonX', 0.3, ['ShellTop']),
             ('RoundPortR', 0.2, ['ShellTop', 'ShellBottom']), ('FloorVentPitch', 0.5, ['ShellBottom'])]

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

    # 8. Tooltips state current values
    stale = [n for n in vs.PropertiesList if vs.getGroupOfProperty(n) not in ('', 'Base') and n != 'ExposedParameters' and not check_tooltip(vs, n)[0]]
    R.add('tooltips', f'{len(vs.PropertiesList)} properties', (not stale, f'stale: {stale}'))
    vs.setDocumentationOfProperty('WindowR', 'stale. Current value: 9 mm')
    R.add('tooltips', 'NEG stale WindowR tooltip', check_tooltip(vs, 'WindowR'), negative=True)

    # 9. Exports (only if present)
    for k, s in shapes.items():
        step = ROOT / 'exports' / f'equip-1-{CFG["version"]}-{k}.step'
        if step.exists():
            R.add('export STEP', step.name, check_export(s, Part.read(str(step))))
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
        f'# {CFG["version"]} validation', '',
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
        'Fit checks use Radxa\'s ROCK 2F v1.0 model and the Firehat Rev 4 KiCad export (hw/cad/boards); neither is a measured board.',
        '', f'Details: `.build/verify-{digest[:12]}.json` (regenerable; rerun `scripts/verify.py`).', ''
    ]
    (ROOT / 'reports').mkdir(exist_ok=True)
    (ROOT / 'reports' / 'validation.md').write_text('\n'.join(lines))
    print(f'VERIFY DONE: {len(real) - len(fails)}/{len(real)} pass, {len(unproven)} unproven negative controls, sha256 {digest}')


main()
