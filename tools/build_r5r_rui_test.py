"""Build and package the S3 RUI viewmodel test for R5R.

Writes test-output/r5r-rui: the retail ptpov_vinson (Flatline viewmodel, 20 RUI panels)
decompiled and rebuilt, and the same rebuild without its $uipanel blocks as a control.
Run `ingame54.py --weapon mp_weapon_vinson --viewmodel <model path>` with each (and
once without --viewmodel for the retail viewmodel): the weapon's script draws its
UiData panels ("vinson_rui_upper", "vinson_rui_lower") on the panel meshes the
viewmodel names, so they must appear on the rebuild as on retail and not on the
control. Needs the installed S3 corpus in test-output/s3-raw.

usage: python tools/build_r5r_rui_test.py --repak <repak.exe>
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

out = root / 'test-output/r5r-rui'
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


vinson = next(corpus.rglob('ptpov_vinson.rmdl'))
retail = Model(vinson, 's3')
qc = decompile(vinson, src / 'vinson_rebuilt', 's3')
text = qc.read_text()
old = '$modelname "' + retail.name.replace(chr(92), '/')[4:] + '"'
assert old in text, old
text = text.replace(old, '$modelname "r5c_rui/vinson_rebuilt.rmdl"')
assert text.count('$uipanel') == len(retail.ui_panels()) and ' ccw\n' in text and 'maskcount' not in text
# every material slot bound to one installed skinned material (as in the jiggle test)
skin = Model(next(corpus.rglob('pilot_light_wraith.rmdl')), 's3').materials[0]
skin_name = skin['name'].replace(chr(92), '/')
text += ''.join('$renamematerial "%s" "%s"\n' % (m['name'], skin_name) for m in retail.materials)
qc.write_text(text)
compile_qc('vinson_rebuilt', qc, [(skin_name, skin['guid'])])
rebuilt = Model(compiled / 'vinson_rebuilt.rmdl', 's3')
assert rebuilt.ui_panels() == [dict(p) for p in retail.ui_panels()]
# control: no $uipanel blocks (each ends at a column-0 brace)
control = re.sub(r'(?ms)^\$uipanel .*?^\}\n', '', text.replace('r5c_rui/vinson_rebuilt', 'r5c_rui/vinson_noui'))
assert '$uipanel' not in control
qc2 = qc.with_name('vinson_noui.qc')
qc2.write_text(control)
compile_qc('vinson_noui', qc2, [(skin_name, skin['guid'])])
assert not Model(compiled / 'vinson_noui.rmdl', 's3').ui_panels()

report = package(models, out / 'pak', 'r5c_rui', args.repak, 's3')
report['runtime_exclusions'] = []
(out / 'pak/r5c_rui.report.json').write_text(json.dumps(report, indent=2))
print(json.dumps([m['path'] for m in report['models']], indent=2), report['outputs'])
