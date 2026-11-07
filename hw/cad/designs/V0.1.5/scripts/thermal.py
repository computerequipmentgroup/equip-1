"""Steady-state thermal estimate (FreeCAD FEM + CalculiX): ROCK 2F + Firehat in the V0.1.5 case (blower).

Conduction model on a simplified, measured geometry: the case envelope, walls and screw towers/bosses from the saved
.FCStd, both boards as slabs, the hot chips as blocks at their measured positions, and the air as a solid with an
effective conductivity (enclosed natural convection + internal radiation). Outside: convection + radiation as one
film coefficient per face. A vent outlet removes rho*cp*Q*(T_air - T_amb), Q from the stack (chimney) formula, or for the
blower from its fan curve against the inlet/outlet losses. The air does not flow in this model (conduction only), so
the blower runs twice: still air (pessimistic) and well-mixed air (k_air raised; optimistic) - the truth is between.

Rough, for comparing variants (sealed / vents / heatsink); not a thermal qualification. Powers are estimates
(no measured ROCK 2F figures). Everything is linear except the vent flow, so temperature rises scale with power.

  FreeCADCmd scripts/thermal.py          -> .build/thermal/ (results.md, one PNG per variant)
"""
import json
import math
import os
from pathlib import Path

import FreeCAD as App
import Part

ROOT = Path(os.environ.get('EQUIP1_CAD_ROOT') or Path(__file__).resolve().parents[1])
OUT = ROOT / '.build' / 'thermal'
T_AMB = 25.0                                   # °C room
# W, estimates: RK3528A under sustained load, LPDDR4, Wi-Fi module, PMIC/regulators spread in the ROCK PCB,
# VIA VT6315N (PCIe 1394a controller) and the TLV775 3.3 V LDO on the Firehat underside.
POWER = {'soc': 2.0, 'dram': 0.3, 'wifi': 0.4, 'rock_pcb': 0.7, 'vt6315n': 0.6, 'ldo': 0.25}
K = {'shell': 0.2, 'air': 0.07, 'pcb': 20.0, 'chip': 10.0, 'alu': 200.0, 'pad': 6.0}   # W/m/K (air: effective, see doc; PCB: multilayer in-plane, 10 = pessimistic)
H_OUT = {'top': 10.0, 'side': 10.0, 'bottom': 8.0}                         # W/m²K (camera-mounted: air all round; 4 on a desk)
RHO_CP, G, CD = 1.2 * 1005.0, 9.81, 0.6

# Measured 2026-11-01 from the board STEPs placed as in verify.py (case coordinates, mm): x0, x1, y0, y1, z0, z1
ROCK_PCB = (-21.04, 43.96, -34.58, 21.46, 3.6, 4.8)
FH_PCB = (-21.0, 44.0, -34.6, 21.4, 16.49, 18.0)
CHIPS = {  # name: (cx, cy, sx, sy, z0, z1)
    'soc': (5.1, -9.9, 13.5, 13.3, 4.8, 5.8),         # RK3528A
    'dram': (3.9, 8.8, 13.6, 12.1, 4.8, 5.7),
    'wifi': (23.7, -24.2, 6.0, 5.5, 4.8, 6.0),
    'vt6315n': (11.15, -5.32, 7.0, 7.0, 15.59, 16.49),  # KiCad 132.15, 70.72 (bottom)
    'ldo': (18.95, 3.9, 3.0, 1.7, 15.39, 16.49),        # U2, KiCad 139.95, 61.5 (bottom)
}
HEATSINK = (5.1, -9.9, 14.0, 14.0, 5.8, 10.05)      # the glued 14 x 14 x 4 mm finned heatsink + 0.25 mm tape (solid block here)
VENT_SETS = {  # (wall, u0, u1, z0, z1): inlets low just above the ROCK board (below the seam), outlets high under the Firehat
    'low left / high front+right': {'in': [('left', -30.0, -3.0, 5.3, 7.3)],
                                    'out': [('front', 18.0, 40.0, 12.0, 16.0), ('right', -31.0, -22.0, 12.0, 16.0)]},
    'diagonal: low right / high left': {'in': [('right', -32.0, -21.0, 5.0, 7.3), ('right', 12.6, 18.5, 5.0, 7.3)],
                                        'out': [('left', -30.0, -1.0, 12.0, 16.2)]},
    'sketch: in low back-left corner / out high right-front': {'in': [('back', -18.0, -14.6, 5.0, 7.3), ('left', 15.0, 18.5, 5.0, 7.3)],
                                                              'out': [('right', -32.0, -21.0, 12.0, 18.0)], 'open': 0.5},
    'recommended: in low left-front / out high right-front': {'in': [('left', -30.0, -3.0, 5.0, 7.3)],
                                                             'out': [('right', -32.0, -21.0, 12.0, 18.0)], 'open': 0.5},
    'max: all free wall low / high': {'in': [('right', -32.0, -21.0, 5.0, 7.3), ('right', 12.6, 18.5, 5.0, 7.3), ('left', -30.0, -3.0, 5.0, 7.3)],
                                      'out': [('left', -30.0, -1.0, 12.0, 16.2), ('front', -18.0, 40.0, 12.0, 16.2), ('right', -31.0, -22.0, 12.0, 16.2), ('right', 13.0, 18.5, 12.0, 16.2)]},
}
VENT_SETS['blower: in right above USB-A / out left (Sunon UB3H3-500)'] = {
    'in': [('right', -19.0, 12.0, 12.9, 15.9)], 'out': [('left', -17.0, -1.2, 9.7, 12.7)], 'open': 0.6, 'fan': True}
