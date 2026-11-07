"""One-time migration: create equip-1-V0.1.5.FCStd from the saved V0.1.4 file.

Every parameter value is read from the predecessor's `01 · Parameters` VarSet (SHA256-pinned),
then the REMOVED / CHANGED / ADDED lists below are applied and the feature tree is regenerated.
NOT a reset command: refuses if the predecessor changed or the output exists
(EQUIP1_CAD_REPLACE=1 backs the existing file up to .build/backup/ and rebuilds).

V0.1.5 = V0.1.4 + active cooling (user request 2026-11-02):
- Sunon UB3H3-500 MagLev blower (17 x 17 x 3 mm, 3 V from the Firehat 3.3 V rail, 6.5 l/min, 40 Pa, 20.4 dB(A) @ 1 m;
  datasheet D01000941F-01) lying flat between the boards in the front-left free zone, intake up, outlet edge against
  the left wall. Both boards cover the whole case outline, so the gap between them (z 4.8-16.5) is the only place for
  it; measured free space: ROCK 2F part at z 8.7 below, Firehat parts at z 14.4 above, PCIe FPC1 at the front.
- Cradle = two C-rails gripping the blower edges + an outlet frame against the wall, carried by an arm on corner
  Spacer 1 (the blower goes in with the board stack: the Firehat covers the footprint, so a lid bracket cannot reach).
- Exhaust window through both shells over the blower outlet: it crosses the FireWire split flank, so it runs from below
  the flank to above the groove (no slivers); the frame closes the window above the outlet (no short circuit).
- Inlet slots in the top-shell right wall above the ROCK 2F USB-A ports: fresh air crosses the boards to the blower.
- Board side (user routes): JST SUR 0.8 mm connector on the Firehat + a GPIO-switched 3.3 V load switch (on/off only,
  Sunon: no PWM on the supply); tach (yellow) optional to a GPIO.

Run headless:   FreeCADCmd scripts/build.py
"""
import hashlib
import json
import math
import os
import re
import shutil
import time
from pathlib import Path

import FreeCAD as App
import Part  # noqa: F401  (registers Part feature types)

ROOT = Path(os.environ.get('EQUIP1_CAD_ROOT') or Path(__file__).resolve().parents[1])
FCSTD = ROOT / 'equip-1-V0.1.5.FCStd'
PREDECESSOR = ROOT.parent / 'V0.1.4' / 'equip-1-V0.1.4.FCStd'
PREDECESSOR_SHA = '9a07d0868b869bd427e2b5d8d060d508f7ba38a219749b7cd653c1f535b11bf6'

REMOVED = []

CHANGED = {  # FPC2 is now the JUSHUO AFC07-S30FCA-00 (customer drawing + JLC model, 2026-11-06)
    'Fpc2EntryY': (-25.331, 'FPC2 entry: JUSHUO latch face (KiCad y 90.731)'),
    'Fpc2CableZ': (15.40, 'FPC centre height inside FPC2: 0.3 mm contact end just below the lower contact bump (z 15.58)'),
}

ADDED = [  # (group, name, value_mm, signed, description); blower: Sunon spec D01000941F-01 (UB3H3-500)
    ('OLED FPC', 'Fpc2InsertDepth', 2.80, False, 'FPC end inside FPC2, latch face to stop (JUSHUO drawing: 2.7 from the housing front + 0.1 latch overhang)'),
    ('Active cooling', 'BlowerSize', 17.00, False, 'Sunon UB3H3-500 blower outline (17 +/- 0.3 mm square; 3 V, 6.5 l/min, 40 Pa, 20.4 dB(A) @ 1 m)'),
    ('Active cooling', 'BlowerT', 3.00, False, 'Blower body thickness at the edges (3 +0.5/-0; the intake guard in the middle reaches 3.8)'),
    ('Active cooling', 'BlowerCX', -11.62, True, 'Blower centre X (outlet edge 0.2 mm from the cradle outlet frame, by expression)'),
    ('Active cooling', 'BlowerCY', -9.10, True, 'Blower centre Y: rails clear the Firehat PCIe FPC1 (front, z 12.0) and the FireWire J2 (back, z 7.7)'),
    ('Active cooling', 'BlowerZ0', 9.70, False, 'Blower underside: the cradle floor lip clears the ROCK 2F left-edge part (z 8.7) by 0.2 mm'),
    ('Active cooling', 'BlowerSlotH', 3.60, False, 'Cradle rail inner height (edge thickness 3 +0.5 mm)'),
    ('Active cooling', 'BlowerPlay', 0.20, False, 'Cradle side play around the blower'),
    ('Active cooling', 'CradleT', 0.80, False, 'Cradle rail web / lip / frame thickness (>= MinWall)'),
    ('Active cooling', 'CradleLip', 1.20, False, 'Rail lips over the blower faces (outside the intake circle)'),
    ('Active cooling', 'CradleWallGap', 0.20, False, 'Cradle outlet frame and arm to the left inner wall'),
    ('Active cooling', 'CradleArmW', 2.80, False, 'Arm width from Spacer 1 along the left wall to the front rail'),
    ('Active cooling', 'ExhaustInset', 0.60, False, 'Exhaust window ends inside the blower outlet edge'),
    ('Active cooling', 'ExhaustZ0', 9.00, False, 'Exhaust window bottom: below the FireWire split flank over its whole length (no sliver)'),
    ('Active cooling', 'ExhaustZ1', 14.30, False, 'Exhaust window top: above the split groove top over its whole length (no sliver)'),
    ('Active cooling', 'InletY0', -19.00, True, 'Right-wall inlet slots from Y'),
    ('Active cooling', 'InletY1', 12.00, True, 'Right-wall inlet slots to Y'),
    ('Active cooling', 'InletZ0', 12.90, False, 'Inlet slot bottom: >= 0.6 mm above the USB-A openings'),
    ('Active cooling', 'InletZ1', 15.90, False, 'Inlet slot top: under the Firehat (z 16.49)'),
    ('Active cooling', 'InletSlotW', 1.50, False, 'Inlet slot width'),
    ('Active cooling', 'InletRibW', 1.00, False, 'Rib between inlet slots'),
]
FPC_R = '($FpcBendR + $FpcThickness / 2)'                        # FPC centre-line bend radius
FPC_YV = '(($SlotBackY + $SlotFrontY) / 2)'                       # FPC centre line down the slot (slot centre)
EXPRESSIONS = {'ActiveAreaOffsetY': '$PanelWidth / 2 - $ActiveAreaEdgeY - $ActiveAreaWidth / 2',
               'PanelY': '$BodyY0 + $BodyWidth / 2 - $ActiveAreaOffsetY',   # active area centred front-to-back
               'WindowCX': '$PanelX', 'WindowCY': '$PanelY + $ActiveAreaOffsetY',
               'SpreaderWallGap': '$InnerBottomR + 0.2 mm', 'MountFrontTopZ': '$LedWinZ1 + 1 mm', 'MountBackTopZ': '$BackSlotZ1 + 1 mm',
               'UsbX0': '$UsbConnX0 - $UsbClearance', 'UsbX1': '$UsbConnX1 + $UsbClearance', 'UsbZ0': '$UsbConnZ0 - $UsbClearance',
               'UsbZ1': '$UsbConnZ1 + $UsbClearance', 'UsbRTop': '$UsbCornerR', 'UsbRBottom': '$UsbCornerR',
               'BlowerCX': '$BodyX0 + $Wall + $CradleWallGap + $CradleT + $BlowerPlay + $BlowerSize / 2',}


# Firehat J2 (FireWire 400, 6-pin) silhouette through the left wall (union of its sections every 0.05 mm from the outer face
# to 1 mm inside, where the opening cut ends), measured 2026-11-01 from the Firehat Rev 5 board model placed as in verify.py;
# case coordinates (y, z) in mm, arcs discretised to 0.004 mm. The opening is this outline offset by FwClearance; verify.py
# checks the clearance on the real model.
J2_SILHOUETTE = [(14.285, 10.655), (14.388, 10.669), (14.483, 10.712), (14.563, 10.778), (14.622, 10.865), (14.654,
                 10.964), (14.660, 11.030), (14.660, 12.780), (14.646, 12.883), (14.603, 12.978), (14.537, 13.058),
                 (14.450, 13.117), (14.351, 13.149), (14.285, 13.155), (13.960, 13.155), (13.960, 13.299), (13.940,
                 13.441), (13.918, 13.506), (13.831, 13.645), (13.812, 13.666), (11.710, 15.405), (11.710, 15.730),
                 (11.696, 15.833), (11.653, 15.928), (11.587, 16.008), (11.500, 16.067), (11.401, 16.099), (11.335,
                 16.105), (3.085, 16.105), (2.982, 16.091), (2.887, 16.048), (2.807, 15.982), (2.748, 15.895), (2.716,
                 15.796), (2.710, 15.730), (2.710, 15.405), (2.260, 15.405), (2.153, 15.391), (2.055, 15.348), (1.971,
                 15.281), (1.910, 15.199), (1.910, 14.613), (1.909, 14.581), (1.900, 14.562), (1.878, 14.562), (1.535,
                 14.555), (1.432, 14.541), (1.337, 14.498), (1.257, 14.432), (1.198, 14.345), (1.166, 14.246), (1.160,
                 14.180), (1.160, 9.630), (1.174, 9.527), (1.217, 9.432), (1.283, 9.352), (1.370, 9.293), (1.469,
                 9.261), (1.535, 9.255), (1.878, 9.255), (1.900, 9.248), (1.909, 9.229), (1.910, 9.197), (1.910,
                 8.611), (1.974, 8.525), (2.059, 8.459), (2.159, 8.418), (2.260, 8.405), (2.710, 8.405), (2.710,
                 8.080), (2.724, 7.977), (2.767, 7.882), (2.833, 7.802), (2.920, 7.743), (3.019, 7.711), (3.085,
                 7.705), (11.335, 7.705), (11.438, 7.719), (11.533, 7.762), (11.613, 7.828), (11.672, 7.915), (11.704,
                 8.014), (11.710, 8.080), (11.710, 8.405), (13.812, 10.144), (13.831, 10.165), (13.910, 10.288),
                 (13.919, 10.307), (13.940, 10.369), (13.960, 10.511), (13.960, 10.655)]

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guard():
    got = sha256(PREDECESSOR)
    if got != PREDECESSOR_SHA:
        raise SystemExit(f'refusing: predecessor SHA256 {got} != pinned {PREDECESSOR_SHA}')
    if FCSTD.exists():
        if os.environ.get('EQUIP1_CAD_REPLACE') != '1':
            raise SystemExit(f'refusing: {FCSTD.name} exists (migration runs once; EQUIP1_CAD_REPLACE=1 backs it up and rebuilds)')
        backup = ROOT / '.build' / 'backup'
        backup.mkdir(parents=True, exist_ok=True)
        shutil.move(str(FCSTD), backup / f'{FCSTD.stem}-{time.strftime("%Y%m%d-%H%M%S")}.FCStd')


