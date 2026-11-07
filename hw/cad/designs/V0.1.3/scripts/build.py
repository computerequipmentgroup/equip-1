"""One-time migration: create equip-1-V0.1.3.FCStd from the saved V0.1.2 file.

Every parameter value is read from the predecessor's `01 · Parameters` VarSet (SHA256-pinned),
then the REMOVED / CHANGED / ADDED lists below are applied and the feature tree is regenerated.
NOT a reset command: refuses if the predecessor changed or the output exists
(EQUIP1_CAD_REPLACE=1 backs the existing file up to .build/backup/ and rebuilds).

V0.1.3 = screen cover centred across the case (user request 2026-10-30): the OLED panel is moved
5.31 mm in Y so its active area sits on the case centre line, and the window/cover follow it.
X stays 11.00: a cover centred in X (edge at x 33.34) cuts into the switch 1 pocket (x 32.3) and
leaves a 0.15 mm sliver; the switches are fixed on the Firehat. Same layout as the original
screencover.step (centred in Y only). The panel glue position and FPC route must be confirmed on the board.

Run headless:   FreeCADCmd scripts/build.py
"""
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

import FreeCAD as App
import Part  # noqa: F401  (registers Part feature types)

ROOT = Path(os.environ.get('EQUIP1_CAD_ROOT') or Path(__file__).resolve().parents[1])
FCSTD = ROOT / 'equip-1-V0.1.3.FCStd'
PREDECESSOR = ROOT.parent / 'V0.1.2' / 'equip-1-V0.1.2.FCStd'
PREDECESSOR_SHA = '402f51578ab0bc9d9b59e1ec26b451422dca9e8cfca6c7d70e9cf127c50f6de6'

REMOVED = []

CHANGED = {  # name -> (value, new description or None to keep); values are overridden by EXPRESSIONS
    'WindowCY': (-6.59, 'Screen window centre Y (follows the panel active area = case centre line)'),
    'PanelY': (-4.54, 'OLED panel centre Y: case centre + ActiveAreaOffsetY, so the active area and cover are centred. Glue position and FPC route to confirm on the board'),
}