FAN = {'q0': 6.5e-3 / 60, 'p0': 40.34}   # Sunon UB3H3-500 at 3 V: free air 6.5 l/min, shut-off 40.34 Pa (linear curve)
K_AIR_MIXED = 0.5                        # W/m/K, effective air conductivity with the blower stirring the case (rough)
VARIANTS_V015 = [('V0.1.4 (alu plate + pad, sealed)', None, True, None, 'inside'),
                 ('+ blower, still air (pessimistic)', 'blower: in right above USB-A / out left (Sunon UB3H3-500)', True, None, 'inside'),
                 ('+ blower, mixed air (optimistic)', 'blower: in right above USB-A / out left (Sunon UB3H3-500)', True, None, 'inside')]
VARIANTS = [  # (name, vent set, heatsink, bottom film, plate) - the ROCK 2F has the 14 x 14 x 4 mm heatsink glued on; mounted on a camera
    ('no heatsink', None, False, None, None), ('heatsink (today)', None, True, None, None),
    ('+ recommended grilles', 'recommended: in low left-front / out high right-front', True, None, None),
    ('+ max vents', 'max: all free wall low / high', True, None, None),
    ('+ alu plate inside + pad', None, True, None, 'inside'),
    ('+ alu plate as the floor + pad', None, True, None, 'outside'),
    ('on a desk (comparison)', None, True, 4.0, None)]
VARIANTS = VARIANTS_V015 + [v for v in VARIANTS if v[0] in ('heatsink (today)', 'on a desk (comparison)')]
if os.environ.get('THERMAL_ONLY'):   # e.g. THERMAL_ONLY=sealed for a quick run
    VARIANTS = [v for v in VARIANTS if v[0] in os.environ['THERMAL_ONLY'].split(',')]


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, App.Vector(x0, y0, z0))


def cbox(cx, cy, sx, sy, z0, z1):
    return box(cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z1)


