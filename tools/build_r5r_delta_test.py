"""Build and package the S3 authored additive-clip (subtract) test for R5R.

Writes test-output/r5r-delta: two skinned three-bone models with the same skeleton
and attachments.
- full: its sequence "combo" plays a moving clip (lean.smd) directly.
- layered: its sequence "combo" plays a still base pose with an autolayer of
  "lean_delta", the same clip made additive with `subtract` against that base pose.
A delta adds to the pose it plays on, so layered combo must pose exactly as full
combo: the report asks `ingame54.py --pose` to compare their attachments at fixed
cycles. That checks the authored additive encoding (delta scale, rotation and position
deltas) and its playback through an autolayer in game; retail clips were checked
separately (build_r5r_import_test.py).
- ramp0 and main_ramp0 record where weight ramps (`weightramp`, the sequence table at
  0xC8/0xCC) do not act in R5R: a weight-0 ramp over the whole cycle on the layered
  delta (ramp0, against full) or on a directly played clip (main_ramp0, against
  main_plain) leaves the pose unchanged. The blend routine that reads the table
  (r5apex.exe+0x1D9F80) applies it only in another context, not reached here.

usage: python tools/build_r5r_delta_test.py --repak <repak.exe>
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--repak', required=True)
args = parser.parse_args()
sys.path.insert(0, str(root / 'tools'))
from decompile54 import write_smd  # noqa: E402
from mdl54 import Model  # noqa: E402
from pack54 import package  # noqa: E402

out = root / 'test-output/r5r-delta'
src = out / 'sources'
src.mkdir(parents=True, exist_ok=True)
compiled = out / 'compiled'
compiled.mkdir(exist_ok=True)

bones = [dict(name='root', parent=-1), dict(name='arm', parent=0), dict(name='hand', parent=1)]
FRAMES = 31
base_pose = [((0, 0, 0), (0, 0, 0), (1, 1, 1)), ((0, 0, 8), (0, 0, 0.3), (1, 1, 1)), ((12, 0, 0), (0, 0.2, 0), (1, 1, 1))]


def lean(s):
    # every animated channel moves: arm rotation about two axes, hand rotation about
    # two axes and a hand translation
    return [((0, 0, 0), (0, 0, 0), (1, 1, 1)),
            ((0, 0, 8), (0.4 * s, 0, 0.3 + 0.5 * s), (1, 1, 1)),
            ((12, 2 * s, 1 * s), (0, 0.2 + 0.6 * s, 0.3 * s), (1, 1, 1))]


def tri(bone, at):
    x, y, z = at
    return ('test/material', [((x, y, z), (0, 0, 1), (0, 0), [(bone, 1.0)]), ((x + 2, y, z), (0, 0, 1), (1, 0), [(bone, 1.0)]),
                              ((x, y + 2, z), (0, 0, 1), (0, 1), [(bone, 1.0)])])


mesh = [tri(0, (0, 0, 0)), tri(1, (0, 0, 8)), tri(2, (12, 0, 8))]
write_smd(src / 'base.smd', bones, [base_pose] * FRAMES, mesh)
write_smd(src / 'lean.smd', bones, [lean(f / (FRAMES - 1)) for f in range(FRAMES)])
ATTACHMENTS = ['tip', 'elbow', 'side']
common = ('$origin 0 0 0 -90\n$body body "base.smd"\n'
          '$attachment "tip" "hand" 6 1 0 rotate 0 0 0\n'
          '$attachment "elbow" "arm" 0 0 2 rotate 0 30 0\n'
          '$attachment "side" "hand" 0 3 2 rotate 10 0 20\n'
          '$animation base_a "base.smd"\n')
qcs = {
    'full': '$modelname "r5c_delta/full.rmdl"\n' + common +
            '$sequence "animseq/r5c_delta/full/combo.rseq" "lean.smd"\n',
    'layered': '$modelname "r5c_delta/layered.rmdl"\n' + common +
               '$animation lean_d "lean.smd" subtract base_a 0\n'
               '$sequence "animseq/r5c_delta/layered/lean_delta.rseq" lean_d\n'
               '$sequence "animseq/r5c_delta/layered/combo.rseq" { base_a autolayer "animseq/r5c_delta/layered/lean_delta.rseq" }\n',
    # weight ramps (the sequence table at 0xC8/0xCC): weight 0 over the whole cycle, on
    # the layered delta and on a directly played clip; R5R leaves both poses unchanged
    'ramp0': '$modelname "r5c_delta/ramp0.rmdl"\n' + common +
             '$animation lean_d "lean.smd" subtract base_a 0\n'
             '$sequence "animseq/r5c_delta/ramp0/lean_delta.rseq" { lean_d weightramp "" 0 0 0 1 1 }\n'
             '$sequence "animseq/r5c_delta/ramp0/combo.rseq" { base_a autolayer "animseq/r5c_delta/ramp0/lean_delta.rseq" }\n',
    'main_plain': '$modelname "r5c_delta/main_plain.rmdl"\n' + common +
                  '$sequence "animseq/r5c_delta/main_plain/combo.rseq" "lean.smd"\n',
    'main_ramp0': '$modelname "r5c_delta/main_ramp0.rmdl"\n' + common +
                  '$sequence "animseq/r5c_delta/main_ramp0/combo.rseq" { "lean.smd" weightramp "" 0 0 0 1 1 }\n',
}
skin = Model(next((root / 'test-output/s3-raw').rglob('pilot_light_wraith.rmdl')), 's3').materials[0]
skin_name = skin['name'].replace(chr(92), '/')
models = []
for name, text in qcs.items():
    qc = src / (name + '.qc')
    qc.write_text(text + '$renamematerial "test/material" "%s"\n' % skin_name)
    model = compiled / (name + '.rmdl')
    cmd = [str(root / 'build/r5studiomdl.exe'), '--target', 's3', '--external-assets', '-quiet', '-o', str(model),
           '--packed-positions', '--material-guid', '%s=%016x' % (skin_name, skin['guid']),
           '--material-type', skin_name + '=sknp', str(qc)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert not r.returncode, r.stdout + r.stderr
    models.append(str(model))

report = package(models, out / 'pak', 'r5c_delta', args.repak, 's3')
report['runtime_exclusions'] = []
spec = dict(group='delta', sequences=['combo'], attachments=ATTACHMENTS, cycles=[0, .25, .5, .75, 1])
for k, (name, group, reference) in enumerate([('full', 'delta', True), ('layered', 'delta', False),
                                               ('ramp0', 'delta', False),
                                               ('main_plain', 'main', True), ('main_ramp0', 'main', False)]):
    assert report['models'][k]['path'] == 'mdl/r5c_delta/%s.rmdl' % name, report['models'][k]['path']
    report['models'][k]['pose_compare'] = dict(spec, group=group, reference=reference)
(out / 'pak/r5c_delta.report.json').write_text(json.dumps(report, indent=2))
print(json.dumps([m['path'] for m in report['models']]), report['outputs'])
