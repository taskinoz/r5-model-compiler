"""Import a matching early-Apex RRIG/RSEQ set into an editable QC animation include.

Place $include after your $body declarations and add the output directory with
the compiler's -path option. This exports skeleton/pose/IK definitions and supported
sequence metadata, SMD poses and native frame movement. It does not retarget a mesh
or copy opaque dependency graphs into a package.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mdl54 import Model, SequenceAsset, PROFILES
from decompile54 import export_skeleton, export_sequences


def import_animations(rig_path, sequence_paths, output, target, *, namespace='imported'):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,31}',namespace):
        raise ValueError('namespace must be a short QC identifier')
    rig_path=Path(rig_path).resolve()
    if rig_path.suffix.lower()!='.rrig': raise ValueError('expected a standalone .rrig')
    rig=Model(rig_path,target)
    if not rig.bones or rig.meshes or rig.materials or rig.sequences:
        raise ValueError('expected a skeleton-only standalone rig')
    if len(rig.bones)>256: raise ValueError('early-profile skeleton exceeds 256 bones')
    if any(b['proctype'] for b in rig.bones): raise ValueError('rig procedural bones are unsupported')
    if any(rig.get('i',off) for off in (0xFC,0x148,0x158,0x1A4,0x1E8)):
        raise ValueError('rig transitions, IK locks, dependencies, weight fixups or followers are unsupported')
    if any(not math.isfinite(x) for b in rig.bones for k in ('pos','rot','quat','scale','pose_to_bone') for x in b[k]):
        raise ValueError('non-finite rig skeleton')
    assets=[SequenceAsset(p,rig) for p in sequence_paths]
    if not assets: raise ValueError('at least one standalone sequence is required')
    labels=[a.name for a in assets]
    if len(set(n.casefold() for n in labels))!=len(labels): raise ValueError('duplicate sequence labels')
    for asset in assets:
        seq=asset.sequences[0]
        # Standalone assets count a reference descriptor's inline clip as one
        # blend. QC referencepose restores the studio form; --external-assets
        # promotes that same clip again when writing the new RSEQ.
        if len(seq['animations'])==1:
            desc=seq['animations'][0]
            if (asset.get('2i',0x44)==(1,1) and asset.string(desc+asset.get('i',desc+4))=='@'+seq['name']
                    and asset.get('i',desc+12)==0 and asset.get('i',desc+16)==1 and abs(asset.get('f',desc+8)-30)<1e-6
                    and not asset.sequence_metadata(seq)['events']):
                asset.sequences[0]=dict(seq,animations=[],reference_clip=desc)
        if not asset.sequences[0]['animations'] and asset.sequences[0]['reference_clip'] is None:
            raise ValueError('standalone reference sequence has no inline clip')
    inputs={str(rig_path):hashlib.sha256(rig.data).hexdigest()}
    inputs.update((str(a.path.resolve()),hashlib.sha256(a.data).hexdigest()) for a in assets)
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True)
    # Unsupported exports fail in staging, preserving an existing include and clips.
    with tempfile.TemporaryDirectory(prefix='.import54-',dir=output) as tmp:
        stage=Path(tmp)
        lines=['// Early-Apex animation include; use after $body and add this directory with -path.']
        lines+=export_skeleton(rig)
        for i,asset in enumerate(assets): lines+=export_sequences(asset,stage,namespace=f'{namespace}_{i}')
        (stage/'animations.qci').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in inputs.items()):
            raise ValueError('animation input changed during import')
        generated=list(stage.iterdir())
        for p in generated:
            if p.name!='animations.qci': shutil.copyfile(p,output/p.name)
        shutil.copyfile(stage/'animations.qci',output/'animations.qci')
    report=dict(target=target,scope='Editable skeleton and supported animations; no mesh retargeting or full dependency-graph import',
                inputs=inputs,labels=labels,namespace=namespace,
                outputs={p.name:hashlib.sha256((output/p.name).read_bytes()).hexdigest() for p in generated},
                tools={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                       (Path(__file__),Path(__file__).with_name('mdl54.py'),Path(__file__).with_name('decompile54.py'))})
    (output/'import54.report.json').write_text(json.dumps(report,indent=2)+'\n')
    return output/'animations.qci'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('rig');p.add_argument('sequences',nargs='+')
    p.add_argument('--target',required=True,choices=PROFILES);p.add_argument('--out',required=True)
    p.add_argument('--namespace',default='imported')
    a=p.parse_args()
    try: print(import_animations(a.rig,a.sequences,a.out,a.target,namespace=a.namespace))
    except (OSError,ValueError) as e: p.exit(1,str(e)+'\n')


if __name__=='__main__': main()