def geometry(vs, vents, heatsink, plate=None):
    """vents: a VENT_SETS entry or None; plate: None, 'inside' (1 mm Al on the floor) or 'outside' (Al sheet as the floor), both with a thermal pad under the SoC."""
    v = lambda n: getattr(vs, n).Value
    X0, Y0, H, W = v('BodyX0'), v('BodyY0'), v('BodyHeight'), v('Wall')
    X1, Y1 = X0 + v('BodyLength'), Y0 + v('BodyWidth')
    cavity = box(X0 + W, X1 - W, Y0 + W, Y1 - W, v('Floor'), H - v('TopSkin'))
    posts = [Part.makeCylinder(v('TowerR'), H - v('TopSkin') - v('TowerBottomZ'), App.Vector(x, y, v('TowerBottomZ')))
             for x in (v('TopScrewX0'), v('TopScrewX1')) for y in (v('TopScrewY0'), v('TopScrewY1'))]
    posts += [Part.makeCylinder(v('BotBossR'), v('BotBossTopZ') - v('Floor'), App.Vector(x, y, v('Floor')))
              for x in (v('BotScrewX0'), v('BotScrewX1')) for y in (v('BotScrewY0'), v('BotScrewY1'))]
    shell = box(X0, X1, Y0, Y1, 0, H).cut(cavity).fuse(posts)

    def slot(wall, u0, u1, z0, z1):
        return {'left': box(X0, X0 + W, u0, u1, z0, z1), 'right': box(X1 - W, X1, u0, u1, z0, z1),
                'front': box(u0, u1, Y0, Y0 + W, z0, z1), 'back': box(u0, u1, Y1 - W, Y1, z0, z1)}[wall]
    slots = {k: [slot(*s) for s in vents[k]] for k in ('in', 'out')} if vents else {'in': [], 'out': []}
    for s in slots['in'] + slots['out']:
        shell = shell.cut(s)
    solids = {'rock_pcb': box(*ROCK_PCB), 'fh_pcb': box(*FH_PCB), **{k: cbox(*c) for k, c in CHIPS.items()}}
    if heatsink:
        solids['heatsink'] = cbox(*HEATSINK)
    if plate:
        soc = CHIPS['soc']
        if plate == 'inside':   # 1 mm aluminium sheet on the floor, pad from it to the ROCK 2F underside under the SoC
            solids['alu'] = box(X0 + W, X1 - W, Y0 + W, Y1 - W, v('Floor'), v('Floor') + 1.0).cut(posts)
            solids['pad'] = cbox(soc[0], soc[1], soc[2], soc[3], v('Floor') + 1.0, ROCK_PCB[4])
        else:                   # the plastic floor inside the wall ring replaced by a 2 mm aluminium plate (outside face exposed)
            floor = box(X0 + W, X1 - W, Y0 + W, Y1 - W, 0.0, v('Floor'))
            solids['alu'] = floor
            shell = shell.cut(floor)
            solids['pad'] = cbox(soc[0], soc[1], soc[2], soc[3], v('Floor'), ROCK_PCB[4])
    air = cavity.fuse(slots['in'] + slots['out']).cut(shell).cut(list(solids.values()))
    parts = {'shell': shell, 'air': air, **solids}
    frag = parts['shell'].generalFuse([p for k, p in parts.items() if k != 'shell'])[0]
    named = []   # (name, solid) per fragment: the part it overlaps most (a hollow shell's centre of mass is in the air)
    for so in frag.Solids:
        named.append((max(parts, key=lambda k: so.common(parts[k]).Volume if so.BoundBox.intersect(parts[k].BoundBox) else 0), so))
    outer = (X0, X1, Y0, Y1, 0.0, H)
    return Part.CompSolid([so for _, so in named]), [n for n, _ in named], outer, slots


BIN = Path('/Applications/FreeCAD.app/Contents/Resources/bin')
FACES = ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0))     # C3D4 faces S1..S4 (ccx node order)


def mesh(comp, work):
    """Tetra mesh of all fragment solids (shared faces -> conformal) with gmsh; returns nodes {id: (x, y, z)}, tets {id: (n1..n4)}."""
    import subprocess
    comp.exportBrep(str(work / 'model.brep'))
    (work / 'mesh.geo').write_text('SetFactory("OpenCASCADE");\nMerge "model.brep";\nCoherence;\n'
                                   'Mesh.CharacteristicLengthMax = 1.8;\nMesh.CharacteristicLengthMin = 0.2;\n'
                                   'Mesh.MshFileVersion = 2.2;\nMesh 3;\nSave "mesh.msh";\n')
    subprocess.run([str(BIN / 'gmsh'), 'mesh.geo', '-'], cwd=work, check=True, capture_output=True)
    nodes, tets, sec = {}, {}, None
    for line in (work / 'mesh.msh').read_text().splitlines():
        if line.startswith('$'):
            sec = line
            continue
        w = line.split()
        if sec == '$Nodes' and len(w) == 4:
            nodes[int(w[0])] = tuple(map(float, w[1:]))
        elif sec == '$Elements' and len(w) > 4 and w[1] == '4':
            tets[int(w[0])] = tuple(map(int, w[-4:]))
    return nodes, tets


