"""Build and package the S3 jiggle-bone and RUI test models for R5R.

Writes test-output/r5r-jiggle: the retail charm_nessy (three jiggle bones) decompiled
and rebuilt with its jiggle bones, the same rebuild without them as a control, and the
retail ptpov_vinson (20 RUI panels, one jiggle bone) decompiled and rebuilt as a load
check. The package report asks `ingame54.py --jiggle` to step the charms sideways and
sample their MENU_CAMERA_FOCUS attachment (on the last jiggle bone): the rebuilt charm
must swing and settle as the installed retail charm does, and the control must not
move. Needs the installed S3 corpus in test-output/s3-raw.

usage: python tools/build_r5r_jiggle_test.py --repak <repak.exe>
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repak', required=True)
args = parser.parse_args()
sys.path.insert(0, str(root / 'tools'))
from decompile54 import decompile  # noqa: E402
from mdl54 import Model  # noqa: E402
from pack54 import package  # noqa: E402

out = root / 'test-output/r5r-jiggle'
src = out / 'sources'
compiled = out / 'compiled'
compiled.mkdir(parents=True, exist_ok=True)
corpus = root / 'test-output/s3-raw'
models = []


def compile_qc(name, qc_path, bindings, kind='sknp'):
    model = compiled / (name + '.rmdl')
    cmd = [str(root / 'build/r5studiomdl.exe'), '--target', 's3', '--external-assets', '-quiet', '-o', str(model),
           '--packed-positions']
    for m_name, m_guid in bindings:
        cmd += ['--material-guid', m_name + '=' + '%016x' % m_guid, '--material-type', m_name + '=' + kind]
    r = subprocess.run(cmd + [str(qc_path)], capture_output=True, text=True)
    assert not r.returncode, r.stdout + r.stderr
    models.append(str(model))


def export(retail, name):
    qc = decompile(retail, src / name, 's3')
    text = qc.read_text()
    old = '$modelname "' + Model(retail, 's3').name.replace(chr(92), '/')[4:] + '"'
    assert old in text, old
    return qc, text.replace(old, '$modelname "r5c_jiggle/%s.rmdl"' % name)


# the charm keeps its own retail material
charm = next(corpus.rglob('charm_nessy.rmdl'))
material = Model(charm, 's3').materials[0]
binding = [(material['name'].replace(chr(92), '/'), material['guid'])]
qc, text = export(charm, 'charm_rebuilt')
assert text.count('$jigglebone') == 3
text += '$renamematerial "%s" "%s"\n' % (material['name'], binding[0][0])
qc.write_text(text)
compile_qc('charm_rebuilt', qc, binding)
# control: the same rebuild without its $jigglebone blocks (each ends at a column-0 brace)
qc2 = qc.with_name('charm_nojiggle.qc')
control = re.sub(r'(?ms)^\$jigglebone .*?^\}\n', '', text.replace('r5c_jiggle/charm_rebuilt', 'r5c_jiggle/charm_nojiggle'))
assert '$jigglebone' not in control and 'charm_nojiggle' in control
qc2.write_text(control)
compile_qc('charm_nojiggle', qc2, binding)
assert Model(compiled / 'charm_rebuilt.rmdl', 's3').jiggle_bones()
# experiment: the same rebuild with the include count patched from -1 (external rig) to
# 0 (embedded rig, as the retail charm stores it)
qc4 = qc.with_name('charm_embedded.qc')
qc4.write_text(text.replace('r5c_jiggle/charm_rebuilt', 'r5c_jiggle/charm_embedded'))
compile_qc('charm_embedded', qc4, binding)
emb = compiled / 'charm_embedded.rmdl'
data = bytearray(emb.read_bytes())
assert int.from_bytes(data[0x158:0x15C], 'little', signed=True) == -1
data[0x158:0x15C] = (0).to_bytes(4, 'little')
emb.write_bytes(bytes(data))
assert not Model(compiled / 'charm_nojiggle.rmdl', 's3').jiggle_bones()

# a viewmodel with RUI panels and a jiggle bone, its slots bound to one skinned material
vinson = next(corpus.rglob('ptpov_vinson.rmdl'))
qc3, text = export(vinson, 'vinson_rebuilt')
assert '$uipanel' in text and '$jigglebone' in text
skin = Model(next(corpus.rglob('pilot_light_wraith.rmdl')), 's3').materials[0]
skin_name = skin['name'].replace(chr(92), '/')
text += ''.join('$renamematerial "%s" "%s"\n' % (m['name'], skin_name) for m in Model(vinson, 's3').materials)
qc3.write_text(text)
compile_qc('vinson_rebuilt', qc3, [(skin_name, skin['guid'])])
assert len(Model(compiled / 'vinson_rebuilt.rmdl', 's3').ui_panels()) == len(Model(vinson, 's3').ui_panels())

report = package(models, out / 'pak', 'r5c_jiggle', args.repak, 's3')
report['runtime_exclusions'] = []
probe = dict(attachment='MENU_CAMERA_FOCUS')
spec = {
    'charm_rebuilt': dict(jiggle_probe=dict(probe, expect_motion=True)),
    'charm_nojiggle': dict(jiggle_probe=dict(probe, expect_motion=False)),
    'charm_embedded': dict(jiggle_probe=dict(probe, expect_motion=True)),
    'vinson_rebuilt': {},
}
for m in report['models']:
    m.update(spec[Path(m['path']).stem])
report['collision_controls'] = [
    dict(path='mdl/props/charm/charm_nessy.rmdl', jiggle_probe=dict(probe, expect_motion=True)),
]
(out / 'pak/r5c_jiggle.report.json').write_text(json.dumps(report, indent=2))
print(json.dumps([m['path'] for m in report['models']], indent=2), report['outputs'])
