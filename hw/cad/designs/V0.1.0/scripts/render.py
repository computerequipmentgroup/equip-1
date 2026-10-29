"""Render the standard set from meshes captured out of the SAVED .FCStd.

Stage 1 (FreeCAD):  FreeCADCmd scripts/render.py
    captures meshes into .build/meshes/, runs Blender headless on this same file, then
    builds renders/contact-sheet.png. Never saves the CAD.
Stage 2 (Blender, started by stage 1):  Blender -b -P scripts/render.py -- <design root>

Render-only changes (materials, lights, cameras) do not change or requalify geometry.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BLENDER = os.environ.get('BLENDER', '/Applications/Blender.app/Contents/MacOS/Blender')
VIEWS = ['hero', 'rear', 'ports', 'exploded', 'internals', 'mechanism']
PRESS = 0.5  # mm, illustrative button travel for the mechanism pose (switch travel not yet sourced)


def capture(root):
    import hashlib
    import FreeCAD as App
    import Mesh
    import MeshPart

    cfg = json.loads((root / 'config' / 'assembly.json').read_text())
    fcstd = root / cfg['document']
    out = root / '.build' / 'meshes'
    out.mkdir(parents=True, exist_ok=True)
    doc = App.openDocument(str(fcstd))
    vs, pv = doc.getObject('Parameters'), doc.getObject('Preview')

    def write(name, shape):
        m = MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.02, AngularDeflection=0.15, Relative=False)
        Mesh.Mesh(m).write(str(out / f'{name}.stl'))

    names = [p['name'] for p in cfg['parts']]
    for n in names:
        write(n, doc.getObject(n).Shape)
    # mechanism pose: section at the button column, buttons pressed (in memory only)
    cut = App.Vector(vs.ButtonX.Value, 0, 0)
    half = lambda s: s.common(__import__('Part').makeBox(200, 200, 200, App.Vector(cut.x, -100, -100)))
    write('section-ShellTop', half(doc.getObject('ShellTop').Shape))
    write('section-ShellBottom', half(doc.getObject('ShellBottom').Shape))
    pv.ButtonPress = PRESS
    doc.recompute()
    for i in (1, 2, 3):
        write(f'section-pressed-Button{i}', half(doc.getObject(f'Button{i}').Shape))
    App.closeDocument(doc.Name)  # never saved
    (out / 'manifest.json').write_text(json.dumps({'fcstd': cfg['document'], 'sha256': hashlib.sha256(fcstd.read_bytes()).hexdigest(),
                                                  'parts': names, 'press_mm': PRESS}, indent=1))


def contact_sheet(root):
    from PIL import Image, ImageDraw
    imgs = [Image.open(root / 'renders' / f'{v}.png').convert('RGB') for v in VIEWS]
    w, h = imgs[0].size
    sheet = Image.new('RGB', (w * 3, (h + 40) * 2), 'white')
    d = ImageDraw.Draw(sheet)
    for i, (v, im) in enumerate(zip(VIEWS, imgs)):
        x, y = (i % 3) * w, (i // 3) * (h + 40)
        sheet.paste(im, (x, y + 40))
        d.text((x + 16, y + 12), f'Equip-1 V0.1.0 - {v}', fill=(40, 40, 40))
    sheet.resize((sheet.width // 2, sheet.height // 2)).save(root / 'renders' / 'contact-sheet.png', optimize=True)


def blender(root):
    import bpy
    from mathutils import Vector

    meshes = root / '.build' / 'meshes'
    manifest = json.loads((meshes / 'manifest.json').read_text())
    scene = bpy.context.scene
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
    scene.render.film_transparent = False
    world = bpy.data.worlds.new('World')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.92, 0.92, 0.93, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.6
    scene.view_settings.view_transform = 'AgX'

    def material(name, rgb, rough, metal=0.0, alpha=1.0):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = (*rgb, 1)
        b.inputs['Roughness'].default_value = rough
        b.inputs['Metallic'].default_value = metal
        return m

    mats = {'shell': material('Resin shell', (0.16, 0.16, 0.17), 0.55),
            'cover': material('Screen cover', (0.02, 0.02, 0.025), 0.08),
            'button': material('Button', (0.32, 0.32, 0.34), 0.45),
            'floor': material('Floor', (0.95, 0.95, 0.95), 0.9)}

    def load(name, mat):
        bpy.ops.wm.stl_import(filepath=str(meshes / f'{name}.stl'))
        o = bpy.context.selected_objects[0]
        o.name = name
        o.data.materials.append(mats[mat])
        return o

    kind = lambda n: 'shell' if 'Shell' in n else 'cover' if 'Cover' in n else 'button'
    objs = {n: load(n, kind(n)) for n in manifest['parts']}
    sect = {n: load(n, kind(n)) for n in ['section-ShellTop', 'section-ShellBottom'] + [f'section-pressed-Button{i}' for i in (1, 2, 3)]}

    bpy.ops.mesh.primitive_plane_add(size=2000, location=(12.7, -6.6, -0.05))
    floor = bpy.context.active_object
    floor.data.materials.append(mats['floor'])

    def light(name, loc, energy, size):
        d = bpy.data.lights.new(name, 'AREA')
        d.energy, d.size = energy, size
        o = bpy.data.objects.new(name, d)
        scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector((12.7, -6.6, 10)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()

    light('Key', (-120, -160, 220), 9e5, 160)
    light('Fill', (200, -60, 120), 3e5, 200)
    light('Rim', (40, 220, 160), 4e5, 120)
    cam_data = bpy.data.cameras.new('Camera')
    cam_data.lens, cam_data.clip_start, cam_data.clip_end = 85, 1, 5000
    cam = bpy.data.objects.new('Camera', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    def shoot(view, eye, target, show, ortho=None, use_floor=True, offsets=None):
        for o in list(objs.values()) + list(sect.values()):
            o.hide_render = o.name not in show
            o.location = (0, 0, (offsets or {}).get(o.name, 0))
        floor.hide_render = not use_floor
        cam_data.type = 'ORTHO' if ortho else 'PERSP'
        if ortho:
            cam_data.ortho_scale = ortho
        cam.location = eye
        cam.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(root / 'renders' / f'{view}.png')
        bpy.ops.render.render(write_still=True)

    c = (12.73, -6.59, 12)
    allp = list(manifest['parts'])
    shoot('hero', (-95, -190, 150), c, allp)
    shoot('rear', (150, 175, 120), c, allp)
    shoot('ports', (12.73, -400, 9), (12.73, 0, 9), allp, ortho=82)
    shoot('exploded', (-150, -250, 230), (12.73, -6.59, 38), allp,
          offsets={'ShellTop': 28, 'ScreenCover': 52, 'Button1': 44, 'Button2': 44, 'Button3': 44})
    shoot('internals', (-60, -150, -140), (12.73, -6.59, 18), ['ShellTop', 'ScreenCover', 'Button1', 'Button2', 'Button3'], use_floor=False)
    shoot('mechanism', (-110, -80, 60), (35.7, -6.6, 20), list(sect), use_floor=True)


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
        capture(root)
        subprocess.run([BLENDER, '-b', '--factory-startup', '-P', str(Path(__file__).resolve()), '--', str(root)], check=True)
        contact_sheet(root)
        print('RENDER DONE')
