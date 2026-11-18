"""Build and package the S3 animation-import test for R5R.

Writes test-output/r5r-import: the retail crypto_drone mesh (decompiled) with its
animations replaced by `import_anim54.py`'s include, made from the retail drone rig and
four of its standalone sequences (exported with RSX into
test-output/native-animation-import-s3), compiled with --external-assets and packaged.
The package report asks `ingame54.py --pose` to play each imported sequence on the
rebuild and on the installed retail drone, paused at fixed cycles, and to compare
attachments on the eye, both wings, the handle and the bottom frame: the imported
clips must pose the rebuild as retail's own clips pose the retail model.

usage: python tools/build_r5r_import_test.py --repak <repak.exe>
"""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repak', required=True)
args = parser.parse_args()
sys.path.insert(0, str(root / 'tools'))
from decompile54 import decompile  # noqa: E402
from import_anim54 import import_animations  # noqa: E402
from mdl54 import Model  # noqa: E402
from pack54 import package  # noqa: E402

LABELS = ['drone_activate', 'drone_active_idle', 'drone_EMP', 'drone_recall']
ATTACHMENTS = ['LENS', 'arm_l_fx', 'arm_r_fx', 'handle_t_fx', 'frame_b_fx']
out = root / 'test-output/r5r-import'
retail = root / 'test-output/s3-raw/mdl/crypto_drone/crypto_drone.rmdl'
rig = root / 'test-output/retail-rigs/animrig/crypto_drone/crypto_drone.rrig'
exported = root / 'test-output/native-animation-import-s3/animseq'
model = Model(retail, 's3')

# the retail sequences, by their asset names (RSX folders flatten the paths)
sequences = []
for label in LABELS:
    path = exported / label / (label + '.rseq')
    data = path.read_bytes()
    name = data[struct.unpack_from('<i', data, 4)[0]:].split(b'\0')[0].decode()
    assert name == 'animseq/props/crypto_drone/crypto_drone/%s.rseq' % label, name
    sequences.append(path)
include = import_animations(rig, sequences, out / 'animations', 's3', namespace='drone')

# the retail mesh, attachments and collision; skeleton and sequences from the include
qc = decompile(retail, out / 'sources', 's3')
lines = qc.read_text().split('\n')
start = next(i for i, l in enumerate(lines) if l.startswith('$weightlist') or l.startswith('$animation'))
end = next(i for i in range(start, len(lines)) if lines[i].startswith('$') and
           not re.match(r'\$(weightlist|animation|sequence)\b', lines[i]) and
           not any(lines[k].startswith('$sequence') for k in range(i, len(lines))))
host = [l for l in lines[:start] if not l.startswith('$definebone')]
host = [l.replace('$modelname "props/crypto_drone/crypto_drone.rmdl"', '$modelname "r5c_import/crypto_drone.rmdl"') for l in host]
host += ['$include "%s"' % str(include).replace('\\', '/')] + lines[end:]
assert '$modelname "r5c_import/crypto_drone.rmdl"' in host
qc_path = out / 'sources' / 'imported.qc'
qc_path.write_text('\n'.join(host))

compiled = out / 'compiled'
compiled.mkdir(parents=True, exist_ok=True)
target = compiled / 'crypto_drone_imported.rmdl'
cmd = [str(root / 'build/r5studiomdl.exe'), '--target', 's3', '--external-assets', '-quiet',
       '-o', str(target), '--packed-positions', '-path', str(include.parent)]
for mat in model.materials:
    name = mat['name']  # exact, as the decompiled $renamematerial keeps it
    cmd += ['--material-guid', name + '=%016x' % mat['guid'], '--material-type', name + '=sknp']
run = subprocess.run(cmd + [str(qc_path)], capture_output=True, text=True)
assert not run.returncode, run.stdout + run.stderr
rebuilt = Model(target, 's3')
# retail sequence assets are labelled with their asset paths; scripts also use the
# short names (e.g. Anim_PlayOnly( "drone_active_idle" )), which the pose test plays
assert [s['name'] for s in rebuilt.sequences] == ['ref'] + [
    'animseq/props/crypto_drone/crypto_drone/%s.rseq' % l for l in LABELS], [s['name'] for s in rebuilt.sequences]

report = package([target], out / 'pak', 'r5c_import', args.repak, 's3')
report['runtime_exclusions'] = []
spec = dict(group='drone', sequences=LABELS, attachments=ATTACHMENTS, cycles=[0, .2, .4, .6, .8, 1])
report['models'][0]['pose_compare'] = dict(spec)
report['collision_controls'] = [dict(path=model.name.replace('\\', '/'), pose_compare=dict(spec, reference=True))]
(out / 'pak/r5c_import.report.json').write_text(json.dumps(report, indent=2))
print(json.dumps([m['path'] for m in report['models']]), report['outputs'])