def solve(comp, names, outer, slots, h_vent, work):
    """Steady heat transfer in ccx (units mm, W, °C). Materials and heat sources by tet centroid, films on outer faces."""
    import subprocess
    nodes, tets = mesh(comp, work)
    sols = list(zip(names, comp.Solids))
    boxes = [(n, so.BoundBox) for n, so in sols if n not in ('shell', 'air')]   # boards, chips, heatsink: box solids
    shell = [so for n, so in sols if n == 'shell']
    owner = {}
    for e, ns in tets.items():
        c = App.Vector(*[sum(nodes[n][k] for n in ns) / 4 for k in range(3)])
        owner[e] = next((n for n, bb in boxes if bb.isInside(c)), None) or ('shell' if any(so.isInside(c, 1e-6, True) for so in shell) else 'air')
    kmat = {'shell': K['shell'], 'air': K['air'], 'rock_pcb': K['pcb'], 'fh_pcb': K['pcb'], 'heatsink': K['alu'], 'alu': K['alu'], 'pad': K['pad']}
    groups = {}
    for e, o in owner.items():
        groups.setdefault(o, []).append(e)
    vol = lambda e: abs((App.Vector(*nodes[tets[e][1]]) - App.Vector(*nodes[tets[e][0]])).dot(
        (App.Vector(*nodes[tets[e][2]]) - App.Vector(*nodes[tets[e][0]])).cross(App.Vector(*nodes[tets[e][3]]) - App.Vector(*nodes[tets[e][0]])))) / 6
    X0, X1, Y0, Y1, Z0, Z1 = outer
    on = lambda a, b: abs(a - b) < 1e-4
    outlet = [s.BoundBox for s in slots['out']]
    films = []
    for e, ns in tets.items():
        for fi, f in enumerate(FACES):
            p = [nodes[ns[k]] for k in f]
            if all(on(q[2], Z1) for q in p):
                h = H_OUT['top']
            elif all(on(q[2], Z0) for q in p):
                h = H_OUT['bottom']
            elif any(all(on(q[i], v) for q in p) for i, v in ((0, X0), (0, X1), (1, Y0), (1, Y1))):
                c = App.Vector(*[sum(q[k] for q in p) / 3 for k in range(3)])
                h = h_vent if any(ob.isInside(c) for ob in outlet) else H_OUT['side']
            else:
                continue
            if h > 0:
                films.append((e, fi + 1, h))
    L = ['*HEADING', 'Equip-1 thermal estimate', '*NODE, NSET=NALL']
    L += [f'{n}, {x:.6f}, {y:.6f}, {z:.6f}' for n, (x, y, z) in nodes.items()]
    L += ['*ELEMENT, TYPE=C3D4, ELSET=EALL'] + [f'{e}, ' + ', '.join(map(str, ns)) for e, ns in tets.items()]
    for o, es in groups.items():
        L += [f'*ELSET, ELSET=E_{o}'] + [', '.join(map(str, es[i:i + 12])) for i in range(0, len(es), 12)]
        L += [f'*MATERIAL, NAME=M_{o}', '*CONDUCTIVITY', f'{kmat.get(o, K["chip"]) / 1000:.6g}', f'*SOLID SECTION, ELSET=E_{o}, MATERIAL=M_{o}']
    L += ['*INITIAL CONDITIONS, TYPE=TEMPERATURE', f'NALL, {T_AMB}', '*STEP', '*HEAT TRANSFER, STEADY STATE', '1., 1.']
    L += ['*DFLUX'] + [f'E_{o}, BF, {POWER[o] / sum(vol(e) for e in groups[o]):.6g}' for o in POWER if o in groups]
    L += ['*FILM'] + [f'{e}, F{fi}, {T_AMB}, {h * 1e-6:.6g}' for e, fi, h in films]
    L += ['*NODE PRINT, NSET=NALL', 'NT', '*END STEP']
    (work / 'model.inp').write_text('\n'.join(L) + '\n')
    r = subprocess.run([str(BIN / 'ccx'), 'model'], cwd=work, capture_output=True, text=True, env={**os.environ, 'OMP_NUM_THREADS': '8'})
    if '*ERROR' in r.stdout or r.returncode:
        raise RuntimeError(r.stdout[-2000:])
    temp, on_t = {}, False
    for line in (work / 'model.dat').read_text().splitlines():
        if 'temperatures' in line:
            on_t = True
            continue
        w = line.split()
        if on_t and len(w) == 2:
            temp[int(w[0])] = float(w[1])
    return [(App.Vector(*nodes[n]), t) for n, t in temp.items()], len(nodes)


