"""Reopen the saved equip-1-V0.1.4.FCStd and run every check, including fit with the real boards. Never saves.

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
EXPORT_REL = 2e-5         # |directed difference| / part volume, native vs STEP read-back (volume-integration noise: ShellBottom
                          # measured 1.5e-5 with an empty boolean difference, from trimmed roll/toroid/sphere faces)
FUZZY = 1e-4             # mm, boolean fuzzy value for near-coincident faces
RAYS = 3                  # wall-thickness samples per face direction (RAYS² per face)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def directed(a, b):
    # fuzzy common: plain OCC booleans mis-handle the coincident faces of near-identical solids
    c = a.common(b, FUZZY).Volume
    return a.Volume - c, b.Volume - c


def bbox(s):
    bb = s.optimalBoundingBox(False, False)   # exact; BoundBox is loose around curved boolean faces (e.g. the radial corner slots)
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
FPC_SLOT_MARGIN = 0.3     # mm; min slot clearance each side of the FPC
FPC_ALIGN_TOL = 0.1       # mm; FPC centre vs FPC2 centre (a 12 mm FPC cannot shift sideways)


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


def fpc_path_length(vs):
    """Independent re-derivation of the FPC centre line (glass edge -> FPC2 entry) from the parameters."""
    v = lambda n: getattr(vs, n).Value
    t, r = v('FpcThickness'), v('FpcBendR') + v('FpcThickness') / 2
    yv = (v('SlotBackY') + v('SlotFrontY')) / 2
    zf = v('TowerBottomZ') + v('PanelFold') + v('PanelCapThickness') - t / 2
    flat = v('PanelY') - v('PanelWidth') / 2 - (yv + r)
    under = (yv - r) - v('Fpc2EntryY')
    return flat, under, flat + math.pi * r + (zf - r - v('Fpc2CableZ') - r) + under


def check_fpc(board_shape, fpc, vs, panel_x):
    """OLED FPC: parameters match the board, FPC aligned with FPC2, fits the slot, fits the shortest FPC."""
    v = lambda n: getattr(vs, n).Value
    board = max(board_shape.Solids, key=lambda so: so.BoundBox.XLength * so.BoundBox.YLength if so.BoundBox.ZLength < 2 else 0)
    top = max(board.Faces, key=lambda f: f.Area)
    slots = [w.BoundBox for w in top.Wires if abs(w.BoundBox.XLength - 16.75) < 0.05 and abs(w.BoundBox.YLength - 2.25) < 0.05]
    bottom = board.BoundBox.ZMin
    fpc2 = [so.BoundBox for so in board_shape.Solids if so.BoundBox.ZMax <= bottom + 0.05
            and 20 < so.BoundBox.XLength < 23 and 5 < so.BoundBox.YLength < 7]
    if len(slots) != 1 or len(fpc2) != 1:
        return False, f'expected one 16.75 x 2.25 mm slot and one FPC2 body, found {len(slots)} / {len(fpc2)}'
    sl, c = slots[0], fpc2[0]
    flat, under, length = fpc_path_length(vs)
    need = length + v('FpcContactLength')
    margin = min(panel_x - v('FpcWidth') / 2 - sl.XMin, sl.XMax - (panel_x + v('FpcWidth') / 2))
    align = panel_x - c.Center.x
    hits = [h for h in board_interference(board_shape, fpc) if h[0] > FIT_INTERFERENCE]
    ok = (abs(sl.YMax - v('SlotBackY')) <= 0.02 and abs(sl.YMin - v('SlotFrontY')) <= 0.02 and abs(c.YMax - v('Fpc2EntryY')) <= 0.02
          and abs(align) <= FPC_ALIGN_TOL and margin >= FPC_SLOT_MARGIN and flat >= 0 and under >= 0
          and need <= v('FpcLength') - v('FpcLengthTol') + 0.01 and not hits)
    return ok, (f'slot {sl.YMin:.3f}..{sl.YMax:.3f} (params {v("SlotFrontY"):.3f}..{v("SlotBackY"):.3f}), FPC2 entry {c.YMax:.3f} (param {v("Fpc2EntryY"):.3f}); '
                f'FPC vs FPC2 centre {align:+.2f} mm, slot margin {margin:.2f} mm, flat {flat:.2f} / under-board {under:.2f} mm; '
                f'needs {need:.3f} mm, shortest FPC {v("FpcLength") - v("FpcLengthTol"):.1f} mm; board hits {hits}')


def board_interference(board, part):
    hits = []
    for so in board.Solids:
        if so.BoundBox.intersect(part.BoundBox):
            v = so.common(part).Volume
            if v > FIT_INTERFERENCE:
                b = so.BoundBox
                hits.append((round(v, 3), [round(c, 1) for c in (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)]))
    return hits


def check_locators(top, vs, shift=0.0):
    """Posts sit PanelLocatorGap from the glass edges; the stop ring covers the bare glass margin but not the polarizer."""
    v = lambda n: getattr(vs, n).Value
    gx0, gy0 = v('PanelX') - v('PanelLength') / 2 + shift, v('PanelY') - v('PanelWidth') / 2
    L, W = v('PanelLength'), v('PanelWidth')
    gtop = v('TowerBottomZ') + v('PanelFold') + v('PanelThickness') - v('PolarizerThickness')
    z0, z1 = gtop - v('PanelLocatorDepth') + 0.05, gtop - 0.05
    band = lambda e: top.common(Part.makeBox(L + 2 * e, W + 2 * e, z1 - z0, App.Vector(gx0 - e, gy0 - e, z0))).Volume
    inside, outside = band(v('PanelLocatorGap') - 0.02), band(v('PanelLocatorGap') + 0.1)
    margin = top.common(Part.makeBox(L, W, 0.05, App.Vector(gx0, gy0, gtop + 0.01))).Volume
    pol = top.common(Part.makeBox(v('PolarizerLength') + 0.1, v('PolarizerWidth') + 0.1, v('PolarizerThickness'),
                                  App.Vector(gx0 + v('PolarizerOffsetX') - 0.05, gy0 + W - v('PolarizerOffsetY') - v('PolarizerWidth') - 0.05, gtop))).Volume
    ok = inside < VOL_EPS and outside > 0.05 and margin > 0.5 and pol < VOL_EPS
    return ok, f'material inside gap {inside:.4f} mm³, posts at gap {outside:.3f} mm³, ring on glass margin {margin:.3f} mm³, over polarizer {pol:.4f} mm³'


def check_leds(board, vs):
    """Each LED light window is centred on a Firehat LED (SK6812-EC20 body); the skin over it is covered by min wall."""
    v = lambda n: getattr(vs, n).Value
    zb, rows = v('TowerBottomZ'), []
    for i in (1, 2, 3):
        x, y = v(f'LedLight{i}X'), v('LedLightY')
        near = [so.BoundBox for so in board.Solids if abs(so.BoundBox.ZMin - zb) < 0.2 and 1.6 < so.BoundBox.XLength < 2.6 and 1.6 < so.BoundBox.YLength < 2.6
                and abs(so.BoundBox.Center.x - x) < 1.5 and abs(so.BoundBox.Center.y - y) < 1.5]
        if not near:
            return False, f'LED{i}: no LED body found near ({x:.2f}, {y:.2f})'
        c = max(near, key=lambda b: b.XLength * b.YLength).Center
        rows.append((i, math.hypot(c.x - x, c.y - y)))
    off = max(d for _, d in rows)
    return off <= 0.15, 'window to LED centre ' + ', '.join(f'LED{i} {d:.2f} mm' for i, d in rows)


HEATSINK = (14.0, 14.0, 4.25)   # finned heatsink glued on the RK3528A, 14 x 14 x 4 mm + 0.25 mm tape (user, 2026-11-01); not in the Radxa model


def check_heatsink(rock, firehat, min_gap=1.0):
    """The glued heatsink on the ROCK 2F SoC clears the Firehat (VT6315N sits almost above it) by min_gap."""
    soc = max((so.BoundBox for so in rock.Solids if 12 < so.BoundBox.XLength < 15 and 12 < so.BoundBox.YLength < 15 and so.BoundBox.ZLength < 2),
              key=lambda b: b.XLength * b.YLength)
    hs = Part.makeBox(HEATSINK[0], HEATSINK[1], HEATSINK[2], App.Vector(soc.Center.x - HEATSINK[0] / 2, soc.Center.y - HEATSINK[1] / 2, soc.ZMax))
    zone = App.BoundBox(hs.BoundBox.XMin - 3, hs.BoundBox.YMin - 3, hs.BoundBox.ZMax, hs.BoundBox.XMax + 3, hs.BoundBox.YMax + 3, 30)
    gap = min((hs.distToShape(so)[0] for so in firehat.Solids if so.BoundBox.intersect(zone)), default=99)
    return gap >= min_gap, f'SoC at ({soc.Center.x:.1f}, {soc.Center.y:.1f}), heatsink top z {hs.BoundBox.ZMax:.2f}, clearance to the Firehat {gap:.2f} mm (want {min_gap})'


def check_spreader(rock, sheet, pad, vs):
    """Aluminium sheet clears every ROCK 2F underside part by >= 0.3 mm; the gap pad touches the PCB underside and the parts
    under the SoC press into it by <= 0.7 mm (soft pad, 2 mm compressed to 1.6)."""
    pcb = max(rock.Solids, key=lambda so: so.BoundBox.XLength * so.BoundBox.YLength if so.BoundBox.ZLength < 2 else 0)
    under = [so for so in rock.Solids if so is not pcb and so.BoundBox.ZMax <= pcb.BoundBox.ZMin + 0.3 and so.BoundBox.ZMin < pcb.BoundBox.ZMin]
    zone = sheet.BoundBox
    gap = min((sheet.distToShape(so)[0] for so in under if so.BoundBox.ZMin < zone.ZMax + 1), default=99)
    pb = pad.BoundBox
    press = [pb.ZMax - so.BoundBox.ZMin for so in under if so.BoundBox.intersect(pb) and pad.common(so).Volume > 1e-6]
    contact = pcb.BoundBox.ZMin - pb.ZMax
    ok = gap >= 0.3 and abs(contact) < 0.01 and max(press, default=0) <= 0.7
    return ok, f'sheet to underside parts {gap:.2f} mm; pad to PCB {contact:.3f} mm, {len(press)} parts press in up to {max(press, default=0):.2f} mm'


def check_spacers(rock, firehat, spacers):
    """Each corner spacer sits on the ROCK 2F top and under the Firehat (gap <= 0.05 mm both ends) and hits no part of
    either board: the screw stack is clamped, not floating."""
    pcb = lambda sh: max(sh.Solids, key=lambda so: so.BoundBox.XLength * so.BoundBox.YLength if so.BoundBox.ZLength < 2 else 0).BoundBox
    rz, fz = pcb(rock).ZMax, pcb(firehat).ZMin
    rows = []
    for k, sp in spacers.items():
        bb = sp.BoundBox
        hit = sum(sp.common(so).Volume for sh in (rock, firehat) for so in sh.Solids if so.BoundBox.intersect(bb))
        rows.append((k, bb.ZMin - rz, fz - bb.ZMax, hit))
    ok = all(abs(a) <= 0.05 and abs(b) <= 0.05 and h < FIT_INTERFERENCE for _, a, b, h in rows)
    return ok, '; '.join(f'{k}: ROCK {a:+.3f} / Firehat {b:+.3f} mm, overlap {h:.4f} mm³' for k, a, b, h in rows)


def check_mount(mount, bottom, top, vs):
    """Clip mount: no contact with the case, hugs it within MountGap + 0.05, and the two pins and the tongue reach into the
    insets / slot (their tips are inside the case outline)."""
    gap = min(mount.distToShape(bottom)[0], mount.distToShape(top)[0])
    y0, y1 = vs.BodyY0.Value, vs.BodyY0.Value + vs.BodyWidth.Value
    front = mount.common(Part.makeBox(200, 2, 30, App.Vector(-100, y0 + 0.2, -10))).Volume   # pins past the front face
    back = mount.common(Part.makeBox(200, 2, 30, App.Vector(-100, y1 - 2.2, -10))).Volume     # tongue past the back face
    ok = 0.1 <= gap <= vs.MountGap.Value + 0.05 and front > 0.5 and back > 3
    return ok, f'gap to the case {gap:.3f} mm; pins {front:.2f} mm³ / tongue {back:.2f} mm³ inside the case outline'


def check_button(board, cap, top, vs, out):
    """Cap rests CapRestGap above its switch actuator, sticks out ButtonProtrusion, clears the shell by the flange play,
    and its flange is larger than the hole (retained)."""
    v = lambda n: getattr(vs, n).Value
    bb = cap.BoundBox
    zone = App.BoundBox(bb.XMin - 0.5, bb.YMin - 0.5, bb.ZMin - 2, bb.XMax + 0.5, bb.YMax + 0.5, bb.ZMax)
    near = [so for so in board.Solids if so.BoundBox.intersect(zone)]
    rest = min((so.distToShape(cap)[0] for so in near), default=-1)
    prot = bb.ZMax - v('BodyHeight')
    gap = cap.distToShape(top)[0]
    want = min(out.CapSideClearance.Value, v('FlangePlay'), v('CapChannelMargin'))
    acts = [so.BoundBox for so in near if abs(so.BoundBox.ZMax - v('ActuatorTopZ')) < 0.05 and so.BoundBox.XLength < 3]
    off = min((math.hypot(a.Center.x - bb.Center.x, a.Center.y - bb.Center.y) for a in acts), default=99)   # switch actuator under the cap centre
    ok = abs(rest - v('CapRestGap')) < 0.02 and abs(prot - out.ButtonProtrusion.Value) < 0.01 and abs(gap - want) < 0.01 and v('FlangeSize') > v('ButtonHoleSize') and off < 0.05
    return ok, f'rest gap {rest:.3f} mm (want {v("CapRestGap"):.2f}), switch {off:.3f} mm off the cap centre, {prot:.2f} mm above the top, to the shell {gap:.3f} mm (want {want:.2f}), flange {v("FlangeSize"):.1f} > hole {v("ButtonHoleSize"):.1f}'


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
    expected = {'ShellTop': env[:2] + [vs.SeamZ.Value] + env[3:], 'ShellBottom': env[:5] + [max(vs.LipTopZ.Value, vs.FwSplitZ.Value + vs.LipTopZ.Value - vs.SeamZ.Value)]}   # FireWire split tab + lip
    wcx, wcy, cc = vs.WindowCX.Value, vs.WindowCY.Value, vs.CoverClearance.Value
    expected['ScreenCover'] = [wcx - vs.WindowLength.Value / 2 + cc, wcy - vs.WindowWidth.Value / 2 + cc, vs.BodyHeight.Value - vs.CoverThickness.Value,
                               wcx + vs.WindowLength.Value / 2 - cc, wcy + vs.WindowWidth.Value / 2 - cc, vs.BodyHeight.Value]
    pz = vs.TowerBottomZ.Value + vs.PanelFold.Value
    expected['OledPanel'] = [vs.PanelX.Value - vs.PanelLength.Value / 2, vs.PanelY.Value - vs.PanelWidth.Value / 2, pz,
                             vs.PanelX.Value + vs.PanelLength.Value / 2, vs.PanelY.Value + vs.PanelWidth.Value / 2, pz + vs.PanelThickness.Value]
    gx0, gy1, face = vs.PanelX.Value - vs.PanelLength.Value / 2, vs.PanelY.Value + vs.PanelWidth.Value / 2, pz + vs.PanelThickness.Value
    expected['OledViewArea'] = [gx0 + vs.ViewAreaOffsetX.Value, gy1 - vs.ViewAreaEdgeY.Value - vs.ViewAreaWidth.Value, face,
                                gx0 + vs.ViewAreaOffsetX.Value + vs.ViewAreaLength.Value, gy1 - vs.ViewAreaEdgeY.Value, face + 0.01]
    expected['OledActiveArea'] = [gx0 + vs.ActiveAreaOffsetX.Value, gy1 - vs.ActiveAreaEdgeY.Value - vs.ActiveAreaWidth.Value, face + 0.01,
                                  gx0 + vs.ActiveAreaOffsetX.Value + vs.ActiveAreaLength.Value, gy1 - vs.ActiveAreaEdgeY.Value, face + 0.02]
    for k, s in shapes.items():
        if k in expected:
            R.add('solid+bbox', k, check_solid(s, expected[k]))
        else:   # OledFpc (bent), contacts, glass jig: checked against the board in section 6
            R.add('solid+bbox', k, (len(s.Solids) == 1 and s.isValid() and s.Solids[0].isClosed(), f'solids={len(s.Solids)} valid={s.isValid()} (no box check)'))
    R.add('solid+bbox', 'NEG two disjoint boxes', check_solid(Part.makeCompound([Part.makeBox(1, 1, 1), Part.makeBox(1, 1, 1, App.Vector(3, 0, 0))]), [0, 0, 0, 4, 1, 1]), negative=True)

    # 2. Interference + clearances between our parts
    tools = [p['name'] for p in CFG['parts'] if p.get('group') == 'tool']   # used without the case, never assembled with it
    names = [k for k in shapes if k not in tools]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            R.add('no interference', f'{a} × {b}', check_no_interference(shapes[a], shapes[b]))
    R.add('no interference', 'NEG overlapping boxes', check_no_interference(Part.makeBox(2, 2, 2), Part.makeBox(2, 2, 2, App.Vector(1, 1, 1))), negative=True)
    R.add('clearance', 'ScreenCover ↔ ShellTop', check_clearance(shapes['ScreenCover'], shapes['ShellTop'], min(vs.CoverClearance.Value, out.ScreenCoverFloorGap.Value)))
    lip = shapes['ShellBottom'].common(Part.makeBox(200, 200, 10, App.Vector(-100, -100, vs.SeamZ.Value + 0.01)))
    R.add('clearance', 'lip ↔ groove', check_clearance(lip, shapes['ShellTop'], min(out.SeamLateralClearance.Value, out.SeamVerticalClearance.Value)))
    R.add('clearance', 'OledPanel ↔ ScreenCover', check_clearance(shapes['OledPanel'], shapes['ScreenCover'], out.PanelToCoverGap.Value))
    R.add('clearance', 'OledPanel ↔ ShellTop', check_clearance(shapes['OledPanel'], shapes['ShellTop'], 0.0))  # the glass rests on the stop ring
    R.add('OLED locators', 'posts and stop ring', check_locators(shapes['ShellTop'], vs))
    R.add('shoe mount', 'clips into the insets and the back slot', check_mount(shapes['ShoeMount'], shapes['ShellBottom'], shapes['ShellTop'], vs))
    R.add('OLED locators', 'NEG panel moved 0.3 mm', check_locators(shapes['ShellTop'], vs, shift=0.3), negative=True)
    for k in ('OledFpc', 'OledFpcContacts'):
        R.add('no interference', f'GlassJig × {k}', check_no_interference(shapes['GlassJig'], shapes[k]))
    R.add('clearance', 'OledPanel ↔ GlassJig pocket', check_clearance(shapes['OledPanel'], shapes['GlassJig'], vs.JigPocketGap.Value))
    R.add('clearance', 'NEG cover moved 0.2 mm', check_clearance(shapes['ScreenCover'].translated(App.Vector(0.2, 0, 0)), shapes['ShellTop'], min(vs.CoverClearance.Value, out.ScreenCoverFloorGap.Value)), negative=True)

    # 3. Minimum wall / skin thickness
    for k in ('ShellTop', 'ShellBottom', 'ScreenCover', 'HeatSpreader', 'Spacer1', 'Spacer2', 'ShoeMount', 'GlassJig'):
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
        for c in (cut.Tool.Shapes if hasattr(cut.Tool, 'Shapes') else [cut.Tool]):
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
        for i in (1, 2, 3):
            R.add('fit', f'Button{i} cap on its switch', check_button(fhb, shapes[f'Button{i}'], shapes['ShellTop'], vs, out))
            R.add('fit', f'Firehat × Button{i}', check_fit(fhb, shapes[f'Button{i}']))
        R.add('fit', 'NEG Button1 lifted 0.3 mm', check_button(fhb, shapes['Button1'].translated(App.Vector(0, 0, 0.3)), shapes['ShellTop'], vs, out), negative=True)
        pins = max(so.BoundBox.ZMax for so in rkb.Solids if so.BoundBox.ZLength > 9)
        sock = min(so.BoundBox.ZMin for so in fhb.Solids if so.BoundBox.ZLength > 9 and so.BoundBox.XLength > 40)
        R.add('fit', '40-pin header engagement', (pins - sock >= 3.0, f'{pins - sock:.2f} mm (ROCK 2F pin tips z {pins:.2f}, Firehat socket bottom z {sock:.2f})'))
        R.add('fit', 'LED light windows over the LEDs', check_leds(fhb, vs))
        R.add('fit', 'ROCK 2F heatsink clears the Firehat', check_heatsink(rkb, fhb))
        R.add('fit', 'heat spreader + thermal pad under the ROCK 2F', check_spreader(rkb, shapes['HeatSpreader'], shapes['ThermalPad'], vs))
        sp = {k: shapes[k] for k in ('Spacer1', 'Spacer2')}
        R.add('fit', 'corner spacers clamp the boards', check_spacers(rkb, fhb, sp))
        R.add('fit', 'NEG spacer 0.3 mm short', check_spacers(rkb, fhb, {'Spacer1': sp['Spacer1'].common(Part.makeBox(200, 200, sp['Spacer1'].BoundBox.ZMax - 0.3, App.Vector(-100, -100, 0)))}), negative=True)
        R.add('fit', 'NEG heat spreader 0.3 mm thicker', check_spreader(rkb, shapes['HeatSpreader'].translated(App.Vector(0, 0, 0.3)), shapes['ThermalPad'], vs), negative=True)
        R.add('fit', 'NEG heatsink 5.6 mm taller', check_heatsink(rkb, fhb, min_gap=1.0 + 5.6), negative=True)
        R.add('fit', 'OLED FPC through the slot into FPC2', check_fpc(fhb, shapes['OledFpc'], vs, vs.PanelX.Value))
        R.add('fit', 'NEG FPC with panel moved 1 mm in X', check_fpc(fhb, shapes['OledFpc'], vs, vs.PanelX.Value + 1.0), negative=True)
        for k in ('OledFpc',):
            R.add('fit', f'ROCK 2F × {k}', check_fit(rkb, shapes[k]))
        R.add('fit', 'Firehat × GlassJig (pins in the mounting holes)', check_fit(fhb, shapes['GlassJig']))
        R.add('fit', 'NEG GlassJig shifted 0.3 mm', check_fit(fhb, shapes['GlassJig'].translated(App.Vector(0.3, 0, 0))), negative=True)
        _, lifted = place_boards(vs, rk, fh, firehat_lift=1.0)
        R.add('fit', 'NEG Firehat lifted 1 mm', check_fit(lifted, shapes['ShellTop']), negative=True)
    else:
        R.add('fit', 'board models', (False, 'missing: run hw/cad/boards/build_boards.py first'))

    # 7. Edit / restore
    brep = {k: hashlib.sha256(o.Shape.exportBrepToString().encode()).hexdigest() for k, o in parts.items()}
    edits = [('BodyLength', 1.0, ['ShellTop', 'ShellBottom']), ('BodyHeight', 0.5, ['ShellTop', 'ScreenCover']),
             ('Wall', 0.2, ['ShellTop', 'ShellBottom']), ('InnerBottomR', -0.3, ['ShellBottom']),
             ('TopEdgeR', 0.5, ['ShellTop']), ('InnerTopR', -0.3, ['ShellTop']), ('SeamZ', 0.5, ['ShellTop', 'ShellBottom']),
             ('ActiveAreaEdgeY', 0.3, ['ShellTop', 'OledPanel']), ('ButtonX', 0.3, ['ShellTop']),
             ('RoundPortR', 0.2, ['ShellTop', 'ShellBottom']),
             ('PanelLocatorGap', 0.1, ['ShellTop']), ('LedLightSkin', 0.1, ['ShellTop']), ('SpreaderGap', 0.05, ['HeatSpreader']), ('SpacerFinT', 0.1, ['Spacer1', 'Spacer2']), ('MountArmT', 0.1, ['ShoeMount']), ('FwTabGap', 0.05, ['ShellTop']), ('SpreaderBossGap', 0.1, ['ShellBottom', 'HeatSpreader']), ('JigPocketGap', 0.1, ['GlassJig'])]

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