def migrate_params():
    """Predecessor VarSet values + REMOVED/CHANGED/ADDED -> [(group, name, value, signed, desc)]."""
    doc = App.openDocument(str(PREDECESSOR))
    vs = doc.getObject('Parameters')
    params = []
    for name in vs.PropertiesList:
        group = vs.getGroupOfProperty(name)
        if group in ('', 'Base') or name == 'ExposedParameters' or name in REMOVED:
            continue
        desc = vs.getDocumentationOfProperty(name).split('. Current value:')[0]
        value = getattr(vs, name).Value
        if name in CHANGED:
            value, new_desc = CHANGED[name]
            desc = new_desc or desc
        params.append((group, name, value, vs.getTypeIdOfProperty(name) == 'App::PropertyDistance', desc))
    App.closeDocument(doc.Name)
    missing = [n for n in list(CHANGED) + REMOVED if n not in vs_names(params) and n not in REMOVED]
    if missing:
        raise SystemExit(f'CHANGED names not in predecessor: {missing}')
    return params + ADDED


def vs_names(params):
    return {p[1] for p in params}


def X(s):
    """Expand $Name -> Parameters.Name and @Name -> Preview.Name."""
    return re.sub(r'@(\w+)', r'Preview.\1', re.sub(r'\$(\w+)', r'Parameters.\1', s))


class Builder:
    def __init__(self, doc):
        self.doc = doc

    def _hide(self, o, label):
        o.Label = label
        o.Visibility = False
        return o

    def _set(self, o, prop, expr):
        o.setExpression(prop, X(expr))

    def box(self, label, x0, x1, y0, y1, z0, z1):
        o = self._hide(self.doc.addObject('Part::Box', 'Box'), label)
        for prop, a, b in (('Length', x0, x1), ('Width', y0, y1), ('Height', z0, z1)):
            self._set(o, prop, f'({b}) - ({a})')
        for ax, a in (('x', x0), ('y', y0), ('z', z0)):
            self._set(o, f'Placement.Base.{ax}', a)
        return o

    def cyl(self, label, axis, r, cu, cv, w0, w1):
        """Cylinder along axis; (cu, cv) is the centre in the plane normal to it."""
        o = self._hide(self.doc.addObject('Part::Cylinder', 'Cyl'), label)
        rot = {'z': App.Rotation(), 'y': App.Rotation(App.Vector(1, 0, 0), -90), 'x': App.Rotation(App.Vector(0, 1, 0), 90)}[axis]
        o.Placement = App.Placement(App.Vector(), rot)
        self._set(o, 'Radius', r)
        self._set(o, 'Height', f'({w1}) - ({w0})')
        base = {'z': (cu, cv, w0), 'y': (cu, w0, cv), 'x': (w0, cu, cv)}[axis]
        for ax, v in zip('xyz', base):
            self._set(o, f'Placement.Base.{ax}', v)
        return o

    def _uvw_box(self, label, plane, u0, u1, v0, v1, w0, w1):
        x, y, z = {'xy': ((u0, u1), (v0, v1), (w0, w1)), 'xz': ((u0, u1), (w0, w1), (v0, v1)), 'yz': ((w0, w1), (u0, u1), (v0, v1))}[plane]
        return self.box(label, *x, *y, *z)

    def fuse(self, label, shapes, refine=False, name='Fusion'):
        o = self._hide(self.doc.addObject('Part::MultiFuse', name), label)
        o.Shapes = shapes
        o.Refine = refine
        return o

    def common(self, label, shapes, name='Common'):
        o = self._hide(self.doc.addObject('Part::MultiCommon', name), label)
        o.Shapes = shapes
        return o

    def cut(self, label, base, tool, refine=False, name='Cut'):
        o = self._hide(self.doc.addObject('Part::Cut', name), label)
        o.Base, o.Tool, o.Refine = base, tool, refine
        return o

    def profile(self, label, plane, u0, u1, v0, v1, rt, rb, w0, w1):
        """Rectangle in the (u, v) plane extruded along w; top corners radius rt, bottom rb (None = sharp)."""
        axis = {'xy': 'z', 'xz': 'y', 'yz': 'x'}[plane]
        vb = f'({v0}) + ({rb})' if rb else v0
        parts = [self._uvw_box(f'{label} band', plane, u0, u1, vb, f'({v1}) - ({rt})', w0, w1),
                 self._uvw_box(f'{label} top', plane, f'({u0}) + ({rt})', f'({u1}) - ({rt})', f'({v1}) - ({rt})', v1, w0, w1),
                 self.cyl(f'{label} top-left', axis, rt, f'({u0}) + ({rt})', f'({v1}) - ({rt})', w0, w1),
                 self.cyl(f'{label} top-right', axis, rt, f'({u1}) - ({rt})', f'({v1}) - ({rt})', w0, w1)]
        if rb:
            parts += [self._uvw_box(f'{label} bottom', plane, f'({u0}) + ({rb})', f'({u1}) - ({rb})', v0, vb, w0, w1),
                      self.cyl(f'{label} bottom-left', axis, rb, f'({u0}) + ({rb})', vb, w0, w1),
                      self.cyl(f'{label} bottom-right', axis, rb, f'({u1}) - ({rb})', vb, w0, w1)]
        return self.fuse(label, parts)

    def rrect(self, label, plane, u0, u1, v0, v1, r, w0, w1):
        return self.profile(label, plane, u0, u1, v0, v1, r, r, w0, w1)

    def stadium(self, label, plane, u0, u1, v0, v1, w0, w1):
        """Slot with full-round ends along v (r = half the u width)."""
        axis = {'xy': 'z', 'xz': 'y', 'yz': 'x'}[plane]
        r, uc = f'(({u1}) - ({u0})) / 2', f'(({u0}) + ({u1})) / 2'
        return self.fuse(label, [self._uvw_box(f'{label} band', plane, u0, u1, f'({v0}) + {r}', f'({v1}) - {r}', w0, w1),
                                 self.cyl(f'{label} end 0', axis, r, uc, f'({v0}) + {r}', w0, w1),
                                 self.cyl(f'{label} end 1', axis, r, uc, f'({v1}) - {r}', w0, w1)])

    def ring(self, label, a, r, cx, cy, cz, side, sweep):
        """Lower outer quarter of a torus over one 90° plan quadrant (major a, minor r; r may exceed a,
        where Part::Torus fails). A quarter-disc face (disc ∩ rectangle) in the XZ plane on the
        side (+1/-1) of the corner axis is revolved by sweep (±90°). Its end faces coincide with the
        edge cylinders' end discs, a glue-type joint OCC fuses reliably (360° rings tangent to the
        cylinders were silently dropped)."""
        rot = App.Rotation(App.Vector(1, 0, 0), 90)
        sg = '+' if side > 0 else '-'
        circle = self._hide(self.doc.addObject('Part::Circle', 'Circle'), f'{label} circle')
        circle.Placement = App.Placement(App.Vector(), rot)
        self._set(circle, 'Radius', r)
        for ax, v in zip('xyz', (f'({cx}) {sg} ({a})', cy, cz)):
            self._set(circle, f'Placement.Base.{ax}', v)
        disc = self._hide(self.doc.addObject('Part::Face', 'Disc'), f'{label} disc')
        disc.Sources = [circle]
        quad = self._hide(self.doc.addObject('Part::Plane', 'Quadrant'), f'{label} quadrant')
        quad.Placement = App.Placement(App.Vector(), rot)
        width = f'({r}) + ({a}) / 2 + 1 mm'  # starts at a/2: overlaps the slab corner instead of sharing its face
        self._set(quad, 'Length', width)
        self._set(quad, 'Width', f'({r}) + 1 mm')
        x0 = f'({cx}) + ({a}) / 2' if side > 0 else f'({cx}) - ({a}) / 2 - ({width})'
        for ax, v in zip('xyz', (x0, cy, f'({cz}) - ({r}) - 1 mm')):
            self._set(quad, f'Placement.Base.{ax}', v)
        rev = self._hide(self.doc.addObject('Part::Revolution', 'Ring'), label)
        rev.Source, rev.Axis, rev.Angle, rev.Solid = self.common(f'{label} quarter-disc', [disc, quad]), App.Vector(0, 0, 1), sweep, True
        for ax, v in zip('xyz', (cx, cy, cz)):
            self._set(rev, f'Base.{ax}', v)
        return rev

    def torus(self, label, r1, r2, cx, cy, cz):
        o = self._hide(self.doc.addObject('Part::Torus', 'Torus'), label)
        self._set(o, 'Radius1', r1)
        self._set(o, 'Radius2', r2)
        for ax, v in zip('xyz', (cx, cy, cz)):
            self._set(o, f'Placement.Base.{ax}', v)
        return o

    def dome(self, label, rp, rt, cx, cy, zc, core=False):
        """Smooth top-corner solid about the vertical axis (cx, cy): radius rho(z) = sqrt(rt² - (z - zc)²) - (rt - rp),
        i.e. the edge roll revolved around the corner (G1 with the rolls; plan radius rp where the roll starts).
        Revolved from disc ∩ rectangle so it stays expression-driven and works for rt > rp."""
        rot = App.Rotation(App.Vector(1, 0, 0), 90)
        circle = self._hide(self.doc.addObject('Part::Circle', 'Circle'), f'{label} circle')
        circle.Placement = App.Placement(App.Vector(), rot)
        self._set(circle, 'Radius', rt)
        for ax, v in zip('xyz', (f'({cx}) - (({rt}) - ({rp}))', cy, zc)):
            self._set(circle, f'Placement.Base.{ax}', v)
        disc = self._hide(self.doc.addObject('Part::Face', 'Disc'), f'{label} disc')
        disc.Sources = [circle]
        quad = self._hide(self.doc.addObject('Part::Plane', 'Quadrant'), f'{label} quadrant')
        quad.Placement = App.Placement(App.Vector(), rot)
        self._set(quad, 'Length', f'({rp}) + 1 mm')
        self._set(quad, 'Width', f'({rt}) + 1 mm')
        for ax, v in zip('xyz', (cx, cy, zc)):
            self._set(quad, f'Placement.Base.{ax}', v)
        shape = disc
        if core:  # rt < rp: the corner body also fills rho < rp - rt up to the top (the disc alone leaves a cusp at the axis)
            plane = self._hide(self.doc.addObject('Part::Plane', 'Core'), f'{label} core')
            plane.Placement = App.Placement(App.Vector(), rot)
            self._set(plane, 'Length', f'({rp}) - ({rt})')
            self._set(plane, 'Width', f'({rt}) + 1 mm')
            for ax, v in zip('xyz', (cx, cy, zc)):
                self._set(plane, f'Placement.Base.{ax}', v)
            shape = self.fuse(f'{label} disc + core', [disc, plane])
        rev = self._hide(self.doc.addObject('Part::Revolution', 'Dome'), label)
        rev.Source, rev.Axis, rev.Angle, rev.Solid = self.common(f'{label} profile', [shape, quad]), App.Vector(0, 0, 1), 360, True
        for ax, v in zip('xyz', (cx, cy, zc)):
            self._set(rev, f'Base.{ax}', v)
        return rev

    def block(self, label, x0, x1, y0, y1, z0, z1, rp, rt, rb, core=False, sharp_slab=False):
        """Rounded block: plan radius rp, top edge radius rt, bottom edge radius rb (None = sharp; rb < rp).
        Bottom edges are exact (plan inset slab + edge cylinders + corner tori, as in the reference).
        Top: intersection of three extruded profiles, then the corner creases are trimmed to a revolved
        dome so the top roll blends smoothly into the vertical corner (the reference uses a spline
        blend there; verify.py reports the remaining deviation)."""
        e = '1 mm'
        zt = f'({z0}) + ({rb})' if rb else z0
        top = self.common(f'{label} upper', [
            self.rrect(f'{label} plan', 'xy', x0, x1, y0, y1, rp, zt, f'({z1}) + {e}'),
            self.profile(f'{label} XZ', 'xz', x0, x1, zt, z1, rt, None, f'({y0}) - {e}', f'({y1}) + {e}'),
            self.profile(f'{label} YZ', 'yz', y0, y1, zt, z1, rt, None, f'({x0}) - {e}', f'({x1}) + {e}')])
        # Smooth top corners: inside each corner quadrant the body is exactly the dome, so remove
        # (quadrant box - dome) from the crease body (the crease body contains the smooth one).
        zc = f'({z1}) - ({rt})'
        qx0, qx1, qy0, qy1 = f'({x0}) + ({rp})', f'({x1}) - ({rp})', f'({y0}) + ({rp})', f'({y1}) - ({rp})'
        trims = []
        for cx, cy, bx, by in ((qx0, qy0, (f'({x0}) - {e}', qx0), (f'({y0}) - {e}', qy0)), (qx1, qy0, (qx1, f'({x1}) + {e}'), (f'({y0}) - {e}', qy0)),
                               (qx0, qy1, (f'({x0}) - {e}', qx0), (qy1, f'({y1}) + {e}')), (qx1, qy1, (qx1, f'({x1}) + {e}'), (qy1, f'({y1}) + {e}'))):
            box = self.box(f'{label} corner quadrant', *bx, *by, zc, f'({z1}) + {e}')
            trims.append(self.cut(f'{label} corner trim', box, self.dome(f'{label} corner dome', rp, rt, cx, cy, zc, core)))
        top = self.cut(f'{label} upper (smooth corners)', top, self.fuse(f'{label} corner trims', trims))
        if not rb:
            return top
        cx0, cx1, cy0, cy1 = f'({x0}) + ({rp})', f'({x1}) - ({rp})', f'({y0}) + ({rp})', f'({y1}) - ({rp})'
        sx0, sx1, sy0, sy1 = f'({x0}) + ({rb})', f'({x1}) - ({rb})', f'({y0}) + ({rb})', f'({y1}) - ({rb})'
        if sharp_slab:  # rb == rp: the inset slab has sharp corners (an rrect would need zero-radius cylinders)
            pieces = [self.box(f'{label} bottom slab', sx0, sx1, sy0, sy1, z0, f'{zt} + 0.01 mm')]
        else:
            pieces = [self.rrect(f'{label} bottom slab', 'xy', sx0, sx1, sy0, sy1, f'({rp}) - ({rb})', z0, f'{zt} + 0.01 mm')]
        for n, yv in (('front', f'({y0}) + ({rb})'), ('back', f'({y1}) - ({rb})')):
            pieces.append(self.cyl(f'{label} bottom edge {n}', 'x', rb, yv, zt, cx0, cx1))
        for n, xv in (('left', f'({x0}) + ({rb})'), ('right', f'({x1}) - ({rb})')):
            pieces.append(self.cyl(f'{label} bottom edge {n}', 'y', rb, xv, zt, cy0, cy1))
        for cx, cy, side, sweep in ((cx0, cy0, -1, 90), (cx0, cy1, -1, -90), (cx1, cy0, 1, -90), (cx1, cy1, 1, 90)):
            pieces.append(self.ring(f'{label} bottom corner', f'({rp}) - ({rb})', rb, cx, cy, zt, side, sweep))
        lower = self.common(f'{label} lower', [self.fuse(f'{label} lower pieces', pieces),
                                                self.box(f'{label} lower clip', f'({x0}) - {e}', f'({x1}) + {e}', f'({y0}) - {e}', f'({y1}) + {e}', z0, f'{zt} + 0.01 mm')])
        return self.fuse(label, [top, lower])

    def wedge(self, label, rot, lims):
        o = self._hide(self.doc.addObject('Part::Wedge', 'Wedge'), label)
        o.Placement = App.Placement(App.Vector(), rot)
        for k, v in lims.items():
            self._set(o, k, v)
        return o