ADDED = []  # (group, name, value_mm, signed, description)
EXPRESSIONS = {'PanelY': '$BodyY0 + $BodyWidth / 2 + $ActiveAreaOffsetY',
               'WindowCX': '$PanelX', 'WindowCY': '$PanelY - $ActiveAreaOffsetY'}


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
        ('Controls', 'ActuatorProtrusion', '$ActuatorTopZ - $BodyHeight'),
        ('Controls', 'SkinOverSwitch', '$BodyHeight - $SwitchPocketTopZ'),
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
    top_adds = b.common('Top additions (clipped to outer)', [b.fuse('Top additions', towers), outer])
    top_base = b.fuse('Top shell base', [top_raw, top_adds], name='ShellTopBase')
    ceiling = f'{H} - $TopSkin'
    pocket_floor = f'{H} - $WindowPocketDepth'
    wx0, wx1 = '$WindowCX - $WindowLength / 2', '$WindowCX + $WindowLength / 2'
    wy0, wy1 = '$WindowCY - $WindowWidth / 2', '$WindowCY + $WindowWidth / 2'
    c = '($LipInset - $GrooveInset)'
    fillers = [b.box(f'Groove filler front {i}', f'$LipGapFront{i}X0 + {c}', f'$LipGapFront{i}X1 - {c}', f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm', '$SeamZ - 2 mm', '$GrooveTopZ + 1 mm') for i in (1, 2, 3)]
    fillers.append(b.box('Groove filler left', lx0, lx1, f'$LipGapLeftY0 + {c}', f'$LipGapLeftY1 - {c}', '$SeamZ - 2 mm', '$GrooveTopZ + 1 mm'))
    groove = b.cut('Seam groove (with fillers)', inset_rrect('Seam groove', '$GrooveInset', '$SeamZ - 1 mm', '$GrooveTopZ'), b.fuse('Groove fillers', fillers))
    top_cutters = [
        groove,
        *[b.cyl(f'Insert hole {i}', 'z', '$InsertHoleR', sx, sy, '$TowerBottomZ - 1 mm', '$TowerBottomZ + $InsertHoleDepth') for i, (sx, sy) in enumerate(screws_top)],
        b.rrect('Screen-cover pocket', 'xy', wx0, wx1, wy0, wy1, '$WindowR', pocket_floor, f'{H} + 1 mm'),
        b.rrect('Panel opening', 'xy', '$PanelX - $PanelLength / 2 - $PanelClearance', '$PanelX + $PanelLength / 2 + $PanelClearance',
                '$PanelY - $PanelWidth / 2 - $PanelClearance', '$PanelY + $PanelWidth / 2 + $PanelClearance', '$PanelOpeningR', f'{ceiling} - 1 mm', f'{pocket_floor} + 0.1 mm'),
        b.box('PCIe FPC connector pocket', '$PcieFpcPocketX0', '$PcieFpcPocketX1', '$PcieFpcPocketY0', '$PcieFpcPocketY1', f'{ceiling} - 1 mm', f'{pocket_floor} + 0.1 mm'),
        *[b.box(f'Switch {i} pocket', '$ButtonX - $SwitchPocketX / 2', '$ButtonX + $SwitchPocketX / 2', f'$Button{i}Y - $SwitchPocketY / 2', f'$Button{i}Y + $SwitchPocketY / 2',
                f'{ceiling} - 1 mm', '$SwitchPocketTopZ') for i in (1, 2, 3)],
        *[b.cyl(f'Actuator hole {i}', 'z', '$ActuatorHoleD / 2', '$ButtonX', f'$Button{i}Y', f'{ceiling} - 1 mm', f'{H} + 1 mm') for i in (1, 2, 3)],
        usb, centre, roundp, vent_a, vent_b,
        b.box('FireWire connector relief', f'{X0} + $Wall', '$FwReliefX1', '$FwReliefY0', '$FwReliefY1', '$FwReliefZ0', ceiling),
        b.box('FireWire core slot', lx0, lx1, '$FwCoreY0', '$FwCoreY1', '$SeamZ - 1 mm', '$FwCoreZ1'),
        b.rrect('FireWire body', 'yz', '$FwHullY0', '$FwShoulderY', '$FwHullZ0', '$FwHullZ1', '$FwHullR', lx0, lx1),
        b.rrect('FireWire nose', 'yz', '$FwHullY0', '$FwHullY1', '$FwNoseZ0', '$FwNoseZ1', '$FwHullR', lx0, lx1),
        b.wedge('FireWire chamfer', App.Rotation(App.Vector(0, 1, 0), -90), {
            'Ymin': '$FwShoulderY - $FwHullR', 'Ymax': '$FwHullY1 - $FwHullR',
            'Xmin': '$FwHullZ0', 'Xmax': '$FwHullZ1', 'X2min': '$FwNoseZ0', 'X2max': '$FwNoseZ1',
            'Zmin': f'-({lx1})', 'Zmax': f'-({lx0})', 'Z2min': f'-({lx1})', 'Z2max': f'-({lx0})'}),
        b.box('FireWire ear 1', lx0, lx1, '$FwEar1Y0', '$FwHullY0 + 0.3 mm', '$FwEar1Z0', '$FwEar1Z1'),
        b.box('FireWire ear 2', lx0, lx1, '$FwHullY1 - 0.3 mm', '$FwEar2Y1', '$FwEar2Z0', '$FwEar2Z1'),
    ]
    top = b.cut('Shell top', top_base, b.fuse('Top shell cutters', top_cutters, name='ShellTopCutters'), refine=True, name='ShellTop')

    # Bottom shell
    bot_raw = b.common('Bottom shell raw', [shell, b.box('Bottom half-space', *big, '-5 mm', '$SeamZ')])
    lip = b.cut('Lip ring', inset_rrect('Lip outer', '$LipInset', '$SeamZ - 0.5 mm', '$LipTopZ'),
                inset_rrect('Lip inner', '$Wall', '$SeamZ - 1 mm', '$LipTopZ + 1 mm'))
    lip_gaps = [b.box(f'Lip gap front {i}', f'$LipGapFront{i}X0', f'$LipGapFront{i}X1', f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm', '$SeamZ', '$LipTopZ + 1 mm') for i in (1, 2, 3)]
    lip_gaps.append(b.box('Lip gap left', lx0, lx1, '$LipGapLeftY0', '$LipGapLeftY1', '$SeamZ', '$LipTopZ + 1 mm'))
    lip = b.cut('Lip (gapped)', lip, b.fuse('Lip gaps', lip_gaps))
    screws = [('$BotScrewX0', '$BotScrewY0'), ('$BotScrewX1', '$BotScrewY0'), ('$BotScrewX0', '$BotScrewY1'), ('$BotScrewX1', '$BotScrewY1')]
    bosses = [b.cyl(f'Screw boss {i}', 'z', '$BotBossR', sx, sy, '$Floor - 0.5 mm', '$BotBossTopZ') for i, (sx, sy) in enumerate(screws)]
    bot_adds = b.common('Bottom additions (clipped to outer)', [b.fuse('Bottom additions', bosses), outer])
    bot_base = b.fuse('Bottom shell base', [bot_raw, lip, bot_adds], name='ShellBottomBase')
    by0, by1 = f'{Y1} - $BackSlotDepth', f'{Y1} + 1 mm'
    bot_cutters = [
        *[b.cyl(f'Counterbore {i}', 'z', '$CounterboreR', sx, sy, '-1 mm', '$CounterboreTopZ') for i, (sx, sy) in enumerate(screws)],
        *[b.cut(f'Counterbore fillet {i}', b.cyl(f'Counterbore fillet {i} envelope', 'z', '$CounterboreR + $CounterboreFilletR', sx, sy, '-1 mm', '$CounterboreFilletR'),
                b.torus(f'Counterbore fillet {i} torus', '$CounterboreR + $CounterboreFilletR', '$CounterboreFilletR', sx, sy, '$CounterboreFilletR')) for i, (sx, sy) in enumerate(screws)],
        *[b.cyl(f'Clearance hole {i}', 'z', '$ClearanceHoleR', sx, sy, '-1 mm', '$BotBossTopZ + 1 mm') for i, (sx, sy) in enumerate(screws)],
        *[b.stadium(f'Floor vent {i + 1}', 'xy', f'$FloorVentX0 + {i} * $FloorVentPitch - $FloorVentW / 2', f'$FloorVentX0 + {i} * $FloorVentPitch + $FloorVentW / 2',
                    '$FloorVentY0', '$FloorVentY1', '-1 mm', '$Floor + 1 mm') for i in range(5)],
        usb, centre, funnel, roundp, vent_a, vent_b,
        *[b.rrect(f'LED window {i}', 'xz', f'$LedWin{i}X0', f'$LedWin{i}X0 + $LedWinW', '$LedWinZ0', '$LedWinZ1', '$LedWinR', fy0, f'{Y0} + $LedWinDepth') for i in (1, 2)],
        b.rrect('Back recess', 'xz', '$BackSlotX0', '$BackSlotX1', '$BackSlotZ0', '$BackSlotZ1', '$BackSlotR', by0, by1),
        b.box('MicroSD notch', lx0, f'{X0} + $SdNotchDepth', '$SdNotchY0', '$SdNotchY1', '$SdNotchZ0', '$SdNotchZ1'),
        b.rrect('MicroSD spot-face', 'yz', '$SdNotchY0 - $SdFaceMargin', '$SdNotchY1 + $SdFaceMargin', '$SdFaceZ0', '$SdNotchZ1 + $SdFaceMargin',
                '$SdFaceR', lx0, f'{X0} + $SdFaceInset'),
        *[b.box(f'USB-A leg relief {i}', '$UsbALegX - $UsbALegPocketX / 2', '$UsbALegX + $UsbALegPocketX / 2', f'$UsbALeg{i}Y - $UsbALegPocketY / 2',
                f'$UsbALeg{i}Y + $UsbALegPocketY / 2', '$UsbALegPocketZ0', '$Floor + 0.5 mm') for i in (1, 2, 3, 4)],
    ]
    bottom = b.cut('Shell bottom', bot_base, b.fuse('Bottom shell cutters', bot_cutters, name='ShellBottomCutters'), refine=True, name='ShellBottom')

    # Screen cover (same bought part as V0.1.0, centred on the panel's active area, on the case centre line)
    cover = b.rrect('Screen cover body', 'xy', f'{wx0} + $CoverClearance', f'{wx1} - $CoverClearance', f'{wy0} + $CoverClearance',
                    f'{wy1} - $CoverClearance', '$WindowR - $CoverClearance', f'{H} - $CoverThickness', H)
    cover_part = b._hide(doc.addObject('Part::Refine', 'ScreenCover'), 'Screen cover')
    cover_part.Source = cover

    # Reference (bought, not printed): OLED panel from the Liyuan datasheet, glued on the Firehat
    panel = b.box('OLED panel (Liyuan LYA130WG30C, reference)', '$PanelX - $PanelLength / 2', '$PanelX + $PanelLength / 2',
                  '$PanelY - $PanelWidth / 2', '$PanelY + $PanelWidth / 2', '$TowerBottomZ + $PanelFold', '$TowerBottomZ + $PanelFold + $PanelThickness')
    panel_part = b._hide(doc.addObject('Part::Refine', 'OledPanel'), 'OLED panel (reference, bought)')
    panel_part.Source = panel

    # Exploded-preview pose: lift the printed top parts (in memory only; keep TopLift at 0 when saving)
    for o in (top, cover_part):
        o.setExpression('Placement.Base.z', 'Preview.TopLift')

    asm = doc.addObject('App::DocumentObjectGroup', 'Assembly')
    asm.Label = '02 · Assembly'
    for o in [top, bottom, cover_part, panel_part]:
        o.Visibility = True
        asm.addObject(o)
    con = doc.addObject('App::DocumentObjectGroup', 'Construction')
    con.Label = '90 · Construction'
    for o in (outer, cavity, shell):
        con.addObject(o)
    return [top, bottom, cover_part, panel_part]


def main():
    guard()
    params = migrate_params()
    doc = App.newDocument('equip_1_V0_1_2')
    parts = build(doc, params)
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