def summarize(pts, outer, heatsink):
    X0, X1, Y0, Y1, Z0, Z1 = outer
    inbox = lambda p, b, e=1e-3: b[0] - e <= p.x <= b[1] + e and b[2] - e <= p.y <= b[3] + e and b[4] - e <= p.z <= b[5] + e
    cb = lambda c: (c[0] - c[2] / 2, c[0] + c[2] / 2, c[1] - c[3] / 2, c[1] + c[3] / 2, c[4], c[5])
    s = {f'{k} max': max(t for p, t in pts if inbox(p, cb(c))) for k, c in CHIPS.items()}
    s['ROCK PCB max'] = max(t for p, t in pts if inbox(p, ROCK_PCB))
    s['Firehat PCB max'] = max(t for p, t in pts if inbox(p, FH_PCB))
    air = [t for p, t in pts if inbox(p, (X0 + 2.5, X1 - 2.5, Y0 + 2.5, Y1 - 2.5, 5.0, 16.0)) and not inbox(p, ROCK_PCB) and not inbox(p, FH_PCB)]
    s['air between boards mean'] = sum(air) / len(air)
    s['case top max'] = max(t for p, t in pts if abs(p.z - Z1) < 1e-3)
    s['case outside max'] = max(t for p, t in pts if abs(p.z - Z1) < 1e-3 or abs(p.z - Z0) < 1e-3 or min(abs(p.x - X0), abs(p.x - X1), abs(p.y - Y0), abs(p.y - Y1)) < 1e-3)
    return s


