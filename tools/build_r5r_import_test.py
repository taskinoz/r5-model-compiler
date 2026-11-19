"""Build and package an S3 animation-import test for R5R.

Writes test-output/r5r-import (--case drone) or test-output/r5r-import-<case>: a
retail mesh (decompiled) whose animations are replaced by `import_anim54.py`'s include,
made from the retail rig and its standalone sequences (exported with RSX into
test-output/native-animation-import-s3), compiled with --external-assets and packaged.
The package report asks `ingame54.py --pose` to play each imported sequence on the
rebuild and on the installed retail model, paused at fixed cycles, and to compare
attachments: the imported clips must pose the rebuild as retail's own clips pose the
retail model.

Cases:
- drone: crypto_drone, four sequences, attachments on the eye, wings, handle and frame.
- mastiff: ptpov_mastiff (the Mastiff viewmodel), every sequence its rig lists: eight
  carry autolayers naming another of its sequences (driven by sprintfrac, so every
  sequence is sampled at sprintfrac 0 and 1), 19 transition nodes and 14 additive
  (delta) clips; attachments on the weapon, both hands, the camera and the shell.

usage: python tools/build_r5r_import_test.py --repak <repak.exe> [--case drone|mastiff]
"""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--repak', required=True)
parser.add_argument('--case', choices=('drone', 'mastiff', 'b3wing'), default='drone')
parser.add_argument('--clear-flag40', action='store_true',
                    help='remove flag 0x40 from every imported clip and sequence (to test what it does in game)')
args = parser.parse_args()
sys.path.insert(0, str(root / 'tools'))
from decompile54 import decompile  # noqa: E402
from import_anim54 import import_animations  # noqa: E402
from mdl54 import Model, asset_guid  # noqa: E402
from pack54 import package  # noqa: E402

corpus = root / 'test-output/s3-raw'
exported = root / 'test-output/native-animation-import-s3/animseq'
if args.case == 'drone':
    out = root / 'test-output/r5r-import'
    retail = corpus / 'mdl/crypto_drone/crypto_drone.rmdl'
    rig = root / 'test-output/retail-rigs/animrig/crypto_drone/crypto_drone.rrig'
    asset_dir = 'animseq/props/crypto_drone/crypto_drone'
    LABELS = ['drone_activate', 'drone_active_idle', 'drone_EMP', 'drone_recall']
    ATTACHMENTS = ['LENS', 'arm_l_fx', 'arm_r_fx', 'handle_t_fx', 'frame_b_fx']
    spec_extra = dict(cycles=[0, .2, .4, .6, .8, 1])
    group = 'drone'
elif args.case == 'b3wing':
    # the B3 Wingman world model's rig: five sequences, among them the execution clip
    # with flag 0x40 (206 retail S3 sequences carry it; the engine's use is unknown)
    out = root / 'test-output/r5r-import-b3wing'
    retail = corpus / 'mdl/w_b3wing/w_b3wing.rmdl'
    rig = root / 'test-output/retail-rigs/animrig/w_b3wing/w_b3wing.rrig'
    asset_dir = 'animseq/weapons/b3wing/w_b3wing'
    LABELS = None
    ATTACHMENTS = ['muzzle_flash', 'shell', 'l_hand_ik', 'r_hand_ik', 'flashlight']
    spec_extra = dict(cycles=[0, .2, .4, .6, .8, 1])
    group = 'b3wing'
else:
    out = root / 'test-output/r5r-import-mastiff'
    retail = corpus / 'mdl/ptpov_mastiff/ptpov_mastiff.rmdl'
    rig = root / 'test-output/retail-rigs/animrig/ptpov_mastiff/ptpov_mastiff.rrig'
    asset_dir = 'animseq/weapons/mastiff_stgn/ptpov_mastiff'
    LABELS = None  # every sequence the rig lists
    ATTACHMENTS = ['muzzle_flash', 'shell', 'L_HAND', 'R_HAND', 'CAMERA', 'def_release']
    spec_extra = dict(cycles=[0, .25, .5, .75, 1], pose_sets=[{}, {'sprintfrac': 1.0}])
    group = 'mastiff'
model = Model(retail, 's3')
if args.clear_flag40:
    out = out.with_name(out.name + '-no40')


def label_of(path):
    data = path.read_bytes()
    return data[struct.unpack_from('<i', data, 4)[0]:].split(b'\0')[0].decode()


