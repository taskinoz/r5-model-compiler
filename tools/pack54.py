"""Build an S3 R5R RPak from r5studiomdl --external-assets output using RePak.

RePak is a separate user-provided program. No game or third-party binaries are bundled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mdl54 import Model, SequenceAsset


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def asset_path(name):
    name=name.replace('\\','/')
    parts=name.split('/')
    if not parts or name.startswith('/') or any(p in ('..','.','') for p in parts) or ':' in name or any(ord(c)<32 for c in name):
        raise ValueError('unsafe model asset path')
    if not name.startswith('mdl/'): name='mdl/'+name
    if not name.endswith('.rmdl'): raise ValueError('expected .rmdl model name')
    return name


def package(models, output, name, repak, target):
    if target!='s3': raise ValueError('RPak packaging currently requires the surveyed s3 / R5R profile')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',name): raise ValueError('invalid pak name')
    models=list(models)
    if not models: raise ValueError('at least one model is required')
    output=Path(output).resolve(); sources=output/'sources'; sources.mkdir(parents=True,exist_ok=True)
    files=[]; inputs={}; outputs=[]; names=set()
    def copy(source,dest):
        source=Path(source).resolve(); dest=sources/dest
        dest.parent.mkdir(parents=True,exist_ok=True)
        if source!=dest: shutil.copyfile(source,dest)
        inputs[str(source)]=sha(source)
    for path in models:
        path=Path(path).resolve(); m=Model(path,target)
        if any(not mat['guid'] for mat in m.materials):
            raise ValueError(f'{path}: every material needs an existing nonzero GUID (--material-guid)')
        if len(m.sequences)!=1 or m.sequences[0]['animations'] or m.sequences[0]['name']!='ref':
            raise ValueError(f'{path}: compile with --external-assets before packaging')
        marker=path.with_suffix('.assetset'); lines=marker.read_text().splitlines()
        if len(lines)!=3 or lines[:2]!=['R5AS1',target]: raise ValueError('asset set target/magic mismatch')
        count=int(lines[2])
        if not 0<=count<=32767: raise ValueError('invalid asset set sequence count')
        native=asset_path(m.name)
        if native.casefold() in names: raise ValueError('duplicate model asset path')
        names.add(native.casefold()); base=native[4:-5]; rigpath=f'animrig/{base}.rrig'
        rigfile=path.with_suffix('.rrig'); rig=Model(rigfile,target)
        if rig.bones!=m.bones: raise ValueError('model/rig bone layout mismatch')
        copy(path,native); copy(path.with_suffix('.vg'),native[:-5]+'.vg'); copy(rigfile,rigpath)
        sequences=[]; labels=[]
        for i in range(count):
            source=path.with_suffix(f'.seq{i}.rseq'); seq=SequenceAsset(source,rig)
            dest=f'animseq/{base}/seq{i}.rseq'; copy(source,dest); sequences.append(dest); labels.append(seq.name)
        files.append(dict(_type='arig',_path=rigpath,**{'$sequences':sequences}))
        files.append(dict(_type='mdl_',_path=native,**{'$animrigs':[rigpath]}))
        inputs[str(marker)]=sha(marker)
        outputs.append(dict(path=native,rig=rigpath,sequences=sequences,labels=labels))
    build=dict(version=8,name=name,assetsDir=str(sources),outputDir=str(output),
               streamFileMandatory=f'paks/Win64/{name}.starpak',keepClientOnly=True,keepServerOnly=True,files=files)
    config=output/(name+'.json'); config.write_text(json.dumps(build,indent=2)+'\n')
    # Build in a fresh directory: an old successful package cannot mask a failed run.
    with tempfile.TemporaryDirectory(prefix='.repak-',dir=output) as scratch:
        build['outputDir']=scratch
        transient=Path(scratch)/(name+'.json')
        transient.write_text(json.dumps(build,indent=2)+'\n')
        run=subprocess.run([str(Path(repak).resolve()),str(transient)],cwd=output,capture_output=True,text=True,timeout=180)
        (output/(name+'.repak.log')).write_text(run.stdout+run.stderr)
        if run.returncode: raise ValueError(f'RePak failed ({run.returncode}): {run.stdout[-2000:]}{run.stderr[-2000:]}')
        artifacts=[Path(scratch)/(name+suffix) for suffix in ('.rpak','.starpak')]
        if not all(p.is_file() and p.stat().st_size for p in artifacts):
            raise ValueError('RePak did not produce RPak and mandatory stream')
        for artifact in artifacts: shutil.copy2(artifact,output/artifact.name)
    pak=output/(name+'.rpak'); stream=output/(name+'.starpak')
    if any(sha(p)!=h for p,h in inputs.items()): raise ValueError('asset input changed during packaging')
    report=dict(target=target,scope='RePak build; runtime compatibility requires an in-game test',models=outputs,
                inputs=inputs,repak_sha256=sha(repak),build_map_sha256=sha(config),
                outputs={str(p):sha(p) for p in (pak,stream)},tools={p.name:sha(p) for p in (Path(__file__),Path(__file__).with_name('mdl54.py'))})
    (output/(name+'.report.json')).write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('models',nargs='+')
    p.add_argument('--target',required=True,choices=['s3']); p.add_argument('--repak',required=True)
    p.add_argument('--out',required=True); p.add_argument('--name',default='r5c_models')
    a=p.parse_args()
    try:
        report=package(a.models,a.out,a.name,a.repak,a.target)
        print(json.dumps(report,indent=2))
    except (OSError,ValueError,subprocess.SubprocessError) as e: p.exit(1,str(e)+'\n')

if __name__=='__main__': main()
