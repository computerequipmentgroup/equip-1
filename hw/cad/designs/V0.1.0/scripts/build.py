"""One-time migration: create equip-1-V0.1.0.FCStd from the reference STEP set.

This is NOT a reset command. It refuses to run if the pinned reference STEP files
changed, or if the .FCStd already exists. Set EQUIP1_CAD_REPLACE=1 to rebuild anyway;
the existing file is then moved to .build/backup/ first.

Run headless:   FreeCADCmd scripts/build.py
or in the GUI Python console (see hw/cad/README.md).
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
HW = ROOT.parents[2]
FCSTD = ROOT / 'equip-1-V0.1.0.FCStd'

# Predecessor = the reference STEP set (product commit 0dcb520). Pinned by SHA256.
PINNED = {
    'shell-top.step': '6e45d2aa1a6f75b0777dc0c09d0958205acb28b7186a016cad99a152808c9201',
    'shell-bot.step': 'e3153cfc0ddb580f496981a8234c450a0d5d693994192e9ea737e3cb7c1646de',
    'screencover.step': '70606ab7f423716c9ab93e81538093b81104e102e3cab1c95a0a3040fef77793',
    'buttons.step': 'f9bde9392342eaa039214dc3f5bab98b7d91764eadcdc46e42e3c4f224fabbbf',
}

# (group, name, value_mm, signed, description). Values measured from the reference STEPs
# (wiki: sources/2026-10-29-reference-enclosure-step). Coordinates use the reference frame.
PARAMS = [
    ('Body', 'BodyX0', -23.32, True, 'Outer left face X (reference frame origin is off-centre)'),
    ('Body', 'BodyY0', -36.89, True, 'Outer front face Y (port side)'),
    ('Body', 'BodyLength', 72.10, False, 'Outer size along X'),
    ('Body', 'BodyWidth', 60.60, False, 'Outer size along Y'),
    ('Body', 'BodyHeight', 24.00, False, 'Outer height, bottom at Z=0'),
    ('Body', 'CornerR', 5.30, False, 'Outer vertical corner radius'),
    ('Body', 'TopEdgeR', 8.00, False, 'Outer top edge roll radius'),
    ('Body', 'BottomEdgeR', 4.00, False, 'Outer bottom edge radius'),
    ('Body', 'Wall', 2.00, False, 'Side wall thickness (inner radii = outer minus this)'),
    ('Body', 'TopSkin', 2.00, False, 'Top skin thickness'),
    ('Body', 'Floor', 2.00, False, 'Floor thickness'),
    ('Seam', 'SeamZ', 7.50, True, 'Split height between bottom and top shell'),
    ('Seam', 'LipTopZ', 9.10, True, 'Top of bottom-shell locating lip'),
    ('Seam', 'GrooveTopZ', 9.50, True, 'Top of top-shell groove that receives the lip'),
    ('Seam', 'LipInset', 1.20, False, 'Lip outer face inset from outer wall'),
    ('Seam', 'GrooveInset', 0.80, False, 'Groove inset from outer wall (top-shell skin at seam)'),
    ('Seam', 'LipGapFront1X0', -16.80, True, 'Front lip gap 1 start X (around USB-C)'),
    ('Seam', 'LipGapFront1X1', -2.73, True, 'Front lip gap 1 end X'),
    ('Seam', 'LipGapFront2X0', 1.13, True, 'Front lip gap 2 start X (around centre port)'),
    ('Seam', 'LipGapFront2X1', 21.05, True, 'Front lip gap 2 end X'),
    ('Seam', 'LipGapFront3X0', 27.59, True, 'Front lip gap 3 start X (around round port)'),
    ('Seam', 'LipGapFront3X1', 38.29, True, 'Front lip gap 3 end X'),
    ('Seam', 'LipGapLeftY0', -1.87, True, 'Left lip gap start Y (under FireWire opening)'),
    ('Seam', 'LipGapLeftY1', 17.33, True, 'Left lip gap end Y'),
    ('Fasteners', 'TopScrewX0', -17.50, True, 'Top insert towers, left X'),
    ('Fasteners', 'TopScrewX1', 40.50, True, 'Top insert towers, right X'),
    ('Fasteners', 'TopScrewY0', -31.10, True, 'Top insert towers, front Y'),
    ('Fasteners', 'TopScrewY1', 17.90, True, 'Top insert towers, back Y'),
    ('Fasteners', 'BotScrewX0', -17.35, True, 'Bottom screw holes, left X (reference is 0.15 off the towers)'),
    ('Fasteners', 'BotScrewX1', 40.50, True, 'Bottom screw holes, right X'),
    ('Fasteners', 'BotScrewY0', -31.10, True, 'Bottom screw holes, front Y'),
    ('Fasteners', 'BotScrewY1', 17.82, True, 'Bottom screw holes, back Y (reference is 0.08 off the towers)'),
    ('Fasteners', 'TowerR', 4.15, False, 'Top insert tower radius'),
    ('Fasteners', 'TowerBottomZ', 18.00, True, 'Top insert tower bottom Z'),
    ('Fasteners', 'InsertHoleR', 2.20, False, 'Top tower blind hole radius'),
    ('Fasteners', 'InsertHoleDepth', 3.00, False, 'Top tower blind hole depth'),
    ('Fasteners', 'BotBossR', 4.15, False, 'Bottom screw boss radius'),
    ('Fasteners', 'BotBossTopZ', 3.60, True, 'Bottom screw boss top Z'),
    ('Fasteners', 'ClearanceHoleR', 1.50, False, 'Bottom screw clearance hole radius'),
    ('Fasteners', 'CounterboreR', 2.35, False, 'Bottom screw head counterbore radius'),
    ('Fasteners', 'CounterboreTopZ', 2.20, True, 'Counterbore floor Z'),
    ('Fasteners', 'CounterboreFilletR', 0.80, False, 'Counterbore mouth fillet radius'),
    ('Display', 'WindowX0', -11.71, True, 'Screen-cover pocket left X'),
    ('Display', 'WindowX1', 29.71, True, 'Screen-cover pocket right X'),
    ('Display', 'WindowY0', -21.44, True, 'Screen-cover pocket front Y'),
    ('Display', 'WindowY1', 8.26, True, 'Screen-cover pocket back Y'),
    ('Display', 'WindowR', 4.00, False, 'Screen-cover pocket corner radius'),
    ('Display', 'WindowPocketDepth', 1.30, False, 'Screen-cover pocket depth from top'),
    ('Display', 'CoverThickness', 1.00, False, 'Screen cover thickness (top flush with body)'),
    ('Display', 'FrameMargin', 1.00, False, 'Display frame ring offset beyond the pocket outline'),
    ('Display', 'FrameThickness', 0.80, False, 'Display frame ring thickness below the top skin'),
    ('Display', 'ApertureX0', -8.60, True, 'Display aperture left X'),
    ('Display', 'ApertureX1', 26.60, True, 'Display aperture right X'),
    ('Display', 'ApertureY0', -20.94, True, 'Display aperture front Y'),
    ('Display', 'ApertureY1', 3.26, True, 'Display aperture back Y'),
    ('Display', 'TopTabX0', 4.00, True, 'Aperture back tab left X'),
    ('Display', 'TopTabX1', 14.03, True, 'Aperture back tab right X'),
    ('Display', 'TopTabY1', 7.20, True, 'Aperture back tab end Y'),
    ('Display', 'BotTabX0', 2.00, True, 'Aperture front tab left X (FPC side, inferred)'),
    ('Display', 'BotTabX1', 16.00, True, 'Aperture front tab right X'),
    ('Display', 'BotTabY0', -24.94, True, 'Aperture front tab end Y'),
    ('Display', 'TabR', 1.00, False, 'Aperture tab corner radius'),
    ('Controls', 'ButtonX', 35.71, True, 'Button column centre X'),
    ('Controls', 'Button1Y', -14.59, True, 'Button 1 centre Y (front)'),
    ('Controls', 'Button2Y', -6.59, True, 'Button 2 centre Y'),
    ('Controls', 'Button3Y', 1.25, True, 'Button 3 centre Y (back)'),
    ('Controls', 'ButtonHoleSize', 7.00, False, 'Square button hole size'),
    ('Controls', 'ButtonHole1R', 2.00, False, 'Button hole 1 corner radius'),
    ('Controls', 'ButtonHole2R', 2.00, False, 'Button hole 2 corner radius'),
    ('Controls', 'ButtonHole3R', 2.20, False, 'Button hole 3 corner radius'),
    ('Controls', 'Cap1Size', 6.60, False, 'Button 1 cap size'),
    ('Controls', 'Cap2Size', 6.70, False, 'Button 2 cap size'),
    ('Controls', 'Cap3Size', 6.60, False, 'Button 3 cap size'),
    ('Controls', 'Cap1R', 1.80, False, 'Button 1 cap corner radius'),
    ('Controls', 'Cap2R', 1.85, False, 'Button 2 cap corner radius'),
    ('Controls', 'Cap3R', 2.00, False, 'Button 3 cap corner radius'),
    ('Controls', 'Flange1Size', 7.40, False, 'Button 1 retaining flange size'),
    ('Controls', 'Flange2Size', 7.50, False, 'Button 2 retaining flange size'),
    ('Controls', 'Flange3Size', 7.40, False, 'Button 3 retaining flange size'),
    ('Controls', 'Flange1R', 2.20, False, 'Button 1 flange corner radius'),
    ('Controls', 'Flange2R', 2.25, False, 'Button 2 flange corner radius'),
    ('Controls', 'Flange3R', 2.40, False, 'Button 3 flange corner radius'),
    ('Controls', 'FlangeBottomZ', 19.40, True, 'Button flange bottom Z'),
    ('Controls', 'CapTopZ', 25.50, True, 'Button cap top Z'),
    ('Controls', 'CapTopR', 2.00, False, 'Button cap top edge radius'),
    ('Ports', 'UsbX0', -14.17, True, 'Front USB-C opening left X'),
    ('Ports', 'UsbX1', -5.23, True, 'Front USB-C opening right X'),
    ('Ports', 'UsbZ0', 5.14, True, 'Front USB-C opening bottom Z'),
    ('Ports', 'UsbZ1', 7.81, True, 'Front USB-C opening top Z'),
    ('Ports', 'UsbR', 1.28, False, 'Front USB-C opening corner radius'),
    ('Ports', 'CentrePortX0', 3.35, True, 'Front centre port left X (HDMI-shaped, inferred)'),
    ('Ports', 'CentrePortX1', 18.75, True, 'Front centre port right X'),
    ('Ports', 'CentrePortZ0', 6.88, True, 'Front centre port upper section bottom Z'),
    ('Ports', 'CentrePortZ1', 11.02, True, 'Front centre port top Z'),
    ('Ports', 'CentrePortR', 1.00, False, 'Front centre port corner radius'),
    ('Ports', 'FunnelZ0', 5.57, True, 'Front centre port funnel bottom Z'),
    ('Ports', 'FunnelZ1', 7.20, True, 'Front centre port funnel top Z'),
    ('Ports', 'FunnelHalfW0', 5.17, False, 'Funnel half-width at its bottom'),
    ('Ports', 'FunnelHalfW1', 7.00, False, 'Funnel half-width at its top'),
    ('Ports', 'RoundPortX', 33.45, True, 'Front round port centre X'),
    ('Ports', 'RoundPortZ', 7.24, True, 'Front round port centre Z'),
    ('Ports', 'RoundPortR', 3.15, False, 'Front round port radius'),
    ('Ports', 'LedWin1X0', -3.09, True, 'Front blind window 1 left X (LED, inferred)'),
    ('Ports', 'LedWin2X0', 21.91, True, 'Front blind window 2 left X (LED, inferred)'),
    ('Ports', 'LedWinW', 4.76, False, 'Front blind window width'),
    ('Ports', 'LedWinZ0', 4.05, True, 'Front blind window bottom Z'),
    ('Ports', 'LedWinZ1', 6.95, True, 'Front blind window top Z'),
    ('Ports', 'LedWinR', 1.40, False, 'Front blind window corner radius'),
    ('Ports', 'LedWinDepth', 1.00, False, 'Front blind window depth (leaves 1 mm skin)'),
    ('Ports', 'FwHullY0', 1.65, True, 'Left FireWire opening, rounded end Y'),
    ('Ports', 'FwShoulderY', 13.00, True, 'Left FireWire opening, end of full-height section Y'),
    ('Ports', 'FwHullY1', 14.15, True, 'Left FireWire opening, chamfered nose Y'),
    ('Ports', 'FwHullZ0', 8.19, True, 'Left FireWire opening bottom Z'),
    ('Ports', 'FwHullZ1', 15.59, True, 'Left FireWire opening top Z'),
    ('Ports', 'FwNoseZ0', 9.34, True, 'Left FireWire nose bottom Z'),
    ('Ports', 'FwNoseZ1', 14.44, True, 'Left FireWire nose top Z'),
    ('Ports', 'FwHullR', 1.05, False, 'Left FireWire opening corner radius'),
    ('Ports', 'FwCoreY0', 2.55, True, 'Left FireWire core slot start Y (open to seam)'),
    ('Ports', 'FwCoreY1', 11.85, True, 'Left FireWire core slot end Y'),
    ('Ports', 'FwCoreZ1', 16.30, True, 'Left FireWire core slot top Z'),
    ('Ports', 'FwEar1Y0', 0.95, True, 'Left FireWire ear 1 outer Y'),
    ('Ports', 'FwEar1Z0', 9.10, True, 'Left FireWire ear 1 bottom Z'),
    ('Ports', 'FwEar1Z1', 14.70, True, 'Left FireWire ear 1 top Z'),
    ('Ports', 'FwEar2Y1', 14.85, True, 'Left FireWire ear 2 outer Y'),
    ('Ports', 'FwEar2Z0', 10.45, True, 'Left FireWire ear 2 bottom Z'),
    ('Ports', 'FwEar2Z1', 13.35, True, 'Left FireWire ear 2 top Z'),
    ('Ports', 'SdNotchY0', -12.20, True, 'Left bottom notch start Y (microSD access, inferred)'),
    ('Ports', 'SdNotchY1', 0.21, True, 'Left bottom notch end Y'),
    ('Ports', 'SdNotchZ0', 1.80, True, 'Left bottom notch floor Z'),
    ('Ports', 'SdNotchZ1', 3.85, True, 'Left bottom notch top Z'),
    ('Ports', 'SdNotchDepth', 4.00, False, 'Left bottom notch depth from outer wall'),
    ('Ports', 'VentAY0', -20.27, True, 'Right side vent A start Y'),
    ('Ports', 'VentAY1', -6.77, True, 'Right side vent A end Y'),
    ('Ports', 'VentBY0', -1.55, True, 'Right side vent B start Y'),
    ('Ports', 'VentBY1', 11.95, True, 'Right side vent B end Y'),
    ('Ports', 'VentZ0', 6.32, True, 'Right side vents bottom Z'),
    ('Ports', 'VentZ1', 12.20, True, 'Right side vents top Z'),
    ('Ports', 'VentR', 0.80, False, 'Right side vent corner radius'),
    ('Ports', 'BackSlotX0', 0.96, True, 'Back slot left X'),
    ('Ports', 'BackSlotX1', 23.87, True, 'Back slot right X'),
    ('Ports', 'BackSlotZ0', 4.29, True, 'Back slot bottom Z'),
    ('Ports', 'BackSlotZ1', 6.69, True, 'Back slot top Z'),
    ('Ports', 'BackSlotR', 1.00, False, 'Back slot corner radius'),
    ('Ports', 'BackSlotDepth', 1.20, False, 'Back slot depth from outer wall (blind recess)'),
    ('Ports', 'FloorVentX0', -5.27, True, 'Floor vent slot 1 centre X'),
    ('Ports', 'FloorVentPitch', 9.00, False, 'Floor vent slot pitch along X (5 slots)'),
    ('Ports', 'FloorVentY0', -23.11, True, 'Floor vent slots front Y'),
    ('Ports', 'FloorVentY1', 9.89, True, 'Floor vent slots back Y'),
    ('Ports', 'FloorVentW', 3.00, False, 'Floor vent slot width'),
    ('Clearances', 'CoverClearance', 0.30, False, 'Screen cover to pocket wall gap'),
    ('Clearances', 'MinWall', 0.60, False, 'Minimum wall/skin thickness accepted by verify.py (resin)'),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guard():
    for name, digest in PINNED.items():
        got = sha256(HW / name)
        if got != digest:
            raise SystemExit(f'refusing: {name} SHA256 {got} != pinned {digest}')
    if FCSTD.exists():
        if os.environ.get('EQUIP1_CAD_REPLACE') != '1':
            raise SystemExit(f'refusing: {FCSTD.name} exists (migration runs once; EQUIP1_CAD_REPLACE=1 backs it up and rebuilds)')
        backup = ROOT / '.build' / 'backup'
        backup.mkdir(parents=True, exist_ok=True)
        shutil.move(str(FCSTD), backup / f'{FCSTD.stem}-{time.strftime("%Y%m%d-%H%M%S")}.FCStd')


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

    def dome(self, label, rp, rt, cx, cy, zc):
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
        rev = self._hide(self.doc.addObject('Part::Revolution', 'Dome'), label)
        rev.Source, rev.Axis, rev.Angle, rev.Solid = self.common(f'{label} profile', [disc, quad]), App.Vector(0, 0, 1), 360, True
        for ax, v in zip('xyz', (cx, cy, zc)):
            self._set(rev, f'Base.{ax}', v)
        return rev

    def block(self, label, x0, x1, y0, y1, z0, z1, rp, rt, rb):
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
            trims.append(self.cut(f'{label} corner trim', box, self.dome(f'{label} corner dome', rp, rt, cx, cy, zc)))
        top = self.cut(f'{label} upper (smooth corners)', top, self.fuse(f'{label} corner trims', trims))
        if not rb:
            return top
        cx0, cx1, cy0, cy1 = f'({x0}) + ({rp})', f'({x1}) - ({rp})', f'({y0}) + ({rp})', f'({y1}) - ({rp})'
        pieces = [self.rrect(f'{label} bottom slab', 'xy', f'({x0}) + ({rb})', f'({x1}) - ({rb})', f'({y0}) + ({rb})', f'({y1}) - ({rb})',
                             f'({rp}) - ({rb})', z0, f'{zt} + 0.01 mm')]
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


def build(doc):
    b = Builder(doc)

    vs = doc.addObject('App::VarSet', 'Parameters')
    vs.Label = '01 · Parameters'
    for group, name, value, signed, desc in PARAMS:
        vs.addProperty('App::PropertyDistance' if signed else 'App::PropertyLength', name, group, f'{desc}. Current value: {value:g} mm')
        setattr(vs, name, value)

    pv = doc.addObject('App::VarSet', 'Preview')
    pv.Label = '03 · Preview inputs'
    pv.addProperty('App::PropertyLength', 'ButtonPress', 'Pose', 'Moves all button caps down for mechanism previews. Keep 0 mm when saving. Current value: 0 mm')

    out = doc.addObject('App::VarSet', 'Outputs')
    out.Label = '04 · Outputs'
    outputs = [
        ('Envelope', 'EnvelopeLength', '$BodyLength'), ('Envelope', 'EnvelopeWidth', '$BodyWidth'),
        ('Envelope', 'EnvelopeHeight', '$CapTopZ'),
        ('Envelope', 'CavityLength', '$BodyLength - 2 * $Wall'), ('Envelope', 'CavityWidth', '$BodyWidth - 2 * $Wall'),
        ('Envelope', 'CavityHeight', '$BodyHeight - $TopSkin - $Floor'),
        ('Seam', 'SeamLateralClearance', '$LipInset - $GrooveInset'), ('Seam', 'SeamVerticalClearance', '$GrooveTopZ - $LipTopZ'),
        ('Seam', 'LipThickness', '$Wall - $LipInset'),
        ('Display', 'ScreenCoverFloorGap', '$WindowPocketDepth - $CoverThickness'),
        ('Display', 'PocketCeilingSkin', '$TopSkin - $WindowPocketDepth'),
        ('Controls', 'ButtonProtrusion', '$CapTopZ - $BodyHeight'),
        ('Controls', 'Button1SideClearance', '($ButtonHoleSize - $Cap1Size) / 2'),
    ]
    for group, name, expr in outputs:
        out.addProperty('App::PropertyLength', name, group, 'Derived, read-only (see expression).')
        out.setExpression(name, X(expr))
        out.setPropertyStatus(name, 'ReadOnly')

    # Shared body
    X0, Y0, H = '$BodyX0', '$BodyY0', '$BodyHeight'
    X1, Y1 = '$BodyX0 + $BodyLength', '$BodyY0 + $BodyWidth'
    outer = b.block('Outer body', X0, X1, Y0, Y1, '0 mm', H, '$CornerR', '$TopEdgeR', '$BottomEdgeR')
    cavity = b.block('Cavity', f'{X0} + $Wall', f'{X1} - $Wall', f'{Y0} + $Wall', f'{Y1} - $Wall', '$Floor', f'{H} - $TopSkin',
                     '$CornerR - $Wall', '$TopEdgeR - $Wall', '$BottomEdgeR - $Wall')
    shell = b.cut('Hollow shell', outer, cavity)
    big = ('$BodyX0 - 5 mm', '$BodyX0 + $BodyLength + 5 mm', '$BodyY0 - 5 mm', '$BodyY0 + $BodyWidth + 5 mm')

    def inset_rrect(label, inset, z0, z1):
        return b.rrect(label, 'xy', f'{X0} + {inset}', f'{X1} - {inset}', f'{Y0} + {inset}', f'{Y1} - {inset}', f'$CornerR - {inset}', z0, z1)

    # Cutters shared by both shells (wall openings spanning the seam)
    fy0, fy1 = f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm'
    usb = b.rrect('USB-C opening', 'xz', '$UsbX0', '$UsbX1', '$UsbZ0', '$UsbZ1', '$UsbR', fy0, fy1)
    centre = b.rrect('Centre port upper', 'xz', '$CentrePortX0', '$CentrePortX1', '$CentrePortZ0', '$CentrePortZ1', '$CentrePortR', fy0, fy1)
    cx = '($CentrePortX0 + $CentrePortX1) / 2'
    funnel = b.wedge('Centre port funnel', App.Rotation(App.Vector(1, 0, 0), 90), {
        'Ymin': '$FunnelZ0', 'Ymax': '$FunnelZ1',
        'Xmin': f'{cx} - $FunnelHalfW0', 'Xmax': f'{cx} + $FunnelHalfW0', 'X2min': f'{cx} - $FunnelHalfW1', 'X2max': f'{cx} + $FunnelHalfW1',
        'Zmin': f'-({fy1})', 'Zmax': f'-({fy0})', 'Z2min': f'-({fy1})', 'Z2max': f'-({fy0})'})
    roundp = b.cyl('Round port', 'y', '$RoundPortR', '$RoundPortX', '$RoundPortZ', fy0, fy1)
    rx0, rx1 = f'{X1} - $Wall - 1 mm', f'{X1} + 1 mm'
    vent_a = b.rrect('Right vent A', 'yz', '$VentAY0', '$VentAY1', '$VentZ0', '$VentZ1', '$VentR', rx0, rx1)
    vent_b = b.rrect('Right vent B', 'yz', '$VentBY0', '$VentBY1', '$VentZ0', '$VentZ1', '$VentR', rx0, rx1)

    # Top shell
    top_raw = b.common('Top shell raw', [shell, b.box('Top half-space', *big, '$SeamZ', f'{H} + 5 mm')])
    towers = [b.cyl(f'Insert tower {i}', 'z', '$TowerR', sx, sy, '$TowerBottomZ', f'{H} - $TopSkin + 0.5 mm')
              for i, (sx, sy) in enumerate([('$TopScrewX0', '$TopScrewY0'), ('$TopScrewX1', '$TopScrewY0'), ('$TopScrewX0', '$TopScrewY1'), ('$TopScrewX1', '$TopScrewY1')])]
    frame = b.rrect('Display frame ring', 'xy', '$WindowX0 - $FrameMargin', '$WindowX1 + $FrameMargin', '$WindowY0 - $FrameMargin', '$WindowY1 + $FrameMargin',
                    '$WindowR + $FrameMargin', f'{H} - $TopSkin - $FrameThickness', f'{H} - $TopSkin + 0.5 mm')
    top_adds = b.common('Top additions (clipped to outer)', [b.fuse('Top additions', towers + [frame]), outer])
    lx0, lx1 = f'{X0} - 1 mm', f'{X0} + $Wall + 1 mm'
    top_base = b.fuse('Top shell base', [top_raw, top_adds], name='ShellTopBase')
    pocket_floor = f'{H} - $WindowPocketDepth'
    c = '($LipInset - $GrooveInset)'  # in-plane clearance between lip gap and groove filler
    fillers = [b.box(f'Groove filler front {i}', f'$LipGapFront{i}X0 + {c}', f'$LipGapFront{i}X1 - {c}', f'{Y0} - 1 mm', f'{Y0} + $Wall + 1 mm', '$SeamZ - 2 mm', '$GrooveTopZ + 1 mm') for i in (1, 2, 3)]
    fillers.append(b.box('Groove filler left', lx0, lx1, f'$LipGapLeftY0 + {c}', f'$LipGapLeftY1 - {c}', '$SeamZ - 2 mm', '$GrooveTopZ + 1 mm'))
    groove = b.cut('Seam groove (with fillers)', inset_rrect('Seam groove', '$GrooveInset', '$SeamZ - 1 mm', '$GrooveTopZ'), b.fuse('Groove fillers', fillers))
    top_cutters = [
        groove,
        *[b.cyl(f'Insert hole {i}', 'z', '$InsertHoleR', sx, sy, '$TowerBottomZ - 1 mm', '$TowerBottomZ + $InsertHoleDepth')
          for i, (sx, sy) in enumerate([('$TopScrewX0', '$TopScrewY0'), ('$TopScrewX1', '$TopScrewY0'), ('$TopScrewX0', '$TopScrewY1'), ('$TopScrewX1', '$TopScrewY1')])],
        b.rrect('Screen-cover pocket', 'xy', '$WindowX0', '$WindowX1', '$WindowY0', '$WindowY1', '$WindowR', pocket_floor, f'{H} + 1 mm'),
        b.box('Display aperture', '$ApertureX0', '$ApertureX1', '$ApertureY0', '$ApertureY1', f'{H} - $TopSkin - $FrameThickness - 1 mm', pocket_floor),
        b.rrect('Aperture back tab', 'xy', '$TopTabX0', '$TopTabX1', '$ApertureY1 - 1 mm', '$TopTabY1', '$TabR', f'{H} - $TopSkin - $FrameThickness - 1 mm', pocket_floor),
        b.rrect('Aperture front tab', 'xy', '$BotTabX0', '$BotTabX1', '$BotTabY0', '$ApertureY0 + 1 mm', '$TabR', f'{H} - $TopSkin - $FrameThickness - 1 mm', pocket_floor),
        *[b.rrect(f'Button hole {i}', 'xy', '$ButtonX - $ButtonHoleSize / 2', '$ButtonX + $ButtonHoleSize / 2', f'$Button{i}Y - $ButtonHoleSize / 2',
                  f'$Button{i}Y + $ButtonHoleSize / 2', f'$ButtonHole{i}R', f'{H} - $TopSkin - 1 mm', f'{H} + 1 mm') for i in (1, 2, 3)],
        usb, centre, roundp, vent_a, vent_b,
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
    bosses = [b.cyl(f'Screw boss {i}', 'z', '$BotBossR', sx, sy, '$Floor - 0.5 mm', '$BotBossTopZ')
              for i, (sx, sy) in enumerate([('$BotScrewX0', '$BotScrewY0'), ('$BotScrewX1', '$BotScrewY0'), ('$BotScrewX0', '$BotScrewY1'), ('$BotScrewX1', '$BotScrewY1')])]
    bot_adds = b.common('Bottom additions (clipped to outer)', [b.fuse('Bottom additions', bosses), outer])
    bot_base = b.fuse('Bottom shell base', [bot_raw, lip, bot_adds], name='ShellBottomBase')
    screws = [('$BotScrewX0', '$BotScrewY0'), ('$BotScrewX1', '$BotScrewY0'), ('$BotScrewX0', '$BotScrewY1'), ('$BotScrewX1', '$BotScrewY1')]
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
        b.rrect('Back slot', 'xz', '$BackSlotX0', '$BackSlotX1', '$BackSlotZ0', '$BackSlotZ1', '$BackSlotR', by0, by1),
        b.box('MicroSD notch', lx0, f'{X0} + $SdNotchDepth', '$SdNotchY0', '$SdNotchY1', '$SdNotchZ0', '$SdNotchZ1'),
    ]
    bottom = b.cut('Shell bottom', bot_base, b.fuse('Bottom shell cutters', bot_cutters, name='ShellBottomCutters'), refine=True, name='ShellBottom')

    # Screen cover
    cover = b.rrect('Screen cover body', 'xy', '$WindowX0 + $CoverClearance', '$WindowX1 - $CoverClearance', '$WindowY0 + $CoverClearance',
                    '$WindowY1 - $CoverClearance', '$WindowR - $CoverClearance', f'{H} - $CoverThickness', H)
    cover_part = b._hide(doc.addObject('Part::Refine', 'ScreenCover'), 'Screen cover')
    cover_part.Source = cover

    # Buttons (preview: @ButtonPress moves them down)
    buttons = []
    for i in (1, 2, 3):
        y, d = f'$Button{i}Y', '@ButtonPress'
        flange = b.rrect(f'Button {i} flange', 'xy', f'$ButtonX - $Flange{i}Size / 2', f'$ButtonX + $Flange{i}Size / 2', f'{y} - $Flange{i}Size / 2',
                         f'{y} + $Flange{i}Size / 2', f'$Flange{i}R', f'$FlangeBottomZ - {d}', f'{H} - $TopSkin - {d}')
        cap = b.block(f'Button {i} cap', f'$ButtonX - $Cap{i}Size / 2', f'$ButtonX + $Cap{i}Size / 2', f'{y} - $Cap{i}Size / 2', f'{y} + $Cap{i}Size / 2',
                      f'{H} - $TopSkin - {d} - 0.2 mm', f'$CapTopZ - {d}', f'$Cap{i}R', '$CapTopR', None)
        buttons.append(b.fuse(f'Button {i}', [flange, cap], refine=True, name=f'Button{i}'))

    asm = doc.addObject('App::DocumentObjectGroup', 'Assembly')
    asm.Label = '02 · Assembly'
    for o in [top, bottom, cover_part, *buttons]:
        o.Visibility = True
        asm.addObject(o)
    con = doc.addObject('App::DocumentObjectGroup', 'Construction')
    con.Label = '90 · Construction'
    for o in (outer, cavity, shell):
        con.addObject(o)
    return [top, bottom, cover_part, *buttons]


def main():
    guard()
    doc = App.newDocument('equip_1_V0_1_0')
    parts = build(doc)
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