# the retail sequences, by their asset names (RSX folders flatten the paths)
if LABELS is None:
    # the rig's own .rson lists its sequences by asset GUID
    listed = [int(w.strip(), 16) for w in rig.with_suffix('.rson').read_text().splitlines()
              if w.strip() and all(c in '0123456789abcdefABCDEF' for c in w.strip())]
    # (retail keeps them under animseq/ and animseq_derived/)
    by_guid = {}
    for p in exported.rglob('*.rseq'):
        name = label_of(p); by_guid[asset_guid(name)] = (p, name)
    # (the rig also lists one sequence of another rig's folder, whose short name repeats)
    own = (asset_dir + '/', asset_dir.replace('animseq/', 'animseq_derived/', 1) + '/')
    pairs = sorted((by_guid[g] for g in set(listed) if g in by_guid and by_guid[g][1].lower().startswith(own)), key=lambda x: x[1])
    assert pairs, 'no exported sequences for the rig'
    LABELS = [name.rsplit('/', 1)[-1][:-5] for _, name in pairs]
    assert len(set(l.lower() for l in LABELS)) == len(LABELS), [n for _, n in pairs]
    sequences = [p for p, _ in pairs]
    asset_names = [name for _, name in pairs]
else:
    sequences = []
    for label in LABELS:
        path = exported / label / (label + '.rseq')
        assert label_of(path) == '%s/%s.rseq' % (asset_dir, label), label_of(path)
        sequences.append(path)
    asset_names = ['%s/%s.rseq' % (asset_dir, l) for l in LABELS]
include = import_animations(rig, sequences, out / 'animations', 's3', namespace=group)
if args.clear_flag40:
    def clear40(m):
        word, value = m.group(1), int(m.group(2), 0)
        return '%s %s' % (word, hex(value & ~0x40) if m.group(2).startswith('0x') else value & ~0x40)
    text = include.read_text()
    cleared = re.sub(r'\b(animflags|seqflags) (0x[0-9a-fA-F]+|\d+)', clear40, text)
    assert cleared != text, 'no flag 0x40 to clear'
    include.write_text(cleared)

# the retail mesh, attachments and collision; skeleton and sequences from the include
qc = decompile(retail, out / 'sources', 's3')
lines = qc.read_text().split('\n')
start = next(i for i, l in enumerate(lines) if l.startswith('$weightlist') or l.startswith('$animation') or l.startswith('$sequence'))
end = next((i for i in range(start, len(lines)) if lines[i].startswith('$') and
            not re.match(r'\$(weightlist|animation|sequence)\b', lines[i]) and
            not any(lines[k].startswith('$sequence') for k in range(i, len(lines)))), len(lines))
retail_name = '$modelname "' + model.name.replace('\\', '/')[4:] + '"'
new_name = '$modelname "r5c_import/%s.rmdl"' % retail.stem
if [b['name'] for b in model.bones] == [b['name'] for b in Model(rig, 's3').bones]:
    # the rig is the model's skeleton: the include defines it
    host = [l.replace(retail_name, new_name) for l in lines[:start] if not l.startswith('$definebone')]
else:
    # retail models often differ from their rig (the Mastiff viewmodel adds optic and
    # muzzle bones, the rig two magazine/screen bones); the game maps rig bones onto
    # the model by name. As a user would, keep the model's skeleton and take only the
    # rig's sequences and metadata: clips are re-encoded for the model's bones.
    rig_metadata = re.compile(r'\$(definebone|poseparameter|node|localnodeunk|ikchain)\b')
    text = include.read_text().split('\n')
    # weight lists name every rig bone; drop the rig's bones the model lacks
    names = {b['name'] for b in model.bones}
    kept = []; in_weights = False
    for l in text:
        if l.startswith('$weightlist'): in_weights = True
        elif l.startswith('}'): in_weights = False
        elif in_weights and re.fullmatch(r'\s+"([^"]+)" [-+0-9.eE]+', l) and l.split('"')[1] not in names: continue
        if not l.startswith('$definebone'): kept.append(l)
    include.write_text('\n'.join(kept))
    host = [l.replace(retail_name, new_name) for l in lines[:start]
            if l.startswith('$definebone') or not rig_metadata.match(l)]
host += ['$include "%s"' % str(include).replace('\\', '/')] + lines[end:]
assert new_name in host
qc_path = out / 'sources' / 'imported.qc'
qc_path.write_text('\n'.join(host))

compiled = out / 'compiled'
compiled.mkdir(parents=True, exist_ok=True)
target = compiled / (retail.stem + '_imported.rmdl')
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
# (the model keeps only "ref", as retail's; the sequence assets carry the rest)
assert [s['name'] for s in rebuilt.sequences] == ['ref']
built = [label_of(target.with_suffix('.seq%d.rseq' % i)) for i in range(len(asset_names) + 1)]
assert built == ['ref'] + asset_names, built

report = package([target], out / 'pak', 'r5c_import', args.repak, 's3')
report['runtime_exclusions'] = []
spec = dict(group=group, sequences=LABELS, attachments=ATTACHMENTS, **spec_extra)
report['models'][0]['pose_compare'] = dict(spec)
report['collision_controls'] = [dict(path=model.name.replace('\\', '/'), pose_compare=dict(spec, reference=True))]
(out / 'pak/r5c_import.report.json').write_text(json.dumps(report, indent=2))
print(json.dumps([m['path'] for m in report['models']]), len(LABELS), report['outputs'])
