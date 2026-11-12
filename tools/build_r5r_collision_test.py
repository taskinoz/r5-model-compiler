"""Build and package the S3 collision test models for R5R.

Writes test-output/r5r-collision: authored boxes and an L-shaped step (static, rigid
physics, no collision, no BVH, three sizes and masses, one decompiled and rebuilt),
a decompiled and rebuilt retail rocket, and a package report with the trace and drop
expectations that `ingame54.py --collision` checks. Needs the installed S3 corpus in
test-output/s3-raw (for the material binding and the retail rocket).

usage: python tools/build_r5r_collision_test.py --repak <repak.exe>
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repak', required=True)
args = parser.parse_args()
sys.path.insert(0, str(root / 'tools'))
from decompile54 import write_smd  # noqa: E402
from mdl54 import Model  # noqa: E402
from pack54 import package  # noqa: E402

out = root / 'test-output/r5r-collision'
src = out / 'sources'
src.mkdir(parents=True, exist_ok=True)
compiled = out / 'compiled'
compiled.mkdir(exist_ok=True)
bones = [dict(name='root', parent=-1)]
frames = [[((0, 0, 0), (0, 0, 0), (1, 1, 1))]]


def quad(a, b, c, d, n):
    return [('box', [(p, n, uv, [(0, 1.0)]) for p, uv in ((a, (0, 0)), (b, (1, 0)), (c, (1, 1)))]),
            ('box', [(p, n, uv, [(0, 1.0)]) for p, uv in ((a, (0, 0)), (c, (1, 1)), (d, (0, 1)))])]


def box(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    return (quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (0, 0, 1)) +
            quad((x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0), (0, 0, -1)) +
            quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (0, -1, 0)) +
            quad((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (0, 1, 0)) +
            quad((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), (1, 0, 0)) +
            quad((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (-1, 0, 0)))


# L-shaped step: a 64 x 64 x 16 slab, and a 32 x 64 x 48 tower on its -x half (surfaces
# of the union only, so traces must follow the shape, not the bounding box)
def step():
    tris = []
    y0, y1 = -32, 32
    # top of the slab (x 0..32) and of the tower (x -32..0)
    tris += quad((0, y0, 16), (32, y0, 16), (32, y1, 16), (0, y1, 16), (0, 0, 1))
    tris += quad((-32, y0, 64), (0, y0, 64), (0, y1, 64), (-32, y1, 64), (0, 0, 1))
    tris += quad((-32, y1, 0), (32, y1, 0), (32, y0, 0), (-32, y0, 0), (0, 0, -1))
    tris += quad((32, y0, 0), (32, y1, 0), (32, y1, 16), (32, y0, 16), (1, 0, 0))
    tris += quad((0, y0, 16), (0, y1, 16), (0, y1, 64), (0, y0, 64), (1, 0, 0))
    tris += quad((-32, y1, 0), (-32, y0, 0), (-32, y0, 64), (-32, y1, 64), (-1, 0, 0))
    for y, n in ((y0, (0, -1, 0)), (y1, (0, 1, 0))):  # the two L-shaped ends
        rects = [((-32, 0), (32, 16)), ((-32, 16), (0, 64))]
        for (xa, za), (xb, zb) in rects:
            a, b, c, d = (xa, y, za), (xb, y, za), (xb, y, zb), (xa, y, zb)
            tris += quad(a, b, c, d, n) if y == y0 else quad(b, a, d, c, n)
    return tris


write_smd(src / 'box.smd', bones, frames, box((-32, -32, 0), (32, 32, 64)))
write_smd(src / 'step.smd', bones, frames, step())
qcs = {
    'static_box': '$staticprop\n$surfaceprop "concrete"\n$body body "box.smd"\n$sequence idle "box.smd"\n',
    'static_step': '$staticprop\n$surfaceprop "concrete"\n$body body "step.smd"\n$sequence idle "step.smd"\n',
    'phys_box': '$surfaceprop "metal"\n$body body "box.smd"\n$sequence idle "box.smd"\n$collisionmodel "box.smd" { $mass 50 }\n$keyvalues { prop_data { "base" "Metal.Medium" } }\n',
    'nocoll_box': '$surfaceprop "metal"\n$body body "box.smd"\n$sequence idle "box.smd"\n',
}
qcs['phys_box_nobvh'] = qcs['phys_box']
qcs['static_step_phy'] = qcs['static_step'] + '$collisionmodel "step.smd" { $mass 20 }\n'
for size, mass in ((16, 5), (32, 20), (64, 500)):
    write_smd(src / ('box%d.smd' % size), bones, frames, box((-size / 2, -size / 2, 0), (size / 2, size / 2, size)))
    qcs['pbox%d_m%d' % (size, mass)] = ('$surfaceprop "metal"\n$body body "box%d.smd"\n$sequence idle "box%d.smd"\n$collisionmodel "box%d.smd" { $mass %d }\n$keyvalues { prop_data { "base" "Metal.Medium" } }\n') % (size, size, size, mass)
extra = {'phys_box_nobvh': ['--no-bvh']}
# bind the surveyed retail concrete material, as the earlier runtime package did
source = next((root / 'test-output/s3-raw').rglob('concrete_chunk02a.rmdl'))
mat = Model(source, 's3').materials[0]
target = mat['name'].replace(chr(92), '/')
models = []


def compile_qc(name, qc_path, flags=(), material=None, kind='rgdp'):
    model = compiled / (name + '.rmdl')
    m_name, m_guid = material or (target, mat['guid'])
    cmd = [str(root / 'build/r5studiomdl.exe'), '--target', 's3', '--external-assets', '-quiet', '-o', str(model),
           '--material-guid', m_name + '=' + '%016x' % m_guid, '--material-type', m_name + '=' + kind,
           '--packed-positions', *flags, str(qc_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert not r.returncode, r.stdout + r.stderr
    models.append(str(model))


for name, body in qcs.items():
    qc = src / (name + '.qc')
    qc.write_text('$modelname "r5c_collision/%s.rmdl"\n$cdmaterials ""\n%s$renamematerial "box" "%s"\n' % (name, body, target))
    compile_qc(name, qc, extra.get(name, ()))

# a retail physics prop, decompiled (render + PHY) and rebuilt by these tools
from decompile54 import decompile  # noqa: E402
retail = next((root / 'test-output/s3-raw').rglob('bangalore_rockets_projectile.rmdl'))
qc = decompile(retail, src / 'bangalore', 's3', render_only=True, with_physics=True)
text = qc.read_text().replace('$modelname "weapons_r5/misc_bangalore_rockets/bangalore_rockets_projectile.rmdl"',
                              '$modelname "r5c_collision/bangalore_rebuilt.rmdl"')
assert 'r5c_collision/bangalore_rebuilt' in text, text[:300]
slots = [m['name'] for m in Model(retail, 's3').materials]
text += '\n$keyvalues { prop_data { "base" "Metal.Small" } }\n' + ''.join('$renamematerial "%s" "%s"\n' % (s, target) for s in slots)
qc.write_text(text)
compile_qc('bangalore_rebuilt', qc)
# the authored physics box after a decompile/recompile cycle
qc2 = decompile(compiled / 'phys_box.rmdl', src / 'phys_box_rt', 's3', render_only=True, with_physics=True)
t2 = qc2.read_text().replace('$modelname "r5c_collision/phys_box.rmdl"', '$modelname "r5c_collision/pbox64_rt.rmdl"')
assert 'pbox64_rt' in t2
qc2.write_text(t2 + '\n$keyvalues { prop_data { "base" "Metal.Medium" } }\n')
compile_qc('pbox64_rt', qc2)
# a jointed model: the retail bird (six solids), decompiled and rebuilt, with a skinned
# material bound as the earlier runtime package did for multi-bone models
bird = next((root / 'test-output/s3-raw').rglob('bird.rmdl'))
qc3 = decompile(bird, src / 'bird', 's3', render_only=True, with_physics=True)
t3 = qc3.read_text()
old_name = '$modelname "' + Model(bird, 's3').name.replace(chr(92), '/')[4:] + '"'
assert old_name in t3, old_name
skin = Model(next((root / 'test-output/s3-raw').rglob('pilot_light_wraith.rmdl')), 's3').materials[0]
skin_name = skin['name'].replace(chr(92), '/')
t3 = t3.replace(old_name, '$modelname "r5c_collision/bird_rebuilt.rmdl"')
# what the render-only export drops but a ragdoll needs: an ACT_DIERAGDOLL sequence
# (retail's `ragdoll`; posed from the mesh's reference skeleton here) and prop_data
t3 += '$sequence "ragdoll" "mesh0_lod0.dmx" activity ACT_DIERAGDOLL 1' + chr(10)
t3 += '$keyvalues { prop_data { "base" "" } }' + chr(10)
t3 += ''.join('$renamematerial "%s" "%s"\n' % (m['name'], skin_name) for m in Model(bird, 's3').materials)
qc3.write_text(t3)
compile_qc('bird_rebuilt', qc3, material=(skin_name, skin['guid']), kind='sknp')

report = package(models, out / 'pak', 'r5c_collision', args.repak, 's3')
report['runtime_exclusions'] = []


def entry_height(model_path, wx, wy, role='hull'):
    """Top of the model's hull or trace-mesh BVH entry at a world offset from the prop
    (props spawn at angles 0, where BVH coordinates are world offsets). Quads count
    under both diagonals (a flat parallelogram has one top either way)."""
    import bvh54
    parsed = bvh54.from_model(model_path)
    entry = parsed['entries'][parsed[role]]
    tris = list(entry['plain'])
    for a, b, c, d in entry['quads']:
        tris += [(a, b, d), (a, d, c)]
    best = None
    for a, b, c in tris:
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-9:
            continue
        l1 = ((b[1] - c[1]) * (wx - c[0]) + (c[0] - b[0]) * (wy - c[1])) / den
        l2 = ((c[1] - a[1]) * (wx - c[0]) + (a[0] - c[0]) * (wy - c[1])) / den
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) >= -1e-6:
            z = l1 * a[2] + l2 * b[2] + l3 * c[2]
            best = z if best is None else max(best, z)
    return None if best is None else round(best, 3)


# half-inch offsets: no point lies on an edge of the step, where either level is right
grid = [(x + 0.5, y + 0.5) for x in (-28, -18, -8, 0, 8, 18, 28) for y in (-28, -18, -8, 0, 8, 18, 28)]


def expect(name, role):
    return [[x, y, entry_height(compiled / (name + '.rmdl'), x, y, role)] for x, y in grid]


spec = {
    # ordinary traces on a SOLID_VPHYSICS prop_dynamic follow the physics-hull entry and
    # miss models without a PHY (retail error.rmdl too); high-detail traces read the
    # trace-mesh entry: on the step with a PHY the two differ (hull slope vs exact L)
    'static_box': dict(collision_traces=[[0, 0, None]], high_detail_traces=expect('static_box', 'trace')),
    'static_step': dict(collision_traces=[[0, 0, None]], high_detail_traces=expect('static_step', 'trace')),
    'static_step_phy': dict(collision_traces=expect('static_step_phy', 'hull'),
                            high_detail_traces=expect('static_step_phy', 'trace')),
    'nocoll_box': dict(collision_traces=[[0, 0, None]], high_detail_traces=[[0, 0, None]]),
    'phys_box': dict(collision_traces=expect('phys_box', 'hull'), physics_drops=[[None, 0.0]]),
    # without the BVH the box still lands (PHY) but a trace cannot hit it: no trace expectation
    'phys_box_nobvh': dict(physics_drops=[]),
    'pbox16_m5': dict(physics_drops=[[None, 0.0]]),
    'pbox32_m20': dict(physics_drops=[[None, 0.0]]),
    'pbox64_m500': dict(physics_drops=[[None, 0.0]]),
    'pbox64_rt': dict(physics_drops=[[None, 0.0]]),
    # rebuilt retail rocket: rests where the retail control rests (measured 6.72 in R5R)
    'bangalore_rebuilt': dict(physics_drops=[[None, 6.72]]),
    # jointed: must switch to a (client-side) ragdoll, as the retail bird does
    'bird_rebuilt': dict(ragdoll=True),
}
for m in report['models']:
    m.update(spec[Path(m['path']).stem])
report['collision_controls'] = [
    dict(path='mdl/error.rmdl', collision_traces=[[0, 0, None]], high_detail_traces=[[0.399, 1.353, 26.114]]),
    dict(path='mdl/menu/coin.rmdl', collision_traces=[[0, 0, None]], high_detail_traces=[[-0.464, -0.034, 15.276]]),
    dict(path='mdl/props_debris/concrete_chunk02a.rmdl', collision_traces=[[-1.42, 2.21, 10.3]]),
    dict(path='mdl/weapons_r5/misc_bangalore_rockets/bangalore_rockets_projectile.rmdl', physics_drops=[[None, 6.72]]),
    dict(path='mdl/creatures/bird/bird.rmdl', ragdoll=True),
]
(out / 'pak/r5c_collision.report.json').write_text(json.dumps(report, indent=2))
print(json.dumps([m['path'] for m in report['models']], indent=2), report['outputs'])