def build(doc, PARAMS):
    b = Builder(doc)
    P = {p[1]: p[2] for p in PARAMS}

    vs = doc.addObject('App::VarSet', 'Parameters')
    vs.Label = '01 · Parameters'
    for group, name, value, signed, desc in PARAMS:
        vs.addProperty('App::PropertyDistance' if signed else 'App::PropertyLength', name, group, f'{desc}. Current value: {value:g} mm')
        setattr(vs, name, value)
    for name, expr in EXPRESSIONS.items():
        vs.setExpression(name, X(expr))

    pv = doc.addObject('App::VarSet', 'Preview')
    pv.Label = '03 · Preview inputs'
    pv.addProperty('App::PropertyLength', 'TopLift', 'Pose', 'Lifts the top shell for exploded previews. Keep 0 mm when saving. Current value: 0 mm')

    out = doc.addObject('App::VarSet', 'Outputs')
    out.Label = '04 · Outputs'
    outputs = [
        ('Envelope', 'EnvelopeLength', '$BodyLength'), ('Envelope', 'EnvelopeWidth', '$BodyWidth'),
        ('Envelope', 'EnvelopeHeight', '$BodyHeight'),
        ('Envelope', 'CavityLength', '$BodyLength - 2 * $Wall'), ('Envelope', 'CavityWidth', '$BodyWidth - 2 * $Wall'),
        ('Envelope', 'CavityHeight', '$BodyHeight - $TopSkin - $Floor'),
        ('Seam', 'SeamLateralClearance', '$LipInset - $GrooveInset'), ('Seam', 'SeamVerticalClearance', '$GrooveTopZ - $LipTopZ'),
        ('Seam', 'LipThickness', '$Wall - $LipInset'),
        ('Display', 'ScreenCoverFloorGap', '$WindowPocketDepth - $CoverThickness'),
        ('Display', 'CoverLedgeSkin', '$TopSkin - $WindowPocketDepth'),
        ('Display', 'PanelFaceZ', '$TowerBottomZ + $PanelFold + $PanelThickness'),
        ('Display', 'PanelToCoverGap', '$BodyHeight - $CoverThickness - ($TowerBottomZ + $PanelFold + $PanelThickness)'),
        ('Display', 'PanelToCeilingGap', '$BodyHeight - $TopSkin - ($TowerBottomZ + $PanelFold + $PanelThickness)'),
        ('Display', 'ScreenOffsetX', '$BodyX0 + $BodyLength / 2 - $WindowCX'),
        ('Display', 'ScreenOffsetY', '$BodyY0 + $BodyWidth / 2 - $WindowCY'),
        ('Display', 'FpcFlatRun', f'$PanelY - $PanelWidth / 2 - ({FPC_YV} + {FPC_R})'),
        ('Display', 'FpcUnderRun', f'({FPC_YV} - {FPC_R}) - $Fpc2EntryY'),
        ('Controls', 'ButtonProtrusion', '$CapProtrusion'), ('Controls', 'CapSideClearance', '($ButtonHoleSize - $CapSize) / 2'),
        ('Controls', 'SkinOverCaps', '$BodyHeight - ($ActuatorTopZ + $CapRestGap + $FlangeThickness + $FlangePlay)'),
        ('Fasteners', 'SkinOverInsert', '$BodyHeight - $TowerBottomZ - $InsertHoleDepth'),
    ]
    for group, name, expr in outputs:
        out.addProperty('App::PropertyLength', name, group, 'Derived, read-only (see expression).')
        out.setExpression(name, X(expr))
        out.setPropertyStatus(name, 'ReadOnly')

    # Shared body. Both top rolls are now smaller than their plan corner radius (R4.5 < R5.3,
    # R2.5 < R3.3), so the corner domes get a core (structural choice fixed here, values parametric).
    X0, Y0, H = '$BodyX0', '$BodyY0', '$BodyHeight'
    X1, Y1 = '$BodyX0 + $BodyLength', '$BodyY0 + $BodyWidth'
    eq = lambda a, b: abs(a - b) < 1e-6
    outer = b.block('Outer body', X0, X1, Y0, Y1, '0 mm', H, '$CornerR', '$TopEdgeR', '$BottomEdgeR',
                    core=P['TopEdgeR'] < P['CornerR'] and not eq(P['TopEdgeR'], P['CornerR']), sharp_slab=eq(P['BottomEdgeR'], P['CornerR']))
    ri = P['CornerR'] - P['Wall']
    cavity = b.block('Cavity', f'{X0} + $Wall', f'{X1} - $Wall', f'{Y0} + $Wall', f'{Y1} - $Wall', '$Floor', f'{H} - $TopSkin',
                     '$CornerR - $Wall', '$InnerTopR', '$InnerBottomR', core=P['InnerTopR'] < ri and not eq(P['InnerTopR'], ri),
                     sharp_slab=eq(P['InnerBottomR'], ri))
    shell = b.cut('Hollow shell', outer, cavity)
    big = ('$BodyX0 - 5 mm', '$BodyX0 + $BodyLength + 5 mm', '$BodyY0 - 5 mm', '$BodyY0 + $BodyWidth + 5 mm')

    def inset_rrect(label, inset, z0, z1):
        return b.rrect(label, 'xy', f'{X0} + {inset}', f'{X1} - {inset}', f'{Y0} + {inset}', f'{Y1} - {inset}', f'$CornerR - {inset}', z0, z1)

    # Wall openings spanning the seam. Corners never sit across the seam line (V0.1.0 left 0.19 mm slivers there).
    fy0, fy1 = f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm'
    usb = b.profile('USB-C opening', 'xz', '$UsbX0', '$UsbX1', '$UsbZ0', '$UsbZ1', '$UsbRTop', '$UsbRBottom', fy0, fy1)
    centre = b.profile('HDMI opening upper', 'xz', '$CentrePortX0', '$CentrePortX1', '$CentrePortZ0', '$CentrePortZ1', '$CentrePortRTop', None, fy0, fy1)
    cx = '($CentrePortX0 + $CentrePortX1) / 2'
    funnel = b.wedge('HDMI opening funnel', App.Rotation(App.Vector(1, 0, 0), 90), {
        'Ymin': '$FunnelZ0', 'Ymax': '$FunnelZ1',
        'Xmin': f'{cx} - $FunnelHalfW0', 'Xmax': f'{cx} + $FunnelHalfW0', 'X2min': f'{cx} - $FunnelHalfW1', 'X2max': f'{cx} + $FunnelHalfW1',
        'Zmin': f'-({fy1})', 'Zmax': f'-({fy0})', 'Z2min': f'-({fy1})', 'Z2max': f'-({fy0})'})
    roundp = b.fuse('Audio jack opening + relief', [b.cyl('Audio jack opening', 'y', '$RoundPortR', '$RoundPortX', '$RoundPortZ', fy0, fy1),
                    b.box('Audio jack body relief', '$JackReliefX0', '$JackReliefX1', f'{Y0} + $Wall - $JackReliefDepth', f'{Y0} + $Wall + 1 mm', '$JackReliefZ0', '$JackReliefZ1'),
                    b.rrect('Audio jack spot-face', 'xz', '$RoundPortX - $RoundPortR - $JackFaceMargin', '$RoundPortX + $RoundPortR + $JackFaceMargin',
                            '$JackFaceZ0', '$JackFaceZ1', '$JackFaceR', f'{Y0} - 1 mm', f'{Y0} + $JackFaceInset')])
    rx0, rx1 = f'{X1} - $Wall - 1 mm', f'{X1} + 1 mm'
    vent_a = b.rrect('USB-A opening A', 'yz', '$VentAY0', '$VentAY1', '$VentZ0', '$VentZ1', '$VentR', rx0, rx1)
    vent_b = b.rrect('USB-A opening B', 'yz', '$VentBY0', '$VentBY1', '$VentZ0', '$VentZ1', '$VentR', rx0, rx1)
    lx0, lx1 = f'{X0} - 1 mm', f'{X0} + $Wall + 1 mm'

    # Top shell
    top_raw = b.common('Top shell raw', [shell, b.box('Top half-space', *big, '$SeamZ', f'{H} + 5 mm')])
    screws_top = [('$TopScrewX0', '$TopScrewY0'), ('$TopScrewX1', '$TopScrewY0'), ('$TopScrewX0', '$TopScrewY1'), ('$TopScrewX1', '$TopScrewY1')]
    towers = [b.cyl(f'Insert tower {i}', 'z', '$TowerR', sx, sy, '$TowerBottomZ', f'{H} - $TopSkin + 0.5 mm') for i, (sx, sy) in enumerate(screws_top)]
    # OLED locators hanging from the ceiling: a stop ring on the bare glass margin around the polarizer (sets the height)
    # and posts at the glass edges (set X/Y), so the glued glass lands where the window expects it.
    gtop = '$TowerBottomZ + $PanelFold + $PanelThickness - $PolarizerThickness'   # substrate (glass) top face
    gx0, gx1 = '$PanelX - $PanelLength / 2', '$PanelX + $PanelLength / 2'
    gy0, gy1 = '$PanelY - $PanelWidth / 2', '$PanelY + $PanelWidth / 2'
    so, sw = '$PanelStopOverlap', '($PanelClearance + $PanelStopWidth)'
    ring = b.cut('OLED stop ring', b.rrect('OLED stop ring outer', 'xy', f'{gx0} - {sw}', f'{gx1} + {sw}', f'{gy0} - {sw}', f'{gy1} + {sw}', '$PanelOpeningR', gtop, f'{H} - $TopSkin + 0.3 mm'),
                 b.box('OLED stop ring window', f'{gx0} + {so}', f'{gx1} - {so}', f'{gy0} + {so}', f'{gy1} - {so}', f'{gtop} - 1 mm', f'{H} + 1 mm'))
    g, t, w, pz0 = '$PanelLocatorGap', '$PanelLocatorT', '$PanelLocatorW / 2', f'{gtop} - $PanelLocatorDepth'
    posts = [b.box(f'OLED locator {n}', *xy, pz0, f'{gtop} + 0.1 mm') for n, xy in (
        ('front left', (f'$PanelX - $PanelLocatorPostX - {w}', f'$PanelX - $PanelLocatorPostX + {w}', f'{gy0} - {g} - {t}', f'{gy0} - {g}')),
        ('front right', (f'$PanelX + $PanelLocatorPostX - {w}', f'$PanelX + $PanelLocatorPostX + {w}', f'{gy0} - {g} - {t}', f'{gy0} - {g}')),
        ('back left', (f'$PanelX - $PanelLocatorPostX - {w}', f'$PanelX - $PanelLocatorPostX + {w}', f'{gy1} + {g}', f'{gy1} + {g} + {t}')),
        ('back right', (f'$PanelX + $PanelLocatorPostX - {w}', f'$PanelX + $PanelLocatorPostX + {w}', f'{gy1} + {g}', f'{gy1} + {g} + {t}')),
        ('left', (f'{gx0} - {g} - {t}', f'{gx0} - {g}', f'$PanelY - {w}', f'$PanelY + {w}')),
        ('right', (f'{gx1} + {g}', f'{gx1} + {g} + {t}', f'$PanelY - {w}', f'$PanelY + {w}')))]
    # LED light block: one tunnel per LED from just above the LED to the thinned skin (no light bleed between LEDs)
    tun_z0 = '$TowerBottomZ + $LedHeight + $LedTunnelGap'
    tun_z1 = f'{H} - $TopSkin + 0.3 mm'
    light = b.fuse('LED light block', [   # round ends concentric with the outer tunnels: even wall all round
        b.box('LED light block band', '$LedLight1X', '$LedLight3X', '$LedLightY - $LedTunnelHalfW', '$LedLightY + $LedTunnelHalfW', tun_z0, tun_z1),
        *[b.cyl(f'LED light block end {i}', 'z', '$LedTunnelHalfW', f'$LedLight{i}X', '$LedLightY', tun_z0, tun_z1) for i in (1, 3)]])
    top_adds = b.common('Top additions (clipped to outer)', [b.fuse('Top additions', towers + [ring, light] + posts), outer])
    cm = '($FlangeSize / 2 + $CapChannelMargin)'                       # cap channel half width around the column
    cz = '$ActuatorTopZ + $CapRestGap'                                   # cap underside, directly on the actuator
    top_base = b.fuse('Top shell base', [top_raw, top_adds], name='ShellTopBase')
    ceiling = f'{H} - $TopSkin'
    pocket_floor = f'{H} - $WindowPocketDepth'
    wx0, wx1 = '$WindowCX - $WindowLength / 2', '$WindowCX + $WindowLength / 2'
    wy0, wy1 = '$WindowCY - $WindowWidth / 2', '$WindowCY + $WindowWidth / 2'
    c = '($LipInset - $GrooveInset)'
    fillers = [b.box(f'Groove filler front {i}', f'$LipGapFront{i}X0 + {c}', f'$LipGapFront{i}X1 - {c}', f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm', '$SeamZ - 2 mm', '$GrooveTopZ + 1 mm') for i in (1, 2, 3)]
    groove = b.cut('Seam groove (with fillers)', inset_rrect('Seam groove', '$GrooveInset', '$SeamZ - 1 mm', '$GrooveTopZ'), b.fuse('Groove fillers', fillers))
    # FireWire opening: applied to both shells; the seam steps up to the port's centre line (user request: a bottom-shell tab
    # holds the lower half of the port, the lid the upper half).
    def fw_trapezoid(label, grow, z0, z1, x0, x1, lift='0 mm'):
        """Split tab (grow 0) or lid notch (grow = gap) in the left wall: sides flare (FwTabFlareFront/Back) from the split
        down to the seam; lift raises the whole outline (lip band above the tab, groove in the lid)."""
        h = '($FwSplitZ - $SeamZ)'
        gf = f'{grow} * sqrt({h} ^ 2 + $FwTabFlareFront ^ 2) / {h}'   # horizontal shift = gap normal to the sloped side
        gb = f'{grow} * sqrt({h} ^ 2 + $FwTabFlareBack ^ 2) / {h}'
        front = lambda z: f'$FwTabY0 - $FwTabFlareFront * ($FwSplitZ + {lift} - ({z})) / {h} - {gf}'
        back = lambda z: f'$FwTabY1 + $FwTabFlareBack * ($FwSplitZ + {lift} - ({z})) / {h} + {gb}'
        return b.wedge(label, App.Rotation(App.Vector(1, 1, 1), 120), {   # local X, Y, Z = case y, z, x
            'Ymin': z0, 'Ymax': z1, 'Xmin': front(z0), 'Xmax': back(z0), 'X2min': front(z1), 'X2max': back(z1),
            'Zmin': x0, 'Zmax': x1, 'Z2min': x0, 'Z2max': x1})

    def j2_face(pts, x):
        return Part.Face(Part.makePolygon([App.Vector(x, y, z) for y, z in pts] + [App.Vector(x, *pts[0])]))
    fw_prof = doc.addObject('Part::Feature', 'FwOpeningProfile')
    fw_prof.Shape = j2_face(J2_SILHOUETTE, P['BodyX0'] - 1).makeOffset2D(P['FwClearance'], 2)   # mitred: flat faces only (arcs at 91 points made STEP volume noise)
    b._hide(fw_prof, 'FireWire opening profile (J2 silhouette + FwClearance)')
    fw_open = b._hide(doc.addObject('Part::Extrusion', 'FwOpening'), 'FireWire opening')
    fw_open.Base, fw_open.Dir, fw_open.Solid = fw_prof, App.Vector(1, 0, 0), True
    b._set(fw_open, 'LengthFwd', '$Wall + 2 mm')
    fw_cutters = [fw_open]
    # Active cooling: exhaust window over the blower outlet (both shells) + inlet slots above the USB-A ports (top shell)
    exhaust = b.box('Fan exhaust window', f'{X0} - 1 mm', f'{X0} + $Wall + 0.1 mm', '$BlowerCY - $BlowerSize / 2 + $ExhaustInset',
                    '$BlowerCY + $BlowerSize / 2 - $ExhaustInset', '$ExhaustZ0', '$ExhaustZ1')
    n_in = int((P['InletY1'] - P['InletY0'] + P['InletRibW']) // (P['InletSlotW'] + P['InletRibW']))
    inlet = b.fuse('Fan inlet slots', [b.box(f'Fan inlet slot {k + 1}', f'{X1} - $Wall - 0.1 mm', f'{X1} + 1 mm',
                                             f'$InletY0 + {k} * ($InletSlotW + $InletRibW)', f'$InletY0 + {k} * ($InletSlotW + $InletRibW) + $InletSlotW',
                                             '$InletZ0', '$InletZ1') for k in range(n_in)])
    top_cutters = [
        groove,
        *[b.cyl(f'Insert hole {i}', 'z', '$InsertHoleR', sx, sy, '$TowerBottomZ - 1 mm', '$TowerBottomZ + $InsertHoleDepth') for i, (sx, sy) in enumerate(screws_top)],
        b.rrect('Screen-cover pocket', 'xy', wx0, wx1, wy0, wy1, '$WindowR', pocket_floor, f'{H} + 1 mm'),
        b.rrect('Panel opening', 'xy', '$PanelX - $PanelLength / 2 - $PanelClearance', '$PanelX + $PanelLength / 2 + $PanelClearance',
                '$PanelY - $PanelWidth / 2 - $PanelClearance', '$PanelY + $PanelWidth / 2 + $PanelClearance', '$PanelOpeningR', ceiling, f'{pocket_floor} + 0.1 mm'),  # starts at the ceiling: keeps the stop ring below it
        b.rrect('Cap channel', 'xy', f'$ButtonX - {cm}', f'$ButtonX + {cm}', f'$Button1Y - {cm}', f'$Button3Y + {cm}', '$FlangeR + $CapChannelMargin',
                f'{ceiling} - 1 mm', f'{cz} + $FlangeThickness + $FlangePlay'),
        *[b.rrect(f'Cap hole {i}', 'xy', '$ButtonX - $ButtonHoleSize / 2', '$ButtonX + $ButtonHoleSize / 2', f'$Button{i}Y - $ButtonHoleSize / 2',
                  f'$Button{i}Y + $ButtonHoleSize / 2', '$ButtonHoleR', f'{ceiling} - 1 mm', f'{H} + 1 mm') for i in (1, 2, 3)],
        *[b.cyl(f'LED light tunnel {i}', 'z', '$LedLightD / 2', f'$LedLight{i}X', '$LedLightY', f'{tun_z0} - 1 mm', f'{H} - $LedLightSkin') for i in (1, 2, 3)],
        usb, centre, roundp, vent_a, vent_b,
        b.box('FireWire connector relief', f'{X0} + $Wall', '$FwReliefX1', '$FwReliefY0', '$FwReliefY1', '$FwReliefZ0', ceiling),
        *fw_cutters, exhaust, inlet,
        fw_trapezoid('FireWire split notch (skin)', '$FwTabGap', '$SeamZ - 0.01 mm', '$FwSplitZ + $FwTabGap', lx0, f'{X0} + $GrooveInset + 0.01 mm'),
        b.cut('FireWire split groove (flanks)', fw_trapezoid('FireWire split groove', '$FwTabGap', '$GrooveTopZ - 0.3 mm', '$FwSplitZ + $GrooveTopZ - $SeamZ', f'{X0} + $GrooveInset', lx1,
                                                             '($GrooveTopZ - $SeamZ)'),
              b.box('FireWire split groove: none over the flat top', f'{X0}', f'{X0} + $Wall + 2 mm', '$FwTabY0 + $FwTabGap', '$FwLipBack - $FwTabGap',
                    '$FwSplitZ + $FwTabGap', '$FwSplitZ + 4 mm')),
    ]
    top = b.cut('Shell top', top_base, b.fuse('Top shell cutters', top_cutters, name='ShellTopCutters'), refine=True, name='ShellTop')

    # Bottom shell
    bot_raw = b.common('Bottom shell raw', [shell, b.box('Bottom half-space', *big, '-5 mm', '$SeamZ')])
    lip = b.cut('Lip ring', inset_rrect('Lip outer', '$LipInset', '$SeamZ - 0.5 mm', '$LipTopZ'),
                inset_rrect('Lip inner', '$Wall', '$SeamZ - 1 mm', '$LipTopZ + 1 mm'))
    lip_gaps = [b.box(f'Lip gap front {i}', f'$LipGapFront{i}X0', f'$LipGapFront{i}X1', f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm', '$SeamZ', '$LipTopZ + 1 mm') for i in (1, 2, 3)]
    lip = b.cut('Lip (gapped)', lip, b.fuse('Lip gaps', lip_gaps))
    screws = [('$BotScrewX0', '$BotScrewY0'), ('$BotScrewX1', '$BotScrewY0'), ('$BotScrewX0', '$BotScrewY1'), ('$BotScrewX1', '$BotScrewY1')]
    bosses = [b.cyl(f'Screw boss {i}', 'z', '$BotBossR', sx, sy, '$Floor - 0.5 mm', '$BotBossTopZ') for i, (sx, sy) in enumerate(screws)]
    fw_tab = b.fuse('FireWire split tab + lip', [
        fw_trapezoid('FireWire split tab', '0 mm', '$SeamZ - 0.5 mm', '$FwSplitZ', f'{X0} - 1 mm', f'{X0} + $Wall'),
        b.cut('FireWire split lip (flanks)', fw_trapezoid('FireWire split lip', '0 mm', '$LipTopZ - 0.3 mm', '$FwSplitZ + $LipTopZ - $SeamZ', f'{X0} + $LipInset',
                                                       f'{X0} + $Wall', '($LipTopZ - $SeamZ)'),
              b.box('FireWire split lip: none over the flat top', f'{X0}', f'{X0} + $Wall + 1 mm', '$FwTabY0', '$FwLipBack', '$FwSplitZ', '$FwSplitZ + 3 mm'))])
    bot_adds = b.common('Bottom additions (clipped to outer)', [b.fuse('Bottom additions', bosses + [fw_tab]), outer])
    bot_base = b.fuse('Bottom shell base', [bot_raw, lip, bot_adds], name='ShellBottomBase')
    by0, by1 = f'{Y1} - $BackSlotDepth', f'{Y1} + 1 mm'
    # Heat spreader: 1 mm aluminium sheet in a floor pocket (top flush with the floor) and a soft gap pad from it to the ROCK 2F
    # underside under the RK3528A (thermal study, scripts/thermal.py: about 20 °C off the SoC). The sheet keeps clear of the
    # screw bosses and the USB-A leg pockets.
    swg = '$SpreaderWallGap'
    def spreader_keepouts(extra):
        return ([b.cyl(f'Spreader boss keep-out {i} +{extra}', 'z', f'$BotBossR + $SpreaderBossGap + {extra}', sx, sy, '-1 mm', H) for i, (sx, sy) in enumerate(screws)]
                + [b.box(f'Spreader USB-A leg keep-out {i} +{extra}', f'$UsbALegX - $UsbALegPocketX / 2 - $SpreaderBossGap - {extra}', f'$UsbALegX + $UsbALegPocketX / 2 + $SpreaderBossGap + {extra}',
                         f'$UsbALeg{i}Y - $UsbALegPocketY / 2 - $SpreaderBossGap - {extra}',
                         '$BotScrewY1' if i == 4 else f'$UsbALeg{i}Y + $UsbALegPocketY / 2 + $SpreaderBossGap + {extra}', '-1 mm', H) for i in (1, 2, 3, 4)])   # leg 4 runs into the back boss: no sliver
    spreader_pocket = b.cut('Heat spreader pocket', b.rrect('Heat spreader pocket outline', 'xy', f'{X0} + $Wall + {swg}', f'{X1} - $Wall - {swg}', f'{Y0} + $Wall + {swg}',
                                                            f'{Y1} - $Wall - {swg}', '$SpreaderR + $SpreaderGap', '$Floor - $SpreaderT', '$Floor + 0.01 mm'),
                            b.fuse('Heat spreader pocket keep-outs', spreader_keepouts('0 mm')))
    bot_cutters = [
        *[b.cyl(f'Counterbore {i}', 'z', '$CounterboreR', sx, sy, '-1 mm', '$CounterboreTopZ') for i, (sx, sy) in enumerate(screws)],
        *[b.cut(f'Counterbore fillet {i}', b.cyl(f'Counterbore fillet {i} envelope', 'z', '$CounterboreR + $CounterboreFilletR', sx, sy, '-1 mm', '$CounterboreFilletR'),
                b.torus(f'Counterbore fillet {i} torus', '$CounterboreR + $CounterboreFilletR', '$CounterboreFilletR', sx, sy, '$CounterboreFilletR')) for i, (sx, sy) in enumerate(screws)],
        *[b.cyl(f'Clearance hole {i}', 'z', '$ClearanceHoleR', sx, sy, '-1 mm', '$BotBossTopZ + 1 mm') for i, (sx, sy) in enumerate(screws)],
        usb, centre, funnel, roundp, vent_a, vent_b, spreader_pocket, *fw_cutters, exhaust,
        *[b.rrect(f'LED window {i}', 'xz', f'$LedWin{i}X0', f'$LedWin{i}X0 + $LedWinW', '$LedWinZ0', '$LedWinZ1', '$LedWinR', fy0, f'{Y0} + $LedWinDepth') for i in (1, 2)],
        b.rrect('Back recess', 'xz', '$BackSlotX0', '$BackSlotX1', '$BackSlotZ0', '$BackSlotZ1', '$BackSlotR', by0, by1),
        b.box('MicroSD notch', lx0, f'{X0} + $SdNotchDepth', '$SdNotchY0', '$SdNotchY1', '$SdNotchZ0', '$SdNotchZ1'),
        b.rrect('MicroSD spot-face', 'yz', '$SdNotchY0 - $SdFaceMargin', '$SdNotchY1 + $SdFaceMargin', '$SdFaceZ0', '$SdNotchZ1 + $SdFaceMargin',
                '$SdFaceR', lx0, f'{X0} + $SdFaceInset'),
        *[b.box(f'USB-A leg relief {i}', '$UsbALegX - $UsbALegPocketX / 2', '$UsbALegX + $UsbALegPocketX / 2', f'$UsbALeg{i}Y - $UsbALegPocketY / 2',
                f'$UsbALeg{i}Y + $UsbALegPocketY / 2', '$UsbALegPocketZ0', '$Floor + 0.5 mm') for i in (1, 2, 3, 4)],
    ]
    bottom = b.cut('Shell bottom', bot_base, b.fuse('Bottom shell cutters', bot_cutters, name='ShellBottomCutters'), refine=True, name='ShellBottom')

    # Screen cover (same bought part as V0.1.0, centred on the panel's active area = the case centre)
    cover = b.rrect('Screen cover body', 'xy', f'{wx0} + $CoverClearance', f'{wx1} - $CoverClearance', f'{wy0} + $CoverClearance',
                    f'{wy1} - $CoverClearance', '$WindowR - $CoverClearance', f'{H} - $CoverThickness', H)
    sg = '$SpreaderGap'
    spreader = b.cut('Heat spreader (1 mm aluminium, bought/cut)', b.rrect('Heat spreader outline', 'xy', f'{X0} + $Wall + {swg} + {sg}', f'{X1} - $Wall - {swg} - {sg}',
                                                                        f'{Y0} + $Wall + {swg} + {sg}', f'{Y1} - $Wall - {swg} - {sg}', '$SpreaderR', '$Floor - $SpreaderT', '$Floor'),
                     b.fuse('Heat spreader keep-outs', spreader_keepouts(sg)), refine=True, name='HeatSpreader')
    pad_part = b._hide(doc.addObject('Part::Refine', 'ThermalPad'), 'Thermal pad (soft gap pad, bought)')
    pad_part.Source = b.box('Thermal pad body', '$PadX - $PadSize / 2', '$PadX + $PadSize / 2', '$PadY - $PadSize / 2', '$PadY + $PadSize / 2', '$Floor', '$BotBossTopZ')
    cover_part = b._hide(doc.addObject('Part::Refine', 'ScreenCover'), 'Screen cover')
    cover_part.Source = cover

    # Reference (bought, not printed): the 1.3" OLED actually used (supplier drawing), glued on the Firehat with the
    # FPC edge facing the board slot. Stack from the board up: adhesive, cap glass (not under the FPC ledge),
    # substrate, polarizer. V/A and A/A are thin markers on the polarizer, for positioning.
    pz, gx0, gy0, gy1 = '$TowerBottomZ + $PanelFold', '$PanelX - $PanelLength / 2', '$PanelY - $PanelWidth / 2', '$PanelY + $PanelWidth / 2'
    gx1, face = '$PanelX + $PanelLength / 2', '$TowerBottomZ + $PanelFold + $PanelThickness'
    panel = b.fuse('OLED panel layers', [
        b.box('OLED cap glass', gx0, gx1, f'{gy1} - $PanelCapWidth', gy1, pz, f'{pz} + $PanelCapThickness'),
        b.box('OLED substrate glass', gx0, gx1, gy0, gy1, f'{pz} + $PanelCapThickness', f'{face} - $PolarizerThickness'),
        b.box('OLED polarizer', f'{gx0} + $PolarizerOffsetX', f'{gx0} + $PolarizerOffsetX + $PolarizerLength',
              f'{gy1} - $PolarizerOffsetY - $PolarizerWidth', f'{gy1} - $PolarizerOffsetY', f'{face} - $PolarizerThickness', face)])
    panel_part = b._hide(doc.addObject('Part::Refine', 'OledPanel'), 'OLED panel (reference, bought)')
    panel_part.Source = panel
    view = b.box('OLED viewing area V/A (marker, 0.01 mm)', f'{gx0} + $ViewAreaOffsetX', f'{gx0} + $ViewAreaOffsetX + $ViewAreaLength',
                 f'{gy1} - $ViewAreaEdgeY - $ViewAreaWidth', f'{gy1} - $ViewAreaEdgeY', face, f'{face} + 0.01 mm')
    view_part = b._hide(doc.addObject('Part::Refine', 'OledViewArea'), 'OLED viewing area V/A (marker)')
    view_part.Source = view
    active = b.box('OLED active area A/A (marker, 0.01 mm)', f'{gx0} + $ActiveAreaOffsetX', f'{gx0} + $ActiveAreaOffsetX + $ActiveAreaLength',
                   f'{gy1} - $ActiveAreaEdgeY - $ActiveAreaWidth', f'{gy1} - $ActiveAreaEdgeY', f'{face} + 0.01 mm', f'{face} + 0.02 mm')
    active_part = b._hide(doc.addObject('Part::Refine', 'OledActiveArea'), 'OLED active area A/A (marker)')
    active_part.Source = active

    # Glass jig (printed tool, not part of the device): pins in the Firehat's 4 mounting holes, a pocket for the glass
    # (glass + JigPocketGap) open at the top, and an FPC opening in the front wall so the jig lifts off over the FPC.
    zb, jw, jq = '$TowerBottomZ', '($JigPocketGap + $JigWall)', '$JigPocketGap'
    jp0, jp1 = f'{zb} + $JigPlateZ0', f'{zb} + $JigPlateZ0 + $JigPlateT'
    ei = '(3.5 mm - $JigEdgeInset)'     # Firehat edge = mounting holes -/+ 3.5 mm; plate inset by JigEdgeInset
    jig_body = b.fuse('Jig body', [
        b.rrect('Jig plate', 'xy', f'$TopScrewX0 - {ei}', f'$TopScrewX1 + {ei}', f'$TopScrewY0 - {ei}', f'$TopScrewY1 + {ei}', '3 mm', jp0, jp1),
        b.box('Jig pocket walls', f'{gx0} - {jw}', f'{gx1} + {jw}', f'{gy0} - {jw}', f'{gy1} + {jw}', zb, f'{jp0} + 0.5 mm'),
        *[b.cyl(f'Jig leg {i}', 'z', '$JigLegD / 2', sx, sy, zb, f'{jp0} + 0.5 mm') for i, (sx, sy) in enumerate(screws_top)],
        *[b.cyl(f'Jig pin {i}', 'z', '$JigPinD / 2', sx, sy, f'{zb} - $JigPinLength', f'{zb} + 0.5 mm') for i, (sx, sy) in enumerate(screws_top)]])
    jig_cutters = [
        b.box('Jig pocket', f'{gx0} - {jq}', f'{gx1} + {jq}', f'{gy0} - {jq}', f'{gy1} + {jq}', f'{zb} - 1 mm', f'{jp1} + 1 mm'),
        *[b.cyl(f'Jig corner relief {i}', 'z', '0.5 mm', cx_, cy_, f'{zb} - 1 mm', f'{jp1} + 1 mm') for i, (cx_, cy_) in enumerate(
            [(f'{gx0} - {jq}', f'{gy0} - {jq}'), (f'{gx1} + {jq}', f'{gy0} - {jq}'), (f'{gx1} + {jq}', f'{gy1} + {jq}')])],   # none at the back-left corner: the FireWire relief is next to it
        b.box('Jig FPC opening', '$PanelX - $JigFpcNotchW / 2', '$PanelX + $JigFpcNotchW / 2', f'{gy0} - {jw} - 1 mm', gy0, f'{zb} - 1 mm', jp0),
        b.box('Jig FireWire relief', '$TopScrewX0 - 10 mm', '$JigFwReliefX1', '$JigFwReliefY0', '$JigFwReliefY1', f'{zb} - 1 mm', f'{zb} + $JigFwReliefH')]
    jig = b.cut('Glass jig', jig_body, b.fuse('Jig cutters', jig_cutters), refine=True, name='GlassJig')

    # Corner spacers (printed, resin): at the two front screws between the ROCK 2F and the Firehat, length = board gap (user: the back is held by the GPIO header). The case walls
    # locate them (two fins); the M2.5 screw passes through without thread and only the lid insert pulls the stack together.
    sz0, sz1 = '$BotBossTopZ + $RockPcbT', '$TowerBottomZ - $FirehatPcbT'
    # Blower cradle on Spacer 1: C-rails along X gripping the blower edges (slides in from +X, outlet edge first), an outlet
    # frame against the wall closing the exhaust window above/below the outlet, and an arm along the wall to the spacer.
    fx0 = f'{X0} + $Wall + $CradleWallGap'
    bx0, bx1 = '$BlowerCX - $BlowerSize / 2 - $BlowerPlay', '$BlowerCX + $BlowerSize / 2 + $BlowerPlay'
    by0, by1 = '$BlowerCY - $BlowerSize / 2 - $BlowerPlay', '$BlowerCY + $BlowerSize / 2 + $BlowerPlay'
    bz0, bz1 = '$BlowerZ0', '$BlowerZ0 + $BlowerSlotH'
    cz0, cz1 = f'{bz0} - $CradleT', f'{bz1} + $CradleT'
    cradle = [
        b.box('Cradle front web', fx0, bx1, f'{by0} - $CradleT', by0, cz0, cz1),
        b.box('Cradle front lip low', fx0, bx1, by0, f'{by0} + $CradleLip', cz0, bz0),
        b.box('Cradle front lip high', fx0, bx1, by0, f'{by0} + $CradleLip', bz1, cz1),
        b.box('Cradle back web', fx0, bx1, by1, f'{by1} + $CradleT', cz0, cz1),
        b.box('Cradle back lip low', fx0, bx1, f'{by1} - $CradleLip', by1, cz0, bz0),
        b.box('Cradle back lip high', fx0, bx1, f'{by1} - $CradleLip', by1, bz1, cz1),
        b.box('Cradle outlet frame low', fx0, f'{fx0} + $CradleT', by0, by1, cz0, bz0),
        b.box('Cradle outlet frame high', fx0, f'{fx0} + $CradleT', by0, by1, bz1, '$ExhaustZ1 + 0.3 mm'),
        b.box('Cradle arm', fx0, f'{fx0} + $CradleArmW', '$TopScrewY0 - 0.4 mm', f'{by0} - $CradleT', cz0, cz1),
    ]
    blower = b._hide(doc.addObject('Part::Refine', 'Blower'), 'Blower (Sunon UB3H3-500, bought; edge envelope)')
    blower.Source = b.box('Blower body', '$BlowerCX - $BlowerSize / 2', '$BlowerCX + $BlowerSize / 2', '$BlowerCY - $BlowerSize / 2',
                          '$BlowerCY + $BlowerSize / 2', bz0, f'{bz0} + $BlowerT')
    spacers = []
    for i, (sx, sy, left, front) in enumerate([('$TopScrewX0', '$TopScrewY0', True, True), ('$TopScrewX1', '$TopScrewY0', False, True)]):   # back: the GPIO header couples the boards
        wx = f'{X0} + $Wall + $SpacerWallGap' if left else f'{X1} - $Wall - $SpacerWallGap'
        wy = f'{Y0} + $Wall + $SpacerWallGap' if front else f'{Y1} - $Wall - $SpacerWallGap'
        body = b.fuse(f'Spacer {i + 1} body', [
            b.cyl(f'Spacer {i + 1} tube', 'z', '$SpacerOD / 2', sx, sy, sz0, sz1),
            b.box(f'Spacer {i + 1} fin x', *((wx, sx) if left else (sx, wx)), f'{sy} - $SpacerFinT / 2', f'{sy} + $SpacerFinT / 2', sz0, sz1),
            b.box(f'Spacer {i + 1} fin y', f'{sx} - $SpacerFinT / 2', f'{sx} + $SpacerFinT / 2', *((wy, sy) if front else (sy, wy)), sz0, sz1),
            *(cradle if i == 0 else [])])
        spacers.append(b.cut(f'Corner spacer {i + 1}', body, b.cyl(f'Spacer {i + 1} bore', 'z', '$SpacerBore / 2', sx, sy, f'{sz0} - 1 mm', f'{sz1} + 1 mm'),
                             refine=True, name=f'Spacer{i + 1}'))

    # Cold-shoe clip mount (printed accessory: PETG, nylon or tough resin). Two pins click into the front mount insets
    # (LedWin*), a tongue hooks into the back slot, both from fingers/arms that hug the R5 bottom rolls; a cold-shoe foot
    # underneath slides into the camera's shoe. Fit: back edge in first (tongue into the slot), press the front down.
    mg, mt, mr = '$MountGap', '$MountArmT', '$BottomEdgeR'
    def roll_band(label, x0, x1, back):
        yc = f'{Y1} - {mr}' if back else f'{Y0} + {mr}'
        ring = b.cut(f'{label} ring', b.cyl(f'{label} outer', 'x', f'{mr} + {mg} + {mt}', yc, mr, x0, x1), b.cyl(f'{label} inner', 'x', f'{mr} + {mg}', yc, mr, f'{x0} - 1 mm', f'{x1} + 1 mm'))
        quad = b.box(f'{label} quadrant', x0, x1, *((yc, f'{Y1} + 10 mm') if back else (f'{Y0} - 10 mm', yc)), '-10 mm', mr)
        return b.common(label, [ring, quad])
    def pin(label, xc, zc, w, hgt, ymin, ymax, at_ymin, at_ymax):
        """Wedge along Y: z range at_ymin(z0, z1) at Ymin, at_ymax(z0, z1) at Ymax (full at the arm face, bottom 0.3 mm at the
        tip: sloped top = lead-in, flat bottom = retention)."""
        z0, z1 = f'{zc} - {hgt} / 2', f'{zc} + {hgt} / 2'
        (za, zb), (zc2, zd) = at_ymin(z0, z1), at_ymax(z0, z1)
        xs = {'Xmin': f'{xc} - {w} / 2', 'Xmax': f'{xc} + {w} / 2', 'X2min': f'{xc} - {w} / 2', 'X2max': f'{xc} + {w} / 2'}
        return b.wedge(label, App.Rotation(), {**xs, 'Ymin': ymin, 'Ymax': ymax, 'Zmin': za, 'Zmax': zb, 'Z2min': zc2, 'Z2max': zd})
    full = lambda z0, z1: (z0, z1)
    tip = lambda z0, z1: (z0, f'{z0} + 0.65 mm')   # >= min wall at the tip
    fx = [(f'$LedWin{i}X0 - $MountFingerMargin', f'$LedWin{i}X0 + $LedWinW + $MountFingerMargin') for i in (1, 2)]
    bx = ('$BackSlotX0 - $MountBackMargin', '$BackSlotX1 + $MountBackMargin')
    ins_z = '($LedWinZ0 + $LedWinZ1) / 2'
    slot_z = '($BackSlotZ0 + $BackSlotZ1) / 2'
    mcx, mcy = f'({X0} + $BodyLength / 2)', f'({Y0} + $BodyWidth / 2)'
    mb0 = f'-({mg}) - $MountBaseT'
    mount_parts = [
        b.box('Mount base', f'{X0} + $CornerR', f'{X1} - $CornerR', f'{Y0} + {mr}', f'{Y1} - {mr}', mb0, f'-({mg})'),
        roll_band('Mount front band', fx[0][0], fx[1][1], False),
        roll_band('Mount back band', bx[0], bx[1], True),
        *[b.box(f'Mount front finger {i + 1}', x0, x1, f'{Y0} - {mg} - {mt}', f'{Y0} - {mg}', mr, '$MountFrontTopZ') for i, (x0, x1) in enumerate(fx)],
        b.box('Mount back arm', *bx, f'{Y1} + {mg}', f'{Y1} + {mg} + {mt}', mr, '$MountBackTopZ'),
        *[pin(f'Mount pin {i}', f'$LedWin{i}X0 + $LedWinW / 2', ins_z, '$MountPinW', '$MountPinH',
              f'{Y0} - {mg} - 0.1 mm', f'{Y0} + $LedWinDepth - $MountPinClear', full, tip) for i in (1, 2)],
        pin('Mount tongue', '($BackSlotX0 + $BackSlotX1) / 2', slot_z, '$MountTongueL', '$MountTongueH',
            f'{Y1} - $BackSlotDepth + $MountPinClear', f'{Y1} + {mg} + 0.1 mm', tip, full),
        b.box('Shoe neck', f'{mcx} - $ShoeNeckW / 2', f'{mcx} + $ShoeNeckW / 2', f'{mcy} - $ShoeFootL / 2', f'{mcy} + $ShoeFootL / 2', f'{mb0} - $ShoeNeckH', mb0),
        b.box('Shoe foot', f'{mcx} - $ShoeFootW / 2', f'{mcx} + $ShoeFootW / 2', f'{mcy} - $ShoeFootL / 2', f'{mcy} + $ShoeFootL / 2',
              f'{mb0} - $ShoeNeckH - $ShoeFootT', f'{mb0} - $ShoeNeckH')]
    mount = b.fuse('Cold-shoe clip mount', mount_parts, refine=True, name='ShoeMount')

    # Button caps (V0.1.0 shape, TPU) directly on the flat GT-TCA84C actuator: domed square cap through the flat top,
    # flange in a shallow channel under the skin.
    buttons = []
    for i in (1, 2, 3):
        y = f'$Button{i}Y'
        flange = b.rrect(f'Button {i} flange', 'xy', '$ButtonX - $FlangeSize / 2', '$ButtonX + $FlangeSize / 2', f'{y} - $FlangeSize / 2', f'{y} + $FlangeSize / 2',
                         '$FlangeR', cz, f'{cz} + $FlangeThickness')
        cap = b.block(f'Button {i} cap', '$ButtonX - $CapSize / 2', '$ButtonX + $CapSize / 2', f'{y} - $CapSize / 2', f'{y} + $CapSize / 2',
                      cz, f'{H} + $CapProtrusion', '$CapR', '$CapTopR', None)
        buttons.append(b.fuse(f'Button {i}', [flange, cap], refine=True, name=f'Button{i}'))


    # Exploded-preview pose: lift the printed top parts (in memory only; keep TopLift at 0 when saving)
    for o in (top, cover_part):
        o.setExpression('Placement.Base.z', 'Preview.TopLift')

    asm = doc.addObject('App::DocumentObjectGroup', 'Assembly')
    asm.Label = '02 · Assembly'
    for o in [top, bottom, cover_part, spreader, pad_part, *spacers, blower, mount, panel_part, view_part, active_part, jig, *buttons]:
        o.Visibility = True
        asm.addObject(o)
    con = doc.addObject('App::DocumentObjectGroup', 'Construction')
    con.Label = '90 · Construction'
    for o in (outer, cavity, shell):
        con.addObject(o)
    return [top, bottom, cover_part, spreader, pad_part, *spacers, blower, mount, panel_part, view_part, active_part, jig, *buttons]


def fpc_path(vs):
    """FPC centre line in the YZ plane, glass edge -> FPC2 entry: flat toward the slot, down the slot, forward
    under the board into the turned FPC2 (route chosen 2026-10-30)."""
    v = lambda n: getattr(vs, n).Value
    t, r = v('FpcThickness'), v('FpcBendR') + v('FpcThickness') / 2
    yv = (v('SlotBackY') + v('SlotFrontY')) / 2
    zf = v('TowerBottomZ') + v('PanelFold') + v('PanelCapThickness') - t / 2
    zc, e = v('Fpc2CableZ'), v('PanelY') - v('PanelWidth') / 2
    return [('line', (e, zf), (yv + r, zf)),                      # flat, from the glass edge toward the slot
            ('arc', (yv + r, zf - r), r, 90, 180),                # down into the slot
            ('line', (yv, zf - r), (yv, zc + r)),                 # down the slot, under the board
            ('arc', (yv - r, zc + r), r, 0, -90),                 # turn forward
            ('line', (yv - r, zc), (v('Fpc2EntryY'), zc))]        # into the FPC2 entry (back face)


def fpc_path_length(vs):
    """Length of the tightest route (fpc_path): the FPC length this layout needs at least."""
    s = 0.0
    for seg in fpc_path(vs):
        s += math.hypot(seg[2][0] - seg[1][0], seg[2][1] - seg[1][1]) if seg[0] == 'line' else seg[2] * math.radians(abs(seg[4] - seg[3]))
    return s


def fpc_curve(vs):
    """Drawn FPC centre line: two smooth cubic Beziers (glass edge -> vertical in the slot at mid board -> FPC2 entry),
    handle scale solved so the free length is the shortest FPC's (FpcLength - FpcLengthTol - Fpc2InsertDepth): the
    taut design case, smooth instead of line + arc kinks. A nominal FPC has FpcLengthTol of slack on top."""
    v = lambda n: getattr(vs, n).Value
    t = v('FpcThickness')
    yv = (v('SlotBackY') + v('SlotFrontY')) / 2
    zf = v('TowerBottomZ') + v('PanelFold') + v('PanelCapThickness') - t / 2
    zm = v('TowerBottomZ') - 0.8          # middle of the 1.6 mm Firehat
    zc, e, ye = v('Fpc2CableZ'), v('PanelY') - v('PanelWidth') / 2, v('Fpc2EntryY')
    P = lambda y, z: App.Vector(0, y, z)

    def bezier(poles):
        c = Part.BezierCurve()
        c.setPoles(poles)
        return c

    def curves(k):
        return [bezier([P(e, zf), P(e - k * (e - yv), zf), P(yv, zm + k * (zf - zm)), P(yv, zm)]),
                bezier([P(yv, zm), P(yv, zm - k * (zm - zc)), P(ye + k * (yv - ye), zc), P(ye, zc)])]
    target, lo, hi = v('FpcLength') - v('FpcLengthTol') - v('Fpc2InsertDepth'), 0.05, 20.0
    for _ in range(60):             # length grows with k toward the staircase route
        k = (lo + hi) / 2
        lo, hi = (k, hi) if sum(c.length() for c in curves(k)) < target else (lo, k)
    return curves((lo + hi) / 2)


def fpc_shape(vs):
    """The FPC as drawn (neck, taper, contact end, alignment holes), bent along fpc_curve; ends at the FPC2 face."""
    v = lambda n: getattr(vs, n).Value
    t, xc = v('FpcThickness'), v('PanelX')
    n0, n1 = v('FpcNeckLength'), v('FpcNeckLength') + v('FpcTaperLength')
    hole_s = v('FpcLength') - v('FpcHoleFromEnd')
    width = lambda s: v('FpcNeckWidth') if s <= n0 else v('FpcWidth') if s >= n1 else v('FpcNeckWidth') + (v('FpcWidth') - v('FpcNeckWidth')) * (s - n0) / (n1 - n0)
    stations, s = [], 0.0          # (s, (y, z), unit normal (ny, nz))
    for c in fpc_curve(vs):
        L, n = c.length(), 60
        for i in range(n + 1):
            u = c.parameterAtDistance(L * i / n, c.FirstParameter)
            p, d = c.value(u), c.tangent(u)[0]
            stations.append((s + L * i / n, (p.y, p.z), (-d.z, d.y)))
        s += L
    wires, last = [], None
    for st, (y, z), (ny, nz) in stations:
        if last is not None and abs(st - last) < 1e-9:
            continue
        last, w = st, width(st)
        pts = [App.Vector(xc + sx * w / 2, y + ny * sn * t / 2, z + nz * sn * t / 2) for sx, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        wires.append(Part.makePolygon(pts + [pts[0]]))
    shape = Part.makeLoft(wires, True, True)
    for st, (y, z), (ny, nz) in stations:
        if st >= hole_s - 1e-6:     # the alignment holes (exact on a straight, nearest arc station otherwise)
            for sx in (-1, 1):
                base = App.Vector(xc + sx * v('FpcHolePitch') / 2, y - ny * t, z - nz * t)
                shape = shape.cut(Part.makeCylinder(v('FpcHoleD') / 2, 2 * t, base, App.Vector(0, ny, nz)))
            break
    return shape.removeSplitter(), s


def fpc_contacts(vs):
    """The FPC contact end inside FPC2: stiffened Fpc2InsertDepth section at the cable height, 30 gold fingers
    (0.3 wide, 0.5 pitch, drawing) on the board-facing side (the turned bottom-contact FPC2 touches them from above)."""
    v = lambda n: getattr(vs, n).Value
    xc, w, t, L = v('PanelX'), v('FpcWidth'), v('FpcContactThickness'), v('Fpc2InsertDepth')
    y1, zc = v('Fpc2EntryY'), v('Fpc2CableZ')
    body = Part.makeBox(w, L, t, App.Vector(xc - w / 2, y1 - L, zc - t / 2))
    fingers = [Part.makeBox(0.3, L - 0.2, 0.021, App.Vector(xc + (i - 14.5) * 0.5 - 0.15, y1 - L + 0.1, zc + t / 2 - 0.001)) for i in range(30)]
    return body.fuse(fingers).removeSplitter()


def main():
    guard()
    params = migrate_params()
    doc = App.newDocument('equip_1_V0_1_5')
    parts = build(doc, params)
    doc.recompute()
    vs = doc.getObject('Parameters')
    fpc, length = fpc_shape(vs)
    fpc_part = doc.addObject('Part::Feature', 'OledFpc')
    fpc_part.Label = 'OLED FPC (reference, generated by build.py from 01 · Parameters; ends at the FPC2 face)'
    fpc_part.Shape = fpc
    doc.getObject('Assembly').addObject(fpc_part)
    parts.append(fpc_part)
    con_part = doc.addObject('Part::Feature', 'OledFpcContacts')
    con_part.Label = 'OLED FPC contact end (reference, inside FPC2)'
    con_part.Shape = fpc_contacts(vs)
    doc.getObject('Assembly').addObject(con_part)
    parts.append(con_part)
    expect = vs.FpcLength.Value - vs.FpcLengthTol.Value - vs.Fpc2InsertDepth.Value
    if fpc_path_length(vs) > expect + 1e-3:
        raise SystemExit(f'FPC route {fpc_path_length(vs):.4f} mm is longer than the shortest FPC allows ({expect:.4f} mm): move the slot / FPC2')
    for name in EXPRESSIONS:   # tooltips of expression-bound parameters show their computed values
        desc = vs.getDocumentationOfProperty(name).split('. Current value:')[0]
        vs.setDocumentationOfProperty(name, f'{desc}. Current value: {getattr(vs, name).Value:g} mm')
    doc.recompute()
    bad = [o.Name for o in doc.Objects if 'Invalid' in o.State or 'Error' in o.State]
    if bad:
        raise SystemExit(f'recompute errors: {bad}')
    summary = {}
    for o in parts:
        s = o.Shape
        bb = s.BoundBox
        summary[o.Name] = dict(solids=len(s.Solids), valid=s.isValid(), volume=round(s.Volume, 2),
                               bbox=[round(v, 3) for v in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)])
    doc.saveAs(str(FCSTD))
    print('BUILD ' + json.dumps({'file': FCSTD.name, 'sha256': sha256(FCSTD), 'parts': summary}, indent=1))
    App.closeDocument(doc.Name)


main()