def plot(pts, outer, title, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri
    X0, X1, Y0, Y1, Z0, Z1 = outer
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.2), gridspec_kw={'width_ratios': [1.2, 1.2, 1.5]})
    lo, hi = T_AMB, max(t for _, t in pts)
    lv = [lo + (hi - lo) * i / 24 for i in range(25)]
    for a, (label, sel, uv) in zip(ax, [
            ('between the boards, z = 11 mm (from above)', lambda p: abs(p.z - 11.0) < 0.7, lambda p: (p.x, p.y)),
            ('case top surface (from above)', lambda p: abs(p.z - Z1) < 1e-3, lambda p: (p.x, p.y)),
            ('section through the SoC, y = -9.9 mm (from the front)', lambda p: abs(p.y + 9.9) < 0.7, lambda p: (p.x, p.z))]):
        q = [(uv(p), t) for p, t in pts if sel(p)]
        tri = mtri.Triangulation([u for (u, _), _ in q], [w for (_, w), _ in q])
        cs = a.tricontourf(tri, [t for _, t in q], levels=lv, cmap='inferno')
        a.set_title(label, fontsize=10)
        a.set_aspect('equal')
        a.set_xlabel('x (mm)')
    fig.colorbar(cs, ax=ax, label='°C', shrink=0.85)
    fig.suptitle(title, fontsize=11)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cad = App.openDocument(str(ROOT / json.loads((ROOT / 'config' / 'assembly.json').read_text())['document']))
    vs = cad.getObject('Parameters')
    rows = {}
    for name, vents, hs, h_bot, plate in VARIANTS:
        H_OUT['bottom'] = h_bot or 8.0   # 8: free air (camera-mounted), 4: standing on a desk
        vset = VENT_SETS.get(vents)
        comp, names, outer, slots = geometry(vs, vset, hs, plate)
        work = OUT / ''.join(c if c.isalnum() else '_' for c in name).strip('_')
        work.mkdir(exist_ok=True)
        h_vent, flow = 0.0, ''
        K['air'] = K_AIR_MIXED if 'mixed air' in name else 0.07
        pts, n = solve(comp, names, outer, slots, 0.0, work)
        if vset and vset.get('fan'):   # operating point: fan curve = inlet grille (Cd 0.6, open area) + outlet jet losses
            a_in = sum((s[2] - s[1]) * (s[4] - s[3]) for s in vset['in']) * 1e-6 * vset.get('open', 1.0)
            a_out = sum((s[2] - s[1]) * (s[4] - s[3]) for s in vset['out']) * 1e-6
            k = 0.5 * 1.2 * (1 / (CD * a_in) ** 2 + 1 / a_out ** 2)
            a, b_, c = k, FAN['p0'] / FAN['q0'], -FAN['p0']
            q = (-b_ + math.sqrt(b_ * b_ - 4 * a * c)) / (2 * a)
            h_vent = RHO_CP * q / a_out
            pts, n = solve(comp, names, outer, slots, h_vent, work)
            dt = summarize(pts, outer, hs)['air between boards mean'] - T_AMB
            flow = f'{vents}: {q * 6e4:.2f} l/min at {k * q * q:.1f} Pa (fan curve), {a_in * 1e6:.0f} mm² open in / {a_out * 1e6:.0f} mm² out, k_air {K["air"]:g}'
        elif vents:   # stack flow from the air temperature, then re-solve (2 rounds converge to ~0.5 °C)
            a_in = sum((s[2] - s[1]) * (s[4] - s[3]) for s in vset['in']) * 1e-6
            a_out = sum((s[2] - s[1]) * (s[4] - s[3]) for s in vset['out']) * 1e-6
            a_in, a_out = a_in * vset.get('open', 1.0), a_out * vset.get('open', 1.0)   # grille: open-area fraction
            a_eff = 1 / math.sqrt(1 / a_in ** 2 + 1 / a_out ** 2)
            dz = (sum((s[3] + s[4]) / 2 for s in vset['out']) / len(vset['out']) - sum((s[3] + s[4]) / 2 for s in vset['in']) / len(vset['in'])) * 1e-3
            for _ in range(2):
                dt = summarize(pts, outer, hs)['air between boards mean'] - T_AMB
                q = CD * a_eff * math.sqrt(2 * G * dz * max(dt, 0.1) / (T_AMB + 273.15))
                h_vent = RHO_CP * q / a_out
                pts, n = solve(comp, names, outer, slots, h_vent, work)
            flow = f'{vents}: {q * 6e4:.2f} l/min through {a_in * 1e6:.0f} mm² in / {a_out * 1e6:.0f} mm² out, {RHO_CP * q * dt:.2f} W carried out'
        s = summarize(pts, outer, hs)
        rows[name] = (s, flow, n)
        plot(pts, outer, f'{name}: {sum(POWER.values()):.2f} W inside, {T_AMB:.0f} °C room (estimate)', OUT / f"{''.join(c if c.isalnum() else '_' for c in name).strip('_')}.png")
        print(f'THERMAL {name}: SoC {s["soc max"]:.1f} °C, VT6315N {s["vt6315n max"]:.1f} °C, air {s["air between boards mean"]:.1f} °C, case {s["case outside max"]:.1f} °C, {n} nodes {flow}')
    keys = list(next(iter(rows.values()))[0])
    lines = ['# Thermal estimate (V0.1.5, conduction model)', '',
             f'Room {T_AMB:.0f} °C; powers (W, estimates): ' + ', '.join(f'{k} {p}' for k, p in POWER.items()) + f' = {sum(POWER.values()):.2f} W.',
             f'Conductivities (W/m/K): {K}. Outside films (W/m²K): top {H_OUT["top"]:g}, sides {H_OUT["side"]:g}, bottom 8 in free air / 4 on a desk. ROCK 2F throttles at 80 °C (SoC).', '',
             '| | ' + ' | '.join(rows) + ' |', '|---|' + '---|' * len(rows)]
    lines += [f'| {k} | ' + ' | '.join(f'{rows[v][0][k]:.1f}' for v in rows) + ' |' for k in keys]
    lines += ['', *[f'- {v}: {rows[v][1]}' for v in rows if rows[v][1]], '', 'Vent sets (wall, from..to, z):']
    lines += [f'- {n}: ' + '; '.join(f'{k}: ' + ', '.join(f'{w} {u0:g}..{u1:g}, z {z0:g}..{z1:g}' for w, u0, u1, z0, z1 in vs_[k]) for k in ('in', 'out')) + (f", open area {vs_['open']:.0%}" if 'open' in vs_ else '') for n, vs_ in VENT_SETS.items()]
    (OUT / (f"results_{os.environ['THERMAL_ONLY'].replace(',', '_').replace(' ', '-')}.md" if os.environ.get('THERMAL_ONLY') else 'results.md')).write_text('\n'.join(lines) + '\n')
    print('THERMAL DONE', OUT / 'results.md')


main()
