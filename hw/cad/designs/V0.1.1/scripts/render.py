"""Render the standard set from meshes captured out of the SAVED .FCStd.

Stage 1 (FreeCAD):  FreeCADCmd scripts/render.py
    captures meshes into .build/meshes/, runs Blender headless on this same file, then
    builds renders/contact-sheet.png. Never saves the CAD.
Stage 2 (Blender, started by stage 1):  Blender -b -P scripts/render.py -- <design root>

Committed renders show the enclosure and the OLED panel reference only. If the board models
exist (hw/cad/boards/.build), extra fit renders with the ROCK 2F and Firehat go to
.build/fit-renders/ (not committed; the board models are third-party / unreleased).
Render-only changes (materials, lights, cameras) do not change or requalify geometry.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BLENDER = os.environ.get('BLENDER', '/Applications/Blender.app/Contents/MacOS/Blender')
VIEWS = ['hero', 'rear', 'ports', 'exploded', 'internals', 'mechanism']


def place_boards(App, vs, rk, fh):
    """Same placement as verify.py: ROCK 2F on the bottom bosses, Firehat under the towers."""
    def frame(shape, lo, hi):
        b = max(shape.Solids, key=lambda so: so.BoundBox.XLength * so.BoundBox.YLength if so.BoundBox.ZLength < 2 else 0)
        u = {(round(f.Surface.Center.x, 2), round(f.Surface.Center.y, 2)) for f in b.Faces
             if type(f.Surface).__name__ == 'Cylinder' and lo < f.Surface.Radius < hi}
        return b, App.Vector(sum(p[0] for p in u) / len(u), sum(p[1] for p in u) / len(u), 0)
    cx, cy = (vs.TopScrewX0.Value + vs.TopScrewX1.Value) / 2, (vs.TopScrewY0.Value + vs.TopScrewY1.Value) / 2
    rb, rc = frame(rk, 1.7, 1.8)
    fb, fc = frame(fh, 1.3, 1.4)
    r = rk.copy(); r.translate(-rc); r.rotate(App.Vector(), App.Vector(0, 0, 1), 90)
    r.translate(App.Vector(cx, cy, vs.BotBossTopZ.Value - rb.BoundBox.ZMin))
    f = fh.copy(); f.translate(App.Vector(cx - fc.x, cy - fc.y, vs.TowerBottomZ.Value - fb.BoundBox.ZMax))
    return r, f


def capture(root):
    import hashlib
    import FreeCAD as App
    import Mesh
    import MeshPart
    import Part

    cfg = json.loads((root / 'config' / 'assembly.json').read_text())
    fcstd = root / cfg['document']
    out = root / '.build' / 'meshes'
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob('*.stl'):
        old.unlink()
    doc = App.openDocument(str(fcstd))
    vs = doc.getObject('Parameters')

    def write(name, shape):
        m = MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.02, AngularDeflection=0.15, Relative=False)
        Mesh.Mesh(m).write(str(out / f'{name}.stl'))

    names = [p['name'] for p in cfg['parts']]
    cuts = {'section': Part.makeBox(200, 200, 200, App.Vector(vs.ButtonX.Value, -100, -100)),          # x >= actuator column
            'ysection': Part.makeBox(200, 200, 200, App.Vector(-100, vs.PanelY.Value, -100)),          # y >= panel centre
            'fsection': Part.makeBox(200, 200, 200, App.Vector(-100, vs.BodyY0.Value + 1.0, -100))}    # through the front wall
    for n in names:
        s = doc.getObject(n).Shape
        write(n, s)
        for tag, box in cuts.items():
            write(f'{tag}-{n}', s.common(box))
    boards = False
    bcfg = cfg.get('boards', {})
    rk_p, fh_p = (root / bcfg.get('rock2f', 'missing')).resolve(), (root / bcfg.get('firehat', 'missing')).resolve()
    if rk_p.exists() and fh_p.exists():
        rkb, fhb = place_boards(App, vs, Part.read(str(rk_p)), Part.read(str(fh_p)))
        for tag, shp in (('rock2f', rkb), ('firehat', fhb)):
            write(f'board-{tag}', shp)
            for c in ('ysection', 'fsection'):
                write(f'{c}-board-{tag}', shp.common(cuts[c]))
        boards = True
    App.closeDocument(doc.Name)  # never saved
    (out / 'manifest.json').write_text(json.dumps({'fcstd': cfg['document'], 'version': cfg['version'],
                                                  'sha256': hashlib.sha256(fcstd.read_bytes()).hexdigest(), 'parts': names, 'boards': boards}, indent=1))


def contact_sheet(root, version):
    from PIL import Image, ImageDraw
    imgs = [Image.open(root / 'renders' / f'{v}.png').convert('RGB') for v in VIEWS]
    w, h = imgs[0].size
    sheet = Image.new('RGB', (w * 3, (h + 40) * 2), 'white')
    d = ImageDraw.Draw(sheet)
    for i, (v, im) in enumerate(zip(VIEWS, imgs)):
        x, y = (i % 3) * w, (i // 3) * (h + 40)
        sheet.paste(im, (x, y + 40))
        d.text((x + 16, y + 12), f'Equip-1 {version} - {v}', fill=(40, 40, 40))
    sheet.resize((sheet.width // 2, sheet.height // 2)).save(root / 'renders' / 'contact-sheet.png', optimize=True)


def blender(root):
    import bpy
    from mathutils import Vector

    meshes = root / '.build' / 'meshes'
    manifest = json.loads((meshes / 'manifest.json').read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL'
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        scene.cycles.device = 'GPU'
    except Exception:
        scene.cycles.device = 'CPU'
    scene.render.resolution_x, scene.render.resolution_y = 1400, 1000
    world = bpy.data.worlds.new('World')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.92, 0.92, 0.93, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.6
    scene.view_settings.view_transform = 'AgX'

    def material(name, rgb, rough, metal=0.0):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = (*rgb, 1)
        b.inputs['Roughness'].default_value = rough
        b.inputs['Metallic'].default_value = metal
        return m

    mats = {'shell': material('Resin shell', (0.16, 0.16, 0.17), 0.55), 'cover': material('Screen cover', (0.02, 0.02, 0.025), 0.08),
            'panel': material('OLED panel', (0.05, 0.07, 0.12), 0.15), 'board': material('Board', (0.05, 0.3, 0.12), 0.45),
            'floor': material('Floor', (0.95, 0.95, 0.95), 0.9)}
    kind = lambda n: 'board' if 'board' in n else 'shell' if 'Shell' in n else 'cover' if 'Cover' in n else 'panel'

    objs = {}
    for f in sorted(meshes.glob('*.stl')):
        bpy.ops.wm.stl_import(filepath=str(f))
        o = bpy.context.selected_objects[0]
        o.name = f.stem
        o.data.materials.append(mats[kind(f.stem)])
        objs[f.stem] = o

    bpy.ops.mesh.primitive_plane_add(size=2000, location=(12.7, -6.6, -0.05))
    floor = bpy.context.active_object
    floor.data.materials.append(mats['floor'])
    for nm, loc, e, sz in (('Key', (-120, -160, 220), 9e5, 160), ('Fill', (200, -60, 120), 3e5, 200), ('Rim', (40, 220, 160), 4e5, 120)):
        d = bpy.data.lights.new(nm, 'AREA')
        d.energy, d.size = e, sz
        o = bpy.data.objects.new(nm, d)
        scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector((12.7, -6.6, 10)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    cam_data = bpy.data.cameras.new('Camera')
    cam_data.lens, cam_data.clip_start, cam_data.clip_end = 85, 1, 5000
    cam = bpy.data.objects.new('Camera', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    def shoot(view, eye, target, show, ortho=None, use_floor=True, offsets=None, folder='renders'):
        for n, o in objs.items():
            o.hide_render = n not in show
            o.location = (0, 0, (offsets or {}).get(n, 0))
        floor.hide_render = not use_floor
        cam_data.type = 'ORTHO' if ortho else 'PERSP'
        if ortho:
            cam_data.ortho_scale = ortho
        cam.location = eye
        cam.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(root / folder / f'{view}.png')
        bpy.ops.render.render(write_still=True)

    c = (12.73, -6.59, 11)
    allp = list(manifest['parts'])
    printed = [n for n in allp if n != 'OledPanel']
    shoot('hero', (-95, -190, 140), c, printed)
    shoot('rear', (150, 175, 110), c, printed)
    shoot('ports', (12.73, -400, 9), (12.73, 0, 9), printed, ortho=82)
    shoot('exploded', (-150, -250, 220), (12.73, -6.59, 30), allp, offsets={'ShellTop': 26, 'ScreenCover': 44, 'OledPanel': 14})
    shoot('internals', (-60, -150, -140), (12.73, -6.59, 16), ['ShellTop', 'ScreenCover', 'OledPanel'], use_floor=False)
    shoot('mechanism', (-110, -80, 55), (35.7, -6.6, 18), [f'section-{n}' for n in allp])
    if manifest.get('boards'):
        fit = dict(folder='.build/fit-renders')
        shoot('fit-section-display', (12.7, -400, 13), (12.7, 0, 13), [f'ysection-{n}' for n in allp] + ['ysection-board-rock2f', 'ysection-board-firehat'], ortho=78, **fit)
        shoot('fit-section-ports', (12.7, -400, 11), (12.7, 0, 11), [f'fsection-{n}' for n in allp] + ['fsection-board-rock2f', 'fsection-board-firehat'], ortho=78, **fit)
        shoot('fit-internals', (-110, -150, 120), (12.7, -6.6, 12), ['ShellBottom', 'OledPanel', 'board-rock2f', 'board-firehat'], **fit)


try:
    import bpy  # noqa: F401  (stage 2: running inside Blender)
    IN_BLENDER = True
except ImportError:
    IN_BLENDER = False

if IN_BLENDER:
    blender(Path(sys.argv[sys.argv.index('--') + 1]))
else:
    root = Path(os.environ.get('EQUIP1_CAD_ROOT') or Path(__file__).resolve().parents[1])
    (root / 'renders').mkdir(exist_ok=True)
    (root / '.build' / 'fit-renders').mkdir(parents=True, exist_ok=True)
    capture(root)
    subprocess.run([BLENDER, '-b', '--factory-startup', '-P', str(Path(__file__).resolve()), '--', str(root)], check=True)
    contact_sheet(root, json.loads((root / 'config' / 'assembly.json').read_text())['version'])
    print('RENDER DONE')
